import sqlite3
import tempfile
import unittest
from pathlib import Path

from app import db, nas_imports, product_taxonomy
from app.main import product_cards


class ProductTaxonomyIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(Path(self.tmp.name) / "taxonomy.db")
        db.init_db(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_registry_seeds_all_skus_and_review_statuses(self):
        counts = dict(
            self.conn.execute(
                """
                SELECT category_status, COUNT(*)
                FROM sku_meta
                WHERE taxonomy_version='2.0.0'
                GROUP BY category_status
                """
            ).fetchall()
        )

        self.assertEqual(counts["verified"], 2571)
        self.assertEqual(counts["needs_review"], 64)
        self.assertEqual(sum(counts.values()), 2635)

    def test_fixed_model_rules_and_plush_tag_are_preserved(self):
        df3 = product_taxonomy.classify_product(self.conn, name="黑色 DF3 毛绒推杆套")
        oz1 = product_taxonomy.classify_product(self.conn, name="白色 OZ.1i HS 推杆套")

        self.assertEqual(df3["category_id"], "HC_PLUSH")
        self.assertIn("MODEL_DF3", df3["tags"])
        self.assertIn("PLUSH_ANIMAL", df3["tags"])
        self.assertEqual(oz1["category_id"], "HC_PUTTER_MALLET_SMALL")

    def test_customer_product_card_uses_canonical_english_category(self):
        self.conn.execute(
            """
            INSERT INTO files(id, name, mime_type, path, sku, brand, category, asset_type)
            VALUES (
              'taxonomy-file', '1.jpg', 'image/jpeg',
              '04 Product Images/01 Craftsman Golf/Old Folder/6015196/1.jpg',
              '6015196', '01 Craftsman Golf', 'Old Folder', 'image'
            )
            """
        )
        self.conn.commit()

        row = db.search_files(self.conn, "admin", q="6015196", limit=10)[0]
        card = product_cards([row])[0]

        self.assertEqual(row["display_category"], "Mallet Putter Covers")
        self.assertEqual(card["category"], "Mallet Putter Covers")

    def test_product_catalog_import_keeps_canonical_english_category(self):
        before = self.conn.execute(
            "SELECT category, category_id FROM sku_meta WHERE sku='6000576'"
        ).fetchone()
        self.assertEqual(
            (before["category"], before["category_id"]),
            ("Driver Covers", "HC_DRIVER"),
        )

        db.import_product_catalog_csv(
            self.conn,
            "\n".join(
                [
                    "sku,english_name,chinese_name,brand,category,set_code,source_sheet",
                    "6000576,Patriot Driver Cover,爱国者一号木杆套,Craftsman Golf,1号木杆套,,MyTag",
                ]
            ),
        )

        after = self.conn.execute(
            "SELECT category, category_id FROM sku_meta WHERE sku='6000576'"
        ).fetchone()
        self.assertEqual(
            (after["category"], after["category_id"]),
            ("Driver Covers", "HC_DRIVER"),
        )

    def test_fixed_themes_are_manually_assignable_and_exposed_to_customers(self):
        expected = [
            "Americana",
            "Lucky & Clover",
            "Pop Culture & Entertainment",
            "Food & Drinks",
            "Animals",
            "Women's & Girls",
            "Skulls & Gothic",
            "Classic & Retro",
            "Limited Edition",
        ]
        self.assertEqual([item["label"] for item in product_taxonomy.theme_options()], expected)
        self.assertEqual(
            product_taxonomy.normalize_themes(["LIMITED_EDITION", "AMERICANA"]),
            "AMERICANA|LIMITED_EDITION",
        )
        with self.assertRaisesRegex(ValueError, "Unknown theme"):
            product_taxonomy.normalize_themes(["NOT_A_THEME"])

        self.conn.execute(
            """
            INSERT INTO files(id, name, mime_type, path, sku, brand, category, asset_type)
            VALUES (
              'theme-file', '1.jpg', 'image/jpeg',
              '04 Product Images/01 Craftsman Golf/Driver Covers/THEME-1/1.jpg',
              'THEME-1', 'Craftsman Golf', 'Driver Covers', 'image'
            )
            """
        )
        db.update_product_metadata(
            self.conn,
            ["THEME-1"],
            themes="AMERICANA|LIMITED_EDITION",
            update_themes=True,
        )

        metadata = db.list_product_metadata(self.conn, q="THEME-1")
        self.assertEqual(metadata["products"][0]["themes"], "AMERICANA|LIMITED_EDITION")
        self.assertEqual(metadata["theme_options"], product_taxonomy.theme_options())
        card = product_cards(db.search_files(self.conn, "admin", q="THEME-1"))[0]
        self.assertEqual(card["themes"], ["Americana", "Limited Edition"])

    def test_drive_registry_sync_does_not_overwrite_manual_themes(self):
        db.update_product_metadata(
            self.conn,
            ["6015196"],
            themes="ANIMALS|CLASSIC_RETRO",
            update_themes=True,
        )
        product_taxonomy.import_registry(self.conn)
        row = self.conn.execute(
            "SELECT themes FROM sku_meta WHERE sku='6015196'"
        ).fetchone()

        self.assertEqual(row["themes"], "ANIMALS|CLASSIC_RETRO")

    def test_admin_can_create_and_assign_a_custom_theme(self):
        created = product_taxonomy.create_custom_theme(
            self.conn,
            label="Summer Campaign",
            created_by=1,
        )
        self.assertEqual(created["label"], "Summer Campaign")
        self.assertTrue(created["id"].startswith("CUSTOM_SUMMER_CAMPAIGN"))
        with self.assertRaisesRegex(ValueError, "already exists"):
            product_taxonomy.create_custom_theme(
                self.conn,
                label="summer campaign",
                created_by=1,
            )

        self.conn.execute(
            """
            INSERT INTO files(id, name, mime_type, path, sku, brand, category, asset_type)
            VALUES (
              'custom-theme-file', '1.jpg', 'image/jpeg',
              '04 Product Images/01 Craftsman Golf/Driver Covers/CUSTOM-1/1.jpg',
              'CUSTOM-1', 'Craftsman Golf', 'Driver Covers', 'image'
            )
            """
        )
        db.update_product_metadata(
            self.conn,
            ["CUSTOM-1"],
            themes=created["id"],
            update_themes=True,
        )

        options = product_taxonomy.theme_options(self.conn)
        metadata = db.list_product_metadata(self.conn, q="CUSTOM-1")
        card = product_cards(
            db.search_files(self.conn, "admin", q="CUSTOM-1"),
            options,
        )[0]
        self.assertIn(created, metadata["theme_options"])
        self.assertEqual(card["themes"], ["Summer Campaign"])

    def test_high_confidence_legacy_category_is_backfilled_but_event_is_not(self):
        self.conn.execute(
            """
            INSERT INTO files(id, name, mime_type, path, sku, brand, category, asset_type)
            VALUES
              (
                'legacy-driver', 'front.jpg', 'image/jpeg',
                '04 Product Images/01 Craftsman Golf/02 Driver Cover/6999999 Example/front.jpg',
                '6999999', 'Craftsman Golf', '02 Driver Cover', 'image'
              ),
              (
                'legacy-event', 'expo.jpg', 'image/jpeg',
                'Events/2026 USA PGA SHOW/expo.jpg',
                '2026 USA PGA SHOW', '', '', 'image'
              )
            """
        )
        updated = product_taxonomy.backfill_catalogue_categories(self.conn)
        driver = self.conn.execute(
            "SELECT category_id, category, category_status FROM sku_meta WHERE sku='6999999'"
        ).fetchone()
        event = self.conn.execute(
            "SELECT category_id, category_status FROM sku_meta WHERE sku='2026 USA PGA SHOW'"
        ).fetchone()

        self.assertEqual(updated, 1)
        self.assertEqual(
            (driver["category_id"], driver["category"], driver["category_status"]),
            ("HC_DRIVER", "Driver Covers", "verified"),
        )
        self.assertIsNone(event)

    def test_manual_correction_is_inherited_and_audit_is_append_only(self):
        db.update_product_metadata(
            self.conn,
            ["NEW-TAXONOMY-1"],
            category_id="HC_PUTTER_MALLET_SMALL",
            update_category=True,
            reviewer_id=1,
        )
        result = product_taxonomy.classify_product(
            self.conn,
            sku="NEW-TAXONOMY-1",
            name="1.jpg",
        )
        event = self.conn.execute(
            "SELECT id FROM category_correction_events WHERE sku='NEW-TAXONOMY-1'"
        ).fetchone()

        self.assertEqual(result["category_id"], "HC_PUTTER_MALLET_SMALL")
        self.assertEqual(result["source"], "human_correction")
        with self.assertRaises(sqlite3.DatabaseError):
            self.conn.execute(
                "UPDATE category_correction_events SET note='changed' WHERE id=?",
                (event["id"],),
            )

    def test_product_image_approval_requires_fixed_category(self):
        self.conn.execute(
            """
            INSERT INTO nas_imports(
              local_path, rel_path, name, size, mtime_ns, sha256, status,
              final_sku, final_english_name, final_drive_folder, final_drive_name,
              final_asset_type
            ) VALUES (
              'missing.jpg', '产品图片/missing.jpg', 'missing.jpg', 1, 1, 'missing-category',
              'suggested', 'NEW-0001', 'New Driver Cover',
              '04 Product Images/01 Craftsman Golf/02 Driver Cover/NEW-0001',
              'NEW-0001.jpg', 'image'
            )
            """
        )
        import_id = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.conn.commit()

        with self.assertRaisesRegex(ValueError, "category|分类"):
            nas_imports.approve_import(self.conn, import_id, "root", 1)

    def test_pending_imports_receive_category_without_ai_call(self):
        self.conn.execute(
            """
            INSERT INTO nas_imports(
              local_path, rel_path, name, size, mtime_ns, sha256,
              final_sku, final_english_name
            ) VALUES (
              'known.jpg', '产品图片/6015196/known.jpg', 'known.jpg', 1, 1,
              'known-category', '6015196', 'Known Putter Cover'
            )
            """
        )
        self.conn.commit()

        self.assertEqual(product_taxonomy.backfill_pending_imports(self.conn), 1)
        row = self.conn.execute(
            "SELECT * FROM nas_imports WHERE sha256='known-category'"
        ).fetchone()

        self.assertEqual(row["final_category_id"], "HC_PUTTER_MALLET_LARGE")
        self.assertEqual(row["category_source"], "sku_inheritance")
        self.assertEqual(row["category_needs_review"], 0)

    def test_customer_taxonomy_exposes_only_the_requested_two_groups(self):
        options = product_taxonomy.category_options(self.conn)
        labels_by_group: dict[str, list[str]] = {}
        for option in options:
            labels_by_group.setdefault(option["group"], []).append(option["label_en"])

        self.assertEqual(
            labels_by_group,
            {
                "Golf Headcover": [
                    "Plush Covers",
                    "Driver Covers",
                    "Fairway Covers",
                    "Hybrid Covers",
                    "Blade Putter Covers",
                    "Mallet Putter Covers",
                    "Mid-Mallet Putter Covers",
                    "Square Mallet Putter Covers",
                    "Iron Cover Sets",
                    "Wedge Cover Sets",
                    "Alignment Stick Covers",
                ],
                "Golf Accessories": [
                    "Divot Tools & Ball Markers",
                    "Scorecard Holders",
                    "Golf Towels",
                    "Golf Ball & Tee Pouchs",
                    "Valuables Pouches",
                    "Glove Caddie",
                    "Rangefinder Case",
                    "Others",
                ],
            },
        )

    def test_administrator_can_add_and_assign_a_category_inside_a_fixed_group(self):
        created = product_taxonomy.create_custom_category(
            self.conn,
            group="Golf Headcover",
            label_en="Junior Covers",
            label_zh="青少年杆套",
            created_by=1,
        )

        self.assertTrue(created["id"].startswith("CUSTOM_"))
        self.assertEqual(
            product_taxonomy.validate_category_id(created["id"], self.conn),
            created["id"],
        )
        db.update_product_metadata(
            self.conn,
            ["CUSTOM-0001"],
            category_id=created["id"],
            update_category=True,
            reviewer_id=1,
        )
        row = self.conn.execute(
            "SELECT category_id, category, category_zh FROM sku_meta WHERE sku='CUSTOM-0001'"
        ).fetchone()
        self.assertEqual(
            (row["category_id"], row["category"], row["category_zh"]),
            (created["id"], "Junior Covers", "青少年杆套"),
        )
        self.assertIn(created["id"], {item["id"] for item in product_taxonomy.category_options(self.conn)})
        with self.assertRaisesRegex(ValueError, "already exists"):
            product_taxonomy.create_custom_category(
                self.conn,
                group="Golf Accessories",
                label_en="junior covers",
            )

    def test_existing_plush_and_legacy_extension_categories_are_normalized(self):
        self.conn.executemany(
            """
            INSERT INTO sku_meta(sku, category, category_id, category_tags)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(sku) DO UPDATE SET
              category=excluded.category,
              category_id=excluded.category_id,
              category_tags=excluded.category_tags
            """,
            [
                ("LEGACY-PLUSH", "Driver Cover", "HC_DRIVER", "PLUSH_ANIMAL"),
                ("LEGACY-SET", "Headcover Set", "HC_SET", ""),
                ("LEGACY-HAT", "Hat", "APPAREL_HAT", ""),
            ],
        )

        product_taxonomy.normalize_existing_categories(self.conn)
        rows = {
            row["sku"]: (row["category_id"], row["category"])
            for row in self.conn.execute(
                "SELECT sku, category_id, category FROM sku_meta WHERE sku LIKE 'LEGACY-%'"
            ).fetchall()
        }
        self.assertEqual(rows["LEGACY-PLUSH"], ("HC_PLUSH", "Plush Covers"))
        self.assertEqual(rows["LEGACY-SET"], ("ACC_OTHER", "Others"))
        self.assertEqual(rows["LEGACY-HAT"], ("ACC_OTHER", "Others"))


if __name__ == "__main__":
    unittest.main()
