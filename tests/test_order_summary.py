from copy import deepcopy
from datetime import date, datetime
from unittest import TestCase

from src.app.order_finance import assortment_status, status_explanation, order_totals, render_order_totals
from src.app import web_server as web


def lines():
    return [
        {'forecast_quantity':5,'matrix_role':'core','daily_forecast':[{'date':'2026-11-23','quantity':2},{'date':'2026-11-24','quantity':3}],
         'model':{'price':150,'cost':50,'expected_guest_sales':4,'expected_profit':350}},
        {'forecast_quantity':3,'is_experiment':True,'matrix_role':'experiment',
         'daily_forecast':[{'date':'2026-11-23','quantity':1},{'date':'2026-11-24','quantity':2}], 'model':{}},
    ]


class OrderSummaryTests(TestCase):
    def test_partial_money_and_complete_quantities(self):
        rows=lines()
        result=order_totals(rows,['2026-11-23','2026-11-24'])
        self.assertEqual([d['value'] for d in result['daily']],[3,5])
        self.assertEqual(result['quantity'],{'value':8,'known':2,'missing':0})
        self.assertEqual(result['retail_value'],{'value':750,'known':1,'missing':1})
        self.assertEqual(result['expected_margin'],{'value':350,'known':1,'missing':1})
        html=render_order_totals(result)
        self.assertIn('неполный итог: без 1 поз.',html)
        self.assertEqual(html.count('<td>—</td>'),2)  # No sum of prices or unit margins/percentages.

    def test_unknown_quantity_is_not_a_known_zero(self):
        rows=lines()
        rows[1].update(quantity_unknown=True,forecast_quantity=0)
        result=order_totals(rows,['2026-11-23','2026-11-24'])
        self.assertEqual(result['quantity']['value'],5)
        self.assertEqual(result['quantity']['missing'],1)
        self.assertEqual([d['missing'] for d in result['daily']],[1,1])
        self.assertEqual(result['retail_value']['missing'],1)
        rows[1]['quantity_unknown']=False
        for day in rows[1]['daily_forecast']:day['quantity']=0
        result=order_totals(rows,['2026-11-23','2026-11-24'])
        self.assertEqual(result['retail_value']['missing'],0)  # Zero volume contributes zero, no invented price.

    def test_missing_prices_are_not_a_complete_zero_sum(self):
        rows=lines()[1:]
        result=order_totals(rows,['2026-11-23'])
        self.assertIsNone(result['retail_value']['value'])
        self.assertEqual(result['retail_value']['missing'],1)
        self.assertIn('нет данных',render_order_totals(result))

    def test_roles_are_menu_roles_not_claims_about_stability(self):
        row={'matrix_role':'core','stability':'неровный спрос','forecast_quantity':8}
        before=deepcopy(row)
        self.assertEqual(assortment_status(row),('Основное меню','core'))
        self.assertEqual(row,before)
        self.assertIn('не доказывает',status_explanation(row))
        self.assertEqual(assortment_status({'matrix_role':'rotation'}),('Ротация','rotation'))
        self.assertEqual(assortment_status({'matrix_role':'experiment'}),('Тест','trial'))
        self.assertEqual(assortment_status({}),('В работе','unknown'))

    def test_three_day_summary_and_empty_order(self):
        rows=lines()
        for row,q in zip(rows,[4,0]):
            row['daily_forecast'].append({'date':'2026-11-25','quantity':q})
            row['forecast_quantity']+=q
        totals=order_totals(rows,['2026-11-23','2026-11-24','2026-11-25'])
        self.assertEqual([d['value'] for d in totals['daily']],[3,5,4])
        self.assertEqual(totals['quantity']['value'],12)
        self.assertEqual(order_totals([],[])['quantity']['value'],0)

    def test_order_day_cells_are_only_quantities(self):
        from tests.synthetic_sales import dashboard_fixture
        with dashboard_fixture(web):
            payload=web.build_dashboard_payload(start_day=date(2026,11,23),now=datetime(2026,11,18,12))
        item=payload['culinary_strategy']['future_orders'][0]['rows'][0]
        html=web._render_operational_row(item).split('<template>')[0]
        self.assertNotIn('гостям с резервом',html)
        self.assertNotIn('питание',html)
        self.assertNotIn('чеки',html)
        page=web.render_dashboard_html(payload)
        self.assertIn('<tfoot>',page)
        self.assertIn('Итого к поставке',page)
        self.assertNotIn('<th>История списаний</th>',page)
        self.assertIn('<th>Статус</th>',page)
