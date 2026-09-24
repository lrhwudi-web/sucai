from __future__ import annotations

import json
import os
import threading
from collections import deque
from pathlib import Path
from typing import Callable, Iterator

from .logic import FOLDER_MIME, classify_asset, infer_drive_fields, is_ignored_file, is_included_drive_collection, is_internal_path

DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
DRIVE_WRITE_SCOPE = "https://www.googleapis.com/auth/drive"
THUMBNAIL_FETCH_TIMEOUT = max(2.0, min(float(os.getenv("GOOGLE_THUMBNAIL_TIMEOUT", "8")), 30.0))
_SESSION_CACHE = threading.local()


def _thread_sessions() -> dict[tuple, object]:
    sessions = getattr(_SESSION_CACHE, "sessions", None)
    if sessions is None:
        sessions = {}
        _SESSION_CACHE.sessions = sessions
    return sessions


def raise_for_google_error(response) -> None:
    if response.ok:
        return
    try:
        message = response.json()["error"]["message"]
    except Exception:
        message = response.text
    raise RuntimeError(f"Google Drive API error {response.status_code}: {message}")


def service(scopes: list[str] | None = None):
    from google.oauth2.credentials import Credentials
    from google.oauth2 import service_account
    from google.auth.transport.requests import AuthorizedSession, Request
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    scopes = scopes or [DRIVE_READONLY_SCOPE]
    key_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
    token_file = os.getenv("GOOGLE_OAUTH_TOKEN_FILE")
    proxy = os.getenv("GOOGLE_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
    cache_key = (tuple(sorted(scopes)), key_file or "", token_file or "", proxy or "")
    sessions = _thread_sessions()
    cached = sessions.get(cache_key)
    if cached is not None:
        return cached
    if key_file:
        creds = service_account.Credentials.from_service_account_file(key_file, scopes=scopes)
    elif token_file:
        token_data = json.loads(Path(token_file).read_text(encoding="utf-8"))
        token_scopes = token_data.get("scopes") or []
        if isinstance(token_scopes, str):
            token_scopes = token_scopes.split()
        if DRIVE_WRITE_SCOPE in scopes and token_scopes and DRIVE_WRITE_SCOPE not in token_scopes:
            raise RuntimeError(
                "Google OAuth 令牌只有只读权限，不能入库。请使用 "
                "scripts/create_oauth_token.py --write 重新授权。"
            )
        creds = Credentials.from_authorized_user_file(token_file)
    else:
        raise RuntimeError("Set GOOGLE_OAUTH_TOKEN_FILE or GOOGLE_SERVICE_ACCOUNT_FILE")
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=0.4,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
    auth_session = requests.Session()
    auth_session.mount("http://", adapter)
    auth_session.mount("https://", adapter)
    if proxy:
        auth_session.proxies.update({"http": proxy, "https": proxy})
    session = AuthorizedSession(creds, auth_request=Request(session=auth_session))
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    if proxy:
        session.proxies.update(auth_session.proxies)
    sessions[cache_key] = session
    return session


def quote_query_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def list_children(svc, folder_id: str, drive_id: str = "") -> Iterator[dict]:
    page_token = None
    while True:
        params = {
            "q": f"'{folder_id}' in parents and trashed = false",
            "fields": "nextPageToken, files(id,name,mimeType,size,modifiedTime,thumbnailLink,md5Checksum,sha1Checksum,sha256Checksum)",
            "pageSize": 1000,
            "pageToken": page_token,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if drive_id:
            params.update({"corpora": "drive", "driveId": drive_id})
        response = svc.get(
            "https://www.googleapis.com/drive/v3/files",
            params=params,
            timeout=60,
        )
        raise_for_google_error(response)
        payload = response.json()
        yield from payload.get("files", [])
        page_token = payload.get("nextPageToken")
        if not page_token:
            break


def find_child(svc, parent_id: str, name: str, folder: bool) -> dict | None:
    mime_clause = f"mimeType = '{FOLDER_MIME}'" if folder else f"mimeType != '{FOLDER_MIME}'"
    response = svc.get(
        "https://www.googleapis.com/drive/v3/files",
        params={
            "q": f"'{quote_query_value(parent_id)}' in parents and name = '{quote_query_value(name)}' and {mime_clause} and trashed = false",
            "fields": "files(id,name,mimeType,size,modifiedTime,appProperties)",
            "pageSize": 1,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        },
        timeout=60,
    )
    raise_for_google_error(response)
    files = response.json().get("files", [])
    return files[0] if files else None


def create_folder(svc, parent_id: str, name: str) -> dict:
    response = svc.post(
        "https://www.googleapis.com/drive/v3/files",
        params={"supportsAllDrives": "true", "fields": "id,name"},
        json={"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]},
        timeout=60,
    )
    raise_for_google_error(response)
    return response.json()


def file_metadata(svc, file_id: str) -> dict:
    response = svc.get(
        f"https://www.googleapis.com/drive/v3/files/{file_id}",
        params={
            "fields": "id,name,mimeType,parents,webViewLink,size,md5Checksum,sha1Checksum,sha256Checksum",
            "supportsAllDrives": "true",
        },
        timeout=60,
    )
    raise_for_google_error(response)
    return response.json()


def file_is_within_folder(
    svc,
    file_id: str,
    ancestor_folder_id: str,
    *,
    metadata: dict | None = None,
    max_depth: int = 32,
) -> bool:
    """Return whether a live Drive file still belongs to the inbox tree."""
    if not ancestor_folder_id:
        return True
    frontier = [file_id]
    seen: set[str] = set()
    first_metadata = metadata
    for _depth in range(max_depth):
        next_frontier: list[str] = []
        for current_id in frontier:
            if current_id == ancestor_folder_id:
                return True
            if current_id in seen:
                continue
            seen.add(current_id)
            current = first_metadata if first_metadata is not None and current_id == file_id else file_metadata(svc, current_id)
            for parent_id in current.get("parents") or []:
                if parent_id == ancestor_folder_id:
                    return True
                if parent_id not in seen:
                    next_frontier.append(parent_id)
        first_metadata = None
        if not next_frontier:
            return False
        frontier = next_frontier
    return False


def find_sku_folder(svc, asset_file_id: str, sku: str, max_depth: int = 12) -> dict:
    normalized_sku = sku.strip().upper()
    current = file_metadata(svc, asset_file_id)
    for _depth in range(max_depth):
        parents = current.get("parents") or []
        if not parents:
            break
        current = file_metadata(svc, parents[0])
        name = str(current.get("name") or "").strip().upper()
        if current.get("mimeType") == FOLDER_MIME and (
            name == normalized_sku
            or name.startswith(f"{normalized_sku} ")
            or name.startswith(f"{normalized_sku}-")
            or name.startswith(f"{normalized_sku}_")
        ):
            return current
    raise RuntimeError(f"Could not locate the Google Drive folder for SKU {normalized_sku}")


def copy_file(svc, file_id: str, parent_id: str, name: str) -> dict:
    response = svc.post(
        f"https://www.googleapis.com/drive/v3/files/{file_id}/copy",
        params={"supportsAllDrives": "true", "fields": "id,name,mimeType,parents"},
        json={"name": name, "parents": [parent_id]},
        timeout=300,
    )
    raise_for_google_error(response)
    return response.json()


def create_public_reader_permission(svc, folder_id: str) -> None:
    existing = svc.get(
        f"https://www.googleapis.com/drive/v3/files/{folder_id}/permissions",
        params={"supportsAllDrives": "true", "fields": "permissions(id,type,role)"},
        timeout=60,
    )
    raise_for_google_error(existing)
    if any(
        permission.get("type") == "anyone" and permission.get("role") in {"reader", "commenter", "writer"}
        for permission in existing.json().get("permissions", [])
    ):
        return
    response = svc.post(
        f"https://www.googleapis.com/drive/v3/files/{folder_id}/permissions",
        params={"supportsAllDrives": "true", "sendNotificationEmail": "false", "fields": "id"},
        json={"type": "anyone", "role": "reader", "allowFileDiscovery": False},
        timeout=60,
    )
    raise_for_google_error(response)


def trash_file(svc, file_id: str) -> None:
    response = svc.patch(
        f"https://www.googleapis.com/drive/v3/files/{file_id}",
        params={"supportsAllDrives": "true", "fields": "id,trashed"},
        json={"trashed": True},
        timeout=60,
    )
    raise_for_google_error(response)


def delete_export_folder(svc, folder_id: str, expected_parent_id: str) -> bool:
    if not folder_id or folder_id == expected_parent_id:
        raise RuntimeError("Refusing to delete an invalid Drive export folder")
    metadata_response = svc.get(
        f"https://www.googleapis.com/drive/v3/files/{folder_id}",
        params={"fields": "id,name,mimeType,parents,trashed", "supportsAllDrives": "true"},
        timeout=60,
    )
    if metadata_response.status_code == 404:
        return False
    raise_for_google_error(metadata_response)
    metadata = metadata_response.json()
    if metadata.get("mimeType") != FOLDER_MIME or expected_parent_id not in (metadata.get("parents") or []):
        raise RuntimeError("Refusing to delete a Drive folder outside the configured client export directory")
    response = svc.delete(
        f"https://www.googleapis.com/drive/v3/files/{folder_id}",
        params={"supportsAllDrives": "true"},
        timeout=300,
    )
    if response.status_code == 404:
        return False
    raise_for_google_error(response)
    return True


def copy_accessible_folder(
    svc,
    source_folder_id: str,
    destination_parent_id: str,
    allowed_file_ids: set[str],
    progress: Callable[[int, int], None] | None = None,
) -> dict:
    source = file_metadata(svc, source_folder_id)
    children_by_folder: dict[str, list[dict]] = {}
    folders = deque([source_folder_id])
    visited: set[str] = set()
    discovered_files: set[str] = set()

    while folders:
        folder_id = folders.popleft()
        if folder_id in visited:
            continue
        visited.add(folder_id)
        children = list(list_children(svc, folder_id))
        children_by_folder[folder_id] = children
        for item in children:
            if item.get("mimeType") == FOLDER_MIME:
                folders.append(item["id"])
            else:
                discovered_files.add(item["id"])

    matched_file_ids = allowed_file_ids & discovered_files
    if not matched_file_ids:
        raise RuntimeError("No customer-visible indexed files were found in the SKU folder")
    missing_file_ids = allowed_file_ids - matched_file_ids
    if missing_file_ids:
        raise RuntimeError(
            f"{len(missing_file_ids)} customer-visible indexed files are outside the detected SKU folder"
        )

    relevant_cache: dict[str, bool] = {}

    def has_allowed_files(folder_id: str) -> bool:
        if folder_id in relevant_cache:
            return relevant_cache[folder_id]
        relevant = False
        for item in children_by_folder.get(folder_id, []):
            if item.get("mimeType") == FOLDER_MIME:
                relevant = has_allowed_files(item["id"]) or relevant
            elif item["id"] in matched_file_ids:
                relevant = True
        relevant_cache[folder_id] = relevant
        return relevant

    has_allowed_files(source_folder_id)
    root_copy = create_folder(svc, destination_parent_id, source["name"])
    completed = 0
    total = len(matched_file_ids)

    def copy_children(source_id: str, destination_id: str) -> None:
        nonlocal completed
        for item in children_by_folder.get(source_id, []):
            if item.get("mimeType") == FOLDER_MIME:
                if not has_allowed_files(item["id"]):
                    continue
                child_copy = create_folder(svc, destination_id, item["name"])
                copy_children(item["id"], child_copy["id"])
                continue
            if item["id"] not in matched_file_ids:
                continue
            copy_file(svc, item["id"], destination_id, item["name"])
            completed += 1
            if progress:
                progress(completed, total)

    try:
        copy_children(source_folder_id, root_copy["id"])
        create_public_reader_permission(svc, root_copy["id"])
    except Exception:
        try:
            trash_file(svc, root_copy["id"])
        except Exception:
            pass
        raise

    return {
        "folder_id": root_copy["id"],
        "folder_name": root_copy.get("name") or source["name"],
        "folder_url": f"https://drive.google.com/drive/folders/{root_copy['id']}",
        "file_count": total,
    }


def ensure_folder_path(svc, root_id: str, parts: list[str]) -> str:
    folder_id = root_id
    for part in parts:
        found = find_child(svc, folder_id, part, folder=True)
        folder_id = found["id"] if found else create_folder(svc, folder_id, part)["id"]
    return folder_id


def move_file(svc, file_id: str, parent_id: str, name: str) -> dict:
    current = svc.get(
        f"https://www.googleapis.com/drive/v3/files/{file_id}",
        params={"fields": "parents", "supportsAllDrives": "true"},
        timeout=60,
    )
    raise_for_google_error(current)
    response = svc.patch(
        f"https://www.googleapis.com/drive/v3/files/{file_id}",
        params={
            "addParents": parent_id,
            "removeParents": ",".join(current.json().get("parents", [])),
            "supportsAllDrives": "true",
            "fields": "id,name,parents",
        },
        json={"name": name},
        timeout=60,
    )
    raise_for_google_error(response)
    return response.json()


class _ProgressReader:
    def __init__(self, handle, total: int, callback: Callable[[int, int], None]):
        self.handle = handle
        self.total = total
        self.completed = 0
        self.callback = callback

    def __len__(self) -> int:
        return self.total

    def read(self, size: int = -1):
        chunk = self.handle.read(size)
        if chunk:
            self.completed += len(chunk)
            self.callback(min(self.completed, self.total), self.total)
        return chunk

    def __getattr__(self, name: str):
        if name.startswith("__"):
            raise AttributeError(name)
        return getattr(self.handle, name)


def upload_file(
    svc,
    local_path: Path,
    parent_id: str,
    name: str,
    mime_type: str,
    app_properties: dict[str, str],
    file_id: str | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> dict:
    size = local_path.stat().st_size
    metadata = {"name": name, "mimeType": mime_type, "appProperties": app_properties}
    if not file_id:
        metadata["parents"] = [parent_id]
    url = "https://www.googleapis.com/upload/drive/v3/files"
    if file_id:
        url = f"{url}/{file_id}"
    response = svc.request(
        "PATCH" if file_id else "POST",
        url,
        params={"uploadType": "resumable", "supportsAllDrives": "true", "fields": "id,name,size,modifiedTime,appProperties"},
        json=metadata,
        headers={
            "X-Upload-Content-Type": mime_type,
            "X-Upload-Content-Length": str(size),
        },
        timeout=60,
    )
    raise_for_google_error(response)
    with local_path.open("rb") as handle:
        body = _ProgressReader(handle, size, progress) if progress else handle
        uploaded = svc.put(
            response.headers["Location"],
            data=body,
            headers={"Content-Type": mime_type, "Content-Length": str(size)},
            timeout=300,
        )
    raise_for_google_error(uploaded)
    return uploaded.json()


def scan_drive(root_id: str) -> list[dict]:
    svc = service()
    found: list[dict] = []
    drive_id = root_id if root_id.startswith("0A") else ""
    folders = deque([(root_id, "")])
    while folders:
        folder_id, base_path = folders.popleft()
        for item in list_children(svc, folder_id, drive_id):
            if is_ignored_file(item["name"]):
                continue
            if not base_path and not is_included_drive_collection(item["name"]):
                continue
            path = f"{base_path}/{item['name']}".strip("/")
            if item["mimeType"] == FOLDER_MIME:
                folders.append((item["id"], path))
                continue
            brand, category, other, sku = infer_drive_fields(path)
            found.append(
                {
                    "id": item["id"],
                    "name": item["name"],
                    "mime_type": item["mimeType"],
                    "size": int(item.get("size") or 0),
                    "modified_time": item.get("modifiedTime"),
                    "thumbnail_link": item.get("thumbnailLink", ""),
                    "path": path,
                    "sku": sku,
                    "brand": brand,
                    "category": category,
                    "other": other,
                    "asset_type": classify_asset(path, item["mimeType"]),
                    "internal_only": 1 if is_internal_path(path) else 0,
                }
            )
    return found


def download_file(file_id: str, chunk_size: int = 1024 * 1024, start: int | None = None, end: int | None = None, svc=None) -> Iterator[bytes]:
    headers = {}
    if start is not None:
        headers["Range"] = f"bytes={start}-{'' if end is None else end}"
    response = (svc or service()).get(
        f"https://www.googleapis.com/drive/v3/files/{file_id}",
        params={"alt": "media", "supportsAllDrives": "true"},
        headers=headers,
        stream=True,
        timeout=60,
    )
    raise_for_google_error(response)
    yield from response.iter_content(chunk_size=chunk_size)


def thumbnail_link(file_id: str, svc=None) -> str:
    response = (svc or service()).get(
        f"https://www.googleapis.com/drive/v3/files/{file_id}",
        params={"fields": "thumbnailLink", "supportsAllDrives": "true"},
        timeout=THUMBNAIL_FETCH_TIMEOUT,
    )
    raise_for_google_error(response)
    return response.json().get("thumbnailLink", "")


def download_thumbnail(file_id: str, thumbnail_url: str = "") -> tuple[bytes, str, str]:
    svc = service()
    response = None
    for url in [thumbnail_url] if thumbnail_url else []:
        response = svc.get(url, timeout=THUMBNAIL_FETCH_TIMEOUT)
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
        if response.ok and response.content and content_type.startswith("image/"):
            if len(response.content) > 10 * 1024 * 1024:
                raise RuntimeError("Google Drive thumbnail is unexpectedly large")
            return response.content, content_type, url
    fresh_url = thumbnail_link(file_id, svc=svc)
    if fresh_url and fresh_url != thumbnail_url:
        response = svc.get(fresh_url, timeout=THUMBNAIL_FETCH_TIMEOUT)
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
        if response.ok and response.content and content_type.startswith("image/"):
            if len(response.content) > 10 * 1024 * 1024:
                raise RuntimeError("Google Drive thumbnail is unexpectedly large")
            return response.content, content_type, fresh_url
    if response is not None:
        raise_for_google_error(response)
    raise RuntimeError("Google Drive did not provide a thumbnail")
