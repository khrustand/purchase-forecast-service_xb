"""Объединение источников по блюдам; не смешивает порции с упоминаниями в актах."""

import re
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

from scripts.analyze_culinary_strategy import read_xlsx, normalize_name, daily_sales_period
from src.domain.culinary import is_culinary_category
from src.infrastructure.report_formats import decimal_value, waste_lines, receipt_days
from src.domain.loss_budget import loss_group, GROUPS, allocate_loss_budget


def product_key(name: str) -> str:
    key = normalize_name(name)
    for old,new in [('картоф.', 'карт.'), ('сливочным', 'слив.'), ('кисло сладком', 'кисло-сладком')]:
        key = key.replace(old, new)
    key = key.replace('запеченным', 'запеч.')
    return re.sub(r'(\d)г$', r'\1', key)


def load_checks(paths: list[Path]) -> tuple[dict[date, int], int]:
    rows, conflicts = load_receipt_series(paths)
    return {day: row.checks for day,row in rows.items()}, conflicts


def load_receipt_series(paths: list[Path]):
    result = {}
    conflicts = 0
    for path in paths:
        for row in receipt_days(read_xlsx(path)):
            if row.day in result and result[row.day] != row:
                conflicts += 1
            # Перекрывающиеся отчеты не суммируются; первый (более новый) имеет приоритет.
            result.setdefault(row.day, row)
    return result, conflicts


def read_detailed_waste(paths: list[Path]):
    documents = set()
    result = []
    for path in paths:
        lines = waste_lines(read_xlsx(path))
        if not lines:
            continue
        identity = (lines[0].day, lines[0].document)
        if identity not in documents:
            result.extend(lines)
            documents.add(identity)
    return result


def dish_economics(sales_paths: list[Path], waste_paths: list[Path], start: date, end: date) -> dict:
    items = {}
    sale_dates = set()
    for path in sales_paths:
        rows = read_xlsx(path)
        period = daily_sales_period(rows)
        if not period or not start <= period[0] <= end:
            continue
        sale_dates.add(period[0])
        for row in rows[4:]:
            if len(row) < 9 or not row[0] or not row[1] or not is_culinary_category(str(row[0])):
                continue
            key = product_key(str(row[1]))
            item = items.setdefault(key, {'name': str(row[1]), 'sold': Decimal(0), 'revenue': Decimal(0),
                'gross_profit': Decimal(0), 'waste_quantity': Decimal(0), 'waste_cost': Decimal(0),
                'staff_quantity': Decimal(0), 'staff_cost': Decimal(0), 'quantity_known': False,
                'category': str(row[0]), 'sale_dates': set()})
            item['sale_dates'].add(period[0])
            for field,column in [('sold',4),('revenue',6),('gross_profit',8)]:
                item[field] += decimal_value(row[column])
    lines = [line for line in read_detailed_waste(waste_paths) if start <= line.day <= end]
    for line in lines:
        key = product_key(line.name)
        if key not in items and not any(tag in line.account.casefold() for tag in ('ретрит', 'кулинар')):
            continue
        if any(tag in line.account.casefold() for tag in ('снэк', 'сэндвич', 'сандвич')):
            continue
        item = items.setdefault(key, {'name': line.name, 'sold': Decimal(0), 'revenue': Decimal(0),
            'gross_profit': Decimal(0), 'waste_quantity': Decimal(0), 'waste_cost': Decimal(0),
            'staff_quantity': Decimal(0), 'staff_cost': Decimal(0), 'quantity_known': False,
            'category': '', 'sale_dates': set()})
        item['quantity_known'] = True
        if line.unit not in ('порц', 'шт'):
            continue
        prefix = 'staff' if line.staff else 'waste'
        item[prefix + '_quantity'] += line.quantity
        item[prefix + '_cost'] += line.cost
    for key,item in items.items():
        item['key'] = key
        item['active_days'] = len(item.pop('sale_dates'))
        adjusted = item['gross_profit'] - item['waste_cost'] - item['staff_cost']
        item['profit_after_known_costs'] = adjusted
        item['margin_after_known_costs'] = round(float(adjusted / item['revenue'] * 100), 2) if item['revenue'] else None
        for key,value in list(item.items()):
            if isinstance(value, Decimal):
                item[key] = round(float(value), 2)
    return {'start': start.isoformat(), 'end': end.isoformat(),
            'sales_days': len(sale_dates), 'detailed_waste_days': len({r.day for r in lines}),
            'rows': sorted(items.values(), key=lambda item: item['name']),
            'notice': 'Прибыль после известных списаний; неполные акты не означают нулевые потери. Общая цель 2% относится к кулинарии, снекам, выпечке, кондитерке и хлебу совместно. Питание исключено из KPI.'}


def monthly_loss_kpi(economics: dict, receipts: dict, groups: dict | None = None) -> dict:
    start, end = date.fromisoformat(economics['start']), date.fromisoformat(economics['end'])
    records = [row for day,row in receipts.items() if start <= day <= end]
    revenue = sum((row.revenue for row in records), Decimal(0))
    waste = sum(Decimal(str(row['waste_cost'])) for row in economics['rows'])
    expected_days = (end - start).days + 1
    result = {'start': str(start), 'end': str(end), 'total_revenue': float(revenue),
            'known_waste_cost': float(waste), 'target_percent': 2.0,
            'known_percent': round(float(waste / revenue * 100), 3) if revenue > 0 else None,
            'revenue_days': len(records), 'expected_days': expected_days,
            'waste_days': economics['detailed_waste_days'],
            'complete': len(records) == expected_days and economics['detailed_waste_days'] == expected_days,
            'scope': 'all_food_groups',
            'notice': '2% — общий таргет пяти групп, не отдельный лимит кулинарии. Известный вклад кулинарии не равен общим списаниям. Питание исключено. Неполные акты не позволяют подтвердить итог месяца.'}
    if groups is not None:
        budget = allocate_loss_budget(float(revenue), {g: groups[g]['revenue'] for g in GROUPS})
        for row in budget['rows']:
            row.update(known_waste_cost=groups[row['group']]['waste_cost'], waste_days=groups[row['group']]['waste_days'])
            row['known_loss_on_group_revenue_percent'] = round(row['known_waste_cost'] / row['revenue'] * 100, 2) if row['revenue'] and row['waste_days'] else None
        result.update(budget=budget, known_all_groups_waste=sum(groups[g]['waste_cost'] for g in GROUPS),
                      culinary_revenue=groups['culinary']['revenue'])
        result['complete'] = False  # Наличие строк актов не подтверждает полноту всех причин и групп.
    return result


def loss_group_totals(sales_paths: list[Path], waste_paths: list[Path], start: date, end: date) -> dict:
    totals = {g: {'revenue': Decimal(0), 'waste_cost': Decimal(0), 'days': set()} for g in GROUPS}
    products = {}
    for path in sales_paths:
        rows = read_xlsx(path)
        period = daily_sales_period(rows)
        if not period or not start <= period[0] <= end:
            continue
        for row in rows[4:]:
            if len(row) < 9 or not row[0] or not row[1]:
                continue
            group = loss_group(str(row[0]))
            products[product_key(str(row[1]))] = group
            if group:
                totals[group]['revenue'] += decimal_value(row[6])
    for line in read_detailed_waste(waste_paths):
        if line.staff or not start <= line.day <= end:
            continue
        group = products.get(product_key(line.name)) or loss_group(line.account)
        if group:
            totals[group]['waste_cost'] += line.cost
            totals[group]['days'].add(line.day)
    return {g: {'revenue': float(row['revenue']), 'waste_cost': float(row['waste_cost']),
                'waste_days': len(row['days'])} for g,row in totals.items()}


def traffic_history(receipts: dict, as_of: date) -> dict:
    current_year = as_of.year
    months = []
    for month in range(1, as_of.month + 1):
        pairs = []
        for day,row in receipts.items():
            if day.year != current_year or day.month != month or day > as_of:
                continue
            try:
                previous = day.replace(year=current_year - 1)
            except ValueError:
                continue
            if previous in receipts:
                pairs.append((day, receipts[previous].checks, row.checks))
        if not pairs:
            continue
        last, current = sum(r[1] for r in pairs), sum(r[2] for r in pairs)
        months.append({'month': month, 'paired_days': len(pairs), 'last_year_checks': last,
                       'current_checks': current, 'change_percent': round((current / last - 1) * 100, 1) if last else None})
    previous = [{'date': str(day), 'checks': row.checks, 'revenue': float(row.revenue)}
                for day,row in sorted(receipts.items()) if day.year == current_year - 1]
    return {'year': current_year, 'previous_year': current_year - 1, 'months': months, 'previous_daily': previous}
