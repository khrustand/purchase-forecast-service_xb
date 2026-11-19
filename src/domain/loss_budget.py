"""Распределение общего бюджета потерь между товарными группами."""

GROUPS = ('culinary', 'snacks', 'bakery', 'desserts', 'bread')
GROUP_LABELS = dict(zip(GROUPS, ('Кулинария и ТТ', 'Снеки', 'Выпечка', 'Кондитерка', 'Хлеб')))


def loss_group(category: str) -> str | None:
    key = category.casefold().strip()
    if 'кулинар' in key or 'ретрит' in key:
        return 'culinary'
    if any(tag in key for tag in ('снэк', 'снек', 'сэндвич', 'сандвич', 'фокач', 'тортиль')):
        return 'snacks'
    if 'хлеб' in key:
        return 'bread'
    if any(tag in key for tag in ('кондитер', 'торт', 'песоч', 'мелкоштуч', 'пирожн')):
        return 'desserts'
    if any(tag in key for tag in ('слоен', 'слойк', 'сдоб', 'выпеч')):
        return 'bakery'
    return None


def allocate_loss_budget(total_revenue: float, group_revenues: dict[str, float], target_percent: float = 2.0) -> dict:
    eligible_revenue = sum(max(0, group_revenues.get(group, 0)) for group in GROUPS)
    total_budget = max(0, total_revenue) * target_percent / 100
    rows = []
    allocated = 0.
    for group in GROUPS:
        revenue = max(0, group_revenues.get(group, 0))
        budget = round(total_budget * revenue / eligible_revenue, 2) if eligible_revenue > 0 else None
        if budget is not None:
            allocated += budget
        rows.append({'group': group, 'label': GROUP_LABELS[group], 'revenue': round(revenue, 2),
                     'target_cost': budget,
                     'target_on_group_revenue_percent': round(budget / revenue * 100, 3) if budget is not None and revenue > 0 else None,
                     'target_contribution_percent': round(budget / total_revenue * 100, 3) if budget is not None and total_revenue > 0 else None})
    # Сохраняем общий бюджет с точностью до копейки после независимого округления долей.
    if eligible_revenue > 0:
        largest = max(rows, key=lambda row: row['revenue'])
        largest['target_cost'] = round(largest['target_cost'] + round(total_budget - allocated, 2), 2)
    return {'target_percent': target_percent, 'total_budget': round(total_budget, 2),
            'eligible_revenue': round(eligible_revenue, 2), 'rows': rows,
            'method': 'Предварительное распределение общего бюджета 2% пропорционально выручке пяти групп. Это управленческий ориентир, а не оптимум, рассчитанный по полной истории потерь.'}
