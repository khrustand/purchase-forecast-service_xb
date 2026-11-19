"""Сверка резерва отдельных блюд с наблюдаемым спросом на группу."""

from collections import defaultdict
from datetime import date
from html import escape
from typing import Callable

from src.domain.demand_planning import plan_demand
from src.infrastructure.report_analytics import product_key


def check_category_reserves(
    rows: list[dict], history: dict[str, dict[date, float]], days: list[date], cutoff: date,
    service_level: float, factors: Callable, replan: Callable,
) -> list[dict]:
    groups = defaultdict(list)
    for row in rows:
        if product_key(row['name']).startswith('блины '):
            groups[('Блины', row['category'])].append(row)
    for row in rows:
        groups[(row['category'], row['category'])].append(row)
    checks = []
    for (label, category), members in groups.items():
        if len(members) < 2:
            continue
        usable = min(len(days), max(row['shelf_life_days'] for row in members))
        window = days[:usable]
        combined = defaultdict(float)
        for row in members:
            for day, quantity in history.get(product_key(row['name']), {}).items():
                if len(window) == 3 and day.weekday() == 6 and row['shelf_life_days'] == 2:
                    continue
                combined[day] += quantity
        model = plan_demand(combined, window, cutoff, [0] * usable, factors(category, window, combined),
                            service_level=service_level)
        reference = model['service_quantity'] if model['history_points'] >= 3 and (
            model['basis'] == 'сопоставимые календарные окна') else None
        guest_before = sum(row['model']['guest_quantity'] or 0 for row in members)
        excess = max(0, guest_before - reference) if reference is not None else 0
        removed = 0
        if excess:
            candidates = sorted(
                (row for row in members if row['model']['economic_quantity'] is not None),
                key=lambda row: -(row['model']['expected_remaining_cost'] or 0),
            )
            for row in candidates:
                current = row['model']
                remove = min(excess - removed, current['guest_quantity'] - current['economic_quantity'])
                if remove > 0:
                    replan(row, current['guest_quantity'] - remove)
                    removed += remove
                if removed == excess:
                    break
        checks.append({
            'category': label, 'days': usable, 'windows': model['history_points'],
            'expected_demand': model['expected_demand'] if reference is not None else None,
            'reference': reference, 'guest_before': guest_before,
            'guest_after': guest_before - removed, 'removed': removed,
            'staff': sum(row['staff_quantity'] for row in members),
        })
    for check, members in zip(checks, (g for g in groups.values() if len(g) >= 2)):
        check['guest_after'] = sum(row['model']['guest_quantity'] or 0 for row in members)
    return checks


def render_category_reserves(checks: list[dict]) -> str:
    if not checks:
        return ''
    rows = ''.join(
        f"<tr><td>{escape(check['category'])}</td><td>{check['days']}</td>"
        f"<td>{check['reference'] if check['reference'] is not None else 'мало данных'}</td>"
        f"<td>{check['guest_before']}</td><td>{check['guest_after']}</td><td>{check['staff']}</td></tr>"
        for check in checks
    )
    return f'''<details class="calculation-box"><summary>Спрос по группам</summary>
    <p>Ориентир рассчитан по суммарным продажам группы в сопоставимые дни с поправкой на чеки и погоду.
    При превышении программа уменьшает дополнительный резерв. Если после сверки объем выше ориентира,
    проверьте сочетание похожих блюд и тестовых позиций перед отправкой заказа.</p>
    <div class="table-wrap"><table><thead><tr><th>Группа</th><th>Дней</th><th>Ориентир для гостей</th>
    <th>До сверки</th><th>После сверки</th><th>Питание</th></tr></thead><tbody>{rows}</tbody></table></div></details>'''
