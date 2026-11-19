"""Financial display of an order without changing its quantities."""
from html import escape


def order_financials(item: dict) -> dict:
    model = item.get('model', {})
    price, cost = model.get('price'), model.get('cost')
    quantity = None if item.get('quantity_unknown') else item.get('forecast_quantity')
    priced = price is not None and cost is not None and price > 0 and 0 < cost <= price
    unit_margin = price - cost if priced else None
    expected_revenue = price * model['expected_guest_sales'] if price is not None and model.get('expected_guest_sales') is not None else None
    profit = model.get('expected_profit')
    return {'price': price, 'cost': cost,
            'retail_value': price * quantity if price is not None and quantity is not None else None,
            'unit_margin': unit_margin,
            'unit_margin_percent': unit_margin / price * 100 if priced else None,
            'expected_revenue': expected_revenue, 'expected_margin': profit,
            'expected_margin_percent': profit / expected_revenue * 100 if profit is not None and expected_revenue else None}


def _money(value) -> str:
    return f'{value:,.2f}'.replace(',', ' ') if value is not None else 'нет данных'


def finance_cells(item: dict) -> str:
    values = order_financials(item)
    unit_percent = f"{values['unit_margin_percent']:.1f}%" if values['unit_margin_percent'] is not None else '—'
    plan_percent = f"{values['expected_margin_percent']:.1f}%" if values['expected_margin_percent'] is not None else '—'
    return (f"<td class='number order-finance'>{_money(values['price'])}</td>"
            f"<td class='number order-finance'>{_money(values['retail_value'])}</td>"
            f"<td class='number order-finance'>{_money(values['unit_margin'])}<small>{unit_percent}</small></td>"
            f"<td class='number order-finance'>{_money(values['expected_margin'])}<small>{plan_percent}</small></td>")


def finance_details(item: dict) -> str:
    values = order_financials(item)
    return (f"<section><h3>Цена и маржа</h3><dl><dt>Цена продажи порции</dt><dd>{_money(values['price'])} ₽</dd>"
            f"<dt>Себестоимость порции</dt><dd>{_money(values['cost'])} ₽</dd>"
            f"<dt>Все порции в розничных ценах</dt><dd>{_money(values['retail_value'])} ₽</dd>"
            f"<dt>Ожидаемая выручка гостей</dt><dd>{_money(values['expected_revenue'])} ₽</dd>"
            f"<dt>Маржа плана после риска остатка и питания</dt><dd>{_money(values['expected_margin'])} ₽</dd></dl>"
            "<p>Цена и себестоимость — средние из последнего месяца продаж. Маржа порции = цена − себестоимость. "
            "Стоимость всех порций в розничных ценах включает питание и не равна плановой выручке. "
            "Маржа плана = цена × ожидаемые продажи гостям − себестоимость × все порции, включая питание. "
            "Непроданный остаток уже учтен в стоимости всего выпуска и повторно не вычитается. "
            "Аренда и зарплата не включены. Это модельная оценка, не гарантированный результат.</p></section>")


def assortment_status(item: dict) -> tuple[str, str]:
    if item.get('is_experiment') or item.get('matrix_role') == 'experiment':
        return 'Тест', 'trial'
    return {'core': ('Основное меню', 'core'), 'rotation': ('Ротация', 'rotation')}.get(
        item.get('matrix_role'), ('В работе', 'unknown'))


def status_explanation(item: dict) -> str:
    _, role = assortment_status(item)
    return {
        'core': 'Блюдо включено в постоянную часть текущей матрицы по спросу и экономике после известных потерь. Роль не доказывает статистическую стабильность продаж.',
        'rotation': 'Блюдо включено в сменную часть текущей матрицы. Кандидат для чередования ассортимента с учетом спроса и маржи после известных потерь.',
        'trial': 'Пробная позиция без подтвержденной истории. Тестовый объем — 3 порции на поставку. Это не утверждение о дате появления блюда в меню; риск и прибыль без данных не выдумываются.',
        'unknown': 'Роль в текущей матрице не определена. Нельзя автоматически считать это блюдо новинкой или позицией со стабильным спросом.',
    }[role] + ' Статус описывает роль в меню, а не коэффициент увеличения или уменьшения заказа.'


def status_details(item: dict) -> str:
    label, _ = assortment_status(item)
    return f'<section><h3>Роль в меню: {label}</h3><p>{escape(status_explanation(item))}</p></section>'


def order_totals(rows: list[dict], dates: list[str]) -> dict:
    """Aggregate additive quantities and money, preserving incomplete coverage."""
    def quantity(row):
        return None if row.get('quantity_unknown') else row.get('forecast_quantity')

    def aggregate(values):
        known = [value for value in values if value is not None]
        return {'value': sum(known) if known or not values else None, 'known': len(known), 'missing': len(values)-len(known)}

    daily = []
    for index, day in enumerate(dates):
        values = []
        for row in rows:
            entry = next((d for d in row.get('daily_forecast', []) if d['date'] == day), {})
            unknown = row.get('quantity_unknown') and index < int(row.get('shelf_life_days', len(dates)))
            values.append(None if unknown else entry.get('quantity'))
        daily.append(aggregate(values))
    finances = [order_financials(row) for row in rows]
    return {'daily': daily, 'quantity': aggregate([quantity(row) for row in rows]),
            'retail_value': aggregate([0 if quantity(row) == 0 else f['retail_value'] for row,f in zip(rows,finances)]),
            'expected_margin': aggregate([0 if quantity(row) == 0 else f['expected_margin'] for row,f in zip(rows,finances)]),
            'rows': len(rows)}


def _total_cell(total: dict, money: bool = False) -> str:
    value = _money(total['value']) if money else (str(total['value']) if total['value'] is not None else 'нет данных')
    coverage = f"<small>неполный итог: без {total['missing']} поз.</small>" if total['missing'] else ''
    return f"<td class='number'><strong>{value}</strong>{coverage}</td>"


def render_order_totals(totals: dict) -> str:
    cells = ''.join(_total_cell(day) for day in totals['daily'])
    return ("<tfoot><tr class='order-summary'><th scope='row'>Итого к поставке</th>" + cells
            + _total_cell(totals['quantity']) + '<td>—</td>' + _total_cell(totals['retail_value'], True)
            + '<td>—</td>' + _total_cell(totals['expected_margin'], True) + '<td></td><td></td></tr></tfoot>')
