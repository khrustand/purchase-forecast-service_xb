"""Актуальные розничные цены для поставки и собственного производства."""

import json
from dataclasses import dataclass
from pathlib import Path

from src.infrastructure.report_analytics import product_key


@dataclass(frozen=True)
class MenuPrices:
    by_sku: dict[str, int]
    by_name: dict[str, int]


def _read_prices(values: object, *, by_sku: bool) -> dict[str, int]:
    if not isinstance(values, dict):
        raise ValueError('Цены должны быть указаны словарем.')
    result = {}
    for name, price in values.items():
        key = name if by_sku else product_key(name)
        if not key or (by_sku and not key.isdecimal()) or type(price) is not int or price <= 0:
            raise ValueError('Для каждой позиции нужна положительная цена в целых рублях.')
        if key in result:
            raise ValueError('В прайсе повторяется позиция.')
        result[key] = price
    return result


def load_menu_prices(path: Path) -> MenuPrices:
    if not path.exists():
        return MenuPrices({}, {})
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if isinstance(data, dict) and ('by_sku' in data or 'by_name' in data):
        return MenuPrices(_read_prices(data.get('by_sku', {}), by_sku=True),
                          _read_prices(data.get('by_name', {}), by_sku=False))
    return MenuPrices(_read_prices(data, by_sku=True), {})
