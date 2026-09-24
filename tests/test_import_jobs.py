import os
import tempfile
import unittest
from pathlib import Path

from app import db, nas_imports


class ImportJobsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old_inbox = os.environ.get("NAS_INBOX_DIR")
        os.environ["NAS_INBOX_DIR"] = str(self.root)
        self.database_path = self.root / "test.db"
        self.conn = db.connect(self.database_path)
        db.init_db(self.conn)

    def tearDown(self):
        self.conn.close()
        if self.old_inbox is None:
            os.environ.pop("NAS_INBOX_DIR", None)
        else:
            os.environ["NAS_INBOX_DIR"] = self.old_inbox
        self.tmp.cleanup()

    def create_suggested_import(self, name: str = "1.jpg"):
        local_path = self.root / name
        local_path.write_bytes(b"image")
        self.conn.execute(
            """
            INSERT INTO nas_imports(
              local_path, rel_path, name, size, mtime_ns, sha256, status,
              final_sku, final_english_name, final_drive_folder, final_drive_name,
              final_asset_type, final_category_id
            ) VALUES (?, ?, ?, 5, 1, ?, 'suggested',
              '6012065', 'Pink Birdie Driver Cover',
              '04 Product Images/01 Craftsman Golf/03 Driver Cover',
              '6012065 Pink Birdie Driver Cover.jpg', 'image', 'HC_DRIVER')
            """,
            (str(local_path), f"incoming/batch-a/{name}", name, f"hash-{name}"),
        )
        self.conn.execute(
            """
            INSERT INTO sku_meta(sku, english_name, brand, category_id)
            VALUES ('6012065', 'Pink Birdie Driver Cover', 'Craftsman Golf', 'HC_DRIVER')
            ON CONFLICT(sku) DO UPDATE SET
              english_name=excluded.english_name,
              brand=excluded.brand,
              category_id=excluded.category_id
            """
        )
        self.conn.commit()
        return self.conn.execute("SELECT * FROM nas_imports WHERE name=?", (name,)).fetchone()

    def test_queue_returns_before_upload_and_exposes_per_file_progress(self):
        row = self.create_suggested_import()
        upload_calls = []
        old_upload = nas_imports.drive.upload_file
        nas_imports.drive.upload_file = lambda *_args, **_kwargs: upload_calls.append(True) or {"id": "drive-file"}
        try:
            job = nas_imports.queue_import_job(
                self.conn,
                [row["id"]],
                "root",
                1,
                batch_id="incoming/batch-a",
                batch_name="batch-a",
            )
            self.assertEqual(upload_calls, [])
            self.assertEqual(nas_imports.get_import(self.conn, row["id"])["status"], "approved")
            queued = nas_imports.get_import_job(self.conn, job["id"])
            self.assertEqual(queued["status"], "queued")
            self.assertEqual(queued["items"][0]["progress"], 0)
            self.assertEqual(queued["items"][0]["stage"], "queued")
        finally:
            nas_imports.drive.upload_file = old_upload

    def test_approval_always_adds_the_sku_product_folder(self):
        row = self.create_suggested_import()
        old_service = nas_imports.drive.service
        old_ensure = nas_imports.drive.ensure_folder_path
        old_upload = nas_imports.drive.upload_file
        folder_calls = []
        nas_imports.drive.service = lambda scopes: "svc"
        nas_imports.drive.ensure_folder_path = lambda svc, root_id, parts: folder_calls.append(parts) or "parent"
        nas_imports.drive.upload_file = lambda *_args, **_kwargs: {"id": "drive-file"}
        try:
            nas_imports.approve_import(self.conn, row["id"], "root", 1)
        finally:
            nas_imports.drive.service = old_service
            nas_imports.drive.ensure_folder_path = old_ensure
            nas_imports.drive.upload_file = old_upload

        self.assertEqual(
            folder_calls[0],
            [
                "04 Product Images",
                "01 Craftsman Golf",
                "03 Driver Cover",
                "6012065 CF - Pink Birdie Driver Cover",
            ],
        )

    def test_background_worker_completes_each_file_progress(self):
        row = self.create_suggested_import()
        job = nas_imports.queue_import_job(
            self.conn,
            [row["id"]],
            "root",
            1,
            batch_id="incoming/batch-a",
            batch_name="batch-a",
        )
        old_service = nas_imports.drive.service
        old_ensure = nas_imports.drive.ensure_folder_path
        old_upload = nas_imports.drive.upload_file
        nas_imports.drive.service = lambda scopes: "svc"
        nas_imports.drive.ensure_folder_path = lambda *_args: "parent"

        def fake_upload(*_args, progress=None, **_kwargs):
            if progress:
                progress(5, 5)
            return {"id": "drive-file"}

        nas_imports.drive.upload_file = fake_upload
        try:
            completed = nas_imports.run_import_job(self.database_path, job["id"], "root")
        finally:
            nas_imports.drive.service = old_service
            nas_imports.drive.ensure_folder_path = old_ensure
            nas_imports.drive.upload_file = old_upload

        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["progress"], 100)
        self.assertEqual(completed["items"][0]["status"], "completed")
        self.assertEqual(completed["items"][0]["stage"], "completed")
        self.assertEqual(completed["items"][0]["progress"], 100)

    def test_failed_jobs_persist_until_an_admin_dismisses_them(self):
        row = self.create_suggested_import()
        job = nas_imports.queue_import_job(
            self.conn,
            [row["id"]],
            "root",
            1,
            batch_id="incoming/batch-a",
            batch_name="batch-a",
        )
        with self.conn:
            self.conn.execute(
                """
                UPDATE nas_import_jobs
                SET status='failed', finished_at=datetime('now', '-2 days'), updated_at=datetime('now', '-2 days')
                WHERE id=?
                """,
                (job["id"],),
            )
            self.conn.execute(
                "UPDATE nas_import_job_items SET status='error', stage='error', error='upload failed' WHERE job_id=?",
                (job["id"],),
            )

        self.assertIn(job["id"], [item["id"] for item in nas_imports.list_import_jobs(self.conn)])
        dismissed = nas_imports.dismiss_import_job(self.conn, job["id"])
        self.assertIsNotNone(dismissed["dismissed_at"])
        self.assertNotIn(job["id"], [item["id"] for item in nas_imports.list_import_jobs(self.conn)])

    def test_retrying_a_failed_item_closes_its_previous_error_job(self):
        row = self.create_suggested_import()
        failed_job = nas_imports.queue_import_job(self.conn, [row["id"]], "root", 1)
        with self.conn:
            self.conn.execute("UPDATE nas_import_jobs SET status='failed', finished_at=CURRENT_TIMESTAMP WHERE id=?", (failed_job["id"],))
            self.conn.execute("UPDATE nas_import_job_items SET status='error', stage='error' WHERE job_id=?", (failed_job["id"],))
            self.conn.execute("UPDATE nas_imports SET status='suggested' WHERE id=?", (row["id"],))

        retry_job = nas_imports.queue_import_job(self.conn, [row["id"]], "root", 1)
        previous = nas_imports.get_import_job(self.conn, failed_job["id"])
        self.assertIsNotNone(previous["dismissed_at"])
        self.assertEqual(retry_job["status"], "queued")


if __name__ == "__main__":
    unittest.main()
