import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import db, dingtalk_catalog, nas_imports


class DingTalkCatalogAutoImportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(Path(self.tmp.name) / "catalog.db")
        db.init_db(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def record(
        self,
        sku="7202656",
        *,
        record_id="record-1",
        brand="无牌",
        product_type="毛巾",
        chinese_name="无牌 回到未来系列华夫格毛巾40*40cm",
        english_name="Back to the Future Golf Towel - 40*40cm",
        partition="A_产品目录",
        set_code="Set00088",
    ):
        fields = dingtalk_catalog.FIELD_IDS
        cells = {
            fields["sku"]: sku,
            fields["brand"]: {"id": "brand", "name": brand},
            fields["product_type"]: {"id": "type", "name": product_type},
            fields["chinese_name"]: chinese_name,
            fields["english_name"]: english_name,
            fields["partition"]: {"id": "partition", "name": partition},
        }
        if set_code:
            cells[fields["set_code"]] = {"refFieldType": "autoNumber", "value": [set_code]}
        return {"recordId": record_id, "cells": cells}

    @staticmethod
    def runner(records):
        payload = {"success": True, "status": "success", "data": {"records": records}}
        return lambda *_args, **_kwargs: SimpleNamespace(
            stdout=json.dumps(payload, ensure_ascii=False), stderr="", returncode=0
        )

    def test_sync_stores_ready_product_and_updates_sku_metadata(self):
        result = dingtalk_catalog.sync_catalog(self.conn, runner=self.runner([self.record()]))

        self.assertEqual(result, {"records": 1, "ready": 1})
        product = dingtalk_catalog.product_for_sku(self.conn, "7202656")
        self.assertIsNotNone(product)
        self.assertEqual(product["category_id"], "ACC_TOWEL")
        self.assertEqual(product["set_code"], "Set00088")
        meta = self.conn.execute("SELECT * FROM sku_meta WHERE sku='7202656'").fetchone()
        self.assertEqual(meta["english_name"], "Back to the Future Golf Towel - 40*40cm")
        self.assertEqual(meta["category_source"], "dingtalk_aitable")
        self.assertEqual(meta["category_status"], "verified")

    def test_retryable_cli_error_from_stderr_is_retried_once(self):
        responses = iter(
            [
                SimpleNamespace(
                    stdout="",
                    stderr=json.dumps(
                        {"error": {"message": "temporary", "retryable": True}},
                        ensure_ascii=False,
                    ),
                    returncode=1,
                ),
                SimpleNamespace(
                    stdout=json.dumps(
                        {"data": {"records": [self.record()]}},
                        ensure_ascii=False,
                    ),
                    stderr="",
                    returncode=0,
                ),
            ]
        )
        calls = []

        def runner(*args, **kwargs):
            calls.append((args, kwargs))
            return next(responses)

        rows = dingtalk_catalog.fetch_records(runner, skus=["7202656"])

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["sku"], "7202656")
        self.assertEqual(len(calls), 2)

    def test_duplicate_active_sku_is_not_safe_for_automatic_import(self):
        records = [self.record(record_id="one"), self.record(record_id="two")]
        result = dingtalk_catalog.sync_catalog(self.conn, runner=self.runner(records))

        self.assertEqual(result, {"records": 2, "ready": 0})
        self.assertIsNone(dingtalk_catalog.product_for_sku(self.conn, "7202656"))
        reasons = {
            row["validation_error"]
            for row in self.conn.execute("SELECT validation_error FROM dingtalk_catalog_products")
        }
        self.assertEqual(reasons, {"SKU 在 A_产品目录中存在重复记录"})

    def test_non_product_partition_and_missing_english_name_are_not_ready(self):
        records = [
            self.record(record_id="b", partition="B_包装&物料"),
            self.record(sku="8300072", record_id="missing", english_name=""),
        ]
        result = dingtalk_catalog.sync_catalog(self.conn, runner=self.runner(records))

        self.assertEqual(result, {"records": 2, "ready": 0})
        self.assertIsNone(dingtalk_catalog.product_for_sku(self.conn, "8300072"))

    def test_catalog_suggestion_uses_table_name_and_deterministic_directory(self):
        dingtalk_catalog.sync_catalog(self.conn, runner=self.runner([self.record()]))
        self.conn.execute(
            """
            INSERT INTO nas_imports(local_path, rel_path, name, size, mtime_ns, sha256)
            VALUES ('gdrive:file-1', '临时/7202656新品/1.jpg', '1.jpg', 10, 1, 'sha-1')
            """
        )
        self.conn.commit()
        import_id = self.conn.execute("SELECT id FROM nas_imports WHERE sha256='sha-1'").fetchone()["id"]

        self.assertTrue(nas_imports.suggest_import_from_catalog(self.conn, import_id))

        saved = nas_imports.get_import(self.conn, import_id)
        self.assertEqual(saved["status"], "suggested")
        self.assertEqual(saved["final_english_name"], "Back to the Future Golf Towel - 40*40cm")
        self.assertEqual(
            saved["final_drive_folder"],
            "04 Product Images (No Brand)/15 Golf Towl/7202656 Back to the Future Golf Towel - 40*40cm",
        )
        self.assertEqual(
            saved["final_drive_name"],
            "7202656 Back to the Future Golf Towel - 40*40cm (1).jpg",
        )

    def test_enabled_catalog_mode_never_calls_ai_for_a_missing_sku(self):
        dingtalk_catalog.sync_catalog(self.conn, runner=self.runner([self.record()]))
        self.conn.execute(
            """
            INSERT INTO nas_imports(local_path, rel_path, name, size, mtime_ns, sha256)
            VALUES ('gdrive:file-2', '临时/9999999新品/1.jpg', '1.jpg', 10, 1, 'sha-2')
            """
        )
        self.conn.commit()
        import_id = self.conn.execute("SELECT id FROM nas_imports WHERE sha256='sha-2'").fetchone()["id"]

        with patch.dict(os.environ, {"DINGTALK_AITABLE_SYNC_ENABLED": "1"}), patch.object(
            nas_imports, "request_ai_suggestion", side_effect=AssertionError("AI must not run")
        ):
            nas_imports.suggest_import(self.conn, import_id)

        saved = nas_imports.get_import(self.conn, import_id)
        self.assertEqual(saved["status"], "pending")
        self.assertIn("9999999", saved["reason"])

    def test_safe_match_moves_drive_file_without_manual_review(self):
        dingtalk_catalog.sync_catalog(self.conn, runner=self.runner([self.record()]))
        self.conn.execute(
            """
            INSERT INTO users(id, email, name, role, password_hash)
            VALUES (101, 'liuruihua@example.com', '刘芮华', 'super_admin', 'x')
            """
        )
        self.conn.execute(
            """
            INSERT INTO nas_imports(local_path, rel_path, name, size, mtime_ns, sha256)
            VALUES ('gdrive:file-3', '临时/7202656新品/2.jpg', '2.jpg', 10, 1, 'sha-3')
            """
        )
        self.conn.commit()
        moves = []

        with patch.object(nas_imports.drive, "service", return_value="service"), patch.object(
            nas_imports.drive, "ensure_folder_path", return_value="folder"
        ), patch.object(
            nas_imports.drive, "file_metadata", return_value={"id": "file-3", "parents": ["source-folder"]}
        ), patch.object(
            nas_imports.drive, "move_file", side_effect=lambda *args: moves.append(args)
        ):
            uploaded = nas_imports.auto_import_catalog_matches(self.conn, "root")

        self.assertEqual(uploaded, 1)
        saved = self.conn.execute("SELECT * FROM nas_imports WHERE sha256='sha-3'").fetchone()
        self.assertEqual(saved["status"], "uploaded")
        self.assertEqual(saved["approved_by"], 101)
        self.assertEqual(saved["drive_file_id"], "file-3")
        self.assertEqual(len(moves), 1)

    def test_file_already_moved_out_of_inbox_is_not_moved_again(self):
        dingtalk_catalog.sync_catalog(self.conn, runner=self.runner([self.record()]))
        self.conn.execute(
            "INSERT INTO users(id, email, name, role, password_hash) VALUES (104, 'used@example.com', '刘芮华', 'super_admin', 'x')"
        )
        self.conn.execute(
            """
            INSERT INTO nas_imports(local_path, rel_path, name, size, mtime_ns, sha256)
            VALUES ('gdrive:file-7', '临时/7202656新品/4.jpg', '4.jpg', 10, 1, 'sha-7')
            """
        )
        self.conn.commit()

        with patch.dict(os.environ, {"GOOGLE_DRIVE_INBOX_FOLDER_ID": "inbox"}), patch.object(
            nas_imports.drive, "service", return_value="service"
        ), patch.object(
            nas_imports.drive, "file_metadata", return_value={"id": "file-7", "parents": ["used-folder"]}
        ), patch.object(
            nas_imports.drive, "file_is_within_folder", return_value=False
        ), patch.object(
            nas_imports.drive, "ensure_folder_path", side_effect=AssertionError("must not create a target")
        ), patch.object(
            nas_imports.drive, "move_file", side_effect=AssertionError("must not move a used file")
        ):
            uploaded = nas_imports.auto_import_catalog_matches(self.conn, "root")

        self.assertEqual(uploaded, 1)
        saved = self.conn.execute("SELECT * FROM nas_imports WHERE sha256='sha-7'").fetchone()
        self.assertEqual(saved["status"], "uploaded")
        self.assertEqual(saved["drive_file_id"], "file-7")
        self.assertIn("已经使用", saved["reason"])

    def test_matching_content_in_target_folder_is_not_moved_again(self):
        dingtalk_catalog.sync_catalog(self.conn, runner=self.runner([self.record()]))
        self.conn.execute(
            "INSERT INTO users(id, email, name, role, password_hash) VALUES (105, 'duplicate@example.com', '刘芮华', 'super_admin', 'x')"
        )
        self.conn.execute(
            """
            INSERT INTO nas_imports(local_path, rel_path, name, size, mtime_ns, sha256)
            VALUES ('gdrive:file-8', '临时/7202656新品/5.jpg', '5.jpg', 10, 1, 'sha-8')
            """
        )
        self.conn.commit()

        with patch.dict(os.environ, {"GOOGLE_DRIVE_INBOX_FOLDER_ID": "inbox"}), patch.object(
            nas_imports.drive, "service", return_value="service"
        ), patch.object(
            nas_imports.drive,
            "file_metadata",
            return_value={"id": "file-8", "parents": ["inbox"], "md5Checksum": "same"},
        ), patch.object(
            nas_imports.drive, "file_is_within_folder", return_value=True
        ), patch.object(
            nas_imports.drive, "ensure_folder_path", return_value="target-folder"
        ), patch.object(
            nas_imports.drive,
            "list_children",
            return_value=iter([{"id": "existing-file", "mimeType": "image/jpeg", "md5Checksum": "same"}]),
        ), patch.object(
            nas_imports.drive, "move_file", side_effect=AssertionError("must not move duplicate content")
        ):
            uploaded = nas_imports.auto_import_catalog_matches(self.conn, "root")

        self.assertEqual(uploaded, 1)
        saved = self.conn.execute("SELECT * FROM nas_imports WHERE sha256='sha-8'").fetchone()
        self.assertEqual(saved["status"], "uploaded")
        self.assertEqual(saved["drive_file_id"], "existing-file")
        self.assertIn("内容相同", saved["reason"])

    def test_matching_content_is_checked_without_an_inbox_folder_setting(self):
        dingtalk_catalog.sync_catalog(self.conn, runner=self.runner([self.record()]))
        self.conn.execute(
            "INSERT INTO users(id, email, name, role, password_hash) VALUES (106, 'no-inbox@example.com', '刘芮华', 'super_admin', 'x')"
        )
        self.conn.execute(
            """
            INSERT INTO nas_imports(local_path, rel_path, name, size, mtime_ns, sha256)
            VALUES ('gdrive:file-9', '临时/7202656新品/6.jpg', '6.jpg', 10, 1, 'sha-9')
            """
        )
        self.conn.commit()

        with patch.dict(os.environ, {"GOOGLE_DRIVE_INBOX_FOLDER_ID": ""}), patch.object(
            nas_imports.drive, "service", return_value="service"
        ), patch.object(
            nas_imports.drive,
            "file_metadata",
            return_value={"id": "file-9", "parents": ["source-folder"], "md5Checksum": "same"},
        ) as metadata, patch.object(
            nas_imports.drive, "ensure_folder_path", return_value="target-folder"
        ), patch.object(
            nas_imports.drive,
            "list_children",
            return_value=iter([{"id": "existing-file", "mimeType": "image/jpeg", "md5Checksum": "same"}]),
        ), patch.object(
            nas_imports.drive, "move_file", side_effect=AssertionError("must not move duplicate content")
        ):
            uploaded = nas_imports.auto_import_catalog_matches(self.conn, "root")

        self.assertEqual(uploaded, 1)
        metadata.assert_called_once_with("service", "file-9")
        saved = self.conn.execute("SELECT * FROM nas_imports WHERE sha256='sha-9'").fetchone()
        self.assertEqual(saved["status"], "uploaded")
        self.assertEqual(saved["drive_file_id"], "existing-file")
        self.assertIn("内容相同", saved["reason"])

    def test_safe_matches_are_queued_as_resumable_background_jobs(self):
        dingtalk_catalog.sync_catalog(self.conn, runner=self.runner([self.record()]))
        self.conn.execute(
            """
            INSERT INTO users(id, email, name, role, password_hash)
            VALUES (102, 'auto@example.com', '刘芮华', 'super_admin', 'x')
            """
        )
        self.conn.execute(
            """
            INSERT INTO nas_imports(local_path, rel_path, name, size, mtime_ns, sha256)
            VALUES ('gdrive:file-4', '临时/7202656新品/3.jpg', '3.jpg', 10, 1, 'sha-4')
            """
        )
        self.conn.commit()

        job_ids = nas_imports.queue_catalog_auto_import_jobs(self.conn, "root")

        self.assertEqual(len(job_ids), 1)
        saved = self.conn.execute("SELECT * FROM nas_imports WHERE sha256='sha-4'").fetchone()
        self.assertEqual(saved["status"], "approved")
        job = nas_imports.get_import_job(self.conn, job_ids[0])
        self.assertEqual(job["status"], "queued")
        self.assertEqual(job["total"], 1)

    def test_duplicate_generated_target_names_receive_unique_sequences(self):
        dingtalk_catalog.sync_catalog(self.conn, runner=self.runner([self.record()]))
        self.conn.execute(
            """
            INSERT INTO users(id, email, name, role, password_hash)
            VALUES (103, 'collision@example.com', '刘芮华', 'super_admin', 'x')
            """
        )
        self.conn.executemany(
            """
            INSERT INTO nas_imports(local_path, rel_path, name, size, mtime_ns, sha256)
            VALUES (?, ?, '1.jpg', 10, 1, ?)
            """,
            [
                ("gdrive:file-5", "临时/第一批/7202656新品/1.jpg", "sha-5"),
                ("gdrive:file-6", "临时/第二批/7202656新品/1.jpg", "sha-6"),
            ],
        )
        self.conn.commit()

        job_ids = nas_imports.queue_catalog_auto_import_jobs(self.conn, "root")

        self.assertEqual(len(job_ids), 2)
        rows = self.conn.execute(
            "SELECT status, final_drive_name, reason FROM nas_imports WHERE sha256 IN ('sha-5','sha-6') ORDER BY sha256"
        ).fetchall()
        self.assertEqual([row["status"] for row in rows], ["approved", "approved"])
        self.assertEqual(
            {row["final_drive_name"] for row in rows},
            {
                "7202656 Back to the Future Golf Towel - 40*40cm (1).jpg",
                "7202656 Back to the Future Golf Towel - 40*40cm (2).jpg",
            },
        )
        self.assertTrue(any("自动分配唯一序号" in row["reason"] for row in rows))

    def test_catalog_attention_notification_lists_missing_skus_and_deduplicates(self):
        self.conn.execute(
            """
            INSERT INTO users(id, email, name, role, password_hash)
            VALUES (107, 'notify@example.com', '刘芮华', 'super_admin', 'x')
            """
        )
        self.conn.execute(
            """
            INSERT INTO user_identities(
              user_id, provider, provider_subject, provider_user_id, display_name
            ) VALUES (107, 'dingtalk', 'subject-107', 'ding-user-107', '刘芮华')
            """
        )
        self.conn.commit()
        messages = []

        def fake_send(recipients, content, client_id, client_secret, agent_id):
            messages.append((recipients, content, client_id, client_secret, agent_id))
            return {"task_id": "catalog-alert-1"}

        with patch.dict(
            os.environ,
            {
                "DINGTALK_CLIENT_ID": "client-id",
                "DINGTALK_CLIENT_SECRET": "client-secret",
                "DINGTALK_AGENT_ID": "123",
            },
        ), patch.object(nas_imports.dingtalk_auth, "send_work_notification", side_effect=fake_send):
            sent = nas_imports.notify_catalog_import_attention(
                self.conn,
                ["6017054", "6017055", "6017054"],
                pending_file_count=29,
            )
            duplicate = nas_imports.notify_catalog_import_attention(
                self.conn,
                ["6017054", "6017055"],
                pending_file_count=29,
            )

        self.assertTrue(sent)
        self.assertFalse(duplicate)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0][0], ["ding-user-107"])
        self.assertIn("29 个", messages[0][1])
        self.assertIn("6017054 6017055", messages[0][1])
        saved = self.conn.execute(
            "SELECT status, recipient_name FROM missing_sku_notifications ORDER BY id DESC LIMIT 1"
        ).fetchone()
        self.assertEqual(saved["status"], "sent")
        self.assertEqual(saved["recipient_name"], "刘芮华")

    def test_catalog_sync_failure_notifies_and_keeps_import_pending(self):
        self.conn.execute(
            """
            INSERT INTO nas_imports(local_path, rel_path, name, size, mtime_ns, sha256)
            VALUES ('gdrive:today-1', '临时/6017054新品/1.jpg', '1.jpg', 10, 1, 'today-sha-1')
            """
        )
        self.conn.commit()
        notifications = []

        with patch.dict(os.environ, {"DRIVE_ROOT_FOLDER_ID": "root"}), patch.object(
            nas_imports, "scan_drive_inbox", return_value=110
        ), patch.object(
            nas_imports.product_taxonomy, "backfill_pending_imports"
        ), patch.object(nas_imports.dingtalk_catalog, "enabled", return_value=True), patch.object(
            nas_imports.dingtalk_catalog,
            "sync_catalog_skus",
            side_effect=dingtalk_catalog.DingTalkCatalogError("pagination failed"),
        ), patch.object(
            nas_imports,
            "notify_catalog_import_attention",
            side_effect=lambda _conn, skus, **kwargs: notifications.append((skus, kwargs)) or True,
        ):
            count, job_ids = nas_imports.scan_sources(self.conn)

        self.assertEqual(count, 110)
        self.assertEqual(job_ids, [])
        self.assertEqual(notifications[0][0], ["6017054"])
        self.assertEqual(notifications[0][1]["pending_file_count"], 110)
        self.assertIn("pagination failed", notifications[0][1]["error"])
        saved = self.conn.execute("SELECT status FROM nas_imports WHERE sha256='today-sha-1'").fetchone()
        self.assertEqual(saved["status"], "pending")


if __name__ == "__main__":
    unittest.main()
