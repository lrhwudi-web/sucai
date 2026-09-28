import os
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from app import db, main


DIRECTORY = {
    "departments": [
        {"id": "1", "name": "全部组织", "parent_id": "", "depth": 0},
        {"id": "2", "name": "信息技术部", "parent_id": "1", "depth": 1},
        {"id": "3", "name": "销售部", "parent_id": "1", "depth": 1},
    ],
    "members": [
        {"user_id": "ding-liu", "name": "刘芮华", "department_ids": ["2"]},
        {"user_id": "ding-sales", "name": "业务员甲", "department_ids": ["3"]},
    ],
}


class SuperAdminCacheAndMissingSkuTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = Path(self.temp.name) / "test.db"
        with closing(db.connect()) as conn:
            db.init_db(conn)
            self.super_admin = conn.execute(
                "SELECT * FROM users WHERE role='super_admin' ORDER BY id LIMIT 1"
            ).fetchone()
            searcher_id = db.create_user(
                conn, "buyer@example.com", "采购员甲", "overseas_customer", "password123"
            )
            liu_id = db.create_user(
                conn, "liu@example.com", "刘芮华", "internal_staff", "password123"
            )
            conn.execute(
                """
                INSERT INTO user_identities(
                  user_id, provider, provider_subject, provider_user_id, display_name
                ) VALUES (?, 'dingtalk', 'liu-subject', 'ding-liu', '刘芮华')
                """,
                (liu_id,),
            )
            conn.commit()
            self.searcher = conn.execute("SELECT * FROM users WHERE id=?", (searcher_id,)).fetchone()

    def tearDown(self):
        db.DB_PATH = self.original_db_path
        self.temp.cleanup()

    def test_organization_reads_local_cache_until_manual_refresh(self):
        with patch.object(main, "_live_dingtalk_organization", return_value=DIRECTORY) as live:
            first = main.api_super_admin_organization(user=self.super_admin)
            second = main.api_super_admin_organization(user=self.super_admin)
            refreshed = main.api_refresh_super_admin_organization(user=self.super_admin)

        self.assertEqual(live.call_count, 2)
        self.assertEqual(first["members"][0]["name"], "刘芮华")
        self.assertEqual(second["synced_at"], first["synced_at"])
        self.assertTrue(refreshed["synced_at"])
        with closing(db.connect()) as conn:
            cached = db.dingtalk_organization_cache(conn)
        self.assertIsNotNone(cached)
        self.assertEqual(cached["directory"]["members"][1]["user_id"], "ding-sales")

    def test_missing_skus_notify_liu_once_with_searcher_and_all_skus(self):
        sent = []

        def fake_send(user_ids, content, client_id, client_secret, agent_id):
            sent.append((user_ids, content, agent_id))
            return {"task_id": "task-001", "recipient_count": len(user_ids)}

        with patch.dict(os.environ, {
            "DINGTALK_CLIENT_ID": "client-id",
            "DINGTALK_CLIENT_SECRET": "client-secret",
            "DINGTALK_AGENT_ID": "123456",
        }), patch.object(main.dingtalk_auth, "send_work_notification", side_effect=fake_send):
            first = main.api_report_missing_skus(
                {"skus": ["SKU-100", "sku-200"], "searched_count": 8},
                user=self.searcher,
            )
            duplicate = main.api_report_missing_skus(
                {"skus": ["SKU-200", "SKU-100"], "searched_count": 8},
                user=self.searcher,
            )
            imported = main.api_report_missing_skus(
                {"skus": ["SKU-300"], "searched_count": 1, "source": "excel_import"},
                user=self.searcher,
            )

        self.assertTrue(first["notified"])
        self.assertFalse(first["duplicate"])
        self.assertTrue(duplicate["duplicate"])
        self.assertTrue(imported["notified"])
        self.assertEqual(len(sent), 2)
        self.assertEqual(sent[0][0], ["ding-liu"])
        self.assertIn("采购员甲（buyer@example.com）", sent[0][1])
        self.assertIn("SKU-100 SKU-200", sent[0][1])
        self.assertEqual(sent[0][2], "123456")
        self.assertIn("管理员 Excel 导入缺失提醒", sent[1][1])
        self.assertIn("搜索数量：1，未找到：1", sent[1][1])
        self.assertIn("SKU-300", sent[1][1])

    def test_material_admin_apis_require_super_admin_but_customer_accounts_do_not(self):
        dependency_by_path = {}
        for route in main.app.routes:
            path = getattr(route, "path", "")
            if path.startswith("/api/admin/"):
                dependency_by_path[path] = {
                    getattr(dependency.call, "__name__", "")
                    for dependency in getattr(route, "dependant").dependencies
                }

        for path in (
            "/api/admin/overview",
            "/api/admin/notifications",
            "/api/admin/import-jobs",
            "/api/admin/messages",
            "/api/admin/products",
            "/api/admin/categories",
            "/api/admin/themes",
            "/api/admin/products/bulk-metadata",
        ):
            self.assertIn("require_api_super_admin", dependency_by_path[path], path)

        for path in (
            "/api/admin/access-control",
            "/api/admin/users",
            "/api/admin/users/{user_id}",
            "/api/admin/users/{user_id}/reset-password",
        ):
            self.assertIn("require_api_admin", dependency_by_path[path], path)


if __name__ == "__main__":
    unittest.main()
