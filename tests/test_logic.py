import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from fastapi import HTTPException

from app import db, drive, main
from app.logic import FOLDER_MIME, OTHER_COLLECTIONS, classify_asset, display_folder_name, infer_brand_category_sku, infer_drive_fields, is_ignored_file, is_included_drive_collection, is_internal_path
from app.main import active_import_notification_count, build_zip_cache, english_name_from_path, other_asset_name_from_path, parse_range_header, product_cards, safe_cache_name, seconds_until_drive_sync, seconds_until_nas_scan, zip_cache_digest


class LogicTest(unittest.TestCase):
    def test_scheduled_drive_sync_notifies_recipient_after_success(self):
        with patch.object(main, "run_sync", return_value=48190), patch.object(
            main, "count_products_missing_english_names", return_value=171
        ), patch.object(main, "send_drive_sync_notification") as notify:
            result = main.run_scheduled_drive_sync_once()

        self.assertEqual(result, 48190)
        notify.assert_called_once_with(file_count=48190, missing_english_name_count=171)

    def test_scheduled_drive_sync_notifies_recipient_after_failure(self):
        error = RuntimeError("Drive API timeout")
        with patch.object(main, "run_sync", side_effect=error), patch.object(
            main, "send_drive_sync_notification"
        ) as notify:
            result = main.run_scheduled_drive_sync_once()

        self.assertIsNone(result)
        notify.assert_called_once_with(error=error)

    def test_drive_sync_notification_uses_configured_dingtalk_recipient(self):
        sent = {}

        def fake_send(user_ids, content, client_id, client_secret, agent_id):
            sent.update(
                {
                    "user_ids": user_ids,
                    "content": content,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "agent_id": agent_id,
                }
            )
            return {"task_id": "123", "recipient_count": len(user_ids)}

        with patch.dict(
            "os.environ",
            {
                "DINGTALK_SYNC_RECIPIENT_USER_IDS": "user-a, user-a;user-b",
                "DINGTALK_CLIENT_ID": "client-id",
                "DINGTALK_CLIENT_SECRET": "client-secret",
                "DINGTALK_AGENT_ID": "1001",
            },
        ), patch.object(main.dingtalk_auth, "send_work_notification", side_effect=fake_send):
            result = main.send_drive_sync_notification(
                file_count=12,
                missing_english_name_count=3,
            )

        self.assertEqual(sent["user_ids"], ["user-a", "user-b"])
        self.assertIn("已索引文件：12", sent["content"])
        self.assertIn("缺少英文品名的 SKU：3", sent["content"])
        self.assertEqual(result, {"task_id": "123", "recipient_count": 2})

    def test_super_admin_schema_migration_preserves_existing_user_foreign_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / "test.db")
            conn.executescript(
                """
                CREATE TABLE users (
                  id INTEGER PRIMARY KEY,
                  email TEXT UNIQUE NOT NULL,
                  name TEXT NOT NULL,
                  role TEXT NOT NULL CHECK(role IN ('admin','internal_staff','overseas_customer','domestic_customer','service_provider')),
                  password_hash TEXT NOT NULL,
                  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE user_refs (
                  id INTEGER PRIMARY KEY,
                  user_id INTEGER NOT NULL REFERENCES users(id)
                );
                """
            )
            conn.execute(
                "INSERT INTO users(id, email, name, role, password_hash) VALUES (7, 'admin@example.com', 'Admin', 'admin', ?)",
                (db.hash_password("legacy-test-password"),),
            )
            conn.execute("INSERT INTO user_refs(id, user_id) VALUES (1, 7)")
            conn.commit()

            db.init_db(conn)

            self.assertEqual(conn.execute("SELECT role FROM users WHERE id=7").fetchone()["role"], "super_admin")
            self.assertEqual(conn.execute("SELECT user_id FROM user_refs WHERE id=1").fetchone()["user_id"], 7)
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            conn.close()

    def test_super_admin_owns_access_control_and_seeded_admin_is_promoted(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / "test.db")
            db.init_db(conn)
            seeded = conn.execute("SELECT * FROM users ORDER BY id LIMIT 1").fetchone()

            self.assertEqual(seeded["role"], "super_admin")
            self.assertTrue(main.user_payload(seeded)["is_admin"])
            self.assertTrue(main.user_payload(seeded)["is_super_admin"])
            self.assertEqual(main.require_api_admin({"role": "admin"})["role"], "admin")
            with self.assertRaises(HTTPException) as denied:
                main.require_api_super_admin({"role": "admin"})
            self.assertEqual(denied.exception.status_code, 403)
            self.assertEqual(main.require_api_super_admin({"role": "super_admin"})["role"], "super_admin")
            conn.close()

    def test_individual_customer_brand_grant_overrides_only_matching_role_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / "test.db")
            db.init_db(conn)
            db.replace_files(
                conn,
                [
                    {
                        "id": "brand-a",
                        "name": "a.jpg",
                        "mime_type": "image/jpeg",
                        "size": 1,
                        "modified_time": "",
                        "path": "Brand A/Category/SKU-A/a.jpg",
                        "sku": "SKU-A",
                        "brand": "Brand A",
                        "category": "Category",
                        "asset_type": "image",
                        "internal_only": 0,
                    },
                    {
                        "id": "brand-b",
                        "name": "b.jpg",
                        "mime_type": "image/jpeg",
                        "size": 1,
                        "modified_time": "",
                        "path": "Brand B/Category/SKU-B/b.jpg",
                        "sku": "SKU-B",
                        "brand": "Brand B",
                        "category": "Category",
                        "asset_type": "image",
                        "internal_only": 0,
                    },
                ],
            )
            db.create_user(conn, "allowed@example.com", "Allowed", "overseas_customer", "password1")
            db.create_user(conn, "blocked@example.com", "Blocked", "overseas_customer", "password1")
            allowed_id = conn.execute("SELECT id FROM users WHERE email='allowed@example.com'").fetchone()["id"]
            blocked_id = conn.execute("SELECT id FROM users WHERE email='blocked@example.com'").fetchone()["id"]
            db.create_role_rule(conn, "overseas_customer", "brand", "Brand A")

            self.assertEqual(
                [row["id"] for row in db.search_files(conn, "overseas_customer", user_id=allowed_id)],
                ["brand-b"],
            )
            db.create_user_grant(conn, allowed_id, "brand", "Brand A")
            self.assertEqual(
                [row["id"] for row in db.search_files(conn, "overseas_customer", user_id=allowed_id)],
                ["brand-a", "brand-b"],
            )
            self.assertEqual(
                [row["id"] for row in db.search_files(conn, "overseas_customer", user_id=blocked_id)],
                ["brand-b"],
            )
            conn.close()

    def test_role_hidden_other_collection_cannot_be_reopened_by_account_grant(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / "test.db")
            db.init_db(conn)
            db.replace_files(
                conn,
                [
                    {
                        "id": "show",
                        "name": "show.jpg",
                        "mime_type": "image/jpeg",
                        "size": 1,
                        "modified_time": "",
                        "path": "06 Show & Exhibitions/2026/show.jpg",
                        "sku": "",
                        "brand": "",
                        "category": "",
                        "other": "Show & Exhibitions",
                        "asset_type": "image",
                        "internal_only": 0,
                    },
                    {
                        "id": "catalog",
                        "name": "catalog.pdf",
                        "mime_type": "application/pdf",
                        "size": 1,
                        "modified_time": "",
                        "path": "01 Product Catalogs/2026/catalog.pdf",
                        "sku": "",
                        "brand": "",
                        "category": "",
                        "other": "Product Catalogs",
                        "asset_type": "other",
                        "internal_only": 0,
                    },
                ],
            )
            user = db.create_customer_user_with_permissions(
                conn,
                "collections@example.com",
                "Collections Buyer",
                "overseas_customer",
                "password1",
                permission_mode="allowlist",
                grants=[("other", "Show & Exhibitions"), ("other", "Product Catalogs")],
            )
            db.create_role_rule(conn, "overseas_customer", "other", "Show & Exhibitions")

            self.assertEqual(
                [row["id"] for row in db.search_files(conn, "overseas_customer", user_id=int(user["id"]))],
                ["catalog"],
            )
            conn.close()

    def test_no_brand_is_a_brand_permission_option_and_matches_unbranded_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / "test.db")
            try:
                db.init_db(conn)
                db.replace_files(
                    conn,
                    [
                    {
                        "id": "no-brand-1",
                        "name": "no-brand.jpg",
                        "mime_type": "image/jpeg",
                        "size": 1,
                        "modified_time": "",
                        "path": "04 Product Images (No Brand)/01 Headcover Set/6017001/no-brand.jpg",
                        "sku": "6017001",
                        "brand": "",
                        "category": "Headcover Set",
                        "other": "No Brand",
                        "asset_type": "image",
                        "internal_only": 0,
                    },
                    {
                        "id": "brand-1",
                        "name": "brand.jpg",
                        "mime_type": "image/jpeg",
                        "size": 1,
                        "modified_time": "",
                        "path": "04 Product Images/01 Craftsman Golf/01 Headcover Set/6017002/brand.jpg",
                        "sku": "6017002",
                        "brand": "01 Craftsman Golf",
                        "category": "Headcover Set",
                        "other": "",
                        "asset_type": "image",
                        "internal_only": 0,
                    },
                    ],
                )
                db.create_user(conn, "no-brand@example.com", "No Brand Buyer", "overseas_customer", "password1")
                user_id = conn.execute("SELECT id FROM users WHERE email='no-brand@example.com'").fetchone()["id"]

                self.assertIn("No Brand", db.permission_rule_values(conn)["brand"])
                # Legacy databases stored the No Brand hiding rule under the
                # ``other`` scope, while the customer UI grants it as a brand.
                conn.execute(
                    "INSERT INTO role_permission_rules(role, scope, value) VALUES (?, ?, ?)",
                    ("overseas_customer", "other", "No Brand"),
                )
                conn.commit()
                self.assertEqual(
                    [row["id"] for row in db.search_files(conn, "overseas_customer", user_id=user_id)],
                    ["brand-1"],
                )
                db.create_user_grant(conn, user_id, "brand", "No Brand")
                self.assertEqual(
                    [row["id"] for row in db.search_files(conn, "overseas_customer", user_id=user_id)],
                    ["no-brand-1", "brand-1"],
                )
            finally:
                conn.close()

    def test_drive_service_cache_is_thread_local_and_reusable(self):
        old_sessions = getattr(drive._SESSION_CACHE, "sessions", None)
        if hasattr(drive._SESSION_CACHE, "sessions"):
            del drive._SESSION_CACHE.sessions
        try:
            sessions = drive._thread_sessions()
            marker = object()
            sessions[("readonly",)] = marker
            self.assertIs(drive._thread_sessions()[("readonly",)], marker)
            self.assertIs(sessions, drive._thread_sessions())
        finally:
            if old_sessions is None:
                if hasattr(drive._SESSION_CACHE, "sessions"):
                    del drive._SESSION_CACHE.sessions
            else:
                drive._SESSION_CACHE.sessions = old_sessions

    def test_admin_folder_resolution_can_fall_back_to_deepest_existing_parent(self):
        old_find_child = main.drive.find_child
        tree = {
            ("root", "04 Product Images"): {"id": "products"},
            ("products", "01 Craftsman Golf"): {"id": "brand"},
        }
        main.drive.find_child = lambda _svc, parent_id, name, folder=True: tree.get((parent_id, name))
        try:
            folder_id, path = main.resolve_admin_drive_folder(
                None,
                "root",
                "04 Product Images/01 Craftsman Golf/Missing AI Folder",
                allow_missing=True,
            )
        finally:
            main.drive.find_child = old_find_child

        self.assertEqual(folder_id, "brand")
        self.assertEqual(path, "04 Product Images/01 Craftsman Golf")

    def test_filter_labels_hide_sort_prefix_and_categories_follow_brand(self):
        self.assertEqual(display_folder_name("01 Craftsman Golf"), "Craftsman Golf")
        self.assertEqual(display_folder_name("02_Putter Covers"), "Putter Covers")
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / "test.db")
            db.init_db(conn)
            db.replace_files(
                conn,
                [
                    {
                        "id": str(index),
                        "name": f"{index}.jpg",
                        "mime_type": "image/jpeg",
                        "size": 1,
                        "modified_time": "",
                        "thumbnail_link": "",
                        "path": f"{brand}/{category}/SKU-{index}/{index}.jpg",
                        "sku": f"SKU-{index}",
                        "brand": brand,
                        "category": category,
                        "other": "",
                        "asset_type": "image",
                        "internal_only": 0,
                    }
                    for index, (brand, category) in enumerate(
                        (
                            ("01 Craftsman Golf", "01 Headcovers"),
                            ("01 Craftsman Golf", "02 Golf Bags"),
                            ("02 MyTag", "03 Plush Headcovers"),
                        ),
                        1,
                    )
                ],
            )
            options = db.facets(conn, "admin")
            self.assertEqual(
                options["categories_by_brand"]["01 Craftsman Golf"],
                ["01 Headcovers", "02 Golf Bags"],
            )
            conn.close()

        template = Path("app/templates/index.html").read_text(encoding="utf-8")
        self.assertIn("categoriesByBrand[brand.value]", template)
        self.assertIn("{{ folder_label(item) }}", template)

    def test_brand_mark_uses_uppercase_craftsman_golf(self):
        templates = "".join(
            Path(path).read_text(encoding="utf-8")
            for path in ("app/templates/base.html", "app/templates/login.html")
        )
        self.assertEqual(templates.count("CRAFTSMAN GOLF"), 2)
        self.assertNotIn(">MI<", templates)

    def test_home_thumbnails_never_fallback_to_full_original_images(self):
        template = Path("app/templates/index.html").read_text(encoding="utf-8")
        self.assertNotIn('data-full="/media/', template)
        self.assertNotIn("img.onerror", template)

    def test_thumb_route_proxies_and_reuses_cached_thumbnail(self):
        row = {
            "id": "file-1",
            "mime_type": "image/png",
            "thumbnail_link": "https://stale.example/thumb",
            "modified_time": "2026-07-14T00:00:00Z",
        }

        class FakeConnection:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def execute(self, *_args):
                return None

            def commit(self):
                return None

        old_connect = db.connect
        old_get_file = db.get_file
        old_download = drive.download_thumbnail
        old_cache_dir = main.THUMB_CACHE_DIR
        old_schedule = main.schedule_thumbnail_warm
        calls = []
        db.connect = lambda: FakeConnection()
        db.get_file = lambda _conn, _file_id, _role: row

        def fake_download(file_id, thumbnail_url=""):
            calls.append((file_id, thumbnail_url))
            output = BytesIO()
            Image.new("RGB", (32, 24), "#cc2233").save(output, format="PNG")
            return output.getvalue(), "image/png", "https://fresh.example/thumb"

        drive.download_thumbnail = fake_download
        try:
            with tempfile.TemporaryDirectory() as tmp:
                main.THUMB_CACHE_DIR = Path(tmp)
                first = main.thumb("file-1", variant="small", user={"role": "admin"})
                main.populate_thumbnail_cache(row, "small")
                second = main.thumb("file-1", variant="small", user={"role": "admin"})
                self.assertEqual(first.media_type, "image/svg+xml")
                self.assertIn(b"Preview loading", first.body)
                self.assertNotIn("location", first.headers)
                self.assertEqual(second.media_type, "image/webp")
                with Image.open(second.path) as generated:
                    self.assertEqual(generated.size, (126, 110))
        finally:
            db.connect = old_connect
            db.get_file = old_get_file
            drive.download_thumbnail = old_download
            main.THUMB_CACHE_DIR = old_cache_dir
            main.schedule_thumbnail_warm = old_schedule

        self.assertEqual(calls, [("file-1", "https://stale.example/thumb")])

    def test_thumbnail_download_refreshes_stale_google_link(self):
        class FakeResponse:
            def __init__(self, status_code, payload=None, content=b"", content_type=""):
                self.status_code = status_code
                self.ok = status_code == 200
                self._payload = payload or {}
                self.content = content
                self.headers = {"Content-Type": content_type} if content_type else {}
                self.text = ""

            def json(self):
                return self._payload

        class FakeSession:
            def __init__(self):
                self.calls = []

            def get(self, url, **_kwargs):
                self.calls.append(url)
                if url == "https://stale.example/thumb":
                    return FakeResponse(403)
                if url.startswith("https://www.googleapis.com/drive/v3/files/file-1"):
                    return FakeResponse(200, {"thumbnailLink": "https://fresh.example/thumb"})
                return FakeResponse(200, content=b"thumbnail", content_type="image/jpeg")

        session = FakeSession()
        old_service = drive.service
        drive.service = lambda: session
        try:
            content, content_type, url = drive.download_thumbnail(
                "file-1", "https://stale.example/thumb"
            )
        finally:
            drive.service = old_service

        self.assertEqual(content, b"thumbnail")
        self.assertEqual(content_type, "image/jpeg")
        self.assertEqual(url, "https://fresh.example/thumb")
        self.assertEqual(
            session.calls,
            [
                "https://stale.example/thumb",
                "https://www.googleapis.com/drive/v3/files/file-1",
                "https://fresh.example/thumb",
            ],
        )

    def test_shared_drive_scan_only_enters_included_collections(self):
        root_id = "0ACmeRj4wNpNYUk9PVA"
        folder_names = (
            "01 Product Catalogs",
            "02 Brand Assets",
            "03 Packaging Assets",
            "04 Product Images",
            "04 Product Images (No Brand)",
            "05 Influencer Assets",
            "06 Show & Exhibitions",
            "07 Event & Sponsorships",
            "08 Collection Assets",
            "09 Private Working Files",
        )
        tree = {
            root_id: [{"id": f"folder-{index}", "name": name, "mimeType": FOLDER_MIME} for index, name in enumerate(folder_names)],
        }
        for index, name in enumerate(folder_names):
            tree[f"folder-{index}"] = [
                {"id": f"file-{index}", "name": f"{index}.jpg", "mimeType": "image/jpeg", "size": "1"}
            ]
        calls = []
        old_service = drive.service
        old_list_children = drive.list_children
        drive.service = lambda: object()

        def fake_list_children(_svc, folder_id, drive_id=""):
            calls.append((folder_id, drive_id))
            yield from tree.get(folder_id, [])

        drive.list_children = fake_list_children
        try:
            rows = drive.scan_drive(root_id)
        finally:
            drive.service = old_service
            drive.list_children = old_list_children

        self.assertEqual(len(rows), 9)
        rows_by_collection = {row["path"].split("/", 1)[0]: row for row in rows}
        self.assertEqual(rows_by_collection["04 Product Images (No Brand)"]["other"], "No Brand")
        self.assertEqual(rows_by_collection["01 Product Catalogs"]["other"], "Product Catalogs")
        self.assertEqual(rows_by_collection["02 Brand Assets"]["other"], "Brand Assets")
        self.assertEqual(rows_by_collection["03 Packaging Assets"]["other"], "Packaging Assets")
        self.assertEqual(rows_by_collection["05 Influencer Assets"]["other"], "Influencer Assets")
        self.assertEqual(rows_by_collection["06 Show & Exhibitions"]["other"], "Show & Exhibitions")
        self.assertEqual(rows_by_collection["07 Event & Sponsorships"]["other"], "Event & Sponsorships")
        self.assertEqual(rows_by_collection["08 Collection Assets"]["other"], "Collection Assets")
        scanned_ids = {folder_id for folder_id, _drive_id in calls}
        self.assertNotIn("folder-9", scanned_ids)
        self.assertTrue(all(drive_id == root_id for _folder_id, drive_id in calls))

    def test_zip_build_reuses_one_drive_session(self):
        session = object()
        service_calls = []
        progress = []
        old_service = drive.service
        old_download = drive.download_file

        def fake_service():
            service_calls.append(True)
            return session

        def fake_download(file_id, **kwargs):
            self.assertIs(kwargs["svc"], session)
            yield file_id.encode()

        drive.service = fake_service
        drive.download_file = fake_download
        try:
            with tempfile.TemporaryDirectory() as tmp:
                cache_path = Path(tmp) / "sku.zip"
                build_zip_cache(
                    cache_path,
                    [{"id": "one", "path": "SKU/one.txt"}, {"id": "two", "path": "SKU/two.txt"}],
                    lambda completed, total: progress.append((completed, total)),
                )
                with zipfile.ZipFile(cache_path) as archive:
                    self.assertEqual(archive.read("SKU/one.txt"), b"one")
                    self.assertEqual(archive.read("SKU/two.txt"), b"two")
        finally:
            drive.service = old_service
            drive.download_file = old_download
        self.assertEqual(len(service_calls), 1)
        self.assertEqual(progress, [(1, 2), (2, 2)])

    def test_zip_buttons_use_background_preparation(self):
        base = Path("app/templates/base.html").read_text(encoding="utf-8")
        index = Path("app/templates/index.html").read_text(encoding="utf-8")
        sku = Path("app/templates/sku.html").read_text(encoding="utf-8")
        self.assertIn('/zip/prepare`, { method: "POST" }', base)
        self.assertIn("downloadInBackground", base)
        self.assertIn("data-zip-progress", base)
        self.assertIn("result.progress", base)
        self.assertIn('data-zip-sku="{{ product.sku }}"', index)
        self.assertIn('data-zip-sku="{{ sku }}"', sku)

    def test_pending_imports_use_non_blocking_per_file_progress(self):
        pending = Path("app/fontend/src/admin/PendingReview.tsx").read_text(encoding="utf-8")
        service = Path("app/fontend/src/admin/adminService.ts").read_text(encoding="utf-8")
        styles = Path("app/fontend/src/admin/PendingReview.css").read_text(encoding="utf-8")

        self.assertIn("loadImportJobs", pending)
        self.assertIn("ImportJobIndicator", pending)
        self.assertIn("item.progress", pending)
        self.assertIn("可以继续审核下一批", pending)
        self.assertIn("nextCompletedImportJobExpiry", pending)
        self.assertIn("dismissImportJob", pending)
        self.assertNotIn("batchImportProgress", pending)
        self.assertIn("/api/admin/import-jobs", service)
        self.assertIn(".pending-import-job-indicator:hover .pending-import-job-tooltip", styles)
        self.assertIn(".pending-import-job-dismiss", styles)

    def test_nas_scan_runs_daily_at_0500_china_time(self):
        china_time = timezone(timedelta(hours=8))
        self.assertEqual(seconds_until_nas_scan(datetime(2026, 7, 13, 4, 30, tzinfo=china_time)), 30 * 60)
        self.assertEqual(seconds_until_nas_scan(datetime(2026, 7, 13, 5, 0, tzinfo=china_time)), 0)
        self.assertEqual(seconds_until_nas_scan(datetime(2026, 7, 13, 5, 30, tzinfo=china_time)), 23.5 * 60 * 60)

    def test_drive_sync_runs_daily_at_0500_china_time(self):
        china_time = timezone(timedelta(hours=8))
        self.assertEqual(seconds_until_drive_sync(datetime(2026, 7, 13, 4, 30, tzinfo=china_time)), 30 * 60)
        self.assertEqual(seconds_until_drive_sync(datetime(2026, 7, 13, 5, 0, tzinfo=china_time)), 0)
        self.assertEqual(seconds_until_drive_sync(datetime(2026, 7, 13, 5, 30, tzinfo=china_time)), 23.5 * 60 * 60)

    def test_admin_notification_count_only_includes_materials_awaiting_confirmation(self):
        self.assertEqual(
            active_import_notification_count(
                {"pending": 2, "suggested": 3, "error": 1, "approved": 1, "uploaded": 4, "rejected": 2}
            ),
            6,
        )

    def test_system_files_are_ignored(self):
        self.assertTrue(is_ignored_file("Thumbs.db"))
        self.assertTrue(is_ignored_file("desktop.ini"))
        self.assertTrue(is_ignored_file(".DS_Store"))
        self.assertTrue(is_ignored_file("._6012177.jpg"))
        self.assertFalse(is_ignored_file("6012177 (1).jpg"))

        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / "test.db")
            db.init_db(conn)
            db.replace_files(
                conn,
                [
                    {
                        "id": "junk",
                        "name": "Thumbs.db",
                        "mime_type": "application/octet-stream",
                        "size": 1,
                        "modified_time": "",
                        "path": "Brand/Type/SKU/Thumbs.db",
                        "sku": "SKU",
                        "brand": "Brand",
                        "category": "Type",
                        "asset_type": "other",
                        "internal_only": 0,
                    }
                ],
            )
            db.init_db(conn)
            self.assertIsNone(conn.execute("SELECT id FROM files WHERE id='junk'").fetchone())
            conn.close()

    def test_sku_gallery_keeps_file_details_out_of_tiles(self):
        template = Path("app/templates/sku.html").read_text(encoding="utf-8")
        self.assertNotIn("<strong>{{ file.name }}</strong>", template)
        self.assertNotIn("<small>{{ file.path }}</small>", template)
        self.assertNotIn("{{ file.asset_type }}", template)
        self.assertIn('href="/media/{{ file.id }}"', template)
        self.assertIn('href="/download/{{ file.id }}"', template)

    def test_product_card_never_uses_file_name_as_english_name(self):
        self.assertEqual(product_cards([{"sku": ""}]), [])
        product = product_cards(
            [
                {
                    "id": "1",
                    "sku": "6010174",
                    "english_name": "",
                    "name": "6010174 (1).jpg",
                    "brand": "01 Craftsman Golf",
                    "category": "03 Plush Headcover",
                    "owner": "",
                    "mime_type": "image/jpeg",
                    "asset_type": "image",
                    "internal_only": 0,
                    "path": "01 Craftsman Golf/03 Plush Headcover/6010174/6010174 (1).jpg",
                }
            ]
        )[0]
        self.assertEqual(product["name"], "English name not set")
        self.assertNotIn("latest_path", product)

    def test_product_card_uses_canonical_drive_folder_english_name(self):
        self.assertEqual(
            english_name_from_path(
                "01 Craftsman Golf/03 Plush Headcover/6010174 CF-Happy Gilmore 1 Plush Driver Cover/6010174 (1).png",
                "6010174",
            ),
            "Happy Gilmore 1 Plush Driver Cover",
        )
        self.assertEqual(
            english_name_from_path("产品图片/MyTag/6016400 黄色小鸭/1.jpg", "6016400"),
            "",
        )

    def test_product_card_counts_kol_ucg_images_and_videos_as_one_asset_type(self):
        base = {
            "sku": "6010001",
            "english_name": "Campaign Driver Cover",
            "brand": "Craftsman Golf",
            "category": "Driver Covers",
            "other": "",
            "owner": "",
            "asset_type": "kol_ugc",
            "internal_only": 0,
            "modified_time": "",
        }
        product = product_cards(
            [
                {
                    **base,
                    "id": "kol-image",
                    "name": "customer.jpg",
                    "mime_type": "image/jpeg",
                    "path": "04 Product Images/Craftsman Golf/Driver Covers/6010001/KOL & UCG/customer.jpg",
                },
                {
                    **base,
                    "id": "kol-video",
                    "name": "influencer.mp4",
                    "mime_type": "video/mp4",
                    "path": "04 Product Images/Craftsman Golf/Driver Covers/6010001/KOL & UCG/influencer.mp4",
                },
            ]
        )[0]
        self.assertEqual(product["asset_types"], ["kol_ugc"])
        self.assertEqual(product["kol_count"], 2)
        self.assertEqual(product["image_count"], 1)
        self.assertEqual(product["video_count"], 1)
        self.assertEqual(product["other_count"], 0)

    def test_admin_row_loads_inspector_without_full_page_navigation(self):
        template = Path("app/templates/admin.html").read_text(encoding="utf-8")
        self.assertIn("data-bulk-inspector", template)
        self.assertIn("const openRow = async (row)", template)
        self.assertIn("void openRow(row);", template)
        self.assertIn('id="permission-rule-select"', template)
        self.assertIn('id="permission-rule-input"', template)
        self.assertNotIn("路径包含", template)
        self.assertNotIn('"sku": permission_', Path("app/main.py").read_text(encoding="utf-8"))
        self.assertIn("修改日志", template)
        self.assertIn("入库记录", template)
        self.assertIn("nas_import_edit_logs", Path("app/db.py").read_text(encoding="utf-8"))
        self.assertNotIn("window.location.href = row.dataset.href", template)

    def test_parse_range_header(self):
        self.assertEqual(parse_range_header("bytes=0-99", 1000), (0, 99))
        self.assertEqual(parse_range_header("bytes=100-", 1000), (100, 999))
        self.assertEqual(parse_range_header("bytes=-200", 1000), (800, 999))
        self.assertIsNone(parse_range_header("bytes=1000-1200", 1000))

    def test_zip_cache_digest_changes_by_role_and_file_state(self):
        files = [{"id": "1", "size": 10, "modified_time": "t1", "path": "Brand/Cat/SKU/a.jpg"}]
        same = zip_cache_digest("sku", "admin", files)
        self.assertEqual(same, zip_cache_digest("SKU", "admin", files))
        self.assertNotEqual(same, zip_cache_digest("SKU", "overseas_customer", files))
        changed_files = [{**files[0], "modified_time": "t2"}]
        self.assertNotEqual(same, zip_cache_digest("SKU", "admin", changed_files))
        self.assertEqual(safe_cache_name("../SKU 1"), "___SKU_1")

    def test_path_rules(self):
        self.assertTrue(is_internal_path("Craftsman/_internal/SKU/a.jpg"))
        self.assertTrue(is_internal_path("Craftsman/源文件/SKU/a.psd"))
        self.assertEqual(classify_asset("Brand/Cat/SKU/KOL/a.jpg", "image/jpeg"), "image")
        self.assertEqual(
            classify_asset(
                "04 Product Images/Brand/Driver Covers/6010001/KOL & UCG/customer.jpg",
                "image/jpeg",
            ),
            "kol_ugc",
        )
        self.assertEqual(
            classify_asset(
                "06 Show & Exhibitions/2026 Thailand Golf Expo/KOL&UCG/customer.jpg",
                "image/jpeg",
            ),
            "image",
        )
        self.assertEqual(
            classify_asset(
                "12 Collection Assets/Realistic Animal Collection/6015231/KOL/UGC/customer.jpg",
                "image/jpeg",
            ),
            "image",
        )
        self.assertEqual(
            classify_asset(
                "04 Product Images/Brand/Driver Covers/6010001/KOL & UCG/influencer.mp4",
                "video/mp4",
            ),
            "kol_ugc",
        )
        self.assertEqual(
            classify_asset(
                "04 Product Images/Brand/Headcover Sets/"
                "Set00243 Pink Power Headcover Set/KOL & UCG/customer.jpg",
                "image/jpeg",
            ),
            "image",
        )
        self.assertEqual(classify_asset("Brand/Cat/SKU/Video/a.mp4", "video/mp4"), "video")
        self.assertEqual(
            classify_asset("02 Product Catalogs/Craftsman Golf Brochure 2026.pdf", "application/pdf"),
            "other",
        )
        self.assertTrue(main.is_product_asset_mime("application/pdf"))
        pdf_payload = main.api_asset_payload(
            {
                "id": "catalog-pdf",
                "name": "Craftsman Golf Brochure 2026.pdf",
                "mime_type": "application/pdf",
                "size": 1024,
                "modified_time": "2026-07-24T00:00:00Z",
                "path": "02 Product Catalogs/Craftsman Golf Brochure 2026.pdf",
                "asset_type": "other",
                "internal_only": 0,
            }
        )
        self.assertEqual(pdf_payload["kind"], "document")
        self.assertEqual(pdf_payload["thumbnail_url"], "")
        self.assertEqual(infer_brand_category_sku("Craftsman Golf/Driver Covers/abc-001/a.jpg"), ("Craftsman Golf", "Driver Covers", "ABC-001"))
        self.assertEqual(
            infer_brand_category_sku("04 Product Images/Craftsman Golf/Driver Covers/abc-001/a.jpg"),
            ("Craftsman Golf", "Driver Covers", "ABC-001"),
        )
        self.assertEqual(
            infer_brand_category_sku(
                "04 Product Images/01 Craftsman Golf/01 Headcover Set/"
                "Set00001 CF - Sunglass Gorilla Headcover Set/"
                "6011822 CF - Sunglass Gorilla Driver Cover/1.jpg"
            ),
            ("01 Craftsman Golf", "01 Headcover Set", "6011822"),
        )
        self.assertEqual(
            infer_brand_category_sku(
                "04 Product Images/01 Craftsman Golf/01 Headcover Set/"
                "Set00001 CF - Sunglass Gorilla Headcover Set/set-overview.jpg"
            ),
            ("01 Craftsman Golf", "01 Headcover Set", ""),
        )
        self.assertEqual(
            infer_brand_category_sku(
                "04 Product Images/03 Big Crazy/03 Plush Headcover/"
                "Set00061 Big Crazy - Orange Monster Headcover Set/"
                "6010430 Big Crazy - Orange Monster Driver Cover/1.jpg"
            ),
            ("03 Big Crazy", "03 Plush Headcover", "6010430"),
        )
        self.assertEqual(
            infer_drive_fields("04 Product Images/06 Manufacturing Process Video/2025112002.mp4"),
            ("06 Manufacturing Process Video", "", "", "MANUFACTURING"),
        )
        self.assertEqual(
            infer_drive_fields("04 Product Images (No Brand)/Driver Covers/6017009/a.jpg"),
            ("", "Driver Covers", "No Brand", "6017009"),
        )
        self.assertEqual(
            infer_drive_fields(
                "04 Product Images (No Brand)/08 Square Mallet Putter Cover/"
                "6008317 Spider Series Black Square Mallet Putter Cover/"
                "20220531新版本/Magnetic-closure.jpg"
            ),
            ("", "08 Square Mallet Putter Cover", "No Brand", "6008317"),
        )
        self.assertEqual(
            infer_drive_fields(
                "04 Product Images (No Brand)/03 Driver Cover/20220915新拍/6008655_01.jpg"
            ),
            ("", "03 Driver Cover", "No Brand", "6008655"),
        )
        self.assertEqual(
            infer_drive_fields(
                "04 Product Images/05 Caesar/02 Plush Headcover/"
                "20260817 Caesar - Blue Monster Plush Golf Ball Pouch/"
                "20260817 Blue Monster Plush Golf Ball Pouch (1).jpg"
            ),
            ("05 Caesar", "02 Plush Headcover", "", ""),
        )
        self.assertEqual(
            infer_drive_fields("06 Show & Exhibitions/PGA Show 2026/Photos/a.jpg"),
            ("", "", "Show & Exhibitions", "PGA SHOW 2026"),
        )
        self.assertEqual(
            infer_drive_fields("07 Event Sponsorships/Charity Cup 2026/a.jpg"),
            ("", "", "Event & Sponsorships", "CHARITY CUP 2026"),
        )
        for index, collection in enumerate(OTHER_COLLECTIONS, 1):
            self.assertEqual(
                infer_drive_fields(f"{index:02d} {collection}/Customer Folder/a.jpg"),
                ("", "", collection, "CUSTOMER FOLDER"),
            )
            self.assertTrue(is_included_drive_collection(f"{index:02d} {collection}"))
        self.assertTrue(is_included_drive_collection("04 Product Images"))
        self.assertTrue(is_included_drive_collection("07 Event Sponsorships"))
        self.assertFalse(is_included_drive_collection("05 Company Media Library"))
        self.assertFalse(is_included_drive_collection("08 Custom Cases"))

    def test_special_collections_appear_in_facets_and_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / "test.db")
            db.init_db(conn)
            rows = []
            special_collections = ("No Brand", *OTHER_COLLECTIONS)
            for index, other in enumerate(special_collections, 1):
                rows.append(
                    {
                        "id": str(index),
                        "name": f"{index}.jpg",
                        "mime_type": "image/jpeg",
                        "size": 1,
                        "modified_time": "",
                        "thumbnail_link": "",
                        "path": f"{other}/Item/{index}.jpg",
                        "sku": f"ITEM-{index}",
                        "brand": "",
                        "category": "",
                        "other": other,
                        "asset_type": "image",
                        "internal_only": 0,
                    }
                )
            db.replace_files(conn, rows)

            permission_values = db.permission_rule_values(conn)
            self.assertEqual(permission_values["sku"], [f"ITEM-{index}" for index in range(1, 9)])
            expected = sorted(special_collections)
            self.assertEqual(permission_values["other"], expected)
            self.assertEqual(db.facets(conn, "admin")["others"], expected)
            db.create_role_rule(conn, "service_provider", "other", "Show & Exhibitions")
            self.assertNotIn("Show & Exhibitions", db.facets(conn, "service_provider")["others"])
            conn.close()

    def test_legacy_event_collection_label_is_migrated(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / "test.db")
            db.init_db(conn)
            db.replace_files(
                conn,
                [
                    {
                        "id": "event-file",
                        "name": "photo.jpg",
                        "mime_type": "image/jpeg",
                        "size": 1,
                        "modified_time": "",
                        "thumbnail_link": "",
                        "path": "07 Event Sponsorships/Charity Cup/photo.jpg",
                        "sku": "CHARITY CUP",
                        "brand": "",
                        "category": "",
                        "other": "Event Sponsorships",
                        "asset_type": "image",
                        "internal_only": 0,
                    }
                ],
            )
            db.init_db(conn)
            row = conn.execute("SELECT other FROM files WHERE id='event-file'").fetchone()
            self.assertEqual(row["other"], "Event & Sponsorships")
            conn.close()

    def test_other_assets_use_the_first_customer_folder_as_the_card_name(self):
        path = "01 Product Catalogs/Spring 2027 Catalog/English/catalog.pdf"
        self.assertEqual(
            other_asset_name_from_path(path, "Product Catalogs"),
            "Spring 2027 Catalog",
        )
        product = product_cards(
            [
                {
                    "id": "catalog-file",
                    "sku": "SPRING 2027 CATALOG",
                    "english_name": "",
                    "name": "catalog.pdf",
                    "brand": "",
                    "category": "",
                    "other": "Product Catalogs",
                    "owner": "",
                    "mime_type": "application/pdf",
                    "asset_type": "other",
                    "internal_only": 0,
                    "modified_time": "",
                    "path": path,
                }
            ]
        )[0]
        self.assertEqual(product["name"], "Spring 2027 Catalog")
        self.assertEqual(product["other"], "Product Catalogs")

    def test_old_permission_table_migrates_to_other_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / "test.db")
            conn.executescript(
                """
                CREATE TABLE role_permission_rules (
                  id INTEGER PRIMARY KEY,
                  role TEXT NOT NULL,
                  scope TEXT NOT NULL CHECK(scope IN ('sku','brand','category','asset_type','path_contains')),
                  value TEXT NOT NULL,
                  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE UNIQUE INDEX idx_role_permission_rules_unique
                  ON role_permission_rules(role, scope, value);
                INSERT INTO role_permission_rules(role, scope, value)
                  VALUES ('service_provider', 'category', 'Legacy');
                """
            )
            db.init_db(conn)
            db.create_role_rule(conn, "service_provider", "other", "Show & Exhibitions")
            self.assertEqual(
                [(row["scope"], row["value"]) for row in db.list_role_rules(conn)],
                [("category", "Legacy"), ("other", "Show & Exhibitions")],
            )
            conn.close()

    def test_permissions_and_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / "test.db")
            db.init_db(conn)
            count = db.import_meta_csv(conn, "sku,english_name,owner,notes\nABC-001,Blade Cover,Amy,n\n")
            self.assertEqual(count, 1)
            db.replace_files(
                conn,
                [
                    {
                        "id": "1",
                        "name": "public.jpg",
                        "mime_type": "image/jpeg",
                        "size": 1,
                        "modified_time": "",
                        "thumbnail_link": "https://example.test/thumb.jpg",
                        "path": "Brand/Cat/ABC-001/public.jpg",
                        "sku": "ABC-001",
                        "brand": "Brand",
                        "category": "Cat",
                        "asset_type": "image",
                        "internal_only": 0,
                    },
                    {
                        "id": "2",
                        "name": "raw.psd",
                        "mime_type": "application/octet-stream",
                        "size": 1,
                        "modified_time": "",
                        "path": "Brand/Cat/ABC-001/_internal/raw.psd",
                        "sku": "ABC-001",
                        "brand": "Brand",
                        "category": "Cat",
                        "asset_type": "other",
                        "internal_only": 1,
                    },
                ],
            )
            self.assertEqual(db.get_file(conn, "1", "admin")["thumbnail_link"], "https://example.test/thumb.jpg")
            self.assertEqual(len(db.search_files(conn, "external", "ABC")), 1)
            self.assertEqual(len(db.search_files(conn, "internal", "ABC")), 2)
            self.assertEqual(len(db.search_files(conn, "service_provider", "ABC")), 1)
            self.assertEqual(len(db.search_files(conn, "admin", "ABC")), 2)
            self.assertEqual(db.sku_files(conn, "ABC-001", "admin")[0]["english_name"], "Blade Cover")
            self.assertEqual([row["id"] for row in db.search_files(conn, "admin", "ABC", limit=1, offset=1)], ["2"])

            db.create_user(conn, "customer@example.com", "Customer", "external", "pw")
            user = conn.execute("SELECT role FROM users WHERE email = ?", ("customer@example.com",)).fetchone()
            self.assertEqual(user["role"], "overseas_customer")

            db.create_role_rule(conn, "overseas_customer", "sku", "abc-001")
            self.assertEqual(len(db.search_files(conn, "overseas_customer", "ABC")), 0)
            self.assertEqual(len(db.sku_files(conn, "ABC-001", "overseas_customer")), 0)
            self.assertIsNone(db.get_file(conn, "1", "overseas_customer"))
            self.assertEqual(len(db.search_files(conn, "admin", "ABC")), 2)

            db.create_role_rule(conn, "domestic_customer", "category", "Cat")
            self.assertEqual(db.facets(conn, "domestic_customer")["categories"], [])
            with self.assertRaises(ValueError):
                db.create_role_rule(conn, "domestic_customer", "path_contains", "internal")
            conn.close()

    def test_permission_rules_filter_before_pagination(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / "test.db")
            db.init_db(conn)
            rows = []
            for index, other in enumerate(("No Brand", "", "", ""), start=1):
                rows.append(
                    {
                        "id": str(index),
                        "name": f"{index}.jpg",
                        "mime_type": "image/jpeg",
                        "size": 1,
                        "modified_time": "",
                        "path": f"Collection/{index}.jpg",
                        "sku": f"SKU-{index:03d}",
                        "brand": "Brand",
                        "category": "Category",
                        "other": other,
                        "asset_type": "image",
                        "internal_only": 0,
                    }
                )
            db.replace_files(conn, rows)
            db.create_role_rule(conn, "overseas_customer", "other", "No Brand")

            self.assertEqual(
                [row["id"] for row in db.search_files(conn, "overseas_customer", limit=2)],
                ["2", "3"],
            )
            self.assertEqual(
                [row["id"] for row in db.search_files(conn, "overseas_customer", limit=2, offset=2)],
                ["4"],
            )
            conn.close()

    def test_refresh_file_metadata_does_not_use_filename_as_category(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / "test.db")
            db.init_db(conn)
            db.replace_files(
                conn,
                [
                    {
                        "id": "video-1",
                        "name": "2025112002.mp4",
                        "mime_type": "video/mp4",
                        "size": 1,
                        "modified_time": "",
                        "path": "04 Product Images/06 Manufacturing Process Video/2025112002.mp4",
                        "sku": "MANUFACTURING",
                        "brand": "06 Manufacturing Process Video",
                        "category": "2025112002.mp4",
                        "other": "",
                        "asset_type": "video",
                        "internal_only": 0,
                    }
                ],
            )

            self.assertEqual(db.refresh_file_metadata(conn), 1)
            row = conn.execute("SELECT sku, brand, category FROM files WHERE id='video-1'").fetchone()
            self.assertEqual(dict(row), {
                "sku": "MANUFACTURING",
                "brand": "06 Manufacturing Process Video",
                "category": "",
            })
            conn.close()

    def test_refresh_file_metadata_keeps_kol_ucg_inside_product_images_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / "test.db")
            db.init_db(conn)
            rows = []
            for file_id, path, mime_type in (
                (
                    "product-kol",
                    "04 Product Images/Brand/Driver Covers/6010001/KOL & UCG/customer.jpg",
                    "image/jpeg",
                ),
                (
                    "exhibition-image",
                    "06 Show & Exhibitions/Thailand Golf Expo/KOL&UCG/customer.jpg",
                    "image/jpeg",
                ),
                (
                    "collection-video",
                    "12 Collection Assets/Animal Collection/6010002/KOL/UGC/customer.mp4",
                    "video/mp4",
                ),
            ):
                rows.append(
                    {
                        "id": file_id,
                        "name": path.rsplit("/", 1)[-1],
                        "mime_type": mime_type,
                        "size": 1,
                        "modified_time": "",
                        "path": path,
                        "sku": "STALE",
                        "brand": "",
                        "category": "",
                        "other": "",
                        "asset_type": "kol_ugc",
                        "internal_only": 0,
                    }
                )
            db.replace_files(conn, rows)

            self.assertEqual(db.refresh_file_metadata(conn), 3)
            asset_types = dict(
                conn.execute("SELECT id, asset_type FROM files ORDER BY id").fetchall()
            )
            self.assertEqual(asset_types["product-kol"], "kol_ugc")
            self.assertEqual(asset_types["exhibition-image"], "image")
            self.assertEqual(asset_types["collection-video"], "video")
            conn.close()

    def test_refresh_file_metadata_uses_child_sku_below_set_collection(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / "test.db")
            db.init_db(conn)
            db.replace_files(
                conn,
                [
                    {
                        "id": "gorilla-driver",
                        "name": "1.jpg",
                        "mime_type": "image/jpeg",
                        "size": 1,
                        "modified_time": "",
                        "path": (
                            "04 Product Images/01 Craftsman Golf/01 Headcover Set/"
                            "Set00001 CF - Sunglass Gorilla Headcover Set/"
                            "6011822 CF - Sunglass Gorilla Driver Cover/1.jpg"
                        ),
                        "sku": "SET00001",
                        "brand": "01 Craftsman Golf",
                        "category": "01 Headcover Set",
                        "other": "",
                        "asset_type": "image",
                        "internal_only": 0,
                    }
                ],
            )

            self.assertEqual(db.refresh_file_metadata(conn), 1)
            row = conn.execute(
                "SELECT sku, brand, category FROM files WHERE id='gorilla-driver'"
            ).fetchone()
            self.assertEqual(dict(row), {
                "sku": "6011822",
                "brand": "01 Craftsman Golf",
                "category": "01 Headcover Set",
            })
            conn.close()


if __name__ == "__main__":
    unittest.main()
