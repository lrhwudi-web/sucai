import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import db, drive, main
from app.logic import FOLDER_MIME


class DriveExportTest(unittest.TestCase):
    def test_drive_export_expiry_is_persisted_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / "test.db")
            db.init_db(conn)
            created_at = datetime(2026, 7, 17, 8, 30, tzinfo=timezone.utc)
            expires_at = created_at + timedelta(days=15)
            db.record_drive_export(
                conn,
                job_key="user-7:digest",
                user_id="7",
                sku="6011822",
                folder_id="export-folder",
                folder_url="https://drive.google.com/drive/folders/export-folder",
                parent_id="export-parent",
                created_at=created_at,
                expires_at=expires_at,
            )

            active = db.active_drive_export(conn, "user-7:digest", created_at + timedelta(days=14))
            self.assertEqual(active["folder_id"], "export-folder")
            self.assertEqual(active["expires_at"], "2026-08-01T08:30:00Z")
            self.assertIsNone(db.active_drive_export(conn, "user-7:digest", expires_at))
            expired = db.expired_drive_exports(conn, expires_at)
            self.assertEqual([row["folder_id"] for row in expired], ["export-folder"])

            db.mark_drive_export_deleted(conn, expired[0]["id"], expires_at)
            self.assertEqual(db.expired_drive_exports(conn, expires_at + timedelta(days=1)), [])
            conn.close()

    def test_expired_cleanup_only_deletes_generated_folder_from_expected_parent(self):
        rows = [
            {
                "id": 1,
                "folder_id": "export-folder",
                "parent_id": main.DRIVE_CLIENT_EXPORT_FOLDER_ID,
            }
        ]
        calls = []
        old_expired = db.expired_drive_exports
        old_mark_deleted = db.mark_drive_export_deleted
        old_mark_error = db.mark_drive_export_delete_error
        old_service = drive.service
        old_delete = drive.delete_export_folder
        db.expired_drive_exports = lambda _conn, _now: rows
        db.mark_drive_export_deleted = lambda _conn, export_id, deleted_at: calls.append(
            ("deleted", export_id, deleted_at)
        )
        db.mark_drive_export_delete_error = lambda _conn, export_id, error: calls.append(
            ("error", export_id, error)
        )
        drive.service = lambda scopes: calls.append(("service", scopes)) or "svc"
        drive.delete_export_folder = lambda svc, folder_id, parent_id: calls.append(
            ("delete", svc, folder_id, parent_id)
        )
        try:
            deleted = main.cleanup_expired_drive_exports(
                datetime(2026, 8, 1, 8, 30, tzinfo=timezone.utc),
                conn=object(),
            )
        finally:
            db.expired_drive_exports = old_expired
            db.mark_drive_export_deleted = old_mark_deleted
            db.mark_drive_export_delete_error = old_mark_error
            drive.service = old_service
            drive.delete_export_folder = old_delete

        self.assertEqual(deleted, 1)
        self.assertEqual(calls[0], ("service", [drive.DRIVE_WRITE_SCOPE]))
        self.assertEqual(
            calls[1],
            ("delete", "svc", "export-folder", main.DRIVE_CLIENT_EXPORT_FOLDER_ID),
        )
        self.assertEqual(calls[2][0:2], ("deleted", 1))

    def test_background_job_uses_drive_side_copy_and_returns_share_link(self):
        files = [
            {
                "id": "public-1",
                "name": "1.jpg",
                "size": 10,
                "modified_time": "2026-07-17T00:00:00Z",
                "path": "04 Product Images/6011822/1.jpg",
            }
        ]
        calls = []
        old_service = drive.service
        old_find = drive.find_sku_folder
        old_copy = drive.copy_accessible_folder
        old_jobs = main.drive_copy_jobs
        old_connect = db.connect
        temp_db = tempfile.TemporaryDirectory()
        db_path = Path(temp_db.name) / "drive-export.db"
        conn = old_connect(db_path)
        db.init_db(conn)
        conn.close()
        db.connect = lambda _path=None: old_connect(db_path)
        drive.service = lambda scopes: calls.append(("service", scopes)) or "svc"
        drive.find_sku_folder = lambda svc, file_id, sku: calls.append(
            ("find", svc, file_id, sku)
        ) or {"id": "source-folder"}

        def fake_copy(svc, source_id, target_id, allowed_ids, progress):
            calls.append(("copy", svc, source_id, target_id, allowed_ids))
            progress(1, 1)
            return {
                "folder_id": "export-folder",
                "folder_url": "https://drive.google.com/drive/folders/export-folder",
                "file_count": 1,
            }

        drive.copy_accessible_folder = fake_copy
        main.drive_copy_jobs = {
            "job-1": {
                "job_id": "job-1",
                "job_key": "7:digest",
                "user_id": "7",
                "sku": "6011822",
                "state": "building",
                "progress": 5,
            }
        }
        try:
            main.run_drive_copy_job("job-1", "6011822", files)
            state = main.drive_copy_jobs["job-1"]
        finally:
            drive.service = old_service
            drive.find_sku_folder = old_find
            drive.copy_accessible_folder = old_copy
            main.drive_copy_jobs = old_jobs
            db.connect = old_connect
            temp_db.cleanup()

        self.assertEqual(calls[0], ("service", [drive.DRIVE_WRITE_SCOPE]))
        self.assertEqual(calls[1], ("find", "svc", "public-1", "6011822"))
        self.assertEqual(
            calls[2],
            (
                "copy",
                "svc",
                "source-folder",
                main.DRIVE_CLIENT_EXPORT_FOLDER_ID,
                {"public-1"},
            ),
        )
        self.assertEqual(state["state"], "ready")
        self.assertEqual(state["progress"], 100)
        self.assertEqual(state["folder_url"], "https://drive.google.com/drive/folders/export-folder")
        self.assertTrue(state["expires_at"].endswith("Z"))

    def test_find_sku_folder_walks_up_from_an_asset(self):
        metadata = {
            "asset-1": {"id": "asset-1", "name": "1.jpg", "mimeType": "image/jpeg", "parents": ["nested"]},
            "nested": {"id": "nested", "name": "Lifestyle", "mimeType": FOLDER_MIME, "parents": ["sku-folder"]},
            "sku-folder": {
                "id": "sku-folder",
                "name": "6011822 CF - Sunglass Gorilla Driver Cover",
                "mimeType": FOLDER_MIME,
                "parents": ["set-folder"],
            },
        }
        old_metadata = drive.file_metadata
        drive.file_metadata = lambda _svc, file_id: metadata[file_id]
        try:
            folder = drive.find_sku_folder(object(), "asset-1", "6011822")
        finally:
            drive.file_metadata = old_metadata

        self.assertEqual(folder["id"], "sku-folder")

    def test_copy_accessible_folder_only_exports_allowed_indexed_files(self):
        tree = {
            "sku-folder": [
                {"id": "public-1", "name": "1.jpg", "mimeType": "image/jpeg"},
                {"id": "private-1", "name": "internal.psd", "mimeType": "image/vnd.adobe.photoshop"},
                {"id": "nested", "name": "Lifestyle", "mimeType": FOLDER_MIME},
                {"id": "empty", "name": "Internal only", "mimeType": FOLDER_MIME},
            ],
            "nested": [
                {"id": "public-2", "name": "2.jpg", "mimeType": "image/jpeg"},
                {"id": "private-2", "name": "source.ai", "mimeType": "application/postscript"},
            ],
            "empty": [{"id": "private-3", "name": "notes.txt", "mimeType": "text/plain"}],
        }
        created = []
        copied = []
        permissions = []
        progress = []
        old_metadata = drive.file_metadata
        old_list = drive.list_children
        old_create = drive.create_folder
        old_copy = drive.copy_file
        old_permission = drive.create_public_reader_permission
        drive.file_metadata = lambda _svc, _file_id: {
            "id": "sku-folder",
            "name": "6011822 CF - Sunglass Gorilla Driver Cover",
            "mimeType": FOLDER_MIME,
        }
        drive.list_children = lambda _svc, folder_id, _drive_id="": iter(tree.get(folder_id, []))

        def fake_create(_svc, parent_id, name):
            folder_id = "export-root" if parent_id == "export-parent" else f"copy-{name}"
            created.append((parent_id, name, folder_id))
            return {"id": folder_id, "name": name}

        drive.create_folder = fake_create
        drive.copy_file = lambda _svc, file_id, parent_id, name: copied.append(
            (file_id, parent_id, name)
        ) or {"id": f"copy-{file_id}", "name": name}
        drive.create_public_reader_permission = lambda _svc, folder_id: permissions.append(folder_id)
        try:
            result = drive.copy_accessible_folder(
                object(),
                "sku-folder",
                "export-parent",
                {"public-1", "public-2"},
                lambda completed, total: progress.append((completed, total)),
            )
        finally:
            drive.file_metadata = old_metadata
            drive.list_children = old_list
            drive.create_folder = old_create
            drive.copy_file = old_copy
            drive.create_public_reader_permission = old_permission

        self.assertEqual(
            created,
            [
                ("export-parent", "6011822 CF - Sunglass Gorilla Driver Cover", "export-root"),
                ("export-root", "Lifestyle", "copy-Lifestyle"),
            ],
        )
        self.assertEqual(
            copied,
            [
                ("public-1", "export-root", "1.jpg"),
                ("public-2", "copy-Lifestyle", "2.jpg"),
            ],
        )
        self.assertEqual(permissions, ["export-root"])
        self.assertEqual(progress, [(1, 2), (2, 2)])
        self.assertEqual(result["folder_url"], "https://drive.google.com/drive/folders/export-root")

    def test_react_customer_actions_prepare_and_open_drive_folder(self):
        root = Path("app/fontend/src")
        app = (root / "App.tsx").read_text(encoding="utf-8")
        service = (root / "services/materials.ts").read_text(encoding="utf-8")
        card = (root / "components/ProductCard.tsx").read_text(encoding="utf-8")
        drawer = (root / "components/ProductDrawer.tsx").read_text(encoding="utf-8")
        backend = Path("app/main.py").read_text(encoding="utf-8")

        self.assertIn('/sku/${encodeURIComponent(sku)}/drive/prepare', service)
        self.assertIn('/sku/${encodeURIComponent(sku)}/drive/status', service)
        self.assertIn('window.open("about:blank", "_blank")', app)
        self.assertIn("setDriveJob({ sku: product.sku, progress: 100, complete: true", app)
        self.assertIn("driveWindow.location.replace(state.folder_url)", app)
        self.assertIn('window.open(state.folder_url, "_blank", "noopener,noreferrer")', app)
        self.assertNotIn("window.location.assign(state.folder_url)", app)
        self.assertIn("Open in Drive", card + drawer)
        self.assertNotIn("Download ZIP", card + drawer)
        self.assertNotIn("prepareProductZip", app)
        self.assertIn('@app.post("/sku/{sku}/drive/prepare")', backend)


if __name__ == "__main__":
    unittest.main()
