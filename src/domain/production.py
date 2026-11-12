"""Ежедневный план собственного производства без графика поставщика."""

from datetime import date, timedelta
from typing import Any, Mapping


def daily_production_plan(
    items: list[dict[str, Any]],
    start: date,
    days: int,
    history: Mapping[str, Mapping[date, float]],
    factors: Mapping[tuple[str, date], float],
) -> list[dict[str, Any]]:
    result = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        rows = []
        for item in items:
            # Будущие продажи не должны участвовать в исторической базе.
            observed = {d: q for d, q in history.get(item['key'], {}).items() if d < start}
            matching = [q for d, q in observed.items() if d.weekday() == day.weekday()]
            values = matching or list(observed.values())
            average = sum(values) / len(values) if values else None
            factor = factors.get((item['key'], day), 1.0)
            quantity = max(0, round(average * factor)) if average is not None else None
            rows.append({
                **item, 'quantity': quantity, 'base_quantity': average,
                'weather_factor': round(factor, 2), 'history_points': len(values),
                'basis': 'день недели' if matching else ('среднее за историю' if values else 'нет продаж'),
            })
        result.append({'date': day.isoformat(), 'rows': rows,
                       'total': sum(row['quantity'] or 0 for row in rows),
                       'missing_history': sum(row['quantity'] is None for row in rows)})
    return result
