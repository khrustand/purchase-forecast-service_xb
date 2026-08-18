from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from math import ceil, floor


@dataclass(frozen=True)
class PurchaseItem:
    name: str
    category: str
    daily_usage: float
    unit: str
    package_quantity: float
    shelf_life_days: int
    estimated_price: float = 0.0

    def days_per_package(self) -> int:
        if self.daily_usage <= 0:
            raise ValueError("daily_usage must be greater than zero")
        if self.package_quantity <= 0:
            raise ValueError("package_quantity must be greater than zero")
        return max(1, floor(self.package_quantity / self.daily_usage))

    def purchase_interval_days(self) -> int:
        if self.shelf_life_days <= 0:
            raise ValueError("shelf_life_days must be greater than zero")
        return max(1, min(self.days_per_package(), self.shelf_life_days))


@dataclass(frozen=True)
class PurchaseEvent:
    day: date
    item_name: str
    category: str
    quantity: float
    unit: str
    estimated_price: float


@dataclass(frozen=True)
class ExpenseRecord:
    day: date
    category: str
    amount: float
    description: str = ""


def build_purchase_calendar(
    items: list[PurchaseItem],
    start_day: date,
    horizon_days: int,
) -> list[PurchaseEvent]:
    if horizon_days <= 0:
        raise ValueError("horizon_days must be greater than zero")

    events: list[PurchaseEvent] = []
    for item in items:
        interval = item.purchase_interval_days()
        purchase_day = start_day
        end_day = start_day + timedelta(days=horizon_days - 1)

        while purchase_day <= end_day:
            packages = ceil((item.daily_usage * interval) / item.package_quantity)
            events.append(
                PurchaseEvent(
                    day=purchase_day,
                    item_name=item.name,
                    category=item.category,
                    quantity=packages * item.package_quantity,
                    unit=item.unit,
                    estimated_price=packages * item.estimated_price,
                )
            )
            purchase_day += timedelta(days=interval)

    return sorted(events, key=lambda event: (event.day, event.category, event.item_name))


def summarize_expenses(records: list[ExpenseRecord]) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for record in records:
        if record.amount < 0:
            raise ValueError("expense amount must not be negative")
        totals[record.category] += record.amount
    return dict(sorted(totals.items()))


def estimate_calendar_budget(events: list[PurchaseEvent]) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for event in events:
        if event.estimated_price < 0:
            raise ValueError("estimated price must not be negative")
        totals[event.category] += event.estimated_price
    return dict(sorted(totals.items()))
