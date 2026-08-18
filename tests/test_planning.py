from datetime import date
from unittest import TestCase

from src.domain.planning import (
    ExpenseRecord,
    PurchaseItem,
    build_purchase_calendar,
    estimate_calendar_budget,
    summarize_expenses,
)


class PurchasePlanningTests(TestCase):
    def test_builds_calendar_by_package_usage_and_shelf_life(self) -> None:
        items = [
            PurchaseItem(
                name="chicken lunch",
                category="lunches",
                daily_usage=35,
                unit="pcs",
                package_quantity=70,
                shelf_life_days=2,
                estimated_price=9800,
            ),
            PurchaseItem(
                name="caesar salad",
                category="salads",
                daily_usage=18,
                unit="pcs",
                package_quantity=36,
                shelf_life_days=2,
                estimated_price=5400,
            ),
        ]

        events = build_purchase_calendar(items, date(2026, 6, 18), 6)

        self.assertEqual(
            [(event.item_name, event.day.isoformat()) for event in events],
            [
                ("chicken lunch", "2026-06-18"),
                ("caesar salad", "2026-06-18"),
                ("chicken lunch", "2026-06-20"),
                ("caesar salad", "2026-06-20"),
                ("chicken lunch", "2026-06-22"),
                ("caesar salad", "2026-06-22"),
            ],
        )

    def test_estimates_budget_by_category(self) -> None:
        events = build_purchase_calendar(
            [
                PurchaseItem("chicken lunch", "lunches", 35, "pcs", 70, 2, 9800),
                PurchaseItem("chicken roll", "rolls", 22, "pcs", 44, 2, 6600),
            ],
            date(2026, 6, 18),
            6,
        )

        self.assertEqual(
            estimate_calendar_budget(events),
            {"lunches": 29400.0, "rolls": 19800.0},
        )

    def test_summarizes_expenses_by_category(self) -> None:
        totals = summarize_expenses(
            [
                ExpenseRecord(date(2026, 6, 1), "lunches", 9800, "обеды"),
                ExpenseRecord(date(2026, 6, 2), "salads", 5400, "салаты"),
                ExpenseRecord(date(2026, 6, 3), "lunches", 4200, "дозаказ"),
            ]
        )

        self.assertEqual(totals, {"lunches": 14000.0, "salads": 5400.0})

    def test_rejects_invalid_usage(self) -> None:
        item = PurchaseItem("chicken lunch", "lunches", 0, "pcs", 70, 2, 9800)

        with self.assertRaises(ValueError):
            item.purchase_interval_days()
