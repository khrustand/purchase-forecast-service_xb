"""Подтвержденные правила поставок и производства кулинарии."""

from datetime import date, datetime, time, timedelta, timezone
from math import ceil

MOSCOW = timezone(timedelta(hours=3))
DELIVERY_WEEKDAYS = {0, 2, 4}
DISPLAY_CAPACITY = 32
STAFF_PORTIONS = 5
LOSS_TARGET_PERCENT = 2.0


def moscow_now() -> datetime:
    return datetime.now(MOSCOW)


def delivery_deadline(delivery: date) -> datetime:
    return datetime.combine(delivery - timedelta(days=2), time(18), MOSCOW)


def earliest_delivery(now: datetime, requested: date | None = None) -> date:
    local = now.replace(tzinfo=MOSCOW) if now.tzinfo is None else now.astimezone(MOSCOW)
    # «До 18:00»: ровно в 18:00 окно на послезавтра уже закрыто.
    cursor = local.date() + timedelta(days=2 if local.time() < time(18) else 3)
    cursor = max(cursor, requested) if requested else cursor
    while cursor.weekday() not in DELIVERY_WEEKDAYS:
        cursor += timedelta(days=1)
    return cursor


def production_batch(name: str) -> int:
    key = name.casefold().replace('*', '').strip()
    if key.startswith(('каша овсяная', 'каша рисовая')):
        return 5
    if key.startswith('омлет'):
        return 4
    if key.startswith('запеканка'):
        return 8
    return 1


def round_production(name: str, need: int | None) -> dict:
    batch = production_batch(name)
    quantity = ceil(max(0, need) / batch) * batch if need is not None else None
    return {'batch_size': batch, 'quantity': quantity,
            'batch_extra': quantity - need if need is not None else None}
