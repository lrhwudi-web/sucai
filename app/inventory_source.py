from __future__ import annotations

import os
import json
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Iterable, Mapping, Protocol


def _read_env_file(path: str) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path:
        return values
    try:
        lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return values
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _positive_int(value: str | None, default: int, maximum: int) -> int:
    try:
        return max(1, min(int(value or default), maximum))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class InventoryConfig:
    host: str
    port: int
    user: str
    password: str
    database: str
    cache_seconds: int = 60
    connect_timeout: int = 4
    read_timeout: int = 8
    use_ssl: bool = False
    sales_warehouse_name: str = ""

    @property
    def enabled(self) -> bool:
        return all((self.host, self.user, self.password, self.database))

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> "InventoryConfig":
        source = dict(os.environ if environ is None else environ)
        file_values = _read_env_file(source.get("INVENTORY_DB_ENV_FILE", ""))

        def value(name: str, fallback_name: str = "") -> str:
            return str(source.get(name) or (file_values.get(fallback_name) if fallback_name else "") or "").strip()

        return cls(
            host=value("INVENTORY_DB_HOST", "DB_HOST"),
            port=_positive_int(value("INVENTORY_DB_PORT", "DB_PORT"), 3306, 65535),
            user=value("INVENTORY_DB_USER", "DB_USER"),
            password=value("INVENTORY_DB_PASSWORD", "DB_PASSWORD"),
            database=value("INVENTORY_DB_NAME", "DB_NAME"),
            cache_seconds=_positive_int(value("INVENTORY_DB_CACHE_SECONDS"), 60, 3600),
            connect_timeout=_positive_int(value("INVENTORY_DB_CONNECT_TIMEOUT"), 4, 30),
            read_timeout=_positive_int(value("INVENTORY_DB_READ_TIMEOUT"), 8, 60),
            use_ssl=value("INVENTORY_DB_SSL").lower() in {"1", "true", "yes"},
            sales_warehouse_name=value("INVENTORY_SALES_WAREHOUSE_NAME"),
        )


@dataclass(frozen=True)
class InventoryMetrics:
    available: int
    sales_warehouse: int
    sales_age_181_365: int
    sales_age_366_plus: int
    pending_qc: int
    pending_arrival: int


@dataclass(frozen=True)
class InventoryProductMetadata:
    chinese_name: str
    listing_date: str


@dataclass(frozen=True)
class InventoryLookup:
    values: dict[str, int]
    state: str
    updated_at: str = ""
    metrics: dict[str, InventoryMetrics] | None = None
    sales_warehouse_name: str = ""
    product_metadata: dict[str, InventoryProductMetadata] | None = None


class Cursor(Protocol):
    def execute(self, query: str, args: tuple[object, ...]) -> object: ...
    def fetchall(self) -> Iterable[tuple[object, ...]]: ...
    def __enter__(self) -> "Cursor": ...
    def __exit__(self, exc_type, exc, traceback) -> None: ...


class Connection(Protocol):
    def cursor(self) -> Cursor: ...
    def close(self) -> None: ...


Connector = Callable[..., Connection]


LATEST_AVAILABLE_INVENTORY_SQL = """
WITH latest_checkpoint AS (
  SELECT warehouse_id, sync_run_id, finished_at
  FROM (
    SELECT warehouse_id,
           sync_run_id,
           finished_at,
           ROW_NUMBER() OVER (
             PARTITION BY warehouse_id
             ORDER BY finished_at DESC, id DESC
           ) AS checkpoint_rank
    FROM stocking_inventory_warehouse_sync_checkpoints
    WHERE stage = 'local-inventory' AND status = 'success'
  ) ranked
  WHERE checkpoint_rank = 1
)
SELECT details.sku,
       SUM(COALESCE(details.product_valid_num, 0)) AS available_inventory,
       SUM(CASE
             WHEN details.warehouse_name = %s OR details.warehouse_name = CONCAT(%s, '仓库')
             THEN COALESCE(details.product_valid_num, 0)
             ELSE 0
           END) AS sales_warehouse_inventory,
       MAX(CASE
             WHEN details.warehouse_name = %s OR details.warehouse_name = CONCAT(%s, '仓库')
             THEN details.stock_age_list_json
             ELSE NULL
           END) AS sales_warehouse_stock_age,
       SUM(COALESCE(details.product_qc_num, 0)) AS pending_qc,
       SUM(COALESCE(details.quantity_receive, 0)) AS pending_arrival,
       MAX(latest_checkpoint.finished_at) AS updated_at
FROM stocking_lingxing_inventory_details details
JOIN latest_checkpoint
  ON latest_checkpoint.sync_run_id = details.sync_run_id
 AND latest_checkpoint.warehouse_id = details.wid
WHERE details.sku IN ({placeholders})
GROUP BY details.sku
""".strip()


PRODUCT_METADATA_SQL = """
SELECT sku,
       MAX(NULLIF(TRIM(product_name), '')) AS chinese_name,
       MIN(
         CASE
           WHEN YEAR(sku_created_at) = 1970
                AND UNIX_TIMESTAMP(sku_created_at) BETWEEN 1000000 AND 3000000
           THEN FROM_UNIXTIME(UNIX_TIMESTAMP(sku_created_at) * 1000)
           ELSE sku_created_at
         END
       ) AS listing_date
FROM products
WHERE sku IN ({placeholders})
GROUP BY sku
""".strip()


def _timestamp(value: object) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat(timespec="seconds") if isinstance(value, datetime) else value.isoformat()
    return str(value or "")


def _quantity(value: object) -> int:
    try:
        return max(0, int(round(float(value or 0))))
    except (TypeError, ValueError, OverflowError):
        return 0


def _sales_age_quantities(raw_value: object) -> tuple[int, int]:
    if not raw_value:
        return 0, 0
    try:
        buckets = json.loads(raw_value) if isinstance(raw_value, str) else raw_value
    except (TypeError, ValueError, json.JSONDecodeError):
        return 0, 0
    if not isinstance(buckets, list):
        return 0, 0
    age_181_365 = 0
    age_366_plus = 0
    for bucket in buckets:
        if not isinstance(bucket, dict):
            continue
        label = str(bucket.get("name") or bucket.get("label") or bucket.get("key") or "").lower().replace(" ", "")
        quantity = _quantity(bucket.get("qty"))
        if "181-365" in label or "180-365" in label:
            age_181_365 += quantity
        elif "366" in label or "365+" in label or "365天以上" in label:
            age_366_plus += quantity
    return age_181_365, age_366_plus


class InventoryReader:
    def __init__(
        self,
        config: InventoryConfig | None = None,
        connector: Connector | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config or InventoryConfig.from_environment()
        self.connector = connector
        self.clock = clock
        self._lock = threading.Lock()
        self._expires_at: dict[str, float] = {}
        self._values: dict[tuple[str, str], int | None] = {}
        self._metrics: dict[tuple[str, str], InventoryMetrics | None] = {}
        self._product_metadata: dict[tuple[str, str], InventoryProductMetadata | None] = {}
        self._updated_at: dict[str, str] = {}

    @staticmethod
    def normalize_skus(skus: Iterable[str]) -> list[str]:
        return list(dict.fromkeys(str(sku or "").strip().upper() for sku in skus if str(sku or "").strip()))[:500]

    def clear(self) -> None:
        with self._lock:
            self._expires_at.clear()
            self._values.clear()
            self._metrics.clear()
            self._product_metadata.clear()
            self._updated_at.clear()

    def lookup(self, skus: Iterable[str], sales_warehouse_name: str = "") -> InventoryLookup:
        normalized = self.normalize_skus(skus)
        warehouse_name = str(sales_warehouse_name or self.config.sales_warehouse_name or "").strip()[:100]
        if not normalized:
            return InventoryLookup({}, "live", sales_warehouse_name=warehouse_name)
        if not self.config.enabled:
            return InventoryLookup({}, "disabled", sales_warehouse_name=warehouse_name)
        with self._lock:
            now = self.clock()
            if now < self._expires_at.get(warehouse_name, 0) and all((warehouse_name, sku) in self._values for sku in normalized):
                return self._result(normalized, "live", warehouse_name)
            try:
                metrics, product_metadata, updated_at = self._query(normalized, warehouse_name)
            except Exception:
                cached = any((warehouse_name, sku) in self._values for sku in normalized)
                return self._result(normalized, "stale" if cached else "unavailable", warehouse_name)
            for sku in normalized:
                metric = metrics.get(sku)
                key = (warehouse_name, sku)
                self._metrics[key] = metric
                self._product_metadata[key] = product_metadata.get(sku)
                self._values[key] = metric.available if metric else None
            self._updated_at[warehouse_name] = updated_at or self._updated_at.get(warehouse_name, "")
            self._expires_at[warehouse_name] = now + self.config.cache_seconds
            return self._result(normalized, "live", warehouse_name)

    def _result(self, skus: list[str], state: str, warehouse_name: str) -> InventoryLookup:
        values = {sku: value for sku in skus if (value := self._values.get((warehouse_name, sku))) is not None}
        metrics = {sku: value for sku in skus if (value := self._metrics.get((warehouse_name, sku))) is not None}
        product_metadata = {sku: value for sku in skus if (value := self._product_metadata.get((warehouse_name, sku))) is not None}
        return InventoryLookup(values, state, self._updated_at.get(warehouse_name, ""), metrics, warehouse_name, product_metadata)

    def _connect(self) -> Connection:
        if self.connector:
            return self.connector()
        import pymysql

        options: dict[str, object] = {
            "host": self.config.host,
            "port": self.config.port,
            "user": self.config.user,
            "password": self.config.password,
            "database": self.config.database,
            "charset": "utf8mb4",
            "connect_timeout": self.config.connect_timeout,
            "read_timeout": self.config.read_timeout,
            "write_timeout": self.config.connect_timeout,
        }
        if self.config.use_ssl:
            options["ssl"] = {"check_hostname": True}
        return pymysql.connect(**options)

    def _query(self, skus: list[str], sales_warehouse_name: str) -> tuple[dict[str, InventoryMetrics], dict[str, InventoryProductMetadata], str]:
        placeholders = ",".join(["%s"] * len(skus))
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    LATEST_AVAILABLE_INVENTORY_SQL.format(placeholders=placeholders),
                    (
                        sales_warehouse_name,
                        sales_warehouse_name,
                        sales_warehouse_name,
                        sales_warehouse_name,
                        *skus,
                    ),
                )
                rows = cursor.fetchall()
                cursor.execute(PRODUCT_METADATA_SQL.format(placeholders=placeholders), tuple(skus))
                metadata_rows = cursor.fetchall()
        finally:
            connection.close()
        values: dict[str, InventoryMetrics] = {}
        updated_at = ""
        for raw_sku, raw_quantity, raw_sales_quantity, raw_age_buckets, raw_qc, raw_arrival, raw_updated_at in rows:
            sku = str(raw_sku or "").strip().upper()
            if not sku:
                continue
            age_181_365, age_366_plus = _sales_age_quantities(raw_age_buckets)
            values[sku] = InventoryMetrics(
                available=_quantity(raw_quantity),
                sales_warehouse=_quantity(raw_sales_quantity),
                sales_age_181_365=age_181_365,
                sales_age_366_plus=age_366_plus,
                pending_qc=_quantity(raw_qc),
                pending_arrival=_quantity(raw_arrival),
            )
            current_timestamp = _timestamp(raw_updated_at)
            if current_timestamp > updated_at:
                updated_at = current_timestamp
        product_metadata: dict[str, InventoryProductMetadata] = {}
        for raw_sku, raw_chinese_name, raw_listing_date in metadata_rows:
            sku = str(raw_sku or "").strip().upper()
            if not sku:
                continue
            product_metadata[sku] = InventoryProductMetadata(
                chinese_name=str(raw_chinese_name or "").strip(),
                listing_date=_timestamp(raw_listing_date)[:10],
            )
        return values, product_metadata, updated_at


reader = InventoryReader()


def lookup_available_inventory(skus: Iterable[str], sales_warehouse_name: str = "") -> InventoryLookup:
    return reader.lookup(skus, sales_warehouse_name)
