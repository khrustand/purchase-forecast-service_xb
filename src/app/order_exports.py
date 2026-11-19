"""Prepare and retain the exact order shown on a browser page."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import date, datetime
from secrets import token_urlsafe
from threading import Lock
from time import monotonic
from typing import Any

from src.domain.order_policy import MOSCOW
from src.infrastructure.order_workbook import OrderLine, OrderSheet, build_order_workbook
from src.infrastructure.report_analytics import product_key


@dataclass(frozen=True)
class OrderDownload:
    filename: str
    content: bytes


def prepare_order_download(strategy: dict[str, Any]) -> OrderDownload:
    current = strategy['future_orders'][0]
    dates = tuple(date.fromisoformat(day['date']) for day in current['daily_totals'])
    keys = {product_key(row['name']): str(row.get('sku') or '')
            for row in strategy.get('matrix_proposal', {}).get('rows', [])}
    supplier = []
    for row in current['rows']:
        by_day = {day['date']: day for day in row['daily_forecast']}
        quantities = tuple(None if row.get('quantity_unknown') and index < int(row['shelf_life_days'])
                           else by_day.get(day.isoformat(), {}).get('quantity') for index, day in enumerate(dates))
        supplier.append(OrderLine(keys.get(product_key(row['name']), ''), row['name'], row['category'], quantities))

    production = {day['date']: day for day in strategy.get('production_days', [])}
    item_names = {}
    for day in dates:
        for row in production.get(day.isoformat(), {}).get('rows', []):
            item_names[product_key(row['name'])] = row
    own = []
    for key, item in sorted(item_names.items(), key=lambda pair: pair[1]['name']):
        rows = [next((row for row in production.get(day.isoformat(), {}).get('rows', [])
                      if product_key(row['name']) == key), {}) for day in dates]
        own.append(OrderLine(str(item.get('sku') or ''), item['name'], item['category'],
                             tuple(row.get('quantity') for row in rows)))
    supplier_title = f"Поставка {dates[0]:%d.%m.%Y} утром."
    if current.get('deadline'):
        deadline = datetime.fromisoformat(current['deadline']).astimezone(MOSCOW)
        supplier_title += f" Заказать до {deadline:%d.%m.%Y %H:%M} МСК."
    else:
        supplier_title += " Срок заказа уточните."
    tt_title = f"Кулинария ТТ: {dates[0]:%d.%m.%Y}–{dates[-1]:%d.%m.%Y}"
    sheets = (
        OrderSheet('Поставка', supplier_title, dates, tuple(supplier), totals_label='Итого к поставке'),
        OrderSheet('Кулинария ТТ', tt_title, dates, tuple(own), totals_label='Итого ТТ', by_day=True),
    )
    return OrderDownload(f'culinary-order-{dates[0].isoformat()}.xlsx', build_order_workbook(sheets))


class OrderExportStore:
    """Per-server bounded cache. Downloads never rerun a forecast or read user paths."""
    def __init__(self, max_entries: int = 64, ttl_seconds: float = 86400):
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self._entries: OrderedDict[str, tuple[float, OrderDownload]] = OrderedDict()
        self._lock = Lock()

    def _expire(self, now: float) -> None:
        while self._entries and now - next(iter(self._entries.values()))[0] >= self.ttl_seconds:
            self._entries.popitem(last=False)

    def add(self, download: OrderDownload) -> str:
        with self._lock:
            self._expire(monotonic())
            token = token_urlsafe(24)
            self._entries[token] = (monotonic(), download)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
            return token

    def get(self, token: str) -> OrderDownload | None:
        with self._lock:
            self._expire(monotonic())
            entry = self._entries.get(token)
            return entry[1] if entry else None
