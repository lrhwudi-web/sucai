from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import sqlite3
import threading
import time
import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Callable

import requests

from . import db, dingtalk_auth, dingtalk_catalog, drive, product_taxonomy, synology
from .logic import is_included_drive_collection

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv", ".wmv", ".mpeg", ".mpg"}
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS
ASSET_TYPES = {"image", "video", "kol_ugc", "ads", "other"}
SYNOLOGY_PREFIX = "synology:"
GOOGLE_DRIVE_PREFIX = "gdrive:"
GOOGLE_DRIVE_INBOX = "临时"
_DRIVE_TARGET_LOCKS_GUARD = threading.Lock()
_DRIVE_TARGET_LOCKS: dict[str, threading.Lock] = {}
EDIT_FIELD_LABELS = {
    "final_sku": "SKU",
    "final_drive_folder": "目标目录",
    "final_english_name": "英文品名",
    "final_drive_name": "文件名",
}
ENGLISH_NAMING_GUIDE = """
Approved English product-name convention:
- For an exact SKU, copy its approved English name exactly. Never retranslate or paraphrase it.
- For a new SKU, use: theme/design + only distinguishing color/material/style + canonical product type.
- Keep one shared theme name across every SKU in the same Set; change only the product-type suffix.
- Do not include the brand, embroidery/printing method, piece construction, magnets, or PU unless it distinguishes the sellable variant.
- Canonical suffixes: Driver Cover, Fairway Cover, 3 Wood Cover, 5 Wood Cover, Hybrid Cover, Blade Putter Cover, Square Mallet Putter Cover, Mid-Mallet Putter Cover, Mallet Putter Cover, Mallet Putter Cover for DF3, Mallet Putter Cover for OZ.1, Iron Cover Set, Wedge Cover Set, Headcover Set.
- Use concise natural English and Title Case. Keep short linking words such as for and with lowercase. Use lowercase pcs, for example 10pcs.
- Use ASCII punctuation only: deg instead of the degree symbol, Dia instead of the diameter symbol, straight quotes, hyphen-minus, and ASCII parentheses.
""".strip()
ASCII_PRODUCT_TRANSLATION = str.maketrans(
    {
        "\u00b0": " deg",
        "\u2300": "Dia ",
        "\u25c7": "L",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\uff08": "(",
        "\uff09": ")",
        "\u00d7": "x",
    }
)
KNOWN_COVER_TYPES = (
    "Square Mallet Putter Cover",
    "Mid-Mallet Putter Cover",
    "Mallet Putter Cover for DF2.1",
    "Mallet Putter Cover for DF3",
    "Mallet Putter Cover for OZ.1",
    "Mallet Putter Cover",
    "Blade Putter Cover",
    "Driver Cover",
    "Fairway Cover",
    "Hybrid Cover",
    "3 Wood Cover",
    "5 Wood Cover",
    "3-Wood Cover",
    "5-Wood Cover",
    "Wood Cover",
    "Iron Cover",
    "Putter Cover",
)

# These names mirror the live Google Drive directory tree scanned on 2026-08-03.
PRODUCT_BRAND_FOLDERS = {
    "craftsman golf": "01 Craftsman Golf",
    "craftsman": "01 Craftsman Golf",
    "my tag": "02 My Tag",
    "big crazy": "03 Big Crazy",
    "big teeth": "04 Big Teeth",
    "\u51ef\u8d5b": "05 Caesar",
    "caesar": "05 Caesar",
}
PRODUCT_BRAND_NAME_PREFIXES = {
    "01 Craftsman Golf": "CF",
    "02 My Tag": "My Tag",
    "03 Big Crazy": "Big Crazy",
    "04 Big Teeth": "Big Teeth",
    "05 Caesar": "Caesar",
}
PRODUCT_CATEGORY_FOLDERS = {
    "HC_PLUSH": "02 Plush Cover",
    "HC_DRIVER": "03 Driver Cover",
    "HC_FAIRWAY": "04 Fairway Cover",
    "HC_HYBRID": "05 Hybrid Cover",
    "HC_PUTTER_BLADE": "06 Blade Putter Cover",
    "HC_PUTTER_MALLET_LARGE": "07 Mallet Putter Cover",
    "HC_PUTTER_MALLET_SMALL": "07 Mallet Putter Cover",
    "HC_PUTTER_SQUARE": "08 Square Mallet Putter Cover",
    "HC_IRON": "09 Iron Cover Set",
    "HC_WEDGE": "10 Wedge Cover Set",
    "HC_ALIGNMENT": "11 Alignment Stick Cover",
    "ACC_DIVOT_MARKER": "12 Ball Marker & Divot Tool",
    "ACC_SCOREBOOK": "13 Scorecard Holder",
    "ACC_VALUABLES_POUCH": "14 Golf Pouch",
    "ACC_TOWEL": "15 Golf Towl",
    "ACC_GLOVE_CASE": "16 Glove Caddie",
    "ACC_BALL_TEE_POUCH": "17 Golf Ball Pouch",
    "ACC_RANGEFINDER_CASE": "18 Range Finder Case",
    "ACC_OTHER": "Golf Accessories",
}
HEADCOVER_SET_FOLDER = "01 Headcover Set"
UNBRANDED_MARKERS = ("no brand", "unbranded", "\u65e0\u724c")
COMPANY_OWNED_MARKERS = ("\u81ea\u4e3b",)


class ConcurrencyConflict(RuntimeError):
    """Raised when another administrator changed or claimed the same material."""


def inbox_root() -> Path:
    value = os.getenv("NAS_INBOX_DIR")
    if not value:
        raise RuntimeError("NAS_INBOX_DIR is not set")
    return Path(value).resolve()


def split_drive_path(path: str) -> list[str]:
    return [part for part in path.replace("\\", "/").strip().strip("/").split("/") if part and part != "."]


def ensure_relative_drive_path(path: str) -> str:
    parts = split_drive_path(path)
    root_name = os.getenv("DRIVE_ROOT_FOLDER_NAME", "").strip()
    if parts and parts[0] == root_name:
        parts = parts[1:]
    if not parts or any(part == ".." for part in parts):
        raise ValueError("Drive folder must be a relative path under DRIVE_ROOT_FOLDER_ID")
    if not root_name and not is_included_drive_collection(parts[0]):
        raise ValueError("Drive folder must start with an included shared-drive collection")
    return "/".join(parts)


def is_english_drive_text(value: str) -> bool:
    return bool(value) and value.isascii() and all(ord(char) >= 32 for char in value)


def validate_english_drive_fields(english_name: str, drive_folder: str, drive_name: str) -> None:
    if not all(is_english_drive_text(value) for value in (english_name, drive_folder, drive_name)):
        raise ValueError("Google Drive folder, filename, and English name must use English ASCII text only")


def file_inside_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def row_path(row: sqlite3.Row, root: Path | None = None) -> Path:
    root = root or inbox_root()
    path = Path(row["local_path"]).resolve()
    if not file_inside_root(path, root):
        raise ValueError("NAS import path is outside NAS_INBOX_DIR")
    return path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _drive_target_lock(folder: str) -> threading.Lock:
    key = ensure_relative_drive_path(folder).casefold()
    with _DRIVE_TARGET_LOCKS_GUARD:
        return _DRIVE_TARGET_LOCKS.setdefault(key, threading.Lock())


def source_asset_type(name: str, mime_type: str = "") -> str:
    suffix = Path(name or "").suffix.lower()
    return "video" if suffix in VIDEO_EXTS or (mime_type or "").lower().startswith("video/") else "image"


def is_supported_media(name: str, mime_type: str = "") -> bool:
    suffix = Path(name or "").suffix.lower()
    normalized_mime = (mime_type or "").lower()
    return suffix in MEDIA_EXTS or normalized_mime.startswith(("image/", "video/"))


def is_video_import(row) -> bool:
    for field in ("final_asset_type", "suggested_asset_type"):
        try:
            if str(row[field] or "").lower() == "video":
                return True
        except (IndexError, KeyError, TypeError):
            continue
    return source_asset_type(
        str(row["name"] or ""),
        mimetypes.guess_type(str(row["name"] or ""))[0] or "",
    ) == "video"


def remote_fingerprint(path: str, size: int, mtime_ns: int) -> str:
    return hashlib.sha256(f"{SYNOLOGY_PREFIX}{path}:{size}:{mtime_ns}".encode()).hexdigest()


def drive_modified_ns(value: str) -> int:
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1_000_000_000)
    except (TypeError, ValueError):
        return 0


def register_drive_item(conn: sqlite3.Connection, item: dict, rel_path: str) -> int:
    size = int(item.get("size") or 0)
    modified_time = item.get("modifiedTime", "")
    mtime_ns = drive_modified_ns(modified_time)
    fingerprint = hashlib.sha256(
        f"{GOOGLE_DRIVE_PREFIX}{item['id']}:{size}:{modified_time}".encode()
    ).hexdigest()
    asset_type = source_asset_type(item["name"], item.get("mimeType", ""))
    with conn:
        before = conn.total_changes
        conn.execute(
            """
            INSERT OR IGNORE INTO nas_imports(
              local_path, rel_path, name, size, mtime_ns, sha256,
              suggested_asset_type, final_asset_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"{GOOGLE_DRIVE_PREFIX}{item['id']}", rel_path, item["name"],
                size, mtime_ns, fingerprint, asset_type, asset_type,
            ),
        )
        return conn.total_changes - before


def drive_inbox_excluded_folder_ids() -> set[str]:
    value = os.getenv("GOOGLE_DRIVE_INBOX_EXCLUDED_FOLDER_IDS", "")
    return {
        folder_id
        for folder_id in re.split(r"[\s,;]+", value.strip())
        if folder_id
    }


def purge_excluded_drive_imports(
    conn: sqlite3.Connection,
    excluded_paths: list[str],
) -> int:
    removed = 0
    with conn:
        for path in excluded_paths:
            cursor = conn.execute(
                """
                DELETE FROM nas_imports
                WHERE local_path LIKE ?
                  AND status != 'uploaded'
                  AND (
                    rel_path = ?
                    OR substr(rel_path, 1, length(?) + 1) = ? || '/'
                  )
                """,
                (f"{GOOGLE_DRIVE_PREFIX}%", path, path, path),
            )
            removed += cursor.rowcount
    return removed


def scan_drive_inbox(
    conn: sqlite3.Connection,
    root_id: str,
    folder_name: str = GOOGLE_DRIVE_INBOX,
    folder_id: str = "",
) -> int:
    svc = drive.service()
    if folder_id:
        inbox = {"id": folder_id, "name": folder_name}
    else:
        inbox = drive.find_child(svc, root_id, folder_name, folder=True)
        if not inbox:
            raise FileNotFoundError(f"Google Drive folder not found: {folder_name}")
    drive_id = root_id if root_id.startswith("0A") else ""
    folders = [(inbox["id"], folder_name)]
    excluded_folder_ids = drive_inbox_excluded_folder_ids()
    excluded_paths: list[str] = []
    count = 0
    while folders:
        folder_id, base_path = folders.pop()
        for item in drive.list_children(svc, folder_id, drive_id):
            path = f"{base_path}/{item['name']}"
            if item["mimeType"] == drive.FOLDER_MIME:
                if item["id"] in excluded_folder_ids:
                    excluded_paths.append(path)
                    continue
                folders.append((item["id"], path))
            elif is_supported_media(item["name"], item.get("mimeType", "")):
                count += register_drive_item(conn, item, path)
    purge_excluded_drive_imports(conn, excluded_paths)
    return count


def sku_candidates(text: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"\d{5,}", text)))


def is_pure_date_folder(value: str) -> bool:
    normalized = value.strip()
    if not re.fullmatch(r"\d{8}", normalized):
        return False
    try:
        datetime.strptime(normalized, "%Y%m%d")
    except ValueError:
        return False
    return True


def source_product_folder(rel_path: str) -> str:
    """Return the deepest SKU-bearing source directory.

    NAS product imports describe the product most precisely in the last folder,
    often without a separator between SKU, brand, and Chinese product name.
    """
    parts = split_drive_path(rel_path)
    if parts and Path(parts[-1]).suffix.lower() in MEDIA_EXTS:
        parts = parts[:-1]
    for part in reversed(parts):
        if sku_candidates(part) and not is_pure_date_folder(part):
            return part
    return parts[-1] if parts else ""


def source_brand_hint(source_path: str) -> str:
    primary = source_product_folder(source_path).lower()
    for alias, folder in sorted(PRODUCT_BRAND_FOLDERS.items(), key=lambda item: len(item[0]), reverse=True):
        if alias in primary:
            return re.sub(r"^\d+\s+", "", folder)
    if any(marker in primary for marker in COMPANY_OWNED_MARKERS):
        return "Craftsman Golf"
    if any(marker in primary for marker in UNBRANDED_MARKERS):
        return "No Brand"

    # Temporary parent folders are supporting context only. In particular,
    # an ancestor named "No Brand" must not override a SKU folder that marks
    # the product as company-owned. Explicit known brands remain useful when
    # the product folder itself has no brand marker.
    combined = source_path.lower()
    for alias, folder in sorted(PRODUCT_BRAND_FOLDERS.items(), key=lambda item: len(item[0]), reverse=True):
        if alias in combined:
            return re.sub(r"^\d+\s+", "", folder)
    return ""


def scan_inbox(conn: sqlite3.Connection, root: Path | None = None) -> int:
    root = root or inbox_root()
    if not root.exists():
        raise FileNotFoundError(f"NAS_INBOX_DIR not found: {root}")
    count = 0
    for path in sorted(item for item in root.rglob("*") if item.is_file() and item.suffix.lower() in MEDIA_EXTS):
        stat = path.stat()
        file_hash = sha256_file(path)
        rel_path = path.relative_to(root).as_posix()
        asset_type = source_asset_type(path.name)
        with conn:
            before = conn.total_changes
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO nas_imports(
                  local_path, rel_path, name, size, mtime_ns, sha256,
                  suggested_asset_type, final_asset_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(path.resolve()), rel_path, path.name, stat.st_size,
                    stat.st_mtime_ns, file_hash, asset_type, asset_type,
                ),
            )
            count += conn.total_changes - before
    return count


def synology_inbox_path() -> str:
    value = os.getenv("SYNOLOGY_INBOX_PATH", "/产品图片")
    return "/" + value.strip("/")


def synology_item_values(item: dict) -> tuple[str, str, int, int]:
    name = item.get("name", "")
    remote_path = item["path"]
    additional = item.get("additional", {})
    size = int(item.get("size") or additional.get("size") or 0)
    mtime_ns = int(additional.get("time", {}).get("mtime") or 0) * 1_000_000_000
    return name, remote_path, size, mtime_ns


def register_synology_item(conn: sqlite3.Connection, item: dict) -> int:
    name, remote_path, size, mtime_ns = synology_item_values(item)
    asset_type = source_asset_type(name)
    with conn:
        before = conn.total_changes
        conn.execute(
            """
            INSERT OR IGNORE INTO nas_imports(
              local_path, rel_path, name, size, mtime_ns, sha256,
              suggested_asset_type, final_asset_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"{SYNOLOGY_PREFIX}{remote_path}",
                remote_path.strip("/"),
                name,
                size,
                mtime_ns,
                remote_fingerprint(remote_path, size, mtime_ns),
                asset_type,
                asset_type,
            ),
        )
        return conn.total_changes - before


def scan_synology(conn: sqlite3.Connection, client: synology.SynologyClient | None = None, folder_path: str | None = None) -> int:
    client = client or synology.SynologyClient()
    folder_path = folder_path or synology_inbox_path()
    count = 0
    for item in client.walk(folder_path):
        if is_supported_media(item.get("name", "")):
            count += register_synology_item(conn, item)
    return count


def scan_synology_incremental(
    conn: sqlite3.Connection,
    client: synology.SynologyClient | None = None,
    folder_path: str | None = None,
) -> int:
    client = client or synology.SynologyClient()
    folder_path = folder_path or synology_inbox_path()
    source = f"{os.getenv('SYNOLOGY_URL', '')}{SYNOLOGY_PREFIX}{folder_path}"
    initialized = conn.execute("SELECT 1 FROM nas_scan_state WHERE source=?", (source,)).fetchone() is not None
    seen_files = {
        row["path"]: (row["size"], row["mtime_ns"])
        for row in conn.execute(
            "SELECT path, size, mtime_ns FROM nas_scan_seen WHERE source=?",
            (source,),
        ).fetchall()
    }
    count = 0
    file_count = 0
    current_files: list[tuple[str, str, int, int]] = []
    for item in client.walk(folder_path):
        if not is_supported_media(item.get("name", "")):
            continue
        file_count += 1
        _, remote_path, size, mtime_ns = synology_item_values(item)
        if initialized and seen_files.get(remote_path) != (size, mtime_ns):
            count += register_synology_item(conn, item)
        current_files.append((source, remote_path, size, mtime_ns))
    with conn:
        conn.executemany(
            """
            INSERT INTO nas_scan_seen(source, path, size, mtime_ns)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(source, path) DO UPDATE SET size=excluded.size, mtime_ns=excluded.mtime_ns
            """,
            current_files,
        )
        conn.execute(
            """
            INSERT INTO nas_scan_state(source, file_count, new_count)
            VALUES (?, ?, ?)
            ON CONFLICT(source) DO UPDATE SET
              last_scan_at=CURRENT_TIMESTAMP,
              file_count=excluded.file_count,
              new_count=excluded.new_count
            """,
            (source, file_count, count),
        )
    return count


def scan_sources(conn: sqlite3.Connection) -> tuple[int, list[str]]:
    root_id = os.getenv("DRIVE_ROOT_FOLDER_ID", "").strip()
    if not root_id:
        raise RuntimeError("DRIVE_ROOT_FOLDER_ID is not set")
    inbox_folder_id = os.getenv("GOOGLE_DRIVE_INBOX_FOLDER_ID", "").strip()
    count = scan_drive_inbox(conn, root_id, folder_id=inbox_folder_id)
    product_taxonomy.backfill_pending_imports(conn)
    conn.commit()
    job_ids: list[str] = []
    pending_skus: list[str] = []
    attention_file_count = count
    if dingtalk_catalog.enabled():
        try:
            pending_rows = conn.execute(
                """
                SELECT rel_path FROM nas_imports
                WHERE status IN ('pending','suggested','error') AND local_path LIKE ?
                ORDER BY created_at, id
                """,
                (f"{GOOGLE_DRIVE_PREFIX}%",),
            ).fetchall()
            attention_file_count = max(count, len(pending_rows))
            for pending_row in pending_rows:
                candidates = sku_candidates(source_product_folder(pending_row["rel_path"]))
                if len(candidates) == 1:
                    pending_skus.append(candidates[0])
            stats = dingtalk_catalog.sync_catalog_skus(conn, pending_skus)
            job_ids = queue_catalog_auto_import_jobs(conn, root_id)
            missing_skus = [
                sku
                for sku in dict.fromkeys(pending_skus)
                if dingtalk_catalog.product_for_sku(conn, sku) is None
            ]
            if missing_skus:
                try:
                    notify_catalog_import_attention(
                        conn,
                        missing_skus,
                        pending_file_count=attention_file_count,
                    )
                except Exception as notification_exc:
                    print(
                        f"DingTalk catalogue attention notification failed: {notification_exc}",
                        flush=True,
                    )
            print(
                f"DingTalk catalogue sync completed: {stats['ready']}/{stats['records']} ready; "
                f"{len(job_ids)} automatic import jobs queued",
                flush=True,
            )
        except Exception as exc:
            dingtalk_catalog.record_sync_error(conn, str(exc))
            try:
                notify_catalog_import_attention(
                    conn,
                    pending_skus,
                    pending_file_count=attention_file_count,
                    error=str(exc),
                )
            except Exception as notification_exc:
                print(
                    f"DingTalk catalogue failure notification failed: {notification_exc}",
                    flush=True,
                )
            print(f"DingTalk catalogue auto import stopped safely: {exc}", flush=True)
    return count, job_ids


def list_imports(
    conn: sqlite3.Connection,
    limit: int | None = 50,
    offset: int = 0,
    view: str = "active",
) -> list[sqlite3.Row]:
    if view not in {"active", "disabled"}:
        raise ValueError("Invalid import view")
    status_clause = (
        "imports.status = 'rejected'"
        if view == "disabled"
        else "imports.status NOT IN ('approved', 'uploaded', 'rejected')"
    )
    order_clause = (
        "imports.updated_at DESC, imports.id DESC"
        if view == "disabled"
        else "imports.created_at DESC, imports.id DESC"
    )
    source_clause = ""
    args: list[object] = []
    if os.getenv("GOOGLE_DRIVE_INBOX_FOLDER_ID", "").strip():
        source_clause = "AND imports.local_path LIKE ?"
        args.append(f"{GOOGLE_DRIVE_PREFIX}%")
    limit_clause = "" if limit is None else "LIMIT ? OFFSET ?"
    if limit is not None:
        args.extend((max(1, limit), max(0, offset)))
    return conn.execute(
        f"""
        SELECT imports.*,
               COALESCE(meta.set_code, '') AS catalog_set_code,
               COALESCE(meta.themes, '') AS catalog_themes
        FROM nas_imports imports
        LEFT JOIN sku_meta meta
          ON meta.sku = COALESCE(NULLIF(imports.final_sku, ''), NULLIF(imports.suggested_sku, ''))
        WHERE {status_clause}
          {source_clause}
        ORDER BY {order_clause}
        {limit_clause}
        """,
        tuple(args),
    ).fetchall()


def import_batch_key(row: sqlite3.Row) -> str:
    rel_path = str(row["rel_path"] or "").replace("\\", "/")
    parts = [part for part in rel_path.split("/") if part]
    if parts and parts[-1] == row["name"]:
        parts.pop()
    return "/".join(parts) or f"import-{row['id']}"


def paginate_imports(
    conn: sqlite3.Connection,
    page: int = 1,
    page_size: int = 6,
    view: str = "active",
) -> dict:
    """Paginate complete upload batches, not individual imported files."""
    page_size = max(1, min(page_size, 100))
    rows = list_imports(conn, limit=None, view=view)
    batches: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        batches.setdefault(import_batch_key(row), []).append(row)

    batch_rows = list(batches.values())
    batch_total = len(batch_rows)
    page_count = max(1, (batch_total + page_size - 1) // page_size)
    page = max(1, min(page, page_count))
    start = (page - 1) * page_size
    page_batches = batch_rows[start:start + page_size]
    page_imports = [row for batch in page_batches for row in batch]
    return {
        "imports": page_imports,
        "total": len(rows),
        "batch_total": batch_total,
        "batch_count": len(page_batches),
        "page": page,
        "page_size": page_size,
        "pages": page_count,
    }


def get_import(conn: sqlite3.Connection, import_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM nas_imports WHERE id = ?", (import_id,)).fetchone()


def is_synology_row(row: sqlite3.Row) -> bool:
    return row["local_path"].startswith(SYNOLOGY_PREFIX)


def is_google_drive_row(row: sqlite3.Row) -> bool:
    return row["local_path"].startswith(GOOGLE_DRIVE_PREFIX)


def source_drive_file_id(row: sqlite3.Row) -> str:
    if not is_google_drive_row(row):
        raise ValueError("Import is not a Google Drive file")
    return row["local_path"][len(GOOGLE_DRIVE_PREFIX) :]


def synology_remote_path(row: sqlite3.Row) -> str:
    if not is_synology_row(row):
        raise ValueError("NAS import is not a Synology file")
    return row["local_path"][len(SYNOLOGY_PREFIX) :]


def synology_google_root() -> str:
    return "/" + os.getenv("SYNOLOGY_GOOGLE_ROOT", "/google").strip("/")


def join_synology_path(*parts: str) -> str:
    return "/" + "/".join(part.strip("/") for part in parts if part and part.strip("/"))


def ensure_synology_folder_path(client: synology.SynologyClient, root: str, folder: str) -> str:
    current = "/" + root.strip("/")
    for part in split_drive_path(folder):
        existing = {item.get("name") for item in client.list_folder(current) if item.get("isdir")}
        if part not in existing:
            client.create_folder(current, part)
        current = join_synology_path(current, part)
    return current


def copy_synology_to_google(row: sqlite3.Row, folder: str, name: str) -> str:
    client = synology.SynologyClient()
    source_path = synology_remote_path(row)
    dest_folder = ensure_synology_folder_path(client, synology_google_root(), folder)
    taskid = client.copy(source_path, dest_folder)
    client.wait_copy(taskid)
    source_name = Path(source_path).name
    if source_name != name:
        client.rename(join_synology_path(dest_folder, source_name), name)
    return f"{SYNOLOGY_PREFIX}{join_synology_path(dest_folder, name)}"


def download_synology_import(row: sqlite3.Row):
    return synology.SynologyClient().download(synology_remote_path(row))


def status_counts(conn: sqlite3.Connection) -> dict[str, int]:
    if os.getenv("GOOGLE_DRIVE_INBOX_FOLDER_ID", "").strip():
        rows = conn.execute(
            "SELECT status, COUNT(*) AS count FROM nas_imports WHERE local_path LIKE ? GROUP BY status",
            (f"{GOOGLE_DRIVE_PREFIX}%",),
        ).fetchall()
    else:
        rows = conn.execute("SELECT status, COUNT(*) AS count FROM nas_imports GROUP BY status").fetchall()
    return {row["status"]: row["count"] for row in rows}


def list_edit_logs(conn: sqlite3.Connection, limit: int = 500) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT logs.id, logs.import_id, logs.field, logs.suggested_value,
               logs.previous_value, logs.new_value,
               imports.approved_by AS edited_by,
               COALESCE(imports.approved_at, logs.created_at) AS created_at,
               imports.name AS source_name, imports.rel_path,
               COALESCE(NULLIF(users.name, ''), users.email, '') AS editor
        FROM nas_import_edit_logs logs
        JOIN nas_imports imports ON imports.id = logs.import_id
        LEFT JOIN users ON users.id = imports.approved_by
        WHERE imports.status='uploaded'
          AND logs.id=(
            SELECT MAX(latest.id)
            FROM nas_import_edit_logs latest
            WHERE latest.import_id=logs.import_id AND latest.field=logs.field
          )
        ORDER BY imports.approved_at DESC, logs.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def _record_approved_edit_logs(conn: sqlite3.Connection, row: sqlite3.Row, approved_by: int) -> None:
    conn.execute("DELETE FROM nas_import_edit_logs WHERE import_id=?", (int(row["id"]),))
    for field in ("final_sku", "final_english_name", "final_drive_folder", "final_drive_name"):
        suggested_field = field.replace("final_", "suggested_")
        suggested_value = (row[suggested_field] or "").strip()
        final_value = (row[field] or "").strip()
        if suggested_value == final_value:
            continue
        conn.execute(
            """
            INSERT INTO nas_import_edit_logs(
              import_id, field, suggested_value, previous_value, new_value, edited_by
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (int(row["id"]), field, suggested_value, suggested_value, final_value, int(approved_by)),
        )


def list_uploaded_imports(conn: sqlite3.Connection, limit: int = 500) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT imports.*, COALESCE(NULLIF(users.name, ''), users.email, '') AS approver
        FROM nas_imports imports
        LEFT JOIN users ON users.id = imports.approved_by
        WHERE imports.status = 'uploaded'
        ORDER BY imports.approved_at DESC, imports.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def validate_identity_fields(sku: str, english_name: str, drive_name: str) -> tuple[str, str, str]:
    sku = sku.strip().upper()
    english_name = english_name.strip()
    drive_name = drive_name.strip()
    if not sku:
        raise ValueError("SKU 不能为空。")
    if not is_english_drive_text(english_name):
        raise ValueError("英文品名只能使用英文字符，不能包含中文或特殊字符。")
    if not re.search(r"[A-Za-z]", english_name):
        raise ValueError("英文品名必须包含英文字母，不能只填写数字。")
    if not is_english_drive_text(drive_name):
        raise ValueError("文件名只能使用英文字符，不能包含中文或特殊字符。")
    if "/" in drive_name or "\\" in drive_name:
        raise ValueError("文件名不能包含 / 或 \\。")
    return sku, english_name, drive_name


def _product_name_parts(stem: str, sku: str) -> tuple[str, str, str] | None:
    if not sku or not re.match(rf"^{re.escape(sku)}(?:\s|\(|$)", stem, flags=re.IGNORECASE):
        return None
    sequence = re.search(r"(\s*\(\d+\))$", stem)
    sequence_text = sequence.group(1) if sequence else ""
    stem_without_sequence = stem[: -len(sequence_text)] if sequence_text else stem
    separator = stem_without_sequence.find(" - ")
    prefix = stem_without_sequence[: separator + 3] if separator >= 0 else f"{sku} "
    return prefix, stem_without_sequence[len(prefix) :], sequence_text


def synchronize_product_drive_name(
    drive_name: str,
    sku: str,
    previous_english_name: str,
    english_name: str,
) -> str:
    del previous_english_name
    drive_name = drive_name.strip()
    english_name = english_name.strip()
    if not drive_name or not english_name:
        return drive_name
    suffix = Path(drive_name).suffix
    stem = drive_name[: -len(suffix)] if suffix else drive_name
    parts = _product_name_parts(stem, sku)
    if not parts:
        return drive_name
    prefix, product_name, sequence_text = parts
    if product_name.lower() == english_name.lower():
        return drive_name
    return f"{prefix}{english_name}{sequence_text}{suffix}"


def synchronize_product_drive_folder(
    drive_folder: str,
    sku: str,
    previous_english_name: str,
    english_name: str,
) -> str:
    del previous_english_name
    parts = split_drive_path(drive_folder)
    english_name = english_name.strip()
    if not parts or not english_name:
        return drive_folder
    leaf_parts = _product_name_parts(parts[-1], sku)
    if not leaf_parts:
        return drive_folder
    prefix, product_name, sequence_text = leaf_parts
    if product_name.lower() == english_name.lower():
        return "/".join(parts)
    parts[-1] = f"{prefix}{english_name}{sequence_text}"
    return "/".join(parts)


def _save_identity(
    conn: sqlite3.Connection,
    import_id: int,
    sku: str,
    english_name: str,
    drive_name: str,
    edited_by: int | None = None,
    expected_revision: int | None = None,
) -> None:
    sku, english_name, drive_name = validate_identity_fields(sku, english_name, drive_name)
    current = get_import(conn, import_id)
    if not current:
        raise ValueError(f"素材 {import_id} 不存在或已被处理。")
    if expected_revision is None:
        expected_revision = int(current["revision"])
    if int(current["revision"]) != int(expected_revision):
        raise ConcurrencyConflict("该素材已被其他管理员修改，请刷新后重试。")
    previous_english_name = (current["final_english_name"] or current["suggested_english_name"] or "").strip()
    drive_name = synchronize_product_drive_name(drive_name, sku, previous_english_name, english_name)
    drive_folder = synchronize_product_drive_folder(
        current["final_drive_folder"] or current["suggested_drive_folder"] or "",
        sku,
        previous_english_name,
        english_name,
    )
    if drive_folder.startswith(("04 Product Images/", "04 Product Images (No Brand)/")) or drive_folder in {
        "04 Product Images",
        "04 Product Images (No Brand)",
    }:
        drive_folder = canonical_product_drive_folder(
            conn,
            sku=sku,
            english_name=english_name,
            category_id=current["final_category_id"] or current["suggested_category_id"] or "",
            source_path=current["rel_path"],
            suggested_folder=drive_folder,
            set_code=current["final_set_code"] or "",
        )
    cursor = conn.execute(
        """
        UPDATE nas_imports
        SET final_sku=?, final_english_name=?, final_drive_folder=?, final_drive_name=?,
            status=CASE WHEN status IN ('pending','error') THEN 'suggested' ELSE status END,
            error='', updated_at=CURRENT_TIMESTAMP, revision=revision+1
        WHERE id=? AND revision=? AND status NOT IN ('approved','uploaded')
        """,
        (sku, english_name, drive_folder, drive_name, import_id, expected_revision),
    )
    if cursor.rowcount != 1:
        raise ConcurrencyConflict("该素材已被其他管理员修改或正在入库，请刷新后重试。")


def save_identities(
    conn: sqlite3.Connection,
    import_ids: list[int],
    sku: str,
    english_name: str,
    drive_names: list[str],
    edited_by: int | None = None,
    expected_revisions: list[int] | None = None,
) -> int:
    if not import_ids:
        raise ValueError("没有可保存的素材。")
    if len(import_ids) != len(drive_names):
        raise ValueError("素材数量与文件名数量不一致，请刷新页面后重试。")
    if expected_revisions is not None and len(import_ids) != len(expected_revisions):
        raise ValueError("素材版本数量不一致，请刷新页面后重试。")
    with conn:
        for index, (import_id, drive_name) in enumerate(zip(import_ids, drive_names)):
            revision = expected_revisions[index] if expected_revisions is not None else None
            _save_identity(conn, import_id, sku, english_name, drive_name, edited_by, revision)
    return len(import_ids)


def save_final(
    conn: sqlite3.Connection,
    import_id: int,
    sku: str,
    english_name: str,
    drive_folder: str,
    drive_name: str,
    asset_type: str,
    set_code: str = "",
    category_id: str = "",
    category_tags: str = "",
    themes: str = "",
    update_themes: bool = False,
    edited_by: int | None = None,
    expected_revision: int | None = None,
) -> None:
    sku = sku.strip().upper()
    english_name = english_name.strip()
    drive_folder = ensure_relative_drive_path(drive_folder)
    drive_name = drive_name.strip()
    asset_type = asset_type.strip() or "image"
    set_code = db.normalize_set_code(set_code)
    validate_english_drive_fields(english_name, drive_folder, drive_name)
    if not sku or not english_name or not drive_name or asset_type not in ASSET_TYPES or "/" in drive_name or "\\" in drive_name:
        raise ValueError("Invalid NAS import fields")
    current = get_import(conn, import_id)
    if not current:
        raise ValueError("NAS import not found")
    if expected_revision is None:
        expected_revision = int(current["revision"])
    if int(current["revision"]) != int(expected_revision):
        raise ConcurrencyConflict("该素材已被其他管理员修改，请刷新后重试。")
    category_id = (
        category_id.strip()
        or current["final_category_id"]
        or current["suggested_category_id"]
    )
    category_tags = (
        category_tags.strip()
        or current["final_category_tags"]
        or current["suggested_category_tags"]
    )
    if not category_id:
        classification = product_taxonomy.classify_product(
            conn,
            sku=sku,
            name=current["rel_path"],
            english_name=english_name,
            path=current["rel_path"],
            external_id=str(import_id),
        )
        if classification["category_id"] != "UNKNOWN":
            category_id = classification["category_id"]
            category_tags = "|".join(classification["tags"])
    if category_id:
        category_id = product_taxonomy.validate_category_id(category_id, conn)
        category_tags = product_taxonomy.normalize_tags(category_tags)
    themes = (
        product_taxonomy.normalize_themes(themes, conn)
        if update_themes
        else current["final_themes"]
    )
    previous_english_name = (current["final_english_name"] or current["suggested_english_name"] or "").strip()
    drive_name = synchronize_product_drive_name(drive_name, sku, previous_english_name, english_name)
    drive_folder = synchronize_product_drive_folder(drive_folder, sku, previous_english_name, english_name)
    if drive_folder.startswith(("04 Product Images/", "04 Product Images (No Brand)/")):
        drive_folder = canonical_product_drive_folder(
            conn,
            sku=sku,
            english_name=english_name,
            category_id=category_id,
            source_path=current["rel_path"],
            suggested_folder=drive_folder,
            set_code=set_code,
        )
    validate_english_drive_fields(english_name, drive_folder, drive_name)
    with conn:
        cursor = conn.execute(
            """
            UPDATE nas_imports
            SET final_sku=?, final_english_name=?, final_drive_folder=?, final_drive_name=?,
                final_asset_type=?, final_set_code=?,
                final_category_id=?, final_category_tags=?,
                final_themes=?,
                themes_updated=CASE WHEN ? THEN 1 ELSE themes_updated END,
                category_needs_review=CASE WHEN ? <> '' THEN 0 ELSE category_needs_review END,
                status=CASE WHEN status IN ('pending','error') THEN 'suggested' ELSE status END,
                error='', updated_at=CURRENT_TIMESTAMP, revision=revision+1
            WHERE id=? AND revision=? AND status NOT IN ('approved','uploaded')
            """,
            (
                sku, english_name, drive_folder, drive_name, asset_type, set_code,
                category_id, category_tags, themes, int(update_themes), category_id, import_id,
                expected_revision,
            ),
        )
        if cursor.rowcount != 1:
            raise ConcurrencyConflict("该素材已被其他管理员修改或正在入库，请刷新后重试。")


def apply_batch_settings(
    conn: sqlite3.Connection,
    import_ids: list[int],
    drive_folder: str = "",
    set_code: str = "",
    category_id: str = "",
    category_tags: str = "",
    themes: str = "",
    update_themes: bool = False,
    expected_revisions: list[int] | None = None,
) -> int:
    unique_ids = list(dict.fromkeys(import_ids))
    if not unique_ids:
        return 0
    drive_folder = ensure_relative_drive_path(drive_folder) if drive_folder.strip() else ""
    set_code = db.normalize_set_code(set_code)
    category_id = product_taxonomy.validate_category_id(category_id, conn) if category_id.strip() else ""
    category_tags = product_taxonomy.normalize_tags(category_tags)
    themes = product_taxonomy.normalize_themes(themes, conn) if update_themes else ""
    assignments = []
    values: list[str | int] = []
    if drive_folder:
        assignments.append("final_drive_folder=?")
        values.append(drive_folder)
    if set_code:
        assignments.append("final_set_code=?")
        values.append(set_code)
    if category_id:
        assignments.extend(("final_category_id=?", "category_needs_review=0"))
        values.append(category_id)
    if category_tags:
        assignments.append("final_category_tags=?")
        values.append(category_tags)
    if update_themes:
        assignments.extend(("final_themes=?", "themes_updated=1"))
        values.append(themes)
    if not assignments:
        return 0
    if expected_revisions is not None and len(unique_ids) != len(expected_revisions):
        raise ValueError("素材版本数量不一致，请刷新页面后重试。")
    assignments.append("revision=revision+1")
    if expected_revisions is not None:
        with conn:
            for import_id, revision in zip(unique_ids, expected_revisions):
                cursor = conn.execute(
                    f"UPDATE nas_imports SET {', '.join(assignments)}, updated_at=CURRENT_TIMESTAMP WHERE id=? AND revision=? AND status NOT IN ('approved','uploaded')",
                    [*values, import_id, revision],
                )
                if cursor.rowcount != 1:
                    raise ConcurrencyConflict("整批素材中有内容已被其他管理员修改，请刷新后重试。")
        return len(unique_ids)
    placeholders = ",".join("?" for _ in unique_ids)
    with conn:
        cursor = conn.execute(
            f"UPDATE nas_imports SET {', '.join(assignments)}, updated_at=CURRENT_TIMESTAMP WHERE id IN ({placeholders})",
            [*values, *unique_ids],
        )
    return cursor.rowcount


def reject_imports(conn: sqlite3.Connection, import_ids: list[int]) -> int:
    unique_ids = list(dict.fromkeys(int(import_id) for import_id in import_ids))
    if not unique_ids:
        return 0
    placeholders = ",".join("?" for _ in unique_ids)
    with conn:
        cursor = conn.execute(
            f"""
            UPDATE nas_imports
            SET status='rejected', error='', updated_at=CURRENT_TIMESTAMP, revision=revision+1
            WHERE id IN ({placeholders})
              AND status IN ('pending', 'suggested', 'error')
            """,
            unique_ids,
        )
    return cursor.rowcount


def reject_import(conn: sqlite3.Connection, import_id: int) -> None:
    reject_imports(conn, [import_id])


def restore_imports(conn: sqlite3.Connection, import_ids: list[int]) -> int:
    unique_ids = list(dict.fromkeys(int(import_id) for import_id in import_ids))
    if not unique_ids:
        return 0
    placeholders = ",".join("?" for _ in unique_ids)
    with conn:
        cursor = conn.execute(
            f"""
            UPDATE nas_imports
            SET status='pending', error='', updated_at=CURRENT_TIMESTAMP, revision=revision+1
            WHERE id IN ({placeholders})
              AND status = 'rejected'
            """,
            unique_ids,
        )
    return cursor.rowcount


def restore_import(conn: sqlite3.Connection, import_id: int) -> None:
    restore_imports(conn, [import_id])


def product_destination_guide() -> str:
    category_lines = [f"- {category_id}: {folder}" for category_id, folder in PRODUCT_CATEGORY_FOLDERS.items()]
    brand_lines = [f"- 04 Product Images/{folder}" for folder in dict.fromkeys(PRODUCT_BRAND_FOLDERS.values())]
    return "\n".join(
        [
            "Authoritative current Google Drive product destination hierarchy:",
            "Branded root: 04 Product Images/<brand folder>/<category folder>/<SKU + brand prefix + English product name>.",
            "Allowed brand folders:",
            *brand_lines,
            "No-brand root: 04 Product Images (No Brand)/<category folder>/<SKU + English product name>.",
            "Exact category folders (the identifier is the fixed product category):",
            *category_lines,
            "Big Teeth and Caesar use '02 Plush Headcover' instead of '02 Plush Cover'.",
            "A Set code is product metadata only. Always put the SKU folder directly under its fixed category folder; never create a Headcover Set or Set folder level.",
            "Golf Accessories is also a normal category folder (ACC_OTHER): append the product folder directly under Golf Accessories, with no extra category or Set level.",
            "Never omit or rewrite the numeric prefixes. Never use old plural category names such as Driver Covers or Headcovers Set.",
        ]
    )


def sku_product_metadata(conn: sqlite3.Connection, sku: str) -> dict[str, str]:
    if not sku:
        return {"brand": "", "category_id": "", "set_code": ""}
    row = conn.execute(
        "SELECT brand, category_id, set_code FROM sku_meta WHERE sku=?",
        (sku.strip().upper(),),
    ).fetchone()
    if not row:
        return {"brand": "", "category_id": "", "set_code": ""}
    return {
        "brand": (row["brand"] or "").strip(),
        "category_id": (row["category_id"] or "").strip(),
        "set_code": db.normalize_set_code(row["set_code"] or ""),
    }


def canonical_brand_folder(brand: str, source_path: str = "", suggested_folder: str = "") -> tuple[str, bool]:
    source_hint = source_brand_hint(source_path)
    if source_hint == "No Brand":
        return "", True
    if source_hint:
        hinted_folder = PRODUCT_BRAND_FOLDERS.get(source_hint.lower(), "")
        if hinted_folder:
            return hinted_folder, False
    brand_key = re.sub(r"\s+", " ", brand.strip().lower())
    if brand_key in PRODUCT_BRAND_FOLDERS:
        return PRODUCT_BRAND_FOLDERS[brand_key], False
    combined = f"{brand} {suggested_folder}".lower()
    if any(marker in combined for marker in UNBRANDED_MARKERS):
        return "", True
    for alias, folder in PRODUCT_BRAND_FOLDERS.items():
        if alias in combined:
            return folder, False
    return "", False


def canonical_category_folder(category_id: str, brand_folder: str = "") -> str:
    folder = PRODUCT_CATEGORY_FOLDERS.get(category_id.strip(), "")
    if folder == "02 Plush Cover" and brand_folder in {"04 Big Teeth", "05 Caesar"}:
        return "02 Plush Headcover"
    return folder


def product_folder_name(sku: str, english_name: str, brand_folder: str = "") -> str:
    prefix = PRODUCT_BRAND_NAME_PREFIXES.get(brand_folder, "")
    if prefix:
        return f"{sku} {prefix} - {english_name}".strip()
    return f"{sku} {english_name}".strip()


def set_theme_name(english_name: str) -> str:
    name = english_name.strip()
    name = re.sub(r"\s+Headcover Set\b.*$", "", name, flags=re.IGNORECASE).strip()
    for suffix in KNOWN_COVER_TYPES:
        without_type = re.sub(
            rf"\s+{re.escape(suffix)}(?:\s*#\s*\d+)?$",
            "",
            name,
            flags=re.IGNORECASE,
        ).strip()
        if without_type != name:
            return without_type
    name = re.sub(r"\s+(?:Iron|Wedge) Cover Set$", "", name, flags=re.IGNORECASE).strip()
    return name or english_name.strip()


def set_folder_from_path(folder: str, set_code: str, base_folder: str = "") -> str:
    parts = split_drive_path(folder)
    if base_folder:
        base_parts = split_drive_path(base_folder)
        root_length = 2 if base_parts and base_parts[0] == "04 Product Images" else 1
        if parts[:root_length] != base_parts[:root_length]:
            return ""
    for part in parts:
        if part.lower().startswith(set_code.lower() + " ") or part.lower() == set_code.lower():
            return part
    return ""


def indexed_set_folder(conn: sqlite3.Connection, base_folder: str, set_code: str) -> str:
    prefix = f"{base_folder}/{set_code}"
    rows = conn.execute(
        "SELECT path FROM files WHERE path LIKE ? ORDER BY path LIMIT 40",
        (prefix + "%",),
    ).fetchall()
    base_parts = split_drive_path(base_folder)
    for row in rows:
        parts = split_drive_path(row["path"])
        if parts[: len(base_parts)] != base_parts or len(parts) <= len(base_parts):
            continue
        candidate = parts[len(base_parts)]
        if candidate.lower().startswith(set_code.lower()):
            return candidate
    return ""


def build_set_folder(set_code: str, english_name: str, brand_folder: str = "") -> str:
    theme = set_theme_name(english_name)
    prefix = PRODUCT_BRAND_NAME_PREFIXES.get(brand_folder, "")
    if prefix:
        return f"{set_code} {prefix} - {theme} Headcover Set".strip()
    return f"{set_code} {theme} Headcover Set".strip()


def canonical_product_drive_folder(
    conn: sqlite3.Connection,
    *,
    sku: str,
    english_name: str,
    category_id: str,
    source_path: str = "",
    suggested_folder: str = "",
    set_code: str = "",
) -> str:
    metadata = sku_product_metadata(conn, sku)
    brand = metadata["brand"]
    category_id = category_id.strip() or metadata["category_id"]
    db.normalize_set_code(set_code or metadata["set_code"])
    brand_folder, unbranded = canonical_brand_folder(brand, source_path, suggested_folder)
    if not brand_folder and not unbranded:
        return synchronize_product_drive_folder(suggested_folder, sku, "", english_name)

    root_parts = ["04 Product Images", brand_folder] if brand_folder else ["04 Product Images (No Brand)"]
    category_folder = canonical_category_folder(category_id, brand_folder)
    if not category_folder:
        return synchronize_product_drive_folder(suggested_folder, sku, "", english_name)

    return "/".join([*root_parts, category_folder, product_folder_name(sku, english_name, brand_folder)])


def drive_catalog(conn: sqlite3.Connection, candidates: list[str], source_path: str = "") -> str:
    rows = []
    approved = []
    if candidates:
        placeholders = ",".join("?" for _ in candidates)
        args = [candidate.upper() for candidate in candidates]
        rows = conn.execute(
            f"SELECT sku, brand, category, path FROM files WHERE sku IN ({placeholders}) ORDER BY sku, path LIMIT 80",
            args,
        ).fetchall()
        approved = conn.execute(
            f"""
            SELECT sku, english_name, brand, category_id, set_code
            FROM sku_meta
            WHERE sku IN ({placeholders})
            ORDER BY sku
            """,
            args,
        ).fetchall()
    rows = [
        row for row in rows
        if is_english_drive_text(row["path"]) and "product packaging" not in row["path"].lower()
    ]
    parts = [product_destination_guide()]
    if approved:
        parts.append("Exact SKU metadata (use these values instead of guessing):")
        parts.extend(
            "- "
            f"SKU={row['sku']} english_name={row['english_name']} brand={row['brand']} "
            f"category_id={row['category_id']} set_code={row['set_code']}"
            for row in approved
        )
    if rows:
        parts.append("Existing exact-SKU file paths (use product/Set names only; the authoritative category hierarchy above wins):")
        parts.extend(f"- SKU={row['sku']} brand={row['brand']} category={row['category']} path={row['path']}" for row in rows[:40])
    return "\n".join(parts)


def suggestion_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "sku": {"type": "string"},
            "english_name": {"type": "string"},
            "drive_folder": {"type": "string"},
            "drive_name": {"type": "string"},
            "asset_type": {"type": "string", "enum": sorted(ASSET_TYPES)},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "reason": {"type": "string"},
            "needs_manual_attention": {"type": "boolean"},
        },
        "required": ["sku", "english_name", "drive_folder", "drive_name", "asset_type", "confidence", "reason", "needs_manual_attention"],
    }


def response_text(payload: dict) -> str:
    if payload.get("output_text"):
        return payload["output_text"]
    chunks: list[str] = []
    for item in payload.get("output", []):
        for part in item.get("content", []):
            text = part.get("text") or part.get("output_text")
            if text:
                chunks.append(text)
    return "".join(chunks)


def suggestion_prompt(row: sqlite3.Row, catalog: str, candidates: list[str]) -> str:
    primary_product_folder = source_product_folder(row["rel_path"])
    brand_hint = source_brand_hint(row["rel_path"])
    return f"""
You route new product asset files into an existing Google Drive library.
Use only the source path, filename, SKU candidates, and Drive catalog below.
Do not inspect or infer from image pixels. Do not invent a SKU. If no SKU candidate is present, return sku="" and needs_manual_attention=true.
The Primary source product folder below is the most precise source of truth. Parse its leading digits as the SKU even when the SKU directly touches the brand, for example 6016113Big Teeth. Treat the remaining text as brand plus Chinese product description.
Use ancestor folders only as supporting brand/category hints. Generic ancestors such as 帽套 or 其他产品 must not replace the detailed product description in the Primary source product folder.
Determine the brand from the Primary source product folder before looking at ancestors. A known brand name wins; 自主 means the company-owned Craftsman Golf brand; 凯赛 means Caesar; 无牌, No Brand, or Unbranded means no brand only when it appears in the Primary source product folder. An ancestor named 无牌 is temporary staging context and must never override the Primary source product folder.
Every character in english_name, drive_folder, and drive_name must be English ASCII. Never copy Chinese text into these fields; translate it into concise natural English.
Return a relative Drive folder under DRIVE_ROOT_FOLDER_ID, not an absolute path.
The Drive root is the shared-drive root. drive_folder must start with one of: 04 Product Images, 04 Product Images (No Brand), Product Catalogs, Brand Assets, Packaging Assets, Show & Exhibitions, Event & Sponsorships, Influencer Assets, or Collection Assets. A numeric ordering prefix on the folder is allowed.
Use 04 Product Images for branded product assets and 04 Product Images (No Brand) for unbranded product assets.
When NAS path starts with 产品图片, use only product-image folders. Never return a folder containing Product packaging or 包装.
For product images, follow the authoritative brand/category hierarchy in the catalog exactly. Do not invent, translate, pluralize, or omit a category level.
The product folder is always the last path component and includes the SKU plus the English product name.
Set code is metadata only. Put every SKU folder directly under its fixed category folder. Never create a Headcover Set or Set folder level.
Always return your best English drive_folder suggestion, even when confidence is low or no exact SKU folder exists. Never leave drive_folder blank; use needs_manual_attention=true to express uncertainty instead.
Translate product type conservatively: 推杆帽套=Putter Cover, 一号木帽套=Driver Cover, 3号木帽套=3-Wood Cover, 5号木帽套=5-Wood Cover, 木杆帽套=Wood Cover, 铁杆帽套=Iron Cover, 无牌=Unbranded.
Use this product glossary when present: 黑色PU猴子西服=Sunglass Gorilla.
Keep the original file extension in drive_name.

{ENGLISH_NAMING_GUIDE}

Return JSON with exactly these keys: sku, english_name, drive_folder, drive_name, asset_type, confidence, reason, needs_manual_attention.

Source relative path: {row['rel_path']}
Primary source product folder: {primary_product_folder or '(none)'}
Source brand hint: {brand_hint or '(none)'}
Filename: {row['name']}
SKU candidates from path: {', '.join(candidates) or '(none)'}

Existing Drive catalog:
{catalog}
"""


def load_json_object(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def request_openai_suggestion(prompt: str) -> dict:
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL")
    if not api_key or not model:
        raise RuntimeError("Set OPENAI_API_KEY and OPENAI_MODEL to generate AI suggestions")
    response = requests.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "input": [
                {"role": "system", "content": "You produce conservative JSON suggestions for a human approval queue. All Google Drive names and folders must be English ASCII only."},
                {"role": "user", "content": prompt},
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "nas_import_suggestion",
                    "strict": True,
                    "schema": suggestion_schema(),
                }
            },
        },
        timeout=60,
    )
    response.raise_for_status()
    return load_json_object(response_text(response.json()))


def chat_message_text(payload: dict) -> str:
    return payload["choices"][0]["message"]["content"]


def normalize_drive_name(name: str, fallback: str) -> str:
    name = (name or fallback).strip()
    if "/" in name or "\\" in name:
        name = fallback
    suffix = Path(fallback).suffix
    if suffix and not Path(name).suffix:
        name += suffix
    return name


def glossary_name(rel_path: str) -> str:
    if "黑色PU猴子西服" in rel_path:
        return "Sunglass Gorilla"
    return ""


def cover_type_name(rel_path: str) -> str:
    if "DF3" in rel_path:
        return "Mallet Putter Cover for DF3"
    if "DF2.1" in rel_path:
        return "Mallet Putter Cover for DF2.1"
    if "OZ.1" in rel_path:
        return "Mallet Putter Cover for OZ.1"
    if "\u76f4\u6761" in rel_path:
        return "Blade Putter Cover"
    if any(marker in rel_path for marker in ("\u65b9\u5f62", "\u65b9\u5757")):
        return "Square Mallet Putter Cover"
    if "\u5c0f\u534a\u5706" in rel_path:
        return "Mid-Mallet Putter Cover"
    if any(marker in rel_path for marker in ("\u5927\u534a\u5706", "\u534a\u5706")):
        return "Mallet Putter Cover"
    if "3\u53f7\u6728" in rel_path:
        return "3 Wood Cover"
    if "5\u53f7\u6728" in rel_path:
        return "5 Wood Cover"
    if any(marker in rel_path for marker in ("\u4e00\u53f7\u6728", "1\u53f7\u6728")):
        return "Driver Cover"
    if "\u7403\u9053\u6728" in rel_path:
        return "Fairway Cover"
    if "\u6df7\u5408\u6728" in rel_path:
        return "Hybrid Cover"
    if "推杆帽套" in rel_path:
        return "Putter Cover"
    if "铁杆帽套" in rel_path:
        return "Iron Cover"
    if "5号木帽套" in rel_path:
        return "5-Wood Cover"
    if "3号木帽套" in rel_path:
        return "3-Wood Cover"
    if "一号木帽套" in rel_path:
        return "Driver Cover"
    if "木杆帽套" in rel_path:
        return "Wood Cover"
    return ""


def ascii_product_name(name: str) -> str:
    name = unicodedata.normalize("NFKD", name.translate(ASCII_PRODUCT_TRANSLATION))
    name = name.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", name).strip()


def catalog_english_name(conn: sqlite3.Connection, sku: str) -> str:
    row = conn.execute("SELECT english_name FROM sku_meta WHERE sku=? AND english_name <> ''", (sku,)).fetchone()
    return ascii_product_name(row["english_name"]) if row else ""


def normalize_english_name(name: str, rel_path: str) -> str:
    glossary = glossary_name(rel_path)
    cover_type = cover_type_name(rel_path)
    if glossary:
        return f"{glossary} {cover_type}".strip()
    name = name.strip()
    if cover_type and cover_type.lower() not in name.lower():
        for suffix in KNOWN_COVER_TYPES:
            if name.lower().endswith(suffix.lower()):
                name = name[: -len(suffix)].strip()
                break
        return f"{name} {cover_type}".strip()
    return name


def default_drive_stem(sku: str, english_name: str, rel_path: str, fallback: str = "") -> str:
    prefix = "CF - " if "Craftsman" in rel_path else ""
    suffix = ""
    match = re.search(r"(\([^()]+\))$", Path(fallback).stem)
    if match:
        suffix = f" {match.group(1)}"
    return f"{sku} {prefix}{english_name}{suffix}".strip()


def better_drive_name(name: str, fallback: str, sku: str, english_name: str, rel_path: str = "") -> str:
    name = normalize_drive_name(name, fallback)
    stem = Path(name).stem
    product_parts = _product_name_parts(stem, sku) if sku else None
    exact_name_match = bool(
        product_parts
        and product_parts[1].casefold() == english_name.strip().casefold()
    )
    should_replace = (
        not is_english_drive_text(name)
        or name == fallback
        or (english_name and not exact_name_match)
    )
    if sku and english_name and should_replace:
        suffix_source = name if re.search(r"\([^()]+\)$", Path(name).stem) else fallback
        return normalize_drive_name(default_drive_stem(sku, english_name, rel_path, suffix_source), fallback)
    return name


def better_drive_folder(folder: str, sku: str, english_name: str) -> str:
    parts = split_drive_path(folder)
    if not parts or not sku or not english_name or sku not in parts[-1]:
        return folder
    match = re.match(rf"^{re.escape(sku)}(?:\s+[A-Z]{{2}})?\s+-\s+", parts[-1])
    parts[-1] = f"{match.group(0) if match else f'{sku} '}{english_name}"
    return "/".join(parts)


def confidence_value(value) -> float:
    if isinstance(value, str):
        named = {"high": 0.9, "medium": 0.6, "low": 0.3}
        value = named.get(value.strip().lower(), value)
    try:
        return max(0.0, min(1.0, float(value or 0)))
    except (TypeError, ValueError):
        return 0.0


def request_deepseek_suggestion(prompt: str) -> dict:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("Set DEEPSEEK_API_KEY to generate DeepSeek suggestions")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    system_prompt = """You produce conservative JSON suggestions for a human approval queue.
Return only one valid JSON object. All Google Drive names and folders must be English ASCII only.
Use exactly the keys and value types shown in this example.
EXAMPLE JSON OUTPUT:
{
  "sku": "6016271",
  "english_name": "Iron Cover Set",
  "drive_folder": "04 Product Images/01 Craftsman Golf/05 Iron Cover Set",
  "drive_name": "6016271 Iron Cover Set.jpg",
  "asset_type": "image",
  "confidence": 0.9,
  "reason": "SKU matched the source path.",
  "needs_manual_attention": false
}
Do not include markdown fences, comments, trailing commas, or text outside the JSON object."""
    attempts = 3
    last_error: Exception | None = None
    for attempt in range(attempts):
        response = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "response_format": {"type": "json_object"},
                "thinking": {"type": "disabled"},
                "temperature": 0,
                "max_tokens": 2400,
            },
            timeout=60,
        )
        response.raise_for_status()
        try:
            payload = response.json()
            choice = payload["choices"][0]
            if choice.get("finish_reason") == "length":
                raise ValueError("DeepSeek JSON response was truncated")
            return load_json_object(choice["message"].get("content") or "")
        except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(0.5 * (2**attempt))
    raise RuntimeError("DeepSeek returned invalid JSON after 3 attempts") from last_error


def request_ai_suggestion(row: sqlite3.Row, catalog: str, candidates: list[str]) -> dict:
    provider = (os.getenv("AI_PROVIDER") or ("deepseek" if os.getenv("DEEPSEEK_API_KEY") else "openai")).lower()
    prompt = suggestion_prompt(row, catalog, candidates)
    if provider == "deepseek":
        return request_deepseek_suggestion(prompt)
    if provider == "openai":
        return request_openai_suggestion(prompt)
    raise RuntimeError("AI_PROVIDER must be 'openai' or 'deepseek'")


def _catalog_drive_name(row: sqlite3.Row, sku: str, english_name: str) -> str:
    suffix = Path(str(row["name"] or "")).suffix.lower()
    if suffix not in MEDIA_EXTS:
        suffix = ".mp4" if is_video_import(row) else ".jpg"
    source_stem = Path(str(row["name"] or "")).stem.strip()
    sequence = ""
    if source_stem.isdigit():
        sequence = f" ({int(source_stem)})"
    else:
        numbered = re.search(r"\((\d+)\)$", source_stem)
        if numbered:
            sequence = f" ({int(numbered.group(1))})"
        elif source_stem and source_stem.isascii() and re.fullmatch(r"[A-Za-z0-9 _.-]+", source_stem):
            normalized = re.sub(r"\s+", " ", source_stem).strip(" ._-")
            if normalized and normalized.casefold() not in {sku.casefold(), english_name.casefold()}:
                sequence = f" ({normalized})"
        else:
            sequence = f" ({int(row['id'])})"
    return f"{sku} {english_name}{sequence}{suffix}"


def _set_catalog_import_pending(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    reason: str,
) -> None:
    with conn:
        conn.execute(
            """
            UPDATE nas_imports
            SET status='pending', reason=?, error='', updated_at=CURRENT_TIMESTAMP,
                revision=revision+1
            WHERE id=? AND revision=? AND status IN ('pending','suggested','error')
            """,
            (reason, int(row["id"]), int(row["revision"])),
        )


def suggest_import_from_catalog(conn: sqlite3.Connection, import_id: int) -> bool:
    """Populate a staging import only from one complete DingTalk catalogue row."""
    row = get_import(conn, import_id)
    if not row or row["status"] not in {"pending", "suggested", "error"}:
        return False
    primary_folder = source_product_folder(row["rel_path"])
    candidates = [candidate.upper() for candidate in sku_candidates(primary_folder)]
    if len(candidates) != 1:
        _set_catalog_import_pending(
            conn,
            row,
            "自动录入已暂停：临时产品目录中必须且只能包含一个 SKU。",
        )
        return False
    sku = candidates[0]
    product = dingtalk_catalog.product_for_sku(conn, sku)
    if not product:
        catalogue_rows = conn.execute(
            "SELECT validation_error FROM dingtalk_catalog_products WHERE sku=? AND partition_name=?",
            (sku, dingtalk_catalog.ACTIVE_PARTITION),
        ).fetchall()
        detail = "；".join(dict.fromkeys(str(item["validation_error"] or "记录不完整") for item in catalogue_rows))
        _set_catalog_import_pending(
            conn,
            row,
            f"自动录入已暂停：钉钉产品总表中没有唯一且完整的 SKU {sku}"
            + (f"（{detail}）" if detail else "。"),
        )
        return False

    english_name = str(product["english_name"] or "").strip()
    category_id = str(product["category_id"] or "").strip()
    drive_folder = canonical_product_drive_folder(
        conn,
        sku=sku,
        english_name=english_name,
        category_id=category_id,
        source_path="",
        suggested_folder="",
        set_code=str(product["set_code"] or ""),
    )
    drive_name = _catalog_drive_name(row, sku, english_name)
    if not drive_folder:
        _set_catalog_import_pending(
            conn,
            row,
            f"自动录入已暂停：无法根据钉钉产品总表为 SKU {sku} 确定目标目录。",
        )
        return False
    asset_type = "video" if is_video_import(row) else "image"
    validate_english_drive_fields(english_name, drive_folder, drive_name)
    reason = "钉钉产品总表唯一匹配，已使用表格英文品名、品牌和产品类型自动确定目录。"
    with conn:
        cursor = conn.execute(
            """
            UPDATE nas_imports
            SET status='suggested', suggested_sku=?, suggested_english_name=?,
                suggested_drive_folder=?, suggested_drive_name=?, suggested_asset_type=?,
                confidence=1, reason=?, final_sku=?, final_english_name=?,
                final_drive_folder=?, final_drive_name=?, final_asset_type=?, final_set_code=?,
                suggested_category_id=?, suggested_category_tags=?, category_confidence=1,
                category_source='dingtalk_aitable', category_reason=?, category_needs_review=0,
                final_category_id=?, final_category_tags=?, error='',
                updated_at=CURRENT_TIMESTAMP, revision=revision+1
            WHERE id=? AND revision=? AND status IN ('pending','suggested','error')
            """,
            (
                sku,
                english_name,
                drive_folder,
                drive_name,
                asset_type,
                reason,
                sku,
                english_name,
                drive_folder,
                drive_name,
                asset_type,
                str(product["set_code"] or ""),
                category_id,
                str(product["category_tags"] or ""),
                reason,
                category_id,
                str(product["category_tags"] or ""),
                int(row["id"]),
                int(row["revision"]),
            ),
        )
    return cursor.rowcount == 1


def _automatic_import_actor_id(conn: sqlite3.Connection) -> int | None:
    row = conn.execute(
        """
        SELECT id FROM users
        WHERE role IN ('super_admin', 'admin') AND disabled=0
        ORDER BY CASE WHEN name='刘芮华' THEN 0 WHEN role='super_admin' THEN 1 ELSE 2 END, id
        LIMIT 1
        """
    ).fetchone()
    return int(row["id"]) if row else None


def _catalog_attention_recipient_id(conn: sqlite3.Connection, recipient_name: str) -> str:
    recipient_user_id = os.getenv("DINGTALK_MISSING_SKU_RECIPIENT_USER_ID", "").strip()
    if recipient_user_id:
        return recipient_user_id
    recipient_user_id = db.dingtalk_provider_user_id_by_name(conn, recipient_name)
    if recipient_user_id:
        return recipient_user_id
    cached = db.dingtalk_organization_cache(conn)
    if not cached:
        return ""
    return next(
        (
            str(item.get("user_id") or "").strip()
            for item in cached["directory"].get("members", [])
            if str(item.get("name") or "").strip() == recipient_name
        ),
        "",
    )


def _catalog_attention_sku_groups(skus: list[str], max_length: int = 2800) -> list[list[str]]:
    if not skus:
        return [[]]
    groups: list[list[str]] = []
    current: list[str] = []
    current_length = 0
    for sku in skus:
        next_length = current_length + len(sku) + (1 if current else 0)
        if current and next_length > max_length:
            groups.append(current)
            current = []
            current_length = 0
        current.append(sku)
        current_length += len(sku) + (1 if len(current) > 1 else 0)
    if current:
        groups.append(current)
    return groups


def notify_catalog_import_attention(
    conn: sqlite3.Connection,
    skus: list[str],
    *,
    pending_file_count: int,
    error: str = "",
) -> bool:
    normalized_skus = list(
        dict.fromkeys(str(sku or "").strip().upper() for sku in skus if str(sku or "").strip())
    )
    if not normalized_skus and not error:
        return False
    actor_id = _automatic_import_actor_id(conn)
    if actor_id is None:
        raise RuntimeError("系统中没有可记录自动录入通知的管理员账号")
    recipient_name = os.getenv("DINGTALK_MISSING_SKU_RECIPIENT_NAME", "刘芮华").strip() or "刘芮华"
    recipient_user_id = _catalog_attention_recipient_id(conn, recipient_name)
    if not recipient_user_id:
        raise RuntimeError(f"未找到 {recipient_name} 的钉钉账号")

    notification_kind = "sync_error" if error else "missing_skus"
    fingerprint = hashlib.sha256(
        (f"catalog_auto_import:{notification_kind}\n" + "\n".join(sorted(normalized_skus))).encode("utf-8")
    ).hexdigest()
    if db.recent_missing_sku_notification(conn, actor_id, fingerprint):
        return False

    client_id = os.getenv("DINGTALK_CLIENT_ID", "").strip()
    client_secret = os.getenv("DINGTALK_CLIENT_SECRET", "").strip()
    agent_id = os.getenv("DINGTALK_AGENT_ID", "").strip()
    if not client_id or not client_secret or not agent_id:
        raise RuntimeError("DingTalk work notifications are not configured")

    groups = _catalog_attention_sku_groups(normalized_skus)
    task_ids: list[str] = []
    try:
        for index, group in enumerate(groups, start=1):
            page = f"（{index}/{len(groups)}）" if len(groups) > 1 else ""
            if error:
                lines = [
                    f"素材自动录入异常{page}",
                    "来源：每日 05:00 素材同步",
                    f"当前待录入素材：{max(0, int(pending_file_count))} 个",
                    "钉钉产品总表读取失败，素材已安全保留在待录入。",
                    f"错误：{error[:500]}",
                ]
                if group:
                    lines.extend(("涉及 SKU：", " ".join(group)))
            else:
                lines = [
                    f"素材自动录入待补充{page}",
                    "来源：每日 05:00 素材同步",
                    f"当前待录入素材：{max(0, int(pending_file_count))} 个",
                    f"钉钉产品总表未找到唯一且完整记录：{len(normalized_skus)} 个 SKU",
                    "请在产品目录_总表中补充或修正：",
                    " ".join(group),
                ]
            result = dingtalk_auth.send_work_notification(
                [recipient_user_id], "\n".join(lines), client_id, client_secret, agent_id
            )
            task_ids.append(str(result["task_id"]))
    except Exception as exc:
        db.record_missing_sku_notification(
            conn,
            user_id=actor_id,
            fingerprint=fingerprint,
            searched_count=max(0, int(pending_file_count)),
            missing_skus=normalized_skus,
            recipient_name=recipient_name,
            task_ids=task_ids,
            status="failed",
            error=str(exc) or type(exc).__name__,
        )
        raise

    db.record_missing_sku_notification(
        conn,
        user_id=actor_id,
        fingerprint=fingerprint,
        searched_count=max(0, int(pending_file_count)),
        missing_skus=normalized_skus,
        recipient_name=recipient_name,
        task_ids=task_ids,
        status="sent",
    )
    return True


def auto_import_catalog_matches(conn: sqlite3.Connection, root_id: str) -> int:
    state = conn.execute(
        "SELECT state FROM dingtalk_catalog_sync_state WHERE id=1"
    ).fetchone()
    if not state or state["state"] != "ok":
        return 0
    rows = conn.execute(
        """
        SELECT id FROM nas_imports
        WHERE status IN ('pending','suggested','error')
          AND local_path LIKE ?
        ORDER BY created_at, id
        """,
        (f"{GOOGLE_DRIVE_PREFIX}%",),
    ).fetchall()
    ready_ids = [
        int(row["id"])
        for row in rows
        if suggest_import_from_catalog(conn, int(row["id"]))
    ]
    if not ready_ids:
        return 0
    approved_by = _automatic_import_actor_id(conn)
    if approved_by is None:
        for import_id in ready_ids:
            current = get_import(conn, import_id)
            if current:
                _set_catalog_import_pending(conn, current, "自动录入已暂停：系统中没有可记录的管理员账号。")
        return 0
    return len(approve_imports(conn, ready_ids, root_id, approved_by))


def queue_catalog_auto_import_jobs(conn: sqlite3.Connection, root_id: str) -> list[str]:
    state = conn.execute(
        "SELECT state FROM dingtalk_catalog_sync_state WHERE id=1"
    ).fetchone()
    if not state or state["state"] != "ok":
        return []
    rows = conn.execute(
        """
        SELECT id FROM nas_imports
        WHERE status IN ('pending','suggested','error')
          AND local_path LIKE ?
        ORDER BY created_at, id
        """,
        (f"{GOOGLE_DRIVE_PREFIX}%",),
    ).fetchall()
    ready_ids = [
        int(row["id"])
        for row in rows
        if suggest_import_from_catalog(conn, int(row["id"]))
    ]
    if not ready_ids:
        return []
    used_names: dict[str, set[str]] = {}
    completed_targets = conn.execute(
        """
        SELECT final_drive_folder, final_drive_name
        FROM nas_imports
        WHERE status IN ('approved','uploaded')
          AND final_drive_folder<>'' AND final_drive_name<>''
        """
    ).fetchall()
    for target in completed_targets:
        folder_key = str(target["final_drive_folder"] or "").casefold()
        used_names.setdefault(folder_key, set()).add(str(target["final_drive_name"] or "").casefold())

    target_folders = {
        str(current["final_drive_folder"] or "")
        for import_id in ready_ids
        if (current := get_import(conn, import_id))
    }
    for folder in target_folders:
        folder_key = folder.casefold()
        prefix = f"{folder}/" if folder else ""
        existing_files = conn.execute(
            "SELECT path, name FROM files WHERE path LIKE ?",
            (f"{prefix}%",),
        ).fetchall()
        for file_row in existing_files:
            file_path = str(file_row["path"] or "")
            parent = file_path.rsplit("/", 1)[0] if "/" in file_path else ""
            if parent.casefold() == folder_key:
                used_names.setdefault(folder_key, set()).add(str(file_row["name"] or "").casefold())

    for import_id in ready_ids:
        current = get_import(conn, import_id)
        if not current:
            continue
        folder_key = str(current["final_drive_folder"] or "").casefold()
        reserved = used_names.setdefault(folder_key, set())
        proposed_name = str(current["final_drive_name"] or "")
        chosen_name = proposed_name
        if proposed_name.casefold() in reserved:
            suffix = Path(proposed_name).suffix.lower()
            sku = str(current["final_sku"] or "").strip().upper()
            english_name = str(current["final_english_name"] or "").strip()
            sequence = 1
            while True:
                candidate = f"{sku} {english_name} ({sequence}){suffix}"
                if candidate.casefold() not in reserved:
                    chosen_name = candidate
                    break
                sequence += 1
            with conn:
                conn.execute(
                    """
                    UPDATE nas_imports
                    SET suggested_drive_name=?, final_drive_name=?,
                        reason=reason || ' 目标文件名冲突，已自动分配唯一序号。',
                        updated_at=CURRENT_TIMESTAMP, revision=revision+1
                    WHERE id=? AND status='suggested'
                    """,
                    (chosen_name, chosen_name, import_id),
                )
        reserved.add(chosen_name.casefold())
    approved_by = _automatic_import_actor_id(conn)
    if approved_by is None:
        for import_id in ready_ids:
            current = get_import(conn, import_id)
            if current:
                _set_catalog_import_pending(conn, current, "自动录入已暂停：系统中没有可记录的管理员账号。")
        return []

    batches: dict[str, list[int]] = {}
    for import_id in ready_ids:
        row = get_import(conn, import_id)
        if row:
            batches.setdefault(import_batch_key(row), []).append(import_id)
    job_ids: list[str] = []
    for batch_key, import_ids in batches.items():
        for start in range(0, len(import_ids), 100):
            chunk = import_ids[start : start + 100]
            job = queue_import_job(
                conn,
                chunk,
                root_id,
                approved_by,
                batch_id=batch_key,
                batch_name=batch_key.split("/")[-1] or "自动入库",
            )
            job_ids.append(job["id"])
    return job_ids


def suggest_import(conn: sqlite3.Connection, import_id: int) -> None:
    row = get_import(conn, import_id)
    if not row:
        raise ValueError("NAS import not found")
    if row["status"] not in {"pending", "suggested", "error"}:
        raise ConcurrencyConflict("该素材已被其他管理员处理，请刷新后确认状态。")
    if dingtalk_catalog.enabled():
        suggest_import_from_catalog(conn, import_id)
        return
    primary_folder = source_product_folder(row["rel_path"])
    candidates = sku_candidates(f"{primary_folder} {row['rel_path']} {row['name']}")
    try:
        suggestion = request_ai_suggestion(row, drive_catalog(conn, candidates, row["rel_path"]), candidates)
        sku = (suggestion.get("sku") or "").strip().upper()
        primary_candidates = sku_candidates(primary_folder)
        if len(primary_candidates) == 1:
            primary_sku = primary_candidates[0].upper()
            if sku != primary_sku:
                suggestion["reason"] = (suggestion.get("reason") or "") + " Used the SKU from the primary source product folder."
            sku = primary_sku
            suggestion["sku"] = sku
        elif sku and sku not in [candidate.upper() for candidate in candidates]:
            suggestion["reason"] = (suggestion.get("reason") or "") + " SKU was not present in NAS path, cleared for manual review."
            suggestion["sku"] = ""
            suggestion["needs_manual_attention"] = True
            sku = ""
        try:
            drive_folder = ensure_relative_drive_path(suggestion.get("drive_folder") or "") if suggestion.get("drive_folder") else ""
        except ValueError:
            suggestion["reason"] = (suggestion.get("reason") or "") + " Drive folder was invalid, cleared for manual review."
            suggestion["needs_manual_attention"] = True
            drive_folder = ""
        if drive_folder and (
            not is_english_drive_text(drive_folder)
            or (row["rel_path"].startswith("产品图片/") and "product packaging" in drive_folder.lower())
        ):
            suggestion["reason"] = (suggestion.get("reason") or "") + " Google Drive folder was not a relevant English product-image path, cleared for manual review."
            suggestion["needs_manual_attention"] = True
            drive_folder = ""
        approved_name = catalog_english_name(conn, sku) if sku else ""
        english_name = approved_name or normalize_english_name(suggestion.get("english_name") or "", row["rel_path"])
        if approved_name:
            suggestion["reason"] = (suggestion.get("reason") or "") + " Used approved English name for the exact SKU."
            suggestion["confidence"] = max(confidence_value(suggestion.get("confidence")), 0.98)
            drive_folder = better_drive_folder(drive_folder, sku, english_name)
        if english_name and not is_english_drive_text(english_name):
            suggestion["reason"] = (suggestion.get("reason") or "") + " English name contained non-English text, cleared for manual review."
            suggestion["needs_manual_attention"] = True
            english_name = ""
        drive_name = better_drive_name(suggestion.get("drive_name") or "", row["name"], sku, english_name, row["rel_path"])
        if not is_english_drive_text(drive_name):
            suggestion["reason"] = (suggestion.get("reason") or "") + " Google Drive filename contained non-English text, cleared for manual review."
            suggestion["needs_manual_attention"] = True
            drive_name = ""
        asset_type = (
            "video"
            if is_video_import(row)
            else suggestion.get("asset_type") if suggestion.get("asset_type") in ASSET_TYPES else "image"
        )
        classification = product_taxonomy.classify_product(
            conn,
            sku=sku,
            name=row["rel_path"],
            english_name=english_name,
            path=row["rel_path"],
            external_id=str(import_id),
        )
        category_id = classification["category_id"]
        final_category_id = "" if category_id == "UNKNOWN" else category_id
        category_tags = "|".join(classification["tags"])
        catalog_set_code = sku_product_metadata(conn, sku)["set_code"] if sku else ""
        canonical_folder = canonical_product_drive_folder(
            conn,
            sku=sku,
            english_name=english_name,
            category_id=final_category_id,
            source_path=row["rel_path"],
            suggested_folder=drive_folder,
            set_code=catalog_set_code,
        )
        if canonical_folder:
            drive_folder = canonical_folder
        status = "pending" if suggestion.get("needs_manual_attention") or not all((sku, english_name, drive_folder, drive_name)) else "suggested"
        with conn:
            cursor = conn.execute(
                """
                UPDATE nas_imports
                SET status=?, suggested_sku=?, suggested_english_name=?, suggested_drive_folder=?,
                    suggested_drive_name=?, suggested_asset_type=?, confidence=?, reason=?,
                    final_sku=?, final_english_name=?, final_drive_folder=?, final_drive_name=?,
                    final_asset_type=?, final_set_code=?, suggested_category_id=?, suggested_category_tags=?,
                    category_confidence=?, category_source=?, category_reason=?,
                    category_needs_review=?, final_category_id=?, final_category_tags=?,
                    error='', updated_at=CURRENT_TIMESTAMP, revision=revision+1
                WHERE id=? AND revision=?
                """,
                (
                    status,
                    sku,
                    english_name,
                    drive_folder,
                    drive_name,
                    asset_type,
                    confidence_value(suggestion.get("confidence")),
                    suggestion.get("reason", ""),
                    sku,
                    english_name,
                    drive_folder,
                    drive_name,
                    asset_type,
                    catalog_set_code,
                    category_id,
                    category_tags,
                    classification["confidence"],
                    classification["source"],
                    classification["reason"] + (
                        f"；{'；'.join(classification['conflicts'])}" if classification["conflicts"] else ""
                    ),
                    int(classification["needs_review"] or classification["source"] not in {"sku_inheritance", "human_correction"}),
                    final_category_id,
                    category_tags,
                    import_id,
                    int(row["revision"]),
                ),
            )
            if cursor.rowcount != 1:
                raise ConcurrencyConflict("该素材在 AI 识别期间已被其他管理员修改，请刷新后重试。")
    except ConcurrencyConflict:
        raise
    except Exception as exc:
        with conn:
            conn.execute(
                "UPDATE nas_imports SET status='error', error=?, updated_at=CURRENT_TIMESTAMP, revision=revision+1 WHERE id=?",
                (str(exc), import_id),
            )


def _database_path(conn: sqlite3.Connection) -> str:
    for row in conn.execute("PRAGMA database_list"):
        if row[1] == "main":
            return row[2]
    return ""


def _suggest_import_with_connection(database_path: str, import_id: int, start_delay: float = 0) -> None:
    worker_conn = sqlite3.connect(database_path, timeout=30)
    worker_conn.row_factory = sqlite3.Row
    worker_conn.execute("PRAGMA foreign_keys = ON")
    worker_conn.execute("PRAGMA busy_timeout = 30000")
    try:
        if start_delay:
            time.sleep(start_delay)
        suggest_import(worker_conn, import_id)
    finally:
        worker_conn.close()


def suggest_imports(
    conn: sqlite3.Connection,
    import_ids: list[int],
    max_workers: int | None = None,
) -> int:
    unique_ids = [
        import_id
        for import_id in dict.fromkeys(import_ids)
        if (row := get_import(conn, import_id)) and row["status"] in {"pending", "suggested", "error"}
    ]
    if not unique_ids:
        return 0

    configured_workers = max_workers if max_workers is not None else int(os.getenv("AI_BULK_CONCURRENCY", "4"))
    worker_count = max(1, min(configured_workers, len(unique_ids), 8))
    database_path = _database_path(conn)
    if worker_count == 1 or not database_path:
        for import_id in unique_ids:
            suggest_import(conn, import_id)
        return len(unique_ids)

    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="ai-suggestion") as executor:
        list(executor.map(
            lambda item: _suggest_import_with_connection(database_path, item[1], item[0] * 0.01),
            enumerate(unique_ids),
        ))
    return len(unique_ids)


def _approval_fields(conn: sqlite3.Connection, row: sqlite3.Row, root_id: str) -> dict[str, str]:
    """Validate an import and return the final, upload-safe identity.

    Product assets are canonicalized here as a last line of defence.  This is
    intentionally repeated at approval time because batch settings can contain
    only the shared category folder and older saved rows may predate the
    product-folder rule.
    """
    sku = row["final_sku"].strip().upper()
    english_name = row["final_english_name"].strip()
    folder = ensure_relative_drive_path(row["final_drive_folder"])
    name = row["final_drive_name"].strip()
    asset_type = row["final_asset_type"].strip() or "image"
    category_id = row["final_category_id"].strip()
    category_required = folder in {"04 Product Images", "04 Product Images (No Brand)"} or folder.startswith(
        ("04 Product Images/", "04 Product Images (No Brand)/")
    )
    if category_required:
        product_taxonomy.validate_category_id(category_id, conn)
        folder = canonical_product_drive_folder(
            conn,
            sku=sku,
            english_name=english_name,
            category_id=category_id,
            source_path=row["rel_path"],
            suggested_folder=folder,
            set_code=row["final_set_code"],
        )
        folder_parts = split_drive_path(folder)
        brand_folder = folder_parts[1] if folder_parts and folder_parts[0] == "04 Product Images" and len(folder_parts) > 1 else ""
        expected_leaf = product_folder_name(sku, english_name, brand_folder)
        if not folder_parts or folder_parts[-1] != expected_leaf:
            raise ValueError(f"目标目录缺少产品目录：{expected_leaf}")
    validate_english_drive_fields(english_name, folder, name)
    if not sku or not english_name or not name or asset_type not in ASSET_TYPES:
        raise ValueError("Fill final SKU, English name, product category, Drive folder, Drive name, and asset type before approving")
    if is_google_drive_row(row) and not root_id:
        raise RuntimeError("DRIVE_ROOT_FOLDER_ID is not set")
    if not is_synology_row(row) and not is_google_drive_row(row):
        path = row_path(row)
        if not path.exists():
            raise FileNotFoundError(str(path))
        if not root_id:
            raise RuntimeError("DRIVE_ROOT_FOLDER_ID is not set")

    return {
        "sku": sku,
        "english_name": english_name,
        "folder": folder,
        "name": name,
        "asset_type": asset_type,
    }


def claim_import(
    conn: sqlite3.Connection,
    import_id: int,
    root_id: str,
    expected_revision: int | None = None,
) -> sqlite3.Row:
    row = get_import(conn, import_id)
    if not row:
        raise ValueError("NAS import not found")
    if row["status"] != "suggested":
        raise ConcurrencyConflict("该素材已被其他管理员处理或正在入库，请刷新后确认状态。")
    if expected_revision is None:
        expected_revision = int(row["revision"])
    if int(row["revision"]) != int(expected_revision):
        raise ConcurrencyConflict("该素材已被其他管理员修改，请刷新后重试。")
    fields = _approval_fields(conn, row, root_id)

    with conn:
        claimed = conn.execute(
            """
            UPDATE nas_imports
            SET status='approved', final_drive_folder=?, error='',
                updated_at=CURRENT_TIMESTAMP, revision=revision+1
            WHERE id=? AND status='suggested' AND revision=?
            """,
            (fields["folder"], import_id, expected_revision),
        )
        if claimed.rowcount != 1:
            raise ConcurrencyConflict("该素材已被其他管理员处理或正在入库，请刷新后确认状态。")
    return get_import(conn, import_id)


def upload_claimed_import(
    conn: sqlite3.Connection,
    import_id: int,
    root_id: str,
    approved_by: int,
    progress: Callable[[str, int], None] | None = None,
) -> str:
    row = get_import(conn, import_id)
    if not row or row["status"] != "approved":
        raise ConcurrencyConflict("该素材未处于待入库状态，请刷新后重试。")
    sku = row["final_sku"].strip().upper()
    english_name = row["final_english_name"].strip()
    folder = ensure_relative_drive_path(row["final_drive_folder"])
    name = row["final_drive_name"].strip()

    def report(stage: str, value: int) -> None:
        if progress:
            progress(stage, max(0, min(100, int(value))))

    report("preparing", 5)

    if is_synology_row(row):
        try:
            report("copying", 20)
            drive_file_id = copy_synology_to_google(row, folder, name)
            report("finalizing", 90)
            mark_uploaded(conn, import_id, sku, english_name, drive_file_id, approved_by)
            report("completed", 100)
            return drive_file_id
        except Exception as exc:
            with conn:
                conn.execute(
                    "UPDATE nas_imports SET status='error', error=?, updated_at=CURRENT_TIMESTAMP, revision=revision+1 WHERE id=? AND status IN ('approved','suggested')",
                    (str(exc), import_id),
                )
            raise

    if is_google_drive_row(row):
        try:
            report("preparing", 15)
            svc = drive.service([drive.DRIVE_WRITE_SCOPE])
            drive_file_id = source_drive_file_id(row)
            inbox_folder_id = os.getenv("GOOGLE_DRIVE_INBOX_FOLDER_ID", "").strip()
            source_metadata = drive.file_metadata(svc, drive_file_id)
            if inbox_folder_id and not drive.file_is_within_folder(
                svc,
                drive_file_id,
                inbox_folder_id,
                metadata=source_metadata,
            ):
                mark_uploaded(conn, import_id, sku, english_name, drive_file_id, approved_by)
                with conn:
                    conn.execute(
                        """
                        UPDATE nas_imports
                        SET reason=reason || ' 源文件已不在待录入临时目录，判定为已经使用，未重复移动。',
                            updated_at=CURRENT_TIMESTAMP, revision=revision+1
                        WHERE id=? AND status='uploaded'
                        """,
                        (import_id,),
                    )
                report("completed", 100)
                return drive_file_id

            # Jobs run concurrently. Keep the check-and-move operation atomic per
            # destination folder so two identical pending files cannot both see an
            # empty target and then move themselves into it.
            with _drive_target_lock(folder):
                parent_id = drive.ensure_folder_path(svc, root_id, split_drive_path(folder))
                checksum_field = next(
                    (
                        field
                        for field in ("md5Checksum", "sha256Checksum", "sha1Checksum")
                        if str(source_metadata.get(field) or "").strip()
                    ),
                    "",
                )
                source_checksum = str(source_metadata.get(checksum_field) or "").strip() if checksum_field else ""
                duplicate = None
                if source_checksum:
                    for target_item in drive.list_children(svc, parent_id):
                        if target_item.get("mimeType") == drive.FOLDER_MIME:
                            continue
                        target_checksum = str(target_item.get(checksum_field) or "").strip()
                        if target_item.get("id") == drive_file_id or target_checksum == source_checksum:
                            duplicate = target_item
                            break
                if duplicate:
                    existing_file_id = str(duplicate.get("id") or drive_file_id)
                    mark_uploaded(conn, import_id, sku, english_name, existing_file_id, approved_by)
                    with conn:
                        conn.execute(
                            """
                            UPDATE nas_imports
                            SET reason=reason || ' 目标产品目录已有内容相同的素材，判定为已经使用，未重复移动。',
                                updated_at=CURRENT_TIMESTAMP, revision=revision+1
                            WHERE id=? AND status='uploaded'
                            """,
                            (import_id,),
                        )
                    report("completed", 100)
                    return existing_file_id

                report("moving", 65)
                drive.move_file(svc, drive_file_id, parent_id, name)
                report("finalizing", 90)
                mark_uploaded(conn, import_id, sku, english_name, drive_file_id, approved_by)
                report("completed", 100)
                return drive_file_id
        except Exception as exc:
            with conn:
                conn.execute(
                    "UPDATE nas_imports SET status='error', error=?, updated_at=CURRENT_TIMESTAMP, revision=revision+1 WHERE id=? AND status IN ('approved','suggested')",
                    (str(exc), import_id),
                )
            raise

    path = row_path(row)

    try:
        report("preparing", 15)
        svc = drive.service([drive.DRIVE_WRITE_SCOPE])
        parent_id = drive.ensure_folder_path(svc, root_id, split_drive_path(folder))
        upload_args = (
            svc, path, parent_id, name,
            mimetypes.guess_type(name)[0] or "application/octet-stream",
            {"nasImportId": str(import_id), "nasSize": str(row["size"]), "nasMtimeNs": str(row["mtime_ns"])},
        )
        if progress:
            uploaded = drive.upload_file(
                *upload_args,
                progress=lambda completed, total: report(
                    "uploading",
                    20 + round(completed * 70 / total) if total else 90,
                ),
            )
        else:
            uploaded = drive.upload_file(*upload_args)
        drive_file_id = uploaded["id"]
        report("finalizing", 95)
        mark_uploaded(conn, import_id, sku, english_name, drive_file_id, approved_by)
        report("completed", 100)
        return drive_file_id
    except Exception as exc:
        with conn:
            conn.execute(
                "UPDATE nas_imports SET status='error', error=?, updated_at=CURRENT_TIMESTAMP, revision=revision+1 WHERE id=? AND status='approved'",
                (str(exc), import_id),
            )
        raise


def approve_import(
    conn: sqlite3.Connection,
    import_id: int,
    root_id: str,
    approved_by: int,
    expected_revision: int | None = None,
) -> str:
    claim_import(conn, import_id, root_id, expected_revision)
    return upload_claimed_import(conn, import_id, root_id, approved_by)


def _batch_identity(row: sqlite3.Row) -> tuple[str, str]:
    parts = split_drive_path(row["rel_path"])
    if parts and parts[-1] == row["name"]:
        parts = parts[:-1]
    batch_id = "/".join(parts) or f"import-{row['id']}"
    return batch_id, " · ".join(parts[-2:]) or "Unsorted import"


def _job_payload(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    items = [
        dict(item)
        for item in conn.execute(
            """
            SELECT import_id, name, rel_path, status, progress, stage, error, updated_at
            FROM nas_import_job_items
            WHERE job_id=?
            ORDER BY created_at, import_id
            """,
            (row["id"],),
        ).fetchall()
    ]
    total = len(items)
    completed = sum(item["status"] == "completed" for item in items)
    failed = sum(item["status"] == "error" for item in items)
    progress = round(sum(int(item["progress"]) for item in items) / total) if total else 0
    payload = dict(row)
    payload.update(
        {
            "total": total,
            "completed": completed,
            "failed": failed,
            "progress": progress,
            "items": items,
        }
    )
    return payload


def get_import_job(conn: sqlite3.Connection, job_id: str) -> dict | None:
    row = conn.execute(
        """
        SELECT jobs.*, COALESCE(NULLIF(users.name, ''), users.email, '') AS created_by_name
        FROM nas_import_jobs AS jobs
        LEFT JOIN users ON users.id = jobs.created_by
        WHERE jobs.id=?
        """,
        (job_id,),
    ).fetchone()
    return _job_payload(conn, row) if row else None


def list_import_jobs(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        """
        SELECT jobs.*, COALESCE(NULLIF(users.name, ''), users.email, '') AS created_by_name
        FROM nas_import_jobs AS jobs
        LEFT JOIN users ON users.id = jobs.created_by
        WHERE jobs.dismissed_at IS NULL
          AND (
            jobs.status IN ('queued', 'running', 'partial', 'failed')
            OR (
              jobs.status='completed'
              AND COALESCE(jobs.finished_at, jobs.updated_at) >= datetime('now', '-1 minute')
            )
          )
        ORDER BY
          CASE jobs.status
            WHEN 'running' THEN 0
            WHEN 'queued' THEN 1
            WHEN 'partial' THEN 2
            WHEN 'failed' THEN 3
            ELSE 4
          END,
          jobs.created_at DESC,
          jobs.id DESC
        LIMIT ?
        """,
        (max(1, min(int(limit), 100)),),
    ).fetchall()
    return [_job_payload(conn, row) for row in rows]


def dismiss_import_job(conn: sqlite3.Connection, job_id: str) -> dict:
    job = get_import_job(conn, job_id)
    if not job:
        raise ValueError("入库任务不存在。")
    if job["status"] not in {"partial", "failed"}:
        raise ConcurrencyConflict("只有失败或部分失败的入库任务可以手动关闭。")
    with conn:
        conn.execute(
            """
            UPDATE nas_import_jobs
            SET dismissed_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP
            WHERE id=? AND dismissed_at IS NULL
            """,
            (job_id,),
        )
    return get_import_job(conn, job_id)


def queue_import_job(
    conn: sqlite3.Connection,
    import_ids: list[int],
    root_id: str,
    approved_by: int,
    *,
    batch_id: str = "",
    batch_name: str = "",
) -> dict:
    unique_ids = list(dict.fromkeys(int(import_id) for import_id in import_ids))
    if not unique_ids:
        raise ValueError("没有可入库的素材。")
    rows = [row for import_id in unique_ids if (row := get_import(conn, import_id))]
    if not rows:
        raise ValueError("待入库素材不存在或已被处理。")
    derived_batch_id, derived_batch_name = _batch_identity(rows[0])
    job_id = uuid.uuid4().hex
    with conn:
        conn.execute(
            """
            INSERT INTO nas_import_jobs(id, batch_id, batch_name, status, created_by)
            VALUES (?, ?, ?, 'queued', ?)
            """,
            (job_id, batch_id.strip() or derived_batch_id, batch_name.strip() or derived_batch_name, approved_by),
        )

    queued = 0
    queued_import_ids: list[int] = []
    first_error: Exception | None = None
    for row in rows:
        try:
            claimed = claim_import(conn, int(row["id"]), root_id)
            item_status, item_stage, item_error = "queued", "queued", ""
            queued += 1
            queued_import_ids.append(int(claimed["id"]))
        except Exception as exc:
            claimed = row
            item_status, item_stage, item_error = "error", "error", str(exc)
            first_error = first_error or exc
        with conn:
            conn.execute(
                """
                INSERT INTO nas_import_job_items(
                  job_id, import_id, name, rel_path, status, progress, stage, error
                ) VALUES (?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    job_id,
                    int(claimed["id"]),
                    claimed["name"],
                    claimed["rel_path"],
                    item_status,
                    item_stage,
                    item_error,
                ),
            )

    if not queued:
        with conn:
            conn.execute(
                """
                UPDATE nas_import_jobs
                SET status='failed', finished_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (job_id,),
            )
        if first_error:
            raise first_error
        raise ValueError("没有可入库的素材。")
    placeholders = ",".join("?" for _ in queued_import_ids)
    with conn:
        conn.execute(
            f"""
            UPDATE nas_import_jobs
            SET dismissed_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP
            WHERE id<>?
              AND dismissed_at IS NULL
              AND status IN ('partial', 'failed')
              AND EXISTS (
                SELECT 1
                FROM nas_import_job_items AS previous_items
                WHERE previous_items.job_id=nas_import_jobs.id
                  AND previous_items.status='error'
                  AND previous_items.import_id IN ({placeholders})
              )
            """,
            (job_id, *queued_import_ids),
        )
    return get_import_job(conn, job_id)


def _set_job_item_progress(
    conn: sqlite3.Connection,
    job_id: str,
    import_id: int,
    *,
    status: str,
    stage: str,
    progress: int,
    error: str = "",
) -> None:
    with conn:
        conn.execute(
            """
            UPDATE nas_import_job_items
            SET status=?, stage=?, progress=?, error=?, updated_at=CURRENT_TIMESTAMP
            WHERE job_id=? AND import_id=?
            """,
            (status, stage, max(0, min(100, int(progress))), error, job_id, import_id),
        )
        conn.execute(
            "UPDATE nas_import_jobs SET updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (job_id,),
        )


def run_import_job(database_path: str | Path, job_id: str, root_id: str) -> dict | None:
    conn = db.connect(Path(database_path))
    try:
        job = get_import_job(conn, job_id)
        if not job:
            return None
        approved_by = int(job["created_by"] or 0)
        with conn:
            conn.execute(
                """
                UPDATE nas_import_jobs
                SET status='running', started_at=COALESCE(started_at, CURRENT_TIMESTAMP),
                    finished_at=NULL, updated_at=CURRENT_TIMESTAMP
                WHERE id=? AND status IN ('queued','running')
                """,
                (job_id,),
            )
        items = conn.execute(
            """
            SELECT import_id FROM nas_import_job_items
            WHERE job_id=? AND status IN ('queued','uploading')
            ORDER BY created_at, import_id
            """,
            (job_id,),
        ).fetchall()
        for item in items:
            import_id = int(item["import_id"])
            current = get_import(conn, import_id)
            if current and current["status"] == "uploaded":
                _set_job_item_progress(
                    conn, job_id, import_id,
                    status="completed", stage="completed", progress=100,
                )
                continue
            if not current or current["status"] != "approved":
                message = current["error"] if current and current["error"] else "素材不再处于待入库状态。"
                _set_job_item_progress(
                    conn, job_id, import_id,
                    status="error", stage="error", progress=0, error=message,
                )
                continue
            _set_job_item_progress(
                conn, job_id, import_id,
                status="uploading", stage="preparing", progress=5,
            )
            try:
                upload_claimed_import(
                    conn,
                    import_id,
                    root_id,
                    approved_by,
                    progress=lambda stage, value, item_id=import_id: _set_job_item_progress(
                        conn,
                        job_id,
                        item_id,
                        status="completed" if stage == "completed" else "uploading",
                        stage=stage,
                        progress=value,
                    ),
                )
            except Exception as exc:
                current_item = conn.execute(
                    "SELECT progress FROM nas_import_job_items WHERE job_id=? AND import_id=?",
                    (job_id, import_id),
                ).fetchone()
                _set_job_item_progress(
                    conn, job_id, import_id,
                    status="error", stage="error",
                    progress=int(current_item["progress"] if current_item else 0),
                    error=str(exc),
                )

        counts = conn.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed,
                   SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS failed
            FROM nas_import_job_items WHERE job_id=?
            """,
            (job_id,),
        ).fetchone()
        completed = int(counts["completed"] or 0)
        failed = int(counts["failed"] or 0)
        total = int(counts["total"] or 0)
        status = "completed" if completed == total else "failed" if failed == total else "partial"
        with conn:
            conn.execute(
                """
                UPDATE nas_import_jobs
                SET status=?, finished_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (status, job_id),
            )
        return get_import_job(conn, job_id)
    finally:
        conn.close()


def reset_interrupted_import_jobs(conn: sqlite3.Connection) -> list[str]:
    job_ids = [
        row["id"]
        for row in conn.execute(
            "SELECT id FROM nas_import_jobs WHERE status IN ('queued','running') ORDER BY created_at"
        ).fetchall()
    ]
    with conn:
        conn.execute(
            """
            UPDATE nas_import_job_items
            SET status='queued', stage='queued', updated_at=CURRENT_TIMESTAMP
            WHERE status='uploading'
            """
        )
        conn.execute(
            """
            UPDATE nas_import_jobs
            SET status='queued', finished_at=NULL, updated_at=CURRENT_TIMESTAMP
            WHERE status='running'
            """
        )
    return job_ids


def approve_imports(conn: sqlite3.Connection, import_ids: list[int], root_id: str, approved_by: int) -> list[str]:
    uploaded_ids: list[str] = []
    for import_id in dict.fromkeys(import_ids):
        row = get_import(conn, import_id)
        if not row or row["status"] != "suggested":
            continue
        try:
            uploaded_ids.append(approve_import(conn, import_id, root_id, approved_by))
        except ConcurrencyConflict:
            continue
        except Exception as exc:
            with conn:
                conn.execute(
                    "UPDATE nas_imports SET status='error', error=?, updated_at=CURRENT_TIMESTAMP, revision=revision+1 WHERE id=? AND status IN ('approved','suggested')",
                    (str(exc), import_id),
                )
    return uploaded_ids


def mark_uploaded(conn: sqlite3.Connection, import_id: int, sku: str, english_name: str, drive_file_id: str, approved_by: int) -> None:
    row = get_import(conn, import_id)
    set_code = db.normalize_set_code(row["final_set_code"] if row else "")
    category_id = (row["final_category_id"] if row else "").strip()
    category_tags = product_taxonomy.normalize_tags(row["final_category_tags"] if row else "")
    themes = (
        product_taxonomy.normalize_themes(row["final_themes"], conn)
        if row and row["themes_updated"]
        else None
    )
    with conn:
        _record_approved_edit_logs(conn, row, approved_by)
        conn.execute(
            """
            INSERT INTO sku_meta(sku, english_name, owner, notes, set_code)
            VALUES (?, ?, '', '', ?)
            ON CONFLICT(sku) DO UPDATE SET
              english_name=excluded.english_name,
              set_code=CASE WHEN excluded.set_code <> '' THEN excluded.set_code ELSE sku_meta.set_code END
            """,
            (sku, english_name, set_code),
        )
        if themes is not None:
            conn.execute("UPDATE sku_meta SET themes=? WHERE sku=?", (themes, sku))
        current_category = conn.execute(
            """
            SELECT category_id, category_tags, category_status, category_source
            FROM sku_meta WHERE sku=?
            """,
            (sku,),
        ).fetchone()
        already_verified = (
            current_category
            and current_category["category_id"] == category_id
            and current_category["category_tags"] == category_tags
            and current_category["category_status"] == "verified"
            and current_category["category_source"] in {"sku_registry", "human_correction", "dingtalk_aitable"}
        )
        if category_id and not already_verified:
            db.save_category_decision(
                conn,
                sku=sku,
                category_id=category_id,
                category_tags=category_tags,
                reviewer_id=approved_by,
                source="human_correction",
                note="管理员在素材入库时确认产品分类",
                import_id=import_id,
                previous_category_id=row["suggested_category_id"] if row else None,
                previous_tags=row["suggested_category_tags"] if row else None,
            )
        conn.execute(
            """
            UPDATE nas_imports
            SET status='uploaded', drive_file_id=?, error='', approved_at=CURRENT_TIMESTAMP,
                approved_by=?, updated_at=CURRENT_TIMESTAMP, revision=revision+1
            WHERE id=? AND status IN ('approved','suggested')
            """,
            (drive_file_id, approved_by, import_id),
        )
