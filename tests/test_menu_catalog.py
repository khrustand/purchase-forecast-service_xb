import tempfile
from pathlib import Path
from unittest import TestCase


class MenuCatalogTests(TestCase):
    def test_extracts_culinary_order_items_and_cleans_own_production_marker(self) -> None:
        from src.domain.menu_catalog import extract_order_menu_items

        rows = [
            ["№", "Артикул", "Товар", "К-во Фасовок", "Фасовка", "Общее к-во"],
            ["1", "284004", "284004 Блины с курицей и сливочным сыром 0,160*", "5", "порц", "5"],
            ["2", "281016", "281016 Фо-Бо 0,300* снято", "0", "порц", "0"],
            ["3", "286004", "286004 Оливье с колбасой 0,180*", "", "порц", "6"],
        ]

        items = extract_order_menu_items(rows)

        self.assertEqual([item.sku for item in items], ["284004", "286004"])
        self.assertEqual(items[0].name, "Блины с курицей и сливочным сыром 0,160")
        self.assertEqual(items[0].last_order_quantity, 5)
        self.assertEqual(items[1].last_order_quantity, 6)

    def test_overrides_exclude_item_from_enabled_menu(self) -> None:
        from src.domain.menu_catalog import MenuCatalogItem, MenuCatalogState, apply_menu_state

        item = MenuCatalogItem(
            sku="284004",
            name="Блины с курицей и сливочным сыром 0,160",
            normalized_name="блины с курицей и сливочным сыром 0,160",
            group="Завтраки",
            times_ordered=2,
            average_order_quantity=4.5,
            last_order_quantity=5,
        )
        state = MenuCatalogState(disabled={"блины с курицей и сливочным сыром 0,160"})

        [result] = apply_menu_state([item], state)

        self.assertFalse(result.enabled)

    def test_state_round_trip(self) -> None:
        from src.domain.menu_catalog import MenuCatalogState, load_menu_state, save_menu_state

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "menu-state.json"
            save_menu_state(path, MenuCatalogState(disabled={"суп лапша куриный 0,300"}))

            loaded = load_menu_state(path)

        self.assertEqual(loaded.disabled, {"суп лапша куриный 0,300"})
