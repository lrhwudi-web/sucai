import unittest
from unittest import mock

from app import main


class CatalogLoadingPerformanceTest(unittest.TestCase):
    def setUp(self):
        main.clear_product_catalog_snapshots()

    def tearDown(self):
        main.clear_product_catalog_snapshots()

    def test_followup_pages_reuse_the_first_catalog_snapshot(self):
        products = [{"sku": str(index)} for index in range(5)]
        built = {"products": products, "stats": {"products": 5, "files": 10, "images": 8, "videos": 2}}

        with mock.patch.object(main, "build_product_catalog_snapshot", return_value=built) as build:
            first = main.product_catalog_page("super_admin", "", "", "", "", "", 2, 0, user_id=7)
            second = main.product_catalog_page(
                "super_admin", "", "", "", "", "", 2, 2,
                user_id=7,
                snapshot_token=first["snapshot_token"],
            )

        self.assertEqual([item["sku"] for item in first["products"]], ["0", "1"])
        self.assertEqual([item["sku"] for item in second["products"]], ["2", "3"])
        self.assertEqual(first["snapshot_token"], second["snapshot_token"])
        build.assert_called_once()

    def test_snapshot_cannot_be_reused_by_another_user(self):
        built = {"products": [{"sku": "1"}], "stats": {"products": 1, "files": 1, "images": 1, "videos": 0}}

        with mock.patch.object(main, "build_product_catalog_snapshot", return_value=built) as build:
            first = main.product_catalog_page("super_admin", "", "", "", "", "", 1, 0, user_id=7)
            main.product_catalog_page(
                "super_admin", "", "", "", "", "", 1, 0,
                user_id=8,
                snapshot_token=first["snapshot_token"],
            )

        self.assertEqual(build.call_count, 2)

    def test_parallel_loads_for_one_user_keep_both_snapshot_tokens_valid(self):
        built = {"products": [{"sku": "1"}, {"sku": "2"}], "stats": {"products": 2, "files": 2, "images": 2, "videos": 0}}

        with mock.patch.object(main, "build_product_catalog_snapshot", return_value=built) as build:
            first_tab = main.product_catalog_page("super_admin", "", "", "", "", "", 1, 0, user_id=7)
            second_tab = main.product_catalog_page("super_admin", "", "", "", "", "", 1, 0, user_id=7)
            main.product_catalog_page(
                "super_admin", "", "", "", "", "", 1, 1,
                user_id=7,
                snapshot_token=first_tab["snapshot_token"],
            )
            main.product_catalog_page(
                "super_admin", "", "", "", "", "", 1, 1,
                user_id=7,
                snapshot_token=second_tab["snapshot_token"],
            )

        self.assertEqual(build.call_count, 2)

    def test_frontend_renders_the_first_page_before_background_paging_finishes(self):
        service = (main.Path("app/fontend/src/services/materials.ts")).read_text(encoding="utf-8")
        app_source = (main.Path("app/fontend/src/App.tsx")).read_text(encoding="utf-8")

        self.assertIn("catalog_snapshot", service)
        self.assertIn("onProgress", service)
        self.assertIn("onProgress?.([...products])", service)
        self.assertIn("loadProducts((partialProducts) =>", app_source)
        self.assertIn("setProducts(partialProducts);", app_source)
        self.assertIn("setLoading(false)", app_source)


if __name__ == "__main__":
    unittest.main()
