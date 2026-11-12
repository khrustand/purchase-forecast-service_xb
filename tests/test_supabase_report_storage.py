import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from unittest import TestCase
from unittest.mock import patch

from src.infrastructure.report_storage import (
    MonthlyReportStorage,
    ReportValidationError,
    SupabaseReportStorage,
    create_report_storage,
)


class ReportStorageBackendTests(TestCase):
    def test_cached_file_is_not_used_after_report_row_is_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report_id = 'a' * 32
            cached = Path(directory) / f'sales-{report_id}.xlsx'
            cached.write_bytes(b'cached workbook')
            storage = SupabaseReportStorage(
                url='https://example.supabase.co', service_role_key='secret',
                cache_root=Path(directory), request=lambda *args: (200, b'[]'),
            )
            self.assertEqual(storage.list(), [])
            self.assertIsNone(storage.resolve(report_id))
            self.assertEqual(storage.paths('sales'), [])

    def test_storage_factory_uses_local_backend_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict("os.environ", {"REPORT_UPLOAD_DIR": directory}, clear=True):
                storage = create_report_storage()

        self.assertIsInstance(storage, MonthlyReportStorage)
        self.assertEqual(storage.storage_label(), "Локальное хранилище")

    def test_storage_factory_rejects_incomplete_supabase_config(self) -> None:
        with patch.dict("os.environ", {"STORAGE_BACKEND": "supabase"}, clear=True):
            with self.assertRaises(ReportValidationError):
                create_report_storage()

    def test_supabase_storage_saves_metadata_and_downloads_file(self) -> None:
        source = Path("data/local/culinary_sales_june_july.xlsx")
        if not source.exists():
            self.skipTest("Локальная тестовая книга отсутствует")
        calls: list[tuple[str, str, bytes | None]] = []
        saved_payloads: list[dict[str, object]] = []
        original_bytes = source.read_bytes()

        def fake_request(method: str, url: str, headers: dict[str, str], data: bytes | None = None) -> tuple[int, bytes]:
            calls.append((method, url, data))
            if method == "GET" and "/rest/v1/uploaded_reports" in url:
                import json

                return 200, json.dumps(saved_payloads).encode("utf-8")
            if method == "POST" and "/storage/v1/object/uploads/" in url:
                return 200, b'{"Key":"ok"}'
            if method == "POST" and "/rest/v1/uploaded_reports" in url:
                import json

                saved_payloads.append(json.loads((data or b"{}").decode("utf-8")))
                return 201, b"[]"
            if method == "GET" and "/storage/v1/object/uploads/" in url:
                return 200, original_bytes
            return 500, b"unexpected"

        with tempfile.TemporaryDirectory() as directory:
            storage = SupabaseReportStorage(
                url="https://example.supabase.co",
                service_role_key="secret",
                bucket="uploads",
                cache_root=Path(directory),
                request=fake_request,
            )

            report = storage.save("sales", "../Продажи.xlsx", original_bytes)
            resolved = storage.resolve(report.id)
            self.assertIsNotNone(resolved)
            self.assertEqual(resolved[1].read_bytes(), original_bytes)

        self.assertEqual(report.period_start, "2026-06-01")
        self.assertEqual(report.period_end, "2026-08-03")
        self.assertEqual(report.original_name, "Продажи.xlsx")
        self.assertEqual(report.storage_path, saved_payloads[0]["storage_path"])
        self.assertTrue(any(call[0] == "POST" and "/storage/v1/object/uploads/" in call[1] for call in calls))

    def test_supabase_storage_falls_back_to_database_chunks_when_storage_upload_fails(self) -> None:
        source = Path("data/local/culinary_sales_june_july.xlsx")
        if not source.exists():
            self.skipTest("Локальная тестовая книга отсутствует")
        saved_payloads: list[dict[str, object]] = []
        saved_chunks: list[dict[str, object]] = []
        chunk_payload_sizes: list[int] = []
        chunk_posts = 0
        original_bytes = source.read_bytes()

        def fake_request(method: str, url: str, headers: dict[str, str], data: bytes | None = None) -> tuple[int, bytes]:
            nonlocal chunk_posts
            if method == "GET" and "/rest/v1/uploaded_reports" in url:
                import json

                return 200, json.dumps(saved_payloads).encode("utf-8")
            if method == "GET" and "/rest/v1/uploaded_report_chunks" in url:
                import json

                query = parse_qs(urlparse(url).query)
                limit = int(query.get("limit", [len(saved_chunks)])[0])
                offset = int(query.get("offset", [0])[0])
                ordered = sorted(saved_chunks, key=lambda item: item["chunk_index"])
                return 200, json.dumps(ordered[offset : offset + limit]).encode("utf-8")
            if method == "POST" and "/storage/v1/object/uploads/" in url:
                raise ConnectionError("connection closed")
            if method == "POST" and "/rest/v1/uploaded_report_chunks" in url:
                import json

                chunk_posts += 1
                chunk_payload_sizes.append(len(data or b""))
                self.assertTrue(saved_payloads, "Chunks must be saved after the parent report row")
                payload = json.loads((data or b"{}").decode("utf-8"))
                self.assertIsInstance(payload, dict)
                saved_chunks.append(payload)
                return 201, b"[]"
            if method == "POST" and "/rest/v1/uploaded_reports" in url:
                import json

                saved_payloads.append(json.loads((data or b"{}").decode("utf-8")))
                return 201, b"[]"
            return 500, b"unexpected"

        with tempfile.TemporaryDirectory() as directory:
            storage = SupabaseReportStorage(
                url="https://example.supabase.co",
                service_role_key="secret",
                bucket="uploads",
                cache_root=Path(directory),
                request=fake_request,
            )

            report = storage.save("sales", "Продажи.xlsx", original_bytes)
            resolved = storage.resolve(report.id)
            self.assertIsNotNone(resolved)
            self.assertEqual(resolved[1].read_bytes(), original_bytes)

        self.assertEqual(report.storage_path, f"chunks:{report.id}")
        self.assertEqual(saved_payloads[0]["storage_path"], f"chunks:{report.id}")
        self.assertGreater(len(saved_chunks), 1)
        self.assertEqual(chunk_posts, len(saved_chunks))
        self.assertLessEqual(max(chunk_payload_sizes), 7000)

    def test_supabase_storage_removes_report_when_chunk_upload_fails(self) -> None:
        source = Path("data/local/culinary_sales_june_july.xlsx")
        if not source.exists():
            self.skipTest("Р›РѕРєР°Р»СЊРЅР°СЏ С‚РµСЃС‚РѕРІР°СЏ РєРЅРёРіР° РѕС‚СЃСѓС‚СЃС‚РІСѓРµС‚")
        saved_payloads: list[dict[str, object]] = []
        deleted_urls: list[str] = []
        original_bytes = source.read_bytes()

        def fake_request(method: str, url: str, headers: dict[str, str], data: bytes | None = None) -> tuple[int, bytes]:
            if method == "GET" and "/rest/v1/uploaded_reports" in url:
                import json

                return 200, json.dumps(saved_payloads).encode("utf-8")
            if method == "POST" and "/storage/v1/object/uploads/" in url:
                raise ConnectionError("connection closed")
            if method == "POST" and "/rest/v1/uploaded_reports" in url:
                import json

                saved_payloads.append(json.loads((data or b"{}").decode("utf-8")))
                return 201, b"[]"
            if method == "POST" and "/rest/v1/uploaded_report_chunks" in url:
                raise ConnectionError("chunk upload failed")
            if method == "DELETE" and "/rest/v1/uploaded_reports" in url:
                deleted_urls.append(url)
                return 204, b""
            return 500, b"unexpected"

        with tempfile.TemporaryDirectory() as directory:
            storage = SupabaseReportStorage(
                url="https://example.supabase.co",
                service_role_key="secret",
                bucket="uploads",
                cache_root=Path(directory),
                request=fake_request,
            )

            with self.assertRaises(ReportValidationError):
                storage.save("sales", "РџСЂРѕРґР°Р¶Рё.xlsx", original_bytes)

        self.assertEqual(len(deleted_urls), 1)
        self.assertIn("id=eq.", deleted_urls[0])

    def test_supabase_resolve_downloads_chunks_in_small_pages(self) -> None:
        import base64
        import json

        original_bytes = b"x" * 25000
        chunks = [
            {
                "chunk_index": index,
                "content_base64": base64.b64encode(original_bytes[offset : offset + 4096]).decode("ascii"),
            }
            for index, offset in enumerate(range(0, len(original_bytes), 4096))
        ]
        report_payload = {
            "id": "b" * 32,
            "report_type": "sales",
            "original_name": "report.xlsx",
            "stored_name": "sales-chunks.xlsx",
            "period_start": "2026-06-01",
            "period_end": "2026-08-03",
            "uploaded_at": "2026-09-15T00:00:00+00:00",
            "size": len(original_bytes),
            "storage_path": "chunks:" + ("b" * 32),
        }
        chunk_urls: list[str] = []

        def fake_request(method: str, url: str, headers: dict[str, str], data: bytes | None = None) -> tuple[int, bytes]:
            if method == "GET" and "/rest/v1/uploaded_reports" in url:
                return 200, json.dumps([report_payload]).encode("utf-8")
            if method == "GET" and "/rest/v1/uploaded_report_chunks" in url:
                chunk_urls.append(url)
                query = parse_qs(urlparse(url).query)
                self.assertEqual(query.get("limit"), ["1"])
                offset = int(query.get("offset", ["0"])[0])
                return 200, json.dumps(chunks[offset : offset + 1]).encode("utf-8")
            return 500, b"unexpected"

        with tempfile.TemporaryDirectory() as directory:
            storage = SupabaseReportStorage(
                url="https://example.supabase.co",
                service_role_key="secret",
                bucket="uploads",
                cache_root=Path(directory),
                request=fake_request,
            )

            resolved = storage.resolve("b" * 32)

            self.assertIsNotNone(resolved)
            self.assertEqual(resolved[1].read_bytes(), original_bytes)

        self.assertEqual(len(chunk_urls), len(chunks) + 1)

    def test_supabase_resolve_redownloads_cached_file_with_wrong_size(self) -> None:
        source = Path("data/local/culinary_sales_june_july.xlsx")
        if not source.exists():
            self.skipTest("Локальная тестовая книга отсутствует")
        original_bytes = source.read_bytes()
        report_payload = {
            "id": "a" * 32,
            "report_type": "sales",
            "original_name": "Продажи.xlsx",
            "stored_name": "sales-cache.xlsx",
            "period_start": "2026-06-01",
            "period_end": "2026-08-03",
            "uploaded_at": "2026-09-15T00:00:00+00:00",
            "size": len(original_bytes),
            "storage_path": "reports/sales/sales-cache.xlsx",
        }

        def fake_request(method: str, url: str, headers: dict[str, str], data: bytes | None = None) -> tuple[int, bytes]:
            import json

            if method == "GET" and "/rest/v1/uploaded_reports" in url:
                return 200, json.dumps([report_payload]).encode("utf-8")
            if method == "GET" and "/storage/v1/object/uploads/" in url:
                return 200, original_bytes
            return 500, b"unexpected"

        with tempfile.TemporaryDirectory() as directory:
            cache_root = Path(directory)
            stale_file = cache_root / "sales-cache.xlsx"
            stale_file.write_bytes(b"wrong")
            storage = SupabaseReportStorage(
                url="https://example.supabase.co",
                service_role_key="secret",
                bucket="uploads",
                cache_root=cache_root,
                request=fake_request,
            )

            resolved = storage.resolve("a" * 32)

            self.assertIsNotNone(resolved)
            self.assertEqual(resolved[1].read_bytes(), original_bytes)
