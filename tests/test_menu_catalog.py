import tempfile
from pathlib import Path
from unittest import TestCase


class MenuCatalogTests(TestCase):
    def test_snapshot_includes_unordered_and_excludes_retired(self):
        from src.domain.menu_catalog import extract_order_menu_items
        rows = [['Артикул', 'Товар'], ['1', '1 Суп новый'], ['2', '2 Суп снято']]
        items = extract_order_menu_items(rows, include_unordered=True)
        self.assertEqual([row.sku for row in items], ['1'])
        self.assertEqual(items[0].times_ordered, 0)

    def test_latest_snapshot_does_not_resurrect_old_or_retired_dishes(self):
        from unittest.mock import patch
        from src.domain.menu_catalog import build_menu_catalog
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'old.xlsx').write_bytes(b'old')
            (root / 'current.xlsx').write_bytes(b'current')
            history = [['Артикул', 'Товар', 'К-во фасовок'], ['old', 'Бывший суп', '10']]
            current = [['Артикул', 'Товар'], ['new', 'Новый суп'], ['old', 'Бывший суп снято']]
            with patch('src.domain.menu_catalog.read_culinary_order_sheet', side_effect=lambda p: current if p.name == 'current.xlsx' else history):
                result = build_menu_catalog(root)
        self.assertEqual([row.sku for row in result], ['new'])

    def test_extracts_order_items_without_treating_star_as_own_production(self) -> None:
        from src.domain.menu_catalog import extract_order_menu_items

        rows = [
            ["N", "Артикул", "Товар", "К-во фасовок", "Фасовка", "Общее к-во"],
            ["1", "284004", "284004 Блины с курицей 0,160*", "5", "порц", "5"],
            ["2", "281016", "281016 Фо-Бо 0,300* снято", "0", "порц", "0"],
            ["3", "286004", "286004 Оливье с колбасой 0,180*", "", "порц", "6"],
            ["4", "288009", "288009 Бефстроганов 0,300", "", "порц", "4"],
        ]

        items = extract_order_menu_items(rows)

        self.assertEqual([item.sku for item in items], ["284004", "286004", "288009"])
        self.assertEqual(items[0].name, "Блины с курицей 0,160")
        self.assertFalse(items[0].own_production)
        self.assertEqual(items[0].last_order_quantity, 5)
        self.assertEqual(items[1].name, "Оливье с колбасой 0,180")
        self.assertFalse(items[1].own_production)
        self.assertEqual(items[1].last_order_quantity, 6)
        self.assertFalse(items[2].own_production)

    def test_overrides_exclude_item_from_enabled_menu(self) -> None:
        from src.domain.menu_catalog import MenuCatalogItem, MenuCatalogState, apply_menu_state

        item = MenuCatalogItem(
            sku="284004",
            name="Блины с курицей 0,160",
            normalized_name="блины с курицей 0,160",
            group="Завтраки",
            times_ordered=2,
            average_order_quantity=4.5,
            last_order_quantity=5,
        )
        state = MenuCatalogState(disabled={"блины с курицей 0,160"})

        [result] = apply_menu_state([item], state)

        self.assertFalse(result.enabled)

    def test_overrides_mark_item_as_own_production(self) -> None:
        from src.domain.menu_catalog import MenuCatalogItem, MenuCatalogState, apply_menu_state

        item = MenuCatalogItem(
            sku="284004",
            name="Supplier by default",
            normalized_name="supplier by default",
            group="Hot",
            times_ordered=2,
            average_order_quantity=4.5,
            last_order_quantity=5,
        )
        state = MenuCatalogState(disabled=set(), own_production={"supplier by default"})

        [result] = apply_menu_state([item], state)

        self.assertTrue(result.enabled)
        self.assertTrue(result.own_production)

    def test_state_round_trip(self) -> None:
        from src.domain.menu_catalog import MenuCatalogState, load_menu_state, save_menu_state

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "menu-state.json"
            save_menu_state(
                path,
                MenuCatalogState(
                    disabled={"суп лапша куриный 0,300"},
                    own_production={"блины 0,160"},
                ),
            )

            loaded = load_menu_state(path)

        self.assertEqual(loaded.disabled, {"суп лапша куриный 0,300"})
        self.assertEqual(loaded.own_production, {"блины 0,160"})
