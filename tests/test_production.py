from datetime import date
from unittest import TestCase

from src.domain.production import daily_production_plan


class ProductionTests(TestCase):
    def test_weekday_weather_and_missing_history(self):
        start = date(2026, 11, 12)
        items = [{'key': 'soup', 'name': 'Суп', 'category': 'Супы'},
                 {'key': 'new', 'name': 'Новинка', 'category': 'Салаты'}]
        history = {'soup': {date(2026, 11, 5): 10, date(2026, 11, 6): 4,
                            date(2026, 11, 13): 1000}}
        plan = daily_production_plan(items, start, 3, history, {('soup', start): .8})
        self.assertEqual([d['rows'][0]['quantity'] for d in plan], [8, 4, 7])
        self.assertEqual(plan[0]['rows'][0]['basis'], 'день недели')
        self.assertEqual(plan[2]['rows'][0]['basis'], 'среднее за историю')
        self.assertIsNone(plan[0]['rows'][1]['quantity'])
        self.assertEqual(plan[0]['missing_history'], 1)
        self.assertEqual(plan[0]['total'], 8)

    def test_observed_zero_is_not_missing(self):
        plan = daily_production_plan([{'key': 'a'}], date(2026, 11, 12), 1,
                                     {'a': {date(2026, 11, 5): 0}}, {})
        self.assertEqual(plan[0]['rows'][0]['quantity'], 0)
        self.assertEqual(plan[0]['missing_history'], 0)
