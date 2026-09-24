import tempfile
import unittest
from pathlib import Path

from app import db, nas_imports
from app.main import product_cards


class ProductMetadataTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(Path(self.tmp.name) / "test.db")
        db.init_db(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_mytag_catalog_imports_real_set_members(self):
        rows = self.conn.execute(
            "SELECT sku, set_code FROM sku_meta WHERE set_code='Set00264' ORDER BY sku"
        ).fetchall()

        self.assertEqual(
            [row["sku"] for row in rows],
            ["6015393", "6015394", "6015395", "6015396", "6015397", "6016124"],
        )

    def test_product_cards_receive_set_metadata(self):
        self.conn.execute(
            """
            INSERT INTO files(id, name, mime_type, path, sku, brand, category, asset_type)
            VALUES ('file-1', '1.jpg', 'image/jpeg', '04 Product Images/Craftsman Golf/6015397/1.jpg',
                    '6015397', 'Craftsman Golf', 'Driver Cover', 'image')
            """
        )
        self.conn.commit()

        row = db.search_files(self.conn, "admin", q="6015397", limit=10)[0]

        self.assertEqual(row["set_code"], "Set00264")

    def test_admin_selected_cover_is_persisted_and_missing_cover_falls_back(self):
        self.conn.executemany(
            """
            INSERT INTO files(id, name, mime_type, path, sku, brand, category, asset_type)
            VALUES (?, ?, 'image/jpeg', ?, 'SKU-COVER', 'Kairay Golf', 'Driver Cover', 'image')
            """,
            [
                ("cover-1", "1.jpg", "Kairay Golf/Driver Cover/SKU-COVER/1.jpg"),
                ("cover-2", "2.jpg", "Kairay Golf/Driver Cover/SKU-COVER/2.jpg"),
            ],
        )
        self.conn.commit()

        db.set_product_cover(self.conn, "sku-cover", "cover-2")
        rows = db.sku_files(self.conn, "SKU-COVER", "admin")
        self.assertEqual(product_cards(rows)[0]["cover_id"], "cover-2")
        self.assertEqual(
            self.conn.execute("SELECT cover_file_id FROM sku_meta WHERE sku='SKU-COVER'").fetchone()["cover_file_id"],
            "cover-2",
        )

        self.conn.execute("UPDATE sku_meta SET cover_file_id='missing' WHERE sku='SKU-COVER'")
        self.conn.commit()
        self.assertEqual(product_cards(db.sku_files(self.conn, "SKU-COVER", "admin"))[0]["cover_id"], "cover-1")

    def test_cover_must_be_an_image_from_the_same_product(self):
        self.conn.execute(
            """
            INSERT INTO files(id, name, mime_type, path, sku, brand, category, asset_type)
            VALUES ('video-1', 'clip.mp4', 'video/mp4', 'Kairay Golf/SKU-VIDEO/clip.mp4',
                    'SKU-VIDEO', 'Kairay Golf', 'Video', 'video')
            """
        )
        self.conn.commit()

        with self.assertRaisesRegex(ValueError, "Only an image"):
            db.set_product_cover(self.conn, "SKU-VIDEO", "video-1")
        with self.assertRaisesRegex(ValueError, "does not belong"):
            db.set_product_cover(self.conn, "ANOTHER-SKU", "video-1")

    def test_admin_can_bulk_assign_or_clear_set(self):
        count = db.update_product_metadata(
            self.conn,
            ["6015393", "6015394"],
            set_code="set 00321",
            update_set=True,
        )
        rows = self.conn.execute(
            "SELECT sku, set_code FROM sku_meta WHERE sku IN ('6015393','6015394') ORDER BY sku"
        ).fetchall()

        self.assertEqual(count, 2)
        self.assertTrue(all(row["set_code"] == "Set00321" for row in rows))

        db.update_product_metadata(self.conn, ["6015393"], set_code="", update_set=True)
        cleared = self.conn.execute("SELECT set_code FROM sku_meta WHERE sku='6015393'").fetchone()
        self.assertEqual(cleared["set_code"], "")

    def test_intake_metadata_is_written_to_sku_meta_on_upload(self):
        self.conn.execute(
            """
            INSERT INTO nas_imports(
              local_path, rel_path, name, size, mtime_ns, sha256, status,
              final_sku, final_english_name, final_drive_folder, final_drive_name,
              final_asset_type, final_set_code,
              final_themes, themes_updated
            ) VALUES (
              'local.jpg', 'batch/local.jpg', 'local.jpg', 1, 1, 'hash', 'suggested',
              '6999999', 'Test Driver Cover', '04 Product Images/Craftsman Golf/Test', '6999999.jpg',
              'image', 'Set00264',
              'AMERICANA|ANIMALS', 1
            )
            """
        )
        import_id = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.conn.commit()

        nas_imports.mark_uploaded(self.conn, import_id, "6999999", "Test Driver Cover", "drive-file", 1)
        meta = self.conn.execute("SELECT set_code, themes FROM sku_meta WHERE sku='6999999'").fetchone()

        self.assertEqual(meta["set_code"], "Set00264")
        self.assertEqual(meta["themes"], "AMERICANA|ANIMALS")

    def test_batch_settings_apply_before_ai_fields_are_ready(self):
        self.conn.executemany(
            """
            INSERT INTO nas_imports(local_path, rel_path, name, size, mtime_ns, sha256)
            VALUES (?, ?, ?, 1, 1, ?)
            """,
            [
                ("one.jpg", "batch/one.jpg", "one.jpg", "batch-hash-1"),
                ("two.jpg", "batch/two.jpg", "two.jpg", "batch-hash-2"),
            ],
        )
        self.conn.commit()
        ids = [row[0] for row in self.conn.execute("SELECT id FROM nas_imports ORDER BY id")]

        count = nas_imports.apply_batch_settings(
            self.conn,
            ids,
            drive_folder="04 Product Images/01 Craftsman Golf/01 Headcover Set",
            set_code="Set00264",
            category_tags="MODEL_DF21|PLUSH_ANIMAL",
            themes="AMERICANA|LIMITED_EDITION",
            update_themes=True,
        )
        rows = self.conn.execute(
            """
            SELECT final_drive_folder, final_set_code,
                   final_category_tags, final_themes, themes_updated
            FROM nas_imports ORDER BY id
            """
        ).fetchall()

        self.assertEqual(count, 2)
        self.assertTrue(all(row["final_set_code"] == "Set00264" for row in rows))
        self.assertTrue(all(row["final_category_tags"] == "MODEL_DF21|PLUSH_ANIMAL" for row in rows))
        self.assertTrue(all(row["final_themes"] == "AMERICANA|LIMITED_EDITION" for row in rows))
        self.assertTrue(all(row["themes_updated"] == 1 for row in rows))
        self.assertTrue(all(row["final_drive_folder"].endswith("01 Headcover Set") for row in rows))


if __name__ == "__main__":
    unittest.main()
