from __future__ import annotations

import csv
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from . import dingtalk_auth, product_taxonomy
from .logic import CUSTOMER_ACCOUNT_ROLES, IGNORED_FILE_NAMES, PERMISSION_ROLES, ROLES, RULE_SCOPES, can_user_see, classify_asset, infer_drive_fields, is_internal_path, normalize_permission_rule, normalize_role, normalize_rule_value

DB_PATH = Path(os.getenv("DATABASE_URL", "data/materials.db").replace("sqlite:///", ""))
ENGLISH_NAME_CATALOG = Path(__file__).with_name("english_name_catalog.csv")
ENGLISH_NAME_CATALOG_VERSION = "english-name-catalog-2026-07-13"
PRODUCT_CATALOG = Path(__file__).with_name("product_catalog.csv")
PRODUCT_CATALOG_VERSION = "product-catalog-no-product-tags-2026-07-27-v1"
FILE_METADATA_VERSION = "file-path-metadata-2026-07-17-set-collection-depth-v2"
ROLE_SQL = "','".join(ROLES)
PERMISSION_ROLE_SQL = "','".join(PERMISSION_ROLES)
RULE_SCOPE_SQL = "','".join(RULE_SCOPES)
USER_ACTIVITY_TYPES = ("login", "original_open", "download", "drive_export")
USER_ACTIVITY_TYPE_SQL = "','".join(USER_ACTIVITY_TYPES)
USER_PERMISSION_MODES = ("role_default", "allowlist")
USER_PERMISSION_MODE_SQL = "','".join(USER_PERMISSION_MODES)
CUSTOMER_ACCOUNT_TTL_DAYS = max(1, int(os.getenv("CUSTOMER_ACCOUNT_TTL_DAYS", "15")))
def normalize_set_code(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    match = re.fullmatch(r"set\s*0*(\d{1,8})", value, re.IGNORECASE)
    if not match:
        raise ValueError("套装编号必须使用 Set00264 这样的格式")
    return f"Set{int(match.group(1)):05d}"

def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_users_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY,
          email TEXT UNIQUE NOT NULL,
          name TEXT NOT NULL,
          role TEXT NOT NULL CHECK(role IN ('{ROLE_SQL}')),
          password_hash TEXT NOT NULL,
          disabled INTEGER NOT NULL DEFAULT 0 CHECK(disabled IN (0, 1)),
          expires_at TEXT,
          created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def ensure_users_schema(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
    if not row:
        create_users_table(conn)
        return
    sql = row["sql"] or ""
    if all(role in sql for role in ROLES):
        conn.execute("UPDATE users SET role='internal_staff' WHERE role='internal'")
        conn.execute("UPDATE users SET role='overseas_customer' WHERE role='external'")
        columns = {item["name"] for item in conn.execute("PRAGMA table_info(users)").fetchall()}
        if "disabled" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN disabled INTEGER NOT NULL DEFAULT 0")
        if "expires_at" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN expires_at TEXT")
        if "created_by_user_id" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL")
        placeholders = ",".join("?" for _ in CUSTOMER_ACCOUNT_ROLES)
        conn.execute(
            f"""
            UPDATE users
            SET expires_at=datetime('now', ?)
            WHERE role IN ({placeholders}) AND expires_at IS NULL
            """,
            (f"+{CUSTOMER_ACCOUNT_TTL_DAYS} days", *CUSTOMER_ACCOUNT_ROLES),
        )
        return
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("PRAGMA legacy_alter_table = ON")
    try:
        conn.execute("ALTER TABLE users RENAME TO users_old")
        create_users_table(conn)
        conn.execute(
            """
            INSERT INTO users(id, email, name, role, password_hash, created_at)
            SELECT id, email, name,
              CASE role
                WHEN 'internal' THEN 'internal_staff'
                WHEN 'external' THEN 'overseas_customer'
                ELSE role
              END,
              password_hash, created_at
            FROM users_old
            """
        )
        conn.execute("DROP TABLE users_old")
        placeholders = ",".join("?" for _ in CUSTOMER_ACCOUNT_ROLES)
        conn.execute(
            f"UPDATE users SET expires_at=datetime('now', ?) WHERE role IN ({placeholders})",
            (f"+{CUSTOMER_ACCOUNT_TTL_DAYS} days", *CUSTOMER_ACCOUNT_ROLES),
        )
        conn.commit()
    finally:
        conn.execute("PRAGMA legacy_alter_table = OFF")
        conn.execute("PRAGMA foreign_keys = ON")


def refresh_file_metadata(conn: sqlite3.Connection) -> int:
    rows = conn.execute("SELECT id, path, mime_type FROM files").fetchall()
    updates = []
    for row in rows:
        brand, category, other, sku = infer_drive_fields(row["path"])
        updates.append(
            (
                sku,
                brand,
                category,
                other,
                classify_asset(row["path"], row["mime_type"]),
                int(is_internal_path(row["path"])),
                row["id"],
            )
        )
    conn.executemany(
        "UPDATE files SET sku=?, brand=?, category=?, other=?, asset_type=?, internal_only=? WHERE id=?",
        updates,
    )
    return len(updates)


def init_db(conn: sqlite3.Connection) -> None:
    ensure_users_schema(conn)
    conn.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS files (
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          mime_type TEXT NOT NULL,
          size INTEGER NOT NULL DEFAULT 0,
          modified_time TEXT,
          thumbnail_link TEXT NOT NULL DEFAULT '',
          path TEXT NOT NULL,
          sku TEXT NOT NULL,
          brand TEXT NOT NULL,
          category TEXT NOT NULL,
          other TEXT NOT NULL DEFAULT '',
          asset_type TEXT NOT NULL,
          internal_only INTEGER NOT NULL DEFAULT 0,
          synced_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_files_search ON files(sku, brand, category, asset_type);
        CREATE TABLE IF NOT EXISTS user_identities (
          id INTEGER PRIMARY KEY,
          user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          provider TEXT NOT NULL,
          provider_subject TEXT NOT NULL,
          provider_open_id TEXT NOT NULL DEFAULT '',
          provider_user_id TEXT NOT NULL DEFAULT '',
          provider_email TEXT NOT NULL DEFAULT '',
          display_name TEXT NOT NULL DEFAULT '',
          department_names TEXT NOT NULL DEFAULT '[]',
          departments_verified INTEGER NOT NULL DEFAULT 0,
          department_role_granted INTEGER NOT NULL DEFAULT 0,
          role_before_department_grant TEXT NOT NULL DEFAULT '',
          department_synced_at TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          last_login_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(provider, provider_subject)
        );
        CREATE INDEX IF NOT EXISTS idx_user_identities_user ON user_identities(user_id);
        CREATE TABLE IF NOT EXISTS sales_catalog_orders (
          owner_user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
          sku_order_json TEXT NOT NULL DEFAULT '[]',
          draft_json TEXT NOT NULL DEFAULT '{{}}',
          revision INTEGER NOT NULL DEFAULT 0,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS customer_orders (
          id INTEGER PRIMARY KEY,
          order_number TEXT UNIQUE NOT NULL,
          idempotency_key TEXT NOT NULL,
          customer_user_id INTEGER NOT NULL REFERENCES users(id),
          salesperson_user_id INTEGER NOT NULL REFERENCES users(id),
          customer_name TEXT NOT NULL,
          customer_email TEXT NOT NULL,
          title TEXT NOT NULL DEFAULT '',
          company TEXT NOT NULL DEFAULT '',
          contact TEXT NOT NULL DEFAULT '',
          reference TEXT NOT NULL DEFAULT '',
          currency TEXT NOT NULL DEFAULT 'USD',
          product_count INTEGER NOT NULL DEFAULT 0,
          total_quantity INTEGER NOT NULL DEFAULT 0,
          total_amount_cents INTEGER NOT NULL DEFAULT 0,
          unpriced_count INTEGER NOT NULL DEFAULT 0,
          items_json TEXT NOT NULL DEFAULT '[]',
          file_name TEXT NOT NULL,
          stored_file_name TEXT NOT NULL UNIQUE,
          file_size INTEGER NOT NULL DEFAULT 0,
          download_token_hash TEXT NOT NULL,
          notification_task_id TEXT NOT NULL DEFAULT '',
          notification_status TEXT NOT NULL DEFAULT 'pending',
          notification_error TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'new' CHECK(status IN ('new', 'confirmed')),
          confirmed_at TEXT,
          confirmed_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(customer_user_id, idempotency_key)
        );
        CREATE INDEX IF NOT EXISTS idx_customer_orders_customer
          ON customer_orders(customer_user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_customer_orders_salesperson
          ON customer_orders(salesperson_user_id, created_at DESC);
        CREATE TABLE IF NOT EXISTS dingtalk_admin_grants (
          provider_user_id TEXT PRIMARY KEY,
          display_name TEXT NOT NULL DEFAULT '',
          department_names TEXT NOT NULL DEFAULT '[]',
          user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
          granted_by_user_id INTEGER NOT NULL REFERENCES users(id),
          role_before_grant TEXT NOT NULL DEFAULT 'internal_staff',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_dingtalk_admin_grants_user
          ON dingtalk_admin_grants(user_id);
        CREATE TABLE IF NOT EXISTS dingtalk_organization_cache (
          id INTEGER PRIMARY KEY CHECK(id = 1),
          directory_json TEXT NOT NULL,
          synced_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS missing_sku_notifications (
          id INTEGER PRIMARY KEY,
          user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          fingerprint TEXT NOT NULL,
          searched_count INTEGER NOT NULL DEFAULT 0,
          missing_skus_json TEXT NOT NULL,
          recipient_name TEXT NOT NULL,
          task_ids_json TEXT NOT NULL DEFAULT '[]',
          status TEXT NOT NULL DEFAULT 'sent',
          error TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_missing_sku_notifications_recent
          ON missing_sku_notifications(user_id, fingerprint, created_at DESC);
        CREATE TABLE IF NOT EXISTS sku_meta (
          sku TEXT PRIMARY KEY,
          english_name TEXT NOT NULL DEFAULT '',
          owner TEXT NOT NULL DEFAULT '',
          notes TEXT NOT NULL DEFAULT '',
          chinese_name TEXT NOT NULL DEFAULT '',
          brand TEXT NOT NULL DEFAULT '',
          category TEXT NOT NULL DEFAULT '',
          category_id TEXT NOT NULL DEFAULT '',
          category_zh TEXT NOT NULL DEFAULT '',
          category_tags TEXT NOT NULL DEFAULT '',
          category_confidence REAL NOT NULL DEFAULT 0,
          category_source TEXT NOT NULL DEFAULT '',
          category_status TEXT NOT NULL DEFAULT 'unclassified',
          category_reason TEXT NOT NULL DEFAULT '',
          taxonomy_version TEXT NOT NULL DEFAULT '',
          category_updated_at TEXT,
          set_code TEXT NOT NULL DEFAULT '',
          themes TEXT NOT NULL DEFAULT '',
          cover_file_id TEXT NOT NULL DEFAULT '',
          source_sheet TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS dingtalk_catalog_products (
          record_id TEXT PRIMARY KEY,
          sku TEXT NOT NULL DEFAULT '',
          english_name TEXT NOT NULL DEFAULT '',
          chinese_name TEXT NOT NULL DEFAULT '',
          brand TEXT NOT NULL DEFAULT '',
          product_type TEXT NOT NULL DEFAULT '',
          partition_name TEXT NOT NULL DEFAULT '',
          set_code TEXT NOT NULL DEFAULT '',
          category_id TEXT NOT NULL DEFAULT '',
          category_tags TEXT NOT NULL DEFAULT '',
          ready INTEGER NOT NULL DEFAULT 0 CHECK(ready IN (0, 1)),
          validation_error TEXT NOT NULL DEFAULT '',
          synced_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_dingtalk_catalog_products_sku
          ON dingtalk_catalog_products(sku, partition_name, ready);
        CREATE TABLE IF NOT EXISTS dingtalk_catalog_sync_state (
          id INTEGER PRIMARY KEY CHECK(id = 1),
          state TEXT NOT NULL DEFAULT 'never_run',
          message TEXT NOT NULL DEFAULT '',
          record_count INTEGER NOT NULL DEFAULT 0,
          ready_count INTEGER NOT NULL DEFAULT 0,
          synced_at TEXT
        );
        INSERT OR IGNORE INTO dingtalk_catalog_sync_state(id) VALUES (1);
        CREATE TABLE IF NOT EXISTS sync_status (
          id INTEGER PRIMARY KEY CHECK(id = 1),
          root_id TEXT NOT NULL DEFAULT '',
          state TEXT NOT NULL,
          message TEXT NOT NULL DEFAULT '',
          started_at TEXT,
          finished_at TEXT,
          file_count INTEGER NOT NULL DEFAULT 0
        );
        INSERT OR IGNORE INTO sync_status(id, state) VALUES (1, 'never_run');
        CREATE TABLE IF NOT EXISTS role_permission_rules (
          id INTEGER PRIMARY KEY,
          role TEXT NOT NULL CHECK(role IN ('{PERMISSION_ROLE_SQL}')),
          scope TEXT NOT NULL CHECK(scope IN ('{RULE_SCOPE_SQL}')),
          value TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_role_permission_rules_unique
          ON role_permission_rules(role, scope, value);
        CREATE TABLE IF NOT EXISTS user_permission_grants (
          id INTEGER PRIMARY KEY,
          user_id INTEGER NOT NULL,
          scope TEXT NOT NULL CHECK(scope IN ('{RULE_SCOPE_SQL}')),
          value TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_user_permission_grants_unique
          ON user_permission_grants(user_id, scope, value);
        CREATE TABLE IF NOT EXISTS user_permission_profiles (
          user_id INTEGER PRIMARY KEY,
          mode TEXT NOT NULL DEFAULT 'role_default'
            CHECK(mode IN ('{USER_PERMISSION_MODE_SQL}')),
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS nas_imports (
          id INTEGER PRIMARY KEY,
          local_path TEXT NOT NULL,
          rel_path TEXT NOT NULL,
          name TEXT NOT NULL,
          size INTEGER NOT NULL,
          mtime_ns INTEGER NOT NULL,
          sha256 TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','suggested','approved','uploaded','rejected','error')),
          suggested_sku TEXT NOT NULL DEFAULT '',
          suggested_english_name TEXT NOT NULL DEFAULT '',
          suggested_drive_folder TEXT NOT NULL DEFAULT '',
          suggested_drive_name TEXT NOT NULL DEFAULT '',
          suggested_asset_type TEXT NOT NULL DEFAULT '',
          confidence REAL NOT NULL DEFAULT 0,
          reason TEXT NOT NULL DEFAULT '',
          final_sku TEXT NOT NULL DEFAULT '',
          final_english_name TEXT NOT NULL DEFAULT '',
          final_drive_folder TEXT NOT NULL DEFAULT '',
          final_drive_name TEXT NOT NULL DEFAULT '',
          final_asset_type TEXT NOT NULL DEFAULT '',
          final_set_code TEXT NOT NULL DEFAULT '',
          final_themes TEXT NOT NULL DEFAULT '',
          themes_updated INTEGER NOT NULL DEFAULT 0,
          suggested_category_id TEXT NOT NULL DEFAULT '',
          suggested_category_tags TEXT NOT NULL DEFAULT '',
          category_confidence REAL NOT NULL DEFAULT 0,
          category_source TEXT NOT NULL DEFAULT '',
          category_reason TEXT NOT NULL DEFAULT '',
          category_needs_review INTEGER NOT NULL DEFAULT 1,
          final_category_id TEXT NOT NULL DEFAULT '',
          final_category_tags TEXT NOT NULL DEFAULT '',
          drive_file_id TEXT NOT NULL DEFAULT '',
          error TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          approved_at TEXT,
          approved_by INTEGER,
          revision INTEGER NOT NULL DEFAULT 0
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_nas_imports_fingerprint
          ON nas_imports(sha256, size, mtime_ns);
        CREATE INDEX IF NOT EXISTS idx_nas_imports_status
          ON nas_imports(status, created_at);
        CREATE TABLE IF NOT EXISTS nas_import_jobs (
          id TEXT PRIMARY KEY,
          batch_id TEXT NOT NULL DEFAULT '',
          batch_name TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'queued'
            CHECK(status IN ('queued','running','completed','partial','failed')),
          created_by INTEGER,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          started_at TEXT,
          finished_at TEXT,
          dismissed_at TEXT,
          FOREIGN KEY(created_by) REFERENCES users(id)
        );
        CREATE INDEX IF NOT EXISTS idx_nas_import_jobs_status_updated
          ON nas_import_jobs(status, updated_at DESC);
        CREATE TABLE IF NOT EXISTS nas_import_job_items (
          job_id TEXT NOT NULL,
          import_id INTEGER NOT NULL,
          name TEXT NOT NULL DEFAULT '',
          rel_path TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'queued'
            CHECK(status IN ('queued','uploading','completed','error')),
          progress INTEGER NOT NULL DEFAULT 0 CHECK(progress BETWEEN 0 AND 100),
          stage TEXT NOT NULL DEFAULT 'queued',
          error TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY(job_id, import_id),
          FOREIGN KEY(job_id) REFERENCES nas_import_jobs(id) ON DELETE CASCADE,
          FOREIGN KEY(import_id) REFERENCES nas_imports(id)
        );
        CREATE INDEX IF NOT EXISTS idx_nas_import_job_items_import
          ON nas_import_job_items(import_id, updated_at DESC);
        CREATE TABLE IF NOT EXISTS nas_import_edit_logs (
          id INTEGER PRIMARY KEY,
          import_id INTEGER NOT NULL,
          field TEXT NOT NULL CHECK(field IN ('final_sku','final_drive_folder','final_english_name','final_drive_name')),
          suggested_value TEXT NOT NULL DEFAULT '',
          previous_value TEXT NOT NULL DEFAULT '',
          new_value TEXT NOT NULL,
          edited_by INTEGER,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_nas_import_edit_logs_created
          ON nas_import_edit_logs(created_at, import_id);
        CREATE TABLE IF NOT EXISTS nas_scan_state (
          source TEXT PRIMARY KEY,
          initialized_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          last_scan_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          file_count INTEGER NOT NULL DEFAULT 0,
          new_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS nas_scan_seen (
          source TEXT NOT NULL,
          path TEXT NOT NULL,
          size INTEGER NOT NULL,
          mtime_ns INTEGER NOT NULL,
          PRIMARY KEY(source, path)
        );
        CREATE TABLE IF NOT EXISTS app_migrations (
          name TEXT PRIMARY KEY,
          applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS custom_product_categories (
          id TEXT PRIMARY KEY,
          group_name TEXT NOT NULL CHECK(group_name IN ('Golf Headcover','Golf Accessories')),
          label_en TEXT NOT NULL,
          label_zh TEXT NOT NULL DEFAULT '',
          sort_order INTEGER NOT NULL DEFAULT 0,
          active INTEGER NOT NULL DEFAULT 1,
          created_by INTEGER,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(created_by) REFERENCES users(id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_custom_product_categories_label
          ON custom_product_categories(lower(label_en));
        CREATE TABLE IF NOT EXISTS custom_product_themes (
          id TEXT PRIMARY KEY,
          label TEXT NOT NULL,
          sort_order INTEGER NOT NULL DEFAULT 0,
          active INTEGER NOT NULL DEFAULT 1,
          created_by INTEGER,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(created_by) REFERENCES users(id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_custom_product_themes_label
          ON custom_product_themes(lower(label));
        CREATE TABLE IF NOT EXISTS category_correction_events (
          id INTEGER PRIMARY KEY,
          sku TEXT NOT NULL,
          import_id INTEGER,
          event_type TEXT NOT NULL CHECK(event_type IN ('approved','corrected')),
          previous_category_id TEXT NOT NULL DEFAULT '',
          final_category_id TEXT NOT NULL,
          previous_tags TEXT NOT NULL DEFAULT '',
          final_tags TEXT NOT NULL DEFAULT '',
          source TEXT NOT NULL,
          reviewer_id INTEGER,
          note TEXT NOT NULL DEFAULT '',
          taxonomy_version TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(reviewer_id) REFERENCES users(id)
        );
        CREATE INDEX IF NOT EXISTS idx_category_correction_events_sku
          ON category_correction_events(sku, created_at DESC);
        CREATE TRIGGER IF NOT EXISTS category_correction_events_no_update
        BEFORE UPDATE ON category_correction_events
        BEGIN
          SELECT RAISE(ABORT, 'category_correction_events is append-only');
        END;
        CREATE TRIGGER IF NOT EXISTS category_correction_events_no_delete
        BEFORE DELETE ON category_correction_events
        BEGIN
          SELECT RAISE(ABORT, 'category_correction_events is append-only');
        END;
        CREATE TABLE IF NOT EXISTS drive_exports (
          id INTEGER PRIMARY KEY,
          job_key TEXT NOT NULL,
          user_id TEXT NOT NULL,
          sku TEXT NOT NULL,
          folder_id TEXT NOT NULL UNIQUE,
          folder_url TEXT NOT NULL,
          parent_id TEXT NOT NULL,
          created_at TEXT NOT NULL,
          expires_at TEXT NOT NULL,
          deleted_at TEXT,
          delete_error TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_drive_exports_active
          ON drive_exports(job_key, expires_at, deleted_at);
        CREATE INDEX IF NOT EXISTS idx_drive_exports_expiry
          ON drive_exports(expires_at, deleted_at);
        CREATE TABLE IF NOT EXISTS product_messages (
          id INTEGER PRIMARY KEY,
          user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          sku TEXT NOT NULL,
          body TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_product_messages_user_sku
          ON product_messages(user_id, sku, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_product_messages_admin
          ON product_messages(created_at DESC, id DESC);
        CREATE TABLE IF NOT EXISTS product_favorites (
          user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          sku TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY(user_id, sku)
        );
        CREATE INDEX IF NOT EXISTS idx_product_favorites_user
          ON product_favorites(user_id, created_at DESC);
        CREATE TABLE IF NOT EXISTS user_activity_events (
          id INTEGER PRIMARY KEY,
          user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          event_type TEXT NOT NULL CHECK(event_type IN ('{USER_ACTIVITY_TYPE_SQL}')),
          sku TEXT NOT NULL DEFAULT '',
          file_id TEXT NOT NULL DEFAULT '',
          file_name TEXT NOT NULL DEFAULT '',
          detail TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_user_activity_user_created
          ON user_activity_events(user_id, created_at DESC, id DESC);
        CREATE INDEX IF NOT EXISTS idx_user_activity_type_created
          ON user_activity_events(event_type, created_at DESC, id DESC);
        CREATE TABLE IF NOT EXISTS catalog_events (
          id INTEGER PRIMARY KEY,
          user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          event_type TEXT NOT NULL CHECK(event_type IN ('catalog_view','search','product_open','product_added','product_removed','checkout_open')),
          sku TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_catalog_events_type_created
          ON catalog_events(event_type, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_catalog_events_user_created
          ON catalog_events(user_id, created_at DESC);
        CREATE TABLE IF NOT EXISTS customer_account_renewals (
          id INTEGER PRIMARY KEY,
          customer_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          renewed_by_user_id INTEGER NOT NULL REFERENCES users(id),
          previous_expires_at TEXT NOT NULL,
          new_expires_at TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    edit_logs_table = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='nas_import_edit_logs'"
    ).fetchone()
    if edit_logs_table and "'final_sku'" not in (edit_logs_table["sql"] or ""):
        conn.executescript(
            """
            BEGIN;
            DROP INDEX IF EXISTS idx_nas_import_edit_logs_created;
            ALTER TABLE nas_import_edit_logs RENAME TO nas_import_edit_logs_legacy;
            CREATE TABLE nas_import_edit_logs (
              id INTEGER PRIMARY KEY,
              import_id INTEGER NOT NULL,
              field TEXT NOT NULL CHECK(field IN ('final_sku','final_drive_folder','final_english_name','final_drive_name')),
              suggested_value TEXT NOT NULL DEFAULT '',
              previous_value TEXT NOT NULL DEFAULT '',
              new_value TEXT NOT NULL,
              edited_by INTEGER,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO nas_import_edit_logs(
              id, import_id, field, suggested_value, previous_value, new_value, edited_by, created_at
            )
            SELECT id, import_id, field, suggested_value, previous_value, new_value, edited_by, created_at
            FROM nas_import_edit_logs_legacy;
            DROP TABLE nas_import_edit_logs_legacy;
            CREATE INDEX idx_nas_import_edit_logs_created
              ON nas_import_edit_logs(created_at, import_id);
            COMMIT;
            """
        )
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(sync_status)").fetchall()}
    if "root_id" not in columns:
        conn.execute("ALTER TABLE sync_status ADD COLUMN root_id TEXT NOT NULL DEFAULT ''")
    file_columns = {row["name"] for row in conn.execute("PRAGMA table_info(files)").fetchall()}
    if "thumbnail_link" not in file_columns:
        conn.execute("ALTER TABLE files ADD COLUMN thumbnail_link TEXT NOT NULL DEFAULT ''")
    if "other" not in file_columns:
        conn.execute("ALTER TABLE files ADD COLUMN other TEXT NOT NULL DEFAULT ''")
    conn.execute(
        """
        UPDATE files
        SET other='Event & Sponsorships'
        WHERE other IN ('Event Sponsorships', 'Events & Sponsorships')
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_files_other ON files(other)")
    identity_columns = {row["name"] for row in conn.execute("PRAGMA table_info(user_identities)").fetchall()}
    identity_column_definitions = {
        "provider_user_id": "TEXT NOT NULL DEFAULT ''",
        "department_names": "TEXT NOT NULL DEFAULT '[]'",
        "departments_verified": "INTEGER NOT NULL DEFAULT 0",
        "department_role_granted": "INTEGER NOT NULL DEFAULT 0",
        "role_before_department_grant": "TEXT NOT NULL DEFAULT ''",
        "department_synced_at": "TEXT",
    }
    for column, definition in identity_column_definitions.items():
        if column not in identity_columns:
            conn.execute(f"ALTER TABLE user_identities ADD COLUMN {column} {definition}")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_identities_provider_user "
        "ON user_identities(provider, provider_user_id)"
    )
    sku_meta_columns = {row["name"] for row in conn.execute("PRAGMA table_info(sku_meta)").fetchall()}
    if "product_tag" in sku_meta_columns:
        conn.execute("DROP INDEX IF EXISTS idx_sku_meta_product_tag")
        conn.execute("ALTER TABLE sku_meta DROP COLUMN product_tag")
        sku_meta_columns.remove("product_tag")
    sku_meta_text_columns = (
        "chinese_name", "brand", "category", "category_id", "category_zh", "category_tags",
        "category_source", "category_reason", "taxonomy_version", "set_code",
        "themes", "cover_file_id", "source_sheet",
    )
    for column in sku_meta_text_columns:
        if column not in sku_meta_columns:
            conn.execute(f"ALTER TABLE sku_meta ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
    if "category_confidence" not in sku_meta_columns:
        conn.execute("ALTER TABLE sku_meta ADD COLUMN category_confidence REAL NOT NULL DEFAULT 0")
    if "category_status" not in sku_meta_columns:
        conn.execute("ALTER TABLE sku_meta ADD COLUMN category_status TEXT NOT NULL DEFAULT 'unclassified'")
    if "category_updated_at" not in sku_meta_columns:
        conn.execute("ALTER TABLE sku_meta ADD COLUMN category_updated_at TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sku_meta_set_code ON sku_meta(set_code)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sku_meta_themes ON sku_meta(themes)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sku_meta_category_id ON sku_meta(category_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sku_meta_category_status ON sku_meta(category_status)")
    import_columns = {row["name"] for row in conn.execute("PRAGMA table_info(nas_imports)").fetchall()}
    if "final_product_tag" in import_columns:
        conn.execute("ALTER TABLE nas_imports DROP COLUMN final_product_tag")
        import_columns.remove("final_product_tag")
    if "final_set_code" not in import_columns:
        conn.execute("ALTER TABLE nas_imports ADD COLUMN final_set_code TEXT NOT NULL DEFAULT ''")
    import_text_columns = (
        "suggested_category_id", "suggested_category_tags", "category_source",
        "category_reason", "final_category_id", "final_category_tags", "final_themes",
    )
    for column in import_text_columns:
        if column not in import_columns:
            conn.execute(f"ALTER TABLE nas_imports ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
    if "category_confidence" not in import_columns:
        conn.execute("ALTER TABLE nas_imports ADD COLUMN category_confidence REAL NOT NULL DEFAULT 0")
    if "category_needs_review" not in import_columns:
        conn.execute("ALTER TABLE nas_imports ADD COLUMN category_needs_review INTEGER NOT NULL DEFAULT 1")
    if "themes_updated" not in import_columns:
        conn.execute("ALTER TABLE nas_imports ADD COLUMN themes_updated INTEGER NOT NULL DEFAULT 0")
    if "revision" not in import_columns:
        conn.execute("ALTER TABLE nas_imports ADD COLUMN revision INTEGER NOT NULL DEFAULT 0")
    import_job_columns = {row["name"] for row in conn.execute("PRAGMA table_info(nas_import_jobs)").fetchall()}
    if "dismissed_at" not in import_job_columns:
        conn.execute("ALTER TABLE nas_import_jobs ADD COLUMN dismissed_at TEXT")
    rules_table = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='role_permission_rules'"
    ).fetchone()
    if rules_table and "'other'" not in rules_table["sql"]:
        conn.executescript(
            f"""
            ALTER TABLE role_permission_rules RENAME TO role_permission_rules_old;
            CREATE TABLE role_permission_rules (
              id INTEGER PRIMARY KEY,
              role TEXT NOT NULL CHECK(role IN ('{PERMISSION_ROLE_SQL}')),
              scope TEXT NOT NULL CHECK(scope IN ('{RULE_SCOPE_SQL}')),
              value TEXT NOT NULL,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO role_permission_rules(id, role, scope, value, created_at)
              SELECT id, role, scope, value, created_at FROM role_permission_rules_old;
            DROP TABLE role_permission_rules_old;
            CREATE UNIQUE INDEX idx_role_permission_rules_unique
              ON role_permission_rules(role, scope, value);
            """
        )
    conn.execute("DELETE FROM role_permission_rules WHERE scope='path_contains'")
    ignored_names = sorted(IGNORED_FILE_NAMES)
    placeholders = ",".join("?" for _ in ignored_names)
    conn.execute(f"DELETE FROM files WHERE lower(name) IN ({placeholders}) OR name LIKE '._%'", ignored_names)
    metadata_migrated = conn.execute(
        "SELECT 1 FROM app_migrations WHERE name=?", (FILE_METADATA_VERSION,)
    ).fetchone()
    if not metadata_migrated:
        refresh_file_metadata(conn)
        conn.execute("INSERT INTO app_migrations(name) VALUES (?)", (FILE_METADATA_VERSION,))
    sales_catalog_columns = {row["name"] for row in conn.execute("PRAGMA table_info(sales_catalog_orders)").fetchall()}
    if "draft_json" not in sales_catalog_columns:
        conn.execute("ALTER TABLE sales_catalog_orders ADD COLUMN draft_json TEXT NOT NULL DEFAULT '{}'")
    customer_order_columns = {row["name"] for row in conn.execute("PRAGMA table_info(customer_orders)").fetchall()}
    if "status" not in customer_order_columns:
        conn.execute("ALTER TABLE customer_orders ADD COLUMN status TEXT NOT NULL DEFAULT 'new'")
    if "confirmed_at" not in customer_order_columns:
        conn.execute("ALTER TABLE customer_orders ADD COLUMN confirmed_at TEXT")
    if "confirmed_by_user_id" not in customer_order_columns:
        conn.execute("ALTER TABLE customer_orders ADD COLUMN confirmed_by_user_id INTEGER")
    if "items_json" not in customer_order_columns:
        conn.execute("ALTER TABLE customer_orders ADD COLUMN items_json TEXT NOT NULL DEFAULT '[]'")
    if ENGLISH_NAME_CATALOG.exists():
        migrated = conn.execute("SELECT 1 FROM app_migrations WHERE name=?", (ENGLISH_NAME_CATALOG_VERSION,)).fetchone()
        import_meta_csv(
            conn,
            ENGLISH_NAME_CATALOG.read_text(encoding="utf-8-sig"),
            overwrite=not migrated,
            preserve_existing_metadata=True,
        )
        conn.execute("INSERT OR IGNORE INTO app_migrations(name) VALUES (?)", (ENGLISH_NAME_CATALOG_VERSION,))
    if PRODUCT_CATALOG.exists():
        migrated = conn.execute("SELECT 1 FROM app_migrations WHERE name=?", (PRODUCT_CATALOG_VERSION,)).fetchone()
        if not migrated:
            import_product_catalog_csv(conn, PRODUCT_CATALOG.read_text(encoding="utf-8-sig"))
            conn.execute("INSERT INTO app_migrations(name) VALUES (?)", (PRODUCT_CATALOG_VERSION,))
    taxonomy_migrated = conn.execute(
        "SELECT 1 FROM app_migrations WHERE name=?",
        (product_taxonomy.REGISTRY_VERSION,),
    ).fetchone()
    if not taxonomy_migrated:
        product_taxonomy.import_registry(conn)
        conn.execute(
            "INSERT INTO app_migrations(name) VALUES (?)",
            (product_taxonomy.REGISTRY_VERSION,),
        )
    taxonomy_normalized = conn.execute(
        "SELECT 1 FROM app_migrations WHERE name=?",
        (product_taxonomy.NORMALIZE_VERSION,),
    ).fetchone()
    if not taxonomy_normalized:
        product_taxonomy.normalize_existing_categories(conn)
        conn.execute(
            "INSERT INTO app_migrations(name) VALUES (?)",
            (product_taxonomy.NORMALIZE_VERSION,),
        )
    english_labels_normalized = conn.execute(
        "SELECT 1 FROM app_migrations WHERE name=?",
        (product_taxonomy.CANONICAL_ENGLISH_LABELS_VERSION,),
    ).fetchone()
    if not english_labels_normalized:
        product_taxonomy.normalize_existing_categories(conn)
        conn.execute(
            "INSERT INTO app_migrations(name) VALUES (?)",
            (product_taxonomy.CANONICAL_ENGLISH_LABELS_VERSION,),
        )
    catalogue_backfilled = conn.execute(
        "SELECT 1 FROM app_migrations WHERE name=?",
        (product_taxonomy.CATALOGUE_BACKFILL_VERSION,),
    ).fetchone()
    if not catalogue_backfilled:
        product_taxonomy.backfill_catalogue_categories(conn)
        conn.execute(
            "INSERT INTO app_migrations(name) VALUES (?)",
            (product_taxonomy.CATALOGUE_BACKFILL_VERSION,),
        )
    category_backfilled = conn.execute(
        "SELECT 1 FROM app_migrations WHERE name=?",
        (product_taxonomy.PENDING_BACKFILL_VERSION,),
    ).fetchone()
    if not category_backfilled:
        product_taxonomy.backfill_pending_imports(conn)
        conn.execute(
            "INSERT INTO app_migrations(name) VALUES (?)",
            (product_taxonomy.PENDING_BACKFILL_VERSION,),
        )
    seed_admin(conn)
    conn.commit()


def utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def record_drive_export(
    conn: sqlite3.Connection,
    *,
    job_key: str,
    user_id: str,
    sku: str,
    folder_id: str,
    folder_url: str,
    parent_id: str,
    created_at: datetime,
    expires_at: datetime,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO drive_exports(
          job_key, user_id, sku, folder_id, folder_url, parent_id, created_at, expires_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_key,
            str(user_id),
            sku.upper(),
            folder_id,
            folder_url,
            parent_id,
            utc_timestamp(created_at),
            utc_timestamp(expires_at),
        ),
    )
    conn.commit()
    return int(cursor.lastrowid)


def active_drive_export(conn: sqlite3.Connection, job_key: str, now: datetime) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM drive_exports
        WHERE job_key=? AND deleted_at IS NULL AND expires_at > ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (job_key, utc_timestamp(now)),
    ).fetchone()


def expired_drive_exports(conn: sqlite3.Connection, now: datetime, limit: int = 100) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT * FROM drive_exports
        WHERE deleted_at IS NULL AND expires_at <= ?
        ORDER BY expires_at, id
        LIMIT ?
        """,
        (utc_timestamp(now), max(1, min(limit, 1000))),
    ).fetchall()


def mark_drive_export_deleted(conn: sqlite3.Connection, export_id: int, deleted_at: datetime) -> None:
    conn.execute(
        "UPDATE drive_exports SET deleted_at=?, delete_error='' WHERE id=?",
        (utc_timestamp(deleted_at), export_id),
    )
    conn.commit()


def mark_drive_export_delete_error(conn: sqlite3.Connection, export_id: int, error: str) -> None:
    conn.execute(
        "UPDATE drive_exports SET delete_error=? WHERE id=?",
        (error[:1000], export_id),
    )
    conn.commit()


def create_product_message(conn: sqlite3.Connection, user_id: int, sku: str, body: str) -> sqlite3.Row:
    cursor = conn.execute(
        "INSERT INTO product_messages(user_id, sku, body) VALUES (?, ?, ?)",
        (user_id, sku.strip().upper(), body.strip()),
    )
    conn.commit()
    return conn.execute("SELECT * FROM product_messages WHERE id=?", (cursor.lastrowid,)).fetchone()


def user_product_messages(
    conn: sqlite3.Connection,
    user_id: int,
    sku: str,
    limit: int = 20,
) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT id, sku, body, created_at
        FROM product_messages
        WHERE user_id=? AND sku=?
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (user_id, sku.strip().upper(), max(1, min(limit, 100))),
    ).fetchall()


def admin_product_messages(
    conn: sqlite3.Connection,
    q: str = "",
    limit: int = 200,
    offset: int = 0,
) -> dict[str, object]:
    q = q.strip()
    where = ""
    args: list[object] = []
    if q:
        like = f"%{q}%"
        where = (
            "WHERE pm.sku LIKE ? OR pm.body LIKE ? OR u.name LIKE ? OR u.email LIKE ? "
            "OR COALESCE(meta.english_name, '') LIKE ?"
        )
        args = [like] * 5
    total = conn.execute(
        f"""
        SELECT COUNT(*)
        FROM product_messages pm
        JOIN users u ON u.id=pm.user_id
        LEFT JOIN sku_meta meta ON meta.sku=pm.sku
        {where}
        """,
        args,
    ).fetchone()[0]
    rows = conn.execute(
        f"""
        SELECT pm.id, pm.sku, pm.body, pm.created_at,
          u.id AS user_id, u.name AS user_name, u.email AS user_email,
          COALESCE(meta.english_name, '') AS product_name
        FROM product_messages pm
        JOIN users u ON u.id=pm.user_id
        LEFT JOIN sku_meta meta ON meta.sku=pm.sku
        {where}
        ORDER BY pm.created_at DESC, pm.id DESC
        LIMIT ? OFFSET ?
        """,
        [*args, max(1, min(limit, 500)), max(0, offset)],
    ).fetchall()
    return {"messages": [dict(row) for row in rows], "total": int(total)}


def user_favorite_skus(conn: sqlite3.Connection, user_id: int) -> set[str]:
    return {
        row["sku"]
        for row in conn.execute(
            "SELECT sku FROM product_favorites WHERE user_id=? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
    }


def set_product_favorite(conn: sqlite3.Connection, user_id: int, sku: str, favorite: bool) -> bool:
    sku = sku.strip().upper()
    if favorite:
        conn.execute(
            "INSERT INTO product_favorites(user_id, sku) VALUES (?, ?) ON CONFLICT(user_id, sku) DO NOTHING",
            (user_id, sku),
        )
    else:
        conn.execute("DELETE FROM product_favorites WHERE user_id=? AND sku=?", (user_id, sku))
    conn.commit()
    return favorite


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()
    return f"{salt}${digest}"


def verify_password(password: str, encoded: str) -> bool:
    salt, digest = encoded.split("$", 1)
    return hmac.compare_digest(hash_password(password, salt).split("$", 1)[1], digest)


def seed_admin(conn: sqlite3.Connection) -> None:
    email = os.getenv("ADMIN_EMAIL", "admin@example.com").lower()
    password = os.getenv("ADMIN_PASSWORD", "").strip()
    existing = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if existing:
        if existing["role"] != "super_admin" or (password and not verify_password(password, existing["password_hash"])):
            conn.execute(
                "UPDATE users SET name='Admin', role='super_admin', password_hash=? WHERE id=?",
                (hash_password(password) if password else existing["password_hash"], existing["id"]),
            )
        return

    admins = conn.execute("SELECT id, password_hash FROM users WHERE role IN ('super_admin', 'admin') ORDER BY id").fetchall()
    if len(admins) == 1:
        conn.execute(
            "UPDATE users SET email=?, name='Admin', role='super_admin', password_hash=? WHERE id=?",
            (email, hash_password(password) if password else admins[0]["password_hash"], admins[0]["id"]),
        )
        return

    conn.execute(
        "INSERT INTO users(email, name, role, password_hash) VALUES (?, 'Admin', 'super_admin', ?)",
        (email, hash_password(password or secrets.token_urlsafe(32))),
    )


def customer_account_expiry(now: datetime | None = None) -> str:
    return utc_timestamp((now or datetime.now(timezone.utc)) + timedelta(days=CUSTOMER_ACCOUNT_TTL_DAYS))


def disable_expired_customer_accounts(conn: sqlite3.Connection, now: datetime | None = None) -> int:
    placeholders = ",".join("?" for _ in CUSTOMER_ACCOUNT_ROLES)
    timestamp = utc_timestamp(now or datetime.now(timezone.utc))
    with conn:
        cursor = conn.execute(
            f"""
            UPDATE users
            SET disabled=1
            WHERE role IN ({placeholders})
              AND disabled=0
              AND expires_at IS NOT NULL
              AND datetime(expires_at) <= datetime(?)
            """,
            (*CUSTOMER_ACCOUNT_ROLES, timestamp),
        )
    return int(cursor.rowcount)


def authenticate_with_status(
    conn: sqlite3.Connection,
    email: str,
    password: str,
) -> tuple[sqlite3.Row | None, str]:
    disable_expired_customer_accounts(conn)
    user = conn.execute("SELECT * FROM users WHERE email = ?", (email.lower(),)).fetchone()
    if not user or not verify_password(password, user["password_hash"]):
        return None, "invalid"
    if int(user["disabled"] or 0):
        return None, "disabled"
    return user, "authenticated"


def authenticate(conn: sqlite3.Connection, email: str, password: str) -> sqlite3.Row | None:
    user, _status = authenticate_with_status(conn, email, password)
    return user


def _sync_dingtalk_department_role(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    identity_id: int,
    department_names: Iterable[str],
    departments_verified: bool,
) -> None:
    names = list(dict.fromkeys(str(name).strip() for name in department_names if str(name).strip()))
    identity = conn.execute("SELECT * FROM user_identities WHERE id=?", (identity_id,)).fetchone()
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not identity or not user:
        raise ValueError("DingTalk identity is not linked to a local user")
    is_information_technology = departments_verified and any(
        re.sub(r"\s+", "", name).casefold() == "信息技术部" for name in names
    )
    granted = bool(identity["department_role_granted"])
    previous_role = (identity["role_before_department_grant"] or "").strip()
    current_role = user["role"]

    if is_information_technology and current_role != "super_admin":
        previous_role = current_role if current_role in ROLES else "internal_staff"
        conn.execute("UPDATE users SET role='super_admin' WHERE id=?", (user_id,))
        granted = True
    elif not is_information_technology and granted:
        restored_role = previous_role if previous_role in ROLES and previous_role != "super_admin" else "internal_staff"
        conn.execute("UPDATE users SET role=? WHERE id=?", (restored_role, user_id))
        granted = False
        previous_role = ""

    conn.execute(
        """
        UPDATE user_identities
        SET department_names=?, departments_verified=?, department_role_granted=?,
            role_before_department_grant=?, department_synced_at=CURRENT_TIMESTAMP,
            updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (json.dumps(names, ensure_ascii=False), int(departments_verified), int(granted), previous_role, identity_id),
    )


def _apply_dingtalk_admin_grant(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    provider_user_id: str,
    display_name: str,
    department_names: Iterable[str],
) -> None:
    provider_user_id = provider_user_id.strip()
    if not provider_user_id:
        return
    grant = conn.execute(
        "SELECT * FROM dingtalk_admin_grants WHERE provider_user_id=?",
        (provider_user_id,),
    ).fetchone()
    if not grant:
        return
    names = list(dict.fromkeys(str(name).strip() for name in department_names if str(name).strip()))
    conn.execute(
        """
        UPDATE dingtalk_admin_grants
        SET user_id=?, display_name=?, department_names=?, updated_at=CURRENT_TIMESTAMP
        WHERE provider_user_id=?
        """,
        (user_id, display_name.strip(), json.dumps(names, ensure_ascii=False), provider_user_id),
    )
    current = conn.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
    if current and current["role"] != "super_admin":
        conn.execute("UPDATE users SET role='admin' WHERE id=?", (user_id,))


def set_dingtalk_admin_grant(
    conn: sqlite3.Connection,
    *,
    provider_user_id: str,
    display_name: str,
    department_names: Iterable[str],
    granted_by_user_id: int,
    enabled: bool,
) -> None:
    provider_user_id = provider_user_id.strip()
    if not provider_user_id:
        raise ValueError("钉钉员工标识不能为空")
    names = list(dict.fromkeys(str(name).strip() for name in department_names if str(name).strip()))
    existing = conn.execute(
        "SELECT * FROM dingtalk_admin_grants WHERE provider_user_id=?",
        (provider_user_id,),
    ).fetchone()
    linked_user = conn.execute(
        """
        SELECT users.*
        FROM user_identities
        JOIN users ON users.id=user_identities.user_id
        WHERE user_identities.provider='dingtalk' AND user_identities.provider_user_id=?
        ORDER BY user_identities.id
        LIMIT 1
        """,
        (provider_user_id,),
    ).fetchone()
    if linked_user and linked_user["role"] == "super_admin":
        raise ValueError("超级管理员由信息技术部自动识别，不能手工修改")

    with conn:
        if enabled:
            previous_role = (
                str(existing["role_before_grant"] or "").strip()
                if existing
                else str(linked_user["role"] if linked_user else "internal_staff")
            )
            if previous_role not in ROLES or previous_role == "super_admin":
                previous_role = "internal_staff"
            conn.execute(
                """
                INSERT INTO dingtalk_admin_grants(
                  provider_user_id, display_name, department_names, user_id,
                  granted_by_user_id, role_before_grant
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider_user_id) DO UPDATE SET
                  display_name=excluded.display_name,
                  department_names=excluded.department_names,
                  user_id=excluded.user_id,
                  granted_by_user_id=excluded.granted_by_user_id,
                  updated_at=CURRENT_TIMESTAMP
                """,
                (
                    provider_user_id,
                    display_name.strip(),
                    json.dumps(names, ensure_ascii=False),
                    int(linked_user["id"]) if linked_user else None,
                    int(granted_by_user_id),
                    previous_role,
                ),
            )
            if linked_user:
                conn.execute("UPDATE users SET role='admin' WHERE id=?", (int(linked_user["id"]),))
            return

        if not existing:
            return
        if linked_user and linked_user["role"] == "admin":
            restored_role = str(existing["role_before_grant"] or "internal_staff").strip()
            if restored_role not in ROLES or restored_role == "super_admin":
                restored_role = "internal_staff"
            conn.execute("UPDATE users SET role=? WHERE id=?", (restored_role, int(linked_user["id"])))
        conn.execute("DELETE FROM dingtalk_admin_grants WHERE provider_user_id=?", (provider_user_id,))


def dingtalk_member_access(conn: sqlite3.Connection) -> dict[str, dict]:
    access: dict[str, dict] = {}
    for row in conn.execute(
        """
        SELECT identities.provider_user_id, users.id AS user_id, users.role
        FROM user_identities identities
        JOIN users ON users.id=identities.user_id
        WHERE identities.provider='dingtalk' AND identities.provider_user_id != ''
        """
    ).fetchall():
        access[row["provider_user_id"]] = {
            "local_user_id": int(row["user_id"]),
            "role": row["role"],
            "admin_granted": False,
        }
    for row in conn.execute("SELECT provider_user_id, user_id FROM dingtalk_admin_grants").fetchall():
        item = access.setdefault(
            row["provider_user_id"],
            {"local_user_id": row["user_id"], "role": "admin", "admin_granted": True},
        )
        item["admin_granted"] = True
        if item["role"] != "super_admin":
            item["role"] = "admin"
    return access


def dingtalk_organization_cache(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        "SELECT directory_json, synced_at FROM dingtalk_organization_cache WHERE id=1"
    ).fetchone()
    if not row:
        return None
    try:
        directory = json.loads(row["directory_json"])
    except (TypeError, ValueError):
        return None
    if not isinstance(directory, dict):
        return None
    return {"directory": directory, "synced_at": str(row["synced_at"])}


def save_dingtalk_organization_cache(
    conn: sqlite3.Connection,
    directory: dict,
    synced_at: str,
) -> None:
    payload = json.dumps(directory, ensure_ascii=False, separators=(",", ":"))
    with conn:
        conn.execute(
            """
            INSERT INTO dingtalk_organization_cache(id, directory_json, synced_at)
            VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              directory_json=excluded.directory_json,
              synced_at=excluded.synced_at
            """,
            (payload, synced_at),
        )


def dingtalk_provider_user_id_by_name(conn: sqlite3.Connection, name: str) -> str:
    target = name.strip()
    if not target:
        return ""
    row = conn.execute(
        """
        SELECT identities.provider_user_id
        FROM user_identities identities
        JOIN users ON users.id=identities.user_id
        WHERE identities.provider='dingtalk' AND identities.provider_user_id != ''
          AND (users.name=? COLLATE NOCASE OR identities.display_name=? COLLATE NOCASE)
        ORDER BY identities.last_login_at DESC, identities.id DESC
        LIMIT 1
        """,
        (target, target),
    ).fetchone()
    return str(row["provider_user_id"] or "").strip() if row else ""


def recent_missing_sku_notification(
    conn: sqlite3.Connection,
    user_id: int,
    fingerprint: str,
    hours: int = 24,
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM missing_sku_notifications
        WHERE user_id=? AND fingerprint=? AND status='sent'
          AND created_at >= datetime('now', ?)
        ORDER BY id DESC LIMIT 1
        """,
        (int(user_id), fingerprint, f"-{max(1, int(hours))} hours"),
    ).fetchone()


def record_missing_sku_notification(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    fingerprint: str,
    searched_count: int,
    missing_skus: list[str],
    recipient_name: str,
    task_ids: list[str],
    status: str,
    error: str = "",
) -> int:
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO missing_sku_notifications(
              user_id, fingerprint, searched_count, missing_skus_json,
              recipient_name, task_ids_json, status, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(user_id), fingerprint, int(searched_count),
                json.dumps(missing_skus, ensure_ascii=False), recipient_name.strip(),
                json.dumps(task_ids), status, error[:500],
            ),
        )
    return int(cursor.lastrowid)


def find_or_create_dingtalk_user(
    conn: sqlite3.Connection,
    profile: dict,
    *,
    provider_user_id: str = "",
    department_names: Iterable[str] = (),
    departments_verified: bool = False,
) -> sqlite3.Row:
    provider_user_id = provider_user_id.strip()
    department_names = tuple(
        name.strip() for name in department_names if isinstance(name, str) and name.strip()
    )
    subject = dingtalk_auth.profile_subject(profile)
    if not subject:
        raise ValueError("DingTalk profile is missing a stable identity")
    open_id = dingtalk_auth.profile_open_id(profile)
    email = dingtalk_auth.profile_email(profile)
    name = dingtalk_auth.profile_name(profile)
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        digest = hashlib.sha256(subject.encode("utf-8")).hexdigest()[:24]
        email = f"dingtalk-{digest}@local.invalid"

    identity = conn.execute(
        """
        SELECT users.*, user_identities.id AS identity_id
        FROM user_identities
        JOIN users ON users.id = user_identities.user_id
        WHERE user_identities.provider='dingtalk' AND user_identities.provider_subject=?
        """,
        (subject,),
    ).fetchone()
    if identity:
        with conn:
            conn.execute(
                """
                UPDATE user_identities
                SET provider_open_id=?, provider_user_id=?, provider_email=?, display_name=?,
                    updated_at=CURRENT_TIMESTAMP, last_login_at=CURRENT_TIMESTAMP
                WHERE provider='dingtalk' AND provider_subject=?
                """,
                (open_id, provider_user_id, dingtalk_auth.profile_email(profile), name, subject),
            )
            _sync_dingtalk_department_role(
                conn,
                user_id=int(identity["id"]),
                identity_id=int(identity["identity_id"]),
                department_names=department_names,
                departments_verified=departments_verified,
            )
            _apply_dingtalk_admin_grant(
                conn,
                user_id=int(identity["id"]),
                provider_user_id=provider_user_id,
                display_name=name,
                department_names=department_names,
            )
        return conn.execute("SELECT * FROM users WHERE id=?", (identity["id"],)).fetchone()

    with conn:
        user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if not user:
            cursor = conn.execute(
                """
                INSERT INTO users(email, name, role, password_hash)
                VALUES (?, ?, 'internal_staff', ?)
                """,
                (email, name, hash_password(secrets.token_urlsafe(48))),
            )
            user_id = int(cursor.lastrowid)
        else:
            user_id = int(user["id"])
        identity_cursor = conn.execute(
            """
            INSERT INTO user_identities(
              user_id, provider, provider_subject, provider_open_id, provider_user_id,
              provider_email, display_name
            ) VALUES (?, 'dingtalk', ?, ?, ?, ?, ?)
            """,
            (user_id, subject, open_id, provider_user_id, dingtalk_auth.profile_email(profile), name),
        )
        _sync_dingtalk_department_role(
            conn,
            user_id=user_id,
            identity_id=int(identity_cursor.lastrowid),
            department_names=department_names,
            departments_verified=departments_verified,
        )
        _apply_dingtalk_admin_grant(
            conn,
            user_id=user_id,
            provider_user_id=provider_user_id,
            display_name=name,
            department_names=department_names,
        )
    return conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()


def create_user(conn: sqlite3.Connection, email: str, name: str, role: str, password: str) -> int:
    role = normalize_role(role)
    if role not in ROLES:
        raise ValueError("Invalid role")
    expires_at = customer_account_expiry() if role in CUSTOMER_ACCOUNT_ROLES else None
    cursor = conn.execute(
        "INSERT INTO users(email, name, role, password_hash, expires_at) VALUES (?, ?, ?, ?, ?)",
        (email.lower(), name.strip() or email, role, hash_password(password), expires_at),
    )
    conn.commit()
    return int(cursor.lastrowid)


def list_users(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT id, email, name, role, disabled, created_at FROM users ORDER BY id").fetchall()


def list_customer_users(conn: sqlite3.Connection, created_by_user_id: int | None = None) -> list[sqlite3.Row]:
    disable_expired_customer_accounts(conn)
    placeholders = ",".join("?" for _ in CUSTOMER_ACCOUNT_ROLES)
    return conn.execute(
        f"""
        SELECT users.id, users.email, users.name, users.role, users.disabled, users.expires_at, users.created_at,
               CASE WHEN users.expires_at IS NOT NULL AND datetime(users.expires_at) <= CURRENT_TIMESTAMP THEN 1 ELSE 0 END AS expired,
               users.created_by_user_id, COALESCE(creators.name, '') AS created_by_name,
               COALESCE(profiles.mode, 'role_default') AS permission_mode
        FROM users
        LEFT JOIN user_permission_profiles profiles ON profiles.user_id=users.id
        LEFT JOIN users creators ON creators.id=users.created_by_user_id
        WHERE users.role IN ({placeholders})
          AND (? IS NULL OR users.created_by_user_id=?)
        ORDER BY users.id DESC
        """,
        (*CUSTOMER_ACCOUNT_ROLES, created_by_user_id, created_by_user_id),
    ).fetchall()


def list_salespeople(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT id, email, name, role, disabled
        FROM users
        WHERE role IN ('admin', 'super_admin')
        ORDER BY disabled ASC, name COLLATE NOCASE, id
        """
    ).fetchall()


CATALOG_EVENT_TYPES = frozenset({"catalog_view", "search", "product_open", "product_added", "product_removed", "checkout_open"})


def record_catalog_event(conn: sqlite3.Connection, user_id: int, event_type: str, sku: str = "") -> int:
    if event_type not in CATALOG_EVENT_TYPES:
        raise ValueError("Invalid catalog event type")
    with conn:
        cursor = conn.execute(
            "INSERT INTO catalog_events(user_id, event_type, sku) VALUES (?, ?, ?)",
            (int(user_id), event_type, sku.strip().upper()),
        )
    return int(cursor.lastrowid)


def record_user_activity(
    conn: sqlite3.Connection,
    user_id: int,
    event_type: str,
    *,
    sku: str = "",
    file_id: str = "",
    file_name: str = "",
    detail: str = "",
) -> int:
    event_type = event_type.strip().lower()
    if event_type not in USER_ACTIVITY_TYPES:
        raise ValueError("Invalid user activity type")
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO user_activity_events(user_id, event_type, sku, file_id, file_name, detail)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                int(user_id),
                event_type,
                sku.strip().upper(),
                file_id.strip(),
                file_name.strip(),
                detail.strip(),
            ),
        )
    return int(cursor.lastrowid)


def user_monitor_overview(conn: sqlite3.Connection) -> dict[str, object]:
    users = [
        dict(row)
        for row in conn.execute(
            """
            SELECT users.id, users.email, users.name, users.role, users.created_at,
                   MAX(CASE WHEN events.event_type='login' THEN events.created_at END) AS last_login_at,
                   SUM(CASE WHEN events.event_type='login' THEN 1 ELSE 0 END) AS login_count,
                   SUM(CASE WHEN events.event_type='original_open' THEN 1 ELSE 0 END) AS original_open_count,
                   SUM(CASE WHEN events.event_type IN ('download','drive_export') THEN 1 ELSE 0 END) AS download_count,
                   COUNT(events.id) AS event_count
            FROM users
            LEFT JOIN user_activity_events events ON events.user_id=users.id
            GROUP BY users.id
            ORDER BY CASE WHEN MAX(CASE WHEN events.event_type='login' THEN events.created_at END) IS NULL THEN 1 ELSE 0 END,
                     last_login_at DESC, users.name, users.email
            """
        ).fetchall()
    ]
    stats = dict(
        conn.execute(
            """
            SELECT COUNT(*) AS events,
                   COUNT(DISTINCT CASE WHEN event_type='login' THEN user_id END) AS logged_in_users,
                   SUM(CASE WHEN event_type='login' THEN 1 ELSE 0 END) AS logins,
                   SUM(CASE WHEN event_type='original_open' THEN 1 ELSE 0 END) AS original_opens,
                   SUM(CASE WHEN event_type IN ('download','drive_export') THEN 1 ELSE 0 END) AS downloads
            FROM user_activity_events
            """
        ).fetchone()
    )
    return {
        "users": users,
        "stats": {
            "users": len(users),
            "logged_in_users": int(stats["logged_in_users"] or 0),
            "logins": int(stats["logins"] or 0),
            "original_opens": int(stats["original_opens"] or 0),
            "downloads": int(stats["downloads"] or 0),
            "events": int(stats["events"] or 0),
        },
    }


def user_activity_detail(conn: sqlite3.Connection, user_id: int, limit: int = 500) -> dict[str, object]:
    user = conn.execute(
        "SELECT id, email, name, role, created_at FROM users WHERE id=?",
        (int(user_id),),
    ).fetchone()
    if not user:
        raise ValueError("User not found")
    events = [
        dict(row)
        for row in conn.execute(
            """
            SELECT id, event_type, sku, file_id, file_name, detail, created_at
            FROM user_activity_events
            WHERE user_id=?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (int(user_id), max(1, min(int(limit), 1000))),
        ).fetchall()
    ]
    return {"user": dict(user), "events": events}


def list_role_rules(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM role_permission_rules ORDER BY role, scope, value").fetchall()


def role_rules(conn: sqlite3.Connection, role: str) -> list[sqlite3.Row]:
    role = normalize_role(role)
    if role in {"super_admin", "admin"}:
        return []
    return conn.execute("SELECT * FROM role_permission_rules WHERE role = ? ORDER BY id", (role,)).fetchall()


def create_role_rule(conn: sqlite3.Connection, role: str, scope: str, value: str) -> None:
    role = normalize_role(role)
    value = normalize_rule_value(scope, value)
    if role not in PERMISSION_ROLES or scope not in RULE_SCOPES or not value:
        raise ValueError("Invalid permission rule")
    conn.execute(
        "INSERT OR IGNORE INTO role_permission_rules(role, scope, value) VALUES (?, ?, ?)",
        (role, scope, value),
    )
    conn.commit()


def delete_role_rule(conn: sqlite3.Connection, rule_id: int) -> None:
    conn.execute("DELETE FROM role_permission_rules WHERE id = ?", (rule_id,))
    conn.commit()


def list_user_grants(conn: sqlite3.Connection, created_by_user_id: int | None = None) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT grants.*, users.email, users.name, users.role
        FROM user_permission_grants grants
        JOIN users ON users.id=grants.user_id
        WHERE (? IS NULL OR users.created_by_user_id=?)
        ORDER BY users.name, grants.scope, grants.value
        """,
        (created_by_user_id, created_by_user_id),
    ).fetchall()


def customer_owned_by(conn: sqlite3.Connection, user_id: int, owner_user_id: int) -> bool:
    return conn.execute(
        "SELECT 1 FROM users WHERE id=? AND created_by_user_id=?",
        (int(user_id), int(owner_user_id)),
    ).fetchone() is not None


def user_grants(conn: sqlite3.Connection, user_id: int | None) -> list[sqlite3.Row]:
    if user_id is None:
        return []
    return conn.execute(
        "SELECT * FROM user_permission_grants WHERE user_id=? ORDER BY id",
        (int(user_id),),
    ).fetchall()


def user_permission_mode(conn: sqlite3.Connection, user_id: int | None) -> str:
    if user_id is None:
        return "role_default"
    row = conn.execute(
        "SELECT mode FROM user_permission_profiles WHERE user_id=?",
        (int(user_id),),
    ).fetchone()
    return str(row["mode"]) if row else "role_default"


def migrate_role_rules_to_account_grants(conn: sqlite3.Connection) -> dict[str, int]:
    """Replace role-level rules with equivalent explicit customer allowlists.

    The migration preserves each account's current brand and special-collection
    visibility, then removes every global role rule in one transaction.
    """
    values = permission_rule_values(conn)
    brand_values = values.get("brand", [])
    other_values = [value for value in values.get("other", []) if value != "No Brand"]
    rules = list_role_rules(conn)
    unsupported = {
        normalize_permission_rule(str(rule["scope"]), str(rule["value"]))[0]
        for rule in rules
    } - {"brand", "other"}
    if unsupported:
        raise ValueError(f"Unsupported global permission scopes: {', '.join(sorted(unsupported))}")

    migrated = 0
    grant_count = 0
    with conn:
        for user in list_customer_users(conn):
            user_id = int(user["id"])
            role = normalize_role(str(user["role"]))
            mode = str(user["permission_mode"] or "role_default")
            existing_keys = {
                (scope, value.lower())
                for scope, value in (
                    normalize_permission_rule(str(grant["scope"]), str(grant["value"]))
                    for grant in user_grants(conn, user_id)
                )
            }
            hidden_keys = {
                (scope, value.lower())
                for scope, value in (
                    normalize_permission_rule(str(rule["scope"]), str(rule["value"]))
                    for rule in rules
                    if normalize_role(str(rule["role"])) == role
                )
            }

            grants: list[tuple[str, str]] = []
            for value in brand_values:
                scope, normalized_value = normalize_permission_rule("brand", value)
                key = (scope, normalized_value.lower())
                explicitly_granted = key in existing_keys
                visible = explicitly_granted if mode == "allowlist" else key not in hidden_keys or explicitly_granted
                if visible:
                    grants.append((scope, normalized_value))
            for value in other_values:
                scope, normalized_value = normalize_permission_rule("other", value)
                key = (scope, normalized_value.lower())
                explicitly_granted = key in existing_keys
                visible = explicitly_granted and key not in hidden_keys if mode == "allowlist" else key not in hidden_keys
                if visible:
                    grants.append((scope, normalized_value))

            if not grants:
                raise ValueError(f"Account {user_id} would have no permissions after migration")
            conn.execute(
                """
                INSERT INTO user_permission_profiles(user_id, mode, updated_at)
                VALUES (?, 'allowlist', CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET mode='allowlist', updated_at=CURRENT_TIMESTAMP
                """,
                (user_id,),
            )
            conn.execute("DELETE FROM user_permission_grants WHERE user_id=?", (user_id,))
            conn.executemany(
                "INSERT INTO user_permission_grants(user_id, scope, value) VALUES (?, ?, ?)",
                [(user_id, scope, value) for scope, value in grants],
            )
            migrated += 1
            grant_count += len(grants)
        conn.execute("DELETE FROM role_permission_rules")
    return {"accounts": migrated, "grants": grant_count, "rules_deleted": len(rules)}


def create_customer_user_with_permissions(
    conn: sqlite3.Connection,
    email: str,
    name: str,
    role: str,
    password: str,
    permission_mode: str = "role_default",
    grants: Iterable[tuple[str, str]] = (),
    created_by_user_id: int | None = None,
) -> sqlite3.Row:
    role = normalize_role(role)
    permission_mode = permission_mode.strip().lower()
    if role not in CUSTOMER_ACCOUNT_ROLES:
        raise ValueError("Invalid customer role")
    if permission_mode not in USER_PERMISSION_MODES:
        raise ValueError("Invalid customer permission mode")

    normalized_grants: list[tuple[str, str]] = []
    for scope, value in grants:
        scope = scope.strip().lower()
        normalized_value = normalize_rule_value(scope, value)
        if scope not in RULE_SCOPES or not normalized_value:
            raise ValueError("Invalid customer permission")
        item = (scope, normalized_value)
        if item not in normalized_grants:
            normalized_grants.append(item)
    if permission_mode == "allowlist" and not normalized_grants:
        raise ValueError("At least one permission is required for an allowlist account")
    if permission_mode == "role_default":
        normalized_grants = []

    with conn:
        cursor = conn.execute(
            "INSERT INTO users(email, name, role, password_hash, expires_at, created_by_user_id) VALUES (?, ?, ?, ?, ?, ?)",
            (
                email.lower(),
                name.strip() or email,
                role,
                hash_password(password),
                customer_account_expiry(),
                int(created_by_user_id) if created_by_user_id is not None else None,
            ),
        )
        user_id = int(cursor.lastrowid)
        conn.execute(
            "INSERT INTO user_permission_profiles(user_id, mode) VALUES (?, ?)",
            (user_id, permission_mode),
        )
        conn.executemany(
            "INSERT INTO user_permission_grants(user_id, scope, value) VALUES (?, ?, ?)",
            [(user_id, scope, value) for scope, value in normalized_grants],
        )
    return conn.execute(
        """
        SELECT users.id, users.email, users.name, users.role, users.disabled, users.expires_at, users.created_at, users.created_by_user_id,
               profiles.mode AS permission_mode
        FROM users
        JOIN user_permission_profiles profiles ON profiles.user_id=users.id
        WHERE users.id=?
        """,
        (user_id,),
    ).fetchone()


def sales_catalog_owner_for_user(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row | None:
    user = conn.execute(
        "SELECT id, role, created_by_user_id FROM users WHERE id=?",
        (int(user_id),),
    ).fetchone()
    if not user:
        raise ValueError("User not found")
    role = normalize_role(user["role"])
    owner_id = int(user["id"]) if role in {"super_admin", "admin"} else user["created_by_user_id"]
    return conn.execute("SELECT id, name FROM users WHERE id=?", (owner_id,)).fetchone() if owner_id else None


def customer_order_salesperson(conn: sqlite3.Connection, customer_user_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT salesperson.id, salesperson.name, salesperson.email, salesperson.role
        FROM users customer
        JOIN users salesperson ON salesperson.id=customer.created_by_user_id
        WHERE customer.id=? AND customer.role IN (?, ?, ?) AND salesperson.role IN ('admin', 'super_admin')
        """,
        (int(customer_user_id), *CUSTOMER_ACCOUNT_ROLES),
    ).fetchone()


def dingtalk_provider_user_id_for_user(conn: sqlite3.Connection, user_id: int) -> str:
    row = conn.execute(
        """
        SELECT provider_user_id
        FROM user_identities
        WHERE user_id=? AND provider='dingtalk' AND provider_user_id != ''
        ORDER BY last_login_at DESC, id DESC
        LIMIT 1
        """,
        (int(user_id),),
    ).fetchone()
    return str(row["provider_user_id"] or "").strip() if row else ""


def create_customer_order(
    conn: sqlite3.Connection,
    *,
    order_number: str,
    idempotency_key: str,
    customer_user_id: int,
    salesperson_user_id: int,
    customer_name: str,
    customer_email: str,
    title: str,
    company: str,
    contact: str,
    reference: str,
    currency: str,
    product_count: int,
    total_quantity: int,
    total_amount_cents: int,
    unpriced_count: int,
    items_json: str,
    file_name: str,
    stored_file_name: str,
    file_size: int,
    download_token_hash: str,
) -> sqlite3.Row:
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO customer_orders(
              order_number, idempotency_key, customer_user_id, salesperson_user_id,
              customer_name, customer_email, title, company, contact, reference, currency,
              product_count, total_quantity, total_amount_cents, unpriced_count, items_json,
              file_name, stored_file_name, file_size, download_token_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order_number, idempotency_key, int(customer_user_id), int(salesperson_user_id),
                customer_name, customer_email, title, company, contact, reference, currency,
                int(product_count), int(total_quantity), int(total_amount_cents), int(unpriced_count),
                items_json, file_name, stored_file_name, int(file_size), download_token_hash,
            ),
        )
    return customer_order_by_id(conn, int(cursor.lastrowid))


def customer_order_by_id(conn: sqlite3.Connection, order_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT customer_orders.*, salesperson.name AS salesperson_name,
               salesperson.email AS salesperson_email
        FROM customer_orders
        JOIN users salesperson ON salesperson.id=customer_orders.salesperson_user_id
        WHERE customer_orders.id=?
        """,
        (int(order_id),),
    ).fetchone()


def customer_order_by_idempotency(
    conn: sqlite3.Connection,
    customer_user_id: int,
    idempotency_key: str,
) -> sqlite3.Row | None:
    row = conn.execute(
        "SELECT id FROM customer_orders WHERE customer_user_id=? AND idempotency_key=?",
        (int(customer_user_id), idempotency_key),
    ).fetchone()
    return customer_order_by_id(conn, int(row["id"])) if row else None


def list_customer_orders_for_user(conn: sqlite3.Connection, user_id: int, role: str) -> list[sqlite3.Row]:
    normalized_role = normalize_role(role)
    where_clause = "" if normalized_role == "super_admin" else (
        "WHERE customer_orders.salesperson_user_id=?"
        if normalized_role == "admin"
        else "WHERE customer_orders.customer_user_id=?"
    )
    params: tuple[int, ...] = () if normalized_role == "super_admin" else (int(user_id),)
    return conn.execute(
        f"""
        SELECT customer_orders.*, salesperson.name AS salesperson_name,
               salesperson.email AS salesperson_email
        FROM customer_orders
        JOIN users salesperson ON salesperson.id=customer_orders.salesperson_user_id
        {where_clause}
        ORDER BY customer_orders.created_at DESC, customer_orders.id DESC
        """,
        params,
    ).fetchall()


def pending_customer_order_count_for_user(conn: sqlite3.Connection, user_id: int, role: str) -> int:
    normalized_role = normalize_role(role)
    if normalized_role == "super_admin":
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM customer_orders WHERE status='new'"
        ).fetchone()
    elif normalized_role == "admin":
        row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM customer_orders
            WHERE status='new' AND salesperson_user_id=?
            """,
            (int(user_id),),
        ).fetchone()
    else:
        return 0
    return int(row["count"] if row else 0)


def update_customer_order_notification(
    conn: sqlite3.Connection,
    order_id: int,
    *,
    status: str,
    task_id: str = "",
    error: str = "",
) -> None:
    conn.execute(
        """
        UPDATE customer_orders
        SET notification_status=?, notification_task_id=?, notification_error=?
        WHERE id=?
        """,
        (status, task_id[:120], error[:500], int(order_id)),
    )
    conn.commit()


def confirm_customer_order(
    conn: sqlite3.Connection,
    order_id: int,
    *,
    confirmed_by_user_id: int | None = None,
) -> None:
    conn.execute(
        """
        UPDATE customer_orders
        SET status='confirmed',
            confirmed_at=COALESCE(confirmed_at, CURRENT_TIMESTAMP),
            confirmed_by_user_id=COALESCE(confirmed_by_user_id, ?)
        WHERE id=? AND status != 'confirmed'
        """,
        (int(confirmed_by_user_id) if confirmed_by_user_id is not None else None, int(order_id)),
    )
    conn.commit()


def sales_catalog_order_for_user(conn: sqlite3.Connection, user_id: int) -> dict[str, object]:
    owner = sales_catalog_owner_for_user(conn, user_id)
    owner_id = int(owner["id"]) if owner else None
    row = conn.execute(
        "SELECT sku_order_json, draft_json, revision, updated_at FROM sales_catalog_orders WHERE owner_user_id=?",
        (int(owner_id),),
    ).fetchone() if owner_id else None
    try:
        sku_order = json.loads(row["sku_order_json"]) if row else []
    except (TypeError, json.JSONDecodeError):
        sku_order = []
    if not isinstance(sku_order, list):
        sku_order = []
    try:
        draft = json.loads(row["draft_json"]) if row else None
    except (TypeError, json.JSONDecodeError):
        draft = None
    if not isinstance(draft, dict):
        draft = None
    return {
        "owner_user_id": int(owner["id"]) if owner else None,
        "owner_name": str(owner["name"]) if owner else "",
        "sku_order": sku_order,
        "draft": draft,
        "revision": int(row["revision"]) if row else 0,
        "updated_at": row["updated_at"] if row else None,
    }


def save_sales_catalog_order(
    conn: sqlite3.Connection,
    owner_user_id: int,
    sku_order: Iterable[str],
    draft: dict[str, object],
    *,
    expected_revision: int,
) -> dict[str, object]:
    owner = conn.execute("SELECT role FROM users WHERE id=?", (int(owner_user_id),)).fetchone()
    if not owner or normalize_role(owner["role"]) not in {"super_admin", "admin"}:
        raise ValueError("Administrator account not found")
    normalized: list[str] = []
    for value in sku_order:
        if not isinstance(value, str):
            raise ValueError("Catalog order must contain SKU text values")
        sku = value.strip()
        if not sku or len(sku) > 100 or sku in {"__proto__", "prototype", "constructor"}:
            raise ValueError("Catalog order contains an invalid SKU")
        if sku not in normalized:
            normalized.append(sku)
        if len(normalized) > 5000:
            raise ValueError("Catalog order supports up to 5000 products")
    if not isinstance(draft, dict):
        raise ValueError("Catalog table must be a JSON object")
    draft_json = json.dumps(draft, ensure_ascii=False, separators=(",", ":"))
    if len(draft_json.encode("utf-8")) > 2_000_000:
        raise ValueError("Catalog table is too large to save. Remove embedded pictures and try again.")
    current = conn.execute(
        "SELECT revision FROM sales_catalog_orders WHERE owner_user_id=?",
        (int(owner_user_id),),
    ).fetchone()
    revision = int(current["revision"]) if current else 0
    if int(expected_revision) != revision:
        raise RuntimeError("Catalog order changed in another browser. Reload it before saving.")
    with conn:
        conn.execute(
            """
            INSERT INTO sales_catalog_orders(owner_user_id, sku_order_json, draft_json, revision, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(owner_user_id) DO UPDATE SET
              sku_order_json=excluded.sku_order_json,
              draft_json=excluded.draft_json,
              revision=excluded.revision,
              updated_at=CURRENT_TIMESTAMP
            """,
            (int(owner_user_id), json.dumps(normalized, ensure_ascii=False), draft_json, revision + 1),
        )
    return sales_catalog_order_for_user(conn, int(owner_user_id))


def update_customer_user_with_permissions(
    conn: sqlite3.Connection,
    user_id: int,
    *,
    name: str,
    role: str,
    disabled: bool,
    permission_mode: str = "role_default",
    grants: Iterable[tuple[str, str]] = (),
) -> sqlite3.Row:
    role = normalize_role(role)
    permission_mode = permission_mode.strip().lower()
    if role not in CUSTOMER_ACCOUNT_ROLES:
        raise ValueError("Invalid customer role")
    if permission_mode not in USER_PERMISSION_MODES:
        raise ValueError("Invalid customer permission mode")

    normalized_grants: list[tuple[str, str]] = []
    for scope, value in grants:
        scope = scope.strip().lower()
        normalized_value = normalize_rule_value(scope, value)
        if scope not in RULE_SCOPES or not normalized_value:
            raise ValueError("Invalid customer permission")
        item = (scope, normalized_value)
        if item not in normalized_grants:
            normalized_grants.append(item)
    if permission_mode == "allowlist" and not normalized_grants:
        raise ValueError("At least one permission is required for an allowlist account")
    if permission_mode == "role_default":
        normalized_grants = []

    existing = conn.execute("SELECT role FROM users WHERE id=?", (int(user_id),)).fetchone()
    if not existing or normalize_role(existing["role"]) not in CUSTOMER_ACCOUNT_ROLES:
        raise ValueError("Customer user not found")

    with conn:
        disabled_value = int(bool(disabled))
        expires_at = customer_account_expiry() if not disabled_value else None
        conn.execute(
            """
            UPDATE users
            SET name=?, role=?, disabled=?,
                expires_at=CASE WHEN ?=0 THEN ? ELSE expires_at END
            WHERE id=?
            """,
            (
                name.strip() or "Customer",
                role,
                disabled_value,
                disabled_value,
                expires_at,
                int(user_id),
            ),
        )
        conn.execute(
            """
            INSERT INTO user_permission_profiles(user_id, mode, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET mode=excluded.mode, updated_at=CURRENT_TIMESTAMP
            """,
            (int(user_id), permission_mode),
        )
        conn.execute("DELETE FROM user_permission_grants WHERE user_id=?", (int(user_id),))
        conn.executemany(
            "INSERT INTO user_permission_grants(user_id, scope, value) VALUES (?, ?, ?)",
            [(int(user_id), scope, value) for scope, value in normalized_grants],
        )
    return conn.execute(
        """
        SELECT users.id, users.email, users.name, users.role, users.disabled, users.expires_at, users.created_at,
               profiles.mode AS permission_mode
        FROM users
        JOIN user_permission_profiles profiles ON profiles.user_id=users.id
        WHERE users.id=?
        """,
        (int(user_id),),
    ).fetchone()


def renew_expired_customer_user(conn: sqlite3.Connection, user_id: int, renewed_by_user_id: int) -> sqlite3.Row:
    disable_expired_customer_accounts(conn)
    user = conn.execute(
        "SELECT role, disabled, expires_at FROM users WHERE id=?", (int(user_id),)
    ).fetchone()
    if not user or normalize_role(user["role"]) not in CUSTOMER_ACCOUNT_ROLES:
        raise ValueError("Customer user not found")
    if not user["disabled"] or not user["expires_at"] or user["expires_at"] > utc_timestamp(datetime.now(timezone.utc)):
        raise ValueError("Only expired customer accounts can be renewed")
    next_expiry = customer_account_expiry()
    with conn:
        conn.execute(
            "UPDATE users SET disabled=0, expires_at=? WHERE id=?",
            (next_expiry, int(user_id)),
        )
        conn.execute(
            "INSERT INTO customer_account_renewals(customer_user_id, renewed_by_user_id, previous_expires_at, new_expires_at) VALUES (?, ?, ?, ?)",
            (int(user_id), int(renewed_by_user_id), user["expires_at"], next_expiry),
        )
    return conn.execute("SELECT id, expires_at, disabled FROM users WHERE id=?", (int(user_id),)).fetchone()


def reset_customer_user_password(conn: sqlite3.Connection, user_id: int, password: str) -> None:
    if len(password) < 8:
        raise ValueError("Temporary password must be at least 8 characters")
    user = conn.execute("SELECT role FROM users WHERE id=?", (int(user_id),)).fetchone()
    if not user or normalize_role(user["role"]) not in CUSTOMER_ACCOUNT_ROLES:
        raise ValueError("Customer user not found")
    with conn:
        conn.execute(
            "UPDATE users SET password_hash=? WHERE id=?",
            (hash_password(password), int(user_id)),
        )


def create_user_grant(conn: sqlite3.Connection, user_id: int, scope: str, value: str) -> None:
    value = normalize_rule_value(scope, value)
    user = conn.execute("SELECT role FROM users WHERE id=?", (int(user_id),)).fetchone()
    if not user or normalize_role(user["role"]) not in PERMISSION_ROLES or scope not in RULE_SCOPES or not value:
        raise ValueError("Invalid user permission grant")
    conn.execute(
        "INSERT OR IGNORE INTO user_permission_grants(user_id, scope, value) VALUES (?, ?, ?)",
        (int(user_id), scope, value),
    )
    conn.commit()


def delete_user_grant(conn: sqlite3.Connection, grant_id: int) -> None:
    conn.execute("DELETE FROM user_permission_grants WHERE id=?", (int(grant_id),))
    conn.commit()


def replace_files(conn: sqlite3.Connection, files: Iterable[dict]) -> int:
    rows = [
        {**row, "thumbnail_link": row.get("thumbnail_link", ""), "other": row.get("other", "")}
        for row in files
    ]
    with conn:
        conn.execute("DELETE FROM files")
        conn.executemany(
            """
            INSERT INTO files(id, name, mime_type, size, modified_time, thumbnail_link, path, sku, brand, category, other, asset_type, internal_only)
            VALUES (:id, :name, :mime_type, :size, :modified_time, :thumbnail_link, :path, :sku, :brand, :category, :other, :asset_type, :internal_only)
            """,
            rows,
        )
    return len(rows)


def search_files(
    conn: sqlite3.Connection,
    role: str,
    q: str = "",
    brand: str = "",
    category: str = "",
    other: str = "",
    asset_type: str = "",
    limit: int = 200,
    offset: int = 0,
    user_id: int | None = None,
) -> list[sqlite3.Row]:
    role = normalize_role(role)
    where = []
    args: list[object] = []
    if q:
        like = f"%{q}%"
        where.append(
            "(f.sku LIKE ? OR f.name LIKE ? OR f.path LIKE ? OR m.english_name LIKE ? "
            "OR m.chinese_name LIKE ? OR m.category LIKE ? OR m.category_zh LIKE ?)"
        )
        args.extend([like] * 7)
    if brand:
        where.append("f.brand = ?")
        args.append(brand)
    if category:
        where.append("COALESCE(NULLIF(m.category, ''), f.category) = ?")
        args.append(category)
    if other:
        where.append("f.other = ?")
        args.append(other)
    if asset_type:
        where.append("f.asset_type = ?")
        args.append(asset_type)
    clause = "WHERE " + " AND ".join(where) if where else ""
    rows = conn.execute(
        f"""
        SELECT f.*, COALESCE(NULLIF(m.category, ''), f.category) AS display_category,
               COALESCE(m.category_id, '') AS category_id,
               COALESCE(
                 c.group_name,
                 CASE
                   WHEN COALESCE(m.category_id, '') LIKE 'HC_%' THEN 'Golf Headcover'
                   WHEN COALESCE(m.category_id, '') LIKE 'ACC_%' THEN 'Golf Accessories'
                   ELSE ''
                 END
               ) AS category_group,
               COALESCE(m.category_zh, '') AS category_zh,
               COALESCE(m.category_tags, '') AS category_tags,
               COALESCE(m.category_status, 'unclassified') AS category_status,
               COALESCE(m.english_name, '') AS english_name,
               COALESCE(m.chinese_name, '') AS chinese_name,
               COALESCE(m.owner, '') AS owner,
               COALESCE(m.set_code, '') AS set_code,
               COALESCE(m.themes, '') AS themes,
               COALESCE(m.cover_file_id, '') AS cover_file_id
        FROM files f
        LEFT JOIN sku_meta m ON m.sku = f.sku
        LEFT JOIN custom_product_categories c ON c.id = m.category_id
        {clause}
        ORDER BY f.sku, f.asset_type, f.name
        """,
        args,
    ).fetchall()
    rules = role_rules(conn, role)
    grants = user_grants(conn, user_id)
    permission_mode = user_permission_mode(conn, user_id)
    visible = []
    for row in rows:
        permission_row = dict(row)
        permission_row["category"] = row["display_category"]
        if can_user_see(role, bool(row["internal_only"]), permission_row, rules, grants, permission_mode):
            visible.append(row)
    return visible[offset : offset + limit]


def get_file(conn: sqlite3.Connection, file_id: str, role: str, user_id: int | None = None) -> sqlite3.Row | None:
    role = normalize_role(role)
    row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    rules = role_rules(conn, role)
    grants = user_grants(conn, user_id)
    permission_mode = user_permission_mode(conn, user_id)
    return row if row and can_user_see(role, bool(row["internal_only"]), row, rules, grants, permission_mode) else None


def sku_files(conn: sqlite3.Connection, sku: str, role: str, user_id: int | None = None) -> list[sqlite3.Row]:
    role = normalize_role(role)
    rows = conn.execute(
        """
        SELECT f.*, COALESCE(NULLIF(m.category, ''), f.category) AS display_category,
               COALESCE(m.category_id, '') AS category_id,
               COALESCE(
                 c.group_name,
                 CASE
                   WHEN COALESCE(m.category_id, '') LIKE 'HC_%' THEN 'Golf Headcover'
                   WHEN COALESCE(m.category_id, '') LIKE 'ACC_%' THEN 'Golf Accessories'
                   ELSE ''
                 END
               ) AS category_group,
               COALESCE(m.category_zh, '') AS category_zh,
               COALESCE(m.category_tags, '') AS category_tags,
               COALESCE(m.category_status, 'unclassified') AS category_status,
               COALESCE(m.english_name, '') AS english_name,
               COALESCE(m.chinese_name, '') AS chinese_name,
               COALESCE(m.owner, '') AS owner,
               COALESCE(m.set_code, '') AS set_code,
               COALESCE(m.themes, '') AS themes,
               COALESCE(m.cover_file_id, '') AS cover_file_id
        FROM files f
        LEFT JOIN sku_meta m ON m.sku = f.sku
        LEFT JOIN custom_product_categories c ON c.id = m.category_id
        WHERE f.sku = ?
        ORDER BY f.asset_type, f.name
        """,
        (sku,),
    ).fetchall()
    rules = role_rules(conn, role)
    grants = user_grants(conn, user_id)
    permission_mode = user_permission_mode(conn, user_id)
    visible = []
    for row in rows:
        permission_row = dict(row)
        permission_row["category"] = row["display_category"]
        if can_user_see(role, bool(row["internal_only"]), permission_row, rules, grants, permission_mode):
            visible.append(row)
    return visible


def set_product_cover(conn: sqlite3.Connection, sku: str, file_id: str) -> sqlite3.Row:
    sku = sku.strip().upper()
    row = conn.execute(
        "SELECT id, sku, mime_type FROM files WHERE id = ? AND sku = ?",
        (file_id, sku),
    ).fetchone()
    if not row:
        raise ValueError("The selected image does not belong to this product")
    if not (row["mime_type"] or "").startswith("image/"):
        raise ValueError("Only an image can be used as the product cover")
    with conn:
        conn.execute(
            """
            INSERT INTO sku_meta(sku, cover_file_id) VALUES (?, ?)
            ON CONFLICT(sku) DO UPDATE SET cover_file_id=excluded.cover_file_id
            """,
            (sku, file_id),
        )
    return row


def import_meta_csv(
    conn: sqlite3.Connection,
    content: str,
    overwrite: bool = True,
    preserve_existing_metadata: bool = False,
) -> int:
    reader = csv.DictReader(content.splitlines())
    required = {"sku", "english_name", "owner"}
    if not reader.fieldnames or not required.issubset({h.strip() for h in reader.fieldnames}):
        raise ValueError("CSV must include sku, english_name, owner")
    rows = []
    for row in reader:
        sku = (row.get("sku") or "").strip().upper()
        if sku:
            rows.append((sku, row.get("english_name", "").strip(), row.get("owner", "").strip(), row.get("notes", "").strip()))
    with conn:
        if overwrite and preserve_existing_metadata:
            conflict = "UPDATE SET english_name=excluded.english_name"
        elif overwrite:
            conflict = "UPDATE SET english_name=excluded.english_name, owner=excluded.owner, notes=excluded.notes"
        else:
            conflict = "NOTHING"
        conn.executemany(
            f"""
            INSERT INTO sku_meta(sku, english_name, owner, notes)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(sku) DO {conflict}
            """,
            rows,
        )
    return len(rows)


def import_product_catalog_csv(conn: sqlite3.Connection, content: str) -> int:
    reader = csv.DictReader(content.splitlines())
    required = {"sku", "english_name", "set_code"}
    if not reader.fieldnames or not required.issubset({header.strip() for header in reader.fieldnames}):
        raise ValueError("Product catalog CSV is missing required columns")
    rows = []
    for row in reader:
        sku = (row.get("sku") or "").strip().upper()
        if not sku:
            continue
        rows.append(
            (
                sku,
                (row.get("english_name") or "").strip(),
                (row.get("chinese_name") or "").strip(),
                (row.get("brand") or "").strip(),
                (row.get("category") or "").strip(),
                normalize_set_code(row.get("set_code") or ""),
                (row.get("source_sheet") or "").strip(),
            )
        )
    with conn:
        conn.executemany(
            """
            INSERT INTO sku_meta(
              sku, english_name, chinese_name, brand, category, set_code, source_sheet
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(sku) DO UPDATE SET
              english_name=CASE WHEN excluded.english_name <> '' THEN excluded.english_name ELSE sku_meta.english_name END,
              chinese_name=CASE WHEN excluded.chinese_name <> '' THEN excluded.chinese_name ELSE sku_meta.chinese_name END,
              brand=CASE WHEN excluded.brand <> '' THEN excluded.brand ELSE sku_meta.brand END,
              category=CASE
                WHEN sku_meta.category_id <> '' AND sku_meta.category_id <> 'UNKNOWN'
                  THEN sku_meta.category
                WHEN excluded.category <> '' THEN excluded.category
                ELSE sku_meta.category
              END,
              set_code=excluded.set_code,
              source_sheet=excluded.source_sheet
            """,
            rows,
        )
    return len(rows)


PRODUCT_METADATA_CTE = """
WITH catalog_skus AS (
  SELECT sku FROM sku_meta
  UNION
  SELECT DISTINCT sku FROM files WHERE sku <> ''
), product_data AS (
  SELECT
    catalog_skus.sku,
    COALESCE(m.english_name, '') AS english_name,
    COALESCE(m.chinese_name, '') AS chinese_name,
    COALESCE(NULLIF(m.brand, ''), MIN(f.brand), '') AS brand,
    COALESCE(NULLIF(m.category, ''), MIN(f.category), '') AS category,
    COALESCE(m.category_id, '') AS category_id,
    COALESCE(m.category_zh, '') AS category_zh,
    COALESCE(m.category_tags, '') AS category_tags,
    COALESCE(m.category_confidence, 0) AS category_confidence,
    COALESCE(m.category_source, '') AS category_source,
    COALESCE(m.category_status, 'unclassified') AS category_status,
    COALESCE(m.category_reason, '') AS category_reason,
    COALESCE(m.taxonomy_version, '') AS taxonomy_version,
    COALESCE(m.set_code, '') AS set_code,
    COALESCE(m.themes, '') AS themes,
    COUNT(f.id) AS file_count,
    COALESCE(MAX(f.modified_time), '') AS modified_time
  FROM catalog_skus
  LEFT JOIN sku_meta m ON m.sku = catalog_skus.sku
  LEFT JOIN files f ON f.sku = catalog_skus.sku
  GROUP BY catalog_skus.sku, m.english_name, m.chinese_name, m.brand, m.category,
           m.category_id, m.category_zh, m.category_tags, m.category_confidence,
           m.category_source, m.category_status, m.category_reason, m.taxonomy_version,
           m.set_code, m.themes
)
"""


def _product_metadata_filter(q: str) -> tuple[str, list[str]]:
    q = q.strip()
    if not q:
        return "", []
    like = f"%{q}%"
    return (
        "WHERE sku LIKE ? OR english_name LIKE ? OR chinese_name LIKE ? OR brand LIKE ? "
        "OR category LIKE ? OR category_zh LIKE ? OR category_id LIKE ? "
        "OR set_code LIKE ? OR themes LIKE ?",
        [like] * 9,
    )


def list_product_metadata(
    conn: sqlite3.Connection,
    q: str = "",
    page: int = 1,
    page_size: int = 40,
) -> dict[str, object]:
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    clause, args = _product_metadata_filter(q)
    total = conn.execute(f"{PRODUCT_METADATA_CTE} SELECT COUNT(*) FROM product_data {clause}", args).fetchone()[0]
    rows = conn.execute(
        f"""
        {PRODUCT_METADATA_CTE}
        SELECT * FROM product_data
        {clause}
        ORDER BY CASE WHEN set_code <> '' THEN 0 ELSE 1 END, set_code, sku
        LIMIT ? OFFSET ?
        """,
        [*args, page_size, (page - 1) * page_size],
    ).fetchall()
    set_codes = [row[0] for row in conn.execute("SELECT DISTINCT set_code FROM sku_meta WHERE set_code <> '' ORDER BY set_code").fetchall()]
    return {
        "products": [dict(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "set_codes": set_codes,
        "category_options": product_taxonomy.category_options(conn),
        "category_tag_options": product_taxonomy.tag_options(),
        "theme_options": product_taxonomy.theme_options(conn),
    }


def matching_product_skus(conn: sqlite3.Connection, q: str = "") -> list[str]:
    clause, args = _product_metadata_filter(q)
    return [
        row[0]
        for row in conn.execute(
            f"{PRODUCT_METADATA_CTE} SELECT sku FROM product_data {clause} ORDER BY sku",
            args,
        ).fetchall()
    ]


def save_category_decision(
    conn: sqlite3.Connection,
    *,
    sku: str,
    category_id: str,
    category_tags: str = "",
    reviewer_id: int | None = None,
    source: str = "human_correction",
    note: str = "",
    import_id: int | None = None,
    previous_category_id: str | None = None,
    previous_tags: str | None = None,
) -> int:
    sku = sku.strip().upper()
    if not sku:
        raise ValueError("SKU 不能为空")
    category_id = product_taxonomy.validate_category_id(category_id, conn)
    category_tags = product_taxonomy.normalize_tags(category_tags)
    details = product_taxonomy.category_details(category_id, conn)
    current = conn.execute(
        "SELECT category_id, category_tags FROM sku_meta WHERE sku=?",
        (sku,),
    ).fetchone()
    old_category_id = previous_category_id if previous_category_id is not None else (
        current["category_id"] if current else ""
    )
    old_tags = previous_tags if previous_tags is not None else (
        current["category_tags"] if current else ""
    )
    conn.execute(
        """
        INSERT INTO sku_meta(
          sku, category, category_id, category_zh, category_tags, category_confidence,
          category_source, category_status, category_reason, taxonomy_version,
          category_updated_at
        ) VALUES (?, ?, ?, ?, ?, 1, ?, 'verified', ?, ?, CURRENT_TIMESTAMP)
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
        """,
        (
            sku,
            details["label_en"],
            category_id,
            details["label_zh"],
            category_tags,
            source,
            note,
            product_taxonomy.taxonomy_document()["version"],
        ),
    )
    cursor = conn.execute(
        """
        INSERT INTO category_correction_events(
          sku, import_id, event_type, previous_category_id, final_category_id,
          previous_tags, final_tags, source, reviewer_id, note, taxonomy_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            sku,
            import_id,
            "approved" if old_category_id == category_id and old_tags == category_tags else "corrected",
            old_category_id or "",
            category_id,
            old_tags or "",
            category_tags,
            source,
            reviewer_id,
            note,
            product_taxonomy.taxonomy_document()["version"],
        ),
    )
    return int(cursor.lastrowid)


def list_category_corrections(conn: sqlite3.Connection, limit: int = 500) -> list[dict]:
    rows = conn.execute(
        """
        SELECT events.*, COALESCE(NULLIF(users.name, ''), users.email, 'System') AS editor
        FROM category_correction_events events
        LEFT JOIN users ON users.id=events.reviewer_id
        ORDER BY events.created_at DESC, events.id DESC
        LIMIT ?
        """,
        (max(1, min(limit, 1000)),),
    ).fetchall()
    result = []
    for row in rows:
        before = product_taxonomy.category_details(row["previous_category_id"], conn)["label_zh"] if row["previous_category_id"] else "未分类"
        after = product_taxonomy.category_details(row["final_category_id"], conn)["label_zh"]
        result.append(
            {
                "id": 1_000_000_000 + int(row["id"]),
                "source_name": f"SKU {row['sku']}",
                "rel_path": "",
                "field": "product_category",
                "suggested_value": "",
                "previous_value": before,
                "new_value": after,
                "editor": row["editor"],
                "created_at": row["created_at"],
            }
        )
    return result


def update_product_metadata(
    conn: sqlite3.Connection,
    skus: Iterable[str],
    *,
    set_code: str = "",
    category_id: str = "",
    category_tags: str = "",
    themes: str = "",
    update_set: bool = False,
    update_category: bool = False,
    update_themes: bool = False,
    reviewer_id: int | None = None,
    note: str = "",
) -> int:
    normalized_skus = sorted({sku.strip().upper() for sku in skus if sku.strip()})
    if not normalized_skus or not (update_set or update_category or update_themes):
        return 0
    assignments = []
    values: list[str] = []
    if update_set:
        assignments.append("set_code=?")
        values.append(normalize_set_code(set_code))
    if update_themes:
        assignments.append("themes=?")
        values.append(product_taxonomy.normalize_themes(themes, conn))
    normalized_category_id = ""
    normalized_category_tags = ""
    category_tags_provided = bool(category_tags.strip())
    if update_category:
        normalized_category_id = product_taxonomy.validate_category_id(category_id, conn)
        normalized_category_tags = product_taxonomy.normalize_tags(category_tags)
    with conn:
        conn.executemany("INSERT INTO sku_meta(sku) VALUES (?) ON CONFLICT(sku) DO NOTHING", [(sku,) for sku in normalized_skus])
        if assignments:
            placeholders = ",".join("?" for _ in normalized_skus)
            conn.execute(
                f"UPDATE sku_meta SET {', '.join(assignments)} WHERE sku IN ({placeholders})",
                [*values, *normalized_skus],
            )
        if update_category:
            for sku in normalized_skus:
                existing = conn.execute(
                    "SELECT category_tags FROM sku_meta WHERE sku=?",
                    (sku,),
                ).fetchone()
                save_category_decision(
                    conn,
                    sku=sku,
                    category_id=normalized_category_id,
                    category_tags=(
                        normalized_category_tags
                        if category_tags_provided
                        else (existing["category_tags"] if existing else "")
                    ),
                    reviewer_id=reviewer_id,
                    source="human_correction",
                    note=note or "管理员在数据列表中确认产品分类",
                )
    return len(normalized_skus)


def facets(conn: sqlite3.Connection, role: str, user_id: int | None = None) -> dict[str, object]:
    file_count = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    rows = search_files(conn, role, limit=file_count, user_id=user_id)
    categories_by_brand: dict[str, set[str]] = {}
    for row in rows:
        category = row["display_category"]
        if row["brand"] and category:
            categories_by_brand.setdefault(row["brand"], set()).add(category)
    return {
        "brands": sorted({r["brand"] for r in rows if r["brand"]}),
        "categories": sorted({r["display_category"] for r in rows if r["display_category"]}),
        "categories_by_brand": {
            brand: sorted(categories) for brand, categories in sorted(categories_by_brand.items())
        },
        "others": sorted({r["other"] for r in rows if r["other"]}),
        "asset_types": sorted({r["asset_type"] for r in rows if r["asset_type"]}),
    }


def permission_rule_values(conn: sqlite3.Connection) -> dict[str, list[str]]:
    values = {
        scope: [row[0] for row in conn.execute(
            f"SELECT DISTINCT {scope} FROM files WHERE {scope} <> '' ORDER BY {scope}"
        )]
        for scope in ("brand", "other", "asset_type", "sku")
    }
    has_no_brand = conn.execute(
        """
        SELECT 1
        FROM files
        WHERE TRIM(COALESCE(brand, '')) = ''
          AND LOWER(TRIM(COALESCE(other, ''))) = 'no brand'
        LIMIT 1
        """
    ).fetchone()
    if has_no_brand and "No Brand" not in values["brand"]:
        values["brand"].append("No Brand")
    values["category"] = [
        row[0]
        for row in conn.execute(
            """
            SELECT DISTINCT COALESCE(NULLIF(meta.category, ''), files.category) AS category
            FROM files
            LEFT JOIN sku_meta meta ON meta.sku=files.sku
            WHERE COALESCE(NULLIF(meta.category, ''), files.category) <> ''
            ORDER BY category
            """
        )
    ]
    return values
