from datetime import date
from unittest import TestCase
from unittest.mock import patch


class MenuPageTests(TestCase):
    def test_dashboard_payload_filters_disabled_menu_items(self) -> None:
        import src.app.web_server as web_server
        from src.domain.menu_catalog import MenuCatalogState

        with patch.object(web_server, "load_menu_state", lambda _path=web_server.DEFAULT_MENU_STATE_PATH: MenuCatalogState(disabled={"суп лапша куриный 0,300"})):
            payload = web_server.build_culinary_strategy_payload(reference_day=date(2026, 8, 4))

        self.assertIsNotNone(payload)
        assert payload is not None
        names = {str(row["name"]).lower() for order in payload["future_orders"] for row in order["rows"]}
        self.assertFalse(any("суп лапша куриный" in name for name in names))

    def test_menu_page_renders_catalog_and_toggle_actions(self) -> None:
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
        self.assertIn("Исключить из расчета", html)
