"""Кандидаты текущего ассортимента: локальный справочник, отдельно от меню заказов."""

import json
import os
from pathlib import Path

from src.infrastructure.report_analytics import product_key


def catalog_path() -> Path:
    return Path(os.getenv('LOCALAPPDATA', str(Path.home()))) / 'PurchaseForecastService' / 'assortment-candidates.json'


def load_candidates(fallback: list) -> list[dict]:
    path = catalog_path()
    previous = {}
    if path.exists():
        rows = json.loads(path.read_text(encoding='utf-8'))
        previous = {str(row.get('sku', '')).strip(): row for row in rows}
        if not fallback:
            return [{**row, 'key': product_key(row['name'])} for row in rows]
    return [{'sku': getattr(item, 'sku', ''), 'name': item.name, 'category': item.group,
             'key': product_key(item.name), 'active': item.enabled,
             'own_production': item.own_production,
             'test_priority': previous.get(str(getattr(item, 'sku', '')).strip(), {}).get('test_priority', 100)} for item in fallback]
