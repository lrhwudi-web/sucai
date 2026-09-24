from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
from typing import Callable

from . import db, product_taxonomy


DEFAULT_BASE_ID = "lyQod3RxJKEYYQAkh4dlg59dWkb4Mw9r"
DEFAULT_TABLE_ID = "8bpp2K8"
SOURCE_SHEET = "钉钉 AI 表格/产品目录_总表"
FIELD_IDS = {
    "sku": "duwvvd11bwa3p9oh7b1l1",
    "brand": "teugdeq8yx0yjlag5yzme",
    "product_type": "b2ufbqiihk45i2y1bw1yc",
    "chinese_name": "xtpw16r335fyktcj8u2qh",
    "english_name": "ns46u48n5opzgqeb0k5fj",
    "set_code": "Uq0iqGS",
    "partition": "WAESkxF",
}

PRODUCT_TYPE_CATEGORY = {
    "1号木杆套": "HC_DRIVER",
    "球道木杆套": "HC_FAIRWAY",
    "混合木杆套": "HC_HYBRID",
    "杆套套装": "ACC_OTHER",
    "直条推杆套": "HC_PUTTER_BLADE",
    "方形推杆套": "HC_PUTTER_SQUARE",
    "半圆推杆套": "HC_PUTTER_MALLET_LARGE",
    "DF3推杆套": "HC_PUTTER_MALLET_LARGE",
    "OZ.1推杆套": "HC_PUTTER_MALLET_LARGE",
    "DF2.1推杆套": "HC_PUTTER_MALLET_LARGE",
    "MEZZ.1推杆套": "HC_PUTTER_MALLET_LARGE",
    "OZ.1i HS推杆套": "HC_PUTTER_MALLET_LARGE",
    "铁杆套": "HC_IRON",
    "铁杆套_左手": "HC_IRON",
    "铁杆套_单个": "HC_IRON",
    "沙杆套": "HC_WEDGE",
    "沙杆套_左手": "HC_WEDGE",
    "沙杆套_单个": "HC_WEDGE",
    "方向棒套": "HC_ALIGNMENT",
    "马克&果岭叉": "ACC_DIVOT_MARKER",
    "积分本": "ACC_SCOREBOOK",
    "毛巾": "ACC_TOWEL",
    "什物袋": "ACC_VALUABLES_POUCH",
    "装球袋": "ACC_BALL_TEE_POUCH",
    "手套包": "ACC_GLOVE_CASE",
    "捡球器套": "ACC_OTHER",
    "保温桶&袋": "ACC_OTHER",
    "滑垒手套": "ACC_OTHER",
    "护肘": "ACC_OTHER",
    "测距仪包/绑带": "ACC_RANGEFINDER_CASE",
    "球车用品": "ACC_OTHER",
    "球包带": "ACC_OTHER",
    "其他配件": "ACC_OTHER",
    "匹克球拍套": "ACC_OTHER",
    "球包": "ACC_OTHER",
    "鞋袋": "ACC_OTHER",
    "服饰": "ACC_OTHER",
    "手套": "ACC_OTHER",
    "帽子": "ACC_OTHER",
    "章仔": "ACC_OTHER",
    "充电器": "ACC_OTHER",
}
PRODUCT_TYPE_TAGS = {
    "DF3推杆套": "MODEL_DF3",
    "OZ.1推杆套": "MODEL_OZ1",
    "DF2.1推杆套": "MODEL_DF21",
    "OZ.1i HS推杆套": "MODEL_OZ1I_HS",
}
VALID_BRANDS = {"Craftsman Golf", "My Tag", "Big Crazy", "Big Teeth", "凯赛", "无牌"}
ACTIVE_PARTITION = "A_产品目录"


class DingTalkCatalogError(RuntimeError):
    pass


def enabled() -> bool:
    return os.getenv("DINGTALK_AITABLE_SYNC_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def _cell_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        if "name" in value:
            return str(value.get("name") or "").strip()
        return _cell_text(value.get("value"))
    if isinstance(value, list):
        return "|".join(part for item in value if (part := _cell_text(item)))
    return str(value).strip()


def _normalize_sku(value) -> str:
    sku = _cell_text(value).upper()
    if re.fullmatch(r"\d+\.0+", sku):
        sku = sku.split(".", 1)[0]
    return sku


def _normalize_set_code(value) -> str:
    raw = _cell_text(value).split("|", 1)[0].strip()
    if not raw:
        return ""
    try:
        return db.normalize_set_code(raw)
    except ValueError:
        return ""


def _category(product_type: str, chinese_name: str, english_name: str) -> tuple[str, str]:
    category_id = PRODUCT_TYPE_CATEGORY.get(product_type, "")
    tags = PRODUCT_TYPE_TAGS.get(product_type, "")
    if "毛绒" in chinese_name or re.search(r"\b(?:plush|stuffed)\b", english_name, flags=re.IGNORECASE):
        category_id = "HC_PLUSH"
        tags = "PLUSH_ANIMAL"
    return category_id, tags


def _validation_error(product: dict) -> str:
    if not product["sku"]:
        return "SKU 为空"
    if product["partition"] != ACTIVE_PARTITION:
        return f"分表不是 {ACTIVE_PARTITION}"
    if product["brand"] not in VALID_BRANDS:
        return "品牌为空或不受支持"
    if product["product_type"] not in PRODUCT_TYPE_CATEGORY:
        return "产品类型为空或不受支持"
    english_name = product["english_name"]
    if not english_name or not english_name.isascii() or not re.search(r"[A-Za-z]", english_name):
        return "英文品名为空或不是英文 ASCII 文本"
    if any(ord(char) < 32 for char in english_name):
        return "英文品名含控制字符"
    if not product["category_id"]:
        return "无法映射产品目录"
    return ""


def parse_records(payload: dict) -> list[dict]:
    if payload.get("error") or payload.get("success") is False or payload.get("status") == "error":
        error = payload.get("error") or {}
        raise DingTalkCatalogError(str(error.get("message") or "钉钉产品表读取失败"))
    records = (payload.get("data") or {}).get("records") or []
    parsed: list[dict] = []
    for record in records:
        cells = record.get("cells") or {}
        product = {
            "record_id": str(record.get("recordId") or "").strip(),
            "sku": _normalize_sku(cells.get(FIELD_IDS["sku"])),
            "brand": _cell_text(cells.get(FIELD_IDS["brand"])),
            "product_type": _cell_text(cells.get(FIELD_IDS["product_type"])),
            "chinese_name": _cell_text(cells.get(FIELD_IDS["chinese_name"])),
            "english_name": _cell_text(cells.get(FIELD_IDS["english_name"])),
            "set_code": _normalize_set_code(cells.get(FIELD_IDS["set_code"])),
            "partition": _cell_text(cells.get(FIELD_IDS["partition"])),
        }
        product["category_id"], product["category_tags"] = _category(
            product["product_type"], product["chinese_name"], product["english_name"]
        )
        product["validation_error"] = _validation_error(product)
        product["ready"] = not product["validation_error"]
        parsed.append(product)

    active_by_sku: dict[str, list[dict]] = {}
    for product in parsed:
        if product["sku"] and product["partition"] == ACTIVE_PARTITION:
            active_by_sku.setdefault(product["sku"], []).append(product)
    for rows in active_by_sku.values():
        if len(rows) > 1:
            for product in rows:
                product["ready"] = False
                product["validation_error"] = "SKU 在 A_产品目录中存在重复记录"
    return parsed


def _dws_command(query: str = "", skus: list[str] | None = None) -> list[str]:
    executable = os.getenv("DINGTALK_AITABLE_DWS_BIN", "dws").strip() or "dws"
    args = [
        executable,
        "aitable",
        "record",
        "query",
        "--base-id",
        os.getenv("DINGTALK_AITABLE_BASE_ID", DEFAULT_BASE_ID).strip() or DEFAULT_BASE_ID,
        "--table-id",
        os.getenv("DINGTALK_AITABLE_TABLE_ID", DEFAULT_TABLE_ID).strip() or DEFAULT_TABLE_ID,
        "--field-ids",
        ",".join(FIELD_IDS.values()),
        "--limit",
        "100",
        "--all",
        "--page-limit",
        "0",
        "--timeout",
        "120",
        "--format",
        "json",
    ]
    if query:
        args.extend(("--query", query))
    if skus:
        filters = {
            "operator": "or",
            "operands": [
                {"operator": "eq", "operands": [FIELD_IDS["sku"], sku]}
                for sku in skus
            ],
        }
        args.extend(("--filters", json.dumps(filters, ensure_ascii=False, separators=(",", ":"))))
    return args


def fetch_records(
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    *,
    query: str = "",
    skus: list[str] | None = None,
) -> list[dict]:
    env = os.environ.copy()
    config_dir = os.getenv("DWS_CONFIG_DIR", "").strip()
    if config_dir:
        env["DWS_CONFIG_DIR"] = config_dir
    command = _dws_command(query, skus)
    for attempt in range(2):
        try:
            completed = runner(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=180,
                check=False,
                env=env,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DingTalkCatalogError(f"无法运行钉钉表格客户端：{exc}") from exc
        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()
        output = stdout or stderr
        if not output:
            raise DingTalkCatalogError(f"钉钉产品表没有返回数据：退出码 {completed.returncode}")
        try:
            payload = json.loads(output)
        except json.JSONDecodeError as exc:
            raise DingTalkCatalogError(f"钉钉产品表返回了无法解析的数据：{stderr[:500]}") from exc
        error = payload.get("error") or {}
        if error and error.get("retryable") is True and attempt == 0:
            continue
        return parse_records(payload)
    raise DingTalkCatalogError("钉钉产品表读取失败")


def record_sync_error(conn: sqlite3.Connection, message: str) -> None:
    with conn:
        conn.execute(
            """
            INSERT INTO dingtalk_catalog_sync_state(id, state, message)
            VALUES (1, 'error', ?)
            ON CONFLICT(id) DO UPDATE SET
              state='error', message=excluded.message, synced_at=CURRENT_TIMESTAMP
            """,
            (message[:1000],),
        )


def sync_catalog(
    conn: sqlite3.Connection,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict[str, int]:
    products = fetch_records(runner)
    if not products:
        raise DingTalkCatalogError("钉钉产品总表为空，已停止自动归档")
    ready = [product for product in products if product["ready"]]
    source_url = os.getenv("DINGTALK_AITABLE_URL", SOURCE_SHEET).strip() or SOURCE_SHEET
    with conn:
        conn.execute("DELETE FROM dingtalk_catalog_products")
        conn.executemany(
            """
            INSERT INTO dingtalk_catalog_products(
              record_id, sku, english_name, chinese_name, brand, product_type,
              partition_name, set_code, category_id, category_tags, ready,
              validation_error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    product["record_id"], product["sku"], product["english_name"],
                    product["chinese_name"], product["brand"], product["product_type"],
                    product["partition"], product["set_code"], product["category_id"],
                    product["category_tags"], int(product["ready"]),
                    product["validation_error"],
                )
                for product in products
                if product["record_id"]
            ],
        )
        conn.execute(
            """
            INSERT INTO dingtalk_catalog_sync_state(
              id, state, message, record_count, ready_count, synced_at
            ) VALUES (1, 'ok', '', ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
              state='ok', message='', record_count=excluded.record_count,
              ready_count=excluded.ready_count, synced_at=CURRENT_TIMESTAMP
            """,
            (len(products), len(ready)),
        )
        for product in ready:
            details = product_taxonomy.category_details(product["category_id"], conn)
            conn.execute(
                """
                INSERT INTO sku_meta(
                  sku, english_name, chinese_name, brand, category, category_id,
                  category_zh, category_tags, category_confidence, category_source,
                  category_status, category_reason, taxonomy_version, category_updated_at,
                  set_code, source_sheet
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 'dingtalk_aitable', 'verified',
                          '钉钉产品目录唯一完整匹配', ?, CURRENT_TIMESTAMP, ?, ?)
                ON CONFLICT(sku) DO UPDATE SET
                  english_name=excluded.english_name,
                  chinese_name=excluded.chinese_name,
                  brand=excluded.brand,
                  category=excluded.category,
                  category_id=excluded.category_id,
                  category_zh=excluded.category_zh,
                  category_tags=excluded.category_tags,
                  category_confidence=excluded.category_confidence,
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
                  taxonomy_version=excluded.taxonomy_version,
                  category_updated_at=CURRENT_TIMESTAMP,
                  set_code=excluded.set_code,
                  source_sheet=excluded.source_sheet
                """,
                (
                    product["sku"], product["english_name"], product["chinese_name"],
                    product["brand"], details["label_en"], product["category_id"],
                    details["label_zh"], product["category_tags"],
                    product_taxonomy.REGISTRY_VERSION, product["set_code"], source_url,
                ),
            )
    return {"records": len(products), "ready": len(ready)}


def sync_catalog_skus(
    conn: sqlite3.Connection,
    skus: list[str],
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict[str, int]:
    requested = list(dict.fromkeys(sku.strip().upper() for sku in skus if sku.strip()))
    products: list[dict] = []
    for start in range(0, len(requested), 25):
        batch = requested[start : start + 25]
        requested_batch = set(batch)
        products.extend(product for product in fetch_records(runner, skus=batch) if product["sku"] in requested_batch)
    ready = [product for product in products if product["ready"]]
    source_url = os.getenv("DINGTALK_AITABLE_URL", SOURCE_SHEET).strip() or SOURCE_SHEET
    with conn:
        if requested:
            placeholders = ",".join("?" for _ in requested)
            conn.execute(
                f"DELETE FROM dingtalk_catalog_products WHERE sku IN ({placeholders})",
                requested,
            )
        conn.executemany(
            """
            INSERT INTO dingtalk_catalog_products(
              record_id, sku, english_name, chinese_name, brand, product_type,
              partition_name, set_code, category_id, category_tags, ready,
              validation_error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    product["record_id"], product["sku"], product["english_name"],
                    product["chinese_name"], product["brand"], product["product_type"],
                    product["partition"], product["set_code"], product["category_id"],
                    product["category_tags"], int(product["ready"]), product["validation_error"],
                )
                for product in products
                if product["record_id"]
            ],
        )
        for product in ready:
            details = product_taxonomy.category_details(product["category_id"], conn)
            conn.execute(
                """
                INSERT INTO sku_meta(
                  sku, english_name, chinese_name, brand, category, category_id,
                  category_zh, category_tags, category_confidence, category_source,
                  category_status, category_reason, taxonomy_version, category_updated_at,
                  set_code, source_sheet
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 'dingtalk_aitable', 'verified',
                          '钉钉产品目录唯一完整匹配', ?, CURRENT_TIMESTAMP, ?, ?)
                ON CONFLICT(sku) DO UPDATE SET
                  english_name=excluded.english_name,
                  chinese_name=excluded.chinese_name,
                  brand=excluded.brand,
                  category=excluded.category,
                  category_id=excluded.category_id,
                  category_zh=excluded.category_zh,
                  category_tags=excluded.category_tags,
                  category_confidence=excluded.category_confidence,
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
                  taxonomy_version=excluded.taxonomy_version,
                  category_updated_at=CURRENT_TIMESTAMP,
                  set_code=excluded.set_code,
                  source_sheet=excluded.source_sheet
                """,
                (
                    product["sku"], product["english_name"], product["chinese_name"],
                    product["brand"], details["label_en"], product["category_id"],
                    details["label_zh"], product["category_tags"],
                    product_taxonomy.REGISTRY_VERSION, product["set_code"], source_url,
                ),
            )
        conn.execute(
            """
            INSERT INTO dingtalk_catalog_sync_state(
              id, state, message, record_count, ready_count, synced_at
            ) VALUES (1, 'ok', '', ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
              state='ok', message='', record_count=excluded.record_count,
              ready_count=excluded.ready_count, synced_at=CURRENT_TIMESTAMP
            """,
            (len(products), len(ready)),
        )
    return {"records": len(products), "ready": len(ready)}


def product_for_sku(conn: sqlite3.Connection, sku: str) -> sqlite3.Row | None:
    rows = conn.execute(
        """
        SELECT * FROM dingtalk_catalog_products
        WHERE sku=? AND partition_name=?
        ORDER BY record_id
        """,
        (sku.strip().upper(), ACTIVE_PARTITION),
    ).fetchall()
    if len(rows) != 1 or not rows[0]["ready"]:
        return None
    return rows[0]
