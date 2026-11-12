from io import BytesIO
from unittest import TestCase
from unittest.mock import Mock, patch

from src.app.web_server import DashboardHandler, save_upload_batch, selected_upload_files
from src.infrastructure.report_storage import ReportValidationError


class BatchUploadTests(TestCase):
    def test_multipart_preserves_repeated_file_field(self):
        body = (b'--batch\r\nContent-Disposition: form-data; name="report_type"\r\n\r\nsales\r\n'
                b'--batch\r\nContent-Disposition: form-data; name="file"; filename="one.xlsx"\r\n\r\nPK1\r\n'
                b'--batch\r\nContent-Disposition: form-data; name="file"; filename="two.xlsx"\r\n\r\nPK2\r\n'
                b'--batch--\r\n')
        handler = object.__new__(DashboardHandler)
        handler.headers = {'Content-Length': str(len(body)), 'Content-Type': 'multipart/form-data; boundary=batch'}
        handler.rfile = BytesIO(body)
        self.assertEqual(selected_upload_files(handler._read_multipart_parts()),
                         [('one.xlsx', b'PK1'), ('two.xlsx', b'PK2')])

    def test_batch_continues_after_duplicate_and_invalid_file(self):
        save = Mock(side_effect=[ReportValidationError('Дубликат'), None])
        message, errors = save_upload_batch([('one.xlsx', b'PK1'), ('bad.txt', b'bad'), ('two.xlsx', b'PK2')], save)
        self.assertEqual(save.call_count, 2)
        self.assertIn('1 из 3', message)
        self.assertIn('Дубликат', errors)
        self.assertIn('bad.txt', errors)

    def test_rejects_empty_and_too_many_files(self):
        for parts in ([], [('file', f'{i}.xlsx', b'PK') for i in range(101)]):
            with self.assertRaises(ReportValidationError):
                selected_upload_files(parts)

    def test_accepts_month_of_daily_reports_and_batch_limit(self):
        for count in (31, 62, 100):
            with self.subTest(count=count):
                parts = [('file', f'{i}.xlsx', b'PK') for i in range(count)]
                self.assertEqual(len(selected_upload_files(parts)), count)

    def test_total_size_limit_is_enforced(self):
        with patch('src.app.web_server.MAX_BATCH_UPLOAD_BYTES', 10):
            self.assertEqual(len(selected_upload_files([('file', 'a.xlsx', b'12345'), ('file', 'b.xlsx', b'12345')])), 2)
            with self.assertRaises(ReportValidationError):
                selected_upload_files([('file', 'a.xlsx', b'123456'), ('file', 'b.xlsx', b'12345')])

    def test_post_saves_each_file_with_selected_report_type(self):
        handler = object.__new__(DashboardHandler)
        handler.path = '/reports/upload'
        handler._authorize = lambda: True
        handler._redirect = Mock()
        handler._read_multipart_parts = lambda: [('report_type', None, b'waste'),
                                                ('file', 'one.xlsx', b'PK1'), ('file', 'two.xlsx', b'PK2')]
        with patch('src.app.web_server.REPORT_STORAGE') as storage:
            handler.do_POST()
            self.assertEqual(storage.save.call_args_list[0].args, ('waste', 'one.xlsx', b'PK1'))
            self.assertEqual(storage.save.call_args_list[1].args, ('waste', 'two.xlsx', b'PK2'))
        self.assertIn('/reports?message=', handler._redirect.call_args.args[0])
