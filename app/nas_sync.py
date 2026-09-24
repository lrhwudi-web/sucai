from __future__ import annotations

import csv
import mimetypes
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from . import drive

PRODUCT_TABLE_COLUMNS = {"SKU", "品名", "英文品名", "品牌", "产品类型", "自动Set"}
BRAND_CODES = {"Craftsman Golf": "CF"}
BRAND_FOLDERS = {"Craftsman Golf": "01 Craftsman Golf"}
NAS_BRAND_FOLDERS = {"Craftsman Golf": "Craftsman"}
TYPE_TO_NAS_FOLDERS = {
    "1号木杆套": ["帽套", "木杆帽套"],
    "一号木杆套": ["帽套", "木杆帽套"],
    "直条推杆套": ["帽套", "推杆帽套"],
    "半圆推杆套": ["帽套", "推杆帽套"],
    "推杆套": ["帽套", "推杆帽套"],
    "铁杆套": ["帽套", "铁杆帽套"],
    "毛线帽套": ["帽套", "毛线帽套"],
    "公仔（动物）帽套": ["帽套", "公仔（动物）帽套"],
}
HEAD_COVER_TYPES = set(TYPE_TO_NAS_FOLDERS)


@dataclass(frozen=True)
class PathMapping:
    nas_prefix: str
    drive_prefix: str
    drive_name_template: str = ""


@dataclass(frozen=True)
class UploadPlan:
    local_path: Path
    source_rel: str
    drive_folder_parts: list[str]
    drive_name: str
    size: int
    mtime_ns: int
    mime_type: str

    @property
    def drive_path(self) -> str:
        return "/".join([*self.drive_folder_parts, self.drive_name])


@dataclass
class SyncSummary:
    planned: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    unmapped: int = 0
    settling: int = 0
    indexed_files: int = 0


def normalize_posix(value: str | Path) -> str:
    return "/".join(part for part in str(value).replace("\\", "/").strip().strip("/").split("/") if part and part != ".")


def split_posix(value: str) -> list[str]:
    normalized = normalize_posix(value)
    return normalized.split("/") if normalized else []


def row_get(row: dict[str, str], *names: str) -> str:
    for name in names:
        value = (row.get(name) or "").strip()
        if value:
            return value
    return ""


def brand_code(brand: str) -> str:
    return BRAND_CODES.get(brand, "".join(part[:1] for part in brand.split()).upper() or brand[:2].upper())


def strip_cover_suffix(english_name: str) -> str:
    suffixes = (
        " Blade Putter Cover",
        " Mallet Putter Cover",
        " Driver Cover",
        " Fairway Cover",
        " Hybrid Cover",
        " Putter Cover",
        " Iron Cover",
        " Headcover",
        " Cover",
    )
    for suffix in suffixes:
        if english_name.endswith(suffix):
            return english_name[: -len(suffix)].strip()
    return english_name.strip()


def common_set_name(rows: list[dict[str, str]]) -> str:
    names = [strip_cover_suffix(row_get(row, "英文品名", "english_name")) for row in rows if row_get(row, "英文品名", "english_name")]
    if not names:
        return ""
    words = names[0].split()
    for name in names[1:]:
        other = name.split()
        words = [left for left, right in zip(words, other) if left == right]
        if not words:
            return names[0]
    return " ".join(words) or names[0]


def product_drive_category(product_type: str) -> str:
    return "01 Headcover Set" if product_type in HEAD_COVER_TYPES else product_type


def product_to_mapping(row: dict[str, str], set_rows: dict[str, list[dict[str, str]]]) -> PathMapping | None:
    sku = row_get(row, "SKU", "sku")
    name = row_get(row, "品名", "name")
    english_name = row_get(row, "英文品名", "english_name")
    brand = row_get(row, "品牌", "brand")
    product_type = row_get(row, "产品类型", "product_type")
    auto_set = row_get(row, "自动Set", "auto_set")
    if not all((sku, name, english_name, brand, product_type)):
        return None

    code = brand_code(brand)
    set_name = common_set_name(set_rows.get(auto_set, [row]))
    set_folder = f"{auto_set} {code} - {set_name} Headcover Set" if auto_set and set_name else auto_set
    nas_type_parts = TYPE_TO_NAS_FOLDERS.get(product_type, [product_type])
    nas_prefix = "/".join(["产品图片", NAS_BRAND_FOLDERS.get(brand, brand), *nas_type_parts, f"{sku} {name}"])
    drive_prefix = "/".join(
        [
            "04 Product Images",
            BRAND_FOLDERS.get(brand, brand),
            product_drive_category(product_type),
            set_folder,
            f"{sku} {code} - {english_name}",
        ]
    )
    return PathMapping(nas_prefix, drive_prefix, "{sku}({stem}){suffix}")


def load_mappings(path: Path) -> list[PathMapping]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = set(reader.fieldnames or [])
        rows = list(reader)
        if {"nas_prefix", "drive_prefix"}.issubset(fieldnames):
            mappings = [
                PathMapping(
                    normalize_posix(row.get("nas_prefix", "")),
                    normalize_posix(row.get("drive_prefix", "")),
                    (row.get("drive_name_template") or "").strip(),
                )
                for row in rows
                if normalize_posix(row.get("nas_prefix", "")) and normalize_posix(row.get("drive_prefix", ""))
            ]
        elif PRODUCT_TABLE_COLUMNS.issubset(fieldnames):
            grouped: dict[str, list[dict[str, str]]] = {}
            for row in rows:
                grouped.setdefault(row_get(row, "自动Set", "auto_set"), []).append(row)
            mappings = [mapping for row in rows if (mapping := product_to_mapping(row, grouped))]
        else:
            raise ValueError("Mapping CSV must include nas_prefix/drive_prefix or SKU/品名/英文品名/品牌/产品类型/自动Set columns")
    return sorted(mappings, key=lambda item: len(item.nas_prefix), reverse=True)


def match_mapping(source_rel: str, mappings: Iterable[PathMapping]) -> tuple[PathMapping, str] | None:
    for mapping in mappings:
        if source_rel == mapping.nas_prefix:
            return mapping, ""
        prefix = f"{mapping.nas_prefix}/"
        if source_rel.startswith(prefix):
            return mapping, source_rel[len(prefix) :]
    return None


def render_drive_name(source_name: str, template: str, **values: str) -> str:
    if not template:
        return source_name
    suffix = Path(source_name).suffix
    stem = source_name[: -len(suffix)] if suffix else source_name
    name = template.format(name=source_name, stem=stem, suffix=suffix, **values)
    if not name or "/" in name or "\\" in name:
        raise ValueError(f"Invalid drive_name_template result: {name!r}")
    return name


def plan_file(
    local_path: Path,
    source_root: Path,
    mappings: list[PathMapping],
    now: float | None = None,
    settle_seconds: int = 60,
) -> tuple[UploadPlan | None, str]:
    stat = local_path.stat()
    now = time.time() if now is None else now
    if settle_seconds and now - stat.st_mtime < settle_seconds:
        return None, "settling"

    source_rel = normalize_posix(local_path.relative_to(source_root))
    matched = match_mapping(source_rel, mappings)
    if not matched:
        return None, "unmapped"

    mapping, rest = matched
    rest_parts = split_posix(rest) or [local_path.name]
    drive_folder_parts = [*split_posix(mapping.drive_prefix), *rest_parts[:-1]]
    sku = split_posix(mapping.nas_prefix)[-1].split(" ", 1)[0]
    drive_name = render_drive_name(rest_parts[-1], mapping.drive_name_template, sku=sku)
    mime_type = mimetypes.guess_type(local_path.name)[0] or "application/octet-stream"
    return (
        UploadPlan(
            local_path=local_path,
            source_rel=source_rel,
            drive_folder_parts=drive_folder_parts,
            drive_name=drive_name,
            size=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
            mime_type=mime_type,
        ),
        "",
    )


def remote_is_current(remote: dict | None, plan: UploadPlan) -> bool:
    if not remote:
        return False
    props = remote.get("appProperties") or {}
    return props.get("nasSize") == str(plan.size) and props.get("nasMtimeNs") == str(plan.mtime_ns)


def app_properties(plan: UploadPlan) -> dict[str, str]:
    return {"nasSize": str(plan.size), "nasMtimeNs": str(plan.mtime_ns)}


def sync_to_drive(
    source_root: Path,
    mapping_file: Path,
    root_id: str,
    dry_run: bool = False,
    settle_seconds: int = 60,
    refresh_index: bool = True,
) -> SyncSummary:
    if not source_root.exists():
        raise FileNotFoundError(f"NAS_SOURCE_DIR not found: {source_root}")
    mappings = load_mappings(mapping_file)
    summary = SyncSummary()
    svc = None if dry_run else drive.service([drive.DRIVE_WRITE_SCOPE])

    for local_path in sorted(path for path in source_root.rglob("*") if path.is_file()):
        plan, reason = plan_file(local_path, source_root, mappings, settle_seconds=settle_seconds)
        if not plan:
            if reason == "settling":
                summary.settling += 1
            elif reason == "unmapped":
                summary.unmapped += 1
            continue

        summary.planned += 1
        print(f"{'DRY ' if dry_run else ''}{plan.source_rel} -> {plan.drive_path}")
        if dry_run:
            continue

        parent_id = drive.ensure_folder_path(svc, root_id, plan.drive_folder_parts)
        remote = drive.find_child(svc, parent_id, plan.drive_name, folder=False)
        if remote_is_current(remote, plan):
            summary.unchanged += 1
            continue

        drive.upload_file(
            svc,
            plan.local_path,
            parent_id,
            plan.drive_name,
            plan.mime_type,
            app_properties(plan),
            file_id=remote["id"] if remote else None,
        )
        if remote:
            summary.updated += 1
        else:
            summary.created += 1

    if refresh_index and not dry_run and (summary.created or summary.updated):
        from .main import run_sync

        summary.indexed_files = run_sync()
    return summary


def mapping_path_from_env() -> Path:
    return Path(os.getenv("NAS_SYNC_MAPPING", "data/nas_drive_map.csv"))
