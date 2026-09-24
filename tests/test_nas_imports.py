import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

from app import db, nas_imports


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class NasImportsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old_env = {
            name: os.environ.get(name)
            for name in (
                "NAS_INBOX_DIR",
                "OPENAI_API_KEY",
                "OPENAI_MODEL",
                "DEEPSEEK_API_KEY",
                "DEEPSEEK_MODEL",
                "DEEPSEEK_BASE_URL",
                "AI_PROVIDER",
                "SYNOLOGY_URL",
                "SYNOLOGY_USER",
                "SYNOLOGY_PASSWORD",
                "SYNOLOGY_INBOX_PATH",
                "SYNOLOGY_GOOGLE_ROOT",
                "GOOGLE_DRIVE_INBOX_FOLDER_ID",
                "GOOGLE_DRIVE_INBOX_EXCLUDED_FOLDER_IDS",
            )
        }
        os.environ["NAS_INBOX_DIR"] = str(self.root)
        for name in (
            "OPENAI_API_KEY",
            "OPENAI_MODEL",
            "DEEPSEEK_API_KEY",
            "DEEPSEEK_MODEL",
            "DEEPSEEK_BASE_URL",
            "AI_PROVIDER",
            "SYNOLOGY_URL",
            "SYNOLOGY_USER",
            "SYNOLOGY_PASSWORD",
            "SYNOLOGY_INBOX_PATH",
            "SYNOLOGY_GOOGLE_ROOT",
            "GOOGLE_DRIVE_INBOX_FOLDER_ID",
            "GOOGLE_DRIVE_INBOX_EXCLUDED_FOLDER_IDS",
        ):
            os.environ.pop(name, None)

    def tearDown(self):
        for name, value in self.old_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        self.tmp.cleanup()

    def conn(self):
        conn = db.connect(self.root / "test.db")
        db.init_db(conn)
        return conn

    def test_overlapping_english_name_synchronizes_filename_and_product_folder_exactly(self):
        sku = "7203100"
        english_name = "Child Safety Booster Seat for Golf Cart"
        self.assertEqual(
            nas_imports.synchronize_product_drive_name(
                "7203100 Child Safety Booster Seat for Golf Carts (1).jpg",
                sku,
                english_name,
                english_name,
            ),
            "7203100 Child Safety Booster Seat for Golf Cart (1).jpg",
        )
        self.assertEqual(
            nas_imports.synchronize_product_drive_folder(
                "04 Product Images/01 Craftsman Golf/Golf Accessories/7203100 Child Safety Booster Seat for Golf Carts",
                sku,
                english_name,
                english_name,
            ),
            "04 Product Images/01 Craftsman Golf/Golf Accessories/7203100 Child Safety Booster Seat for Golf Cart",
        )

    def test_batch_identity_save_normalizes_legacy_accessories_path_and_name(self):
        conn = self.conn()
        conn.execute(
            """
            INSERT INTO nas_imports(
              local_path, rel_path, name, size, mtime_ns, sha256, status,
              final_sku, final_english_name, final_drive_folder, final_drive_name,
              final_category_id
            ) VALUES (
              'local', 'incoming/7203100/1.jpg', '1.jpg', 1, 1, 'accessory-sync', 'suggested',
              '7203100', 'Child Safety Booster Seat for Golf Cart',
              '04 Product Images/01 Craftsman Golf/06 Accessories/7203100 Child Safety Booster Seat for Golf Carts',
              '7203100 Child Safety Booster Seat for Golf Carts (1).jpg', 'ACC_OTHER'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO sku_meta(sku, english_name, brand, category_id)
            VALUES ('7203100', 'Child Safety Booster Seat for Golf Cart', 'Craftsman Golf', 'ACC_OTHER')
            ON CONFLICT(sku) DO UPDATE SET
              english_name=excluded.english_name,
              brand=excluded.brand,
              category_id=excluded.category_id
            """
        )
        conn.commit()
        row = nas_imports.list_imports(conn)[0]

        nas_imports.save_identities(
            conn,
            [row["id"]],
            "7203100",
            "Child Safety Booster Seat for Golf Cart",
            ["7203100 Child Safety Booster Seat for Golf Carts (1).jpg"],
            expected_revisions=[row["revision"]],
        )
        saved = nas_imports.get_import(conn, row["id"])

        self.assertEqual(
            saved["final_drive_name"],
            "7203100 Child Safety Booster Seat for Golf Cart (1).jpg",
        )
        self.assertEqual(
            saved["final_drive_folder"],
            "04 Product Images/01 Craftsman Golf/Golf Accessories/7203100 CF - Child Safety Booster Seat for Golf Cart",
        )
        conn.close()

    def test_current_product_hierarchy_routes_set_members_to_fixed_categories(self):
        conn = self.conn()
        conn.executemany(
            """
            INSERT INTO sku_meta(sku, english_name, brand, category_id, set_code)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(sku) DO UPDATE SET
              english_name=excluded.english_name,
              brand=excluded.brand,
              category_id=excluded.category_id,
              set_code=excluded.set_code
            """,
            [
                ("7999001", "Lucky Driver Cover", "My Tag", "HC_DRIVER", ""),
                ("7999002", "Plain Driver Cover", "No Brand", "HC_DRIVER", ""),
                ("7999003", "Rose Blade Putter Cover", "Craftsman Golf", "HC_PUTTER_BLADE", "Set00999"),
                ("7999004", "Golf Swing Phone Holder", "Craftsman Golf", "ACC_OTHER", ""),
            ],
        )
        conn.commit()

        cases = [
            (
                "7999001", "Lucky Driver Cover", "HC_DRIVER",
                "04 Product Images/02 My Tag/03 Driver Cover/7999001 My Tag - Lucky Driver Cover",
            ),
            (
                "7999002", "Plain Driver Cover", "HC_DRIVER",
                "04 Product Images (No Brand)/03 Driver Cover/7999002 Plain Driver Cover",
            ),
            (
                "7999003", "Rose Blade Putter Cover", "HC_PUTTER_BLADE",
                "04 Product Images/01 Craftsman Golf/06 Blade Putter Cover/7999003 CF - Rose Blade Putter Cover",
            ),
            (
                "7999004", "Golf Swing Phone Holder", "ACC_OTHER",
                "04 Product Images/01 Craftsman Golf/Golf Accessories/7999004 CF - Golf Swing Phone Holder",
            ),
        ]
        for sku, english_name, category_id, expected in cases:
            self.assertEqual(
                nas_imports.canonical_product_drive_folder(
                    conn,
                    sku=sku,
                    english_name=english_name,
                    category_id=category_id,
                ),
                expected,
            )
        conn.close()

    def test_source_product_context_uses_the_deepest_sku_folder(self):
        big_teeth_path = (
            "临时/Big Teeth/帽套/推杆帽套/"
            "6016113Big Teeth 黑白PU拼接西服领结刺绣三片式双耳磁铁款大半圆DF3形体推杆套/1.jpg"
        )
        no_brand_path = (
            "临时/无牌/其他产品/果岭叉/"
            "5902330无牌 棕色姜饼人开瓶器果岭叉/1.jpg"
        )

        self.assertEqual(
            nas_imports.source_product_folder(big_teeth_path),
            "6016113Big Teeth 黑白PU拼接西服领结刺绣三片式双耳磁铁款大半圆DF3形体推杆套",
        )
        self.assertEqual(
            nas_imports.source_product_folder(no_brand_path),
            "5902330无牌 棕色姜饼人开瓶器果岭叉",
        )
        self.assertEqual(nas_imports.source_brand_hint(big_teeth_path), "Big Teeth")
        self.assertEqual(nas_imports.source_brand_hint(no_brand_path), "No Brand")

    def test_source_product_context_skips_a_pure_date_child_folder(self):
        source_path = (
            "临时/无牌/帽套/木杆帽套/"
            "6016394 无牌 绿色PU打鸭子刺绣两片式一号木帽套/20260803/1.jpg"
        )

        self.assertEqual(
            nas_imports.source_product_folder(source_path),
            "6016394 无牌 绿色PU打鸭子刺绣两片式一号木帽套",
        )
        self.assertEqual(
            nas_imports.sku_candidates(nas_imports.source_product_folder(source_path)),
            ["6016394"],
        )

    def test_company_owned_product_folder_overrides_unbranded_ancestor(self):
        source_path = (
            "\u4e34\u65f6/\u65e0\u724c/\u5176\u4ed6\u4ea7\u54c1/\u6d4b\u8ddd\u4eea\u5305/"
            "7203132\u81ea\u4e3b \u7eff\u8272\u683c\u5b50\u5370\u5237\u52a0\u7c89\u8272\u523a\u7ee3\u6d4b\u8ddd\u4eea\u5305/1.jpg"
        )
        product_folder = (
            "7203132\u81ea\u4e3b \u7eff\u8272\u683c\u5b50\u5370\u5237\u52a0\u7c89\u8272\u523a\u7ee3\u6d4b\u8ddd\u4eea\u5305"
        )

        self.assertEqual(nas_imports.source_product_folder(source_path), product_folder)
        self.assertEqual(nas_imports.source_brand_hint(source_path), "Craftsman Golf")

        conn = self.conn()
        self.assertEqual(
            nas_imports.canonical_product_drive_folder(
                conn,
                sku="7203132",
                english_name="Green & Pink Checkered Rangefinder Case",
                category_id="ACC_RANGEFINDER_CASE",
                source_path=source_path,
            ),
            "04 Product Images/01 Craftsman Golf/18 Range Finder Case/7203132 CF - Green & Pink Checkered Rangefinder Case",
        )
        prompt = nas_imports.suggestion_prompt(
            {"rel_path": source_path, "name": "1.jpg"},
            nas_imports.drive_catalog(conn, ["7203132"], source_path),
            ["7203132"],
        )
        self.assertIn("Source brand hint: Craftsman Golf", prompt)
        conn.close()

    def test_chinese_caesar_product_folder_overrides_unbranded_ancestor_and_set(self):
        source_path = (
            "\u4e34\u65f6/\u65e0\u724c/\u5e3d\u5957/\u6728\u6746\u5e3d\u5957/"
            "6017781 \u51ef\u8d5b \u6df1\u84dd\u8272\u4eff\u76ae\u9769PU\u7b80\u5355\u6b3e\u8d34\u7247\u4e09\u7247\u5f0f\u5e3d\u59574PCS(135X)/"
            "6017008 \u51ef\u8d5b \u6df1\u84dd\u8272\u4eff\u76ae\u9769PU\u7b80\u5355\u6b3e\u8d34\u7247\u4e09\u7247\u5f0f3\u53f7\u6728\u5e3d\u5957/1.jpg"
        )
        wrong_suggestion = (
            "04 Product Images (No Brand)/01 Headcover Set/"
            "Set00299 Vintage Navy Headcover Set/6017008 Vintage Navy Fairway Cover # 3"
        )

        self.assertEqual(
            nas_imports.source_product_folder(source_path),
            "6017008 \u51ef\u8d5b \u6df1\u84dd\u8272\u4eff\u76ae\u9769PU\u7b80\u5355\u6b3e\u8d34\u7247\u4e09\u7247\u5f0f3\u53f7\u6728\u5e3d\u5957",
        )
        self.assertEqual(nas_imports.source_brand_hint(source_path), "Caesar")

        conn = self.conn()
        self.assertEqual(
            nas_imports.canonical_product_drive_folder(
                conn,
                sku="6017008",
                english_name="Vintage Navy Fairway Cover # 3",
                category_id="HC_FAIRWAY",
                source_path=source_path,
                suggested_folder=wrong_suggestion,
                set_code="Set00299",
            ),
            "04 Product Images/05 Caesar/04 Fairway Cover/6017008 Caesar - Vintage Navy Fairway Cover # 3",
        )

        conn.execute(
            """
            INSERT INTO nas_imports(local_path, rel_path, name, size, mtime_ns, sha256)
            VALUES ('local-caesar', ?, '1.jpg', 1, 1, 'source-caesar')
            """,
            (source_path,),
        )
        conn.commit()
        row = nas_imports.list_imports(conn)[0]
        old_request = nas_imports.request_ai_suggestion
        nas_imports.request_ai_suggestion = lambda *_args: {
            "sku": "6017008",
            "english_name": "Vintage Navy Fairway Cover # 3",
            "drive_folder": wrong_suggestion,
            "drive_name": "6017008 Vintage Navy Fairway Cover # 3.jpg",
            "asset_type": "image",
            "confidence": 0.8,
            "reason": "AI incorrectly used the temporary No Brand ancestor.",
            "needs_manual_attention": False,
        }
        try:
            nas_imports.suggest_import(conn, row["id"])
        finally:
            nas_imports.request_ai_suggestion = old_request
        saved = nas_imports.get_import(conn, row["id"])
        self.assertEqual(saved["status"], "suggested")
        self.assertEqual(
            saved["final_drive_folder"],
            "04 Product Images/05 Caesar/04 Fairway Cover/6017008 Caesar - Vintage Navy Fairway Cover # 3",
        )
        conn.close()

    def test_real_source_paths_drive_deterministic_brand_category_and_target_names(self):
        conn = self.conn()
        big_teeth_path = (
            "临时/Big Teeth/帽套/推杆帽套/"
            "6016113Big Teeth 黑白PU拼接西服领结刺绣三片式双耳磁铁款大半圆DF3形体推杆套/1.jpg"
        )
        no_brand_path = (
            "临时/无牌/其他产品/果岭叉/"
            "5902330无牌 棕色姜饼人开瓶器果岭叉/1.jpg"
        )
        conn.execute(
            """
            INSERT INTO sku_meta(sku, english_name, brand, category_id)
            VALUES ('5902330', '', 'Craftsman Golf', 'ACC_DIVOT_MARKER')
            ON CONFLICT(sku) DO UPDATE SET
              english_name='', brand='Craftsman Golf', category_id='ACC_DIVOT_MARKER'
            """
        )
        conn.commit()

        self.assertEqual(
            nas_imports.canonical_product_drive_folder(
                conn,
                sku="6016113",
                english_name="The Golf Father Mallet Putter Cover for DF3",
                category_id="HC_PUTTER_MALLET_LARGE",
                source_path=big_teeth_path,
            ),
            "04 Product Images/04 Big Teeth/07 Mallet Putter Cover/6016113 Big Teeth - The Golf Father Mallet Putter Cover for DF3",
        )
        self.assertEqual(
            nas_imports.canonical_product_drive_folder(
                conn,
                sku="5902330",
                english_name="Brown Gingerbread Man Bottle Opener Divot Tool",
                category_id="ACC_DIVOT_MARKER",
                source_path=no_brand_path,
            ),
            "04 Product Images (No Brand)/12 Ball Marker & Divot Tool/5902330 Brown Gingerbread Man Bottle Opener Divot Tool",
        )
        self.assertEqual(
            nas_imports.better_drive_name(
                "5902330 Brown Gingerbread Man Bottle Opener Divot Tools (1).jpg",
                "1.jpg",
                "5902330",
                "Brown Gingerbread Man Bottle Opener Divot Tool",
                no_brand_path,
            ),
            "5902330 Brown Gingerbread Man Bottle Opener Divot Tool (1).jpg",
        )
        prompt = nas_imports.suggestion_prompt(
            {"rel_path": no_brand_path, "name": "1.jpg"},
            nas_imports.drive_catalog(conn, ["5902330"], no_brand_path),
            ["5902330"],
        )
        self.assertIn("Primary source product folder: 5902330无牌 棕色姜饼人开瓶器果岭叉", prompt)
        self.assertIn("No Brand", prompt)
        conn.close()

    def test_ai_suggestion_uses_company_owned_leaf_over_no_brand_parent(self):
        conn = self.conn()
        source_path = (
            "\u4e34\u65f6/\u65e0\u724c/\u5176\u4ed6\u4ea7\u54c1/\u6d4b\u8ddd\u4eea\u5305/"
            "7203132\u81ea\u4e3b \u7eff\u8272\u683c\u5b50\u5370\u5237\u52a0\u7c89\u8272\u523a\u7ee3\u6d4b\u8ddd\u4eea\u5305/1.jpg"
        )
        conn.execute(
            """
            INSERT INTO nas_imports(local_path, rel_path, name, size, mtime_ns, sha256)
            VALUES ('local-company-owned', ?, '1.jpg', 1, 1, 'source-company-owned')
            """,
            (source_path,),
        )
        conn.commit()
        row = nas_imports.list_imports(conn)[0]
        old_request = nas_imports.request_ai_suggestion
        nas_imports.request_ai_suggestion = lambda *_args: {
            "sku": "",
            "english_name": "Wrong AI Rangefinder Name",
            "drive_folder": "04 Product Images (No Brand)/18 Range Finder Case",
            "drive_name": "7203132 Wrong AI Rangefinder Name.jpg",
            "asset_type": "image",
            "confidence": 0.6,
            "reason": "AI incorrectly used the temporary No Brand ancestor.",
            "needs_manual_attention": False,
        }
        try:
            nas_imports.suggest_import(conn, row["id"])
        finally:
            nas_imports.request_ai_suggestion = old_request

        saved = nas_imports.get_import(conn, row["id"])
        self.assertEqual(saved["status"], "suggested")
        self.assertEqual(saved["final_sku"], "7203132")
        self.assertEqual(saved["final_english_name"], "Green & Pink Checkered Rangefinder Case")
        self.assertEqual(saved["final_drive_name"], "7203132 Green & Pink Checkered Rangefinder Case.jpg")
        self.assertEqual(
            saved["final_drive_folder"],
            "04 Product Images/01 Craftsman Golf/18 Range Finder Case/7203132 CF - Green & Pink Checkered Rangefinder Case",
        )
        conn.close()

    def test_ai_suggestion_uses_primary_sku_folder_for_big_teeth_and_no_brand(self):
        conn = self.conn()
        rows = [
            (
                "local-big-teeth",
                "临时/Big Teeth/帽套/推杆帽套/6016113Big Teeth 黑白PU拼接西服领结刺绣三片式双耳磁铁款大半圆DF3形体推杆套/1.jpg",
                "1.jpg",
                "source-big-teeth",
            ),
            (
                "local-no-brand",
                "临时/无牌/其他产品/果岭叉/5902330无牌 棕色姜饼人开瓶器果岭叉/1.jpg",
                "1.jpg",
                "source-no-brand",
            ),
        ]
        conn.executemany(
            """
            INSERT INTO nas_imports(local_path, rel_path, name, size, mtime_ns, sha256)
            VALUES (?, ?, ?, 1, 1, ?)
            """,
            rows,
        )
        conn.commit()
        old_request = nas_imports.request_ai_suggestion

        def fake_request(row, _catalog, _candidates):
            if "6016113" in row["rel_path"]:
                return {
                    "sku": "",
                    "english_name": "Wrong AI Putter Name",
                    "drive_folder": "04 Product Images/Big Teeth/Putter Covers",
                    "drive_name": "6016113 The Golf Father Mallet Putter Covers for DF3 (1).jpg",
                    "asset_type": "image",
                    "confidence": 0.6,
                    "reason": "AI used generic ancestors.",
                    "needs_manual_attention": False,
                }
            return {
                "sku": "",
                "english_name": "Brown Gingerbread Man Bottle Opener Divot Tool",
                "drive_folder": "04 Product Images/01 Craftsman Golf/Golf Accessories",
                "drive_name": "5902330 Brown Gingerbread Man Bottle Opener Divot Tools (1).jpg",
                "asset_type": "image",
                "confidence": 0.6,
                "reason": "AI used the wrong brand root.",
                "needs_manual_attention": False,
            }

        nas_imports.request_ai_suggestion = fake_request
        try:
            for row in nas_imports.list_imports(conn):
                nas_imports.suggest_import(conn, row["id"])
        finally:
            nas_imports.request_ai_suggestion = old_request

        saved = {row["final_sku"]: row for row in nas_imports.list_imports(conn)}
        self.assertEqual(saved["6016113"]["status"], "suggested")
        self.assertEqual(
            saved["6016113"]["final_english_name"],
            "The Golf Father Mallet Putter Cover for DF3",
        )
        self.assertEqual(
            saved["6016113"]["final_drive_name"],
            "6016113 The Golf Father Mallet Putter Cover for DF3 (1).jpg",
        )
        self.assertEqual(
            saved["6016113"]["final_drive_folder"],
            "04 Product Images/04 Big Teeth/07 Mallet Putter Cover/6016113 Big Teeth - The Golf Father Mallet Putter Cover for DF3",
        )
        self.assertEqual(saved["5902330"]["status"], "suggested")
        self.assertEqual(
            saved["5902330"]["final_drive_name"],
            "5902330 Brown Gingerbread Man Bottle Opener Divot Tool (1).jpg",
        )
        self.assertEqual(
            saved["5902330"]["final_drive_folder"],
            "04 Product Images (No Brand)/12 Ball Marker & Divot Tool/5902330 Brown Gingerbread Man Bottle Opener Divot Tool",
        )
        conn.close()

    def test_stale_material_save_is_rejected_instead_of_overwriting_newer_admin_edit(self):
        conn = self.conn()
        conn.execute(
            """
            INSERT INTO nas_imports(local_path, rel_path, name, size, mtime_ns, sha256)
            VALUES ('local', 'incoming/6012065.jpg', '6012065.jpg', 1, 1, 'concurrency-save')
            """
        )
        conn.commit()
        row = nas_imports.list_imports(conn)[0]
        fields = (
            "6012065", "First Admin", "Brand Assets", "first.jpg", "image",
        )

        nas_imports.save_final(conn, row["id"], *fields, expected_revision=row["revision"])
        with self.assertRaises(nas_imports.ConcurrencyConflict):
            nas_imports.save_final(
                conn,
                row["id"],
                "6012065", "Stale Admin", "Brand Assets", "stale.jpg", "image",
                expected_revision=row["revision"],
            )

        current = nas_imports.get_import(conn, row["id"])
        self.assertEqual(current["final_english_name"], "First Admin")
        self.assertEqual(current["revision"], row["revision"] + 1)
        conn.close()

    def test_only_one_admin_can_claim_and_move_the_same_drive_import(self):
        conn = self.conn()
        conn.execute(
            """
            INSERT INTO nas_imports(
              local_path, rel_path, name, size, mtime_ns, sha256, status,
              final_sku, final_english_name, final_drive_folder, final_drive_name,
              final_asset_type
            ) VALUES (
              'gdrive:source-file', '临时/6012065.jpg', '6012065.jpg', 1, 1,
              'concurrency-approve', 'suggested', '6012065', 'Iron Cover',
              'Brand Assets', '6012065 Iron Cover.jpg', 'image'
            )
            """
        )
        conn.commit()
        row = nas_imports.list_imports(conn)[0]
        calls = []
        original_service = nas_imports.drive.service
        original_metadata = nas_imports.drive.file_metadata
        original_ensure = nas_imports.drive.ensure_folder_path
        original_move = nas_imports.drive.move_file
        nas_imports.drive.service = lambda *_args, **_kwargs: object()
        nas_imports.drive.file_metadata = lambda *_args, **_kwargs: {"id": "source-file"}
        nas_imports.drive.ensure_folder_path = lambda *_args, **_kwargs: "target-folder"
        nas_imports.drive.move_file = lambda *_args, **_kwargs: calls.append("move")
        try:
            nas_imports.approve_import(conn, row["id"], "root", 1)
            with self.assertRaises(nas_imports.ConcurrencyConflict):
                nas_imports.approve_import(conn, row["id"], "root", 2)
        finally:
            nas_imports.drive.service = original_service
            nas_imports.drive.file_metadata = original_metadata
            nas_imports.drive.ensure_folder_path = original_ensure
            nas_imports.drive.move_file = original_move

        self.assertEqual(calls, ["move"])
        self.assertEqual(nas_imports.get_import(conn, row["id"])["status"], "uploaded")
        conn.close()

    def test_scan_inbox_only_registers_images_once(self):
        (self.root / "incoming").mkdir()
        (self.root / "incoming" / "6012065-photo.jpg").write_bytes(b"image")
        (self.root / "incoming" / "notes.txt").write_text("skip", encoding="utf-8")
        conn = self.conn()

        self.assertEqual(nas_imports.scan_inbox(conn), 1)
        self.assertEqual(nas_imports.scan_inbox(conn), 0)
        rows = nas_imports.list_imports(conn)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "6012065-photo.jpg")
        conn.close()

    def test_scan_inbox_registers_supported_videos_as_video_assets(self):
        incoming = self.root / "incoming"
        incoming.mkdir()
        for name in ("6012065-demo.mp4", "6012065-demo.MOV", "6012065-demo.webm"):
            (incoming / name).write_bytes(name.encode())
        (incoming / "notes.txt").write_text("skip", encoding="utf-8")
        conn = self.conn()

        self.assertEqual(nas_imports.scan_inbox(conn), 3)
        rows = nas_imports.list_imports(conn)

        self.assertEqual({row["name"] for row in rows}, {
            "6012065-demo.mp4", "6012065-demo.MOV", "6012065-demo.webm",
        })
        self.assertTrue(all(row["suggested_asset_type"] == "video" for row in rows))
        self.assertTrue(all(row["final_asset_type"] == "video" for row in rows))
        conn.close()

    def test_pending_import_pagination_uses_a_fixed_batch_count_without_splitting_batches(self):
        conn = self.conn()
        rows = []
        for batch_index, batch_size in enumerate((20,) * 8, start=1):
            for file_index in range(batch_size):
                name = f"{batch_index}-{file_index}.jpg"
                rows.append((
                    f"local-{batch_index}-{file_index}",
                    f"临时/batch-{batch_index}/{name}",
                    name,
                    f"hash-{batch_index}-{file_index}",
                ))
        conn.executemany(
            """
            INSERT INTO nas_imports(local_path, rel_path, name, size, mtime_ns, sha256)
            VALUES (?, ?, ?, 1, 1, ?)
            """,
            rows,
        )
        conn.commit()

        first = nas_imports.paginate_imports(conn, page=1, page_size=6)
        second = nas_imports.paginate_imports(conn, page=2, page_size=6)
        first_batch_keys = {
            nas_imports.import_batch_key(row) for row in first["imports"]
        }
        conn.close()

        self.assertEqual(first["total"], 160)
        self.assertEqual(first["batch_total"], 8)
        self.assertEqual(first["batch_count"], 6)
        self.assertEqual(first["pages"], 2)
        self.assertEqual(len(first["imports"]), 120)
        self.assertEqual(len(second["imports"]), 40)
        self.assertEqual(len(first_batch_keys), 6)
        self.assertEqual(second["batch_count"], 2)

    def test_rejected_imports_are_retained_in_disabled_view_and_can_be_restored(self):
        conn = self.conn()
        conn.executemany(
            """
            INSERT INTO nas_imports(local_path, rel_path, name, size, mtime_ns, sha256)
            VALUES (?, ?, ?, 1, 1, ?)
            """,
            [
                ("local-a", "临时/batch-a/a.jpg", "a.jpg", "hash-a"),
                ("local-b", "临时/batch-a/b.jpg", "b.jpg", "hash-b"),
            ],
        )
        conn.commit()
        import_ids = [row["id"] for row in nas_imports.list_imports(conn)]

        self.assertEqual(nas_imports.reject_imports(conn, [*import_ids, import_ids[0]]), 2)
        self.assertEqual(nas_imports.list_imports(conn), [])
        disabled = nas_imports.paginate_imports(conn, view="disabled")
        self.assertEqual(disabled["total"], 2)
        self.assertEqual({row["status"] for row in disabled["imports"]}, {"rejected"})

        restored_id = import_ids[0]
        self.assertEqual(nas_imports.restore_imports(conn, [restored_id, restored_id]), 1)
        active_rows = nas_imports.list_imports(conn)
        disabled_rows = nas_imports.list_imports(conn, view="disabled")
        self.assertEqual([row["id"] for row in active_rows], [restored_id])
        self.assertEqual(active_rows[0]["status"], "pending")
        self.assertEqual({row["id"] for row in disabled_rows}, {import_ids[1]})
        conn.close()

    def test_drive_inbox_scan_registers_nested_images_once(self):
        tree = {
            "inbox": [
                {"id": "nested", "name": "Craftsman", "mimeType": nas_imports.drive.FOLDER_MIME},
                {"id": "skip", "name": "notes.txt", "mimeType": "text/plain", "size": "1"},
            ],
            "nested": [
                {
                    "id": "drive-file-1",
                    "name": "6012065.jpg",
                    "mimeType": "image/jpeg",
                    "size": "12",
                    "modifiedTime": "2026-07-14T01:02:03Z",
                }
            ],
        }
        old_service = nas_imports.drive.service
        old_find = nas_imports.drive.find_child
        old_list = nas_imports.drive.list_children
        calls = []
        nas_imports.drive.service = lambda: "svc"
        nas_imports.drive.find_child = lambda svc, root_id, name, folder: {"id": "inbox", "name": name}

        def fake_list(svc, folder_id, drive_id):
            calls.append((folder_id, drive_id))
            yield from tree.get(folder_id, [])

        nas_imports.drive.list_children = fake_list
        conn = self.conn()
        try:
            self.assertEqual(nas_imports.scan_drive_inbox(conn, "0ACroot"), 1)
            self.assertEqual(nas_imports.scan_drive_inbox(conn, "0ACroot"), 0)
        finally:
            nas_imports.drive.service = old_service
            nas_imports.drive.find_child = old_find
            nas_imports.drive.list_children = old_list

        row = nas_imports.list_imports(conn)[0]
        self.assertEqual(row["local_path"], "gdrive:drive-file-1")
        self.assertEqual(row["rel_path"], "临时/Craftsman/6012065.jpg")
        self.assertTrue(all(drive_id == "0ACroot" for _folder_id, drive_id in calls))
        conn.close()

    def test_drive_inbox_scan_registers_video_files(self):
        old_service = nas_imports.drive.service
        old_list = nas_imports.drive.list_children
        nas_imports.drive.service = lambda: "svc"
        nas_imports.drive.list_children = lambda *_args: iter((
            {
                "id": "drive-video-1",
                "name": "6012065-demo.mp4",
                "mimeType": "video/mp4",
                "size": "128",
                "modifiedTime": "2026-08-27T01:02:03Z",
            },
            {"id": "skip", "name": "notes.txt", "mimeType": "text/plain", "size": "1"},
        ))
        conn = self.conn()
        try:
            self.assertEqual(nas_imports.scan_drive_inbox(conn, "0ACroot", folder_id="inbox"), 1)
        finally:
            nas_imports.drive.service = old_service
            nas_imports.drive.list_children = old_list

        row = nas_imports.list_imports(conn)[0]
        self.assertEqual(row["local_path"], "gdrive:drive-video-1")
        self.assertEqual(row["final_asset_type"], "video")
        conn.close()

    def test_drive_inbox_scan_uses_configured_folder_id_without_name_lookup(self):
        old_service = nas_imports.drive.service
        old_find = nas_imports.drive.find_child
        old_list = nas_imports.drive.list_children
        calls = []
        nas_imports.drive.service = lambda: "svc"
        nas_imports.drive.find_child = lambda *_args, **_kwargs: self.fail(
            "Configured Drive inbox ID must bypass folder-name lookup"
        )
        nas_imports.drive.list_children = lambda svc, folder_id, drive_id: (
            calls.append((folder_id, drive_id)) or iter(
                (
                    {
                        "id": "drive-file-direct",
                        "name": "direct.jpg",
                        "mimeType": "image/jpeg",
                        "size": "24",
                        "modifiedTime": "2026-07-30T01:02:03Z",
                    },
                )
            )
        )
        conn = self.conn()
        try:
            self.assertEqual(
                nas_imports.scan_drive_inbox(
                    conn,
                    "0ACroot",
                    folder_id="1DJBOInTYtaKYOqsGJIszxXU3RNmjuuJv",
                ),
                1,
            )
        finally:
            nas_imports.drive.service = old_service
            nas_imports.drive.find_child = old_find
            nas_imports.drive.list_children = old_list

        row = nas_imports.list_imports(conn)[0]
        self.assertEqual(row["local_path"], "gdrive:drive-file-direct")
        self.assertEqual(row["rel_path"], f"{nas_imports.GOOGLE_DRIVE_INBOX}/direct.jpg")
        self.assertEqual(calls, [("1DJBOInTYtaKYOqsGJIszxXU3RNmjuuJv", "0ACroot")])
        conn.close()

    def test_configured_drive_inbox_hides_legacy_non_drive_pending_rows(self):
        conn = self.conn()
        conn.executemany(
            """
            INSERT INTO nas_imports(local_path, rel_path, name, size, mtime_ns, sha256, status)
            VALUES (?, ?, ?, 1, 1, ?, ?)
            """,
            (
                ("gdrive:file-1", "临时/file-1.jpg", "file-1.jpg", "hash-g", "pending"),
                ("synology:/old.jpg", "old.jpg", "old.jpg", "hash-s", "suggested"),
                (str(self.root / "local.jpg"), "local.jpg", "local.jpg", "hash-l", "pending"),
            ),
        )
        conn.commit()
        os.environ["GOOGLE_DRIVE_INBOX_FOLDER_ID"] = "1DJBOInTYtaKYOqsGJIszxXU3RNmjuuJv"

        rows = nas_imports.list_imports(conn)
        counts = nas_imports.status_counts(conn)

        self.assertEqual([row["local_path"] for row in rows], ["gdrive:file-1"])
        self.assertEqual(counts, {"pending": 1})
        conn.close()

    def test_drive_inbox_skips_excluded_folder_and_purges_its_pending_index(self):
        tree = {
            "inbox": [
                {
                    "id": "1DU2M6iJouIWusMcZ9zCThguQsP8xw5lw",
                    "name": "领星主图",
                    "mimeType": nas_imports.drive.FOLDER_MIME,
                },
                {
                    "id": "keep-file",
                    "name": "keep.jpg",
                    "mimeType": "image/jpeg",
                    "size": "12",
                    "modifiedTime": "2026-07-30T01:02:03Z",
                },
            ],
        }
        old_service = nas_imports.drive.service
        old_list = nas_imports.drive.list_children
        calls = []
        nas_imports.drive.service = lambda: "svc"

        def fake_list(_svc, folder_id, _drive_id):
            calls.append(folder_id)
            yield from tree.get(folder_id, [])

        nas_imports.drive.list_children = fake_list
        os.environ["GOOGLE_DRIVE_INBOX_EXCLUDED_FOLDER_IDS"] = (
            "1DU2M6iJouIWusMcZ9zCThguQsP8xw5lw"
        )
        conn = self.conn()
        conn.executemany(
            """
            INSERT INTO nas_imports(local_path, rel_path, name, size, mtime_ns, sha256, status)
            VALUES (?, ?, ?, 1, 1, ?, ?)
            """,
            (
                (
                    "gdrive:excluded-pending",
                    f"{nas_imports.GOOGLE_DRIVE_INBOX}/领星主图/old.jpg",
                    "old.jpg",
                    "excluded-pending",
                    "pending",
                ),
                (
                    "gdrive:excluded-uploaded",
                    f"{nas_imports.GOOGLE_DRIVE_INBOX}/领星主图/uploaded.jpg",
                    "uploaded.jpg",
                    "excluded-uploaded",
                    "uploaded",
                ),
            ),
        )
        conn.commit()
        try:
            self.assertEqual(
                nas_imports.scan_drive_inbox(conn, "0ACroot", folder_id="inbox"),
                1,
            )
        finally:
            nas_imports.drive.service = old_service
            nas_imports.drive.list_children = old_list

        rows = conn.execute(
            "SELECT local_path, status FROM nas_imports ORDER BY local_path"
        ).fetchall()
        self.assertEqual(
            [(row["local_path"], row["status"]) for row in rows],
            [
                ("gdrive:excluded-uploaded", "uploaded"),
                ("gdrive:keep-file", "pending"),
            ],
        )
        self.assertEqual(calls, ["inbox"])
        conn.close()

    def test_drive_write_rejects_readonly_oauth_token_clearly(self):
        token_file = self.root / "google-token.json"
        token_file.write_text(
            json.dumps({"scopes": [nas_imports.drive.DRIVE_READONLY_SCOPE]}),
            encoding="utf-8",
        )
        old_token = os.environ.get("GOOGLE_OAUTH_TOKEN_FILE")
        old_service_account = os.environ.pop("GOOGLE_SERVICE_ACCOUNT_FILE", None)
        os.environ["GOOGLE_OAUTH_TOKEN_FILE"] = str(token_file)
        try:
            with self.assertRaisesRegex(RuntimeError, "只有只读权限"):
                nas_imports.drive.service([nas_imports.drive.DRIVE_WRITE_SCOPE])
        finally:
            if old_token is None:
                os.environ.pop("GOOGLE_OAUTH_TOKEN_FILE", None)
            else:
                os.environ["GOOGLE_OAUTH_TOKEN_FILE"] = old_token
            if old_service_account is not None:
                os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"] = old_service_account

    def test_scan_synology_registers_images_once(self):
        class FakeClient:
            def walk(self, folder_path):
                yield {
                    "name": "1.jpg",
                    "path": "/产品图片/Craftsman/帽套/推杆帽套/6012159 自主 黑色PU猴子西服贴片绣磁铁推杆套/1.jpg",
                    "size": 12,
                    "additional": {"time": {"mtime": 100}},
                }
                yield {"name": "notes.txt", "path": "/产品图片/notes.txt", "size": 1, "additional": {"time": {"mtime": 100}}}

        conn = self.conn()

        self.assertEqual(nas_imports.scan_synology(conn, FakeClient(), "/产品图片"), 1)
        self.assertEqual(nas_imports.scan_synology(conn, FakeClient(), "/产品图片"), 0)
        row = nas_imports.list_imports(conn)[0]

        self.assertTrue(row["local_path"].startswith("synology:/产品图片/"))
        self.assertEqual(row["rel_path"], "产品图片/Craftsman/帽套/推杆帽套/6012159 自主 黑色PU猴子西服贴片绣磁铁推杆套/1.jpg")
        conn.close()

    def test_scan_synology_registers_video_files(self):
        class FakeClient:
            def walk(self, folder_path):
                yield {
                    "name": "6012159-demo.mov",
                    "path": "/产品图片/Craftsman/6012159-demo.mov",
                    "size": 256,
                    "additional": {"time": {"mtime": 100}},
                }
                yield {"name": "notes.txt", "path": "/产品图片/notes.txt", "size": 1, "additional": {"time": {"mtime": 100}}}

        conn = self.conn()
        self.assertEqual(nas_imports.scan_synology(conn, FakeClient(), "/产品图片"), 1)
        row = nas_imports.list_imports(conn)[0]
        self.assertEqual(row["name"], "6012159-demo.mov")
        self.assertEqual(row["final_asset_type"], "video")
        conn.close()

    def test_video_source_type_overrides_an_incorrect_ai_image_type(self):
        path = self.root / "6012065-demo.mp4"
        path.write_bytes(b"video")
        conn = self.conn()
        nas_imports.scan_inbox(conn)
        row = nas_imports.list_imports(conn)[0]
        old_request = nas_imports.request_ai_suggestion
        nas_imports.request_ai_suggestion = lambda *_args: {
            "sku": "6012065",
            "english_name": "Pink Birdie Driver Cover",
            "drive_folder": "04 Product Images/01 Craftsman Golf/03 Driver Cover/6012065 CF - Pink Birdie Driver Cover",
            "drive_name": "6012065 Pink Birdie Driver Cover.mp4",
            "asset_type": "image",
            "confidence": 0.9,
            "reason": "Matched the source path.",
            "needs_manual_attention": False,
        }
        try:
            nas_imports.suggest_import(conn, row["id"])
        finally:
            nas_imports.request_ai_suggestion = old_request

        saved = nas_imports.get_import(conn, row["id"])
        self.assertEqual(saved["suggested_asset_type"], "video")
        self.assertEqual(saved["final_asset_type"], "video")
        conn.close()

    def test_synology_inbox_defaults_to_product_images(self):
        self.assertEqual(nas_imports.synology_inbox_path(), "/产品图片")

    def test_incremental_synology_scan_baselines_then_queues_new_images(self):
        items = [
            {
                "name": "old.jpg",
                "path": "/产品图片/old.jpg",
                "size": 10,
                "additional": {"time": {"mtime": 100}},
            }
        ]

        class FakeClient:
            def walk(self, folder_path):
                yield from items

        conn = self.conn()
        self.assertEqual(nas_imports.scan_synology_incremental(conn, FakeClient(), "/产品图片"), 0)
        self.assertEqual(nas_imports.list_imports(conn), [])

        items.append(
            {
                "name": "new.jpg",
                "path": "/产品图片/new.jpg",
                "size": 20,
                "additional": {"time": {"mtime": 200}},
            }
        )
        self.assertEqual(nas_imports.scan_synology_incremental(conn, FakeClient(), "/产品图片"), 1)
        self.assertEqual(nas_imports.scan_synology_incremental(conn, FakeClient(), "/产品图片"), 0)
        self.assertEqual([row["name"] for row in nas_imports.list_imports(conn)], ["new.jpg"])
        conn.close()

    def test_synology_walk_reads_nested_folders(self):
        client = object.__new__(nas_imports.synology.SynologyClient)
        tree = {
            "/产品图片": [
                {"isdir": True, "path": "/产品图片/Craftsman"},
                {"isdir": False, "path": "/产品图片/root.jpg"},
            ],
            "/产品图片/Craftsman": [
                {"isdir": False, "path": "/产品图片/Craftsman/nested.jpg"},
            ],
        }
        client.list_folder = lambda path: tree[path]

        self.assertEqual(
            sorted(item["path"] for item in client.walk("/产品图片")),
            ["/产品图片/Craftsman/nested.jpg", "/产品图片/root.jpg"],
        )

    def test_synology_list_retries_transient_errors(self):
        client = object.__new__(nas_imports.synology.SynologyClient)
        client.sid = "sid"
        attempts = []

        def fake_json(cgi, params):
            attempts.append(params["folder_path"])
            if len(attempts) == 1:
                raise RuntimeError("temporary")
            return {"files": [{"name": "ok.jpg"}]}

        old_sleep = nas_imports.synology.time.sleep
        client._json = fake_json
        nas_imports.synology.time.sleep = lambda seconds: None
        try:
            self.assertEqual(client.list_folder("/产品图片"), [{"name": "ok.jpg"}])
        finally:
            nas_imports.synology.time.sleep = old_sleep
        self.assertEqual(len(attempts), 2)

    def test_row_path_rejects_file_outside_inbox(self):
        conn = self.conn()
        path = self.root / "a.jpg"
        path.write_bytes(b"x")
        nas_imports.scan_inbox(conn)
        row = nas_imports.list_imports(conn)[0]
        outside = self.root.parent / "outside.jpg"
        conn.execute("UPDATE nas_imports SET local_path=? WHERE id=?", (str(outside), row["id"]))
        conn.commit()
        row = nas_imports.get_import(conn, row["id"])

        with self.assertRaises(ValueError):
            nas_imports.row_path(row)
        conn.close()

    def test_shared_drive_collection_prefix_is_kept(self):
        self.assertEqual(
            nas_imports.ensure_relative_drive_path("04 Product Images/01 Craftsman Golf/Set00300"),
            "04 Product Images/01 Craftsman Golf/Set00300",
        )
        with self.assertRaisesRegex(ValueError, "included shared-drive collection"):
            nas_imports.ensure_relative_drive_path("01 Craftsman Golf/Set00300")

    def test_google_path_rejects_non_english_text(self):
        path = self.root / "6017009.jpg"
        path.write_bytes(b"x")
        conn = self.conn()
        nas_imports.scan_inbox(conn)
        row = nas_imports.list_imports(conn)[0]

        with self.assertRaisesRegex(ValueError, "English"):
            nas_imports.save_final(
                conn,
                row["id"],
                "6017009",
                "Navy Blue 5-Wood Cover",
                "04 Product Images/07 Product packaging/Craftsman Golf 包装系列",
                "6017009 Navy Blue 5-Wood Cover.jpg",
                "image",
            )
        conn.close()

    def test_batch_identity_save_does_not_validate_unfinished_category_or_folder(self):
        conn = self.conn()
        for name in ("front.jpg", "back.jpg"):
            (self.root / name).write_bytes(name.encode())
        nas_imports.scan_inbox(conn)
        rows = nas_imports.list_imports(conn)
        import_ids = [row["id"] for row in rows]
        conn.executemany(
            """
            UPDATE nas_imports
            SET final_drive_folder='04 Product Images',
                suggested_drive_folder='04 Product Images',
                suggested_category_id='UNKNOWN'
            WHERE id=?
            """,
            [(import_id,) for import_id in import_ids],
        )
        conn.commit()

        updated = nas_imports.save_identities(
            conn,
            import_ids,
            "7016689",
            "Bear Plush Fairway Wood Cover",
            ["7016689 Bear Plush Fairway Wood Cover (1).jpg", "7016689 Bear Plush Fairway Wood Cover (2).jpg"],
        )
        saved = conn.execute(
            "SELECT final_sku, final_english_name, final_drive_folder, final_drive_name FROM nas_imports ORDER BY id DESC"
        ).fetchall()

        self.assertEqual(updated, 2)
        self.assertTrue(all(row["final_sku"] == "7016689" for row in saved))
        self.assertTrue(all(row["final_english_name"] == "Bear Plush Fairway Wood Cover" for row in saved))
        self.assertTrue(all(row["final_drive_folder"] == "04 Product Images" for row in saved))
        conn.close()

    def test_init_db_migrates_legacy_edit_log_constraint_before_batch_identity_save(self):
        conn = self.conn()
        try:
            conn.executescript(
                """
                DROP INDEX IF EXISTS idx_nas_import_edit_logs_created;
                DROP TABLE nas_import_edit_logs;
                CREATE TABLE nas_import_edit_logs (
                  id INTEGER PRIMARY KEY,
                  import_id INTEGER NOT NULL,
                  field TEXT NOT NULL CHECK(field IN ('final_drive_folder','final_english_name','final_drive_name')),
                  suggested_value TEXT NOT NULL DEFAULT '',
                  previous_value TEXT NOT NULL DEFAULT '',
                  new_value TEXT NOT NULL,
                  edited_by INTEGER,
                  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX idx_nas_import_edit_logs_created
                  ON nas_import_edit_logs(created_at, import_id);
                """
            )
            db.init_db(conn)
            (self.root / "front.jpg").write_bytes(b"front")
            nas_imports.scan_inbox(conn)
            row = nas_imports.list_imports(conn)[0]

            nas_imports.save_identities(
                conn,
                [row["id"]],
                "10086",
                "Name",
                ["DSC00478.JPG"],
                edited_by=1,
            )

            self.assertEqual(conn.execute("SELECT COUNT(*) FROM nas_import_edit_logs").fetchone()[0], 0)
            nas_imports.mark_uploaded(conn, row["id"], "10086", "Name", "drive-file-1", 1)
            fields = {
                log["field"]
                for log in conn.execute("SELECT field FROM nas_import_edit_logs").fetchall()
            }
            self.assertEqual(fields, {"final_sku", "final_english_name", "final_drive_name"})
        finally:
            conn.close()

    def test_batch_identity_save_reports_field_error_and_rolls_back_every_item(self):
        conn = self.conn()
        for name in ("front.jpg", "back.jpg"):
            (self.root / name).write_bytes(name.encode())
        nas_imports.scan_inbox(conn)
        rows = nas_imports.list_imports(conn)
        import_ids = [row["id"] for row in rows]

        with self.assertRaisesRegex(ValueError, "文件名"):
            nas_imports.save_identities(
                conn,
                import_ids,
                "7016689",
                "Bear Plush Fairway Wood Cover",
                ["7016689 Bear Plush Fairway Wood Cover (1).jpg", "中文文件名.jpg"],
            )

        saved = conn.execute(
            "SELECT final_sku, final_english_name, final_drive_name FROM nas_imports"
        ).fetchall()
        self.assertTrue(all(not row["final_sku"] for row in saved))
        self.assertTrue(all(not row["final_english_name"] for row in saved))
        self.assertTrue(all(not row["final_drive_name"] for row in saved))
        conn.close()

    def test_batch_identity_save_rejects_numeric_english_name(self):
        conn = self.conn()
        (self.root / "front.jpg").write_bytes(b"front")
        nas_imports.scan_inbox(conn)
        row = nas_imports.list_imports(conn)[0]

        with self.assertRaisesRegex(ValueError, "英文品名必须包含英文字母"):
            nas_imports.save_identities(
                conn,
                [row["id"]],
                "7016689",
                "42143",
                ["DSC00478.JPG"],
            )
        conn.close()

    def test_product_image_catalog_excludes_chinese_packaging_paths(self):
        conn = self.conn()
        conn.executemany(
            """
            INSERT INTO files(id, name, mime_type, path, sku, brand, category, asset_type)
            VALUES (?, '1.jpg', 'image/jpeg', ?, '6017009', ?, ?, 'image')
            """,
            [
                ("bad", "04 Product Images/07 Product packaging/Craftsman Golf 包装系列/合集图/1.jpg", "07 Product packaging", "Craftsman Golf 包装系列"),
                ("good", "01 Product Images/Unbranded Headcovers/6017009 Navy Blue 5-Wood Cover/1.jpg", "01 Product Images", "Unbranded Headcovers"),
            ],
        )
        conn.commit()

        catalog = nas_imports.drive_catalog(conn, ["6017009"], "产品图片/无牌/帽套/6017009/1.jpg")

        self.assertIn("Unbranded Headcovers", catalog)
        self.assertNotIn("包装", catalog)
        self.assertNotIn("Product packaging", catalog)
        conn.close()

    def test_drive_catalog_traverses_product_paths_without_sku_candidates(self):
        conn = self.conn()
        conn.executemany(
            """
            INSERT INTO files(id, name, mime_type, path, sku, brand, category, asset_type)
            VALUES (?, '1.jpg', 'image/jpeg', ?, ?, ?, ?, 'image')
            """,
            [
                (
                    "brand-path",
                    "04 Product Images/01 Craftsman Golf/01 Headcover Set/Set00001 CF - Sunglass Gorilla Headcover Set/6012159 CF - Sunglass Gorilla Putter Cover/1.jpg",
                    "6012159",
                    "01 Craftsman Golf",
                    "01 Headcover Set",
                ),
                (
                    "no-brand-path",
                    "04 Product Images (No Brand)/03 Driver Cover/6017009 Navy Blue Driver Cover/1.jpg",
                    "6017009",
                    "",
                    "03 Driver Cover",
                ),
                (
                    "other-path",
                    "06 Show & Exhibitions/2026 USA PGA Show/1.jpg",
                    "2026 USA PGA SHOW",
                    "",
                    "",
                ),
            ],
        )
        conn.commit()

        catalog = nas_imports.drive_catalog(conn, [])
        prompt = nas_imports.suggestion_prompt(
            {"rel_path": "临时/new.jpg", "name": "new.jpg"}, catalog, []
        )

        self.assertIn("04 Product Images/01 Craftsman Golf", catalog)
        self.assertIn("04 Product Images (No Brand)/<category folder>", catalog)
        self.assertIn("HC_DRIVER: 03 Driver Cover", catalog)
        self.assertIn("never create a Headcover Set", catalog)
        self.assertNotIn("Show & Exhibitions", catalog)
        self.assertIn("Never leave drive_folder blank", prompt)
        conn.close()

    def test_human_edits_and_uploaded_history_are_recorded(self):
        path = self.root / "6012065.jpg"
        path.write_bytes(b"x")
        conn = self.conn()
        nas_imports.scan_inbox(conn)
        row = nas_imports.list_imports(conn)[0]
        admin_id = conn.execute("SELECT id FROM users WHERE role IN ('super_admin','admin') ORDER BY id").fetchone()[0]
        conn.execute(
            """
            UPDATE nas_imports
            SET suggested_english_name='AI Driver Cover', final_english_name='AI Driver Cover',
                suggested_drive_folder='04 Product Images/01 Craftsman Golf/AI Folder',
                final_drive_folder='04 Product Images/01 Craftsman Golf/AI Folder',
                suggested_drive_name='6012065 AI Driver Cover.jpg',
                final_drive_name='6012065 AI Driver Cover.jpg'
            WHERE id=?
            """,
            (row["id"],),
        )
        conn.commit()

        values = (
            "6012065",
            "Pink Birdie Driver Cover",
            "04 Product Images/01 Craftsman Golf/01 Headcovers Set/Set00300",
            "6012065 Pink Birdie Driver Cover.jpg",
            "image",
        )
        try:
            nas_imports.save_final(conn, row["id"], *values, edited_by=admin_id)
            nas_imports.save_final(conn, row["id"], *values, edited_by=admin_id)
            self.assertEqual(nas_imports.list_edit_logs(conn), [])

            nas_imports.mark_uploaded(conn, row["id"], "6012065", values[1], "drive-file-1", admin_id)
            logs = nas_imports.list_edit_logs(conn)

            self.assertEqual(len(logs), 4)
            self.assertEqual(
                {item["field"] for item in logs},
                {"final_sku", "final_drive_folder", "final_english_name", "final_drive_name"},
            )
            self.assertTrue(all(item["editor"] == "Admin" for item in logs))
            approved_at = nas_imports.get_import(conn, row["id"])["approved_at"]
            self.assertTrue(all(item["created_at"] == approved_at for item in logs))

            history = nas_imports.list_uploaded_imports(conn)
            self.assertEqual(len(history), 1)
            self.assertEqual(
                history[0]["final_drive_folder"],
                "04 Product Images/01 Craftsman Golf/03 Driver Cover/6012065 CF - Pink Birdie Driver Cover",
            )
            self.assertEqual(history[0]["approver"], "Admin")
        finally:
            conn.close()

    def test_ai_chinese_google_path_requires_manual_attention(self):
        path = self.root / "6017009.jpg"
        path.write_bytes(b"x")
        conn = self.conn()
        nas_imports.scan_inbox(conn)
        row = nas_imports.list_imports(conn)[0]
        old_request = nas_imports.request_ai_suggestion
        nas_imports.request_ai_suggestion = lambda *_args: {
            "sku": "6017009",
            "english_name": "Navy Blue 5-Wood Cover",
            "drive_folder": "04 Product Images/07 Product packaging/Craftsman Golf 包装系列/合集图",
            "drive_name": "6017009 深蓝色5号木帽套.jpg",
            "asset_type": "image",
            "confidence": 0.8,
            "reason": "Matched an unsuitable catalog path.",
            "needs_manual_attention": False,
        }
        try:
            nas_imports.suggest_import(conn, row["id"])
        finally:
            nas_imports.request_ai_suggestion = old_request
        row = nas_imports.get_import(conn, row["id"])

        self.assertEqual(row["status"], "pending")
        self.assertEqual(
            row["final_drive_folder"],
            "04 Product Images/05 Caesar/04 Fairway Cover/6017009 Caesar - Vintage Navy Fairway Cover # 5",
        )
        self.assertTrue(row["final_drive_name"].isascii())
        conn.close()

    def test_ai_suggestion_writes_structured_fields(self):
        os.environ["OPENAI_API_KEY"] = "test"
        os.environ["OPENAI_MODEL"] = "test-model"
        path = self.root / "6012065-new.jpg"
        path.write_bytes(b"x")
        conn = self.conn()
        nas_imports.scan_inbox(conn)
        row = nas_imports.list_imports(conn)[0]
        old_post = nas_imports.requests.post

        def fake_post(*args, **kwargs):
            return FakeResponse(
                {
                    "output_text": json.dumps(
                        {
                            "sku": "6012065",
                            "english_name": "Pink Birdie Driver Cover",
                            "drive_folder": "04 Product Images/01 Craftsman Golf/01 Headcovers Set/Set00300 CF - Pink Birdie Headcover Set/6012065 CF - Pink Birdie Driver Cover",
                            "drive_name": "6012065(1).jpg",
                            "asset_type": "image",
                            "confidence": 0.8,
                            "reason": "SKU matched path.",
                            "needs_manual_attention": False,
                        }
                    )
                }
            )

        nas_imports.requests.post = fake_post
        try:
            nas_imports.suggest_import(conn, row["id"])
        finally:
            nas_imports.requests.post = old_post
        row = nas_imports.get_import(conn, row["id"])

        self.assertEqual(row["status"], "suggested")
        self.assertEqual(row["final_sku"], "6012065")
        self.assertEqual(row["final_drive_name"], "6012065 Pink Birdie Driver Cover (1).jpg")
        conn.close()

    def test_approved_catalog_name_overrides_ai_wording(self):
        folder = self.root / "Craftsman"
        folder.mkdir()
        path = folder / "6012159-new.jpg"
        path.write_bytes(b"x")
        conn = self.conn()
        nas_imports.scan_inbox(conn)
        row = nas_imports.list_imports(conn)[0]
        old_request = nas_imports.request_ai_suggestion
        nas_imports.request_ai_suggestion = lambda *_args: {
            "sku": "6012159",
            "english_name": "Wrong Gorilla Putter Cover",
            "drive_folder": "04 Product Images/01 Craftsman Golf/01 Headcovers Set/Set00001 CF - Sunglass Gorilla Headcover Set/6012159 CF - Wrong Gorilla Putter Cover",
            "drive_name": "6012159 CF - Wrong Gorilla Putter Cover.jpg",
            "asset_type": "image",
            "confidence": 0.5,
            "reason": "AI wording.",
            "needs_manual_attention": False,
        }
        try:
            nas_imports.suggest_import(conn, row["id"])
        finally:
            nas_imports.request_ai_suggestion = old_request
        row = nas_imports.get_import(conn, row["id"])

        self.assertEqual(row["final_english_name"], "Sunglass Gorilla Blade Putter Cover")
        self.assertTrue(row["final_drive_folder"].endswith("6012159 CF - Sunglass Gorilla Blade Putter Cover"))
        self.assertEqual(row["final_drive_name"], "6012159 CF - Sunglass Gorilla Blade Putter Cover.jpg")
        self.assertEqual(row["confidence"], 0.98)
        conn.close()

    def test_catalog_names_are_seeded_without_overwriting_admin_edits(self):
        conn = self.conn()

        self.assertEqual(nas_imports.catalog_english_name(conn, "6012065"), "Pink Birdie Driver Cover")
        conn.execute("UPDATE sku_meta SET english_name='Old AI Name' WHERE sku='6012065'")
        conn.execute("DELETE FROM app_migrations WHERE name=?", (db.ENGLISH_NAME_CATALOG_VERSION,))
        conn.commit()
        db.init_db(conn)
        self.assertEqual(nas_imports.catalog_english_name(conn, "6012065"), "Pink Birdie Driver Cover")

        conn.execute("UPDATE sku_meta SET english_name='Admin Name' WHERE sku='6012065'")
        conn.commit()
        db.init_db(conn)

        self.assertEqual(nas_imports.catalog_english_name(conn, "6012065"), "Admin Name")
        self.assertEqual(
            nas_imports.ascii_product_name("Appliqu\u00e9 52\u00b0 \u2013 \u230034mm"),
            "Applique 52 deg - Dia 34mm",
        )
        conn.close()

    def test_deepseek_suggestion_uses_chat_completions(self):
        os.environ["AI_PROVIDER"] = "deepseek"
        os.environ["DEEPSEEK_API_KEY"] = "test"
        path = self.root / "6012159-new.jpg"
        path.write_bytes(b"x")
        conn = self.conn()
        nas_imports.scan_inbox(conn)
        row = nas_imports.list_imports(conn)[0]
        old_post = nas_imports.requests.post

        def fake_post(url, **kwargs):
            self.assertEqual(url, "https://api.deepseek.com/chat/completions")
            self.assertEqual(kwargs["json"]["response_format"], {"type": "json_object"})
            self.assertEqual(kwargs["json"]["thinking"], {"type": "disabled"})
            self.assertGreaterEqual(kwargs["json"]["max_tokens"], 2400)
            system_prompt = kwargs["json"]["messages"][0]["content"]
            self.assertIn("EXAMPLE JSON OUTPUT", system_prompt)
            self.assertIn('"needs_manual_attention": false', system_prompt)
            return FakeResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "sku": "6012159",
                                        "english_name": "Sunglass Gorilla Putter Cover",
                                        "drive_folder": "04 Product Images/01 Craftsman Golf/01 Headcovers Set/Set00001 CF - Sunglass Gorilla Headcover Set/6012159 CF - Sunglass Gorilla Putter Cover",
                                        "drive_name": "6012159 CF - Sunglass Gorilla Putter Cover",
                                        "asset_type": "image",
                                        "confidence": 0.78,
                                        "reason": "SKU matched path.",
                                        "needs_manual_attention": False,
                                    }
                                )
                            }
                        }
                    ]
                }
            )

        nas_imports.requests.post = fake_post
        try:
            nas_imports.suggest_import(conn, row["id"])
        finally:
            nas_imports.requests.post = old_post
        row = nas_imports.get_import(conn, row["id"])

        self.assertEqual(row["status"], "suggested")
        self.assertEqual(row["final_sku"], "6012159")
        self.assertEqual(row["final_drive_name"], "6012159 Sunglass Gorilla Blade Putter Cover.jpg")
        conn.close()

    def test_deepseek_retries_an_empty_json_response(self):
        os.environ["DEEPSEEK_API_KEY"] = "test"
        valid = {
            "sku": "6016271",
            "english_name": "Iron Cover Set",
            "drive_folder": "04 Product Images/01 Craftsman Golf/05 Iron Cover Set",
            "drive_name": "6016271 Iron Cover Set.jpg",
            "asset_type": "image",
            "confidence": 0.9,
            "reason": "SKU matched the source path.",
            "needs_manual_attention": False,
        }
        responses = [
            FakeResponse({"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]}),
            FakeResponse({"choices": [{"message": {"content": json.dumps(valid)}, "finish_reason": "stop"}]}),
        ]
        old_post = nas_imports.requests.post
        old_sleep = nas_imports.time.sleep
        nas_imports.requests.post = lambda *_args, **_kwargs: responses.pop(0)
        nas_imports.time.sleep = lambda _seconds: None
        try:
            result = nas_imports.request_deepseek_suggestion("Return JSON.")
        finally:
            nas_imports.requests.post = old_post
            nas_imports.time.sleep = old_sleep

        self.assertEqual(result, valid)
        self.assertEqual(responses, [])

    def test_deepseek_retries_a_length_truncated_response(self):
        os.environ["DEEPSEEK_API_KEY"] = "test"
        incomplete = {
            "sku": "6016270",
            "english_name": "Incomplete",
        }
        complete = {
            "sku": "6016270",
            "english_name": "Iron Cover Set",
            "drive_folder": "04 Product Images/01 Craftsman Golf/05 Iron Cover Set",
            "drive_name": "6016270 Iron Cover Set.jpg",
            "asset_type": "image",
            "confidence": 0.9,
            "reason": "SKU matched the source path.",
            "needs_manual_attention": False,
        }
        responses = [
            FakeResponse({"choices": [{"message": {"content": json.dumps(incomplete)}, "finish_reason": "length"}]}),
            FakeResponse({"choices": [{"message": {"content": json.dumps(complete)}, "finish_reason": "stop"}]}),
        ]
        old_post = nas_imports.requests.post
        old_sleep = nas_imports.time.sleep
        nas_imports.requests.post = lambda *_args, **_kwargs: responses.pop(0)
        nas_imports.time.sleep = lambda _seconds: None
        try:
            result = nas_imports.request_deepseek_suggestion("Return JSON.")
        finally:
            nas_imports.requests.post = old_post
            nas_imports.time.sleep = old_sleep

        self.assertEqual(result, complete)
        self.assertEqual(responses, [])

    def test_deepseek_retries_malformed_json_instead_of_exposing_decoder_errors(self):
        os.environ["DEEPSEEK_API_KEY"] = "test"
        valid = {
            "sku": "6016271",
            "english_name": "Iron Cover Set",
            "drive_folder": "04 Product Images/01 Craftsman Golf/05 Iron Cover Set",
            "drive_name": "6016271 Iron Cover Set.jpg",
            "asset_type": "image",
            "confidence": 0.9,
            "reason": "SKU matched the source path.",
            "needs_manual_attention": False,
        }
        responses = [
            FakeResponse({"choices": [{"message": {"content": '{"sku": "6016271",}'}, "finish_reason": "stop"}]}),
            FakeResponse({"choices": [{"message": {"content": json.dumps(valid)}, "finish_reason": "stop"}]}),
        ]
        old_post = nas_imports.requests.post
        old_sleep = nas_imports.time.sleep
        nas_imports.requests.post = lambda *_args, **_kwargs: responses.pop(0)
        nas_imports.time.sleep = lambda _seconds: None
        try:
            result = nas_imports.request_deepseek_suggestion("Return JSON.")
        finally:
            nas_imports.requests.post = old_post
            nas_imports.time.sleep = old_sleep

        self.assertEqual(result, valid)
        self.assertEqual(responses, [])

    def test_original_filename_becomes_sku_english_filename(self):
        self.assertEqual(
            nas_imports.better_drive_name("1.jpg", "1.jpg", "6012159", "Sunglass Gorilla Putter Cover"),
            "6012159 Sunglass Gorilla Putter Cover.jpg",
        )

    def test_chinese_headcover_name_rules(self):
        rel_path = "产品图片/Craftsman/帽套/推杆帽套/6012159 自主 黑色PU猴子西服贴片绣磁铁推杆套/1.jpg"

        english_name = nas_imports.normalize_english_name("Sunglass Gorilla", rel_path)

        self.assertEqual(english_name, "Sunglass Gorilla Putter Cover")
        self.assertEqual(
            nas_imports.better_drive_name("1.jpg", "1.jpg", "6012159", english_name, rel_path),
            "6012159 CF - Sunglass Gorilla Putter Cover.jpg",
        )
        self.assertEqual(
            nas_imports.better_drive_name("1600x1600(12).jpg", "1600x1600(12).jpg", "6012159", english_name, rel_path),
            "6012159 CF - Sunglass Gorilla Putter Cover (12).jpg",
        )
        self.assertEqual(nas_imports.cover_type_name("帽套/木杆帽套/6017009 深蓝色5号木帽套/1.jpg"), "5 Wood Cover")

    def test_product_type_normalization_uses_catalog_convention(self):
        self.assertEqual(
            nas_imports.normalize_english_name("Lily Putter Cover", "\u76f4\u6761\u63a8\u6746\u5957/1.jpg"),
            "Lily Blade Putter Cover",
        )
        self.assertEqual(nas_imports.cover_type_name("\u65b9\u5757\u63a8\u6746\u5957/1.jpg"), "Square Mallet Putter Cover")
        self.assertEqual(nas_imports.cover_type_name("\u5c0f\u534a\u5706\u63a8\u6746\u5957/1.jpg"), "Mid-Mallet Putter Cover")

    def test_named_confidence_is_accepted(self):
        self.assertEqual(nas_imports.confidence_value("high"), 0.9)
        self.assertEqual(nas_imports.confidence_value("medium"), 0.6)
        self.assertEqual(nas_imports.confidence_value("low"), 0.3)
        self.assertEqual(nas_imports.confidence_value("unknown"), 0.0)

    def test_ai_error_stays_in_queue_without_raising(self):
        path = self.root / "6012065-new.jpg"
        path.write_bytes(b"x")
        conn = self.conn()
        nas_imports.scan_inbox(conn)
        row = nas_imports.list_imports(conn)[0]

        nas_imports.suggest_import(conn, row["id"])
        row = nas_imports.get_import(conn, row["id"])

        self.assertEqual(row["status"], "error")
        self.assertIn("OPENAI_API_KEY", row["error"])
        conn.close()

    def test_batch_actions_deduplicate_and_continue_after_approval_error(self):
        conn = self.conn()
        conn.executemany(
            """
            INSERT INTO nas_imports(local_path, rel_path, name, size, mtime_ns, sha256, status)
            VALUES (?, ?, ?, 1, 1, ?, ?)
            """,
            [
                (str(self.root / "1.jpg"), "1.jpg", "1.jpg", "hash-1", "suggested"),
                (str(self.root / "2.jpg"), "2.jpg", "2.jpg", "hash-2", "suggested"),
                (str(self.root / "3.jpg"), "3.jpg", "3.jpg", "hash-3", "pending"),
            ],
        )
        conn.commit()
        rows = nas_imports.list_imports(conn)
        first, second, pending = [row["id"] for row in reversed(rows)]
        suggested = []
        approved = []
        old_suggest = nas_imports.suggest_import
        old_approve = nas_imports.approve_import
        nas_imports.suggest_import = lambda connection, import_id: suggested.append(import_id)

        def fake_approve(connection, import_id, root_id, approved_by):
            approved.append(import_id)
            if import_id == first:
                raise RuntimeError("upload failed")
            return "drive-file-2"

        nas_imports.approve_import = fake_approve
        try:
            self.assertEqual(nas_imports.suggest_imports(conn, [first, first, pending]), 2)
            uploaded = nas_imports.approve_imports(conn, [first, second, pending], "root", 1)
        finally:
            nas_imports.suggest_import = old_suggest
            nas_imports.approve_import = old_approve

        self.assertEqual(suggested, [first, pending])
        self.assertEqual(approved, [first, second])
        self.assertEqual(uploaded, ["drive-file-2"])
        self.assertEqual(nas_imports.get_import(conn, first)["status"], "error")
        conn.close()

    def test_batch_suggestions_run_with_bounded_concurrency(self):
        conn = self.conn()
        conn.executemany(
            """
            INSERT INTO nas_imports(local_path, rel_path, name, size, mtime_ns, sha256, status)
            VALUES (?, ?, ?, 1, 1, ?, 'pending')
            """,
            [
                (str(self.root / "parallel-1.jpg"), "parallel-1.jpg", "parallel-1.jpg", "parallel-hash-1"),
                (str(self.root / "parallel-2.jpg"), "parallel-2.jpg", "parallel-2.jpg", "parallel-hash-2"),
            ],
        )
        conn.commit()
        import_ids = [row["id"] for row in nas_imports.list_imports(conn)]
        barrier = threading.Barrier(2)
        calls = []
        old_suggest = nas_imports.suggest_import

        def fake_suggest(connection, import_id):
            calls.append((import_id, id(connection)))
            barrier.wait(timeout=0.5)
            time.sleep(0.05)

        nas_imports.suggest_import = fake_suggest
        try:
            started = time.perf_counter()
            count = nas_imports.suggest_imports(conn, import_ids, max_workers=2)
            elapsed = time.perf_counter() - started
        finally:
            nas_imports.suggest_import = old_suggest
            conn.close()

        self.assertEqual(count, 2)
        self.assertEqual({call[0] for call in calls}, set(import_ids))
        self.assertEqual(len({call[1] for call in calls}), 2)
        self.assertLess(elapsed, 0.3)

    def test_approve_uploads_and_upserts_sku_meta(self):
        path = self.root / "6012065-new.jpg"
        path.write_bytes(b"x")
        conn = self.conn()
        nas_imports.scan_inbox(conn)
        row = nas_imports.list_imports(conn)[0]
        nas_imports.save_final(
            conn,
            row["id"],
            "6012065",
            "Pink Birdie Driver Cover",
            "04 Product Images/01 Craftsman Golf/Set00300",
            "6012065(1).jpg",
            "image",
        )
        old_service = nas_imports.drive.service
        old_ensure = nas_imports.drive.ensure_folder_path
        old_upload = nas_imports.drive.upload_file
        calls = []
        nas_imports.drive.service = lambda scopes: "svc"
        nas_imports.drive.ensure_folder_path = lambda svc, root_id, parts: calls.append(("folder", root_id, parts)) or "parent"
        nas_imports.drive.upload_file = lambda svc, local_path, parent_id, name, mime_type, app_properties: {"id": "drive-file-1"}
        try:
            drive_file_id = nas_imports.approve_import(conn, row["id"], "root", 1)
        finally:
            nas_imports.drive.service = old_service
            nas_imports.drive.ensure_folder_path = old_ensure
            nas_imports.drive.upload_file = old_upload
        row = nas_imports.get_import(conn, row["id"])
        meta = conn.execute("SELECT english_name FROM sku_meta WHERE sku='6012065'").fetchone()

        self.assertEqual(drive_file_id, "drive-file-1")
        self.assertEqual(row["status"], "uploaded")
        self.assertEqual(meta["english_name"], "Pink Birdie Driver Cover")
        self.assertEqual(
            calls[0][2],
            [
                "04 Product Images",
                "01 Craftsman Golf",
                "03 Driver Cover",
                "6012065 CF - Pink Birdie Driver Cover",
            ],
        )
        conn.close()

    def test_approve_drive_inbox_file_moves_without_upload(self):
        conn = self.conn()
        nas_imports.register_drive_item(
            conn,
            {
                "id": "drive-file-1",
                "name": "6012065.jpg",
                "size": "12",
                "modifiedTime": "2026-07-14T01:02:03Z",
            },
            "临时/6012065.jpg",
        )
        row = nas_imports.list_imports(conn)[0]
        nas_imports.save_final(
            conn,
            row["id"],
            "6012065",
            "Pink Birdie Driver Cover",
            "04 Product Images/01 Craftsman Golf/Set00300",
            "6012065.jpg",
            "image",
        )
        old_service = nas_imports.drive.service
        old_metadata = nas_imports.drive.file_metadata
        old_ensure = nas_imports.drive.ensure_folder_path
        old_move = nas_imports.drive.move_file
        calls = []
        nas_imports.drive.service = lambda scopes: "svc"
        nas_imports.drive.file_metadata = lambda *_args, **_kwargs: {"id": "drive-file-1"}
        nas_imports.drive.ensure_folder_path = lambda svc, root_id, parts: "target-folder"
        nas_imports.drive.move_file = lambda svc, file_id, parent_id, name: calls.append(
            (svc, file_id, parent_id, name)
        ) or {"id": file_id}
        try:
            drive_file_id = nas_imports.approve_import(conn, row["id"], "0ACroot", 1)
        finally:
            nas_imports.drive.service = old_service
            nas_imports.drive.file_metadata = old_metadata
            nas_imports.drive.ensure_folder_path = old_ensure
            nas_imports.drive.move_file = old_move

        self.assertEqual(drive_file_id, "drive-file-1")
        self.assertEqual(
            calls,
            [("svc", "drive-file-1", "target-folder", "6012065 Pink Birdie Driver Cover.jpg")],
        )
        self.assertEqual(nas_imports.get_import(conn, row["id"])["status"], "uploaded")
        conn.close()

    def test_approve_synology_copies_into_google_root(self):
        class FakeClient:
            def __init__(self):
                self.created = []
                self.copied = []
                self.renamed = []

            def walk(self, folder_path):
                yield {"name": "6012065.jpg", "path": "/产品图片/6012065.jpg", "size": 12, "additional": {"time": {"mtime": 100}}}

            def list_folder(self, folder_path):
                return []

            def create_folder(self, folder_path, name):
                self.created.append((folder_path, name))

            def copy(self, path, dest_folder_path):
                self.copied.append((path, dest_folder_path))
                return "task-1"

            def wait_copy(self, taskid):
                self.taskid = taskid

            def rename(self, path, name):
                self.renamed.append((path, name))

        conn = self.conn()
        nas_imports.scan_synology(conn, FakeClient(), "/产品图片")
        row = nas_imports.list_imports(conn)[0]
        nas_imports.save_final(
            conn,
            row["id"],
            "6012065",
            "Pink Birdie Driver Cover",
            "04 Product Images/01 Craftsman Golf/Set00300",
            "6012065.jpg",
            "image",
        )
        old_client = nas_imports.synology.SynologyClient
        copy_client = FakeClient()
        nas_imports.synology.SynologyClient = lambda: copy_client
        try:
            drive_file_id = nas_imports.approve_import(conn, row["id"], "root", 1)
        finally:
            nas_imports.synology.SynologyClient = old_client

        row = nas_imports.get_import(conn, row["id"])
        expected_folder = "/google/04 Product Images/01 Craftsman Golf/03 Driver Cover/6012065 CF - Pink Birdie Driver Cover"
        self.assertEqual(
            drive_file_id,
            f"synology:{expected_folder}/6012065 Pink Birdie Driver Cover.jpg",
        )
        self.assertEqual(row["status"], "uploaded")
        self.assertEqual(
            copy_client.created[-1],
            ("/google/04 Product Images/01 Craftsman Golf/03 Driver Cover", "6012065 CF - Pink Birdie Driver Cover"),
        )
        self.assertEqual(copy_client.copied[0][1], expected_folder)
        self.assertTrue(copy_client.copied[0][0].endswith("/6012065.jpg"))
        self.assertEqual(
            copy_client.renamed,
            [(f"{expected_folder}/6012065.jpg", "6012065 Pink Birdie Driver Cover.jpg")],
        )
        conn.close()


if __name__ == "__main__":
    unittest.main()
