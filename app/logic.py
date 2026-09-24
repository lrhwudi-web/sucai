from __future__ import annotations

import re
from pathlib import PurePosixPath

FOLDER_MIME = "application/vnd.google-apps.folder"
IGNORED_FILE_NAMES = {"thumbs.db", "desktop.ini", ".ds_store"}
INTERNAL_MARKERS = ("_internal", "内部", "源文件")
ROLES = ("super_admin", "admin", "internal_staff", "overseas_customer", "domestic_customer", "service_provider")
CUSTOMER_ACCOUNT_ROLES = ("overseas_customer", "domestic_customer", "service_provider")
PERMISSION_ROLES = ("internal_staff", *CUSTOMER_ACCOUNT_ROLES)
ROLE_LABELS = {
    "super_admin": "超级管理员",
    "admin": "管理员",
    "internal_staff": "内部员工",
    "overseas_customer": "海外客户",
    "domestic_customer": "国内客户",
    "service_provider": "服务商",
}
LEGACY_ROLE_MAP = {"internal": "internal_staff", "external": "overseas_customer"}
RULE_SCOPES = ("sku", "brand", "category", "other", "asset_type")
DRIVE_PRODUCT_COLLECTIONS = {
    "04 Product Images": "",
    "04 Product Images (No Brand)": "No Brand",
}
OTHER_COLLECTIONS = (
    "Product Catalogs",
    "Brand Assets",
    "Packaging Assets",
    "Show & Exhibitions",
    "Event & Sponsorships",
    "Influencer Assets",
    "Collection Assets",
)
OTHER_COLLECTION_ALIASES = {
    "product catalog": "Product Catalogs",
    "product catalogs": "Product Catalogs",
    "brand asset": "Brand Assets",
    "brand assets": "Brand Assets",
    "packaging asset": "Packaging Assets",
    "packaging assets": "Packaging Assets",
    "show exhibition": "Show & Exhibitions",
    "show exhibitions": "Show & Exhibitions",
    "event sponsorship": "Event & Sponsorships",
    "event sponsorships": "Event & Sponsorships",
    "events sponsorships": "Event & Sponsorships",
    "influencer asset": "Influencer Assets",
    "influencer assets": "Influencer Assets",
    "collection asset": "Collection Assets",
    "collection assets": "Collection Assets",
}
DRIVE_INCLUDED_COLLECTIONS = (*DRIVE_PRODUCT_COLLECTIONS, *OTHER_COLLECTIONS)
DRIVE_SPECIAL_CATEGORIES = ("No Brand", *OTHER_COLLECTIONS)
SET_COLLECTION_FOLDER = re.compile(r"^set\d{4,}(?:\b|[\s._-])", re.IGNORECASE)
CONCRETE_SET_SKU_FOLDER = re.compile(r"^\d{5,}(?:\b|[\s._-])")
SEVEN_DIGIT_PRODUCT_SKU = re.compile(r"(?<!\d)(\d{7})(?!\d)")
DATE_LIKE_PRODUCT_FOLDER = re.compile(r"^(?:19|20)\d{2}(?:\d{4})?(?:\D|$)")
RULE_SCOPE_LABELS = {
    "sku": "SKU",
    "brand": "品牌",
    "category": "分类",
    "other": "Other",
    "asset_type": "素材类型",
}


def is_internal_path(path: str) -> bool:
    lowered = path.lower()
    return any(marker.lower() in lowered for marker in INTERNAL_MARKERS)


def is_ignored_file(name: str) -> bool:
    lowered = name.lower()
    return lowered in IGNORED_FILE_NAMES or lowered.startswith("._")


def display_folder_name(value: str) -> str:
    return re.sub(r"^\d{2}[\s._-]+", "", value).strip()


def collection_key(value: str) -> str:
    return re.sub(
        r"[^a-z0-9]+",
        " ",
        display_folder_name(value).casefold().replace("&", " and "),
    ).strip().replace(" and ", " ")


def canonical_other_collection(name: str) -> str:
    return OTHER_COLLECTION_ALIASES.get(collection_key(name), "")


def classify_asset(path: str, mime_type: str) -> str:
    lowered = path.lower()
    parts = [part for part in path.replace("\\", "/").split("/") if part]
    folder_keys = {
        re.sub(r"[^a-z0-9]+", " ", part.casefold()).strip()
        for part in parts[:-1]
    }
    is_product_asset = bool(parts) and parts[0] in DRIVE_PRODUCT_COLLECTIONS
    has_concrete_sku = bool(infer_drive_fields(path)[3]) if is_product_asset else False
    is_kol_media = mime_type.lower().startswith(("image/", "video/"))
    if (
        is_product_asset
        and has_concrete_sku
        and is_kol_media
        and folder_keys.intersection({"kol ucg", "kol ugc"})
    ):
        return "kol_ugc"
    if mime_type.lower().startswith("application/pdf"):
        return "other"
    if any(token in lowered for token in ("ads", "ad ", "广告")):
        return "ads"
    if any(token in lowered for token in ("video", "视频")) or mime_type.startswith("video/"):
        return "video"
    if any(token in lowered for token in ("product", "产品图", "图片")) or mime_type.startswith("image/"):
        return "image"
    return "other"


def path_parts(path: str) -> list[str]:
    return [part for part in PurePosixPath(path).parts if part not in ("", "/")]


def is_included_drive_collection(name: str) -> bool:
    return name in DRIVE_PRODUCT_COLLECTIONS or bool(canonical_other_collection(name))


def special_collection_sku(parts: list[str]) -> str:
    folders = parts[:-1]
    for part in reversed(folders):
        match = re.search(r"\d{5,}", part)
        if match:
            return match.group(0)
    source = folders[0] if folders else PurePosixPath(parts[-1]).stem
    return re.sub(r"\s+", " ", source).strip().upper()


def product_sku_folder(product_folders: list[str]) -> str:
    if not product_folders:
        return ""
    first_folder = product_folders[0]
    if not SET_COLLECTION_FOLDER.match(first_folder):
        return first_folder
    if len(product_folders) < 2 or not CONCRETE_SET_SKU_FOLDER.match(product_folders[1]):
        return ""
    return product_folders[1]


def is_date_like_product_folder(value: str) -> bool:
    return bool(DATE_LIKE_PRODUCT_FOLDER.match(value.strip()))


def infer_product_sku(product_folders: list[str], file_name: str = "") -> str:
    sku_folder = product_sku_folder(product_folders)
    if sku_folder and not is_date_like_product_folder(sku_folder):
        return normalize_sku(sku_folder)

    # Reshoot folders are commonly named YYYY or YYYYMMDD. If one appears
    # where a product folder would normally be, recover the real seven-digit
    # catalog SKU from a surrounding product folder or the asset filename.
    for value in [*product_folders, PurePosixPath(file_name).stem]:
        match = SEVEN_DIGIT_PRODUCT_SKU.search(value)
        if match:
            return match.group(1)
    return ""


def infer_drive_fields(path: str) -> tuple[str, str, str, str]:
    parts = path_parts(path)
    if parts and parts[0] in DRIVE_PRODUCT_COLLECTIONS:
        collection = parts.pop(0)
        special_category = DRIVE_PRODUCT_COLLECTIONS[collection]
        if special_category:
            category = parts[0] if special_category == "No Brand" and len(parts) > 1 else ""
            folders = parts[:-1]
            product_folders = folders[1:] if len(folders) > 1 else []
            return "", category, special_category, infer_product_sku(product_folders, parts[-1] if parts else "")
    if parts:
        special_category = canonical_other_collection(parts[0])
        if special_category:
            parts.pop(0)
            return "", "", special_category, special_collection_sku(parts)
    folders = parts[:-1]
    brand = folders[0] if len(folders) > 0 else ""
    category = folders[1] if len(folders) > 1 else ""
    product_folders = folders[2:] if len(folders) > 2 else folders[-1:]
    return brand, category, "", infer_product_sku(product_folders, parts[-1] if parts else "")


def infer_brand_category_sku(path: str) -> tuple[str, str, str]:
    brand, category, _other, sku = infer_drive_fields(path)
    return brand, category, sku


def normalize_sku(value: str) -> str:
    value = value.strip()
    match = re.search(r"[A-Za-z0-9][A-Za-z0-9._-]{2,}", value)
    return match.group(0).upper() if match else value.upper()


def normalize_role(role: str) -> str:
    return LEGACY_ROLE_MAP.get(role, role)


def role_label(role: str) -> str:
    return ROLE_LABELS.get(normalize_role(role), role)


def item_get(item, key: str) -> str:
    value = item[key] if item and key in item.keys() else ""
    return "" if value is None else str(value)


def normalize_rule_value(scope: str, value: str) -> str:
    value = value.strip()
    return value.upper() if scope == "sku" else value


def is_no_brand_permission_value(value: str) -> bool:
    normalized = re.sub(r"[\s._-]+", " ", value.strip().lower())
    return normalized in {"no brand", "nobrand", "unbranded", "无牌"}


def normalize_permission_rule(scope: str, value: str) -> tuple[str, str]:
    scope = scope.strip().lower()
    value = normalize_rule_value(scope, value)
    if scope in {"brand", "other"} and is_no_brand_permission_value(value):
        return "brand", "No Brand"
    return scope, value


def permission_rule_key(rule) -> tuple[str, str]:
    scope, value = normalize_permission_rule(item_get(rule, "scope"), item_get(rule, "value"))
    return scope, value.lower()


def file_permission_value(scope: str, file_row) -> str:
    """Return the user-facing permission value for a file field.

    Unbranded product images are stored with an empty ``brand`` and the
    sentinel ``other=No Brand``.  Treat that sentinel as a real brand option
    for access-control purposes so brand rules and grants use one vocabulary.
    """
    if scope == "brand":
        brand = item_get(file_row, "brand").strip()
        if brand:
            return brand
        other = item_get(file_row, "other").strip()
        path = item_get(file_row, "path").replace("\\", "/").lower()
        if other.lower() == "no brand" or path.startswith("04 product images (no brand)/"):
            return "No Brand"
        return ""
    return item_get(file_row, scope)


def rule_matches_file(rule, file_row) -> bool:
    scope = item_get(rule, "scope")
    value = item_get(rule, "value")
    if not scope or not value:
        return False
    if scope == "path_contains":
        return value.lower() in item_get(file_row, "path").lower()
    if scope == "sku":
        return item_get(file_row, "sku").upper() == value.upper()
    if scope in ("brand", "category", "other", "asset_type"):
        return file_permission_value(scope, file_row).lower() == value.lower()
    return False


def can_user_see(
    role: str,
    internal_only: bool,
    file_row=None,
    rules=(),
    grants=(),
    permission_mode: str = "role_default",
) -> bool:
    role = normalize_role(role)
    if role in {"super_admin", "admin"}:
        return True
    if internal_only and role != "internal_staff":
        return False
    if not file_row:
        return True
    matching_grants = {
        permission_rule_key(grant)
        for grant in grants
        if rule_matches_file(grant, file_row)
    }
    if permission_mode == "allowlist" and not matching_grants:
        return False
    for rule in rules:
        if not rule_matches_file(rule, file_row):
            continue
        key = permission_rule_key(rule)
        # Special-collection hiding is absolute at the role level. Individual
        # exceptions remain supported for brands (including No Brand), but a
        # stale or overly broad account grant must not reopen hidden collections.
        if key[0] == "other" or key not in matching_grants:
            return False
    return True
