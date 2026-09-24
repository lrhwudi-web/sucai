import tempfile
import unittest
from pathlib import Path

from app.nas_sync import PathMapping, load_mappings, plan_file, remote_is_current


class NasSyncTest(unittest.TestCase):
    def test_chinese_nas_folder_maps_to_drive_set_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            local_file = root / "产品图片" / "Craftsman" / "帽套" / "木杆帽套" / "6011822 自主 黑色PU猴子西服刺绣一号木帽套" / "1.jpg"
            local_file.parent.mkdir(parents=True)
            local_file.write_bytes(b"image")
            mapping = [
                PathMapping(
                    "产品图片/Craftsman/帽套/木杆帽套/6011822 自主 黑色PU猴子西服刺绣一号木帽套",
                    "04 Product Images/01 Craftsman Golf/01 Headcovers Set/Set00001 CF - Sunglass Gorilla Headcover Set/6011822 CF - Sunglass Gorilla Driver Cover",
                    "60128229({stem}){suffix}",
                )
            ]

            plan, reason = plan_file(local_file, root, mapping, settle_seconds=0)

            self.assertEqual(reason, "")
            self.assertIsNotNone(plan)
            self.assertEqual(plan.drive_name, "60128229(1).jpg")
            self.assertEqual(
                plan.drive_path,
                "04 Product Images/01 Craftsman Golf/01 Headcovers Set/Set00001 CF - Sunglass Gorilla Headcover Set/6011822 CF - Sunglass Gorilla Driver Cover/60128229(1).jpg",
            )

    def test_product_table_builds_set_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mapping_file = root / "products.csv"
            mapping_file.write_text(
                "\n".join(
                    [
                        "SKU,产品图,品名,英文品名,品牌,产品类型,销售状态,首次回货日,自动Set",
                        "6012065,,自主 桃红色PU皮BIRDIE刺绣两片式一号木帽套,Pink Birdie Driver Cover,Craftsman Golf,1号木杆套,,2024-12-03,Set00300",
                        "6014376,,自主 桃红色PU皮BIRDIE刺绣直条推杆帽套,Pink Birdie Blade Putter Cover,Craftsman Golf,直条推杆套,,2025-09-08,Set00300",
                        "6014375,,自主 桃红色PU皮BIRDIE刺绣单耳大半圆推杆帽套,Pink Birdie Mallet Putter Cover,Craftsman Golf,半圆推杆套,,2025-09-10,Set00300",
                    ]
                ),
                encoding="utf-8-sig",
            )
            local_file = root / "产品图片" / "Craftsman" / "帽套" / "木杆帽套" / "6012065 自主 桃红色PU皮BIRDIE刺绣两片式一号木帽套" / "1.jpg"
            local_file.parent.mkdir(parents=True)
            local_file.write_bytes(b"image")

            plan, reason = plan_file(local_file, root, load_mappings(mapping_file), settle_seconds=0)

            self.assertEqual(reason, "")
            self.assertEqual(
                plan.drive_path,
            "04 Product Images/01 Craftsman Golf/01 Headcover Set/Set00300 CF - Pink Birdie Headcover Set/6012065 CF - Pink Birdie Driver Cover/6012065(1).jpg",
            )

    def test_recent_or_unmapped_files_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            local_file = root / "unmapped.jpg"
            local_file.write_bytes(b"x")
            stat = local_file.stat()

            plan, reason = plan_file(local_file, root, [], now=stat.st_mtime + 1, settle_seconds=60)
            self.assertIsNone(plan)
            self.assertEqual(reason, "settling")

            plan, reason = plan_file(local_file, root, [], now=stat.st_mtime + 120, settle_seconds=60)
            self.assertIsNone(plan)
            self.assertEqual(reason, "unmapped")

    def test_remote_current_uses_nas_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            local_file = root / "a.jpg"
            local_file.write_bytes(b"x")
            mapping = [PathMapping("a.jpg", "Drive")]
            plan, _ = plan_file(local_file, root, mapping, settle_seconds=0)
            remote = {"appProperties": {"nasSize": str(plan.size), "nasMtimeNs": str(plan.mtime_ns)}}

            self.assertTrue(remote_is_current(remote, plan))
            self.assertFalse(remote_is_current({"appProperties": {"nasSize": "999"}}, plan))


if __name__ == "__main__":
    unittest.main()
