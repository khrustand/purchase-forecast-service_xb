from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from src.app import web_server as web
from src.domain.menu_catalog import MenuCatalogState
from scripts.analyze_culinary_strategy import DailySalesItem


class ProductionPageTests(TestCase):
    def test_32_supplier_places_are_separate_from_five_tt_items(self):
        tt = ['Каша овсяная 0,250', 'Каша рисовая 0,250', 'Омлет с ветчиной 0,200',
              'Сырники классические 0,140', 'Запеканка 0,200']
        names = [f'Суп {i}' for i in range(34)] + tt
        catalog = [SimpleNamespace(name=name, normalized_name=name.casefold(), group='Супы',
                                   enabled=True, own_production=name in tt) for name in names]
        history = [DailySalesItem('Супы', name, {date(2026, 11, d): 3 for d in range(1, 15)}) for name in names]
        with patch.object(web, 'REPORT_STORAGE') as storage, \
             patch.object(web, 'load_met_norway_forecast', return_value=None), \
             patch.object(web, 'build_menu_catalog', return_value=[]), \
             patch.object(web, 'apply_menu_state', return_value=catalog), \
             patch.object(web, 'load_menu_state', return_value=MenuCatalogState(disabled=set())), \
             patch.object(web, 'load_candidates', return_value=[]), \
             patch.object(web, 'read_xlsx', return_value=[]), \
             patch('src.infrastructure.report_analytics.read_xlsx', return_value=[]), \
             patch.object(web, 'dish_economics', return_value={
                 'start': '2026-11-01', 'end': '2026-11-14', 'rows': [], 'detailed_waste_days': 0}), \
             patch.object(web, 'extract_items', return_value=history):
            storage.paths.side_effect = lambda kind: [Path('sales.xlsx')] if kind == 'sales' else []
            storage.list.return_value = []
            strategy = web.build_culinary_strategy_payload(reference_day=date(2026, 11, 17),
                production_start_day=date(2026, 11, 16), shelf_life_path=Path('__missing__'), waste_path=Path('__missing__'))
        order = strategy['future_orders'][0]
        self.assertEqual(len(order['rows']), 32)
        self.assertEqual(len(strategy['production_days'][0]['rows']), 5)
        self.assertEqual(order['staff_quantity'], 10)
        supplier_staff = sum(row['staff_quantity'] for row in order['rows'])
        tt_staff = sum(row['staff_quantity'] for day in strategy['production_days']
                       if order['start'] <= day['date'] <= order['end'] for row in day['rows'])
        self.assertEqual(supplier_staff + tt_staff, 10)
        self.assertEqual(sum(day['quantity'] for day in order['daily_totals']), order['total_quantity'])
        for day in strategy['production_days']:
            for row in day['rows']:
                self.assertEqual(row['batch_size'], 1)
                self.assertEqual(row['quantity'], row['model']['quantity'])
                self.assertEqual(row['quantity'], row['guest_quantity'] + row['staff_quantity'] + row['batch_extra'])
        for row in order['rows']:
            self.assertEqual(row['forecast_quantity'], row['model']['quantity'])
            self.assertEqual(row['model']['service_level'], .85)
            self.assertEqual(row['display_extra'], 0)

    def test_only_enabled_own_items_including_items_without_sales(self):
        menu = [SimpleNamespace(normalized_name=name, name=name, group='Салаты', enabled=True, own_production=False)
                for name in ('own', 'disabled', 'supplier', 'new')]
        # apply_menu_state работает с dataclass; подменяем только чтение результата меню.
        catalog = [SimpleNamespace(normalized_name=name, name=name, group='Салаты',
                                   enabled=name != 'disabled', own_production=name != 'supplier')
                   for name in ('own', 'disabled', 'supplier', 'new')]
        history = [DailySalesItem('Салаты', 'own', {date(2026, 11, 5): 10})]
        with patch.object(web, 'REPORT_STORAGE') as storage, \
             patch.object(web, 'load_met_norway_forecast', return_value=None), \
             patch.object(web, 'build_menu_catalog', return_value=menu), \
             patch.object(web, 'apply_menu_state', return_value=catalog), \
             patch.object(web, 'load_menu_state', return_value=MenuCatalogState(disabled={'disabled'})), \
             patch.object(web, 'read_xlsx', return_value=[]), \
             patch('src.infrastructure.report_analytics.read_xlsx', return_value=[]), \
             patch.object(web, 'dish_economics', return_value={
                 'start': '2026-11-01', 'end': '2026-11-05', 'rows': [], 'detailed_waste_days': 0}), \
             patch.object(web, 'extract_items', return_value=history):
            storage.paths.side_effect = lambda kind: [Path('sales.xlsx')] if kind == 'sales' else []
            storage.list.return_value = []
            strategy = web.build_culinary_strategy_payload(waste_path=Path('__missing__'),
                shelf_life_path=Path('__missing__'), reference_day=date(2026, 11, 11))
        rows = strategy['production_days'][0]['rows']
        self.assertEqual([row['name'] for row in rows], ['own', 'new'])
        self.assertIsNone(rows[1]['quantity'])
        html = web.render_production_workspace(strategy)
        self.assertIn('нет данных', html)
        self.assertIn('2026-11-12', html)

    def test_weather_factor_affects_quantity_and_missing_weather_is_neutral(self):
        day = date(2026, 11, 14)
        with patch.dict(web.WEATHER_BY_DATE, {}, clear=True):
            self.assertEqual(web._weather_factor('Завтраки', [day]), 1)
            web.WEATHER_BY_DATE[day] = {'rain': True, 'temperature': 10, 'summary': 'дождь'}
            source = SimpleNamespace(by_date={date(2026, 11, 7): 100})
            rainy = web._weekday_daily_forecast(source, 'Супы', [day], .8)
            self.assertEqual(rainy[0]['quantity'], 86)
            web.WEATHER_BY_DATE[day] = {'rain': False, 'temperature': 10, 'summary': 'ясно'}
            dry = web._weekday_daily_forecast(source, 'Супы', [day], .8)
            self.assertEqual(dry[0]['quantity'], 100)

    def test_production_route_and_navigation(self):
        payload = {'culinary_strategy': None}
        handler = object.__new__(web.DashboardHandler)
        handler.path = '/production'
        handler._authorize = lambda: True
        from unittest.mock import Mock
        handler._send_html = Mock()
        with patch.object(web, '_payload_from_query', return_value=payload), \
             patch.object(web, 'render_dashboard_html', return_value='Кулинария ТТ') as render:
            handler.do_GET()
        render.assert_called_once_with(payload, view='production')
        with patch.object(web, 'DEFAULT_PREVIOUS_ORDERS_DIR', Path('__missing__')):
            html = web.render_dashboard_html(web.build_dashboard_payload(start_day=date(2026, 8, 4)), view='production')
        nav = html.split('<nav>')[1].split('</nav>')[0]
        self.assertLess(nav.index('Заказы'), nav.index('Кулинария ТТ'))
        self.assertLess(nav.index('Кулинария ТТ'), nav.index('Аналитика'))

    def test_old_live_forecast_is_removed_when_provider_is_unavailable(self):
        day = date(2026, 11, 14)
        with patch.dict(web.WEATHER_BY_DATE, {day: {'source': 'MET Norway', 'rain': True}}, clear=True), \
             patch.object(web, 'load_met_norway_forecast', return_value=None), \
             patch.object(web, 'REPORT_STORAGE') as storage:
            storage.paths.return_value = []
            web.build_culinary_strategy_payload(sales_path=Path('__missing__'))
            self.assertNotIn(day, web.WEATHER_BY_DATE)
