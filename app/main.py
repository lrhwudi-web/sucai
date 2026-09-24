from __future__ import annotations

import os
import hashlib
import itertools
import json
import queue
import re
import secrets
import sqlite3
import threading
import time
import zipfile
import mimetypes
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, URLSafeSerializer

from . import db, dingtalk_auth, drive, inventory_source, local_media, nas_imports, product_taxonomy, thumbnails
from .logic import CUSTOMER_ACCOUNT_ROLES, FOLDER_MIME, PERMISSION_ROLES, ROLE_LABELS, ROLES, RULE_SCOPE_LABELS, RULE_SCOPES, display_folder_name, is_ignored_file, is_included_drive_collection, role_label

app = FastAPI(title="Material Index")
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["role_label"] = role_label
templates.env.globals["rule_scope_label"] = lambda scope: RULE_SCOPE_LABELS.get(scope, scope)
templates.env.globals["folder_label"] = display_folder_name
app.mount("/static", StaticFiles(directory="app/static"), name="static")
signer = URLSafeSerializer(os.getenv("APP_SECRET", "dev-change-me"))
DINGTALK_STATE_COOKIE = "dingtalk_oauth_state"
DINGTALK_STATE_MAX_AGE = 10 * 60
SESSION_MAX_AGE = max(300, int(os.getenv("SESSION_MAX_AGE_SECONDS", str(7 * 24 * 60 * 60))))
sync_lock = threading.Lock()
nas_scan_lock = threading.Lock()
zip_locks_guard = threading.Lock()
zip_locks: dict[str, threading.Lock] = {}
zip_jobs_guard = threading.Lock()
zip_jobs: dict[str, dict[str, str]] = {}
drive_copy_jobs_guard = threading.Lock()
drive_copy_jobs: dict[str, dict] = {}
drive_copy_job_keys: dict[str, str] = {}
IMPORT_UPLOAD_WORKERS = max(1, min(int(os.getenv("IMPORT_UPLOAD_WORKERS", "3")), 8))
import_upload_slots = threading.Semaphore(IMPORT_UPLOAD_WORKERS)
import_job_threads_guard = threading.Lock()
import_job_threads: set[str] = set()
ZIP_MAX_BYTES = int(os.getenv("ZIP_MAX_BYTES", str(2 * 1024 * 1024 * 1024)))
ZIP_MAX_FILES = int(os.getenv("ZIP_MAX_FILES", "500"))
ZIP_CACHE_DIR = Path(os.getenv("ZIP_CACHE_DIR", "data/zip_cache"))
DRIVE_CLIENT_EXPORT_FOLDER_ID = os.getenv(
    "DRIVE_CLIENT_EXPORT_FOLDER_ID",
    "1u3KmFXRHAfdMPjDD7JZ57F6dNZ5eiAVB",
).strip()
DRIVE_EXPORT_TTL_DAYS = max(1, int(os.getenv("DRIVE_EXPORT_TTL_DAYS", "15")))
DRIVE_EXPORT_CLEANUP_SECONDS = max(60, int(os.getenv("DRIVE_EXPORT_CLEANUP_SECONDS", "300")))
THUMB_CACHE_DIR = Path(os.getenv("THUMB_CACHE_DIR", str(ZIP_CACHE_DIR / "thumbs")))
PDF_CACHE_DIR = Path(os.getenv("PDF_CACHE_DIR", str(ZIP_CACHE_DIR / "pdfs")))
CUSTOMER_ORDER_DIR = Path(os.getenv("CUSTOMER_ORDER_DIR", str(db.DB_PATH.parent / "customer_orders")))
CUSTOMER_ORDER_MAX_BYTES = int(os.getenv("CUSTOMER_ORDER_MAX_BYTES", str(80 * 1024 * 1024)))
MISSING_SKU_RECIPIENT_NAME = os.getenv("DINGTALK_MISSING_SKU_RECIPIENT_NAME", "刘芮华").strip() or "刘芮华"
THUMBNAIL_QUEUE_SIZE = int(os.getenv("THUMBNAIL_QUEUE_SIZE", "512"))
THUMBNAIL_WORKERS = max(1, int(os.getenv("THUMBNAIL_WORKERS", "4")))
THUMBNAIL_CACHE_CLEANUP_SECONDS = max(
    3600,
    int(os.getenv("THUMBNAIL_CACHE_CLEANUP_SECONDS", str(6 * 60 * 60))),
)
THUMBNAIL_CACHE_GRACE_SECONDS = max(
    3600,
    int(os.getenv("THUMBNAIL_CACHE_GRACE_SECONDS", str(7 * 24 * 60 * 60))),
)
BROWSE_PAGE_SIZE = int(os.getenv("BROWSE_PAGE_SIZE", "600"))
PRODUCT_CATALOG_SNAPSHOT_TTL_SECONDS = max(
    30,
    int(os.getenv("PRODUCT_CATALOG_SNAPSHOT_TTL_SECONDS", "120")),
)
PRODUCT_CATALOG_SNAPSHOT_MAX_ENTRIES = max(
    2,
    int(os.getenv("PRODUCT_CATALOG_SNAPSHOT_MAX_ENTRIES", "12")),
)
product_catalog_snapshots_guard = threading.Lock()
product_catalog_snapshots: dict[str, dict] = {}
CHINA_TIMEZONE = timezone(timedelta(hours=8))
thumbnail_jobs: queue.PriorityQueue[tuple[int, int, dict[str, str]]] = queue.PriorityQueue(
    maxsize=THUMBNAIL_QUEUE_SIZE
)
thumbnail_job_sequence = itertools.count()
thumbnail_jobs_guard = threading.Lock()
thumbnail_jobs_pending: set[str] = set()
admin_import_thumbnail_locks_guard = threading.Lock()
admin_import_thumbnail_locks: dict[str, threading.Lock] = {}
admin_import_thumbnail_backfill_guard = threading.Lock()
admin_import_thumbnail_backfill_thread: threading.Thread | None = None
THUMBNAIL_PRIORITIES = {"drawer": 0, "small": 1, "card": 2}
THUMBNAIL_LOCAL_VARIANTS = ("small", "drawer")
THUMBNAIL_TRANSIENT_ERRORS = {
    "ConnectTimeout",
    "ConnectionError",
    "ProxyError",
    "ReadTimeout",
    "SSLError",
    "Timeout",
    "TimeoutError",
    "TransportError",
}
thumbnail_backfill_guard = threading.Lock()
thumbnail_backfill_requested = threading.Event()
thumbnail_backfill_thread: threading.Thread | None = None
catalog_pdf_backfill_guard = threading.Lock()
catalog_pdf_backfill_requested = threading.Event()
catalog_pdf_backfill_thread: threading.Thread | None = None
LEGACY_THUMBNAIL_TYPES = {
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
THUMBNAIL_PLACEHOLDER = b"""<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480" viewBox="0 0 640 480">
<rect width="640" height="480" fill="#edf1ee"/>
<g fill="none" stroke="#6f8176" stroke-width="12" stroke-linecap="round" stroke-linejoin="round">
<rect x="236" y="142" width="168" height="144" rx="16"/>
<circle cx="286" cy="192" r="17"/>
<path d="M252 258l56-58 38 38 28-28 42 48"/>
</g>
<text x="320" y="334" text-anchor="middle" fill="#526259" font-family="Arial,sans-serif" font-size="22">Preview loading</text>
</svg>"""


def english_name_from_path(path: str, sku: str) -> str:
    for part in reversed(path.replace("\\", "/").split("/")[:-1]):
        if not part.upper().startswith(sku.upper()):
            continue
        value = part[len(sku) :].strip(" -_")
        value = re.sub(r"^[A-Za-z][A-Za-z0-9]{1,11}\s*-\s*", "", value).strip(" -_")
        if value.isascii() and any(character.isalpha() for character in value):
            return value
    return ""


def other_asset_name_from_path(path: str, other: str) -> str:
    if not other or other == "No Brand":
        return ""
    folders = path.replace("\\", "/").split("/")[:-1]
    if len(folders) > 1:
        return display_folder_name(folders[1])
    return other


def product_cards(files, theme_options=None) -> list[dict]:
    products: dict[str, dict] = {}
    for row in files:
        sku = row["sku"]
        if not sku:
            continue
        modified_time = row["modified_time"] if "modified_time" in row.keys() else ""
        product = products.setdefault(
            sku,
            {
                "sku": sku,
                "name": (
                    row["english_name"]
                    or english_name_from_path(row["path"], sku)
                    or other_asset_name_from_path(row["path"], row["other"] if "other" in row.keys() else "")
                    or "English name not set"
                ),
                "chinese_name": row["chinese_name"] if "chinese_name" in row.keys() else "",
                "brand": row["brand"],
                "category": row["display_category"] if "display_category" in row.keys() else row["category"],
                "category_group": row["category_group"] if "category_group" in row.keys() else "",
                "other": row["other"] if "other" in row.keys() else "",
                "owner": row["owner"],
                "set_code": row["set_code"] if "set_code" in row.keys() else "",
                "themes": product_taxonomy.theme_labels(row["themes"], theme_options) if "themes" in row.keys() else [],
                "preferred_cover_id": row["cover_file_id"] if "cover_file_id" in row.keys() else "",
                "cover_id": "",
                "cover_mime": "",
                "cover_modified_time": "",
                "first_file_id": row["id"],
                "drive_path": "/".join(row["path"].replace("\\", "/").split("/")[:-1]),
                "modified_time": modified_time or "",
                "file_count": 0,
                "image_count": 0,
                "video_count": 0,
                "pdf_count": 0,
                "kol_count": 0,
                "other_count": 0,
                "internal_count": 0,
                "asset_types": set(),
            },
        )
        product["file_count"] += 1
        if (modified_time or "") > product["modified_time"]:
            product["modified_time"] = modified_time or ""
        product["asset_types"].add(row["asset_type"])
        if row["internal_only"]:
            product["internal_count"] += 1
        if row["asset_type"] == "kol_ugc":
            product["kol_count"] += 1
        if row["mime_type"].startswith("image/"):
            product["image_count"] += 1
            if not product["cover_id"] or row["id"] == product["preferred_cover_id"]:
                product["cover_id"] = row["id"]
                product["cover_mime"] = row["mime_type"]
                product["cover_modified_time"] = modified_time or ""
        elif row["mime_type"].startswith("video/"):
            product["video_count"] += 1
            if not product["cover_id"]:
                product["cover_id"] = row["id"]
                product["cover_mime"] = row["mime_type"]
                product["cover_modified_time"] = modified_time or ""
        elif row["mime_type"].lower().startswith("application/pdf"):
            product["pdf_count"] += 1
            product["other_count"] += 1
        elif row["asset_type"] != "kol_ugc":
            product["other_count"] += 1
    result = list(products.values())
    for product in result:
        product["asset_types"] = sorted(product["asset_types"])
        product.pop("preferred_cover_id", None)
    return result


def dashboard_stats(files, products: list[dict]) -> dict:
    return {
        "products": len(products),
        "files": len(files),
        "images": sum(1 for row in files if row["mime_type"].startswith("image/")),
        "videos": sum(1 for row in files if row["mime_type"].startswith("video/")),
    }


def file_stats(files) -> dict:
    return {
        "images": sum(1 for row in files if row["mime_type"].startswith("image/")),
        "videos": sum(1 for row in files if row["mime_type"].startswith("video/")),
        "other": sum(1 for row in files if not row["mime_type"].startswith(("image/", "video/"))),
    }


def safe_cache_name(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in value.strip())
    return cleaned or "sku"


def populate_product_catalog_pdf_cache(row, svc=None) -> Path:
    return local_media.ensure_pdf_cached(
        PDF_CACHE_DIR,
        row,
        lambda: drive.download_file(str(row["id"]), svc=svc),
    )


def warm_product_catalog_pdf_cache_all() -> tuple[int, int]:
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT id, name, mime_type, size, modified_time, other
            FROM files
            WHERE LOWER(mime_type) LIKE 'application/pdf%'
              AND other = 'Product Catalogs'
            ORDER BY id
            """
        ).fetchall()
    if not rows:
        return 0, 0

    svc = drive.service()
    ready = 0
    for row in rows:
        try:
            populate_product_catalog_pdf_cache(row, svc=svc)
            ready += 1
        except Exception as exc:
            print(
                f"Product Catalog PDF cache failed for {row['id']}: {type(exc).__name__}",
                flush=True,
            )
    print(
        f"Local Product Catalog PDF backfill complete: {ready}/{len(rows)} files ready",
        flush=True,
    )
    return ready, len(rows)


def product_catalog_pdf_backfill_loop() -> None:
    global catalog_pdf_backfill_thread
    try:
        while catalog_pdf_backfill_requested.is_set():
            catalog_pdf_backfill_requested.clear()
            try:
                warm_product_catalog_pdf_cache_all()
            except Exception as exc:
                print(
                    f"Local Product Catalog PDF backfill failed: {type(exc).__name__}",
                    flush=True,
                )
    finally:
        with catalog_pdf_backfill_guard:
            catalog_pdf_backfill_thread = None
        if catalog_pdf_backfill_requested.is_set():
            start_product_catalog_pdf_cache_backfill()


def start_product_catalog_pdf_cache_backfill() -> bool:
    global catalog_pdf_backfill_thread
    catalog_pdf_backfill_requested.set()
    with catalog_pdf_backfill_guard:
        if catalog_pdf_backfill_thread and catalog_pdf_backfill_thread.is_alive():
            return False
        catalog_pdf_backfill_thread = threading.Thread(
            target=product_catalog_pdf_backfill_loop,
            daemon=True,
            name="product-catalog-pdf-cache-backfill",
        )
        catalog_pdf_backfill_thread.start()
    return True


def thumbnail_row_value(row, key: str, default=""):
    try:
        return row[key]
    except (KeyError, TypeError, IndexError):
        return default


def thumbnail_placeholder_label(row) -> str:
    mime_type = str(thumbnail_row_value(row, "mime_type") or "")
    if mime_type == "image/x-photoshop":
        return "PSD"
    if mime_type.startswith("video/"):
        return "VIDEO"
    name = str(thumbnail_row_value(row, "name") or "")
    suffix = Path(name).suffix.lstrip(".")
    return suffix or "FILE"


def thumbnail_cache_entry(row, variant_name: str = "card"):
    path = thumbnails.cache_path(THUMB_CACHE_DIR, row, variant_name)
    return (path, "image/webp") if path.exists() else None


def admin_import_thumbnail_row(row) -> dict[str, str]:
    try:
        modified_time = str(row["mtime_ns"] or row["updated_at"] or "")
    except (KeyError, TypeError, IndexError):
        modified_time = ""
    return {
        "id": f"admin-nas-import:{row['id']}",
        "modified_time": modified_time,
        "name": str(row["name"] or ""),
        "mime_type": mimetypes.guess_type(str(row["name"] or ""))[0] or "",
    }


def admin_import_thumbnail_cache_path(row) -> Path:
    return thumbnails.cache_path(
        THUMB_CACHE_DIR / "imports",
        admin_import_thumbnail_row(row),
        "small",
    )


def admin_import_thumbnail_version(row) -> str:
    return thumbnails.cache_key(admin_import_thumbnail_row(row), "small")[:16]


def populate_admin_import_thumbnail_cache(row) -> Path:
    target = admin_import_thumbnail_cache_path(row)
    if target.exists():
        return target

    with admin_import_thumbnail_locks_guard:
        lock = admin_import_thumbnail_locks.setdefault(target.name, threading.Lock())
    with lock:
        if target.exists():
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        staging_path = target.with_name(
            f".{target.stem}.{os.getpid()}.{threading.get_ident()}.source"
        )
        try:
            if nas_imports.is_google_drive_row(row):
                try:
                    source, _content_type, _thumbnail_url = drive.download_thumbnail(
                        nas_imports.source_drive_file_id(row),
                        "",
                    )
                except RuntimeError:
                    if nas_imports.is_video_import(row):
                        return thumbnails.write_placeholder_webp(target, "small", "VIDEO")
                    raise
                return thumbnails.write_webp(source, target, "small")
            elif nas_imports.is_video_import(row):
                return thumbnails.write_placeholder_webp(target, "small", "VIDEO")
            elif nas_imports.is_synology_row(row):
                chunks = nas_imports.download_synology_import(row)
            else:
                source_path = nas_imports.row_path(row)
                if not source_path.exists():
                    raise FileNotFoundError(source_path)
                return thumbnails.write_webp(source_path, target, "small")

            with staging_path.open("wb") as output:
                for chunk in chunks:
                    output.write(chunk)
            return thumbnails.write_webp(staging_path, target, "small")
        finally:
            if staging_path.exists():
                staging_path.unlink()


def legacy_thumbnail_cache_entry(row):
    digest = thumbnails.legacy_cache_key(row)
    for suffix, content_type in LEGACY_THUMBNAIL_TYPES.items():
        path = THUMB_CACHE_DIR / f"{digest}{suffix}"
        if path.exists():
            return path, content_type
    return None


def provisional_thumbnail_cache_entry(row, variant_name: str):
    alternatives = {
        "drawer": ("card", "small"),
        "small": ("card", "drawer"),
        "card": ("small", "drawer"),
    }
    for alternative in alternatives[variant_name]:
        cached = thumbnail_cache_entry(row, alternative)
        if cached:
            return cached
    return legacy_thumbnail_cache_entry(row)


def populate_thumbnail_bundle(
    row,
    variant_names: tuple[str, ...] = THUMBNAIL_LOCAL_VARIANTS,
) -> dict[str, Path]:
    names = tuple(dict.fromkeys(thumbnails.variant(name).name for name in variant_names))
    generated = {}
    missing = []
    for name in names:
        cached = thumbnail_cache_entry(row, name)
        if cached:
            generated[name] = cached[0]
        else:
            missing.append(name)
    if not missing:
        return generated

    THUMB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    legacy = legacy_thumbnail_cache_entry(row)
    refreshed_url = str(thumbnail_row_value(row, "thumbnail_link") or "")
    if legacy:
        source = legacy[0]
    else:
        try:
            for attempt in range(4):
                try:
                    source, _content_type, refreshed_url = drive.download_thumbnail(
                        str(row["id"]),
                        str(thumbnail_row_value(row, "thumbnail_link") or ""),
                    )
                    break
                except Exception as exc:
                    if type(exc).__name__ not in THUMBNAIL_TRANSIENT_ERRORS or attempt == 3:
                        raise
                    time.sleep(0.5 * (2**attempt))
        except RuntimeError as exc:
            if "did not provide a thumbnail" not in str(exc):
                raise
            label = thumbnail_placeholder_label(row)
            for name in missing:
                cache_path = thumbnails.cache_path(THUMB_CACHE_DIR, row, name)
                generated[name] = thumbnails.write_placeholder_webp(cache_path, name, label)
            return generated

    for name in missing:
        cache_path = thumbnails.cache_path(THUMB_CACHE_DIR, row, name)
        generated[name] = thumbnails.write_webp(source, cache_path, name)

    if refreshed_url != str(thumbnail_row_value(row, "thumbnail_link") or ""):
        with db.connect() as conn:
            conn.execute(
                "UPDATE files SET thumbnail_link = ? WHERE id = ?",
                (refreshed_url, row["id"]),
            )
            conn.commit()
    return generated


def populate_thumbnail_cache(row, variant_name: str = "card") -> Path:
    spec = thumbnails.variant(variant_name)
    return populate_thumbnail_bundle(row, (spec.name,))[spec.name]


def schedule_thumbnail_warm(row, variant_name: str = "card") -> bool:
    spec = thumbnails.variant(variant_name)
    if thumbnail_cache_entry(row, spec.name):
        return False
    claim_key = thumbnails.cache_key(row, spec.name)
    snapshot = {
        "id": str(row["id"]),
        "modified_time": str(thumbnail_row_value(row, "modified_time") or ""),
        "thumbnail_link": str(thumbnail_row_value(row, "thumbnail_link") or ""),
        "name": str(thumbnail_row_value(row, "name") or ""),
        "mime_type": str(thumbnail_row_value(row, "mime_type") or ""),
        "size": str(thumbnail_row_value(row, "size", 0) or 0),
        "variant": spec.name,
        "cache_key": claim_key,
    }
    with thumbnail_jobs_guard:
        if claim_key in thumbnail_jobs_pending:
            return False
        thumbnail_jobs_pending.add(claim_key)
    try:
        thumbnail_jobs.put_nowait(
            (THUMBNAIL_PRIORITIES[spec.name], next(thumbnail_job_sequence), snapshot)
        )
    except queue.Full:
        with thumbnail_jobs_guard:
            thumbnail_jobs_pending.discard(claim_key)
        return False
    return True


def schedule_thumbnail_bundle(row, block: bool = True) -> bool:
    if all(thumbnail_cache_entry(row, name) for name in THUMBNAIL_LOCAL_VARIANTS):
        return False
    claim_key = f"bundle:{thumbnails.legacy_cache_key(row)}:{thumbnails.ENCODER_VERSION}"
    snapshot = {
        "id": str(row["id"]),
        "modified_time": str(thumbnail_row_value(row, "modified_time") or ""),
        "thumbnail_link": str(thumbnail_row_value(row, "thumbnail_link") or ""),
        "name": str(thumbnail_row_value(row, "name") or ""),
        "mime_type": str(thumbnail_row_value(row, "mime_type") or ""),
        "size": str(thumbnail_row_value(row, "size", 0) or 0),
        "variant": "bundle",
        "cache_key": claim_key,
    }
    with thumbnail_jobs_guard:
        if claim_key in thumbnail_jobs_pending:
            return False
        thumbnail_jobs_pending.add(claim_key)
    try:
        if block:
            thumbnail_jobs.put((3, next(thumbnail_job_sequence), snapshot))
        else:
            thumbnail_jobs.put_nowait((3, next(thumbnail_job_sequence), snapshot))
    except queue.Full:
        with thumbnail_jobs_guard:
            thumbnail_jobs_pending.discard(claim_key)
        return False
    return True


def thumbnail_warm_worker() -> None:
    while True:
        _priority, _sequence, row = thumbnail_jobs.get()
        try:
            try:
                if row["variant"] == "bundle":
                    populate_thumbnail_bundle(row)
                else:
                    populate_thumbnail_cache(row, row["variant"])
            except Exception as exc:
                print(
                    f"Thumbnail generation failed for {row['id']} ({row['variant']}): {type(exc).__name__}",
                    flush=True,
                )
        finally:
            with thumbnail_jobs_guard:
                thumbnail_jobs_pending.discard(row["cache_key"])
            thumbnail_jobs.task_done()


def warm_thumbnail_cache_all() -> tuple[int, int]:
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT f.id, f.name, f.modified_time, f.thumbnail_link, f.mime_type, f.size
            FROM files f
            LEFT JOIN sku_meta s ON s.cover_file_id = f.id
            WHERE f.mime_type LIKE 'image/%' OR f.mime_type LIKE 'video/%'
            ORDER BY
              CASE WHEN s.cover_file_id = f.id THEN 0 ELSE 1 END,
              CASE WHEN f.mime_type LIKE 'image/%' THEN 0 ELSE 1 END,
              f.synced_at DESC
            """
        ).fetchall()
    queued = sum(1 for row in rows if schedule_thumbnail_bundle(row, block=True))
    if queued:
        thumbnail_jobs.join()
    ready = sum(
        1
        for row in rows
        if all(thumbnail_cache_entry(row, name) for name in THUMBNAIL_LOCAL_VARIANTS)
    )
    print(
        f"Local thumbnail backfill complete: {ready}/{len(rows)} files ready "
        f"({queued} processed)",
        flush=True,
    )
    return ready, len(rows)


def thumbnail_backfill_loop() -> None:
    global thumbnail_backfill_thread
    try:
        while thumbnail_backfill_requested.is_set():
            thumbnail_backfill_requested.clear()
            try:
                warm_thumbnail_cache_all()
            except Exception as exc:
                print(f"Local thumbnail backfill failed: {type(exc).__name__}", flush=True)
    finally:
        with thumbnail_backfill_guard:
            thumbnail_backfill_thread = None
            restart = thumbnail_backfill_requested.is_set()
        if restart:
            start_thumbnail_cache_backfill()


def start_thumbnail_cache_backfill() -> bool:
    global thumbnail_backfill_thread
    thumbnail_backfill_requested.set()
    with thumbnail_backfill_guard:
        if thumbnail_backfill_thread and thumbnail_backfill_thread.is_alive():
            return False
        thumbnail_backfill_thread = threading.Thread(
            target=thumbnail_backfill_loop,
            daemon=True,
            name="thumbnail-cache-backfill",
        )
        thumbnail_backfill_thread.start()
    return True


def warm_admin_import_thumbnail_cache_all() -> tuple[int, int]:
    with db.connect() as conn:
        if os.getenv("GOOGLE_DRIVE_INBOX_FOLDER_ID", "").strip():
            rows = conn.execute(
                "SELECT * FROM nas_imports WHERE local_path LIKE ? ORDER BY id DESC",
                (f"{nas_imports.GOOGLE_DRIVE_PREFIX}%",),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM nas_imports ORDER BY id DESC"
            ).fetchall()
    ready = 0
    for row in rows:
        try:
            with db.connect() as conn:
                if not conn.execute(
                    "SELECT 1 FROM nas_imports WHERE id=?",
                    (row["id"],),
                ).fetchone():
                    continue
            populate_admin_import_thumbnail_cache(row)
            ready += 1
        except Exception:
            continue
    print(
        f"Admin import thumbnail backfill complete: {ready}/{len(rows)} files ready",
        flush=True,
    )
    return ready, len(rows)


def start_admin_import_thumbnail_backfill() -> bool:
    global admin_import_thumbnail_backfill_thread
    with admin_import_thumbnail_backfill_guard:
        if (
            admin_import_thumbnail_backfill_thread
            and admin_import_thumbnail_backfill_thread.is_alive()
        ):
            return False
        admin_import_thumbnail_backfill_thread = threading.Thread(
            target=warm_admin_import_thumbnail_cache_all,
            daemon=True,
            name="admin-import-thumbnail-backfill",
        )
        admin_import_thumbnail_backfill_thread.start()
    return True


def cleanup_thumbnail_cache_once() -> int:
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT id, modified_time
            FROM files
            WHERE mime_type LIKE 'image/%' OR mime_type LIKE 'video/%'
            """
        ).fetchall()
    active_names = thumbnails.active_cache_names(rows)
    active_names.update(thumbnails.active_legacy_cache_names(rows))
    return thumbnails.cleanup_cache(
        THUMB_CACHE_DIR,
        active_names,
        THUMBNAIL_CACHE_GRACE_SECONDS,
    )


def thumbnail_cache_cleanup_loop() -> None:
    while True:
        try:
            removed = cleanup_thumbnail_cache_once()
            if removed:
                print(f"Thumbnail cache cleanup removed {removed} stale file(s)", flush=True)
        except Exception as exc:
            print(f"Thumbnail cache cleanup failed: {type(exc).__name__}", flush=True)
        time.sleep(THUMBNAIL_CACHE_CLEANUP_SECONDS)


def zip_cache_digest(sku: str, role: str, files) -> str:
    digest = hashlib.sha256()
    digest.update(sku.upper().encode())
    digest.update(b"\0")
    digest.update(role.encode())
    for row in files:
        digest.update(str(row["id"]).encode())
        digest.update(b"\0")
        digest.update(str(row["size"] or 0).encode())
        digest.update(b"\0")
        digest.update(str(row["modified_time"] or "").encode())
        digest.update(b"\0")
        digest.update(str(row["path"]).encode())
        digest.update(b"\0")
    return digest.hexdigest()


def zip_cache_path(sku: str, role: str, files) -> Path:
    digest = zip_cache_digest(sku, role, files)
    name = f"{safe_cache_name(sku.upper())}-{safe_cache_name(role)}-{digest}.zip"
    return ZIP_CACHE_DIR / name


def zip_build_lock(cache_path: Path) -> threading.Lock:
    with zip_locks_guard:
        return zip_locks.setdefault(cache_path.name, threading.Lock())


def zip_context(sku: str, role: str, user_id: int | None = None):
    sku = sku.upper()
    with db.connect() as conn:
        files = [row for row in db.sku_files(conn, sku, role, user_id=user_id) if not is_ignored_file(row["name"])]
    if not files:
        raise HTTPException(404)
    total_size = sum(int(row["size"] or 0) for row in files)
    if len(files) > ZIP_MAX_FILES or total_size > ZIP_MAX_BYTES:
        raise HTTPException(413, f"Too large to zip: {len(files)} files, {total_size} bytes")
    return sku, files, zip_cache_path(sku, role, files)


def build_zip_cache(cache_path: Path, files, progress=None) -> None:
    if cache_path.exists():
        return
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with zip_build_lock(cache_path):
        if cache_path.exists():
            return
        tmp_path = cache_path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            svc = drive.service()
            total = len(files)
            with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_STORED) as zf:
                for completed, row in enumerate(files, 1):
                    with zf.open(row["path"], "w") as target:
                        for chunk in drive.download_file(row["id"], svc=svc):
                            target.write(chunk)
                    if progress:
                        progress(completed, total)
            os.replace(tmp_path, cache_path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()


def run_zip_job(cache_path: Path, files) -> None:
    def update_progress(completed: int, total: int) -> None:
        with zip_jobs_guard:
            zip_jobs[cache_path.name].update(
                completed=completed,
                total=total,
                progress=round(completed * 100 / total) if total else 100,
            )

    try:
        build_zip_cache(cache_path, files, update_progress)
        state = {"state": "ready", "error": "", "completed": len(files), "total": len(files), "progress": 100}
    except Exception as exc:
        state = {"state": "error", "error": str(exc), "progress": 0}
    with zip_jobs_guard:
        zip_jobs[cache_path.name] = state


def start_zip_job(cache_path: Path, files) -> str:
    if cache_path.exists():
        return "ready"
    with zip_jobs_guard:
        current = zip_jobs.get(cache_path.name)
        if current and current["state"] == "building":
            return "building"
        zip_jobs[cache_path.name] = {
            "state": "building",
            "error": "",
            "completed": 0,
            "total": len(files),
            "progress": 0,
        }
    threading.Thread(target=run_zip_job, args=(cache_path, files), daemon=True).start()
    return "building"


def drive_copy_context(sku: str, role: str, user_id: int | None = None):
    sku = sku.upper()
    with db.connect() as conn:
        files = [row for row in db.sku_files(conn, sku, role, user_id=user_id) if not is_ignored_file(row["name"])]
    if not files:
        raise HTTPException(404, detail="Product not found")
    if not DRIVE_CLIENT_EXPORT_FOLDER_ID:
        raise HTTPException(503, detail="The client Drive export folder is not configured")
    return sku, files


def drive_copy_state_payload(state: dict) -> dict:
    return {
        "job_id": state["job_id"],
        "sku": state["sku"],
        "state": state["state"],
        "progress": state.get("progress", 0),
        "completed": state.get("completed", 0),
        "total": state.get("total", 0),
        "error": state.get("error", ""),
        "folder_id": state.get("folder_id", ""),
        "folder_url": state.get("folder_url", ""),
        "expires_at": state.get("expires_at", ""),
    }


def drive_copy_state_is_active(state: dict, now: datetime | None = None) -> bool:
    if state.get("state") == "building":
        return True
    if state.get("state") != "ready" or not state.get("expires_at"):
        return False
    now = now or datetime.now(timezone.utc)
    try:
        expires_at = datetime.fromisoformat(str(state["expires_at"]).replace("Z", "+00:00"))
    except ValueError:
        return False
    return expires_at > now


def run_drive_copy_job(job_id: str, sku: str, files) -> None:
    total = len(files)

    def update_progress(completed: int, copy_total: int) -> None:
        with drive_copy_jobs_guard:
            state = drive_copy_jobs.get(job_id)
            if not state:
                return
            state.update(
                completed=completed,
                total=copy_total,
                progress=min(95, 5 + round(completed * 90 / copy_total)) if copy_total else 95,
            )

    try:
        svc = drive.service([drive.DRIVE_WRITE_SCOPE])
        source_folder = drive.find_sku_folder(svc, files[0]["id"], sku)
        result = drive.copy_accessible_folder(
            svc,
            source_folder["id"],
            DRIVE_CLIENT_EXPORT_FOLDER_ID,
            {str(row["id"]) for row in files},
            update_progress,
        )
        with drive_copy_jobs_guard:
            job_state = dict(drive_copy_jobs.get(job_id) or {})
        created_at = datetime.now(timezone.utc)
        expires_at = created_at + timedelta(days=DRIVE_EXPORT_TTL_DAYS)
        try:
            conn = db.connect()
            try:
                db.record_drive_export(
                    conn,
                    job_key=job_state["job_key"],
                    user_id=job_state["user_id"],
                    sku=sku,
                    folder_id=result["folder_id"],
                    folder_url=result["folder_url"],
                    parent_id=DRIVE_CLIENT_EXPORT_FOLDER_ID,
                    created_at=created_at,
                    expires_at=expires_at,
                )
            finally:
                conn.close()
        except Exception:
            try:
                drive.delete_export_folder(svc, result["folder_id"], DRIVE_CLIENT_EXPORT_FOLDER_ID)
            except Exception:
                pass
            raise
        update = {
            "state": "ready",
            "error": "",
            "completed": result["file_count"],
            "total": result["file_count"],
            "progress": 100,
            "folder_id": result["folder_id"],
            "folder_url": result["folder_url"],
            "expires_at": db.utc_timestamp(expires_at),
        }
    except Exception as exc:
        update = {
            "state": "error",
            "error": str(exc),
            "completed": 0,
            "total": total,
            "progress": 0,
            "folder_id": "",
            "folder_url": "",
            "expires_at": "",
        }
    with drive_copy_jobs_guard:
        if job_id in drive_copy_jobs:
            drive_copy_jobs[job_id].update(update)


def start_drive_copy_job(sku: str, role: str, user_id: str, files) -> dict:
    digest = zip_cache_digest(sku, role, files)
    job_key = f"{user_id}:{digest}"
    conn = db.connect()
    try:
        persisted = db.active_drive_export(conn, job_key, datetime.now(timezone.utc))
    finally:
        conn.close()
    with drive_copy_jobs_guard:
        existing_job_id = drive_copy_job_keys.get(job_key)
        existing = drive_copy_jobs.get(existing_job_id or "")
        if existing and drive_copy_state_is_active(existing):
            return drive_copy_state_payload(existing)
        if persisted:
            job_id = secrets.token_urlsafe(18)
            state = {
                "job_id": job_id,
                "job_key": job_key,
                "user_id": str(user_id),
                "sku": sku,
                "state": "ready",
                "progress": 100,
                "completed": len(files),
                "total": len(files),
                "error": "",
                "folder_id": persisted["folder_id"],
                "folder_url": persisted["folder_url"],
                "expires_at": persisted["expires_at"],
            }
            drive_copy_jobs[job_id] = state
            drive_copy_job_keys[job_key] = job_id
            return drive_copy_state_payload(state)

        job_id = secrets.token_urlsafe(18)
        state = {
            "job_id": job_id,
            "job_key": job_key,
            "user_id": str(user_id),
            "sku": sku,
            "state": "building",
            "progress": 5,
            "completed": 0,
            "total": len(files),
            "error": "",
            "folder_id": "",
            "folder_url": "",
            "expires_at": "",
        }
        drive_copy_jobs[job_id] = state
        drive_copy_job_keys[job_key] = job_id
    threading.Thread(target=run_drive_copy_job, args=(job_id, sku, files), daemon=True).start()
    return drive_copy_state_payload(state)


def browse_page(role: str, q: str, brand: str, category: str, other: str, asset_type: str, limit: int, offset: int, user_id: int | None = None) -> dict:
    limit = max(1, min(limit, 1000))
    offset = max(0, offset)
    with db.connect() as conn:
        files = db.search_files(conn, role, q, brand, category, other, asset_type, limit=limit + 1, offset=offset, user_id=user_id)
        theme_options = product_taxonomy.theme_options(conn)
    has_more = len(files) > limit
    page_files = files[:limit]
    products = product_cards(page_files, theme_options)
    return {
        "files": page_files,
        "products": products,
        "stats": dashboard_stats(page_files, products),
        "next_offset": offset + limit,
        "has_more": has_more,
    }


def product_catalog_snapshot_key(
    role: str,
    q: str,
    brand: str,
    category: str,
    other: str,
    asset_type: str,
    user_id: int | None = None,
) -> tuple:
    return (str(user_id or ""), role, q, brand, category, other, asset_type)


def clear_product_catalog_snapshots() -> None:
    with product_catalog_snapshots_guard:
        product_catalog_snapshots.clear()


def cleanup_product_catalog_snapshots(now: float | None = None) -> None:
    now = time.monotonic() if now is None else now
    expired = [
        token
        for token, snapshot in product_catalog_snapshots.items()
        if now - snapshot["created_at"] >= PRODUCT_CATALOG_SNAPSHOT_TTL_SECONDS
    ]
    for token in expired:
        product_catalog_snapshots.pop(token, None)


def get_product_catalog_snapshot(token: str, key: tuple) -> dict | None:
    if not token:
        return None
    with product_catalog_snapshots_guard:
        cleanup_product_catalog_snapshots()
        snapshot = product_catalog_snapshots.get(token)
        if not snapshot or snapshot["key"] != key:
            return None
        return snapshot


def store_product_catalog_snapshot(key: tuple, payload: dict) -> tuple[str, dict]:
    token = secrets.token_urlsafe(18)
    snapshot = {
        "key": key,
        "created_at": time.monotonic(),
        "products": payload["products"],
        "stats": payload["stats"],
    }
    with product_catalog_snapshots_guard:
        cleanup_product_catalog_snapshots(snapshot["created_at"])
        while len(product_catalog_snapshots) >= PRODUCT_CATALOG_SNAPSHOT_MAX_ENTRIES:
            oldest = min(product_catalog_snapshots, key=lambda item: product_catalog_snapshots[item]["created_at"])
            product_catalog_snapshots.pop(oldest, None)
        product_catalog_snapshots[token] = snapshot
    return token, snapshot


def build_product_catalog_snapshot(
    role: str,
    q: str,
    brand: str,
    category: str,
    other: str,
    asset_type: str,
    user_id: int | None = None,
) -> dict:
    with db.connect() as conn:
        file_count = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        files = db.search_files(
            conn,
            role,
            q,
            brand,
            category,
            other,
            asset_type,
            limit=max(file_count, 1),
            user_id=user_id,
        )
        theme_options = product_taxonomy.theme_options(conn)
    products = product_cards(files, theme_options)
    return {
        "products": products,
        "stats": dashboard_stats(files, products),
    }


def product_catalog_page(
    role: str,
    q: str,
    brand: str,
    category: str,
    other: str,
    asset_type: str,
    limit: int,
    offset: int,
    user_id: int | None = None,
    snapshot_token: str = "",
) -> dict:
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    key = product_catalog_snapshot_key(role, q, brand, category, other, asset_type, user_id)
    snapshot = get_product_catalog_snapshot(snapshot_token, key)
    if snapshot is None:
        payload = build_product_catalog_snapshot(role, q, brand, category, other, asset_type, user_id)
        snapshot_token, snapshot = store_product_catalog_snapshot(key, payload)
    products = snapshot["products"]
    page_products = products[offset : offset + limit]
    return {
        "products": page_products,
        "stats": snapshot["stats"],
        "total": len(products),
        "next_offset": offset + len(page_products),
        "has_more": offset + len(page_products) < len(products),
        "snapshot_token": snapshot_token,
    }


def parse_range_header(value: str, size: int) -> tuple[int, int] | None:
    if not value.startswith("bytes=") or size <= 0:
        return None
    spec = value.removeprefix("bytes=").split(",", 1)[0].strip()
    if "-" not in spec:
        return None
    start_text, end_text = spec.split("-", 1)
    try:
        if start_text:
            start = int(start_text)
            end = int(end_text) if end_text else size - 1
        else:
            suffix_size = int(end_text)
            start = max(size - suffix_size, 0)
            end = size - 1
    except ValueError:
        return None
    if start < 0 or start >= size or end < start:
        return None
    return start, min(end, size - 1)


def option_rows(values: tuple[str, ...], labels: dict[str, str]) -> list[dict]:
    return [{"value": value, "label": labels.get(value, value)} for value in values]


@app.on_event("startup")
def startup() -> None:
    with db.connect() as conn:
        db.init_db(conn)
        interrupted_import_jobs = nas_imports.reset_interrupted_import_jobs(conn)
    for job_id in interrupted_import_jobs:
        start_import_job(job_id, os.getenv("DRIVE_ROOT_FOLDER_ID", ""))
    thread = threading.Thread(target=sync_loop, daemon=True)
    thread.start()
    for _worker in range(THUMBNAIL_WORKERS):
        threading.Thread(target=thumbnail_warm_worker, daemon=True).start()
    start_thumbnail_cache_backfill()
    start_admin_import_thumbnail_backfill()
    start_product_catalog_pdf_cache_backfill()
    threading.Thread(target=thumbnail_cache_cleanup_loop, daemon=True).start()
    if DRIVE_CLIENT_EXPORT_FOLDER_ID:
        threading.Thread(target=drive_export_cleanup_loop, daemon=True).start()
    if os.getenv("DRIVE_ROOT_FOLDER_ID"):
        threading.Thread(target=nas_scan_loop, daemon=True).start()


def run_import_job_in_background(job_id: str, root_id: str) -> None:
    try:
        with import_upload_slots:
            result = nas_imports.run_import_job(db.DB_PATH.resolve(), job_id, root_id)
        if result and result.get("completed"):
            try:
                run_sync()
            except Exception as exc:
                print(f"Drive sync after import job {job_id} failed: {exc}", flush=True)
    except Exception as exc:
        print(f"Import job {job_id} failed: {exc}", flush=True)
    finally:
        with import_job_threads_guard:
            import_job_threads.discard(job_id)


def start_import_job(job_id: str, root_id: str) -> bool:
    with import_job_threads_guard:
        if job_id in import_job_threads:
            return False
        import_job_threads.add(job_id)
    threading.Thread(
        target=run_import_job_in_background,
        args=(job_id, root_id),
        name=f"nas-import-{job_id[:8]}",
        daemon=True,
    ).start()
    return True


def sync_loop() -> None:
    while True:
        time.sleep(seconds_until_drive_sync())
        run_scheduled_drive_sync_once()


def run_scheduled_drive_sync_once() -> int | None:
    try:
        count = run_sync()
        print(f"Drive sync completed: {count} files at 05:00 China time", flush=True)
    except Exception as exc:
        print(f"Drive sync failed: {exc}", flush=True)
        try:
            send_drive_sync_notification(error=exc)
        except Exception as notification_exc:
            print(f"DingTalk Drive sync notification failed: {notification_exc}", flush=True)
        return None

    try:
        send_drive_sync_notification(
            file_count=count,
            missing_english_name_count=count_products_missing_english_names(),
        )
    except Exception as notification_exc:
        print(f"DingTalk Drive sync notification failed: {notification_exc}", flush=True)
    return count


def count_products_missing_english_names(conn=None) -> int:
    owns_connection = conn is None
    database = conn or db.connect()
    try:
        rows = database.execute(
            """
            SELECT f.sku, f.path, COALESCE(m.english_name, '') AS english_name
            FROM files f
            LEFT JOIN sku_meta m ON m.sku=f.sku
            WHERE f.sku <> ''
              AND (
                f.path LIKE '04 Product Images/%'
                OR f.path LIKE '04 Product Images (No Brand)/%'
              )
            """
        ).fetchall()
        all_skus: set[str] = set()
        named_skus: set[str] = set()
        for row in rows:
            sku = str(row["sku"] or "").strip()
            if not sku:
                continue
            all_skus.add(sku)
            if str(row["english_name"] or "").strip() or english_name_from_path(row["path"], sku):
                named_skus.add(sku)
        return len(all_skus - named_skus)
    finally:
        if owns_connection:
            database.close()


def drive_sync_recipient_user_ids() -> list[str]:
    raw_value = os.getenv("DINGTALK_SYNC_RECIPIENT_USER_IDS", "")
    return list(
        dict.fromkeys(
            value
            for value in re.split(r"[\s,;]+", raw_value.strip())
            if value
        )
    )


def drive_sync_notification_message(
    *,
    file_count: int | None = None,
    missing_english_name_count: int | None = None,
    error: Exception | str | None = None,
    now: datetime | None = None,
) -> str:
    finished_at = (now or datetime.now(CHINA_TIMEZONE)).astimezone(CHINA_TIMEZONE)
    lines = [
        "素材平台每日同步结果",
        f"时间：{finished_at:%Y-%m-%d %H:%M:%S}",
        f"状态：{'失败' if error else '成功'}",
    ]
    if error:
        error_text = re.sub(r"\s+", " ", str(error)).strip() or type(error).__name__
        lines.append(f"错误：{error_text[:500]}")
    else:
        lines.append(f"已索引文件：{int(file_count or 0):,}")
        if missing_english_name_count is not None:
            lines.append(f"缺少英文品名的 SKU：{max(0, int(missing_english_name_count)):,}")
    return "\n".join(lines)


def send_drive_sync_notification(
    *,
    file_count: int | None = None,
    missing_english_name_count: int | None = None,
    error: Exception | str | None = None,
    now: datetime | None = None,
) -> dict[str, str | int]:
    recipients = drive_sync_recipient_user_ids()
    if not recipients:
        raise RuntimeError("DingTalk Drive sync recipient is not configured")
    client_id, client_secret = dingtalk_credentials()
    agent_id = os.getenv("DINGTALK_AGENT_ID", "").strip()
    if not agent_id:
        raise RuntimeError("DingTalk work notifications are not configured")
    return dingtalk_auth.send_work_notification(
        recipients,
        drive_sync_notification_message(
            file_count=file_count,
            missing_english_name_count=missing_english_name_count,
            error=error,
            now=now,
        ),
        client_id,
        client_secret,
        agent_id,
    )


def run_nas_scan(blocking: bool = True) -> int:
    if not nas_scan_lock.acquire(blocking=blocking):
        raise RuntimeError("NAS scan already running")
    try:
        with db.connect() as conn:
            db.init_db(conn)
            count, job_ids = nas_imports.scan_sources(conn)
        root_id = os.getenv("DRIVE_ROOT_FOLDER_ID", "")
        for job_id in job_ids:
            start_import_job(job_id, root_id)
        start_admin_import_thumbnail_backfill()
        return count
    finally:
        nas_scan_lock.release()


def seconds_until_daily_0500(now: datetime | None = None) -> float:
    now = now or datetime.now(CHINA_TIMEZONE)
    target = now.replace(hour=5, minute=0, second=0, microsecond=0)
    if now > target:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def seconds_until_drive_sync(now: datetime | None = None) -> float:
    return seconds_until_daily_0500(now)


def seconds_until_nas_scan(now: datetime | None = None) -> float:
    return seconds_until_daily_0500(now)


def nas_scan_loop() -> None:
    while True:
        time.sleep(seconds_until_nas_scan())
        try:
            queued = run_nas_scan(blocking=False)
            print(f"NAS scan completed: {queued} queued", flush=True)
        except Exception as exc:
            print(f"NAS scan failed: {exc}", flush=True)


def cleanup_expired_drive_exports(now: datetime | None = None, conn=None) -> int:
    now = now or datetime.now(timezone.utc)
    owns_connection = conn is None
    database = conn or db.connect()
    try:
        expired = db.expired_drive_exports(database, now)
        if not expired:
            return 0
        svc = drive.service([drive.DRIVE_WRITE_SCOPE])
        deleted = 0
        for export in expired:
            try:
                if export["parent_id"] != DRIVE_CLIENT_EXPORT_FOLDER_ID:
                    raise RuntimeError("Refusing to delete a Drive export registered outside the configured directory")
                drive.delete_export_folder(svc, export["folder_id"], DRIVE_CLIENT_EXPORT_FOLDER_ID)
                db.mark_drive_export_deleted(database, export["id"], now)
                deleted += 1
            except Exception as exc:
                db.mark_drive_export_delete_error(database, export["id"], str(exc))
                print(f"Drive export cleanup failed for {export['folder_id']}: {exc}", flush=True)
        return deleted
    finally:
        if owns_connection:
            database.close()


def drive_export_cleanup_loop() -> None:
    while True:
        try:
            deleted = cleanup_expired_drive_exports()
            if deleted:
                print(f"Drive export cleanup deleted {deleted} expired folder(s)", flush=True)
        except Exception as exc:
            print(f"Drive export cleanup failed: {exc}", flush=True)
        time.sleep(DRIVE_EXPORT_CLEANUP_SECONDS)


def run_sync() -> int:
    root_id = os.getenv("DRIVE_ROOT_FOLDER_ID")
    if not root_id:
        raise RuntimeError("DRIVE_ROOT_FOLDER_ID is not set")
    if not sync_lock.acquire(blocking=False):
        raise RuntimeError("sync already running")
    try:
        with db.connect() as conn:
            db.init_db(conn)
            conn.execute(
                """
                UPDATE sync_status
                SET root_id=?, state='running', message='', started_at=CURRENT_TIMESTAMP, finished_at=NULL
                WHERE id=1
                """,
                (root_id,),
            )
            conn.commit()
        rows = drive.scan_drive(root_id)
        with db.connect() as conn:
            db.init_db(conn)
            count = db.replace_files(conn, rows)
            conn.execute(
                """
                UPDATE sync_status
                SET state='ok', message='', finished_at=CURRENT_TIMESTAMP, file_count=?
                WHERE id=1
                """,
                (count,),
            )
            conn.commit()
        start_thumbnail_cache_backfill()
        start_product_catalog_pdf_cache_backfill()
        return count
    except Exception as exc:
        with db.connect() as conn:
            db.init_db(conn)
            conn.execute(
                """
                UPDATE sync_status
                SET root_id=?, state='error', message=?, finished_at=CURRENT_TIMESTAMP
                WHERE id=1
                """,
                (root_id, str(exc)),
            )
            conn.commit()
        raise
    finally:
        sync_lock.release()


def current_user(request: Request):
    token = request.cookies.get("session")
    if not token:
        return None
    try:
        user_id = signer.loads(token)
    except BadSignature:
        return None
    with closing(db.connect()) as conn:
        db.disable_expired_customer_accounts(conn)
        return conn.execute("SELECT * FROM users WHERE id = ? AND disabled = 0", (user_id,)).fetchone()


def require_user(request: Request):
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user


def require_api_user(request: Request):
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def require_admin(user=Depends(require_user)):
    if user["role"] not in {"super_admin", "admin"}:
        raise HTTPException(403)
    return user


def require_api_admin(user=Depends(require_api_user)):
    if user["role"] not in {"super_admin", "admin"}:
        raise HTTPException(403, detail="Administrator access required")
    return user


def require_super_admin(user=Depends(require_user)):
    if user["role"] != "super_admin":
        raise HTTPException(403, detail="Super administrator access required")
    return user


def require_api_super_admin(user=Depends(require_api_user)):
    if user["role"] != "super_admin":
        raise HTTPException(403, detail="Super administrator access required")
    return user


def user_payload(user) -> dict:
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "role": user["role"],
        "is_admin": user["role"] in {"super_admin", "admin"},
        "is_super_admin": user["role"] == "super_admin",
    }


def password_login_allowed(user) -> bool:
    return bool(user) and user["role"] not in {"super_admin", "admin"}


def account_id(user) -> int | None:
    if isinstance(user, dict):
        value = user.get("id")
    else:
        value = user["id"] if "id" in user.keys() else None
    return int(value) if value is not None else None


def wants_json(request: Request) -> bool:
    return "application/json" in request.headers.get("accept", "").lower()


def secure_cookie_request(request: Request) -> bool:
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip().lower()
    return request.url.scheme == "https" or forwarded_proto == "https"


def set_session_cookie(response: Response, request: Request, user_id: int) -> None:
    response.set_cookie(
        "session",
        signer.dumps(user_id),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=secure_cookie_request(request),
        samesite="lax",
        path="/",
    )


def dingtalk_redirect_uri(request: Request) -> str:
    configured = os.getenv("DINGTALK_REDIRECT_URI", "").strip()
    if configured:
        return configured
    referer = urlparse(request.headers.get("referer", ""))
    if referer.scheme in {"http", "https"} and referer.hostname in {"127.0.0.1", "localhost"}:
        return f"{referer.scheme}://{referer.netloc}/auth/dingtalk/callback"
    return str(request.url_for("dingtalk_callback"))


def dingtalk_credentials() -> tuple[str, str]:
    client_id = os.getenv("DINGTALK_CLIENT_ID", "").strip()
    client_secret = os.getenv("DINGTALK_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise HTTPException(503, "DingTalk login is not configured")
    return client_id, client_secret


def customer_order_public_origin(request: Request) -> str:
    configured = os.getenv("CUSTOMER_ORDER_PUBLIC_URL", "").strip().rstrip("/")
    if configured:
        parsed = urlparse(configured)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    redirect = urlparse(dingtalk_redirect_uri(request))
    if redirect.scheme in {"http", "https"} and redirect.netloc:
        return f"{redirect.scheme}://{redirect.netloc}"
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip()
    forwarded_host = request.headers.get("x-forwarded-host", "").split(",", 1)[0].strip()
    if forwarded_proto in {"http", "https"} and forwarded_host:
        return f"{forwarded_proto}://{forwarded_host}"
    return str(request.base_url).rstrip("/")


def customer_order_file_name(customer_name: str, submitted_at: datetime | None = None) -> str:
    submitted_at = submitted_at or datetime.now(CHINA_TIMEZONE)
    safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", customer_name).strip(" ._")[:80]
    return f"{safe_name or 'Customer'}_{submitted_at:%Y-%m-%d}.xlsx"


def customer_order_payload(row) -> dict:
    try:
        items = json.loads(row["items_json"] or "[]")
    except (json.JSONDecodeError, TypeError):
        items = []
    if not isinstance(items, list):
        items = []
    return {
        "id": int(row["id"]),
        "order_number": row["order_number"],
        "customer_name": row["customer_name"],
        "customer_email": row["customer_email"],
        "salesperson_name": row["salesperson_name"],
        "title": row["title"],
        "company": row["company"],
        "contact": row["contact"],
        "reference": row["reference"],
        "currency": row["currency"],
        "product_count": int(row["product_count"]),
        "total_quantity": int(row["total_quantity"]),
        "total_amount_cents": int(row["total_amount_cents"]),
        "unpriced_count": int(row["unpriced_count"]),
        "items": items,
        "file_name": row["file_name"],
        "file_size": int(row["file_size"]),
        "notification_status": row["notification_status"],
        "status": row["status"] or "new",
        "confirmed_at": row["confirmed_at"] or "",
        "created_at": row["created_at"],
        "download_url": f"/api/orders/{int(row['id'])}/download",
    }


def validate_customer_order_workbook(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as workbook:
            names = set(workbook.namelist())
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError("The generated Excel file is not a valid .xlsx workbook.") from exc
    if "[Content_Types].xml" not in names or "xl/workbook.xml" not in names:
        raise ValueError("The generated Excel file is not a valid .xlsx workbook.")


def validate_customer_order_items(raw: object, product_count: int, total_quantity: int) -> str:
    if raw is None or not isinstance(raw, str):
        raw = "[]"
    try:
        source = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "The order product details are invalid") from exc
    if not isinstance(source, list) or len(source) > 5000:
        raise HTTPException(400, "The order product details are invalid")
    items: list[dict[str, object]] = []
    for value in source:
        if not isinstance(value, dict):
            raise HTTPException(400, "The order product details are invalid")
        sku = str(value.get("sku") or "").strip()
        name = str(value.get("name") or "").strip()
        try:
            quantity = int(value.get("quantity") or 0)
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, "The order product details are invalid") from exc
        if not sku or len(sku) > 120 or len(name) > 300 or not 1 <= quantity <= 5_000_000_000:
            raise HTTPException(400, "The order product details are invalid")
        normalized: dict[str, object] = {"sku": sku, "name": name or sku, "quantity": quantity}
        for source_key, target_key in (("unitPriceCents", "unit_price_cents"), ("amountCents", "amount_cents")):
            cents = value.get(source_key, value.get(target_key))
            if cents is None:
                normalized[target_key] = None
                continue
            try:
                cents = int(cents)
            except (TypeError, ValueError) as exc:
                raise HTTPException(400, "The order product details are invalid") from exc
            if not 0 <= cents <= 10**15:
                raise HTTPException(400, "The order product details are invalid")
            normalized[target_key] = cents
        image_url = str(value.get("imageUrl", value.get("image_url", "")) or "").strip()
        normalized["image_url"] = image_url[:500] if image_url.startswith("/thumb/") and "://" not in image_url else ""
        items.append(normalized)
    if items and (len(items) != product_count or sum(int(item["quantity"]) for item in items) != total_quantity):
        raise HTTPException(400, "The order product details do not match the order totals")
    return json.dumps(items, ensure_ascii=False, separators=(",", ":"))


def validate_customer_order_inventory(
    items: list[dict[str, object]],
    catalog_draft: dict[str, object] | None,
    salesperson_name: str,
) -> None:
    if not items:
        return
    fallback: dict[str, int] = {}
    lines = catalog_draft.get("lines") if isinstance(catalog_draft, dict) else None
    if isinstance(lines, dict):
        for raw_sku, raw_line in lines.items():
            if not isinstance(raw_sku, str) or not isinstance(raw_line, dict):
                continue
            raw_inventory = raw_line.get("inventory")
            try:
                inventory = int(raw_inventory)
            except (TypeError, ValueError):
                continue
            if inventory >= 0 and str(raw_inventory).strip().isdigit():
                fallback[raw_sku.strip().upper()] = inventory

    skus = [str(item["sku"]).strip().upper() for item in items]
    lookup = inventory_source.lookup_available_inventory(skus, salesperson_name)
    limits = dict(fallback)
    limits.update({str(sku).strip().upper(): max(0, int(value)) for sku, value in lookup.values.items()})
    unavailable: list[str] = []
    exceeded: list[tuple[str, int, int]] = []
    requested: dict[str, int] = {}
    display_skus: dict[str, str] = {}
    for item, sku in zip(items, skus):
        requested[sku] = requested.get(sku, 0) + int(item["quantity"])
        display_skus.setdefault(sku, str(item["sku"]))
    for sku, quantity in requested.items():
        limit = limits.get(sku)
        if limit is None:
            unavailable.append(display_skus[sku])
        elif quantity > limit:
            exceeded.append((display_skus[sku], quantity, limit))
    if unavailable:
        listed = ", ".join(unavailable[:5])
        suffix = f" and {len(unavailable) - 5} more" if len(unavailable) > 5 else ""
        raise HTTPException(409, f"Inventory is unavailable for SKU {listed}{suffix}. Refresh the catalog and try again.")
    if exceeded:
        sku, quantity, limit = exceeded[0]
        raise HTTPException(409, f"SKU {sku}: order quantity {quantity:,} cannot exceed inventory ({limit:,}).")


def admin_pending_redirect(import_id: int | None = None) -> RedirectResponse:
    location = "/admin?section=pending"
    if import_id:
        location += f"&import_id={import_id}"
    return RedirectResponse(location, status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": ""})


@app.get("/auth/dingtalk/start")
@app.get("/api/auth/dingtalk/start")
def dingtalk_start(request: Request):
    client_id, _client_secret = dingtalk_credentials()
    state = secrets.token_urlsafe(32)
    location = dingtalk_auth.authorization_url(client_id, dingtalk_redirect_uri(request), state)
    response = RedirectResponse(location, status_code=302)
    response.set_cookie(
        DINGTALK_STATE_COOKIE,
        state,
        max_age=DINGTALK_STATE_MAX_AGE,
        httponly=True,
        secure=secure_cookie_request(request),
        samesite="lax",
        path="/",
    )
    response.delete_cookie(DINGTALK_STATE_COOKIE, path="/auth/dingtalk")
    return response


@app.get("/auth/dingtalk/callback")
@app.get("/api/auth/dingtalk/callback")
def dingtalk_callback(
    request: Request,
    authCode: str = "",
    code: str = "",
    state: str = "",
    error: str = "",
):
    if error:
        return RedirectResponse(f"/?dingtalk_error={quote('DingTalk authorization was cancelled.')}", status_code=303)
    expected_state = request.cookies.get(DINGTALK_STATE_COOKIE, "")
    if not state or not expected_state or not secrets.compare_digest(state, expected_state):
        raise HTTPException(400, "Invalid or expired DingTalk login state")
    oauth_code = (authCode or code).strip()
    if not oauth_code:
        raise HTTPException(400, "DingTalk authorization code is missing")

    client_id, client_secret = dingtalk_credentials()
    try:
        access_token = dingtalk_auth.exchange_code(oauth_code, client_id, client_secret)
        profile = dingtalk_auth.get_user_profile(access_token)
        try:
            membership = dingtalk_auth.get_organization_membership(profile, client_id, client_secret)
            provider_user_id = str(membership.get("user_id") or "").strip()
            department_names = membership.get("department_names") or []
            departments_verified = True
        except dingtalk_auth.DingTalkAuthError:
            provider_user_id = ""
            department_names = []
            departments_verified = False
        with closing(db.connect()) as conn:
            db.init_db(conn)
            user = db.find_or_create_dingtalk_user(
                conn,
                profile,
                provider_user_id=provider_user_id,
                department_names=department_names,
                departments_verified=departments_verified,
            )
            db.record_user_activity(conn, int(user["id"]), "login", detail="dingtalk")
    except (dingtalk_auth.DingTalkAuthError, ValueError, sqlite3.Error):
        response = RedirectResponse(
            f"/?dingtalk_error={quote('DingTalk login failed. Please try again.')}",
            status_code=303,
        )
        response.delete_cookie(DINGTALK_STATE_COOKIE, path="/")
        response.delete_cookie(DINGTALK_STATE_COOKIE, path="/auth/dingtalk")
        return response

    response = RedirectResponse("/#catalogue", status_code=303)
    set_session_cookie(response, request, int(user["id"]))
    response.delete_cookie(DINGTALK_STATE_COOKIE, path="/")
    response.delete_cookie(DINGTALK_STATE_COOKIE, path="/auth/dingtalk")
    return response


@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    admin_password_login_blocked = False
    authentication_status = "invalid"
    with closing(db.connect()) as conn:
        db.init_db(conn)
        user, authentication_status = db.authenticate_with_status(conn, email, password)
        if user and not password_login_allowed(user):
            admin_password_login_blocked = True
            user = None
        if user:
            db.record_user_activity(conn, int(user["id"]), "login", detail="password")
    if not user:
        error = (
            "Administrator accounts must sign in with DingTalk"
            if admin_password_login_blocked
            else "This account has been disabled."
            if authentication_status == "disabled"
            else "Invalid email or password"
        )
        if wants_json(request):
            return JSONResponse({"detail": error}, status_code=401)
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": error},
            status_code=401,
        )
    response = JSONResponse({"user": user_payload(user)}) if wants_json(request) else RedirectResponse("/", status_code=303)
    set_session_cookie(response, request, int(user["id"]))
    return response


@app.post("/logout")
def logout(request: Request):
    response = JSONResponse({"signed_out": True}) if wants_json(request) else RedirectResponse("/login", status_code=303)
    response.delete_cookie("session")
    return response


@app.get("/api/session")
def api_session(user=Depends(require_api_user)):
    return {"user": user_payload(user)}


@app.post("/api/orders")
async def api_create_customer_order(
    request: Request,
    idempotency_key: str = Form(...),
    title: str = Form(""),
    company: str = Form(""),
    contact: str = Form(""),
    reference: str = Form(""),
    currency: str = Form("USD"),
    product_count: int = Form(...),
    total_quantity: int = Form(...),
    total_amount_cents: int = Form(...),
    unpriced_count: int = Form(0),
    items_json: str = Form("[]"),
    excel_file: UploadFile = File(...),
    user=Depends(require_api_user),
):
    if user["role"] not in CUSTOMER_ACCOUNT_ROLES:
        raise HTTPException(403, "Only customer accounts can place orders")
    idempotency_key = idempotency_key.strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", idempotency_key):
        raise HTTPException(400, "The order request ID is invalid")
    text_fields = {
        "title": title.strip(),
        "company": company.strip(),
        "contact": contact.strip(),
        "reference": reference.strip(),
    }
    if any(len(value) > 120 for value in text_fields.values()):
        raise HTTPException(400, "Order details are too long")
    currency = currency.strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise HTTPException(400, "The order currency is invalid")
    if not 1 <= product_count <= 5000:
        raise HTTPException(400, "An order must contain between 1 and 5,000 products")
    if not 1 <= total_quantity <= 5_000_000_000:
        raise HTTPException(400, "An order must contain at least one item")
    if not 0 <= total_amount_cents <= 10**15 or not 0 <= unpriced_count <= product_count:
        raise HTTPException(400, "The order totals are invalid")
    normalized_items_json = validate_customer_order_items(items_json, product_count, total_quantity)
    normalized_items = json.loads(normalized_items_json)

    with closing(db.connect()) as conn:
        db.init_db(conn)
        existing = db.customer_order_by_idempotency(conn, int(user["id"]), idempotency_key)
        if existing:
            return {"order": customer_order_payload(existing), "created": False}
        salesperson = db.customer_order_salesperson(conn, int(user["id"]))
        if not salesperson:
            raise HTTPException(409, "This customer account is not assigned to a salesperson yet")
        salesperson_user_id = int(salesperson["id"])
        catalog_order = db.sales_catalog_order_for_user(conn, int(user["id"]))

    validate_customer_order_inventory(
        normalized_items,
        catalog_order.get("draft") if isinstance(catalog_order, dict) else None,
        str(salesperson["name"] or ""),
    )

    submitted_at = datetime.now(CHINA_TIMEZONE)
    order_number = f"ORD-{submitted_at:%Y%m%d}-{secrets.token_hex(4).upper()}"
    stored_file_name = f"{order_number}-{secrets.token_hex(8)}.xlsx"
    file_name = customer_order_file_name(str(user["name"] or user["email"]), submitted_at)
    download_token = secrets.token_urlsafe(32)
    download_token_hash = hashlib.sha256(download_token.encode("utf-8")).hexdigest()
    CUSTOMER_ORDER_DIR.mkdir(parents=True, exist_ok=True)
    final_path = CUSTOMER_ORDER_DIR / stored_file_name
    staging_path = CUSTOMER_ORDER_DIR / f".{stored_file_name}.{secrets.token_hex(4)}.upload"
    file_size = 0
    try:
        with staging_path.open("wb") as output:
            while True:
                chunk = await excel_file.read(1024 * 1024)
                if not chunk:
                    break
                file_size += len(chunk)
                if file_size > CUSTOMER_ORDER_MAX_BYTES:
                    raise HTTPException(413, "The Excel file exceeds the 80 MB order limit")
                output.write(chunk)
        if file_size <= 0:
            raise HTTPException(400, "The generated Excel file is empty")
        try:
            validate_customer_order_workbook(staging_path)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        os.replace(staging_path, final_path)

        try:
            with closing(db.connect()) as conn:
                db.init_db(conn)
                order = db.create_customer_order(
                    conn,
                    order_number=order_number,
                    idempotency_key=idempotency_key,
                    customer_user_id=int(user["id"]),
                    salesperson_user_id=salesperson_user_id,
                    customer_name=str(user["name"] or user["email"]),
                    customer_email=str(user["email"]),
                    title=text_fields["title"],
                    company=text_fields["company"],
                    contact=text_fields["contact"],
                    reference=text_fields["reference"],
                    currency=currency,
                    product_count=product_count,
                    total_quantity=total_quantity,
                    total_amount_cents=total_amount_cents,
                    unpriced_count=unpriced_count,
                    items_json=normalized_items_json,
                    file_name=file_name,
                    stored_file_name=stored_file_name,
                    file_size=file_size,
                    download_token_hash=download_token_hash,
                )
        except sqlite3.IntegrityError:
            final_path.unlink(missing_ok=True)
            with closing(db.connect()) as conn:
                existing = db.customer_order_by_idempotency(conn, int(user["id"]), idempotency_key)
                if existing:
                    return {"order": customer_order_payload(existing), "created": False}
            raise
    except Exception:
        staging_path.unlink(missing_ok=True)
        if final_path.exists():
            with closing(db.connect()) as conn:
                existing = db.customer_order_by_idempotency(conn, int(user["id"]), idempotency_key)
            if not existing:
                final_path.unlink(missing_ok=True)
        raise

    notification_status = "sent"
    notification_error = ""
    try:
        with closing(db.connect()) as conn:
            recipient_user_id = db.dingtalk_provider_user_id_for_user(conn, salesperson_user_id)
        if not recipient_user_id:
            raise RuntimeError("The assigned salesperson has no DingTalk identity")
        client_id, client_secret = dingtalk_credentials()
        agent_id = os.getenv("DINGTALK_AGENT_ID", "").strip()
        if not agent_id:
            raise RuntimeError("DingTalk work notifications are not configured")
        download_url = (
            f"{customer_order_public_origin(request)}/api/orders/{int(order['id'])}/download"
            f"?token={quote(download_token)}"
        )
        amount = f"{currency} {total_amount_cents / 100:,.2f}"
        price_note = f"{amount}（另有 {unpriced_count} 款待询价）" if unpriced_count else amount
        message = "\n".join(
            [
                "新客户订单",
                f"客户：{user['name']}（{user['email']}）",
                f"订单号：{order_number}",
                f"时间：{submitted_at:%Y-%m-%d %H:%M}",
                f"商品：{product_count} 款，共 {total_quantity} 件",
                f"金额：{price_note}",
                f"下载 Excel：{download_url}",
            ]
        )
        result = dingtalk_auth.send_work_notification(
            [recipient_user_id], message, client_id, client_secret, agent_id
        )
        notification_task_id = str(result["task_id"])
    except Exception as exc:
        notification_status = "failed"
        notification_task_id = ""
        notification_error = str(exc) or type(exc).__name__

    with closing(db.connect()) as conn:
        db.update_customer_order_notification(
            conn,
            int(order["id"]),
            status=notification_status,
            task_id=notification_task_id,
            error=notification_error,
        )
        order = db.customer_order_by_id(conn, int(order["id"]))
    payload = {"order": customer_order_payload(order), "created": True}
    if notification_status == "failed":
        payload["notification_warning"] = "Order saved, but the salesperson notification could not be delivered."
    return payload


@app.get("/api/orders")
def api_customer_orders(user=Depends(require_api_user)):
    with closing(db.connect()) as conn:
        db.init_db(conn)
        rows = db.list_customer_orders_for_user(conn, int(user["id"]), str(user["role"]))
    return {"orders": [customer_order_payload(row) for row in rows]}


@app.get("/api/orders/pending-count")
def api_pending_customer_order_count(user=Depends(require_api_admin)):
    with closing(db.connect()) as conn:
        db.init_db(conn)
        pending_count = db.pending_customer_order_count_for_user(
            conn,
            int(user["id"]),
            str(user["role"]),
        )
    return {"pending_count": pending_count}


@app.get("/api/orders/{order_id}")
def api_customer_order(order_id: int, user=Depends(require_api_user)):
    with closing(db.connect()) as conn:
        order = db.customer_order_by_id(conn, order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    is_customer = int(order["customer_user_id"]) == int(user["id"])
    is_salesperson = int(order["salesperson_user_id"]) == int(user["id"])
    is_super_admin = str(user["role"]) == "super_admin"
    if not is_customer and not is_salesperson and not is_super_admin:
        raise HTTPException(404, "Order not found")
    return {"order": customer_order_payload(order)}


@app.get("/api/orders/{order_id}/download")
def api_download_customer_order(order_id: int, request: Request, token: str = ""):
    user = current_user(request)
    with closing(db.connect()) as conn:
        order = db.customer_order_by_id(conn, order_id)
        if not order:
            raise HTTPException(404, "Order not found")
        authorized_user = bool(
            user
            and (
                str(user["role"]) == "super_admin"
                or int(user["id"]) in {
                    int(order["customer_user_id"]),
                    int(order["salesperson_user_id"]),
                }
            )
        )
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest() if token else ""
        authorized_token = bool(
            token_hash
            and secrets.compare_digest(token_hash, str(order["download_token_hash"]))
        )
        if not authorized_user and not authorized_token:
            raise HTTPException(401, "Authentication or a valid download link is required")
        path = CUSTOMER_ORDER_DIR / str(order["stored_file_name"])
        if not path.is_file():
            raise HTTPException(410, "The order Excel file is no longer available")
        downloaded_by_admin = bool(user and str(user["role"]) in {"admin", "super_admin"})
        if downloaded_by_admin or authorized_token:
            db.confirm_customer_order(
                conn,
                int(order["id"]),
                confirmed_by_user_id=int(user["id"]) if downloaded_by_admin else None,
            )
        if user:
            db.record_user_activity(
                conn,
                int(user["id"]),
                "download",
                detail=f"customer-order:{order['order_number']}",
                file_name=str(order["file_name"]),
            )
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=str(order["file_name"]),
        headers={"Cache-Control": "private, no-store"},
    )


@app.get("/", response_class=HTMLResponse)
def home(request: Request, user=Depends(require_user)):
    q = request.query_params.get("q", "")
    brand = request.query_params.get("brand", "")
    category = request.query_params.get("category", "")
    other = request.query_params.get("other", "")
    asset_type = request.query_params.get("asset_type", "")
    lang = request.query_params.get("lang", "zh")
    page = browse_page(user["role"], q, brand, category, other, asset_type, BROWSE_PAGE_SIZE, 0, user_id=user["id"])
    with db.connect() as conn:
        options = db.facets(conn, user["role"], user_id=user["id"])
        status = conn.execute("SELECT * FROM sync_status WHERE id=1").fetchone()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "user": user,
            "files": page["files"],
            "products": page["products"],
            "stats": page["stats"],
            "next_offset": page["next_offset"],
            "has_more": page["has_more"],
            "page_size": BROWSE_PAGE_SIZE,
            "status": status,
            "facets": options,
            "filters": {"q": q, "brand": brand, "category": category, "other": other, "asset_type": asset_type, "lang": lang},
        },
    )


@app.get("/api/products")
def api_products(
    q: str = "",
    brand: str = "",
    category: str = "",
    other: str = "",
    asset_type: str = "",
    limit: int = BROWSE_PAGE_SIZE,
    offset: int = 0,
    catalog_snapshot: str = "",
    user=Depends(require_api_user),
):
    page = product_catalog_page(
        user["role"], q, brand, category, other, asset_type, limit, offset,
        user_id=user["id"],
        snapshot_token=catalog_snapshot,
    )
    page["products"] = [dict(product) for product in page["products"]]
    with db.connect() as conn:
        favorites = db.user_favorite_skus(conn, int(user["id"]))
        catalog_owner = db.sales_catalog_owner_for_user(conn, int(user["id"]))
    warehouse_account_name = str(catalog_owner["name"] if catalog_owner else user["name"] or "")
    inventory = inventory_source.lookup_available_inventory(
        (product["sku"] for product in page["products"]),
        warehouse_account_name,
    )
    can_manage_catalog = user["role"] in {"super_admin", "admin"}
    for product in page["products"]:
        product["is_favorite"] = product["sku"] in favorites
        product["inventory_state"] = inventory.state
        product["inventory_updated_at"] = inventory.updated_at
        product["sales_warehouse_name"] = inventory.sales_warehouse_name
        inventory_sku = product["sku"].upper()
        if inventory_sku in inventory.values:
            product["available_inventory"] = inventory.values[inventory_sku]
        metadata = (inventory.product_metadata or {}).get(inventory_sku)
        if metadata:
            product["listing_date"] = metadata.listing_date
            if not product.get("chinese_name"):
                product["chinese_name"] = metadata.chinese_name
        metric = (inventory.metrics or {}).get(inventory_sku)
        if metric and can_manage_catalog:
            product.update(
                sales_warehouse_inventory=metric.sales_warehouse,
                sales_warehouse_age_181_365=metric.sales_age_181_365,
                sales_warehouse_age_366_plus=metric.sales_age_366_plus,
                total_pending_qc=metric.pending_qc,
                total_pending_arrival=metric.pending_arrival,
            )
    return {
        "products": page["products"],
        "stats": page["stats"],
        "total": page["total"],
        "next_offset": page["next_offset"],
        "has_more": page["has_more"],
        "catalog_snapshot": page["snapshot_token"],
    }


@app.get("/api/themes")
def api_theme_options(user=Depends(require_api_user)):
    with db.connect() as conn:
        return {"themes": product_taxonomy.theme_options(conn)}


@app.post("/api/catalogue/missing-skus")
def api_report_missing_skus(payload: dict = Body(...), user=Depends(require_api_user)):
    raw_skus = payload.get("skus")
    searched_count = payload.get("searched_count")
    source = str(payload.get("source") or "batch_search").strip()
    if not isinstance(raw_skus, list) or not isinstance(searched_count, int):
        raise HTTPException(400, "skus and searched_count are required")
    if source not in {"batch_search", "excel_import"}:
        raise HTTPException(400, "The missing SKU source is invalid")
    if not 1 <= searched_count <= 5000 or len(raw_skus) > searched_count:
        raise HTTPException(400, "The batch SKU search is invalid")
    missing_skus: list[str] = []
    seen: set[str] = set()
    for value in raw_skus:
        sku = str(value).strip().upper()
        if not re.fullmatch(r"(?=.*\d)[A-Z0-9][A-Z0-9._-]{2,99}", sku):
            raise HTTPException(400, "A missing SKU is invalid")
        if sku not in seen:
            seen.add(sku)
            missing_skus.append(sku)
    if not missing_skus:
        return {"missing_skus": [], "notified": False, "duplicate": False}

    fingerprint = hashlib.sha256("\n".join(sorted(missing_skus)).encode("utf-8")).hexdigest()
    with closing(db.connect()) as conn:
        db.init_db(conn)
        recent = db.recent_missing_sku_notification(conn, int(user["id"]), fingerprint)
        if recent:
            return {
                "missing_skus": missing_skus,
                "notified": True,
                "duplicate": True,
                "recipient_name": MISSING_SKU_RECIPIENT_NAME,
            }
        recipient_user_id = os.getenv("DINGTALK_MISSING_SKU_RECIPIENT_USER_ID", "").strip()
        if not recipient_user_id:
            recipient_user_id = db.dingtalk_provider_user_id_by_name(conn, MISSING_SKU_RECIPIENT_NAME)
        if not recipient_user_id:
            cached = db.dingtalk_organization_cache(conn)
            if cached:
                recipient_user_id = next(
                    (
                        str(item.get("user_id") or "").strip()
                        for item in cached["directory"].get("members", [])
                        if str(item.get("name") or "").strip() == MISSING_SKU_RECIPIENT_NAME
                    ),
                    "",
                )
    if not recipient_user_id:
        raise HTTPException(503, f"未找到 {MISSING_SKU_RECIPIENT_NAME} 的钉钉账号")

    sku_groups: list[list[str]] = []
    current_group: list[str] = []
    current_length = 0
    for sku in missing_skus:
        next_length = current_length + len(sku) + (1 if current_group else 0)
        if current_group and next_length > 3000:
            sku_groups.append(current_group)
            current_group = []
            current_length = 0
        current_group.append(sku)
        current_length += len(sku) + (1 if len(current_group) > 1 else 0)
    if current_group:
        sku_groups.append(current_group)

    task_ids: list[str] = []
    try:
        client_id, client_secret = dingtalk_credentials()
        agent_id = os.getenv("DINGTALK_AGENT_ID", "").strip()
        if not agent_id:
            raise RuntimeError("DingTalk work notifications are not configured")
        for index, group in enumerate(sku_groups, start=1):
            page = f"（{index}/{len(sku_groups)}）" if len(sku_groups) > 1 else ""
            source_label = "管理员 Excel 导入" if source == "excel_import" else "批量 SKU 搜索"
            message = "\n".join(
                [
                    f"{source_label}缺失提醒{page}",
                    f"搜索人：{user['name']}（{user['email']}）",
                    f"搜索数量：{searched_count}，未找到：{len(missing_skus)}",
                    "请核对并添加以下 SKU：",
                    " ".join(group),
                ]
            )
            result = dingtalk_auth.send_work_notification(
                [recipient_user_id], message, client_id, client_secret, agent_id
            )
            task_ids.append(str(result["task_id"]))
    except Exception as exc:
        with closing(db.connect()) as conn:
            db.record_missing_sku_notification(
                conn,
                user_id=int(user["id"]),
                fingerprint=fingerprint,
                searched_count=searched_count,
                missing_skus=missing_skus,
                recipient_name=MISSING_SKU_RECIPIENT_NAME,
                task_ids=task_ids,
                status="failed",
                error=str(exc) or type(exc).__name__,
            )
        raise HTTPException(502, "未找到的 SKU 暂时无法通知管理员，请稍后重试") from exc

    with closing(db.connect()) as conn:
        db.record_missing_sku_notification(
            conn,
            user_id=int(user["id"]),
            fingerprint=fingerprint,
            searched_count=searched_count,
            missing_skus=missing_skus,
            recipient_name=MISSING_SKU_RECIPIENT_NAME,
            task_ids=task_ids,
            status="sent",
        )
    return {
        "missing_skus": missing_skus,
        "notified": True,
        "duplicate": False,
        "recipient_name": MISSING_SKU_RECIPIENT_NAME,
    }


@app.get("/api/catalog-order")
def api_catalog_order(user=Depends(require_api_user)):
    with db.connect() as conn:
        order = db.sales_catalog_order_for_user(conn, int(user["id"]))
    return {
        **order,
        "can_manage": user["role"] in {"super_admin", "admin"},
    }


@app.put("/api/catalog-order")
def api_save_catalog_order(payload: dict = Body(...), user=Depends(require_api_admin)):
    sku_order = payload.get("sku_order")
    draft = payload.get("draft")
    expected_revision = payload.get("revision")
    if not isinstance(sku_order, list) or not isinstance(draft, dict) or not isinstance(expected_revision, int):
        raise HTTPException(400, "sku_order, draft and revision are required")
    with db.connect() as conn:
        try:
            order = db.save_sales_catalog_order(
                conn,
                int(user["id"]),
                sku_order,
                draft,
                expected_revision=expected_revision,
            )
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    return {**order, "can_manage": True}


def is_product_asset_mime(mime_type: str) -> bool:
    lowered = (mime_type or "").lower()
    return lowered.startswith(("image/", "video/", "application/pdf"))


def api_asset_payload(row) -> dict:
    mime_type = row["mime_type"] or "application/octet-stream"
    if mime_type.startswith("video/"):
        kind = "video"
    elif mime_type.lower().startswith("application/pdf"):
        kind = "document"
    else:
        kind = "image"
    return {
        "id": row["id"],
        "name": row["name"],
        "kind": kind,
        "mime_type": mime_type,
        "size": int(row["size"] or 0),
        "modified_time": row["modified_time"] or "",
        "path": row["path"],
        "asset_type": row["asset_type"],
        "internal_only": bool(row["internal_only"]),
        "thumbnail_url": "" if kind == "document" else f"/thumb/{row['id']}",
        "preview_url": f"/media/{row['id']}",
        "download_url": f"/download/{row['id']}",
    }


@app.get("/api/products/{sku}")
def api_product_detail(sku: str, user=Depends(require_api_user)):
    sku = sku.upper()
    with db.connect() as conn:
        files = [row for row in db.sku_files(conn, sku, user["role"], user_id=user["id"]) if not is_ignored_file(row["name"])]
        meta = conn.execute("SELECT * FROM sku_meta WHERE sku = ?", (sku,)).fetchone()
        favorites = db.user_favorite_skus(conn, int(user["id"]))
        theme_options = product_taxonomy.theme_options(conn)
        catalog_owner = db.sales_catalog_owner_for_user(conn, int(user["id"]))
    if not files:
        raise HTTPException(404, detail="Product not found")
    product = product_cards(files, theme_options)[0]
    media_files = [row for row in files if is_product_asset_mime(row["mime_type"])]
    product["assets"] = [api_asset_payload(row) for row in media_files]
    product["notes"] = meta["notes"] if meta else ""
    product["is_favorite"] = sku in favorites
    warehouse_account_name = str(catalog_owner["name"] if catalog_owner else user["name"] or "")
    inventory = inventory_source.lookup_available_inventory([sku], warehouse_account_name)
    can_manage_catalog = user["role"] in {"super_admin", "admin"}
    product["inventory_state"] = inventory.state
    product["inventory_updated_at"] = inventory.updated_at
    product["sales_warehouse_name"] = inventory.sales_warehouse_name
    inventory_sku = sku.strip().upper()
    if inventory_sku in inventory.values:
        product["available_inventory"] = inventory.values[inventory_sku]
    metadata = (inventory.product_metadata or {}).get(inventory_sku)
    if metadata:
        product["listing_date"] = metadata.listing_date
        if not product.get("chinese_name"):
            product["chinese_name"] = metadata.chinese_name
    metric = (inventory.metrics or {}).get(inventory_sku)
    if metric and can_manage_catalog:
        product.update(
            sales_warehouse_inventory=metric.sales_warehouse,
            sales_warehouse_age_181_365=metric.sales_age_181_365,
            sales_warehouse_age_366_plus=metric.sales_age_366_plus,
            total_pending_qc=metric.pending_qc,
            total_pending_arrival=metric.pending_arrival,
        )
    return {"product": product}


@app.post("/api/admin/products/{sku}/cover")
def api_set_product_cover(
    sku: str,
    file_id: str = Form(...),
    user=Depends(require_api_admin),
):
    with db.connect() as conn:
        try:
            row = db.set_product_cover(conn, sku, file_id)
        except ValueError as exc:
            raise HTTPException(400, detail=str(exc)) from exc
    return {"sku": row["sku"], "cover_file_id": row["id"]}


def ensure_visible_sku(conn, sku: str, role: str, user_id: int | None = None) -> None:
    if not db.sku_files(conn, sku, role, user_id=user_id):
        raise HTTPException(404, detail="Product not found")


@app.get("/api/products/{sku}/messages")
def api_my_product_messages(sku: str, user=Depends(require_api_user)):
    sku = sku.upper()
    with db.connect() as conn:
        ensure_visible_sku(conn, sku, user["role"], user["id"])
        messages = [dict(row) for row in db.user_product_messages(conn, int(user["id"]), sku)]
    return {"messages": messages}


@app.post("/api/products/{sku}/messages")
def api_create_product_message(
    sku: str,
    message: str = Form(...),
    user=Depends(require_api_user),
):
    sku = sku.upper()
    body = message.strip()
    if not body:
        raise HTTPException(400, detail="Please enter a comment or message")
    if len(body) > 1000:
        raise HTTPException(400, detail="Messages must be 1,000 characters or fewer")
    with db.connect() as conn:
        ensure_visible_sku(conn, sku, user["role"], user["id"])
        created = dict(db.create_product_message(conn, int(user["id"]), sku, body))
    return {"message": created}


@app.post("/api/products/{sku}/favorite")
def api_set_product_favorite(
    sku: str,
    favorite: bool = Form(...),
    user=Depends(require_api_user),
):
    sku = sku.upper()
    with db.connect() as conn:
        ensure_visible_sku(conn, sku, user["role"], user["id"])
        value = db.set_product_favorite(conn, int(user["id"]), sku, favorite)
    return {"sku": sku, "is_favorite": value}


@app.post("/api/activity/original-open")
def api_record_original_open(
    sku: str = Form(...),
    file_id: str = Form(...),
    user=Depends(require_api_user),
):
    sku = sku.strip().upper()
    with db.connect() as conn:
        row = db.get_file(conn, file_id, user["role"], user_id=int(user["id"]))
        if not row or row["sku"] != sku:
            raise HTTPException(404, detail="Asset not found")
        db.record_user_activity(
            conn,
            int(user["id"]),
            "original_open",
            sku=sku,
            file_id=str(row["id"]),
            file_name=row["name"],
        )
    return {"recorded": True}


@app.post("/api/catalog/events")
def api_record_catalog_event(payload: dict = Body(...), user=Depends(require_api_user)):
    if user["role"] not in CUSTOMER_ACCOUNT_ROLES:
        raise HTTPException(403, detail="Customer account required")
    event_type = payload.get("event_type")
    sku = payload.get("sku", "")
    if not isinstance(event_type, str) or event_type not in db.CATALOG_EVENT_TYPES:
        raise HTTPException(400, detail="Invalid catalog event")
    if not isinstance(sku, str) or len(sku) > 100:
        raise HTTPException(400, detail="Invalid SKU")
    sku = sku.strip().upper()
    product_event = event_type in {"product_open", "product_added", "product_removed"}
    if product_event != bool(sku):
        raise HTTPException(400, detail="SKU does not match event type")
    with db.connect() as conn:
        if sku:
            ensure_visible_sku(conn, sku, user["role"], int(user["id"]))
        db.record_catalog_event(conn, int(user["id"]), event_type, sku)
    return {"recorded": True}


@app.get("/api/search")
def api_search(
    q: str = "",
    brand: str = "",
    category: str = "",
    other: str = "",
    asset_type: str = "",
    user=Depends(require_api_user),
):
    with db.connect() as conn:
        rows = db.search_files(conn, user["role"], q, brand, category, other, asset_type, user_id=user["id"])
    return [dict(row) for row in rows]


@app.get("/sku/{sku}", response_class=HTMLResponse)
def sku_page(sku: str, request: Request, user=Depends(require_user)):
    with db.connect() as conn:
        files = db.sku_files(conn, sku.upper(), user["role"], user_id=user["id"])
        meta = conn.execute("SELECT * FROM sku_meta WHERE sku = ?", (sku.upper(),)).fetchone()
        theme_options = product_taxonomy.theme_options(conn)
    files = [row for row in files if not is_ignored_file(row["name"]) and is_product_asset_mime(row["mime_type"])]
    if not files:
        raise HTTPException(404)
    product = product_cards(files, theme_options)[0]
    primary = next((row for row in files if row["mime_type"].startswith("image/")), files[0] if files else None)
    return templates.TemplateResponse(
        "sku.html",
        {
            "request": request,
            "user": user,
            "sku": sku.upper(),
            "files": files,
            "primary": primary,
            "stats": file_stats(files),
            "meta": meta,
            "product": product,
        },
    )


def cached_product_catalog_pdf_response(row, request: Request):
    path = populate_product_catalog_pdf_cache(row)
    size = path.stat().st_size
    headers = {
        "Cache-Control": "private, max-age=31536000, immutable",
        "Accept-Ranges": "bytes",
    }
    range_header = request.headers.get("range", "")
    if range_header and size:
        byte_range = parse_range_header(range_header, size)
        if not byte_range:
            return Response(
                status_code=416,
                headers={
                    **headers,
                    "Content-Range": f"bytes */{size}",
                },
            )
        start, end = byte_range
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        headers["Content-Length"] = str(end - start + 1)
        return StreamingResponse(
            local_media.iter_file_range(path, start, end),
            status_code=206,
            media_type=row["mime_type"],
            headers=headers,
        )
    return FileResponse(
        path,
        media_type=row["mime_type"],
        headers=headers,
    )


@app.get("/media/{file_id}")
def media(file_id: str, request: Request, user=Depends(require_user)):
    with db.connect() as conn:
        user_id = account_id(user)
        row = db.get_file(conn, file_id, user["role"], user_id=user_id) if user_id is not None else db.get_file(conn, file_id, user["role"])
    if not row:
        raise HTTPException(404)
    if local_media.is_product_catalog_pdf(row):
        return cached_product_catalog_pdf_response(row, request)

    headers = {"Cache-Control": "private, max-age=86400", "Accept-Ranges": "bytes"}
    size = int(row["size"] or 0)
    range_header = request.headers.get("range", "")
    if range_header and size:
        byte_range = parse_range_header(range_header, size)
        if not byte_range:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        start, end = byte_range
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        headers["Content-Length"] = str(end - start + 1)
        return StreamingResponse(
            drive.download_file(file_id, start=start, end=end),
            status_code=206,
            media_type=row["mime_type"],
            headers=headers,
        )
    if size:
        headers["Content-Length"] = str(size)
    return StreamingResponse(
        drive.download_file(file_id),
        media_type=row["mime_type"],
        headers=headers,
    )


@app.get("/thumb/{file_id}")
def thumb(file_id: str, v: str = "", variant: str = "card", user=Depends(require_user)):
    try:
        spec = thumbnails.variant(variant)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    with db.connect() as conn:
        user_id = account_id(user)
        row = db.get_file(conn, file_id, user["role"], user_id=user_id) if user_id is not None else db.get_file(conn, file_id, user["role"])
    if not row or not row["mime_type"].startswith(("image/", "video/")):
        raise HTTPException(404)
    headers = {
        "Cache-Control": "private, max-age=31536000, immutable"
        if v
        else "private, max-age=86400"
    }
    cached = thumbnail_cache_entry(row, spec.name)
    if cached:
        path, content_type = cached
        return FileResponse(path, media_type=content_type, headers=headers)
    provisional = provisional_thumbnail_cache_entry(row, spec.name)
    if provisional:
        path, content_type = provisional
        return FileResponse(
            path,
            media_type=content_type,
            headers={
                "Cache-Control": "no-store",
            },
        )
    return Response(
        THUMBNAIL_PLACEHOLDER,
        media_type="image/svg+xml",
        headers={
            "Cache-Control": "no-store",
        },
    )


@app.get("/download/{file_id}")
def download(file_id: str, user=Depends(require_user)):
    with db.connect() as conn:
        user_id = account_id(user)
        row = db.get_file(conn, file_id, user["role"], user_id=user_id) if user_id is not None else db.get_file(conn, file_id, user["role"])
        if row and user_id is not None:
            db.record_user_activity(
                conn,
                user_id,
                "download",
                sku=row["sku"],
                file_id=str(row["id"]),
                file_name=row["name"],
            )
    if not row:
        raise HTTPException(404)
    if local_media.is_product_catalog_pdf(row):
        return FileResponse(
            populate_product_catalog_pdf_cache(row),
            media_type=row["mime_type"],
            filename=row["name"],
            headers={"Cache-Control": "private, max-age=31536000, immutable"},
        )
    headers = {"Content-Disposition": f'attachment; filename="{row["name"]}"'}
    return StreamingResponse(drive.download_file(file_id), media_type="application/octet-stream", headers=headers)


@app.get("/sku/{sku}/zip")
def zip_sku(sku: str, user=Depends(require_user)):
    sku, files, cache_path = zip_context(sku, user["role"], user["id"])
    if not cache_path.exists():
        start_zip_job(cache_path, files)
        return JSONResponse({"detail": "ZIP is being prepared"}, status_code=202, headers={"Retry-After": "2"})
    with db.connect() as conn:
        db.record_user_activity(conn, int(user["id"]), "download", sku=sku, file_name=f"{sku}.zip", detail="sku_zip")
    return FileResponse(
        cache_path,
        media_type="application/zip",
        filename=f"{sku}.zip",
        headers={"Cache-Control": "private, max-age=86400"},
    )


@app.post("/sku/{sku}/zip/prepare")
def prepare_zip_sku(sku: str, user=Depends(require_user)):
    sku, files, cache_path = zip_context(sku, user["role"], user["id"])
    state = start_zip_job(cache_path, files)
    return {
        "state": state,
        "progress": 100 if state == "ready" else 0,
        "status_url": f"/sku/{sku}/zip/status",
        "download_url": f"/sku/{sku}/zip" if state == "ready" else "",
    }


@app.get("/sku/{sku}/zip/status")
def zip_sku_status(sku: str, user=Depends(require_user)):
    sku, _files, cache_path = zip_context(sku, user["role"], user["id"])
    if cache_path.exists():
        return {"state": "ready", "progress": 100, "download_url": f"/sku/{sku}/zip"}
    with zip_jobs_guard:
        state = dict(zip_jobs.get(cache_path.name, {"state": "idle", "error": "", "progress": 0}))
    state["download_url"] = ""
    return state


@app.post("/sku/{sku}/drive/prepare")
def prepare_drive_copy(sku: str, user=Depends(require_api_user)):
    sku, files = drive_copy_context(sku, user["role"], user["id"])
    with db.connect() as conn:
        db.record_user_activity(conn, int(user["id"]), "drive_export", sku=sku, detail="open_in_drive")
    state = start_drive_copy_job(sku, user["role"], str(user["id"]), files)
    state["status_url"] = f"/sku/{sku}/drive/status?job_id={state['job_id']}"
    return state


@app.get("/api/super-admin/user-monitor")
def api_super_admin_user_monitor(user=Depends(require_api_super_admin)):
    with db.connect() as conn:
        return db.user_monitor_overview(conn)


@app.get("/api/super-admin/user-monitor/{user_id}")
def api_super_admin_user_activity(user_id: int, user=Depends(require_api_super_admin)):
    with db.connect() as conn:
        try:
            return db.user_activity_detail(conn, user_id)
        except ValueError as exc:
            raise HTTPException(404, detail=str(exc)) from exc


@app.get("/sku/{sku}/drive/status")
def drive_copy_status(sku: str, job_id: str, user=Depends(require_api_user)):
    sku = sku.upper()
    with drive_copy_jobs_guard:
        state = drive_copy_jobs.get(job_id)
        if not state or state["sku"] != sku or state["user_id"] != str(user["id"]):
            raise HTTPException(404, detail="Drive copy job not found")
        payload = drive_copy_state_payload(state)
    payload["status_url"] = f"/sku/{sku}/drive/status?job_id={job_id}"
    return payload


@app.get("/api/admin/overview")
def api_admin_overview(
    import_page: int = 1,
    import_page_size: int = 6,
    import_view: str = "active",
    user=Depends(require_api_super_admin),
):
    if import_view not in {"active", "disabled"}:
        raise HTTPException(400, "Invalid import view")
    can_manage_access = user["role"] == "super_admin"
    with db.connect() as conn:
        owner_id = None if user["role"] == "super_admin" else int(user["id"])
        users = [dict(row) for row in db.list_customer_users(conn, owner_id)]
        rules = [dict(row) for row in db.list_role_rules(conn)] if can_manage_access else []
        user_grants = [dict(row) for row in db.list_user_grants(conn, owner_id)] if can_manage_access else []
        status_row = conn.execute("SELECT * FROM sync_status WHERE id=1").fetchone()
        import_page_data = nas_imports.paginate_imports(
            conn,
            import_page,
            import_page_size,
            view=import_view,
        )
        imports = []
        for row in import_page_data["imports"]:
            item = dict(row)
            item["preview_url"] = (
                f"/admin/nas-imports/{row['id']}/preview"
                f"?v={admin_import_thumbnail_version(row)}"
            )
            item["media_url"] = (
                f"/admin/nas-imports/{row['id']}/media"
                f"?v={admin_import_thumbnail_version(row)}"
                if nas_imports.is_video_import(row)
                else ""
            )
            imports.append(item)
        counts = nas_imports.status_counts(conn)
        edit_logs = [dict(row) for row in nas_imports.list_edit_logs(conn)]
        edit_logs.extend(db.list_category_corrections(conn))
        edit_logs.sort(key=lambda item: (item.get("created_at") or "", item.get("id") or 0), reverse=True)
        upload_history = [dict(row) for row in nas_imports.list_uploaded_imports(conn)]
        permission_values = db.permission_rule_values(conn) if can_manage_access else {}
        message_count = conn.execute("SELECT COUNT(*) FROM product_messages").fetchone()[0]
        category_options = product_taxonomy.category_options(conn)
        theme_options = product_taxonomy.theme_options(conn)
    return {
        "users": users,
        "rules": rules,
        "user_grants": user_grants,
        "can_manage_access": can_manage_access,
        "sync_status": dict(status_row) if status_row else None,
        "imports": imports,
        "import_total": import_page_data["total"],
        "import_batch_total": import_page_data["batch_total"],
        "import_batch_count": import_page_data["batch_count"],
        "import_page": import_page_data["page"],
        "import_page_size": import_page_data["page_size"],
        "import_pages": import_page_data["pages"],
        "import_view": import_view,
        "active_import_total": active_import_notification_count(counts),
        "disabled_import_total": int(counts.get("rejected", 0)),
        "import_status_counts": {
            status: int(counts.get(status, 0))
            for status in ("pending", "suggested", "error", "rejected")
        },
        "import_counts": counts,
        "edit_logs": edit_logs,
        "upload_history": upload_history,
        "permission_values": permission_values,
        "category_options": category_options,
        "category_tag_options": product_taxonomy.tag_options(),
        "theme_options": theme_options,
        "message_count": message_count,
        "role_labels": ROLE_LABELS,
        "scope_labels": RULE_SCOPE_LABELS,
    }


def active_import_notification_count(counts: dict[str, int]) -> int:
    return sum(
        int(count)
        for status, count in counts.items()
        if status not in {"approved", "uploaded", "rejected"}
    )


@app.get("/api/admin/notifications")
def api_admin_notifications(user=Depends(require_api_super_admin)):
    with db.connect() as conn:
        counts = nas_imports.status_counts(conn)
    return {"pending_count": active_import_notification_count(counts)}


@app.get("/api/admin/import-jobs")
def api_admin_import_jobs(limit: int = 20, user=Depends(require_api_super_admin)):
    with db.connect() as conn:
        return {"jobs": nas_imports.list_import_jobs(conn, limit=limit)}


@app.post("/api/admin/import-jobs/{job_id}/dismiss")
def api_admin_dismiss_import_job(job_id: str, user=Depends(require_api_super_admin)):
    with db.connect() as conn:
        try:
            job = nas_imports.dismiss_import_job(conn, job_id)
        except nas_imports.ConcurrencyConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
    return {"dismissed": True, "job": job}


def _live_dingtalk_organization() -> dict:
    client_id, client_secret = dingtalk_credentials()
    return dingtalk_auth.get_organization_directory(client_id, client_secret)


def _is_information_technology_department(names: list[str]) -> bool:
    return any(re.sub(r"\s+", "", name).casefold() == "信息技术部" for name in names)


def _refresh_dingtalk_organization_cache() -> dict:
    directory = _live_dingtalk_organization()
    synced_at = datetime.now(CHINA_TIMEZONE).isoformat()
    with closing(db.connect()) as conn:
        db.init_db(conn)
        db.save_dingtalk_organization_cache(conn, directory, synced_at)
    return {"directory": directory, "synced_at": synced_at}


def _cached_dingtalk_organization() -> dict | None:
    with closing(db.connect()) as conn:
        db.init_db(conn)
        return db.dingtalk_organization_cache(conn)


def _dingtalk_organization_payload(cached: dict) -> dict:
    directory = cached["directory"]
    try:
        departments = directory["departments"]
        directory_members = directory["members"]
    except (KeyError, TypeError) as exc:
        raise HTTPException(500, "本地组织架构缓存无效，请手动刷新") from exc
    department_names = {str(item["id"]): str(item["name"]) for item in departments}
    with closing(db.connect()) as conn:
        db.init_db(conn)
        access = db.dingtalk_member_access(conn)

    members = []
    for item in directory_members:
        provider_user_id = str(item["user_id"])
        member_department_names = [
            department_names[department_id]
            for department_id in item["department_ids"]
            if department_id in department_names and department_id != "1"
        ]
        is_super_admin = _is_information_technology_department(member_department_names)
        current = access.get(provider_user_id, {})
        role = "super_admin" if is_super_admin else str(current.get("role") or "internal_staff")
        members.append(
            {
                "user_id": provider_user_id,
                "name": item["name"],
                "department_ids": item["department_ids"],
                "department_names": member_department_names,
                "role": role,
                "is_super_admin": is_super_admin,
                "admin_granted": bool(current.get("admin_granted")) and not is_super_admin,
                "has_local_account": bool(current.get("local_user_id")),
            }
        )
    members.sort(key=lambda item: (item["role"] != "super_admin", item["role"] != "admin", item["name"]))
    direct_counts: dict[str, int] = {}
    for item in members:
        for department_id in item["department_ids"]:
            direct_counts[department_id] = direct_counts.get(department_id, 0) + 1
    for department in departments:
        department["member_count"] = direct_counts.get(str(department["id"]), 0)
    return {
        "departments": departments,
        "members": members,
        "stats": {
            "departments": max(0, len(departments) - 1),
            "members": len(members),
            "admins": sum(1 for item in members if item["role"] == "admin"),
            "super_admins": sum(1 for item in members if item["role"] == "super_admin"),
        },
        "synced_at": cached["synced_at"],
    }


@app.get("/api/super-admin/organization")
def api_super_admin_organization(user=Depends(require_api_super_admin)):
    cached = _cached_dingtalk_organization()
    if not cached:
        try:
            cached = _refresh_dingtalk_organization_cache()
        except dingtalk_auth.DingTalkAuthError as exc:
            raise HTTPException(502, "钉钉组织架构同步失败，请检查通讯录权限后重试") from exc
    return _dingtalk_organization_payload(cached)


@app.post("/api/super-admin/organization/refresh")
def api_refresh_super_admin_organization(user=Depends(require_api_super_admin)):
    try:
        cached = _refresh_dingtalk_organization_cache()
    except dingtalk_auth.DingTalkAuthError as exc:
        raise HTTPException(502, "钉钉组织架构同步失败，请检查通讯录权限后重试") from exc
    return _dingtalk_organization_payload(cached)


@app.get("/api/admin/access-control")
def api_admin_access_control(user=Depends(require_api_admin)):
    with db.connect() as conn:
        owner_id = None if user["role"] == "super_admin" else int(user["id"])
        return {
            "users": [dict(row) for row in db.list_customer_users(conn, owner_id)],
            "engagement": [dict(row) for row in db.customer_catalog_engagement(conn, owner_id)],
            "salespeople": [dict(row) for row in db.list_salespeople(conn)] if user["role"] == "super_admin" else [],
            "rules": [dict(row) for row in db.list_role_rules(conn)],
            "user_grants": [dict(row) for row in db.list_user_grants(conn, owner_id)],
            "permission_values": db.permission_rule_values(conn),
            "role_labels": ROLE_LABELS,
            "scope_labels": RULE_SCOPE_LABELS,
        }


@app.post("/api/admin/users/{user_id}/catalog-share-copy")
def api_admin_record_catalog_share_copy(user_id: int, user=Depends(require_api_admin)):
    with db.connect() as conn:
        db.init_db(conn)
        owner_id = None if user["role"] == "super_admin" else int(user["id"])
        customer = next((row for row in db.list_customer_users(conn, owner_id) if row["id"] == user_id), None)
        if customer is None:
            raise HTTPException(404, "客户账号不存在或无权访问")
        if customer["disabled"]:
            raise HTTPException(409, "客户账号已停用，请先续期或启用")
        db.record_customer_catalog_share_copy(conn, user_id, int(user["id"]))
    return {"recorded": True}


@app.post("/api/admin/users/{user_id}/catalog-invite")
def api_admin_create_catalog_invite(user_id: int, token: str = Form(...), user=Depends(require_api_admin)):
    if not re.fullmatch(r"[a-f0-9]{32}", token):
        raise HTTPException(400, "邀请链接无效")
    with closing(db.connect()) as conn:
        db.init_db(conn)
        owner_id = None if user["role"] == "super_admin" else int(user["id"])
        customer = next((row for row in db.list_customer_users(conn, owner_id) if row["id"] == user_id), None)
        if customer is None:
            raise HTTPException(404, "客户账号不存在或无权访问")
        if customer["disabled"] or customer["expired"]:
            raise HTTPException(409, "客户账号已停用或过期，请先续期或启用")
        db.create_customer_catalog_invite(
            conn, user_id, int(user["id"]), hashlib.sha256(token.encode("utf-8")).hexdigest()
        )
    return {"created": True}


@app.post("/api/catalog-invites/open")
def api_open_catalog_invite(payload: dict = Body(...)):
    token = payload.get("token")
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token):
        raise HTTPException(404, "Catalog invitation unavailable")
    with closing(db.connect()) as conn:
        db.init_db(conn)
        customer = db.open_customer_catalog_invite(conn, hashlib.sha256(token.encode("utf-8")).hexdigest())
    if customer is None:
        raise HTTPException(404, "Catalog invitation unavailable")
    return JSONResponse(
        {"email": customer["email"], "name": customer["name"]},
        headers={"Cache-Control": "no-store"},
    )


@app.post("/api/admin/users")
def api_admin_create_customer_user(
    email: str = Form(...),
    name: str = Form(""),
    role: str = Form(...),
    password: str = Form(...),
    permission_mode: str = Form("allowlist"),
    permission_scopes: list[str] | None = Form(None),
    permission_values: list[str] | None = Form(None),
    user=Depends(require_api_admin),
):
    role = role.strip().lower()
    if role not in CUSTOMER_ACCOUNT_ROLES:
        raise HTTPException(403, "这里只能创建海外客户、国内客户或服务商账号")
    scopes = permission_scopes or []
    values = permission_values or []
    if len(scopes) != len(values):
        raise HTTPException(400, "权限类型与权限值数量不一致")
    if permission_mode != "allowlist":
        raise HTTPException(400, "客户账号必须设置独立权限")
    with db.connect() as conn:
        db.init_db(conn)
        try:
            created = db.create_customer_user_with_permissions(
                conn,
                email=email,
                name=name,
                role=role,
                password=password,
                permission_mode=permission_mode,
                grants=zip(scopes, values),
                created_by_user_id=int(user["id"]),
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "该邮箱已存在") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        grants = [dict(row) for row in db.user_grants(conn, int(created["id"]))]
    return {"user": dict(created), "grants": grants}


@app.post("/api/admin/users/{user_id}")
def api_admin_update_customer_user(
    user_id: int,
    name: str = Form(...),
    role: str = Form(...),
    disabled: bool = Form(False),
    permission_mode: str = Form("allowlist"),
    permission_scopes: list[str] | None = Form(None),
    permission_values: list[str] | None = Form(None),
    user=Depends(require_api_admin),
):
    role = role.strip().lower()
    if role not in CUSTOMER_ACCOUNT_ROLES:
        raise HTTPException(403, "这里只能修改海外客户、国内客户或服务商账号")
    scopes = permission_scopes or []
    values = permission_values or []
    if len(scopes) != len(values):
        raise HTTPException(400, "权限类型与权限值数量不一致")
    if permission_mode != "allowlist":
        raise HTTPException(400, "客户账号必须设置独立权限")
    with db.connect() as conn:
        db.init_db(conn)
        if user["role"] != "super_admin" and not db.customer_owned_by(conn, user_id, int(user["id"])):
            raise HTTPException(403, "只能修改自己创建的客户账号")
        try:
            updated = db.update_customer_user_with_permissions(
                conn,
                user_id,
                name=name,
                role=role,
                disabled=disabled,
                permission_mode=permission_mode,
                grants=zip(scopes, values),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        grants = [dict(row) for row in db.user_grants(conn, user_id)]
    return {"user": dict(updated), "grants": grants}


@app.post("/api/admin/users/{user_id}/renew")
def api_admin_renew_customer_user(user_id: int, user=Depends(require_api_admin)):
    with db.connect() as conn:
        db.init_db(conn)
        if user["role"] != "super_admin" and not db.customer_owned_by(conn, user_id, int(user["id"])):
            raise HTTPException(403, "只能续期自己创建的客户账号")
        try:
            renewed = db.renew_expired_customer_user(conn, user_id, int(user["id"]))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    return {"user": dict(renewed)}


@app.post("/api/admin/users/{user_id}/reset-password")
def api_admin_reset_customer_password(user_id: int, user=Depends(require_api_admin)):
    groups = ("ABCDEFGHJKLMNPQRSTUVWXYZ", "abcdefghijkmnopqrstuvwxyz", "23456789", "!@#$%")
    password_chars = [secrets.choice(group) for group in groups]
    pool = "".join(groups)
    password_chars.extend(secrets.choice(pool) for _ in range(10))
    secrets.SystemRandom().shuffle(password_chars)
    temporary_password = "".join(password_chars)
    with db.connect() as conn:
        db.init_db(conn)
        if user["role"] != "super_admin" and not db.customer_owned_by(conn, user_id, int(user["id"])):
            raise HTTPException(403, "只能重置自己创建的客户密码")
        try:
            db.reset_customer_user_password(conn, user_id, temporary_password)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    return {"temporary_password": temporary_password}


@app.post("/api/super-admin/organization/{provider_user_id}/admin")
def api_set_organization_admin(
    provider_user_id: str,
    enabled: bool = Form(...),
    user=Depends(require_api_super_admin),
):
    cached = _cached_dingtalk_organization()
    if not cached:
        raise HTTPException(409, "请先手动刷新钉钉组织架构")
    directory = cached["directory"]
    member = next(
        (item for item in directory["members"] if str(item["user_id"]) == provider_user_id),
        None,
    )
    if not member:
        raise HTTPException(404, "该员工不在当前钉钉组织架构中")
    department_names_by_id = {
        str(item["id"]): str(item["name"])
        for item in directory["departments"]
    }
    member_department_names = [
        department_names_by_id[department_id]
        for department_id in member["department_ids"]
        if department_id in department_names_by_id and department_id != "1"
    ]
    if _is_information_technology_department(member_department_names):
        raise HTTPException(409, "信息技术部成员自动拥有超级管理员权限，不能手工修改")
    with db.connect() as conn:
        db.init_db(conn)
        try:
            db.set_dingtalk_admin_grant(
                conn,
                provider_user_id=provider_user_id,
                display_name=str(member["name"]),
                department_names=member_department_names,
                granted_by_user_id=int(user["id"]),
                enabled=enabled,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    return {"updated": True, "role": "admin" if enabled else "internal_staff"}


@app.get("/api/admin/messages")
def api_admin_messages(
    q: str = "",
    limit: int = 200,
    offset: int = 0,
    user=Depends(require_api_super_admin),
):
    with db.connect() as conn:
        return db.admin_product_messages(conn, q=q, limit=limit, offset=offset)


@app.get("/api/admin/products")
def api_admin_products(
    q: str = "",
    page: int = 1,
    page_size: int = 40,
    user=Depends(require_api_super_admin),
):
    with db.connect() as conn:
        return db.list_product_metadata(conn, q=q, page=page, page_size=page_size)


@app.post("/api/admin/categories")
def api_admin_create_category(
    group: str = Form(...),
    label_en: str = Form(...),
    label_zh: str = Form(""),
    user=Depends(require_api_super_admin),
):
    with db.connect() as conn:
        try:
            return product_taxonomy.create_custom_category(
                conn,
                group=group,
                label_en=label_en,
                label_zh=label_zh,
                created_by=user["id"],
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc


@app.post("/api/admin/themes")
def api_admin_create_theme(
    label: str = Form(...),
    user=Depends(require_api_super_admin),
):
    with db.connect() as conn:
        try:
            return product_taxonomy.create_custom_theme(
                conn,
                label=label,
                created_by=user["id"],
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc


@app.post("/api/admin/products/bulk-metadata")
def api_admin_bulk_product_metadata(
    skus: list[str] | None = Form(None),
    q: str = Form(""),
    apply_all: bool = Form(False),
    set_code: str = Form(""),
    category_id: str = Form(""),
    category_tags: str = Form(""),
    themes: str = Form(""),
    update_set: bool = Form(False),
    update_category: bool = Form(False),
    update_themes: bool = Form(False),
    user=Depends(require_api_super_admin),
):
    with db.connect() as conn:
        try:
            target_skus = db.matching_product_skus(conn, q) if apply_all else (skus or [])
            if apply_all and not q.strip():
                raise ValueError("批量更新全部搜索结果时必须先输入搜索条件")
            count = db.update_product_metadata(
                conn,
                target_skus,
                set_code=set_code,
                category_id=category_id,
                category_tags=category_tags,
                themes=themes,
                update_set=update_set,
                update_category=update_category,
                update_themes=update_themes,
                reviewer_id=user["id"],
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    return {"updated": count}


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, user=Depends(require_super_admin)):
    active_section = request.query_params.get("section", "pending")
    if active_section not in {"pending", "permissions", "edits", "history", "sync"}:
        active_section = "pending"
    can_manage_access = True
    with db.connect() as conn:
        users = db.list_users(conn) if can_manage_access else []
        rules = db.list_role_rules(conn) if can_manage_access else []
        user_grants = db.list_user_grants(conn) if can_manage_access else []
        status = conn.execute("SELECT * FROM sync_status WHERE id=1").fetchone()
        nas_rows = nas_imports.list_imports(conn)
        nas_counts = nas_imports.status_counts(conn)
        edit_logs = nas_imports.list_edit_logs(conn)
        edit_log_count = conn.execute("SELECT COUNT(*) FROM nas_import_edit_logs").fetchone()[0]
        upload_history = nas_imports.list_uploaded_imports(conn)
        permission_values = db.permission_rule_values(conn) if active_section == "permissions" else {}
    selected_import_id = request.query_params.get("import_id", "")
    selected_nas_import = next((row for row in nas_rows if str(row["id"]) == selected_import_id), None)
    if not selected_nas_import and nas_rows:
        selected_nas_import = nas_rows[0]
    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "user": user,
            "users": users,
            "rules": rules,
            "user_grants": user_grants,
            "can_manage_access": can_manage_access,
            "role_options": option_rows(PERMISSION_ROLES, ROLE_LABELS),
            "permission_roles": option_rows(PERMISSION_ROLES, ROLE_LABELS),
            "permission_values": permission_values,
            "rule_scopes": option_rows(RULE_SCOPES, RULE_SCOPE_LABELS),
            "status": status,
            "nas_imports": nas_rows,
            "nas_counts": nas_counts,
            "edit_logs": edit_logs,
            "edit_log_count": edit_log_count,
            "edit_field_labels": nas_imports.EDIT_FIELD_LABELS,
            "upload_history": upload_history,
            "selected_nas_import": selected_nas_import,
            "active_section": active_section,
            "asset_types": ("image", "video", "kol_ugc", "ads", "other"),
            "message": "",
        },
    )


@app.post("/admin/users")
def admin_create_user(
    email: str = Form(...),
    name: str = Form(""),
    role: str = Form(...),
    password: str = Form(...),
    user=Depends(require_admin),
):
    role = role.strip().lower()
    if role not in CUSTOMER_ACCOUNT_ROLES:
        raise HTTPException(403, "这里只能创建海外客户、国内客户或服务商账号；管理员权限必须由超级管理员通过钉钉组织架构授予")
    with db.connect() as conn:
        try:
            db.create_customer_user_with_permissions(conn, email, name, role, password, created_by_user_id=int(user["id"]))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    return RedirectResponse("/admin?section=permissions", status_code=303)


@app.post("/admin/role-rules")
def admin_create_role_rule(
    role: str = Form(...),
    scope: str = Form(...),
    value: str = Form(...),
    user=Depends(require_super_admin),
):
    with db.connect() as conn:
        try:
            db.create_role_rule(conn, role, scope, value)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    return RedirectResponse("/admin?section=permissions", status_code=303)


@app.post("/admin/role-rules/{rule_id}/delete")
def admin_delete_role_rule(rule_id: int, user=Depends(require_super_admin)):
    with db.connect() as conn:
        db.delete_role_rule(conn, rule_id)
    return RedirectResponse("/admin?section=permissions", status_code=303)


@app.post("/admin/user-grants")
def admin_create_user_grant(
    user_id: int = Form(...),
    scope: str = Form(...),
    value: str = Form(...),
    user=Depends(require_super_admin),
):
    with db.connect() as conn:
        try:
            db.create_user_grant(conn, user_id, scope, value)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    return RedirectResponse("/admin?section=permissions", status_code=303)


@app.post("/admin/user-grants/{grant_id}/delete")
def admin_delete_user_grant(grant_id: int, user=Depends(require_super_admin)):
    with db.connect() as conn:
        db.delete_user_grant(conn, grant_id)
    return RedirectResponse("/admin?section=permissions", status_code=303)


@app.post("/admin/nas-imports/scan")
def admin_scan_nas_imports(user=Depends(require_super_admin)):
    try:
        run_nas_scan()
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc
    return admin_pending_redirect()


def resolve_admin_drive_folder(
    svc,
    root_id: str,
    parent_path: str,
    allow_missing: bool = False,
) -> tuple[str, str]:
    clean_path = ""
    folder_id = root_id
    if parent_path.strip():
        requested_path = nas_imports.ensure_relative_drive_path(parent_path)
        resolved_parts = []
        for part in nas_imports.split_drive_path(requested_path):
            found = drive.find_child(svc, folder_id, part, folder=True)
            if not found:
                if allow_missing:
                    break
                raise HTTPException(404, f"Drive folder not found: {part}")
            folder_id = found["id"]
            resolved_parts.append(part)
        clean_path = "/".join(resolved_parts)
    return folder_id, clean_path


@app.get("/admin/drive-folders")
def admin_drive_folders(parent_path: str = "", user=Depends(require_super_admin)):
    root_id = os.getenv("DRIVE_ROOT_FOLDER_ID", "")
    if not root_id:
        raise HTTPException(500, "DRIVE_ROOT_FOLDER_ID is not set")
    try:
        svc = drive.service()
        requested_path = nas_imports.ensure_relative_drive_path(parent_path) if parent_path.strip() else ""
        folder_id, clean_path = resolve_admin_drive_folder(svc, root_id, requested_path, allow_missing=True)
        drive_id = root_id if root_id.startswith("0A") else ""
        folders = []
        for item in drive.list_children(svc, folder_id, drive_id):
            if item["mimeType"] != FOLDER_MIME:
                continue
            if not clean_path and not is_included_drive_collection(item["name"]):
                continue
            path = f"{clean_path}/{item['name']}".strip("/")
            folders.append({"id": item["id"], "name": item["name"], "path": path})
        folders.sort(key=lambda item: item["name"].casefold())
        return {
            "path": clean_path,
            "requested_path": requested_path,
            "exact": clean_path == requested_path,
            "folders": folders,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/admin/drive-folders")
def admin_create_drive_folder(
    parent_path: str = Form(...),
    name: str = Form(...),
    user=Depends(require_super_admin),
):
    root_id = os.getenv("DRIVE_ROOT_FOLDER_ID", "")
    if not root_id:
        raise HTTPException(500, "DRIVE_ROOT_FOLDER_ID is not set")
    name = name.strip()
    if not parent_path.strip():
        raise HTTPException(400, "Choose a top-level collection before creating a folder")
    if not nas_imports.is_english_drive_text(name) or "/" in name or "\\" in name or name in {".", ".."}:
        raise HTTPException(400, "Drive folder name must use English ASCII text and cannot contain slashes")
    try:
        svc = drive.service([drive.DRIVE_WRITE_SCOPE])
        parent_id, clean_path = resolve_admin_drive_folder(svc, root_id, parent_path)
        existing = drive.find_child(svc, parent_id, name, folder=True)
        folder = existing or drive.create_folder(svc, parent_id, name)
        return {
            "id": folder["id"],
            "name": name,
            "path": f"{clean_path}/{name}".strip("/"),
            "created": existing is None,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc


@app.get("/admin/nas-imports/{import_id}/preview")
def admin_nas_import_preview(import_id: int, v: str = "", user=Depends(require_super_admin)):
    with db.connect() as conn:
        row = nas_imports.get_import(conn, import_id)
    if not row:
        raise HTTPException(404)
    try:
        path = populate_admin_import_thumbnail_cache(row)
    except Exception as exc:
        print(
            f"Admin import preview {import_id} unavailable ({type(exc).__name__})",
            flush=True,
        )
        return Response(
            content=thumbnails.encode_placeholder_webp("small", "OFFLINE"),
            media_type="image/webp",
            headers={
                "Cache-Control": "no-store",
                "X-Preview-State": "source-unavailable",
            },
        )
    return FileResponse(
        path,
        media_type="image/webp",
        headers={
            "Cache-Control": "private, max-age=31536000, immutable",
            "X-Preview-State": "cached",
        },
    )


@app.get("/admin/nas-imports/{import_id}/media")
def admin_nas_import_media(import_id: int, request: Request, v: str = "", user=Depends(require_super_admin)):
    with db.connect() as conn:
        row = nas_imports.get_import(conn, import_id)
    if not row or not nas_imports.is_video_import(row):
        raise HTTPException(404)

    media_type = mimetypes.guess_type(str(row["name"] or ""))[0] or "video/mp4"
    headers = {"Cache-Control": "private, max-age=3600"}
    if nas_imports.is_google_drive_row(row):
        size = int(row["size"] or 0)
        range_header = request.headers.get("range", "")
        if range_header and size:
            byte_range = parse_range_header(range_header, size)
            if not byte_range:
                return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
            start, end = byte_range
            headers.update({
                "Accept-Ranges": "bytes",
                "Content-Range": f"bytes {start}-{end}/{size}",
                "Content-Length": str(end - start + 1),
            })
            return StreamingResponse(
                drive.download_file(nas_imports.source_drive_file_id(row), start=start, end=end),
                status_code=206,
                media_type=media_type,
                headers=headers,
            )
        if size:
            headers.update({"Accept-Ranges": "bytes", "Content-Length": str(size)})
        return StreamingResponse(
            drive.download_file(nas_imports.source_drive_file_id(row)),
            media_type=media_type,
            headers=headers,
        )
    if nas_imports.is_synology_row(row):
        return StreamingResponse(
            nas_imports.download_synology_import(row),
            media_type=media_type,
            headers=headers,
        )
    path = nas_imports.row_path(row)
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type=media_type, headers=headers)


@app.post("/admin/nas-imports/{import_id}/suggest")
def admin_suggest_nas_import(import_id: int, user=Depends(require_super_admin)):
    with db.connect() as conn:
        try:
            db.init_db(conn)
            nas_imports.suggest_import(conn, import_id)
        except nas_imports.ConcurrencyConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(500, str(exc)) from exc
    return admin_pending_redirect(import_id)


@app.post("/admin/nas-imports/bulk")
def admin_bulk_nas_imports(
    import_ids: list[int] = Form(...),
    action: str = Form(...),
    batch_id: str = Form(""),
    batch_name: str = Form(""),
    user=Depends(require_super_admin),
):
    root_id = os.getenv("DRIVE_ROOT_FOLDER_ID", "")
    with db.connect() as conn:
        db.init_db(conn)
        if action == "suggest":
            nas_imports.suggest_imports(conn, import_ids)
        elif action == "approve":
            try:
                job = nas_imports.queue_import_job(
                    conn,
                    import_ids,
                    root_id,
                    user["id"],
                    batch_id=batch_id,
                    batch_name=batch_name,
                )
            except nas_imports.ConcurrencyConflict as exc:
                raise HTTPException(409, str(exc)) from exc
            except (ValueError, FileNotFoundError) as exc:
                raise HTTPException(400, str(exc)) from exc
            start_import_job(job["id"], root_id)
            return JSONResponse({"accepted": True, "job": job}, status_code=202)
        elif action == "reject":
            nas_imports.reject_imports(conn, import_ids)
        elif action == "restore":
            nas_imports.restore_imports(conn, import_ids)
        else:
            raise HTTPException(400, "Invalid bulk action")
    return admin_pending_redirect()


@app.post("/admin/nas-imports/bulk-settings")
def admin_bulk_nas_import_settings(
    import_ids: list[int] = Form(...),
    final_drive_folder: str = Form(""),
    final_set_code: str = Form(""),
    final_category_id: str = Form(""),
    final_category_tags: str = Form(""),
    final_themes: str = Form(""),
    update_themes: bool = Form(False),
    expected_revisions: list[int] | None = Form(None),
    user=Depends(require_super_admin),
):
    with db.connect() as conn:
        try:
            db.init_db(conn)
            count = nas_imports.apply_batch_settings(
                conn,
                import_ids,
                drive_folder=final_drive_folder,
                set_code=final_set_code,
                category_id=final_category_id,
                category_tags=final_category_tags,
                themes=final_themes,
                update_themes=update_themes,
                expected_revisions=expected_revisions,
            )
        except nas_imports.ConcurrencyConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    return {"updated": count}


@app.post("/admin/nas-imports/{import_id}/save")
def admin_save_nas_import(
    import_id: int,
    final_sku: str = Form(...),
    final_english_name: str = Form(...),
    final_drive_folder: str = Form(...),
    final_drive_name: str = Form(...),
    final_asset_type: str = Form("image"),
    final_set_code: str = Form(""),
    final_category_id: str = Form(""),
    final_category_tags: str = Form(""),
    final_themes: str = Form(""),
    update_themes: bool = Form(False),
    expected_revision: int | None = Form(None),
    user=Depends(require_super_admin),
):
    with db.connect() as conn:
        try:
            db.init_db(conn)
            nas_imports.save_final(
                conn, import_id, final_sku, final_english_name, final_drive_folder,
                final_drive_name, final_asset_type, final_set_code, final_category_id,
                final_category_tags,
                themes=final_themes,
                update_themes=update_themes,
                edited_by=user["id"],
                expected_revision=expected_revision,
            )
        except nas_imports.ConcurrencyConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(400, str(exc)) from exc
    return admin_pending_redirect(import_id)


@app.post("/admin/nas-imports/bulk-identity")
def admin_save_nas_import_identities(
    import_ids: list[int] = Form(...),
    final_sku: str = Form(...),
    final_english_name: str = Form(...),
    final_drive_names: list[str] = Form(...),
    expected_revisions: list[int] | None = Form(None),
    user=Depends(require_super_admin),
):
    with db.connect() as conn:
        try:
            db.init_db(conn)
            count = nas_imports.save_identities(
                conn,
                import_ids,
                final_sku,
                final_english_name,
                final_drive_names,
                edited_by=user["id"],
                expected_revisions=expected_revisions,
            )
        except nas_imports.ConcurrencyConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except sqlite3.Error as exc:
            raise HTTPException(500, f"数据库保存失败：{exc}") from exc
        except Exception as exc:
            raise HTTPException(500, f"整批保存失败：{exc}") from exc
    return {"updated": count}


@app.post("/admin/nas-imports/{import_id}/approve")
def admin_approve_nas_import(
    import_id: int,
    final_sku: str = Form(...),
    final_english_name: str = Form(...),
    final_drive_folder: str = Form(...),
    final_drive_name: str = Form(...),
    final_asset_type: str = Form("image"),
    final_set_code: str = Form(""),
    final_category_id: str = Form(""),
    final_category_tags: str = Form(""),
    final_themes: str = Form(""),
    update_themes: bool = Form(False),
    expected_revision: int | None = Form(None),
    batch_id: str = Form(""),
    batch_name: str = Form(""),
    user=Depends(require_super_admin),
):
    root_id = os.getenv("DRIVE_ROOT_FOLDER_ID", "")
    with db.connect() as conn:
        try:
            db.init_db(conn)
            nas_imports.save_final(
                conn, import_id, final_sku, final_english_name, final_drive_folder,
                final_drive_name, final_asset_type, final_set_code, final_category_id,
                final_category_tags,
                themes=final_themes,
                update_themes=update_themes,
                edited_by=user["id"],
                expected_revision=expected_revision,
            )
            row = nas_imports.get_import(conn, import_id)
            if row and not nas_imports.is_synology_row(row) and not root_id:
                raise RuntimeError("DRIVE_ROOT_FOLDER_ID is not set")
            job = nas_imports.queue_import_job(
                conn,
                [import_id],
                root_id,
                user["id"],
                batch_id=batch_id,
                batch_name=batch_name,
            )
        except nas_imports.ConcurrencyConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(500, str(exc)) from exc
    start_import_job(job["id"], root_id)
    return JSONResponse({"accepted": True, "job": job}, status_code=202)


@app.post("/admin/nas-imports/{import_id}/reject")
def admin_reject_nas_import(import_id: int, user=Depends(require_super_admin)):
    with db.connect() as conn:
        db.init_db(conn)
        nas_imports.reject_import(conn, import_id)
    return admin_pending_redirect()


@app.post("/admin/nas-imports/{import_id}/restore")
def admin_restore_nas_import(import_id: int, user=Depends(require_super_admin)):
    with db.connect() as conn:
        db.init_db(conn)
        nas_imports.restore_import(conn, import_id)
    return admin_pending_redirect()


@app.post("/admin/import-csv")
async def import_csv(file: UploadFile = File(...), user=Depends(require_super_admin)):
    content = (await file.read()).decode("utf-8-sig")
    with db.connect() as conn:
        count = db.import_meta_csv(conn, content)
    return Response(f"已导入 {count} 行", media_type="text/plain")


@app.post("/admin/sync")
def admin_sync(user=Depends(require_super_admin)):
    try:
        count = run_sync()
        return Response(f"已同步 {count} 个文件", media_type="text/plain")
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc
