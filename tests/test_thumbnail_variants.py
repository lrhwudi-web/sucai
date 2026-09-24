import os
import queue
import tempfile
import time
import unittest
from io import BytesIO
from pathlib import Path

from PIL import Image

from app import main, thumbnails


class ThumbnailVariantTest(unittest.TestCase):
    def setUp(self):
        self.row = {
            "id": "image-1",
            "modified_time": "2026-07-28T00:00:00Z",
            "thumbnail_link": "https://example.test/thumb",
            "mime_type": "image/png",
            "size": 1024,
        }

    def test_variant_specs_match_display_density(self):
        self.assertEqual(thumbnails.variant("small").size, (126, 110))
        self.assertEqual(thumbnails.variant("drawer").size, (560, 416))
        self.assertEqual(thumbnails.variant("card").size, (440, 360))

    def test_cache_key_separates_variant_source_version_and_encoder_version(self):
        small = thumbnails.cache_key(self.row, "small")
        drawer = thumbnails.cache_key(self.row, "drawer")
        changed_source = thumbnails.cache_key({**self.row, "modified_time": "2026-07-29T00:00:00Z"}, "small")

        self.assertNotEqual(small, drawer)
        self.assertNotEqual(small, changed_source)
        self.assertTrue(thumbnails.cache_path(Path("cache"), self.row, "small").name.endswith(".webp"))
        self.assertIn(thumbnails.ENCODER_VERSION, thumbnails.cache_identity(self.row, "small"))

    def test_webp_encoder_contains_without_cropping(self):
        source = Image.new("RGB", (200, 50), "#d02030")
        source_bytes = BytesIO()
        source.save(source_bytes, format="PNG")

        encoded = thumbnails.encode_webp(source_bytes.getvalue(), "small")
        with Image.open(BytesIO(encoded)) as result:
            self.assertEqual(result.format, "WEBP")
            self.assertEqual(result.size, (126, 110))
            rgba = result.convert("RGBA")
            self.assertLess(rgba.getpixel((63, 5))[3], 20)
            self.assertGreater(rgba.getpixel((63, 55))[0], 150)

    def test_queue_claim_is_per_variant(self):
        old_jobs = main.thumbnail_jobs
        old_pending = main.thumbnail_jobs_pending
        old_sequence = main.thumbnail_job_sequence
        main.thumbnail_jobs = queue.PriorityQueue(maxsize=10)
        main.thumbnail_jobs_pending = set()
        main.thumbnail_job_sequence = iter(range(100))
        try:
            self.assertTrue(main.schedule_thumbnail_warm(self.row, "card"))
            self.assertTrue(main.schedule_thumbnail_warm(self.row, "drawer"))
            self.assertTrue(main.schedule_thumbnail_warm(self.row, "small"))
            self.assertFalse(main.schedule_thumbnail_warm(self.row, "drawer"))
            queued = [main.thumbnail_jobs.get_nowait()[2] for _ in range(3)]
        finally:
            main.thumbnail_jobs = old_jobs
            main.thumbnail_jobs_pending = old_pending
            main.thumbnail_job_sequence = old_sequence

        self.assertEqual([job["variant"] for job in queued], ["drawer", "small", "card"])

    def test_card_generation_uses_fast_thumbnail_source(self):
        source = Image.new("RGB", (220, 165), "#8b3d3d")
        source_bytes = BytesIO()
        source.save(source_bytes, format="JPEG")
        old_download_file = main.drive.download_file
        old_download_thumbnail = main.drive.download_thumbnail
        old_cache_dir = main.THUMB_CACHE_DIR
        main.drive.download_file = lambda _file_id: self.fail("Cards must not download the original image")
        main.drive.download_thumbnail = lambda *_args: (
            source_bytes.getvalue(),
            "image/jpeg",
            self.row["thumbnail_link"],
        )
        try:
            with tempfile.TemporaryDirectory() as tmp:
                main.THUMB_CACHE_DIR = Path(tmp)
                generated = main.populate_thumbnail_cache(self.row, "card")
                with Image.open(generated) as result:
                    self.assertEqual(result.size, (440, 360))
        finally:
            main.drive.download_file = old_download_file
            main.drive.download_thumbnail = old_download_thumbnail
            main.THUMB_CACHE_DIR = old_cache_dir

    def test_bundle_downloads_one_google_thumbnail_and_writes_every_local_variant(self):
        source = Image.new("RGB", (640, 480), "#1f694c")
        source_bytes = BytesIO()
        source.save(source_bytes, format="JPEG")
        old_download_file = main.drive.download_file
        old_download_thumbnail = main.drive.download_thumbnail
        old_cache_dir = main.THUMB_CACHE_DIR
        calls = []
        main.drive.download_file = lambda _file_id: self.fail(
            "Thumbnail backfill must not download original images"
        )

        def fake_thumbnail(*args):
            calls.append(args)
            return source_bytes.getvalue(), "image/jpeg", self.row["thumbnail_link"]

        main.drive.download_thumbnail = fake_thumbnail
        try:
            with tempfile.TemporaryDirectory() as tmp:
                main.THUMB_CACHE_DIR = Path(tmp)
                generated = main.populate_thumbnail_bundle(self.row)
                self.assertEqual(set(generated), {"small", "drawer"})
                for name, expected_size in {
                    "small": (126, 110),
                    "drawer": (560, 416),
                }.items():
                    with Image.open(generated[name]) as result:
                        self.assertEqual(result.size, expected_size)
        finally:
            main.drive.download_file = old_download_file
            main.drive.download_thumbnail = old_download_thumbnail
            main.THUMB_CACHE_DIR = old_cache_dir

        self.assertEqual(len(calls), 1)

    def test_bundle_retries_transient_thumbnail_transport_errors(self):
        source = Image.new("RGB", (320, 240), "#224466")
        source_bytes = BytesIO()
        source.save(source_bytes, format="JPEG")
        old_download_thumbnail = main.drive.download_thumbnail
        old_cache_dir = main.THUMB_CACHE_DIR
        old_sleep = main.time.sleep
        attempts = []

        class TransportError(Exception):
            pass

        def flaky_thumbnail(*_args):
            attempts.append(1)
            if len(attempts) < 3:
                raise TransportError("temporary")
            return source_bytes.getvalue(), "image/jpeg", self.row["thumbnail_link"]

        main.drive.download_thumbnail = flaky_thumbnail
        main.time.sleep = lambda *_args: None
        try:
            with tempfile.TemporaryDirectory() as tmp:
                main.THUMB_CACHE_DIR = Path(tmp)
                generated = main.populate_thumbnail_bundle(self.row)
        finally:
            main.drive.download_thumbnail = old_download_thumbnail
            main.THUMB_CACHE_DIR = old_cache_dir
            main.time.sleep = old_sleep

        self.assertEqual(len(attempts), 3)
        self.assertEqual(set(generated), {"small", "drawer"})

    def test_bundle_generates_local_placeholder_when_drive_has_no_thumbnail(self):
        old_download_thumbnail = main.drive.download_thumbnail
        old_cache_dir = main.THUMB_CACHE_DIR
        main.drive.download_thumbnail = lambda *_args: (_ for _ in ()).throw(
            RuntimeError("Google Drive did not provide a thumbnail")
        )
        row = {**self.row, "name": "artwork.psd", "mime_type": "image/x-photoshop"}
        try:
            with tempfile.TemporaryDirectory() as tmp:
                main.THUMB_CACHE_DIR = Path(tmp)
                generated = main.populate_thumbnail_bundle(row)
                for name, expected_size in {
                    "small": (126, 110),
                    "drawer": (560, 416),
                }.items():
                    with Image.open(generated[name]) as result:
                        self.assertEqual(result.format, "WEBP")
                        self.assertEqual(result.size, expected_size)
        finally:
            main.drive.download_thumbnail = old_download_thumbnail
            main.THUMB_CACHE_DIR = old_cache_dir

    def test_backfill_enqueues_every_previewable_file_not_documents(self):
        rows = [
            {**self.row, "id": "image-1", "mime_type": "image/jpeg"},
            {**self.row, "id": "video-1", "mime_type": "video/mp4"},
        ]

        class FakeConnection:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def execute(self, *_args):
                return self

            def fetchall(self):
                return rows

        old_connect = main.db.connect
        old_schedule = main.schedule_thumbnail_bundle
        old_cache_entry = main.thumbnail_cache_entry
        scheduled = []
        main.db.connect = lambda: FakeConnection()
        main.schedule_thumbnail_bundle = (
            lambda row, block=True: scheduled.append((row["id"], block)) and False
        )
        main.thumbnail_cache_entry = lambda *_args: (Path("cached.webp"), "image/webp")
        try:
            ready, total = main.warm_thumbnail_cache_all()
        finally:
            main.db.connect = old_connect
            main.schedule_thumbnail_bundle = old_schedule
            main.thumbnail_cache_entry = old_cache_entry

        self.assertEqual(scheduled, [("image-1", True), ("video-1", True)])
        self.assertEqual((ready, total), (2, 2))

    def test_variant_miss_serves_current_legacy_cache_as_provisional_image(self):
        class FakeConnection:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

        old_connect = main.db.connect
        old_get_file = main.db.get_file
        old_cache_dir = main.THUMB_CACHE_DIR
        main.db.connect = lambda: FakeConnection()
        main.db.get_file = lambda *_args: self.row
        try:
            with tempfile.TemporaryDirectory() as tmp:
                main.THUMB_CACHE_DIR = Path(tmp)
                legacy = Path(tmp) / f"{thumbnails.legacy_cache_key(self.row)}.jpg"
                legacy.write_bytes(b"legacy-preview")
                response = main.thumb("image-1", variant="drawer", user={"role": "admin"})
        finally:
            main.db.connect = old_connect
            main.db.get_file = old_get_file
            main.THUMB_CACHE_DIR = old_cache_dir

        self.assertEqual(Path(response.path), legacy)
        self.assertNotIn("x-thumbnail-state", response.headers)
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_current_legacy_cache_names_are_protected_from_cleanup(self):
        names = thumbnails.active_legacy_cache_names([self.row])

        self.assertIn(f"{thumbnails.legacy_cache_key(self.row)}.jpg", names)
        self.assertIn(f"{thumbnails.legacy_cache_key(self.row)}.png", names)

    def test_drawer_generation_uses_google_thumbnail_not_original_stream(self):
        source = Image.new("RGB", (900, 300), "#2a4b7c")
        source_bytes = BytesIO()
        source.save(source_bytes, format="JPEG")
        old_download_file = main.drive.download_file
        old_download_thumbnail = main.drive.download_thumbnail
        old_cache_dir = main.THUMB_CACHE_DIR
        main.drive.download_file = lambda _file_id: self.fail("Drawer must not use the original image")
        main.drive.download_thumbnail = lambda *_args: (
            source_bytes.getvalue(),
            "image/jpeg",
            self.row["thumbnail_link"],
        )
        try:
            with tempfile.TemporaryDirectory() as tmp:
                main.THUMB_CACHE_DIR = Path(tmp)
                generated = main.populate_thumbnail_cache(self.row, "drawer")
                with Image.open(generated) as result:
                    self.assertEqual(result.format, "WEBP")
                    self.assertEqual(result.size, (560, 416))
        finally:
            main.drive.download_file = old_download_file
            main.drive.download_thumbnail = old_download_thumbnail
            main.THUMB_CACHE_DIR = old_cache_dir

    def test_cleanup_removes_only_old_orphan_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            active = cache_dir / f"{'a' * 64}.webp"
            orphan = cache_dir / f"{'b' * 64}.webp"
            recent = cache_dir / f"{'c' * 64}.webp"
            for path in (active, orphan, recent):
                path.write_bytes(b"cache")
            old = time.time() - 10_000
            os.utime(active, (old, old))
            os.utime(orphan, (old, old))

            removed = thumbnails.cleanup_cache(
                cache_dir,
                active_names={active.name},
                grace_seconds=3_600,
                now=time.time(),
            )

            self.assertEqual(removed, 1)
            self.assertTrue(active.exists())
            self.assertFalse(orphan.exists())
            self.assertTrue(recent.exists())


if __name__ == "__main__":
    unittest.main()
