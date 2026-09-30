from datetime import date
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch


class MenuPageTests(TestCase):
    def test_dashboard_payload_filters_disabled_menu_items(self) -> None:
        import src.app.web_server as web_server
        from src.domain.menu_catalog import MenuCatalogState

        with patch.object(
            web_server,
            "load_menu_state",
            lambda _path=web_server.DEFAULT_MENU_STATE_PATH: MenuCatalogState(
                disabled={"суп лапша куриный 0,300"}
            ),
        ):
            payload = web_server.build_culinary_strategy_payload(reference_day=date(2026, 8, 4))

        self.assertIsNotNone(payload)
        assert payload is not None
        names = {str(row["name"]).lower() for order in payload["future_orders"] for row in order["rows"]}
        self.assertFalse(any("суп лапша куриный" in name for name in names))

    def test_menu_page_renders_catalog_and_upload_form(self) -> None:
        from src.app.web_server import render_menu_html
        from src.domain.menu_catalog import MenuCatalogItem

        html = render_menu_html(
            [
                MenuCatalogItem(
                    sku="284004",
                    name="Блины с курицей и сливочным сыром 0,160",
                    normalized_name="блины с курицей и сливочным сыром 0,160",
                    group="Завтраки",
                    times_ordered=3,
                    average_order_quantity=4.7,
                    last_order_quantity=5,
                    enabled=True,
                )
            ]
        )

        self.assertIn("Управление меню", html)
        self.assertIn("Блины с курицей", html)
        self.assertIn("/menu/toggle", html)
        self.assertIn("/menu/upload", html)
        self.assertIn('type="file"', html)
        self.assertIn("Исключить из расчета", html)

    def test_menu_upload_saves_xlsx_to_previous_orders_folder(self) -> None:
        from src.app.web_server import save_menu_order_upload

        with TemporaryDirectory() as directory:
            saved = save_menu_order_upload("Заказ №1.xlsx", b"xlsx-content", Path(directory))

            self.assertEqual(saved.name, "Заказ _1.xlsx")
            self.assertEqual(saved.read_bytes(), b"xlsx-content")

    def test_menu_upload_rejects_non_xlsx_file(self) -> None:
        from src.app.web_server import save_menu_order_upload
        from src.infrastructure.report_storage import ReportValidationError

        with TemporaryDirectory() as directory:
            with self.assertRaises(ReportValidationError):
                save_menu_order_upload("Заказ.csv", b"content", Path(directory))

    def test_menu_coverage_separates_menu_disabled_and_outside_items(self) -> None:
        from src.app.web_server import build_menu_coverage
        from src.domain.menu_catalog import MenuCatalogItem

        sales_items = [
            SimpleNamespace(category="Супы", name="Суп лапша куриный 0,300", by_date={date(2026, 8, 1): 4}),
            SimpleNamespace(category="Салаты", name="Оливье с колбасой 0,180", by_date={date(2026, 8, 1): 3}),
            SimpleNamespace(category="Горячее", name="Позиция вне меню", by_date={date(2026, 8, 1): 5}),
        ]
        menu_items = [
            MenuCatalogItem("1", "Суп лапша куриный 0,300", "суп лапша куриный 0,300", "Супы", 2, 4, 4),
            MenuCatalogItem("2", "Оливье с колбасой 0,180", "оливье с колбасой 0,180", "Салаты", 2, 3, 3, enabled=False),
        ]

        coverage = build_menu_coverage(sales_items, menu_items)

        self.assertEqual(coverage["in_menu"]["items"], 1)
        self.assertEqual(coverage["in_menu"]["quantity"], 4)
        self.assertEqual(coverage["disabled"]["items"], 1)
        self.assertEqual(coverage["disabled"]["quantity"], 3)
        self.assertEqual(coverage["outside_menu"]["items"], 1)
        self.assertEqual(coverage["outside_menu"]["quantity"], 5)
        self.assertEqual(coverage["outside_menu"]["rows"][0]["name"], "Позиция вне меню")
