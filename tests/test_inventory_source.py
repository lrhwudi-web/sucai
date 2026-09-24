import unittest
from datetime import datetime

from app.inventory_source import InventoryConfig, InventoryReader


class FakeCursor:
    def __init__(self, rows, product_rows, statements):
        self.rows = rows
        self.product_rows = product_rows
        self.statements = statements
        self.current_rows = rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def execute(self, query, args):
        self.statements.append((query, args))
        self.current_rows = self.product_rows if "FROM products" in query else self.rows

    def fetchall(self):
        return self.current_rows


class FakeConnection:
    def __init__(self, rows, statements, product_rows=None):
        self.rows = rows
        self.product_rows = product_rows or []
        self.statements = statements
        self.closed = False

    def cursor(self):
        return FakeCursor(self.rows, self.product_rows, self.statements)

    def close(self):
        self.closed = True


class InventorySourceTest(unittest.TestCase):
    def setUp(self):
        self.config = InventoryConfig("db", 3306, "reader", "secret", "inventory", cache_seconds=60)

    def test_reads_latest_warehouse_checkpoints_and_available_stock(self):
        statements = []
        connection = FakeConnection(
            [
                (
                    "5902160", 146, 0,
                    '[{"qty":0,"name":"181-365天库龄"},{"qty":0,"name":"366天以上库龄"}]',
                    0, 0, datetime(2026, 9, 8, 9, 18, 22),
                ),
                (
                    "5902211", 27, 8,
                    '[{"qty":3,"name":"181-365天库龄"},{"qty":5,"name":"366天以上库龄"}]',
                    2, 1, datetime(2026, 9, 8, 9, 18, 21),
                ),
            ],
            statements,
        )
        reader = InventoryReader(self.config, connector=lambda: connection, clock=lambda: 10)

        result = reader.lookup(["5902160", "5902211"], "黄彩丽")

        self.assertEqual(result.values, {"5902160": 146, "5902211": 27})
        self.assertEqual(result.metrics["5902211"].sales_warehouse, 8)
        self.assertEqual(result.metrics["5902211"].sales_age_181_365, 3)
        self.assertEqual(result.metrics["5902211"].sales_age_366_plus, 5)
        self.assertEqual(result.metrics["5902211"].pending_qc, 2)
        self.assertEqual(result.metrics["5902211"].pending_arrival, 1)
        self.assertEqual(result.sales_warehouse_name, "黄彩丽")
        self.assertEqual(result.state, "live")
        self.assertEqual(result.updated_at, "2026-09-08T09:18:22")
        query, args = statements[0]
        self.assertIn("stage = 'local-inventory'", query)
        self.assertIn("product_valid_num", query)
        self.assertIn("product_qc_num", query)
        self.assertIn("quantity_receive", query)
        self.assertIn("stock_age_list_json", query)
        self.assertIn("CONCAT(%s, '仓库')", query)
        self.assertIn("ROW_NUMBER() OVER", query)
        self.assertEqual(args, ("黄彩丽", "黄彩丽", "黄彩丽", "黄彩丽", "5902160", "5902211"))
        self.assertTrue(connection.closed)

    def test_cache_avoids_repeat_queries_and_keeps_zero_stock(self):
        statements = []
        connection = FakeConnection([("ABC", 0, 0, None, 0, 0, datetime(2026, 9, 8, 9, 0, 0))], statements)
        reader = InventoryReader(self.config, connector=lambda: connection, clock=lambda: 20)

        first = reader.lookup(["abc"])
        second = reader.lookup(["ABC"])

        self.assertEqual(first.values, {"ABC": 0})
        self.assertEqual(second.values, {"ABC": 0})
        self.assertEqual(len(statements), 2)

    def test_reads_product_name_and_listing_date(self):
        connection = FakeConnection(
            [("ABC", 7, 0, None, 0, 0, datetime(2026, 9, 8, 9, 0, 0))],
            [],
            product_rows=[("ABC", "Chinese product name", datetime(2025, 10, 8, 17, 33, 20))],
        )
        reader = InventoryReader(self.config, connector=lambda: connection, clock=lambda: 20)

        result = reader.lookup(["ABC"])

        self.assertEqual(result.product_metadata["ABC"].chinese_name, "Chinese product name")
        self.assertEqual(result.product_metadata["ABC"].listing_date, "2025-10-08")

    def test_returns_stale_values_when_refresh_temporarily_fails(self):
        calls = 0

        def connector():
            nonlocal calls
            calls += 1
            if calls > 1:
                raise TimeoutError("inventory database unavailable")
            return FakeConnection([("ABC", 12, 0, None, 0, 0, datetime(2026, 9, 8, 8, 0, 0))], [])

        moments = iter([0, 61])
        reader = InventoryReader(self.config, connector=connector, clock=lambda: next(moments))

        self.assertEqual(reader.lookup(["ABC"]).state, "live")
        stale = reader.lookup(["ABC"])
        self.assertEqual(stale.state, "stale")
        self.assertEqual(stale.values, {"ABC": 12})

    def test_missing_configuration_disables_inventory_without_connecting(self):
        reader = InventoryReader(InventoryConfig("", 3306, "", "", ""), connector=lambda: self.fail("must not connect"))
        self.assertEqual(reader.lookup(["ABC"]).state, "disabled")

    def test_cache_is_isolated_by_sales_account_warehouse(self):
        statements = []

        def connector():
            warehouse = "黄彩丽" if not statements else "吴静"
            quantity = 8 if warehouse == "黄彩丽" else 21
            return FakeConnection([("ABC", 50, quantity, None, 0, 0, datetime(2026, 9, 8, 9, 0, 0))], statements)

        reader = InventoryReader(self.config, connector=connector, clock=lambda: 20)
        yellow = reader.lookup(["ABC"], "黄彩丽")
        wu = reader.lookup(["ABC"], "吴静")

        self.assertEqual(yellow.metrics["ABC"].sales_warehouse, 8)
        self.assertEqual(wu.metrics["ABC"].sales_warehouse, 21)
        self.assertEqual(len(statements), 4)


if __name__ == "__main__":
    unittest.main()
