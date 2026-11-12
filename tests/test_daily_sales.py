from datetime import date
from unittest import TestCase
from unittest.mock import patch
from pathlib import Path

from scripts.analyze_culinary_strategy import daily_sales_period, extract_items
from src.infrastructure.report_storage import detect_period


class DailySalesTests(TestCase):
    def rows(self):
        return [
            ['Отчет о продажах'],
            ['За период: с 01.09.2026 по 01.09.2026'],
            [],
            ['Категория', 'Элемент номенклатуры', 'Цена', 'Цена', 'Количество'],
            ['Супы', 'Борщ', '200', '190', '2'],
            ['Супы', 'Щи', '200', '0', '1'],
            [None, 'Итого:', None, None, '3'],
            ['Супы', 'Нет продаж', None, None, '0'],
        ]

    def test_quantity_includes_free_products_and_excludes_total(self):
        day = date(2026, 9, 1)
        items = extract_items(self.rows(), day, day)
        self.assertEqual([(i.name, i.total) for i in items], [('Борщ', 2), ('Щи', 1)])
        self.assertEqual(extract_items(self.rows(), date(2026, 9, 2), date(2026, 9, 3)), [])

    def test_storage_detects_daily_period(self):
        with patch('src.infrastructure.report_storage.read_xlsx', return_value=self.rows()):
            self.assertEqual(detect_period(Path('daily.xlsx'), 'sales'), (date(2026, 9, 1),) * 2)

    def test_rejects_multiple_days_without_daily_breakdown(self):
        rows = self.rows()
        rows[1] = ['За период: с 01.09.2026 по 30.09.2026']
        with self.assertRaises(ValueError):
            daily_sales_period(rows)
