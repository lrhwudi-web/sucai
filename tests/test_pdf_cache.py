import asyncio
import tempfile
import unittest
from pathlib import Path

from fastapi import Request
from fastapi.responses import FileResponse, StreamingResponse

from app import db, drive, local_media, main


def request_with_range(value: str = "") -> Request:
    headers = [(b"range", value.encode("ascii"))] if value else []
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/media/catalog-pdf",
            "headers": headers,
            "query_string": b"",
            "server": ("127.0.0.1", 8001),
            "client": ("127.0.0.1", 50000),
            "scheme": "http",
        }
    )


async def response_body(response: StreamingResponse) -> bytes:
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk)
    return b"".join(chunks)


class ProductCatalogPdfCacheTest(unittest.TestCase):
    def setUp(self):
        self.row = {
            "id": "catalog-pdf",
            "name": "2026 Product Catalog.pdf",
            "mime_type": "application/pdf",
            "size": 10,
            "modified_time": "2026-07-31T08:00:00Z",
            "other": "Product Catalogs",
        }

    def test_only_product_catalog_pdfs_use_the_local_pdf_cache(self):
        self.assertTrue(local_media.is_product_catalog_pdf(self.row))
        self.assertFalse(local_media.is_product_catalog_pdf({**self.row, "other": "Collection Assets"}))
        self.assertFalse(local_media.is_product_catalog_pdf({**self.row, "mime_type": "image/jpeg"}))

    def test_media_downloads_catalog_pdf_once_then_serves_local_file_and_ranges(self):
        class FakeConnection:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

        calls = []
        old_connect = db.connect
        old_get_file = db.get_file
        old_download = drive.download_file
        old_cache_dir = main.PDF_CACHE_DIR
        db.connect = lambda: FakeConnection()
        db.get_file = lambda _conn, _file_id, _role: self.row
        drive.download_file = lambda file_id, **_kwargs: (
            calls.append(file_id) or iter((b"01234", b"56789"))
        )
        try:
            with tempfile.TemporaryDirectory() as tmp:
                main.PDF_CACHE_DIR = Path(tmp)
                first = main.media(
                    "catalog-pdf",
                    request_with_range(),
                    user={"role": "admin"},
                )
                second = main.media(
                    "catalog-pdf",
                    request_with_range("bytes=2-5"),
                    user={"role": "admin"},
                )

                self.assertIsInstance(first, FileResponse)
                self.assertTrue(Path(first.path).is_file())
                self.assertEqual(first.headers["cache-control"], "private, max-age=31536000, immutable")
                self.assertIsInstance(second, StreamingResponse)
                self.assertEqual(second.status_code, 206)
                self.assertEqual(second.headers["content-range"], "bytes 2-5/10")
                self.assertEqual(asyncio.run(response_body(second)), b"2345")
        finally:
            db.connect = old_connect
            db.get_file = old_get_file
            drive.download_file = old_download
            main.PDF_CACHE_DIR = old_cache_dir

        self.assertEqual(calls, ["catalog-pdf"])

