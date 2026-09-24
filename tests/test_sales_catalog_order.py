import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from app import db, main


class SalesCatalogOrderTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.conn = db.connect(Path(self.temp.name) / "catalog.db")
        db.init_db(self.conn)
        self.admin_a = db.create_user(self.conn, "a@example.com", "Sales A", "admin", "password123")
        self.admin_b = db.create_user(self.conn, "b@example.com", "Sales B", "admin", "password123")

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def customer(self, email, owner):
        return db.create_customer_user_with_permissions(
            self.conn, email, email, "overseas_customer", "password123",
            permission_mode="allowlist", grants=[("brand", "Craftsman Golf")],
            created_by_user_id=owner,
        )

    def test_each_salesperson_has_an_independent_table_inherited_by_their_customers(self):
        customer_a = self.customer("buyer-a@example.com", self.admin_a)
        customer_b = self.customer("buyer-b@example.com", self.admin_b)
        draft_a = {"version": 1, "title": "A price list", "lines": {"A-1": {"price": "6.9"}}}
        draft_b = {"version": 1, "title": "B price list", "lines": {"B-1": {"price": "8"}}}
        db.save_sales_catalog_order(self.conn, self.admin_a, ["A-2", "A-1"], draft_a, expected_revision=0)
        db.save_sales_catalog_order(self.conn, self.admin_b, ["B-1"], draft_b, expected_revision=0)

        inherited_a = db.sales_catalog_order_for_user(self.conn, int(customer_a["id"]))
        inherited_b = db.sales_catalog_order_for_user(self.conn, int(customer_b["id"]))
        owner_a = db.sales_catalog_owner_for_user(self.conn, int(customer_a["id"]))
        owner_b = db.sales_catalog_owner_for_user(self.conn, self.admin_b)
        self.assertEqual(owner_a["name"], "Sales A")
        self.assertEqual(owner_b["name"], "Sales B")
        self.assertEqual(inherited_a["owner_name"], "Sales A")
        self.assertEqual(inherited_a["sku_order"], ["A-2", "A-1"])
        self.assertEqual(inherited_a["draft"], draft_a)
        self.assertEqual(inherited_b["owner_name"], "Sales B")
        self.assertEqual(inherited_b["sku_order"], ["B-1"])
        self.assertNotEqual(inherited_a["draft"], inherited_b["draft"])

    def test_new_customer_records_creator_and_admin_lists_only_their_customers(self):
        customer_a = self.customer("owned-a@example.com", self.admin_a)
        self.customer("owned-b@example.com", self.admin_b)
        unassigned = db.create_customer_user_with_permissions(
            self.conn, "legacy@example.com", "Legacy", "overseas_customer", "password123"
        )
        self.assertEqual(customer_a["created_by_user_id"], self.admin_a)
        self.assertEqual([row["email"] for row in db.list_customer_users(self.conn, self.admin_a)], ["owned-a@example.com"])
        self.assertEqual(
            {row["email"] for row in db.list_customer_users(self.conn)},
            {"owned-a@example.com", "owned-b@example.com", str(unassigned["email"])},
        )
        self.assertTrue(db.customer_owned_by(self.conn, int(customer_a["id"]), self.admin_a))
        self.assertFalse(db.customer_owned_by(self.conn, int(customer_a["id"]), self.admin_b))

    def test_super_admin_access_payload_lists_salespeople_for_client_side_filtering(self):
        self.customer("owned-a@example.com", self.admin_a)
        self.customer("owned-b@example.com", self.admin_b)
        original_connect = db.connect
        db.connect = lambda *_args, **_kwargs: self.conn
        try:
            payload = main.api_admin_access_control(user={"id": 999, "role": "super_admin"})
            self.assertEqual({row["email"] for row in payload["users"]}, {"owned-a@example.com", "owned-b@example.com"})
            salesperson_ids = {row["id"] for row in payload["salespeople"]}
            self.assertTrue({self.admin_a, self.admin_b}.issubset(salesperson_ids))
            self.assertEqual({row["created_by_user_id"] for row in payload["users"]}, {self.admin_a, self.admin_b})

            admin_payload = main.api_admin_access_control(user={"id": self.admin_a, "role": "admin"})
            self.assertEqual([row["email"] for row in admin_payload["users"]], ["owned-a@example.com"])
            self.assertEqual(admin_payload["salespeople"], [])
        finally:
            db.connect = original_connect

    def test_save_rejects_stale_revision_and_invalid_or_oversized_orders(self):
        result = db.save_sales_catalog_order(self.conn, self.admin_a, ["SKU-2", "SKU-2", "SKU-1"], {"version": 1}, expected_revision=0)
        self.assertEqual(result["sku_order"], ["SKU-2", "SKU-1"])
        self.assertEqual(result["revision"], 1)
        with self.assertRaisesRegex(RuntimeError, "another browser"):
            db.save_sales_catalog_order(self.conn, self.admin_a, ["SKU-1"], {"version": 1}, expected_revision=0)
        with self.assertRaisesRegex(ValueError, "invalid SKU"):
            db.save_sales_catalog_order(self.conn, self.admin_b, [""], {"version": 1}, expected_revision=0)
        with self.assertRaisesRegex(ValueError, "too large"):
            db.save_sales_catalog_order(self.conn, self.admin_b, ["SKU"], {"version": 1, "title": "x" * 2_000_001}, expected_revision=0)

    def test_api_links_creator_and_prevents_another_admin_from_editing_customer(self):
        original_connect = db.connect
        db.connect = lambda *_args, **_kwargs: self.conn
        try:
            payload = main.api_admin_create_customer_user(
                email="api@example.com", name="API Buyer", role="overseas_customer", password="password123",
                permission_mode="allowlist", permission_scopes=["brand"], permission_values=["Craftsman Golf"],
                user={"id": self.admin_a, "role": "admin"},
            )
            self.assertEqual(payload["user"]["created_by_user_id"], self.admin_a)
            with self.assertRaises(HTTPException) as denied:
                main.api_admin_update_customer_user(
                    int(payload["user"]["id"]), name="Changed", role="overseas_customer", disabled=False,
                    permission_mode="allowlist", permission_scopes=["brand"], permission_values=["Craftsman Golf"],
                    user={"id": self.admin_b, "role": "admin"},
                )
            self.assertEqual(denied.exception.status_code, 403)
        finally:
            db.connect = original_connect


if __name__ == "__main__":
    unittest.main()
