from datetime import date
from types import SimpleNamespace
from unittest import TestCase

from src.app.web_server import align_sales_with_menu
from scripts.analyze_culinary_strategy import DailySalesItem, build_recommendations, build_daily_menu


class SalesMenuAlignmentTests(TestCase):
    def test_daily_reports_with_general_category_produce_nonempty_plan(self):
        day = date(2026, 9, 1)
        history = {date(2026, 9, offset): 10 for offset in range(1, 11)}
        sales = [DailySalesItem('Кулинария производство', 'Суп лапша', history),
                 DailySalesItem('Кулинария производство', 'Ролл с курицей', history)]
        catalog = [SimpleNamespace(normalized_name='суп лапша', name='Суп лапша', group='Супы'),
                   SimpleNamespace(normalized_name='ролл с курицей', name='Ролл с курицей', group='Роллы')]
        aligned = align_sales_with_menu(sales, catalog)
        menu = build_daily_menu(build_recommendations(aligned, 2, {}))
        self.assertEqual({r['category'] for r in menu}, {'Супы', 'Роллы'})
        self.assertGreater(sum(r['order_for_2_days'] for r in menu), 0)
        self.assertEqual(sales[0].category, 'Кулинария производство')

    def test_matching_names_are_merged_without_losing_daily_quantity(self):
        day = date(2026, 9, 1)
        sales = [DailySalesItem('Кулинария производство', 'СУП ЛАПША', {day: 3}),
                 DailySalesItem('Другая категория', 'Суп лапша', {day: 2})]
        catalog = [SimpleNamespace(normalized_name='суп лапша', name='Суп лапша', group='Супы')]
        aligned = align_sales_with_menu(sales, catalog)
        self.assertEqual(len(aligned), 1)
        self.assertEqual(aligned[0].by_date, {day: 5})
