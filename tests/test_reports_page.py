import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from unittest import TestCase
from unittest.mock import patch

from src.app.web_server import DashboardHandler, build_data_status, render_reports_html
from src.infrastructure.report_storage import MonthlyReport


class ReportsPageTests(TestCase):
    def _reports(self) -> list[MonthlyReport]:
        return [
            MonthlyReport(
                id="a" * 32,
                report_type="sales",
                original_name="Продажи июнь.xlsx",
                stored_name="sales.xlsx",
                period_start="2026-06-01",
                period_end="2026-06-30",
                uploaded_at="2026-09-15T00:00:00+00:00",
                size=12000,
            ),
            MonthlyReport(
                id="b" * 32,
                report_type="waste",
                original_name="Списания июнь.xlsx",
                stored_name="waste.xlsx",
                period_start="2026-06-01",
                period_end="2026-06-30",
                uploaded_at="2026-09-15T00:00:00+00:00",
                size=8000,
            ),
        ]

    def _fake_storage(self):
        reports = self._reports()

        class FakeStorage:
            def list(self):
                return reports

            def resolve(self, report_id: str):
                report = next((item for item in reports if item.id == report_id), None)
                return (report, object()) if report is not None else None

            def storage_label(self) -> str:
                return "Supabase"

        return FakeStorage()

    def test_builds_data_status_from_uploaded_reports(self) -> None:
        reports = self._reports()

        class FakeStorage:
            def list(self):
                return reports

            def resolve(self, report_id: str):
                return (reports[0], object()) if report_id == "a" * 32 else None

            def storage_label(self) -> str:
                return "Supabase"

        status = build_data_status(FakeStorage())

        self.assertEqual(status["storage"], "Supabase")
        self.assertEqual(status["counts"]["sales"], 1)
        self.assertEqual(status["counts"]["waste"], 1)
        self.assertTrue(status["sales_ready"])
        self.assertFalse(status["waste_ready"])
        self.assertTrue(status["forecast_ready"])
        self.assertIn("Продажи участвуют", status["summary"])
        self.assertEqual(status["reports"][0]["status"], "доступен")
        self.assertEqual(status["reports"][1]["status"], "ошибка чтения")

    def test_reports_page_shows_data_status_block(self) -> None:
        import src.app.web_server as web_server

        original = web_server.REPORT_STORAGE
        web_server.REPORT_STORAGE = self._fake_storage()
        try:
            html = render_reports_html()
        finally:
            web_server.REPORT_STORAGE = original

        self.assertIn("Используется в расчете", html)
        self.assertIn("Продажи: 1 файл", html)
        self.assertIn("Списания: 1 файл", html)
        self.assertIn("Продажи участвуют в расчете", html)
        self.assertIn("Продажи июнь.xlsx", html)

    def test_data_status_api_returns_json(self) -> None:
        import src.app.web_server as web_server

        original = web_server.REPORT_STORAGE
        web_server.REPORT_STORAGE = self._fake_storage()
        server = ThreadingHTTPServer(("127.0.0.1", 0), DashboardHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.dict("os.environ", {}, clear=True):
                connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                try:
                    connection.request("GET", "/api/data-status")
                    response = connection.getresponse()
                    payload = json.loads(response.read().decode("utf-8"))
                finally:
                    connection.close()
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()
            web_server.REPORT_STORAGE = original

        self.assertEqual(response.status, 200)
        self.assertEqual(payload["storage"], "Supabase")
        self.assertEqual(payload["counts"]["sales"], 1)
        self.assertTrue(payload["forecast_ready"])

    def test_unknown_page_returns_utf8_404_without_disconnect(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), DashboardHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.dict("os.environ", {}, clear=True):
                connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                try:
                    connection.request("GET", "/favicon.ico")
                    response = connection.getresponse()
                    body = response.read().decode("utf-8")
                finally:
                    connection.close()
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()

        self.assertEqual(response.status, 404)
        self.assertIn("Страница не найдена", body)

    def test_reports_page_shows_storage_backend(self) -> None:
        class FakeStorage:
            def list(self):
                return []

            def storage_label(self) -> str:
                return "Supabase"

        import src.app.web_server as web_server

        original = web_server.REPORT_STORAGE
        web_server.REPORT_STORAGE = FakeStorage()
        try:
            html = render_reports_html()
        finally:
            web_server.REPORT_STORAGE = original

        self.assertIn("Хранилище: Supabase", html)
