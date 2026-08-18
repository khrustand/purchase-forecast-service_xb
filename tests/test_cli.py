import json
import tempfile
from datetime import date
from pathlib import Path
from unittest import TestCase

from src.app.cli import load_purchase_items, render_budget_summary, render_purchase_calendar
from src.domain.planning import build_purchase_calendar


class CliTests(TestCase):
    def test_loads_purchase_items_from_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "items.json"
            path.write_text(
                json.dumps(
                    [
                        {
                            "name": "chicken lunch",
                            "category": "lunches",
                            "daily_usage": 35,
                            "unit": "pcs",
                            "package_quantity": 70,
                            "shelf_life_days": 2,
                            "estimated_price": 9800,
                        }
                    ]
                ),
                encoding="utf-8",
            )

            items = load_purchase_items(path)

        self.assertEqual(items[0].name, "chicken lunch")
        self.assertEqual(items[0].daily_usage, 35)

    def test_renders_calendar_and_budget(self) -> None:
        items = load_purchase_items(Path("data/examples/purchase_items.json"))
        events = build_purchase_calendar(items, date(2026, 6, 18), 4)

        calendar = render_purchase_calendar(events)
        budget = render_budget_summary(events)

        self.assertIn("2026-06-18 | Обеды | Обед с курицей | 70 шт. | 9800", calendar)
        self.assertIn("Горячие блюда | 20800", budget)
