import tempfile
import unittest
import json
from pathlib import Path

from fastapi import HTTPException

from app import db, main


class UserActivityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(Path(self.tmp.name) / "activity.db")
        db.init_db(self.conn)
        db.create_user(self.conn, "customer@example.com", "Customer", "overseas_customer", "password123")
        self.user = self.conn.execute("SELECT * FROM users WHERE email='customer@example.com'").fetchone()
        self.conn.execute(
            """
            INSERT INTO files(id, name, mime_type, size, modified_time, path, sku, brand, category, asset_type, internal_only)
            VALUES ('file-1', '6012001 Front.jpg', 'image/jpeg', 12, '',
                    '04 Product Images/01 Craftsman Golf/03 Driver Cover/6012001 Driver Cover/6012001 Front.jpg',
                    '6012001', '01 Craftsman Golf', '03 Driver Cover', 'image', 0)
            """
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_activity_monitor_aggregates_login_original_download_and_drive_export(self):
        db.record_user_activity(self.conn, self.user["id"], "login", detail="password")
        db.record_user_activity(
            self.conn,
            self.user["id"],
            "original_open",
            sku="6012001",
            file_id="file-1",
            file_name="6012001 Front.jpg",
        )
        db.record_user_activity(
            self.conn,
            self.user["id"],
            "download",
            sku="6012001",
            file_id="file-1",
            file_name="6012001 Front.jpg",
        )
        db.record_user_activity(self.conn, self.user["id"], "drive_export", sku="6012001")

        overview = db.user_monitor_overview(self.conn)
        monitored = next(item for item in overview["users"] if item["id"] == self.user["id"])
        self.assertEqual(monitored["login_count"], 1)
        self.assertEqual(monitored["original_open_count"], 1)
        self.assertEqual(monitored["download_count"], 2)
        self.assertTrue(monitored["last_login_at"])
        self.assertEqual(overview["stats"]["events"], 4)

        detail = db.user_activity_detail(self.conn, self.user["id"])
        self.assertEqual(
            [event["event_type"] for event in detail["events"]],
            ["drive_export", "download", "original_open", "login"],
        )

    def test_original_open_endpoint_checks_visibility_before_recording(self):
        original_connect = db.connect
        db.connect = lambda *_args, **_kwargs: self.conn
        try:
            result = main.api_record_original_open(
                sku="6012001",
                file_id="file-1",
                user=self.user,
            )
        finally:
            db.connect = original_connect
        self.assertTrue(result["recorded"])
        event = self.conn.execute(
            "SELECT * FROM user_activity_events WHERE user_id=? AND event_type='original_open'",
            (self.user["id"],),
        ).fetchone()
        self.assertEqual(event["file_id"], "file-1")

    def test_catalog_funnel_records_visible_products_and_rejects_unknown_skus(self):
        original_connect = db.connect
        db.connect = lambda *_args, **_kwargs: self.conn
        try:
            self.assertTrue(main.api_record_catalog_event({"event_type": "catalog_view"}, user=self.user)["recorded"])
            self.assertTrue(main.api_record_catalog_event({"event_type": "product_added", "sku": "6012001"}, user=self.user)["recorded"])
            with self.assertRaises(HTTPException) as missing:
                main.api_record_catalog_event({"event_type": "product_added", "sku": "9999999"}, user=self.user)
            self.assertEqual(missing.exception.status_code, 404)
            with self.assertRaises(HTTPException) as invalid:
                main.api_record_catalog_event({"event_type": "product_added"}, user=self.user)
            self.assertEqual(invalid.exception.status_code, 400)
        finally:
            db.connect = original_connect
        events = self.conn.execute("SELECT event_type, sku FROM catalog_events ORDER BY id").fetchall()
        self.assertEqual([(row["event_type"], row["sku"]) for row in events], [("catalog_view", ""), ("product_added", "6012001")])

    def test_share_copy_and_customer_interest_are_scoped_to_the_salesperson(self):
        salesperson_id = db.create_user(self.conn, "sales@example.com", "Sales", "admin", "password123")
        other_salesperson_id = db.create_user(self.conn, "other@example.com", "Other", "admin", "password123")
        self.conn.execute("UPDATE users SET created_by_user_id=? WHERE id=?", (salesperson_id, self.user["id"]))
        self.conn.commit()
        original_connect = db.connect
        db.connect = lambda *_args, **_kwargs: self.conn
        try:
            with self.assertRaises(HTTPException) as denied:
                main.api_admin_record_catalog_share_copy(self.user["id"], user={"id": other_salesperson_id, "role": "admin"})
            self.assertEqual(denied.exception.status_code, 404)
            main.api_admin_record_catalog_share_copy(self.user["id"], user={"id": salesperson_id, "role": "admin"})
            main.api_record_catalog_event({"event_type": "catalog_view"}, user=self.user)
            main.api_record_catalog_event({"event_type": "product_added", "sku": "6012001"}, user=self.user)
            own = main.api_admin_access_control(user={"id": salesperson_id, "role": "admin"})
            other = main.api_admin_access_control(user={"id": other_salesperson_id, "role": "admin"})
        finally:
            db.connect = original_connect
        self.assertEqual(len(other["engagement"]), 0)
        self.assertEqual(len(own["engagement"]), 1)
        counts = own["engagement"][0]
        self.assertEqual((counts["share_copies"], counts["catalog_views"], counts["product_adds"], counts["order_count"]), (1, 1, 1, 0))

    def test_invite_open_prefills_only_its_customer_and_records_real_open(self):
        salesperson_id = db.create_user(self.conn, "sales@example.com", "Sales", "admin", "password123")
        other_salesperson_id = db.create_user(self.conn, "other@example.com", "Other", "admin", "password123")
        self.conn.execute("UPDATE users SET created_by_user_id=? WHERE id=?", (salesperson_id, self.user["id"]))
        self.conn.commit()
        original_connect = db.connect
        opened_connections = []
        def tracked_connect(*_args, **_kwargs):
            connection = original_connect(Path(self.tmp.name) / "activity.db")
            opened_connections.append(connection)
            return connection
        db.connect = tracked_connect
        try:
            token = "0123456789abcdef0123456789abcdef"
            with self.assertRaises(HTTPException) as denied:
                main.api_admin_create_catalog_invite(self.user["id"], token=token, user={"id": other_salesperson_id, "role": "admin"})
            self.assertEqual(denied.exception.status_code, 404)
            main.api_admin_create_catalog_invite(self.user["id"], token=token, user={"id": salesperson_id, "role": "admin"})
            self.assertNotIn(token, str(self.conn.execute("SELECT token_hash FROM customer_catalog_invites").fetchone()[0]))
            opened = main.api_open_catalog_invite({"token": token})
            self.assertEqual(json.loads(opened.body)["email"], self.user["email"])
            own = main.api_admin_access_control(user={"id": salesperson_id, "role": "admin"})
            other = main.api_admin_access_control(user={"id": other_salesperson_id, "role": "admin"})
            self.assertEqual(own["engagement"][0]["invite_opens"], 1)
            self.assertEqual(other["engagement"], [])
            self.conn.execute("UPDATE customer_catalog_invites SET expires_at=datetime('now', '-1 day')")
            self.conn.commit()
            with self.assertRaises(HTTPException) as expired:
                main.api_open_catalog_invite({"token": token})
            self.assertEqual(expired.exception.status_code, 404)
        finally:
            db.connect = original_connect
            for connection in opened_connections:
                connection.close()


if __name__ == "__main__":
    unittest.main()
