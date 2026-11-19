from datetime import date, datetime
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import patch

from types import SimpleNamespace

from src.app import web_server
from src.app.web_server import _rain_sales_impact, build_dashboard_payload, render_dashboard_html, server_port


class WebServerTests(TestCase):
    def setUp(self):
        from tests.synthetic_sales import dashboard_fixture
        fixture = dashboard_fixture(web_server)
        fixture.__enter__()
        self.addCleanup(fixture.__exit__, None, None, None)

    def test_default_query_preserves_evening_planning_start(self):
        with patch.object(web_server, 'build_dashboard_payload') as build:
            web_server._payload_from_query('')
        self.assertIsNone(build.call_args.kwargs['start_day'])
        with patch.object(web_server, 'build_culinary_strategy_payload', return_value=None) as strategy:
            payload=build_dashboard_payload(now=datetime(2026,11,16,18,1))
        self.assertEqual(payload['start_day'], '2026-11-17')
        self.assertEqual(strategy.call_args.kwargs['production_start_day'],date(2026,11,17))

    def test_server_port_prefers_platform_port(self) -> None:
        with patch.dict("os.environ", {"PORT": "10000", "APP_PORT": "8000"}, clear=True):
            self.assertEqual(server_port(), 10000)

    def test_server_port_uses_app_port_when_platform_port_missing(self) -> None:
        with patch.dict("os.environ", {"APP_PORT": "9000"}, clear=True):
            self.assertEqual(server_port(), 9000)

    def test_builds_dashboard_payload(self) -> None:
        with patch.object(web_server, "DEFAULT_PREVIOUS_ORDERS_DIR", Path("__missing_previous_orders__")):
            payload = build_dashboard_payload(start_day=date(2026, 8, 4), horizon_days=14,
                                              now=datetime(2026, 8, 2, 12))

        self.assertEqual(payload["start_day"], "2026-08-04")
        self.assertEqual(payload["order_cycle_days"], 2)
        self.assertEqual(payload["budget_total"], 225400.0)
        self.assertEqual(payload["budget"]["Обеды"], 68600.0)
        self.assertIn("forecast_logic", payload)
        self.assertIsNotNone(payload["culinary_strategy"])
        self.assertEqual(payload["culinary_strategy"]["period"], "2026-06-01..2026-08-03")
        self.assertEqual(payload["culinary_strategy"]["weather_city"], "Санкт-Петербург")
        self.assertEqual(payload["culinary_strategy"]["summary"]["target_total"], 32)
        self.assertEqual(payload["culinary_strategy"]["future_orders"][0]["label"], "Ср+Чт")
        self.assertEqual(payload["culinary_strategy"]["future_orders"][0]["start"], "2026-08-05")
        self.assertEqual(payload["culinary_strategy"]["future_orders"][1]["label"], "Пт+Сб+Вс")
        self.assertGreater(payload["culinary_strategy"]["future_orders"][1]["total_quantity"], 125)
        self.assertIn("трехдневное окно", payload["culinary_strategy"]["future_orders"][1]["order_policy"])
        self.assertEqual(len(payload["culinary_strategy"]["retrospective_orders"]), 3)
        self.assertIn("weather_sales_summary", payload["culinary_strategy"])
        self.assertIn("risk_reason", payload["culinary_strategy"]["future_orders"][0]["rows"][0])
        self.assertIn("decision_reason", payload["culinary_strategy"]["future_orders"][0]["rows"][0])
        self.assertEqual(payload["culinary_strategy"]["future_orders"][0]["previous_period"], "2026-07-29..2026-07-30")
        self.assertIn("previous_period_sales", payload["culinary_strategy"]["future_orders"][0]["rows"][0])
        self.assertIn("previous_period_waste", payload["culinary_strategy"]["future_orders"][0]["rows"][0])
        first_order = payload["culinary_strategy"]["future_orders"][0]
        self.assertIn("rain_sales_impact", payload["culinary_strategy"])
        self.assertIn("traffic_factor", first_order["daily_totals"][0])
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
        with patch.object(web_server, "DEFAULT_PREVIOUS_ORDERS_DIR", Path("__missing_previous_orders__")):
            payload = build_dashboard_payload(start_day=date(2026, 8, 19), horizon_days=7,
                                              now=datetime(2026, 8, 17, 12))

        current_order = payload["culinary_strategy"]["future_orders"][0]
        self.assertEqual(current_order["label"], "Ср+Чт")
        self.assertEqual(current_order["start"], "2026-08-19")
        self.assertEqual(current_order["end"], "2026-08-20")
        self.assertIn("19.08: сильный дождь", current_order["weather"])
        self.assertTrue(current_order["daily_totals"][0]["rain"])
        self.assertLess(current_order["daily_totals"][0]["traffic_factor"], 1)

    def test_builds_next_order_windows_from_september_sixth(self) -> None:
        with patch.object(web_server, "DEFAULT_PREVIOUS_ORDERS_DIR", Path("__missing_previous_orders__")):
            payload = build_dashboard_payload(start_day=date(2026, 9, 6), horizon_days=14,
                                              now=datetime(2026, 9, 4, 12))

        orders = payload["culinary_strategy"]["future_orders"]
        self.assertEqual(orders[0]["start"], "2026-09-07")
        self.assertEqual(orders[1]["start"], "2026-09-09")
        self.assertEqual(orders[2]["start"], "2026-09-11")
        self.assertFalse(orders[0]["daily_totals"][0]["weather_available"])

    def test_own_production_stays_in_forecast_as_production_plan(self) -> None:
        from scripts.analyze_culinary_strategy import DAILY_MENU_QUOTAS, DailySalesItem
        from src.domain.menu_catalog import MenuCatalogItem, MenuCatalogState, save_menu_state

        own_item = MenuCatalogItem(
            sku="own",
            name="Own meal",
            normalized_name="own meal",
            group="Hot",
            times_ordered=1,
            average_order_quantity=5,
            last_order_quantity=5,
        )
        supplier_item = MenuCatalogItem(
            sku="supplier",
            name="Supplier meal",
            normalized_name="supplier meal",
            group="Hot",
            times_ordered=1,
            average_order_quantity=5,
            last_order_quantity=5,
        )
        category = next(iter(DAILY_MENU_QUOTAS))
        own_sales = {date(2026, 6, day): 10 for day in range(1, 11)}
        supplier_sales = {date(2026, 6, day): 30 for day in range(1, 11)}
        sales_items = [
            DailySalesItem(category, "Own meal", own_sales),
            DailySalesItem(category, "Supplier meal", supplier_sales),
        ]

        with tempfile.TemporaryDirectory() as directory:
            sales_path = Path(directory) / "sales.xlsx"
            sales_path.write_text("placeholder", encoding="utf-8")
            menu_state_path = Path(directory) / "menu-state.json"
            save_menu_state(menu_state_path, MenuCatalogState(disabled=set(), own_production={"own meal"}))
            with patch.object(web_server, "DEFAULT_MENU_STATE_PATH", menu_state_path):
                with patch.object(web_server, "build_menu_catalog", return_value=[own_item, supplier_item]):
                    with patch('src.infrastructure.report_analytics.read_xlsx', return_value=[]), patch.object(web_server, "read_xlsx", return_value=[]), patch.object(web_server, "dish_economics", return_value={
                        'start': '2026-06-01', 'end': '2026-06-10', 'rows': [], 'detailed_waste_days': 0}):
                        with patch.object(web_server, "extract_items", return_value=sales_items):
                            payload = web_server.build_culinary_strategy_payload(
                                sales_path=sales_path,
                                waste_path=Path("__missing_waste__"),
                                shelf_life_path=Path("__missing_shelf__"),
                                start_day=date(2026, 6, 1),
                                end_day=date(2026, 6, 10),
                                reference_day=date(2026, 6, 10),
                            )

        self.assertIsNotNone(payload)
        assert payload is not None
        first_order = payload["future_orders"][0]
        rows_by_name = {row["name"]: row for row in first_order["rows"]}
        self.assertNotIn("Own meal", rows_by_name)
        self.assertIn("Supplier meal", rows_by_name)
        self.assertEqual(rows_by_name["Supplier meal"]["supply_type"], "supplier")
        self.assertGreater(first_order["production_quantity"], 0)
        self.assertGreater(first_order["supplier_quantity"], 0)
        self.assertEqual(len(payload['production_days']), 7)
        self.assertEqual(payload['production_days'][0]['date'], '2026-06-11')
        self.assertEqual([row['name'] for row in payload['production_days'][0]['rows']], ['Own meal'])
        self.assertEqual(payload['production_days'][0]['rows'][0]['guest_quantity'], 10)
        self.assertEqual(first_order['staff_quantity'], first_order['days'] * 5)

    def test_rain_impact_is_learned_and_bounded_below_dry_traffic(self) -> None:
        item = SimpleNamespace(by_date={
            date(2026, 6, 1): 100,
            date(2026, 6, 4): 60,
            date(2026, 6, 8): 100,
            date(2026, 6, 11): 100,
        })

        impact = _rain_sales_impact([item], date(2026, 6, 1), date(2026, 6, 11))

        self.assertLess(impact["applied_factor"], 1)
        self.assertGreaterEqual(impact["applied_factor"], 0.70)

    def test_renders_dashboard_html(self) -> None:
        with patch.object(web_server, "DEFAULT_PREVIOUS_ORDERS_DIR", Path("__missing_previous_orders__")):
            html = render_dashboard_html(
                build_dashboard_payload(start_day=date(2026, 8, 4), horizon_days=4),
                view="analytics",
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
        self.assertIn("Учет дождя", html)

    def test_renders_simplified_orders_workspace(self) -> None:
        with patch.object(web_server, "DEFAULT_PREVIOUS_ORDERS_DIR", Path("__missing_previous_orders__")):
            html = render_dashboard_html(build_dashboard_payload(start_day=date(2026, 9, 6), horizon_days=14))

        self.assertIn("Ближайший заказ", html)
        self.assertNotIn('id="reconciliation"', html)
        self.assertIn("Заказ до", html)
        self.assertNotIn("Следующие заказы", html)
        self.assertIn("Детали позиции", html)
        self.assertIn('href="/analytics?service=', html)
        self.assertIn('class="calculation-box"', html)
        self.assertIn('class="detail-panel"', html)
        self.assertIn("<template>", html)
        self.assertNotIn("data-details=", html)
