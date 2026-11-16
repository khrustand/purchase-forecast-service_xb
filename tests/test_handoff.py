import json
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from zipfile import ZipFile

from src.infrastructure.handoff import export_snapshot, verify_snapshot
from src.infrastructure.report_storage import MonthlyReport, MonthlyReportStorage


class HandoffTests(TestCase):
    def fixture(self, directory):
        root = Path(directory)
        reports = root / 'original'
        reports.mkdir()
        report = MonthlyReport('a'*32, 'sales', 'Синтетические продажи.xlsx', 'sales.xlsx',
                               '2026-06-01', '2026-08-03', '2026-11-16T12:00:00Z', 6)
        (reports/'sales.xlsx').write_bytes(b'PKtest')
        (reports/'manifest.json').write_text(json.dumps([asdict(report)]), encoding='utf-8')
        profile = root/'profile'
        (profile/'menu-uploads').mkdir(parents=True)
        (profile/'menu-uploads/menu.xlsx').write_bytes(b'PKmenu')
        (profile/'.env').write_text('PASSWORD=must-not-be-exported',encoding='utf-8')
        project = root/'project'
        (project/'data/examples').mkdir(parents=True)
        (project/'data/examples/test.json').write_text('{}')
        return root, MonthlyReportStorage(reports), project, profile

    def test_export_keeps_reports_ids_menu_and_has_integrity_manifest(self):
        with TemporaryDirectory() as directory:
            root, storage, project, profile = self.fixture(directory)
            archive = root/'handoff.zip'
            metadata = export_snapshot(storage, archive, project, profile, root/'no-state', 'revision')
            extracted = root/'copy'
            with ZipFile(archive) as book:
                self.assertFalse(any(Path(name).name == '.env' for name in book.namelist()))
                book.extractall(extracted)
            self.assertEqual(verify_snapshot(extracted)['reports'],1)
            restored = MonthlyReportStorage(extracted/'reports')
            self.assertEqual(restored.list()[0].id,'a'*32)
            self.assertEqual(restored.resolve('a'*32)[1].read_bytes(),b'PKtest')
            self.assertTrue((extracted/'localappdata/PurchaseForecastService/menu-uploads/menu.xlsx').exists())
            self.assertEqual(metadata['code_revision'],'revision')
            restored.resolve('a'*32)[1].write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError,'изменен'):
                verify_snapshot(extracted)

    def test_unavailable_report_does_not_produce_valid_snapshot(self):
        with TemporaryDirectory() as directory:
            root, storage, project, profile = self.fixture(directory)
            (storage.root/'sales.xlsx').unlink()
            with self.assertRaisesRegex(ValueError,'Недоступен отчет'):
                export_snapshot(storage,root/'broken.zip',project,profile,root/'no-state','revision')

    def test_known_secret_in_reference_is_rejected(self):
        with TemporaryDirectory() as directory:
            root, storage, project, profile = self.fixture(directory)
            (project/'reports').mkdir()
            (project/'reports/private.md').write_text('sensitive-test-value')
            with self.assertRaisesRegex(ValueError,'секретное значение'):
                export_snapshot(storage,root/'blocked.zip',project,profile,root/'no-state','revision',
                                forbidden_values=(b'sensitive-test-value',))
