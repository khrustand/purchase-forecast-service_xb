from datetime import date
from unittest import TestCase

from scripts.analyze_culinary_strategy import extract_items


class SalesImportTests(TestCase):
    def test_ignores_missing_cells_but_keeps_explicit_zero(self) -> None:
        rows = [[] for _ in range(5)]
        rows.append([None, None, "46235", "46236", "46237"])
        rows.append(["Салаты", "Тестовый салат", 5, None, 0])

        item = extract_items(rows, date(2026, 8, 1), date(2026, 8, 3))[0]

        self.assertEqual(item.by_date, {date(2026, 8, 1): 5.0, date(2026, 8, 3): 0.0})
        self.assertEqual(item.average_per_day, 2.5)
