import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException, Request

from app import db, main


def json_login_request() -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "https",
            "path": "/login",
            "raw_path": b"/login",
            "query_string": b"",
            "headers": [(b"accept", b"application/json")],
            "server": ("testserver", 443),
            "client": ("127.0.0.1", 12345),
            "root_path": "",
            "app": main.app,
            "router": main.app.router,
        }
    )


class CustomerAccessTest(unittest.TestCase):
    def test_global_rules_migrate_to_equivalent_per_account_allowlists(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / "test.db")
            db.init_db(conn)
            db.replace_files(
                conn,
                [
                    {"id": "brand", "name": "brand.jpg", "mime_type": "image/jpeg", "size": 1, "modified_time": "", "path": "04 Product Images/Brand A/a.jpg", "sku": "", "brand": "Brand A", "category": "", "other": "", "asset_type": "image", "internal_only": 0},
                    {"id": "no-brand", "name": "plain.jpg", "mime_type": "image/jpeg", "size": 1, "modified_time": "", "path": "04 Product Images (No Brand)/plain.jpg", "sku": "", "brand": "", "category": "", "other": "No Brand", "asset_type": "image", "internal_only": 0},
                    {"id": "show", "name": "show.jpg", "mime_type": "image/jpeg", "size": 1, "modified_time": "", "path": "06 Show & Exhibitions/show.jpg", "sku": "", "brand": "", "category": "", "other": "Show & Exhibitions", "asset_type": "image", "internal_only": 0},
                    {"id": "catalog", "name": "catalog.pdf", "mime_type": "application/pdf", "size": 1, "modified_time": "", "path": "01 Product Catalogs/catalog.pdf", "sku": "", "brand": "", "category": "", "other": "Product Catalogs", "asset_type": "other", "internal_only": 0},
                ],
            )
            first = db.create_customer_user_with_permissions(conn, "first@example.com", "First", "overseas_customer", "password123")
            second = db.create_customer_user_with_permissions(conn, "second@example.com", "Second", "overseas_customer", "password123")
            db.create_user_grant(conn, int(first["id"]), "brand", "No Brand")
            db.create_role_rule(conn, "overseas_customer", "other", "No Brand")
            db.create_role_rule(conn, "overseas_customer", "other", "Show & Exhibitions")

            result = db.migrate_role_rules_to_account_grants(conn)

            self.assertEqual(result["accounts"], 2)
            self.assertEqual(result["rules_deleted"], 2)
            self.assertEqual(db.list_role_rules(conn), [])
            self.assertEqual(db.user_permission_mode(conn, int(first["id"])), "allowlist")
            self.assertEqual(db.user_permission_mode(conn, int(second["id"])), "allowlist")
            self.assertEqual(
                {row["id"] for row in db.search_files(conn, "overseas_customer", user_id=int(first["id"]))},
                {"brand", "no-brand", "catalog"},
            )
            self.assertEqual(
                {row["id"] for row in db.search_files(conn, "overseas_customer", user_id=int(second["id"]))},
                {"brand", "catalog"},
            )
            conn.close()

    def test_customer_account_expires_after_fifteen_days_and_reports_disabled_in_english(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.db"
            conn = db.connect(path)
            db.init_db(conn)
            user = db.create_customer_user_with_permissions(
                conn,
                "buyer@example.com",
                "Buyer",
                "overseas_customer",
                "password123",
            )
            expiry = datetime.fromisoformat(str(user["expires_at"]).replace("Z", "+00:00"))
            self.assertAlmostEqual(
                (expiry - datetime.now(timezone.utc)).total_seconds(),
                timedelta(days=15).total_seconds(),
                delta=10,
            )
            conn.execute(
                "UPDATE users SET expires_at=? WHERE id=?",
                ("2026-08-01T00:00:00Z", int(user["id"])),
            )
            conn.commit()
            conn.close()

            original_connect = db.connect
            db.connect = lambda *_args, **_kwargs: original_connect(path)
            try:
                response = main.login(json_login_request(), "buyer@example.com", "password123")
            finally:
                db.connect = original_connect

            self.assertEqual(response.status_code, 401)
            self.assertEqual(json.loads(response.body)["detail"], "This account has been disabled.")
            conn = db.connect(path)
            disabled = conn.execute("SELECT disabled FROM users WHERE id=?", (int(user["id"]),)).fetchone()
            self.assertEqual(disabled["disabled"], 1)
            restored = db.update_customer_user_with_permissions(
                conn,
                int(user["id"]),
                name="Buyer",
                role="overseas_customer",
                disabled=False,
            )
            restored_expiry = datetime.fromisoformat(str(restored["expires_at"]).replace("Z", "+00:00"))
            self.assertEqual(restored["disabled"], 0)
            self.assertAlmostEqual(
                (restored_expiry - datetime.now(timezone.utc)).total_seconds(),
                timedelta(days=15).total_seconds(),
                delta=10,
            )
            conn.close()

    def test_allowlist_account_sees_only_selected_scopes(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / "test.db")
            db.init_db(conn)
            db.replace_files(
                conn,
                [
                    {
                        "id": "craftsman",
                        "name": "craftsman.jpg",
                        "mime_type": "image/jpeg",
                        "size": 1,
                        "modified_time": "",
                        "path": "04 Product Images/01 Craftsman Golf/02 Driver Cover/6011001/craftsman.jpg",
                        "sku": "6011001",
                        "brand": "01 Craftsman Golf",
                        "category": "Driver Cover",
                        "other": "",
                        "asset_type": "image",
                        "internal_only": 0,
                    },
                    {
                        "id": "caesar",
                        "name": "caesar.jpg",
                        "mime_type": "image/jpeg",
                        "size": 1,
                        "modified_time": "",
                        "path": "04 Product Images/05 Caesar/02 Driver Cover/6011002/caesar.jpg",
                        "sku": "6011002",
                        "brand": "05 Caesar",
                        "category": "Driver Cover",
                        "other": "",
                        "asset_type": "image",
                        "internal_only": 0,
                    },
                    {
                        "id": "show",
                        "name": "show.jpg",
                        "mime_type": "image/jpeg",
                        "size": 1,
                        "modified_time": "",
                        "path": "Show & Exhibitions/2026/show.jpg",
                        "sku": "",
                        "brand": "",
                        "category": "",
                        "other": "Show & Exhibitions",
                        "asset_type": "image",
                        "internal_only": 0,
                    },
                ],
            )
            user = db.create_customer_user_with_permissions(
                conn,
                "buyer@example.com",
                "Buyer",
                "overseas_customer",
                "password123",
                permission_mode="allowlist",
                grants=[("brand", "01 Craftsman Golf"), ("other", "Show & Exhibitions")],
            )

            visible = db.search_files(conn, "overseas_customer", user_id=int(user["id"]))

            self.assertEqual({row["id"] for row in visible}, {"craftsman", "show"})
            self.assertEqual(db.user_permission_mode(conn, int(user["id"])), "allowlist")
            listed = next(row for row in db.list_customer_users(conn) if row["id"] == user["id"])
            self.assertEqual(listed["permission_mode"], "allowlist")
            conn.close()

    def test_allowlist_requires_permission_and_does_not_leave_partial_user(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / "test.db")
            db.init_db(conn)

            with self.assertRaisesRegex(ValueError, "At least one permission"):
                db.create_customer_user_with_permissions(
                    conn,
                    "empty@example.com",
                    "Empty",
                    "overseas_customer",
                    "password123",
                    permission_mode="allowlist",
                )

            self.assertIsNone(conn.execute("SELECT id FROM users WHERE email='empty@example.com'").fetchone())
            conn.close()

    def test_api_creates_customer_and_permissions_in_one_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / "test.db")
            db.init_db(conn)
            original_connect = db.connect
            db.connect = lambda *_args, **_kwargs: conn
            try:
                payload = main.api_admin_create_customer_user(
                    email="new@example.com",
                    name="New Buyer",
                    role="overseas_customer",
                    password="password123",
                    permission_mode="allowlist",
                    permission_scopes=["brand", "other"],
                    permission_values=["01 Craftsman Golf", "Show & Exhibitions"],
                    user={"id": 2, "role": "admin"},
                )
            finally:
                db.connect = original_connect

            self.assertEqual(payload["user"]["permission_mode"], "allowlist")
            self.assertEqual(
                {(grant["scope"], grant["value"]) for grant in payload["grants"]},
                {("brand", "01 Craftsman Golf"), ("other", "Show & Exhibitions")},
            )
            conn.close()

    def test_account_update_replaces_permissions_and_can_disable_login(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / "test.db")
            db.init_db(conn)
            user = db.create_customer_user_with_permissions(
                conn,
                "buyer@example.com",
                "Buyer",
                "overseas_customer",
                "password123",
                permission_mode="allowlist",
                grants=[("brand", "01 Craftsman Golf")],
            )

            updated = db.update_customer_user_with_permissions(
                conn,
                int(user["id"]),
                name="Buyer APAC",
                role="domestic_customer",
                disabled=True,
                permission_mode="allowlist",
                grants=[("brand", "05 Caesar"), ("other", "Show & Exhibitions")],
            )

            self.assertEqual(updated["name"], "Buyer APAC")
            self.assertEqual(updated["role"], "domestic_customer")
            self.assertEqual(updated["disabled"], 1)
            self.assertEqual(
                {(grant["scope"], grant["value"]) for grant in db.user_grants(conn, int(user["id"]))},
                {("brand", "05 Caesar"), ("other", "Show & Exhibitions")},
            )
            self.assertIsNone(db.authenticate(conn, "buyer@example.com", "password123"))
            conn.close()

    def test_password_reset_returns_once_and_replaces_the_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / "test.db")
            db.init_db(conn)
            user = db.create_customer_user_with_permissions(
                conn,
                "buyer@example.com",
                "Buyer",
                "overseas_customer",
                "password123",
            )

            db.reset_customer_user_password(conn, int(user["id"]), "Temporary9!")

            self.assertIsNone(db.authenticate(conn, "buyer@example.com", "password123"))
            self.assertEqual(db.authenticate(conn, "buyer@example.com", "Temporary9!")["id"], user["id"])
            stored = conn.execute("SELECT password_hash FROM users WHERE id=?", (int(user["id"]),)).fetchone()
            self.assertNotIn("Temporary9!", stored["password_hash"])
            conn.close()

    def test_admin_access_payload_keeps_existing_rules_and_grants(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / "test.db")
            db.init_db(conn)
            admin_id = db.create_user(conn, "sales@example.com", "Sales", "admin", "password123")
            db.create_user(conn, "buyer@example.com", "Buyer", "overseas_customer", "password123")
            buyer = conn.execute("SELECT id FROM users WHERE email='buyer@example.com'").fetchone()
            conn.execute("UPDATE users SET created_by_user_id=? WHERE id=?", (admin_id, int(buyer["id"])))
            conn.commit()
            db.create_role_rule(conn, "overseas_customer", "other", "No Brand")
            db.create_user_grant(conn, int(buyer["id"]), "brand", "01 Craftsman Golf")

            original_connect = db.connect
            db.connect = lambda *_args, **_kwargs: conn
            try:
                payload = main.api_admin_access_control(user={"id": admin_id, "role": "admin"})
            finally:
                db.connect = original_connect
                conn.close()

            self.assertEqual(payload["rules"][0]["value"], "No Brand")
            self.assertEqual(payload["user_grants"][0]["email"], "buyer@example.com")
            self.assertIn("other", payload["permission_values"])

    def test_expired_customer_can_be_renewed_without_changing_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / "test.db")
            db.init_db(conn)
            admin_id = db.create_user(conn, "sales@example.com", "Sales", "admin", "password123")
            customer = db.create_customer_user_with_permissions(
                conn, "renew@example.com", "Renew", "overseas_customer", "password123",
                permission_mode="allowlist", grants=[("brand", "01 Craftsman Golf")],
                created_by_user_id=admin_id,
            )
            customer_id = int(customer["id"])
            conn.execute("UPDATE users SET expires_at='2020-01-01 00:00:00' WHERE id=?", (customer_id,))
            conn.commit()
            self.assertTrue(next(row for row in db.list_customer_users(conn, admin_id) if row["id"] == customer_id)["expired"])
            before = [(row["scope"], row["value"]) for row in db.user_grants(conn, customer_id)]
            original_connect = db.connect
            db.connect = lambda *_args, **_kwargs: conn
            try:
                with self.assertRaises(HTTPException) as denied:
                    main.api_admin_renew_customer_user(customer_id, user={"id": admin_id + 100, "role": "admin"})
                self.assertEqual(denied.exception.status_code, 403)
                renewed = main.api_admin_renew_customer_user(customer_id, user={"id": admin_id, "role": "admin"})
            finally:
                db.connect = original_connect
            self.assertEqual(renewed["user"]["disabled"], 0)
            self.assertGreater(renewed["user"]["expires_at"], "2020-01-01 00:00:00")
            self.assertEqual([(row["scope"], row["value"]) for row in db.user_grants(conn, customer_id)], before)
            audit = conn.execute("SELECT renewed_by_user_id, previous_expires_at FROM customer_account_renewals WHERE customer_user_id=?", (customer_id,)).fetchone()
            self.assertEqual((audit["renewed_by_user_id"], audit["previous_expires_at"]), (admin_id, "2020-01-01 00:00:00"))
            conn.close()

    def test_customer_cannot_pass_admin_guard(self):
        with self.assertRaises(HTTPException) as denied:
            main.require_api_admin(user={"id": 2, "role": "overseas_customer"})
        self.assertEqual(denied.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
