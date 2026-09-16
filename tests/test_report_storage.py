import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from src.infrastructure.report_storage import (
    MonthlyReportStorage,
    ReportValidationError,
    SupabaseReportStorage,
    create_report_storage,
)


class MonthlyReportStorageTests(TestCase):
    def test_rejects_non_xlsx_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = MonthlyReportStorage(Path(directory))

            with self.assertRaises(ReportValidationError):
                storage.save("sales", "report.csv", b"date,value")

    def test_rejects_unknown_report_type(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = MonthlyReportStorage(Path(directory))

            with self.assertRaises(ReportValidationError):
                storage.save("unknown", "report.xlsx", b"PK")

    def test_saves_sales_report_and_detects_period(self) -> None:
        source = Path("data/local/culinary_sales_june_july.xlsx")
        if not source.exists():
            self.skipTest("Локальная тестовая книга отсутствует")
        with tempfile.TemporaryDirectory() as directory:
            storage = MonthlyReportStorage(Path(directory))
            report = storage.save("sales", "../Продажи.xlsx", source.read_bytes())

            self.assertEqual(report.original_name, "Продажи.xlsx")
            self.assertEqual(report.period_start, "2026-06-01")
            self.assertEqual(report.period_end, "2026-08-03")
            self.assertEqual(len(storage.list()), 1)
            self.assertIsNotNone(storage.resolve(report.id))

            with self.assertRaises(ReportValidationError):
                storage.save("sales", "Повтор.xlsx", source.read_bytes())
            self.assertEqual(len(storage.list()), 1)
