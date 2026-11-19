from datetime import date, datetime, timedelta
from http.client import HTTPConnection
from pathlib import Path
import re
import threading
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from scripts.analyze_culinary_strategy import DailySalesItem
from src.app import web_server as web
from src.app.order_finance import order_financials, finance_cells


class OrderFinanceTests(TestCase):
    def test_retail_value_and_expected_margin_do_not_count_staff_as_sales(self):
        item = {'forecast_quantity': 10, 'model': {'price': 200, 'cost': 80,
                'expected_guest_sales': 7, 'expected_profit': 600}}
        values = order_financials(item)
        self.assertEqual(values['retail_value'], 2000)
        self.assertEqual(values['unit_margin'], 120)
        self.assertEqual(values['unit_margin_percent'], 60)
        self.assertEqual(values['expected_revenue'], 1400)
        self.assertEqual(values['expected_margin'], 600)  # 200*7 - 80*10, staff included in cost.
        self.assertAlmostEqual(values['expected_margin_percent'], 600 / 1400 * 100)

    def test_missing_economics_are_not_zero_or_invented(self):
        cells = finance_cells({'forecast_quantity': 3, 'is_experiment': True, 'model': {}})
        self.assertEqual(cells.count('нет данных'), 4)
        self.assertNotIn('0.00', cells)
        item = {'forecast_quantity': 0, 'quantity_unknown': True, 'model': {'price': 200, 'cost': 80}}
        self.assertIsNone(order_financials(item)['retail_value'])


class ConsistentCalendarPlanTests(TestCase):
    def test_tt_and_staff_are_independent_of_the_opened_date(self):
        from tests.synthetic_sales import dashboard_fixture
        from src.domain.menu_catalog import MenuCatalogState
        names = ['Суп 1', 'Суп 2', 'Каша овсяная 0,250', 'Каша рисовая 0,250',
                 'Омлет с ветчиной 0,200', 'Сырники классические 0,140', 'Запеканка 0,200']
        catalog = [SimpleNamespace(name=name, normalized_name=name.casefold(), group='Супы',
                   enabled=True, own_production=index>=2) for index,name in enumerate(names)]
        history = [DailySalesItem('Супы', name,
                   {date(2026,9,1)+timedelta(days=d): 1+(d*3+index)%9 for d in range(76)})
                   for index,name in enumerate(names)]
        clock = datetime(2026,11,18,19)
        with dashboard_fixture(web), patch.object(web, 'apply_menu_state', return_value=catalog), \
             patch.object(web, 'load_menu_state', return_value=MenuCatalogState(disabled=set())), \
             patch.object(web, 'extract_items', return_value=history):
            base = web.build_dashboard_payload(now=clock)['culinary_strategy']
            for selected in (date(2026,11,23), date(2026,11,25)):
                strategy = web.build_dashboard_payload(start_day=selected,now=clock)['culinary_strategy']
                same = {d['date']:d for d in base['production_days']}
                for day in strategy['production_days']:
                    if day['date'] in same:
                        expected = same[day['date']]
                        self.assertEqual(day['total'], expected['total'])
                        self.assertEqual([(r['name'],r['quantity'],r['staff_quantity']) for r in day['rows']],
                                         [(r['name'],r['quantity'],r['staff_quantity']) for r in expected['rows']])
                current = strategy['future_orders'][0]
                in_period = [d for d in strategy['production_days'] if current['start']<=d['date']<=current['end']]
                self.assertEqual(sum(d['total'] for d in in_period),current['production_quantity'])
                self.assertGreater(current['production_quantity'], 0)
                html = web.render_orders_workspace(strategy)
                cards = re.findall(r"class='daily-card'.*?<strong>(\d+) шт\.</strong>", html)
                expected_daily = [
                    sum(entry['quantity'] for row in current['rows'] for entry in row['daily_forecast']
                        if entry['date'] == day['date'])
                    for day in current['daily_totals']
                ]
                self.assertEqual(list(map(int, cards)), expected_daily)
                self.assertIn(f"<span>Заказать</span><strong>{sum(expected_daily)}</strong>", html)
                supplier_staff = sum(row['staff_quantity'] for row in current['rows'])
                self.assertIn(f"В эту поставку включено питание сотрудников: {supplier_staff} порций.", html)
                self.assertEqual(current['staff_quantity'],current['days']*5)
                self.assertEqual(sum(r['staff_quantity'] for r in current['rows'])+
                                 sum(r['staff_quantity'] for d in in_period for r in d['rows']),current['days']*5)
                self.assertEqual(strategy['forecast_as_of'],'2026-11-19')
                from io import BytesIO
                from zipfile import ZipFile
                from xml.etree import ElementTree as ET
                from src.app.order_exports import prepare_order_download
                from src.infrastructure.order_workbook import NS
                with ZipFile(BytesIO(prepare_order_download(strategy).content)) as archive:
                    sheet=ET.fromstring(archive.read('xl/worksheets/sheet2.xml'))
                footer=sheet.find(f'{{{NS}}}sheetData').findall(f'{{{NS}}}row')[-1]
                total_column=chr(64+current['days']+4)
                total=next(cell for cell in footer if cell.attrib['r'].startswith(total_column))
                self.assertEqual(int(total.findtext(f'{{{NS}}}v')),current['production_quantity'])

    def test_requested_date_cannot_leak_future_actual_sales(self):
        from tests.synthetic_sales import dashboard_fixture
        clock = datetime(2026,8,2,12)
        with dashboard_fixture(web):
            strategy = web.build_dashboard_payload(start_day=date(2026,8,19),now=clock)['culinary_strategy']
        self.assertEqual(strategy['forecast_as_of'],'2026-08-02')


class OrderPageReviewTests(TestCase):
    def test_order_layout_finance_weather_and_selected_tt_link(self):
        from tests.synthetic_sales import dashboard_fixture
        with dashboard_fixture(web):
            payload=web.build_dashboard_payload(start_day=date(2026,11,23),now=datetime(2026,11,18,12))
        html=web.render_dashboard_html(payload)
        self.assertNotIn('Следующие заказы',html)
        self.assertNotIn('<th>Тип</th>',html)
        self.assertIn('Цена продажи<br>порции, ₽',html)
        self.assertIn('Маржа плана',html)
        self.assertIn('href="/production?start=2026-11-23&amp;service=',html)
        self.assertGreater(html.index('Как учитывается погода'),html.index('class="order-table"'))
        self.assertGreater(html.index('Как учитывается погода'),html.index('Питание сотрудников и динамика спроса'))
        self.assertIn('<script src="/assets/orders.js" defer>',html)
        self.assertNotIn('<script>',html)

    def test_same_origin_details_script_is_served(self):
        server=web.DashboardServer(('127.0.0.1',0),web.DashboardHandler)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            with patch.dict('os.environ',{'APP_USERNAME':'','APP_PASSWORD':''}):
                connection=HTTPConnection('127.0.0.1',server.server_port,timeout=5)
                connection.request('GET','/assets/orders.js')
                response=connection.getresponse()
                body=response.read().decode('utf-8')
                connection.close()
            self.assertEqual(response.status,200)
            self.assertIn('application/javascript',response.getheader('Content-Type'))
            self.assertIn('dialog.showModal()',body)
            self.assertIn('cloneNode(true)',body)
        finally:
            server.shutdown();thread.join(5);server.server_close()
