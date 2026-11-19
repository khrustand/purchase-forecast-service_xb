import base64
from datetime import date, datetime
from http.client import HTTPConnection
from io import BytesIO
import threading
from unittest import TestCase
from unittest.mock import patch
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from src.app import web_server as web
from src.app.order_exports import OrderDownload, OrderExportStore, prepare_order_download
from src.infrastructure.order_workbook import NS, MIME_TYPE


def sample_strategy():
    dates = ['2026-11-20', '2026-11-21', '2026-11-22']
    return {
        'period': '2026-11-01..2026-11-15',
        'matrix_proposal': {'rows': [{'sku': '00123', 'name': '=Блюдо & <рыба>'}]},
        'future_orders': [{
            'start': dates[0], 'end': dates[-1], 'deadline': '2026-11-18T18:00:00+03:00',
            'daily_totals': [{'date': day} for day in dates],
            'rows': [{'name': '=Блюдо & <рыба>', 'category': 'Горячее', 'shelf_life_days': 3,
                      'daily_forecast': [{'date': day, 'quantity': q, 'staff_quantity': staff}
                                         for day, q, staff in zip(dates, [3, 2, 1], [1, 0, 0])]}],
        }],
        'production_days': [{'date': day, 'rows': [{'name': 'Каша овсяная', 'category': 'Кулинария. Готовка на ТТ',
                                                  'quantity': q, 'staff_quantity': 1}]}
                            for day, q in zip(dates, [8, 5, 6])]
                           + [{'date': '2026-11-23', 'rows': [{'name': 'Лишняя дата', 'category': 'ТТ', 'quantity': 999}]}],
    }


def sheet_cells(content, number):
    with ZipFile(BytesIO(content)) as archive:
        root = ET.fromstring(archive.read(f'xl/worksheets/sheet{number}.xml'))
    return root, {cell.attrib['r']: cell for cell in root.findall(f'.//{{{NS}}}c')}


def value(cell):
    return cell.findtext(f'{{{NS}}}v') or cell.findtext(f'{{{NS}}}is/{{{NS}}}t')


class OrderWorkbookTests(TestCase):
    def test_printable_layout_exact_portions_and_safe_text(self):
        download = prepare_order_download(sample_strategy())
        with ZipFile(BytesIO(download.content)) as archive:
            self.assertIsNone(archive.testzip())
            book = ET.fromstring(archive.read('xl/workbook.xml'))
            self.assertEqual([s.attrib['name'] for s in book.findall(f'{{{NS}}}sheets/{{{NS}}}sheet')], ['Поставка', 'Кулинария ТТ'])
            areas = book.findall(f'{{{NS}}}definedNames/{{{NS}}}definedName')
            self.assertEqual([area.text for area in areas], ["'Поставка'!$A$1:$D$4", "'Кулинария ТТ'!$A$1:$G$4"])
        root, cells = sheet_cells(download.content, 1)
        self.assertEqual(value(cells['A1']), 'Поставка 20.11.2026 утром. Заказать до 18.11.2026 18:00 МСК.')
        self.assertEqual([value(cells[f'{col}2']) for col in 'ABCD'], ['Артикул', 'Название', 'Категория', 'Порций\nк заказу'])
        self.assertNotIn('E2', cells)
        self.assertEqual(value(cells['A3']), '00123')
        self.assertEqual(value(cells['B3']), '=Блюдо & <рыба>')
        self.assertEqual(cells['B3'].attrib['t'], 'inlineStr')
        self.assertIsNone(cells['B3'].find(f'{{{NS}}}f'))
        self.assertEqual([value(cells[ref]) for ref in ('D3', 'D4')], ['6', '6'])
        self.assertIn('SUM(D3:D3)', cells['D4'].findtext(f'{{{NS}}}f'))
        self.assertEqual(root.find(f'{{{NS}}}sheetViews/{{{NS}}}sheetView/{{{NS}}}pane').attrib['state'], 'frozen')
        own_root, own = sheet_cells(download.content, 2)
        self.assertEqual(value(own['A1']), 'Кулинария ТТ: 20.11.2026–22.11.2026')
        self.assertEqual(value(own['D2']), str((date(2026, 11, 20) - date(1899, 12, 30)).days))
        self.assertEqual([value(own[f'{col}3']) for col in 'DEFG'], ['8', '5', '6', '19'])
        self.assertEqual(value(own['G4']), '19')
        self.assertIn('SUM(D3:F3)', own['G3'].findtext(f'{{{NS}}}f'))
        self.assertNotIn('Лишняя дата', ''.join(own_root.itertext()))
        for sheet, orientation in [(root, 'portrait'), (own_root, 'landscape')]:
            self.assertEqual(sheet.find(f'{{{NS}}}sheetPr/{{{NS}}}pageSetUpPr').get('fitToPage'), '1')
            self.assertEqual(sheet.find(f'{{{NS}}}pageSetup').attrib,
                             {'paperSize': '9', 'orientation': orientation, 'fitToWidth': '1', 'fitToHeight': '1'})
        self.assertIn('culinary-order-2026-11-20.xlsx', download.filename)

    def test_missing_is_visible_and_real_zero_is_numeric(self):
        strategy = sample_strategy()
        strategy['future_orders'][0]['rows'][0]['daily_forecast'][0]['quantity'] = None
        strategy['production_days'][0]['rows'][0]['quantity'] = 0
        strategy['production_days'][1]['rows'] = []
        download = prepare_order_download(strategy)
        _, cells = sheet_cells(download.content, 1)
        self.assertEqual(value(cells['D3']), 'нет данных')
        self.assertEqual(value(cells['D4']), 'нет данных')
        _, own = sheet_cells(download.content, 2)
        self.assertEqual(value(own['D3']), '0')
        self.assertNotIn('t', own['D3'].attrib)
        self.assertEqual(value(own['E3']), 'нет данных')
        self.assertEqual(value(own['G3']), 'нет данных')

    def test_unknown_model_does_not_export_placeholder_zero(self):
        strategy = sample_strategy()
        row = strategy['future_orders'][0]['rows'][0]
        row['quantity_unknown'] = True
        row['shelf_life_days'] = 2
        for day in row['daily_forecast']:
            day['quantity'] = 0
        _, cells = sheet_cells(prepare_order_download(strategy).content, 1)
        self.assertEqual(value(cells['D3']), 'нет данных')

    def test_two_day_order_does_not_include_next_day_tt(self):
        strategy = sample_strategy()
        strategy['future_orders'][0]['daily_totals'].pop()
        strategy['future_orders'][0]['rows'][0]['daily_forecast'].pop()
        _, cells = sheet_cells(prepare_order_download(strategy).content, 2)
        self.assertEqual(value(cells['F3']), '13')  # 8 + 5, no third day.
        self.assertNotIn('G2', cells)

    def test_disabled_tt_does_not_break_supplier_download(self):
        strategy = sample_strategy()
        for day in strategy['production_days']:
            day['rows'] = []
        _, cells = sheet_cells(prepare_order_download(strategy).content, 2)
        self.assertEqual(value(cells['A3']), 'Итого ТТ')
        self.assertEqual(value(cells['G3']), '0')
        self.assertIsNone(cells['G3'].find(f'{{{NS}}}f'))  # No reversed range or circular total.

    def test_snapshot_survives_source_changes_and_expires(self):
        strategy = sample_strategy()
        store = OrderExportStore(max_entries=2, ttl_seconds=10)
        with patch('src.app.order_exports.monotonic', return_value=0):
            download = prepare_order_download(strategy)
            token = store.add(download)
        strategy['future_orders'][0]['rows'][0]['daily_forecast'][0]['quantity'] = 999
        with patch('src.app.order_exports.monotonic', return_value=9):
            self.assertEqual(store.get(token), download)
            store.add(OrderDownload('second.xlsx', b'second'))
            store.add(OrderDownload('third.xlsx', b'third'))
            self.assertIsNone(store.get(token))
        with patch('src.app.order_exports.monotonic', return_value=19):
            self.assertIsNone(store.get('missing'))
            self.assertEqual(len(store._entries), 0)


class OrderDownloadHttpTests(TestCase):
    def test_download_requires_login_and_does_not_recalculate(self):
        server = web.DashboardServer(('127.0.0.1', 0), web.DashboardHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.shutdown)
        download = prepare_order_download(sample_strategy())
        token = server.order_exports.add(download)

        def get(path, headers=None):
            connection = HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            try:
                connection.request('GET', path, headers=headers or {})
                response = connection.getresponse()
                return response.status, dict(response.getheaders()), response.read()
            finally:
                connection.close()

        headers = {'Authorization': 'Basic ' + base64.b64encode(b'test:password').decode()}
        with patch.dict('os.environ', {'APP_USERNAME': 'test', 'APP_PASSWORD': 'password'}), patch.object(web, '_payload_from_query') as build:
            self.assertEqual(get(f'/orders/export.xlsx?snapshot={token}')[0], 401)
            status, received_headers, body = get(f'/orders/export.xlsx?snapshot={token}', headers)
            self.assertEqual(status, 200)
            self.assertEqual(received_headers['Content-Type'], MIME_TYPE)
            self.assertIn(download.filename, received_headers['Content-Disposition'])
            self.assertEqual(received_headers['Cache-Control'], 'no-store')
            self.assertEqual(body, download.content)
            self.assertEqual(get('/orders/export.xlsx?snapshot=unknown', headers)[0], 410)
            build.assert_not_called()

    def test_download_follows_order_summary_and_details_follow_table(self):
        from tests.synthetic_sales import dashboard_fixture
        with dashboard_fixture(web):
            payload = web.build_dashboard_payload(start_day=date(2026, 8, 4), now=datetime(2026, 8, 2, 12))
        html = web.render_dashboard_html(payload, export_url='/orders/export.xlsx?snapshot=test')
        button = html.index('Скачать Excel: кулинария + ТТ')
        table = html.index('<table class="order-table">')
        end_of_table = html.index('</table>', table)
        self.assertLess(html.index('class="daily-strip"'), button)
        self.assertLess(button, table)
        for label in ('Заказ до <strong>', 'В эту поставку включено питание сотрудников', 'class="alert-row"', 'Как рассчитан заказ'):
            with self.subTest(label=label):
                self.assertLess(end_of_table, html.index(label))
        self.assertIn('download>Скачать Excel', html)
