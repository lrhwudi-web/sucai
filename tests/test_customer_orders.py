import asyncio
import io
import json
import os
import tempfile
import unittest
import zipfile
from contextlib import closing
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fastapi import HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from app import db, main
from app.inventory_source import InventoryLookup


def make_request(path: str = "/api/orders") -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "https",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [(b"host", b"pr.kairaygolf.com"), (b"x-forwarded-proto", b"https")],
            "client": ("127.0.0.1", 1234),
            "server": ("pr.kairaygolf.com", 443),
        }
    )


def workbook_bytes() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as workbook:
        workbook.writestr("[Content_Types].xml", "<Types />")
        workbook.writestr("xl/workbook.xml", "<workbook />")
        workbook.writestr("xl/media/image1.jpeg", b"picture")
        workbook.writestr("xl/worksheets/sheet1.xml", '<f>G3*H3</f>')
    return output.getvalue()


class CustomerOrderTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.original_db_path = db.DB_PATH
        self.original_order_dir = main.CUSTOMER_ORDER_DIR
        self.original_send = main.dingtalk_auth.send_work_notification
        self.original_inventory_lookup = main.inventory_source.lookup_available_inventory
        self.original_env = {name: os.environ.get(name) for name in ("DINGTALK_CLIENT_ID", "DINGTALK_CLIENT_SECRET", "DINGTALK_AGENT_ID", "DINGTALK_REDIRECT_URI")}
        db.DB_PATH = self.root / "orders.db"
        main.CUSTOMER_ORDER_DIR = self.root / "order-files"
        os.environ.update({
            "DINGTALK_CLIENT_ID": "client-id",
            "DINGTALK_CLIENT_SECRET": "client-secret",
            "DINGTALK_AGENT_ID": "123456",
            "DINGTALK_REDIRECT_URI": "https://pr.kairaygolf.com/auth/dingtalk/callback",
        })
        main.inventory_source.lookup_available_inventory = lambda _skus, _salesperson="": InventoryLookup(
            {"SKU-001": 10, "SKU-002": 10}, "live", "2026-09-11T16:30:00+08:00"
        )
        with closing(db.connect()) as conn:
            db.init_db(conn)
            self.salesperson_id = db.create_user(conn, "sales@example.com", "业务员甲", "admin", "password123")
            self.other_salesperson_id = db.create_user(conn, "other@example.com", "业务员乙", "admin", "password123")
            self.super_admin_id = db.create_user(conn, "super@example.com", "超级管理员", "super_admin", "password123")
            customer = db.create_customer_user_with_permissions(
                conn,
                "buyer@example.com",
                "上海客户",
                "overseas_customer",
                "password123",
                created_by_user_id=self.salesperson_id,
            )
            self.customer_id = int(customer["id"])
            conn.execute(
                """
                INSERT INTO user_identities(
                  user_id, provider, provider_subject, provider_user_id, display_name
                ) VALUES (?, 'dingtalk', 'sales-subject', 'ding-sales-001', '业务员甲')
                """,
                (self.salesperson_id,),
            )
            conn.commit()
            self.customer = conn.execute("SELECT * FROM users WHERE id=?", (self.customer_id,)).fetchone()
            self.salesperson = conn.execute("SELECT * FROM users WHERE id=?", (self.salesperson_id,)).fetchone()
            self.other_salesperson = conn.execute("SELECT * FROM users WHERE id=?", (self.other_salesperson_id,)).fetchone()
            self.super_admin = conn.execute("SELECT * FROM users WHERE id=?", (self.super_admin_id,)).fetchone()

    def tearDown(self):
        db.DB_PATH = self.original_db_path
        main.CUSTOMER_ORDER_DIR = self.original_order_dir
        main.dingtalk_auth.send_work_notification = self.original_send
        main.inventory_source.lookup_available_inventory = self.original_inventory_lookup
        for name, value in self.original_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        self.temp.cleanup()

    def submit(self, key: str = "requestkey001", payload: bytes | None = None):
        return asyncio.run(
            main.api_create_customer_order(
                request=make_request(),
                idempotency_key=key,
                title="September order",
                company="Shanghai Golf",
                contact="buyer@example.com",
                reference="PO-009",
                currency="USD",
                product_count=2,
                total_quantity=12,
                total_amount_cents=34500,
                unpriced_count=0,
                items_json=json.dumps([
                    {"sku": "SKU-001", "name": "Driver Cover", "quantity": 5, "unitPriceCents": 1200, "amountCents": 6000, "imageUrl": "/thumb/file-001"},
                    {"sku": "SKU-002", "name": "Putter Cover", "quantity": 7, "unitPriceCents": None, "amountCents": None, "imageUrl": "https://example.test/external.jpg"},
                ]),
                excel_file=UploadFile(file=io.BytesIO(payload if payload is not None else workbook_bytes()), filename="catalog.xlsx"),
                user=self.customer,
            )
        )

    def test_submission_is_immutable_idempotent_and_notifies_only_creator(self):
        sent = {}

        def fake_send(user_ids, content, client_id, client_secret, agent_id):
            sent.update({"user_ids": user_ids, "content": content, "agent_id": agent_id})
            return {"task_id": "task-001", "recipient_count": len(user_ids)}

        main.dingtalk_auth.send_work_notification = fake_send
        original_workbook = workbook_bytes()
        first = self.submit(payload=original_workbook)
        order = first["order"]
        self.assertTrue(first["created"])
        self.assertEqual(sent["user_ids"], ["ding-sales-001"])
        self.assertIn("上海客户", sent["content"])
        self.assertIn("/api/orders/", sent["content"])
        self.assertEqual(order["file_name"].split("_")[0], "上海客户")
        self.assertTrue(order["file_name"].endswith(".xlsx"))
        self.assertEqual(order["status"], "new")
        self.assertEqual([item["sku"] for item in order["items"]], ["SKU-001", "SKU-002"])
        self.assertEqual(order["items"][0]["image_url"], "/thumb/file-001")
        self.assertEqual(order["items"][1]["image_url"], "")

        original_current_user = main.current_user
        main.current_user = lambda _request: self.customer
        try:
            customer_download = main.api_download_customer_order(order["id"], make_request(), "")
            self.assertIsInstance(customer_download, FileResponse)
        finally:
            main.current_user = original_current_user
        self.assertEqual(main.api_customer_order(order["id"], self.customer)["order"]["status"], "new")

        token = parse_qs(urlparse(sent["content"].split("下载 Excel：", 1)[1]).query)["token"][0]
        response = main.api_download_customer_order(order["id"], make_request(f"/api/orders/{order['id']}/download"), token)
        self.assertIsInstance(response, FileResponse)
        self.assertEqual(Path(response.path).read_bytes(), original_workbook)
        self.assertIn("attachment", response.headers["content-disposition"])
        confirmed = main.api_customer_order(order["id"], self.salesperson)["order"]
        self.assertEqual(confirmed["status"], "confirmed")
        self.assertTrue(confirmed["confirmed_at"])

        second = self.submit(payload=b"not-an-excel")
        self.assertFalse(second["created"])
        self.assertEqual(second["order"]["id"], order["id"])
        self.assertEqual(len(main.api_customer_orders(self.customer)["orders"]), 1)
        self.assertEqual(len(main.api_customer_orders(self.salesperson)["orders"]), 1)
        self.assertEqual(main.api_customer_orders(self.other_salesperson)["orders"], [])
        self.assertEqual(len(main.api_customer_orders(self.super_admin)["orders"]), 1)
        self.assertEqual(main.api_customer_order(order["id"], self.super_admin)["order"]["id"], order["id"])
        main.current_user = lambda _request: self.super_admin
        try:
            super_download = main.api_download_customer_order(order["id"], make_request(), "")
            self.assertIsInstance(super_download, FileResponse)
        finally:
            main.current_user = original_current_user

        with self.assertRaises(HTTPException) as denied:
            main.api_customer_order(order["id"], self.other_salesperson)
        self.assertEqual(denied.exception.status_code, 404)
        with self.assertRaises(HTTPException) as denied_download:
            main.api_download_customer_order(order["id"], make_request(), "wrong-token")
        self.assertEqual(denied_download.exception.status_code, 401)

    def test_notification_failure_does_not_lose_order(self):
        main.dingtalk_auth.send_work_notification = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("offline"))
        result = self.submit("requestkey002")
        self.assertTrue(result["created"])
        self.assertEqual(result["order"]["notification_status"], "failed")
        self.assertIn("notification_warning", result)
        self.assertTrue((main.CUSTOMER_ORDER_DIR / next(main.CUSTOMER_ORDER_DIR.iterdir()).name).is_file())

    def test_salesperson_download_confirms_new_order(self):
        main.dingtalk_auth.send_work_notification = lambda *_args, **_kwargs: {"task_id": "task-002"}
        order = self.submit("requestkey005")["order"]
        self.assertEqual(order["status"], "new")
        original_current_user = main.current_user
        main.current_user = lambda _request: self.salesperson
        try:
            response = main.api_download_customer_order(order["id"], make_request(), "")
            self.assertIsInstance(response, FileResponse)
        finally:
            main.current_user = original_current_user
        confirmed = main.api_customer_order(order["id"], self.salesperson)["order"]
        self.assertEqual(confirmed["status"], "confirmed")
        self.assertTrue(confirmed["confirmed_at"])

    def test_pending_order_notification_count_is_scoped_and_clears_on_confirmation(self):
        main.dingtalk_auth.send_work_notification = lambda *_args, **_kwargs: {"task_id": "task-count"}
        order = self.submit("requestkey007")["order"]

        self.assertEqual(main.api_pending_customer_order_count(self.salesperson)["pending_count"], 1)
        self.assertEqual(main.api_pending_customer_order_count(self.other_salesperson)["pending_count"], 0)
        self.assertEqual(main.api_pending_customer_order_count(self.super_admin)["pending_count"], 1)

        original_current_user = main.current_user
        main.current_user = lambda _request: self.salesperson
        try:
            main.api_download_customer_order(order["id"], make_request(), "")
        finally:
            main.current_user = original_current_user

        self.assertEqual(main.api_pending_customer_order_count(self.salesperson)["pending_count"], 0)
        self.assertEqual(main.api_pending_customer_order_count(self.super_admin)["pending_count"], 0)

    def test_rejects_order_quantity_above_current_inventory(self):
        main.inventory_source.lookup_available_inventory = lambda _skus, _salesperson="": InventoryLookup(
            {"SKU-001": 4, "SKU-002": 10}, "live", "2026-09-11T16:31:00+08:00"
        )
        with self.assertRaises(HTTPException) as rejected:
            self.submit("requestkey006")
        self.assertEqual(rejected.exception.status_code, 409)
        self.assertIn("SKU-001", str(rejected.exception.detail))
        self.assertIn("inventory (4)", str(rejected.exception.detail))
        self.assertFalse(main.CUSTOMER_ORDER_DIR.exists())

    def test_rejects_non_xlsx_and_unassigned_customer(self):
        main.dingtalk_auth.send_work_notification = lambda *_args, **_kwargs: {"task_id": "unused"}
        with self.assertRaises(HTTPException) as invalid:
            self.submit("requestkey003", b"not-an-excel")
        self.assertEqual(invalid.exception.status_code, 400)
        with closing(db.connect()) as conn:
            unassigned = db.create_customer_user_with_permissions(
                conn, "legacy@example.com", "Legacy", "overseas_customer", "password123"
            )
        with self.assertRaises(HTTPException) as unassigned_error:
            asyncio.run(
                main.api_create_customer_order(
                    request=make_request(), idempotency_key="requestkey004", title="Order", company="", contact="", reference="",
                    currency="USD", product_count=1, total_quantity=1, total_amount_cents=0, unpriced_count=1,
                    items_json="[]",
                    excel_file=UploadFile(file=io.BytesIO(workbook_bytes()), filename="order.xlsx"), user=unassigned,
                )
            )
        self.assertEqual(unassigned_error.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
