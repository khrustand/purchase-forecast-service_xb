from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest import TestCase

from src.domain.order_policy import earliest_delivery, delivery_deadline, round_production, MOSCOW
from src.domain.assortment import propose_matrix
from src.domain.traffic import traffic_adjustment
from src.infrastructure.report_analytics import monthly_loss_kpi, product_key, traffic_history
from src.infrastructure.report_formats import ReceiptDay


class OrderPolicyTests(TestCase):
    def test_shared_loss_budget_and_target_group_mapping(self):
        from src.domain.loss_budget import allocate_loss_budget, loss_group
        budget = allocate_loss_budget(100000, {'culinary': 10000, 'snacks': 10000,
            'bakery': 20000, 'desserts': 5000, 'bread': 5000})
        self.assertEqual(budget['total_budget'], 2000)
        self.assertEqual(budget['rows'][0]['target_cost'], 400)
        self.assertEqual(budget['rows'][0]['target_on_group_revenue_percent'], 4)
        self.assertEqual(sum(row['target_cost'] for row in budget['rows']), 2000)
        self.assertEqual(loss_group('Кулинария. Готовка на ТТ'), 'culinary')
        self.assertEqual(loss_group('Распродажа хлеб'), 'bread')
        self.assertEqual(loss_group('Торт целый'), 'desserts')
        self.assertIsNone(loss_group('Кофе'))

    def test_moscow_cutoff_and_delivery_weekdays(self):
        self.assertEqual(earliest_delivery(datetime(2026, 11, 16, 17, 59, tzinfo=MOSCOW)), date(2026, 11, 18))
        self.assertEqual(earliest_delivery(datetime(2026, 11, 16, 18, tzinfo=MOSCOW)), date(2026, 11, 20))
        self.assertEqual(earliest_delivery(datetime(2026, 11, 16, 15, tzinfo=timezone.utc)), date(2026, 11, 20))
        self.assertEqual(earliest_delivery(datetime(2026, 11, 20, 12, tzinfo=MOSCOW)), date(2026, 11, 23))
        self.assertEqual(delivery_deadline(date(2026, 11, 23)), datetime(2026, 11, 21, 18, tzinfo=MOSCOW))

    def test_selected_date_cannot_reopen_closed_order(self):
        now = datetime(2026, 11, 16, 18, tzinfo=MOSCOW)
        self.assertEqual(earliest_delivery(now, date(2026, 11, 16)), date(2026, 11, 20))
        self.assertEqual(earliest_delivery(now, date(2026, 11, 24)), date(2026, 11, 25))

    def test_production_rounding_exposes_extra_without_inventing_demand(self):
        for name,need,quantity,batch in [('Каша овсяная', 6, 10, 5), ('Каша рисовая', 5, 5, 5),
                                       ('Омлет с ветчиной', 5, 8, 4), ('Запеканка', 5, 8, 8),
                                       ('Сырники классические', 6, 6, 1)]:
            result = round_production(name, need)
            self.assertEqual(result, {'quantity': quantity, 'batch_size': batch, 'batch_extra': quantity - need})
        self.assertEqual(round_production('Запеканка', 0)['quantity'], 0)
        self.assertIsNone(round_production('Запеканка', None)['quantity'])

    def test_year_ahead_traffic_uses_weekday_pairs_and_ignores_future_actuals(self):
        target = date(2026, 11, 16)
        recent = [target - timedelta(weeks=week) for week in range(1, 5)]
        checks = {d: 80 for d in recent}
        checks.update({d - timedelta(days=364): 100 for d in recent})
        checks[target - timedelta(days=364)] = 200
        checks[target] = 99999
        result = traffic_adjustment(checks, recent, target, target)
        self.assertEqual(result['yoy_scale'], .8)
        self.assertEqual(result['seasonal_expected_checks'], 160)
        self.assertEqual(result['expected_checks'], 120)
        self.assertEqual(result['factor'], 1.3)
        self.assertTrue(result['seasonality_applied'])

    def test_matrix_reserves_test_places_and_excludes_losses_zero_cost_and_retired(self):
        candidates = [{'key': str(i), 'name': f'Блюдо {i}', 'sku': str(i), 'active': True} for i in range(36)]
        candidates += [{'key': 'retired', 'name': 'Снято', 'active': False}]
        rows = [{'key': str(i), 'name': f'Блюдо {i}', 'sold': 10, 'revenue': 100,
                 'gross_profit': 60, 'profit_after_known_costs': 50 - i} for i in range(33)]
        rows[31]['profit_after_known_costs'] = -1
        rows[32]['gross_profit'] = 100
        rows.append({'key': 'retired', 'name': 'Снято', 'sold': 1000,
                     'revenue': 10000, 'gross_profit': 5000, 'profit_after_known_costs': 5000})
        result = propose_matrix(candidates, rows)
        self.assertEqual(len(result['rows']), 32)
        self.assertEqual([result[k] for k in ('core_count', 'rotation_count', 'experiment_count')], [22, 7, 3])
        self.assertTrue({'retired', '31', '32'}.isdisjoint({r['key'] for r in result['rows']}))
        self.assertTrue(all(r['profit_after_known_costs'] is None for r in result['rows'] if r['role'] == 'experiment'))

    def test_loss_kpi_uses_all_bakery_revenue_and_excludes_staff_cost(self):
        economics = {'start': '2026-11-01', 'end': '2026-11-15', 'detailed_waste_days': 11,
                     'rows': [{'waste_cost': 40, 'staff_cost': 100, 'revenue': 200}]}
        receipts = {date(2026, 11, 1): ReceiptDay(date(2026, 11, 1), 10, Decimal(2000))}
        result = monthly_loss_kpi(economics, receipts)
        self.assertEqual(result['known_percent'], 2)
        self.assertEqual(result['total_revenue'], 2000)
        self.assertFalse(result['complete'])

    def test_month_comparison_uses_only_dates_available_in_both_years(self):
        data = {}
        for day,q in [(date(2025, 11, 1), 100), (date(2025, 11, 2), 900), (date(2026, 11, 1), 80)]:
            data[day] = ReceiptDay(day, q, Decimal(q * 100))
        result = traffic_history(data, date(2026, 11, 15))
        self.assertEqual(result['months'][0]['last_year_checks'], 100)
        self.assertEqual(result['months'][0]['change_percent'], -20)
        self.assertEqual(len(result['previous_daily']), 2)

    def test_names_match_between_menu_sales_and_acts(self):
        self.assertEqual(product_key('Венская котлета с запеченным картофелем'),
                         product_key('Венская котлета с запеч. картофелем'))
        self.assertEqual(product_key('Шницель с картоф. пюре 0,230г*'),
                         product_key('Шницель с карт. пюре 0,230'))

    def test_reconciliation_recognizes_tt_and_excludes_snacks(self):
        from types import SimpleNamespace
        from src.app.web_server import build_menu_coverage
        sales = [SimpleNamespace(category=group, name=name, by_date={date(2026, 11, 1): q})
                 for group,name,q in [('Кулинария. Готовка на ТТ', '*Каша рисовая 0,250', 5),
                                      ('Снэки', 'Тортилья', 100), ('Супы', 'Суп', 3)]]
        result = build_menu_coverage(sales, [])
        self.assertEqual(result['own_production']['quantity'], 5)
        self.assertEqual(result['outside_menu']['quantity'], 3)
