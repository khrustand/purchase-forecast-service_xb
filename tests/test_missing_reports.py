import json
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock
from unittest.mock import patch
from http import HTTPStatus

from src.app.web_server import DashboardHandler, render_weather_status
from src.infrastructure.report_storage import MonthlyReport, ReportValidationError, SupabaseReportStorage


class MissingReportTests(TestCase):
    def test_cloud_mode_does_not_reuse_local_sales_after_deletion(self):
        from src.app import web_server as web
        with TemporaryDirectory() as directory:
            local = Path(directory) / 'old-sales.xlsx'
            local.write_bytes(b'old local report')
            with patch.object(web, 'REPORT_STORAGE') as storage, \
                 patch.object(web, 'load_met_norway_forecast', return_value=None), \
                 patch.object(web, 'read_xlsx') as read:
                storage.paths.return_value = []
                storage.storage_label.return_value = 'Supabase'
                self.assertIsNone(web.build_culinary_strategy_payload(sales_path=local))
                read.assert_not_called()

    def test_missing_remote_file_does_not_discard_readable_reports(self):
        reports = [MonthlyReport(id=c * 32, report_type='waste', original_name=f'{c}.xlsx',
                    stored_name=f'{c}.xlsx', period_start='2026-09-01', period_end='2026-09-30',
                    uploaded_at='', size=2, storage_path=f'{c}.xlsx') for c in ('a', 'b')]

        def request(method, url, headers, data):
            if '/rest/' in url:
                return 200, json.dumps([asdict(r) for r in reports]).encode()
            return (400, b'not found') if url.endswith('/a.xlsx') else (200, b'PK')

        with TemporaryDirectory() as directory:
            storage = SupabaseReportStorage('https://example.test', 'secret', cache_root=Path(directory), request=request)
            self.assertEqual([p.name for p in storage.paths('waste')], ['b.xlsx'])
            self.assertEqual(list(storage.unavailable_reports.values()), ['a.xlsx'])
        html = render_weather_status({'unavailable_reports': ['a.xlsx']})
        self.assertIn('Расчет неполный', html)
        self.assertIn('a.xlsx', html)

    def test_request_failure_returns_error_page(self):
        handler = object.__new__(DashboardHandler)
        handler._send_error_page = Mock()
        handler.log_message = Mock()
        for error, status in ((ReportValidationError('private detail'), HTTPStatus.SERVICE_UNAVAILABLE),
                              (ValueError('private detail'), HTTPStatus.INTERNAL_SERVER_ERROR)):
            handler._serve_request(Mock(side_effect=error))
            self.assertEqual(handler._send_error_page.call_args.args[0], status)
            self.assertNotIn('private detail', handler._send_error_page.call_args.args[1])
