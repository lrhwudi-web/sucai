import sys
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path.cwd()))

from app import db, drive, main, nas_imports


class ImageLoadingRegressionTest(unittest.TestCase):
    def test_pending_video_imports_have_an_admin_only_playback_route(self):
        backend = Path("app/main.py").read_text(encoding="utf-8")
        review = Path("app/fontend/src/admin/ReviewModals.tsx").read_text(encoding="utf-8")
        types = Path("app/fontend/src/admin/types.ts").read_text(encoding="utf-8")

        self.assertIn('@app.get("/admin/nas-imports/{import_id}/media")', backend)
        self.assertIn("<video", review)
        self.assertIn("mediaUrl: string", types)

    def test_admin_import_preview_generates_small_local_webp_once(self):
        source = Image.new("RGB", (800, 600), "#81452f")
        source_bytes = BytesIO()
        source.save(source_bytes, format="JPEG")
        row = {
            "id": 121,
            "name": "DSC08084.JPG",
            "local_path": "synology:/incoming/DSC08084.JPG",
            "mtime_ns": 1720603800000000000,
            "updated_at": "2026-07-29 10:00:00",
        }
        calls = []
        old_cache_dir = main.THUMB_CACHE_DIR
        old_download = nas_imports.download_synology_import
        nas_imports.download_synology_import = lambda _row: (
            calls.append(_row["id"]) or iter((source_bytes.getvalue(),))
        )
        try:
            with tempfile.TemporaryDirectory() as tmp:
                main.THUMB_CACHE_DIR = Path(tmp)
                first = main.populate_admin_import_thumbnail_cache(row)
                second = main.populate_admin_import_thumbnail_cache(row)
                self.assertEqual(first, second)
                self.assertEqual(first.parent, Path(tmp) / "imports")
                with Image.open(first) as result:
                    self.assertEqual(result.format, "WEBP")
                    self.assertEqual(result.size, (126, 110))
        finally:
            main.THUMB_CACHE_DIR = old_cache_dir
            nas_imports.download_synology_import = old_download

        self.assertEqual(calls, [121])

    def test_google_admin_import_uses_drive_thumbnail_not_original_file(self):
        source = Image.new("RGB", (640, 480), "#355c7d")
        source_bytes = BytesIO()
        source.save(source_bytes, format="JPEG")
        row = {
            "id": 170,
            "name": "product-front.jpg",
            "local_path": "gdrive:drive-file-170",
            "mtime_ns": 1720603800000000000,
            "updated_at": "2026-07-29 10:00:00",
        }
        old_cache_dir = main.THUMB_CACHE_DIR
        old_download_file = drive.download_file
        old_download_thumbnail = drive.download_thumbnail
        calls = []
        drive.download_file = lambda *_args, **_kwargs: self.fail(
            "Admin thumbnails must not download the original Drive image"
        )
        drive.download_thumbnail = lambda file_id, *_args: (
            calls.append(file_id) or (source_bytes.getvalue(), "image/jpeg", "")
        )
        try:
            with tempfile.TemporaryDirectory() as tmp:
                main.THUMB_CACHE_DIR = Path(tmp)
                generated = main.populate_admin_import_thumbnail_cache(row)
                with Image.open(generated) as result:
                    self.assertEqual(result.size, (126, 110))
        finally:
            main.THUMB_CACHE_DIR = old_cache_dir
            drive.download_file = old_download_file
            drive.download_thumbnail = old_download_thumbnail

        self.assertEqual(calls, ["drive-file-170"])

    def test_admin_import_preview_failure_returns_local_non_cached_placeholder(self):
        row = {
            "id": 121,
            "name": "DSC08084.JPG",
            "local_path": "synology:/incoming/DSC08084.JPG",
            "mtime_ns": 1720603800000000000,
            "updated_at": "2026-07-29 10:00:00",
        }

        class FakeConnection:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

        old_connect = db.connect
        old_get_import = nas_imports.get_import
        old_populate = main.populate_admin_import_thumbnail_cache
        db.connect = lambda: FakeConnection()
        nas_imports.get_import = lambda _conn, _import_id: row
        main.populate_admin_import_thumbnail_cache = lambda _row: (_ for _ in ()).throw(
            RuntimeError("SYNOLOGY_URL is not set")
        )
        try:
            response = main.admin_nas_import_preview(121, v="1720603800000000000", user={"role": "admin"})
        finally:
            db.connect = old_connect
            nas_imports.get_import = old_get_import
            main.populate_admin_import_thumbnail_cache = old_populate

        self.assertEqual(response.media_type, "image/webp")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["x-preview-state"], "source-unavailable")
        with Image.open(BytesIO(response.body)) as result:
            self.assertEqual(result.size, (126, 110))

    def test_uncached_thumb_returns_local_placeholder_without_scheduling_drive(self):
        row = {
            "id": "file-timeout",
            "mime_type": "image/jpeg",
            "thumbnail_link": "https://example.test/thumb",
            "modified_time": "2026-07-16T00:00:00Z",
        }

        class FakeConnection:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

        old_connect = db.connect
        old_get_file = db.get_file
        old_download = drive.download_thumbnail
        old_cache_dir = main.THUMB_CACHE_DIR
        old_schedule = main.schedule_thumbnail_warm
        db.connect = lambda: FakeConnection()
        db.get_file = lambda _conn, _file_id, _role: row
        drive.download_thumbnail = lambda *_args, **_kwargs: self.fail("Drive must not be called in the request path")
        main.schedule_thumbnail_warm = lambda *_args, **_kwargs: self.fail(
            "Browsing must not enqueue remote thumbnail work"
        )
        try:
            with tempfile.TemporaryDirectory() as tmp:
                main.THUMB_CACHE_DIR = Path(tmp)
                response = main.thumb("file-timeout", variant="drawer", user={"role": "admin"})
        finally:
            db.connect = old_connect
            db.get_file = old_get_file
            drive.download_thumbnail = old_download
            main.THUMB_CACHE_DIR = old_cache_dir
            main.schedule_thumbnail_warm = old_schedule

        self.assertEqual(response.media_type, "image/svg+xml")
        self.assertIn(b"Preview loading", response.body)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertNotIn("x-thumbnail-state", response.headers)

    def test_react_asset_images_preserve_lazy_cached_thumbnail_loading(self):
        asset_image = Path("app/fontend/src/components/AssetImage.tsx").read_text(encoding="utf-8")
        card = Path("app/fontend/src/components/ProductCard.tsx").read_text(encoding="utf-8")
        drawer = Path("app/fontend/src/components/ProductDrawer.tsx").read_text(encoding="utf-8")
        thumbnail_urls = Path("app/fontend/src/utils/thumbnails.ts").read_text(encoding="utf-8")

        self.assertNotIn("fetch(src", asset_image)
        self.assertNotIn("THUMBNAIL_RETRY_DELAY_MS", asset_image)
        self.assertNotIn("AbortController", asset_image)
        self.assertNotIn("URL.createObjectURL", asset_image)
        self.assertIn("AssetImage", card)
        self.assertIn('loading="lazy"', card)
        self.assertIn('fetchPriority={selected ? "high" : "low"}', card)
        self.assertIn('thumbnailVariantUrl(cover.thumbnailUrl, "drawer")', card)
        self.assertIn("AssetImage", drawer)
        self.assertIn('loading="lazy"', drawer)
        self.assertIn('thumbnailVariantUrl(selectedAsset.thumbnailUrl, "drawer")', drawer)
        self.assertIn('thumbnailVariantUrl(asset.thumbnailUrl, "small")', drawer)
        self.assertIn("URLSearchParams", thumbnail_urls)
        self.assertNotIn("previewSrc={selectedAsset.previewUrl}", drawer)
        self.assertIn('preload="none"', drawer)

    def test_pending_review_keeps_loaded_thumbnails_mounted_between_sections(self):
        panel = Path("app/fontend/src/admin/AdminPanel.tsx").read_text(encoding="utf-8")
        pending = Path("app/fontend/src/admin/PendingReview.tsx").read_text(encoding="utf-8")

        self.assertIn('hidden={section !== "pending"}', panel)
        self.assertNotIn('{section === "pending" && <PendingReview', panel)
        self.assertIn('loading="lazy"', pending)
        self.assertIn("ADMIN_PREVIEW_FALLBACK", pending)

    def test_product_catalog_pdfs_have_document_previews(self):
        types = Path("app/fontend/src/types.ts").read_text(encoding="utf-8")
        card = Path("app/fontend/src/components/ProductCard.tsx").read_text(encoding="utf-8")
        drawer = Path("app/fontend/src/components/ProductDrawer.tsx").read_text(encoding="utf-8")

        self.assertIn('"document"', types)
        self.assertIn('cover.kind === "document"', card)
        self.assertIn('selectedAsset.kind === "document"', drawer)
        self.assertIn("<iframe", drawer)

    def test_product_drawer_omits_public_permission_badge(self):
        drawer = Path("app/fontend/src/components/ProductDrawer.tsx").read_text(encoding="utf-8")

        self.assertNotIn("Approved for client use", drawer)


if __name__ == "__main__":
    unittest.main()
