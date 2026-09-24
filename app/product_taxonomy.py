from __future__ import annotations

import csv
import json
import re
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from .category_kit import Classifier, ProductInput


PACKAGE_DIR = Path(__file__).with_name("category_kit")
TAXONOMY_PATH = PACKAGE_DIR / "config" / "taxonomy.json"
REGISTRY_PATH = PACKAGE_DIR / "data" / "sku_registry.csv"
REGISTRY_VERSION = "golf-product-taxonomy-2.0.0-mytag"
CATALOGUE_BACKFILL_VERSION = "golf-product-taxonomy-1.0.0-catalogue-rules-v2"
PENDING_BACKFILL_VERSION = "golf-product-taxonomy-1.0.0-pending-imports"
NORMALIZE_VERSION = "golf-product-taxonomy-2.0.0-normalize-existing"
CANONICAL_ENGLISH_LABELS_VERSION = "golf-product-taxonomy-2.0.0-canonical-english-labels-v1"
VERIFIED_REGISTRY_STATUSES = {"imported_verified", "derived_high", "human_approved"}
CATEGORY_GROUPS = ("Golf Headcover", "Golf Accessories")
THEME_OPTIONS = (
    {"id": "AMERICANA", "label": "Americana"},
    {"id": "LUCKY_CLOVER", "label": "Lucky & Clover"},
    {"id": "POP_CULTURE_ENTERTAINMENT", "label": "Pop Culture & Entertainment"},
    {"id": "FOOD_DRINKS", "label": "Food & Drinks"},
    {"id": "ANIMALS", "label": "Animals"},
    {"id": "WOMENS_GIRLS", "label": "Women's & Girls"},
    {"id": "SKULLS_GOTHIC", "label": "Skulls & Gothic"},
    {"id": "CLASSIC_RETRO", "label": "Classic & Retro"},
    {"id": "LIMITED_EDITION", "label": "Limited Edition"},
)


@lru_cache(maxsize=1)
def taxonomy_document() -> dict:
    return json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def categories_by_id() -> dict[str, dict]:
    return {item["id"]: item for item in taxonomy_document()["categories"]}


def category_options(
    conn: sqlite3.Connection | None = None,
    *,
    include_unknown: bool = False,
) -> list[dict]:
    options = []
    for item in taxonomy_document()["categories"]:
        if not item.get("active", True):
            continue
        if item["id"] == "UNKNOWN" and not include_unknown:
            continue
        options.append(
            {
                "id": item["id"],
                "group": item["group"],
                "label_zh": item["label_zh"],
                "label_en": item["label_en"],
            }
        )
    if conn is not None:
        try:
            rows = conn.execute(
                """
                SELECT id, group_name, label_zh, label_en
                FROM custom_product_categories
                WHERE active=1
                ORDER BY group_name, sort_order, label_en
                """
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        options.extend(
            {
                "id": row["id"],
                "group": row["group_name"],
                "label_zh": row["label_zh"],
                "label_en": row["label_en"],
            }
            for row in rows
        )
    return options


def tag_options() -> list[dict]:
    return [
        {
            "id": item["id"],
            "label_zh": item["label_zh"],
            "label_en": item["label_en"],
        }
        for item in taxonomy_document().get("tags", [])
    ]


def theme_options(conn: sqlite3.Connection | None = None) -> list[dict]:
    options = [dict(item) for item in THEME_OPTIONS]
    if conn is None:
        return options
    try:
        rows = conn.execute(
            """
            SELECT id, label
            FROM custom_product_themes
            WHERE active=1
            ORDER BY sort_order, label
            """
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    options.extend({"id": row["id"], "label": row["label"]} for row in rows)
    return options


def normalize_themes(
    themes: str | Iterable[str],
    conn: sqlite3.Connection | None = None,
) -> str:
    values = themes.split("|") if isinstance(themes, str) else themes
    requested = {str(value).strip().upper() for value in values if str(value).strip()}
    options = theme_options(conn)
    valid = {item["id"] for item in options}
    invalid = sorted(requested - valid)
    if invalid:
        raise ValueError(f"Unknown theme: {', '.join(invalid)}")
    return "|".join(item["id"] for item in options if item["id"] in requested)


def theme_labels(
    themes: str | Iterable[str],
    options: Iterable[dict] | None = None,
) -> list[str]:
    values = themes.split("|") if isinstance(themes, str) else themes
    requested = {str(value).strip().upper() for value in values if str(value).strip()}
    return [
        item["label"]
        for item in (list(options) if options is not None else theme_options())
        if item["id"] in requested
    ]


def create_custom_theme(
    conn: sqlite3.Connection,
    *,
    label: str,
    created_by: int | None = None,
) -> dict:
    label = " ".join(label.split())
    if len(label) < 2 or len(label) > 80:
        raise ValueError("Theme name must contain 2–80 characters.")
    if any(item["label"].casefold() == label.casefold() for item in theme_options(conn)):
        raise ValueError("This theme already exists.")
    slug = re.sub(r"[^A-Z0-9]+", "_", label.upper()).strip("_")[:42] or "THEME"
    theme_id = f"CUSTOM_{slug}"
    suffix = 2
    while conn.execute("SELECT 1 FROM custom_product_themes WHERE id=?", (theme_id,)).fetchone():
        theme_id = f"CUSTOM_{slug}_{suffix}"
        suffix += 1
    sort_order = conn.execute(
        "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM custom_product_themes"
    ).fetchone()[0]
    with conn:
        conn.execute(
            """
            INSERT INTO custom_product_themes(id, label, sort_order, created_by)
            VALUES (?, ?, ?, ?)
            """,
            (theme_id, label, sort_order, created_by),
        )
    return {"id": theme_id, "label": label}


def category_details(category_id: str, conn: sqlite3.Connection | None = None) -> dict:
    details = categories_by_id().get(category_id)
    if details:
        return details
    if conn is not None and category_id.startswith("CUSTOM_"):
        row = conn.execute(
            """
            SELECT id, group_name AS "group", label_zh, label_en, active
            FROM custom_product_categories WHERE id=?
            """,
            (category_id,),
        ).fetchone()
        if row:
            return dict(row)
    return categories_by_id()["UNKNOWN"]


def validate_category_id(
    category_id: str,
    conn: sqlite3.Connection | None = None,
    *,
    allow_unknown: bool = False,
) -> str:
    category_id = (category_id or "").strip().upper()
    details = category_details(category_id, conn)
    if not category_id or (details["id"] == "UNKNOWN" and category_id != "UNKNOWN"):
        raise ValueError("Please select a category from the product taxonomy.")
    if (category_id == "UNKNOWN" or not details.get("active", True)) and not allow_unknown:
        raise ValueError("Inactive or review-only categories cannot be assigned.")
    return category_id


def create_custom_category(
    conn: sqlite3.Connection,
    *,
    group: str,
    label_en: str,
    label_zh: str = "",
    created_by: int | None = None,
) -> dict:
    group = group.strip()
    label_en = " ".join(label_en.split())
    label_zh = " ".join(label_zh.split())
    if group not in CATEGORY_GROUPS:
        raise ValueError("Custom categories must belong to Golf Headcover or Golf Accessories.")
    if len(label_en) < 2 or len(label_en) > 80:
        raise ValueError("English category name must contain 2–80 characters.")
    duplicate = conn.execute(
        "SELECT id FROM custom_product_categories WHERE lower(label_en)=lower(?)",
        (label_en,),
    ).fetchone()
    if duplicate:
        raise ValueError("This category already exists.")
    slug = re.sub(r"[^A-Z0-9]+", "_", label_en.upper()).strip("_")[:42] or "CATEGORY"
    category_id = f"CUSTOM_{slug}"
    suffix = 2
    while conn.execute("SELECT 1 FROM custom_product_categories WHERE id=?", (category_id,)).fetchone():
        category_id = f"CUSTOM_{slug}_{suffix}"
        suffix += 1
    sort_order = conn.execute(
        "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM custom_product_categories WHERE group_name=?",
        (group,),
    ).fetchone()[0]
    conn.execute(
        """
        INSERT INTO custom_product_categories(
          id, group_name, label_en, label_zh, sort_order, created_by
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (category_id, group, label_en, label_zh, sort_order, created_by),
    )
    conn.commit()
    return {
        "id": category_id,
        "group": group,
        "label_en": label_en,
        "label_zh": label_zh,
    }


def canonical_category_id(category_id: str, tags: str | Iterable[str] = "") -> str:
    tag_values = tags.split("|") if isinstance(tags, str) else list(tags)
    if "PLUSH_ANIMAL" in tag_values:
        return "HC_PLUSH"
    return taxonomy_document().get("legacy_category_remap", {}).get(category_id, category_id)


def normalize_tags(tags: str | Iterable[str]) -> str:
    values = tags.split("|") if isinstance(tags, str) else tags
    valid = {item["id"] for item in taxonomy_document().get("tags", [])}
    return "|".join(sorted({str(value).strip() for value in values if str(value).strip() in valid}))


class DatabaseOverrideStore:
    """Expose administrator-approved SKU corrections to the fixed classifier."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get_override(self, sku: str) -> dict | None:
        row = self.conn.execute(
            """
            SELECT category_id, category_tags
            FROM sku_meta
            WHERE sku=? AND category_source='human_correction' AND category_id <> ''
            """,
            (sku.strip().upper(),),
        ).fetchone()
        if not row:
            return None
        return {
            "category_id": row["category_id"],
            "tags": row["category_tags"] or "",
        }


def classify_product(
    conn: sqlite3.Connection,
    *,
    sku: str = "",
    name: str = "",
    english_name: str = "",
    path: str = "",
    raw_category: str = "",
    external_id: str = "",
) -> dict:
    classifier = Classifier(PACKAGE_DIR, store=DatabaseOverrideStore(conn))
    result = classifier.classify(
        ProductInput(
            sku=sku,
            name=name,
            english_name=english_name,
            path=path,
            raw_category=raw_category,
            external_id=external_id,
        )
    )
    details = category_details(result.category_id, conn)
    return {
        **result.to_dict(),
        "category_label_zh": details["label_zh"],
        "category_label_en": details["label_en"],
        "category_group": details["group"],
    }


def import_registry(conn: sqlite3.Connection) -> int:
    if not REGISTRY_PATH.exists():
        return 0
    with REGISTRY_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    payload = []
    for row in rows:
        sku = (row.get("sku") or "").strip().upper()
        tags = normalize_tags(row.get("tags") or "")
        category_id = canonical_category_id(
            (row.get("category_id") or "UNKNOWN").strip(),
            tags,
        )
        if not sku or category_id not in categories_by_id():
            continue
        details = category_details(category_id, conn)
        verification_status = row.get("verification_status") or "needs_review"
        payload.append(
            (
                sku,
                row.get("english_name") or "",
                row.get("chinese_name") or "",
                details["label_en"] if category_id != "UNKNOWN" else "",
                category_id,
                details["label_zh"],
                tags,
                float(row.get("confidence") or 0),
                "sku_registry",
                "verified" if verification_status in VERIFIED_REGISTRY_STATUSES else "needs_review",
                row.get("evidence") or "",
                taxonomy_document()["version"],
                row.get("source_sheet") or "",
            )
        )
    conn.executemany(
        """
        INSERT INTO sku_meta(
          sku, english_name, chinese_name, category, category_id, category_zh,
          category_tags, category_confidence, category_source, category_status,
          category_reason, taxonomy_version, source_sheet
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(sku) DO UPDATE SET
          english_name=CASE
            WHEN sku_meta.english_name <> '' THEN sku_meta.english_name
            ELSE excluded.english_name
          END,
          chinese_name=CASE
            WHEN sku_meta.chinese_name <> '' THEN sku_meta.chinese_name
            ELSE excluded.chinese_name
          END,
          category=CASE
            WHEN sku_meta.category_source='human_correction' THEN sku_meta.category
            ELSE excluded.category
          END,
          category_id=CASE
            WHEN sku_meta.category_source='human_correction' THEN sku_meta.category_id
            ELSE excluded.category_id
          END,
          category_zh=CASE
            WHEN sku_meta.category_source='human_correction' THEN sku_meta.category_zh
            ELSE excluded.category_zh
          END,
          category_tags=CASE
            WHEN sku_meta.category_source='human_correction' THEN sku_meta.category_tags
            ELSE excluded.category_tags
          END,
          category_confidence=CASE
            WHEN sku_meta.category_source='human_correction' THEN sku_meta.category_confidence
            ELSE excluded.category_confidence
          END,
          category_source=CASE
            WHEN sku_meta.category_source='human_correction' THEN sku_meta.category_source
            ELSE excluded.category_source
          END,
          category_status=CASE
            WHEN sku_meta.category_source='human_correction' THEN sku_meta.category_status
            ELSE excluded.category_status
          END,
          category_reason=CASE
            WHEN sku_meta.category_source='human_correction' THEN sku_meta.category_reason
            ELSE excluded.category_reason
          END,
          taxonomy_version=CASE
            WHEN sku_meta.category_source='human_correction' THEN sku_meta.taxonomy_version
            ELSE excluded.taxonomy_version
          END,
          source_sheet=CASE
            WHEN sku_meta.source_sheet <> '' THEN sku_meta.source_sheet
            ELSE excluded.source_sheet
          END
        """,
        payload,
    )
    return len(payload)


def backfill_catalogue_categories(conn: sqlite3.Connection) -> int:
    """Normalize legacy catalogue rows only when fixed rules are unambiguous."""

    rows = conn.execute(
        """
        SELECT f.sku, MIN(f.category) AS raw_category, MIN(f.path) AS path,
               COALESCE(m.english_name, '') AS english_name
        FROM files f
        LEFT JOIN sku_meta m ON m.sku=f.sku
        WHERE f.sku <> ''
          AND COALESCE(m.category_status, 'unclassified')='unclassified'
          AND COALESCE(m.category_source, '') <> 'human_correction'
        GROUP BY f.sku, m.english_name
        ORDER BY f.sku
        """
    ).fetchall()
    updates = []
    for row in rows:
        result = classify_product(
            conn,
            sku=row["sku"],
            name=row["english_name"],
            english_name=row["english_name"],
            path=row["path"],
            raw_category=row["raw_category"],
        )
        if (
            result["category_id"] == "UNKNOWN"
            or result["needs_review"]
            or float(result["confidence"]) < 0.95
        ):
            continue
        details = category_details(result["category_id"])
        updates.append(
            (
                details["label_en"],
                result["category_id"],
                details["label_zh"],
                normalize_tags(result["tags"]),
                float(result["confidence"]),
                result["source"],
                result["reason"],
                taxonomy_document()["version"],
                row["sku"],
            )
        )
    conn.executemany(
        """
        INSERT INTO sku_meta(
          category, category_id, category_zh, category_tags, category_confidence,
          category_source, category_status, category_reason, taxonomy_version,
          category_updated_at, sku
        ) VALUES (?, ?, ?, ?, ?, ?, 'verified', ?, ?, CURRENT_TIMESTAMP, ?)
        ON CONFLICT(sku) DO UPDATE SET
          category=excluded.category,
          category_id=excluded.category_id,
          category_zh=excluded.category_zh,
          category_tags=excluded.category_tags,
          category_confidence=excluded.category_confidence,
          category_source=excluded.category_source,
          category_status=excluded.category_status,
          category_reason=excluded.category_reason,
          taxonomy_version=excluded.taxonomy_version,
          category_updated_at=CURRENT_TIMESTAMP
        WHERE sku_meta.category_status='unclassified'
        """,
        updates,
    )
    return len(updates)


def normalize_existing_categories(conn: sqlite3.Connection) -> int:
    updates = []
    for row in conn.execute(
        """
        SELECT sku, category_id, category_tags
        FROM sku_meta
        WHERE category_id <> ''
        """
    ).fetchall():
        category_id = canonical_category_id(row["category_id"], row["category_tags"])
        details = category_details(category_id, conn)
        if details["id"] == "UNKNOWN":
            continue
        updates.append(
            (
                details["label_en"],
                category_id,
                details["label_zh"],
                taxonomy_document()["version"],
                row["sku"],
            )
        )
    conn.executemany(
        """
        UPDATE sku_meta
        SET category=?, category_id=?, category_zh=?, taxonomy_version=?,
            category_updated_at=CURRENT_TIMESTAMP
        WHERE sku=?
        """,
        updates,
    )

    import_updates = []
    for row in conn.execute(
        """
        SELECT id, suggested_category_id, suggested_category_tags,
               final_category_id, final_category_tags
        FROM nas_imports
        """
    ).fetchall():
        suggested = (
            canonical_category_id(row["suggested_category_id"], row["suggested_category_tags"])
            if row["suggested_category_id"]
            else ""
        )
        final = (
            canonical_category_id(row["final_category_id"], row["final_category_tags"])
            if row["final_category_id"]
            else ""
        )
        import_updates.append((suggested, final, row["id"]))
    conn.executemany(
        """
        UPDATE nas_imports
        SET suggested_category_id=?, final_category_id=?, updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        import_updates,
    )
    return len(updates)


def backfill_pending_imports(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        """
        SELECT *
        FROM nas_imports
        WHERE status NOT IN ('uploaded', 'rejected')
          AND suggested_category_id=''
        ORDER BY id
        """
    ).fetchall()
    if not rows:
        return 0
    classifier = Classifier(PACKAGE_DIR, store=DatabaseOverrideStore(conn))
    updates = []
    for row in rows:
        sku = (row["final_sku"] or row["suggested_sku"] or "").strip().upper()
        english_name = row["final_english_name"] or row["suggested_english_name"] or ""
        result = classifier.classify(
            ProductInput(
                sku=sku,
                name=row["rel_path"],
                english_name=english_name,
                path=row["rel_path"],
                external_id=str(row["id"]),
            )
        )
        category_id = result.category_id
        tags = "|".join(result.tags)
        updates.append(
            (
                category_id,
                tags,
                result.confidence,
                result.source,
                result.reason + (f"；{'；'.join(result.conflicts)}" if result.conflicts else ""),
                int(result.needs_review or result.source not in {"sku_inheritance", "human_correction"}),
                "" if category_id == "UNKNOWN" else category_id,
                tags,
                row["id"],
            )
        )
    conn.executemany(
        """
        UPDATE nas_imports
        SET suggested_category_id=?, suggested_category_tags=?,
            category_confidence=?, category_source=?, category_reason=?,
            category_needs_review=?, final_category_id=?, final_category_tags=?,
            updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        updates,
    )
    return len(updates)
