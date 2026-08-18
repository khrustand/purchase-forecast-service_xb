from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

from src.domain.planning import (
    PurchaseEvent,
    PurchaseItem,
    build_purchase_calendar,
    estimate_calendar_budget,
)


CATEGORY_LABELS = {
    "lunches": "Обеды",
    "salads": "Салаты",
    "rolls": "Роллы",
    "hot_meals": "Горячие блюда",
}

ITEM_LABELS = {
    "chicken lunch": "Обед с курицей",
    "caesar salad": "Салат Цезарь",
    "chicken roll": "Ролл с курицей",
    "soup of the day": "Суп дня",
    "pasta with chicken": "Паста с курицей",
}

UNIT_LABELS = {
    "pcs": "шт.",
}


def load_purchase_items(path: Path) -> list[PurchaseItem]:
    raw_items = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw_items, list):
        raise ValueError("Файл товаров должен содержать JSON-массив")

    return [_purchase_item_from_mapping(item) for item in raw_items]


def render_purchase_calendar(events: list[PurchaseEvent]) -> str:
    lines = ["дата заказа | категория | позиция кулинарии | количество | расчетная цена"]
    lines.append("--- | --- | --- | ---: | ---:")
    for event in events:
        quantity = _format_number(event.quantity)
        price = _format_number(event.estimated_price)
        lines.append(
            f"{event.day.isoformat()} | {_category_label(event.category)} | "
            f"{_item_label(event.item_name)} | {quantity} {_unit_label(event.unit)} | {price}"
        )
    return "\n".join(lines)


def render_budget_summary(events: list[PurchaseEvent]) -> str:
    totals = estimate_calendar_budget(events)
    lines = ["категория | сумма заказов", "--- | ---:"]
    for category, amount in totals.items():
        lines.append(f"{_category_label(category)} | {_format_number(amount)}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="purchase-forecast",
        description="Построить календарь заказов кулинарии из JSON-файла с позициями.",
    )
    parser.add_argument(
        "--items",
        type=Path,
        default=Path("data/examples/purchase_items.json"),
        help="Путь к JSON-массиву с позициями кулинарии.",
    )
    parser.add_argument(
        "--start",
        type=date.fromisoformat,
        default=date.today(),
        help="Дата первого заказа в формате YYYY-MM-DD.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=14,
        help="Горизонт прогноза в днях.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    items = load_purchase_items(args.items)
    events = build_purchase_calendar(items, args.start, args.days)

    print("# Календарь заказов кулинарии")
    print()
    print(render_purchase_calendar(events))
    print()
    print("# Сводка бюджета")
    print()
    print(render_budget_summary(events))
    return 0


def _purchase_item_from_mapping(item: Any) -> PurchaseItem:
    if not isinstance(item, dict):
        raise ValueError("Каждая позиция должна быть JSON-объектом")
    return PurchaseItem(
        name=str(item["name"]),
        category=str(item["category"]),
        daily_usage=float(item["daily_usage"]),
        unit=str(item["unit"]),
        package_quantity=float(item["package_quantity"]),
        shelf_life_days=int(item["shelf_life_days"]),
        estimated_price=float(item.get("estimated_price", 0)),
    )


def _category_label(category: str) -> str:
    return CATEGORY_LABELS.get(category, category)


def _item_label(item_name: str) -> str:
    return ITEM_LABELS.get(item_name, item_name)


def _unit_label(unit: str) -> str:
    return UNIT_LABELS.get(unit, unit)


def _format_number(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


if __name__ == "__main__":
    raise SystemExit(main())
