"""Экран месячного бюджета и факта по загруженным отчетам."""

from calendar import monthrange
from datetime import date
from html import escape

from src.domain.loss_budget import GROUP_LABELS
from src.infrastructure.loss_plans import load_loss_plans, loss_plan_path
from src.infrastructure.report_analytics import loss_group_totals


def monthly_loss_plan(month: date, sales_paths: list, waste_paths: list, receipts: dict) -> dict:
    key = month.strftime('%Y-%m')
    end = month.replace(day=monthrange(month.year, month.month)[1])
    plan = load_loss_plans(loss_plan_path()).get(key, {})
    groups = loss_group_totals(sales_paths, waste_paths, month, end)
    known = round(sum(row['waste_cost'] for row in groups.values()), 2)
    records = [row for day, row in receipts.items() if month <= day <= end]
    revenue = float(sum(row.revenue for row in records))
    budget = round(plan['revenue'] * .02, 2) if 'revenue' in plan else None
    remaining = plan.get('remaining')
    return {'month': key, 'plan': plan, 'budget': budget, 'groups': groups,
            'known': known, 'revenue': revenue, 'revenue_days': len(records),
            'budget_left': round(budget - known, 2) if budget is not None else None,
            'projected_loss': round(known + remaining, 2) if remaining is not None else None}


def render_monthly_loss_plan(result: dict) -> str:
    month, plan = result['month'], result['plan']

    def money(value):
        return '—' if value is None else f'{value:,.2f} ₽'.replace(',', ' ')

    groups = ''.join(f"<li>{label} — {money(result['groups'][group]['waste_cost'])} по данным за "
                     f"{result['groups'][group]['waste_days']} дн.</li>" for group, label in GROUP_LABELS.items())
    return f'''<section class="calculation-box" id="loss-plan">
    <h2>Бюджет списаний на месяц</h2>
    <form method="get" action="/analytics#loss-plan"><label>Месяц <input type="month" name="loss_month"
    value="{month}" required></label> <button type="submit">Показать</button></form>
    <form method="post" action="/analytics/loss-plan"><input type="hidden" name="month" value="{month}">
    <label>План выручки по БДР, ₽ <input inputmode="decimal" name="revenue"
    value="{escape(str(plan.get('revenue', '')))}" required></label>
    <label>Оценка еще не отраженных потерь, ₽ <input inputmode="decimal" name="remaining"
    value="{escape(str(plan['remaining'] if plan.get('remaining') is not None else ''))}"></label>
    <button type="submit">Сохранить план месяца</button></form>
    <p>Бюджет 2% — <strong>{money(result['budget'])}</strong>. Известные списания — <strong>{money(result['known'])}</strong>.
    Разница с бюджетом по загруженным актам — <strong>{money(result['budget_left'])}</strong>.
    Оценка потерь к закрытию месяца — <strong>{money(result['projected_loss'])}</strong>.</p>
    <p>Выручка по чекам за {result['revenue_days']} дн. — {money(result['revenue'])}. Показатели предварительные до сверки
    всех актов пяти групп. Питание сотрудников исключено. Для оценки к закрытию укажите ожидаемую сумму потерь,
    которой пока нет в загруженных актах.</p><details><summary>Известные списания по группам</summary><ul>{groups}</ul></details>
    <p>23.11.2026 — начало работы по заказам программы. Сравнивайте последующие поставки с предыдущим периодом.</p>
    </section>'''
