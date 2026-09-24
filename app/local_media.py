from __future__ import annotations

import hashlib
import os
import threading
from collections.abc import Callable, Iterable, Iterator, Mapping
from pathlib import Path


PDF_CACHE_VERSION = "catalog-pdf-v1"
_cache_locks_guard = threading.Lock()
_cache_locks: dict[str, threading.Lock] = {}


def row_value(row: Mapping[str, object], key: str, default: object = "") -> object:
    try:
        return row[key]
    except (KeyError, TypeError, IndexError):
        return default


def is_product_catalog_pdf(row: Mapping[str, object]) -> bool:
    mime_type = str(row_value(row, "mime_type") or "").lower()
    other = str(row_value(row, "other") or "").strip()
    return mime_type.startswith("application/pdf") and other == "Product Catalogs"


def pdf_cache_identity(row: Mapping[str, object]) -> str:
    return "|".join(
        (
            PDF_CACHE_VERSION,
            str(row_value(row, "id") or ""),
            str(row_value(row, "modified_time") or ""),
            str(row_value(row, "size", 0) or 0),
        )
    )


def pdf_cache_path(cache_dir: Path, row: Mapping[str, object]) -> Path:
    digest = hashlib.sha256(pdf_cache_identity(row).encode("utf-8")).hexdigest()
    return cache_dir / f"{digest}.pdf"


def ensure_pdf_cached(
    cache_dir: Path,
    row: Mapping[str, object],
    downloader: Callable[[], Iterable[bytes]],
) -> Path:
    target = pdf_cache_path(cache_dir, row)
    expected_size = int(row_value(row, "size", 0) or 0)

    def cache_is_valid() -> bool:
        return target.is_file() and (expected_size <= 0 or target.stat().st_size == expected_size)

    if cache_is_valid():
        return target

    cache_dir.mkdir(parents=True, exist_ok=True)
    with _cache_locks_guard:
        lock = _cache_locks.setdefault(target.name, threading.Lock())

    with lock:
        if cache_is_valid():
            return target
        if target.exists():
            target.unlink()
        temporary = target.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            with temporary.open("wb") as output:
                for chunk in downloader():
                    if chunk:
                        output.write(chunk)
            if expected_size > 0 and temporary.stat().st_size != expected_size:
                raise RuntimeError(
                    f"Downloaded PDF size mismatch: expected {expected_size}, got {temporary.stat().st_size}"
                )
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    return target


def iter_file_range(path: Path, start: int, end: int, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
    remaining = end - start + 1
    with path.open("rb") as source:
        source.seek(start)
        while remaining > 0:
            chunk = source.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk

