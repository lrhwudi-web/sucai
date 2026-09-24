from __future__ import annotations

import hashlib
import os
import re
import threading
import time
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Iterable, Mapping

from PIL import Image, ImageDraw, ImageFont, ImageOps


ENCODER_VERSION = "webp-v1"


@dataclass(frozen=True)
class ThumbnailVariant:
    name: str
    width: int
    height: int
    quality: int

    @property
    def size(self) -> tuple[int, int]:
        return self.width, self.height


VARIANTS = {
    "small": ThumbnailVariant("small", 126, 110, 68),
    "card": ThumbnailVariant("card", 440, 360, 72),
    "drawer": ThumbnailVariant("drawer", 560, 416, 75),
}

_CACHE_FILE_PATTERN = re.compile(r"^[a-f0-9]{64}\.(?:webp|jpe?g|png|gif)$", re.IGNORECASE)
LEGACY_CACHE_SUFFIXES = (".jpg", ".png", ".webp", ".gif")


def variant(name: str) -> ThumbnailVariant:
    normalized = (name or "card").strip().lower()
    try:
        return VARIANTS[normalized]
    except KeyError as exc:
        allowed = ", ".join(VARIANTS)
        raise ValueError(f"Unknown thumbnail variant {name!r}; expected one of: {allowed}") from exc


def _row_value(row: Mapping[str, object], key: str) -> str:
    try:
        return str(row[key] or "")
    except (KeyError, TypeError, IndexError):
        return ""


def cache_identity(row: Mapping[str, object], variant_name: str) -> str:
    spec = variant(variant_name)
    return "\0".join(
        (
            _row_value(row, "id"),
            _row_value(row, "modified_time"),
            spec.name,
            ENCODER_VERSION,
        )
    )


def cache_key(row: Mapping[str, object], variant_name: str) -> str:
    return hashlib.sha256(cache_identity(row, variant_name).encode("utf-8")).hexdigest()


def legacy_cache_key(row: Mapping[str, object]) -> str:
    identity = "\0".join((_row_value(row, "id"), _row_value(row, "modified_time")))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def cache_path(cache_dir: Path, row: Mapping[str, object], variant_name: str) -> Path:
    return cache_dir / f"{cache_key(row, variant_name)}.webp"


def encode_webp(source: bytes | Path, variant_name: str) -> bytes:
    spec = variant(variant_name)
    image_source = BytesIO(source) if isinstance(source, bytes) else source
    with Image.open(image_source) as opened:
        opened.seek(0)
        image = ImageOps.exif_transpose(opened).convert("RGBA")

    contained = ImageOps.contain(image, spec.size, method=Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", spec.size, (255, 255, 255, 0))
    offset = ((spec.width - contained.width) // 2, (spec.height - contained.height) // 2)
    canvas.paste(contained, offset, contained)

    output = BytesIO()
    canvas.save(
        output,
        format="WEBP",
        quality=spec.quality,
        method=4,
        exact=True,
    )
    return output.getvalue()


def write_webp(source: bytes | Path, target: Path, variant_name: str) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target.with_name(
        f".{target.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    try:
        temp_path.write_bytes(encode_webp(source, variant_name))
        os.replace(temp_path, target)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return target


def encode_placeholder_webp(variant_name: str, label: str) -> bytes:
    spec = variant(variant_name)
    canvas = Image.new("RGBA", spec.size, (237, 241, 238, 255))
    draw = ImageDraw.Draw(canvas)
    margin = max(8, spec.width // 8)
    top = max(8, spec.height // 5)
    bottom = spec.height - top
    draw.rounded_rectangle(
        (margin, top, spec.width - margin, bottom),
        radius=max(5, spec.width // 24),
        outline=(111, 129, 118, 255),
        width=max(2, spec.width // 50),
    )
    font_size = max(12, spec.height // 7)
    try:
        font = ImageFont.truetype("arialbd.ttf", font_size)
    except OSError:
        font = ImageFont.load_default()
    normalized = (label or "FILE").strip().upper()[:10]
    bounds = draw.textbbox((0, 0), normalized, font=font)
    text_width = bounds[2] - bounds[0]
    text_height = bounds[3] - bounds[1]
    draw.text(
        ((spec.width - text_width) // 2, (spec.height - text_height) // 2),
        normalized,
        fill=(82, 98, 89, 255),
        font=font,
    )
    output = BytesIO()
    canvas.save(output, format="WEBP", quality=spec.quality, method=4, exact=True)
    return output.getvalue()


def write_placeholder_webp(target: Path, variant_name: str, label: str) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target.with_name(
        f".{target.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    try:
        temp_path.write_bytes(encode_placeholder_webp(variant_name, label))
        os.replace(temp_path, target)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return target


def active_cache_names(
    rows: Iterable[Mapping[str, object]],
    variant_names: Iterable[str] = VARIANTS,
) -> set[str]:
    return {
        cache_path(Path("."), row, variant_name).name
        for row in rows
        for variant_name in variant_names
    }


def active_legacy_cache_names(rows: Iterable[Mapping[str, object]]) -> set[str]:
    return {
        f"{legacy_cache_key(row)}{suffix}"
        for row in rows
        for suffix in LEGACY_CACHE_SUFFIXES
    }


def cleanup_cache(
    cache_dir: Path,
    active_names: set[str],
    grace_seconds: int,
    now: float | None = None,
) -> int:
    if not cache_dir.exists():
        return 0
    current_time = time.time() if now is None else now
    removed = 0
    for path in cache_dir.iterdir():
        if not path.is_file() or path.name in active_names:
            continue
        is_cache_file = bool(_CACHE_FILE_PATTERN.fullmatch(path.name))
        is_temp_file = path.name.startswith(".") and path.name.endswith(".tmp")
        if not is_cache_file and not is_temp_file:
            continue
        try:
            age = current_time - path.stat().st_mtime
            if age < grace_seconds:
                continue
            path.unlink()
            removed += 1
        except OSError:
            continue
    return removed
