"""Date navigation for the existing order page, independent of forecasts."""
from datetime import date, datetime, timedelta
from html import escape
from urllib.parse import urlencode

from src.domain.order_policy import DELIVERY_WEEKDAYS, earliest_delivery


def upcoming_order_dates(clock: datetime) -> list[str]:
    start = earliest_delivery(clock)
    return [(start + timedelta(days=offset)).isoformat() for offset in range(14)
            if (start + timedelta(days=offset)).weekday() in DELIVERY_WEEKDAYS]


def render_order_date_tabs(dates: list[str], selected: str, service: int, reserve_cost: int) -> str:
    if not dates:
        return ''
    weekdays = ('Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс')
    links = []
    for value in dates:
        day = date.fromisoformat(value)
        active = value == selected
        query = urlencode({'start': value, 'days': 14, 'service': service, 'reserve_cost': reserve_cost})
        current = ' aria-current="page"' if active else ''
        links.append(f'<a class="order-date-tab{" active" if active else ""}" '
                     f'href="/?{escape(query, quote=True)}"{current}>'
                     f'{weekdays[day.weekday()]}, {day:%d.%m.%Y}</a>')
    return '<nav class="order-date-tabs" aria-label="Даты заказов">' + ''.join(links) + '</nav>'
