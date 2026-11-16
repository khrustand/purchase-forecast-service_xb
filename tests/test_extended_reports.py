from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from src.infrastructure.report_formats import receipt_days, waste_lines
from src.infrastructure.report_storage import MonthlyReportStorage, SupabaseReportStorage, ReportValidationError, detect_period
from src.infrastructure.report_analytics import dish_economics, load_checks
from src.domain.traffic import allocate_staff, traffic_adjustment


def waste_rows(number='101', account='Списание кулинарии'):
    return [[f'Акт списания №{number} от 01.11.2026'], [], [], [],
            ['Дата и время: 01.11.2026 23:00'], [], [f'На счет: {account}'], [],
            ['№', 'Код товара', 'Товар', 'Размер', 'Тип тары', 'Количество тары',
             'Количество, в ед. изм.', 'Коэффициент списания', None, 'Себестоимость ед., р.', 'Себестоимость всего, р.'],
            ['1', '123456789', 'Суп тестовый', None, 'порц', '2', '2', '1', None, '20', '40'],
            [None, None, 'Итого', None, None, None, '2', None, None, None, '40']]


class ExtendedReportTests(TestCase):
    def test_trial_quantity_is_three_including_friday_window(self):
        from src.app import web_server as web
        trial = {'name':'Онигири новый', 'category':'Роллы', 'order_for_2_days':3,
                 'shelf_life_days':2, 'is_experiment':True}
        result=web._future_period(date(2026,11,20),3,[trial],[],{},.88)
        self.assertEqual(result['rows'][0]['forecast_quantity'],3)
        self.assertEqual(result['rows'][0]['daily_forecast'][2]['quantity'],0)

    def test_receipt_formats_skip_totals_and_reject_wrong_type(self):
        rows = [['Период', 'Чеков', 'Гостей', 'Продажи'],
                ['01.11.2026, воскресенье', '100', '100', '2000'], [None, '100', '100', '2000']]
        for prefix in ([], [['Отчет'], ['За период: с 01.11.2026 по 01.11.2026'], [], [], []]):
            self.assertEqual(receipt_days(prefix + rows)[0].checks, 100)
            with patch('src.infrastructure.report_storage.read_xlsx', return_value=prefix + rows):
                self.assertEqual(detect_period(Path('x'), 'receipts'), (date(2026,11,1),) * 2)
                with self.assertRaisesRegex(ValueError, 'Чеки'):
                    detect_period(Path('x'), 'sales')

    def test_waste_units_document_date_and_staff(self):
        line = waste_lines(waste_rows())[0]
        self.assertEqual((line.quantity, line.cost), (Decimal(2), Decimal(40)))
        self.assertEqual(line.day, date(2026,11,1))
        self.assertFalse(line.staff)
        self.assertTrue(waste_lines(waste_rows(account='Бесплатная еда сотрудников'))[0].staff)

    def test_same_day_different_documents_allowed_duplicate_export_rejected(self):
        with TemporaryDirectory() as directory:
            storage = MonthlyReportStorage(Path(directory))
            for number in ('101', '102'):
                with patch('src.infrastructure.report_storage.read_xlsx', return_value=waste_rows(number)):
                    storage.save('waste', f'{number}.xlsx', b'PKtest')
            with patch('src.infrastructure.report_storage.read_xlsx', return_value=waste_rows('101')):
                with self.assertRaises(ReportValidationError):
                    storage.save('waste', 'другой экспорт.xlsx', b'PKtest')
            self.assertEqual(len(storage.list()), 2)

    def test_supplements_are_visible_without_writing_cloud_metadata(self):
        with TemporaryDirectory() as directory:
            from unittest.mock import Mock
            request = Mock(return_value=(200, b'[]'))
            storage = SupabaseReportStorage('https://example.test', 'secret', request=request,
                                            supplements=MonthlyReportStorage(Path(directory)))
            with patch('src.infrastructure.report_storage.read_xlsx', return_value=waste_rows()):
                saved = storage.save('waste', 'act.xlsx', b'PKtest')
            self.assertIsNotNone(storage.resolve(saved.id))
            self.assertEqual(storage.list()[0].storage_path, 'local-supplement')
            self.assertTrue(all(call.args[0] == 'GET' for call in request.call_args_list))

    def test_profit_deducts_known_losses_and_staff_but_not_sold_cost_twice(self):
        sales = [['Отчет'], ['За период: с 01.11.2026 по 01.11.2026'], [],
                 ['Категория', 'Элемент номенклатуры', '', '', 'Количество'],
                 ['Кулинария производство', 'Суп тестовый', '', '', '10', '', '400', None, '200']]
        paths = {'sales': sales, 'waste': waste_rows(), 'staff': waste_rows('102', 'Питание персонала')}
        with patch('src.infrastructure.report_analytics.read_xlsx', side_effect=lambda p: paths[str(p)]):
            result = dish_economics([Path('sales')], [Path('waste'),Path('waste'),Path('staff')], date(2026,11,1), date(2026,11,15))
        row = result['rows'][0]
        self.assertEqual(row['waste_quantity'], 2)
        self.assertEqual(row['staff_quantity'], 2)
        self.assertEqual(row['profit_after_known_costs'], 120)
        self.assertEqual(row['margin_after_known_costs'], 30)

    def test_staff_total_is_five_across_all_dishes(self):
        result = allocate_staff({'каша': 10, 'суп': 30, 'ролл': 10}, 5)
        self.assertEqual(sum(result.values()), 5)
        self.assertEqual(result['каша'], 1)
        self.assertEqual(result['суп'], 3)

    def test_staff_rounding_does_not_exclude_lower_demand_dishes_forever(self):
        balance = {}
        total = {'каша': 0, 'суп': 0, 'ролл': 0}
        for _ in range(10):
            allocation = allocate_staff({'каша': 1, 'суп': 18, 'ролл': 1}, 5, balance)
            self.assertEqual(sum(allocation.values()), 5)
            for key,q in allocation.items():
                total[key] += q
        self.assertGreater(total['каша'], 0)
        self.assertGreater(total['ролл'], 0)
        self.assertEqual(sum(total.values()), 50)

    def test_friday_two_day_item_has_no_sunday_demand(self):
        from src.app import web_server as web
        from scripts.analyze_culinary_strategy import DailySalesItem, build_daily_menu, build_recommendations
        history = {date(2026,10,d): 10 for d in range(1,29)}
        source = DailySalesItem('Завтраки', 'Блины', history)
        menu = build_daily_menu(build_recommendations([source], 2, {}, {'блины': {'days': 2, 'source': 'test'}}))
        result = web._future_period(date(2026,11,20), 3, menu, [source], {}, .88)
        self.assertGreater(result['rows'][0]['daily_forecast'][0]['quantity'], 0)
        self.assertEqual(result['rows'][0]['daily_forecast'][2]['quantity'], 0)

    def test_checks_exclude_future_data_and_compare_same_weekday(self):
        checks = {date(2026,10,5): 100, date(2026,10,12): 100,
                  date(2026,11,2): 80,date(2026,11,9): 80,date(2026,11,23): 10000}
        result = traffic_adjustment(checks, [date(2026,10,5),date(2026,10,12)], date(2026,11,16), date(2026,11,16))
        self.assertEqual(result['expected_checks'], 90)
        self.assertEqual(result['factor'], .9)

    def test_overlapping_receipts_are_not_summed(self):
        rows = [['Период','Чеков','Продажи'],['01.11.2026','100','2000']]
        with patch('src.infrastructure.report_analytics.read_xlsx', return_value=rows):
            checks, conflicts = load_checks([Path('a'),Path('b')])
        self.assertEqual(checks, {date(2026,11,1): 100})
        self.assertEqual(conflicts, 0)
