from datetime import date, timedelta
from unittest import TestCase

from src.app.category_orders import check_category_reserves


class CategoryOrderTests(TestCase):
    def test_excess_only_reduces_reserve_when_comparable_windows_exist(self):
        start = date(2026, 11, 23)
        dates = [start, start + timedelta(days=1)]
        observed = {day - timedelta(weeks=w): 2 for day in dates for w in (1, 2, 3)}
        rows = [
            {'name': 'Щи', 'category': 'Супы', 'shelf_life_days': 3, 'staff_quantity': 1,
             'model': {'guest_quantity': 8, 'economic_quantity': 6, 'expected_remaining_cost': 50}},
            {'name': 'Борщ', 'category': 'Супы', 'shelf_life_days': 3, 'staff_quantity': 0,
             'model': {'guest_quantity': 4, 'economic_quantity': 4, 'expected_remaining_cost': 0}},
            {'name': 'Новый суп', 'category': 'Супы', 'shelf_life_days': 3, 'staff_quantity': 0,
             'model': {'guest_quantity': 3, 'economic_quantity': None, 'expected_remaining_cost': None}},
        ]
        calls = []

        def replan(row, limit):
            calls.append((row['name'], limit))
            row['model']['guest_quantity'] = limit

        args = (dates, start, .85, lambda category, days, history: [1, 1], replan)
        sparse = check_category_reserves(rows, {'щи': {next(iter(observed)): 2}}, *args)
        self.assertIsNone(sparse[0]['reference'])
        self.assertEqual(calls, [])
        results = check_category_reserves(rows, {'щи': observed, 'борщ': observed}, *args)
        self.assertEqual(calls, [('Щи', 6)])
        self.assertEqual((results[0]['reference'], results[0]['guest_after'], results[0]['staff']), (8, 13, 1))
