from datetime import date
from unittest import TestCase

from src.app.web_server import build_dashboard_payload, render_dashboard_html


class WebServerTests(TestCase):
    def test_builds_dashboard_payload(self) -> None:
        payload = build_dashboard_payload(start_day=date(2026, 8, 4), horizon_days=14)

        self.assertEqual(payload["start_day"], "2026-08-04")
        self.assertEqual(payload["order_cycle_days"], 2)
        self.assertEqual(payload["budget_total"], 225400.0)
        self.assertEqual(payload["budget"]["Обеды"], 68600.0)
        self.assertIn("forecast_logic", payload)
        self.assertIsNotNone(payload["culinary_strategy"])
        self.assertEqual(payload["culinary_strategy"]["period"], "2026-06-01..2026-08-03")
        self.assertEqual(payload["culinary_strategy"]["weather_city"], "Санкт-Петербург")
        self.assertEqual(payload["culinary_strategy"]["summary"]["target_total"], 34)
        self.assertEqual(payload["culinary_strategy"]["future_orders"][0]["label"], "Ср+Чт")
        self.assertEqual(payload["culinary_strategy"]["future_orders"][0]["start"], "2026-08-05")
        self.assertEqual(payload["culinary_strategy"]["future_orders"][1]["label"], "Пт+Сб+Вс")
        self.assertEqual(payload["culinary_strategy"]["future_orders"][1]["total_quantity"], 129)
        self.assertIn("трехдневное окно", payload["culinary_strategy"]["future_orders"][1]["order_policy"])
        self.assertEqual(len(payload["culinary_strategy"]["retrospective_orders"]), 3)
        self.assertIn("weather_sales_summary", payload["culinary_strategy"])
        self.assertIn("risk_reason", payload["culinary_strategy"]["future_orders"][0]["rows"][0])
        self.assertIn("decision_reason", payload["culinary_strategy"]["future_orders"][0]["rows"][0])
        self.assertEqual(payload["culinary_strategy"]["future_orders"][0]["previous_period"], "2026-07-29..2026-07-30")
        self.assertIn("previous_period_sales", payload["culinary_strategy"]["future_orders"][0]["rows"][0])
        self.assertIn("previous_period_waste", payload["culinary_strategy"]["future_orders"][0]["rows"][0])
        first_order = payload["culinary_strategy"]["future_orders"][0]
        self.assertEqual(
            sum(day["quantity"] for day in first_order["daily_totals"]),
            first_order["total_quantity"],
        )
        for row in first_order["rows"]:
            self.assertEqual(
                sum(day["quantity"] for day in row["daily_forecast"]),
                row["forecast_quantity"],
            )

    def test_builds_forecast_for_selected_current_date(self) -> None:
        payload = build_dashboard_payload(start_day=date(2026, 8, 19), horizon_days=7)

        current_order = payload["culinary_strategy"]["future_orders"][0]
        self.assertEqual(current_order["label"], "Ср+Чт")
        self.assertEqual(current_order["start"], "2026-08-19")
        self.assertEqual(current_order["end"], "2026-08-20")
        self.assertIn("19.08: сильный дождь", current_order["weather"])

    def test_renders_dashboard_html(self) -> None:
        html = render_dashboard_html(
            build_dashboard_payload(start_day=date(2026, 8, 4), horizon_days=4)
        )

        self.assertIn("Заказы кулинарии", html)
        self.assertIn("Логика прогноза", html)
        self.assertIn("Обед с курицей", html)
        self.assertIn("tab-base", html)
        self.assertIn("tab-rotation", html)
        self.assertIn("tab-reserve", html)
        self.assertIn("Спрос по погоде", html)
        self.assertIn("Продажи прошлого окна", html)
        self.assertIn("Списания прошлого окна", html)
        self.assertIn("По дням", html)
