"""Общий расчет спроса, резерва и риска для ТТ и поставляемой кулинарии.

Наблюдаемые продажи — приближение спроса: отсутствие наличия не восстановлено.
Функции не читают файлы, не округляют до партий и не выдают остаток за списание.
"""

from datetime import date, timedelta
from math import ceil, floor
from typing import Mapping, Sequence

DEFAULT_SERVICE_LEVEL = .85
DEFAULT_PROFIT_TOLERANCE = .05
HISTORY_DAYS = 56


def recent_history(history: Mapping[date, float], cutoff: date) -> dict[date, float]:
    observed = {d: max(0., float(q)) for d, q in history.items() if d < cutoff}
    recent = {d: q for d, q in observed.items() if d >= cutoff - timedelta(days=HISTORY_DAYS)}
    return recent or observed


def demand_samples(history: Mapping[date, float], days: Sequence[date], cutoff: date) -> tuple[list[list[float]], str]:
    observed = recent_history(history, cutoff)
    if not observed or not days:
        return [], 'нет наблюдений'
    anchors = sorted((d for d in observed if d.weekday() == days[0].weekday()), reverse=True)
    windows = []
    for anchor in anchors:
        window = [anchor + (day - days[0]) for day in days]
        if all(d in observed for d in window):
            windows.append([observed[d] for d in window])
    if len(windows) >= 3:
        return windows[:8], 'сопоставимые календарные окна'
    # Разреженные данные не превращаем в нулевые продажи. Сборные окна не
    # позволяют утверждать, что междневная зависимость достоверно восстановлена.
    pools = []
    for day in days:
        matching = sorted((d for d in observed if d.weekday() == day.weekday()), reverse=True)
        chosen = matching[:8] or sorted(observed, reverse=True)[:8]
        pools.append([observed[d] for d in chosen])
    count = min(len(pool) for pool in pools)
    return [[pool[i] for pool in pools] for i in range(count)], 'разреженная история: сборные окна'


def _quantile(values: list[float], weights: list[float], probability: float) -> float:
    accumulated = 0.
    for value, weight in sorted(zip(values, weights)):
        accumulated += weight
        if accumulated + 1e-12 >= probability:
            return value
    return max(values)


def distribute_quantity(quantity: int, weights: Sequence[float]) -> list[int]:
    if not weights:
        return []
    positive = [max(0., w) for w in weights]
    total = sum(positive)
    fractions = [quantity * w / total for w in positive] if total else [quantity / len(weights)] * len(weights)
    result = [floor(value) for value in fractions]
    for i in sorted(range(len(result)), key=lambda i: (fractions[i] - result[i], -i), reverse=True)[:quantity - sum(result)]:
        result[i] += 1
    return result


def plan_demand(history: Mapping[date, float], days: Sequence[date], cutoff: date,
                staff: Sequence[int], factors: Sequence[float], price: float | None = None,
                cost: float | None = None, service_level: float = DEFAULT_SERVICE_LEVEL,
                trial_quantity: int | None = None,
                profit_tolerance: float = DEFAULT_PROFIT_TOLERANCE) -> dict:
    if not 0 < service_level < 1:
        raise ValueError('Уровень защиты спроса должен быть больше 0 и меньше 100%.')
    if not 0 <= profit_tolerance <= 1:
        raise ValueError('Допустимая цена резерва должна быть от 0 до 100% результата.')
    if len(days) != len(staff) or len(days) != len(factors) or not days:
        raise ValueError('Даты, питание и коэффициенты должны иметь одинаковую ненулевую длину.')
    if any(q < 0 for q in staff) or any(f < 0 for f in factors):
        raise ValueError('Питание и коэффициенты не могут быть отрицательными.')
    samples, basis = demand_samples(history, days, cutoff)
    unknown = {'quantity': None, 'guest_quantity': None, 'expected_demand': None,
               'reserve': None, 'economic_quantity': None, 'service_quantity': None,
               'expected_remaining': None, 'expected_shortage': None, 'stockout_probability': None,
               'expected_profit': None, 'expected_remaining_cost': None, 'expected_lost_margin': None,
               'availability_cost': None, 'availability_cost_limit': None,
               'limited_by_profit': False, 'service_target_met': False,
               'alternatives': [], 'sensitivity': [], 'history_points': 0,
               'service_level': service_level, 'basis': basis, 'daily': [], 'price': price, 'cost': cost}
    if trial_quantity is not None:
        quantities = distribute_quantity(trial_quantity, [1.] * len(days))
        return {**unknown, 'quantity': trial_quantity + sum(staff), 'guest_quantity': trial_quantity,
                'basis': 'тестовый объем, спрос не установлен', 'daily': [
                    {'date': str(d), 'quantity': q + e, 'guest_quantity': q, 'staff_quantity': e}
                    for d, q, e in zip(days, quantities, staff)]}
    if not samples:
        return unknown
    samples = [[q * factor for q, factor in zip(sample, factors)] for sample in samples]
    raw_weights = [.85 ** i for i in range(len(samples))]
    weights = [w / sum(raw_weights) for w in raw_weights]
    totals = [sum(sample) for sample in samples]
    mean = sum(q * w for q, w in zip(totals, weights))
    priced = price is not None and cost is not None and price > 0 and 0 < cost <= price

    def outcomes(q: int, uplift: float = 1.) -> dict:
        remaining = sum(max(0., q - d * uplift) * w for d, w in zip(totals, weights))
        shortage = sum(max(0., d * uplift - q) * w for d, w in zip(totals, weights))
        sold = sum(min(q, d * uplift) * w for d, w in zip(totals, weights))
        risk = sum(w for d, w in zip(totals, weights) if d * uplift > q + 1e-9)
        return {'expected_remaining': remaining, 'expected_shortage': shortage,
                'stockout_probability': risk, 'expected_guest_sales': sold,
                'expected_profit': sold * price - (q + sum(staff)) * cost if priced else None,
                'expected_remaining_cost': remaining * cost if priced else None,
                'expected_lost_margin': shortage * (price - cost) if priced else None}

    # При нулевой стоимости непроданного остатка: порог p(D>Q) >= c/p.
    # Выбираем первый целый Q с максимальной ожидаемой прибылью, без
    # повторного вычитания себестоимости непроданного в самой прибыли.
    economic = None
    if priced:
        critical = _quantile(totals, weights, (price - cost) / price) if price > cost else 0
        economic = max({floor(critical), ceil(critical)}, key=lambda q: (outcomes(q)['expected_profit'], -q))
    service = ceil(_quantile(totals, weights, service_level))
    guest = max(economic or 0, service)
    optimum_profit = outcomes(economic)['expected_profit'] if economic is not None else None
    cost_limit = max(0., optimum_profit) * profit_tolerance if priced else None
    if priced:
        guest = economic
        for candidate in range(economic + 1, max(service, economic) + 1):
            if optimum_profit - outcomes(candidate)['expected_profit'] <= cost_limit + 1e-9:
                guest = candidate
            else:
                break
    results = outcomes(guest)
    daily_mean = [sum(sample[i] * w for sample, w in zip(samples, weights)) for i in range(len(days))]
    allocation = distribute_quantity(guest, daily_mean)
    return {**unknown, **{key: round(value, 4) if value is not None else None for key, value in results.items()},
            'quantity': guest + sum(staff), 'guest_quantity': guest, 'expected_demand': round(mean, 4),
            'reserve': max(0, guest - ceil(mean)), 'change_from_mean': guest - ceil(mean),
            'economic_quantity': economic, 'service_quantity': service,
            'availability_cost': round(optimum_profit - results['expected_profit'], 2) if priced else None,
            'availability_cost_limit': round(cost_limit, 2) if priced else None,
            'limited_by_profit': guest < service,
            'service_target_met': guest >= service,
            'alternatives': [{'policy': policy, 'quantity': q + sum(staff) if q is not None else None,
                              **{key: round(value, 4) if value is not None else None
                                 for key, value in outcomes(q).items()}}
                             for policy, q in [('economic', economic), ('availability', max(economic or 0, service))]
                             if q is not None],
            'history_points': len(samples), 'basis': basis,
            'daily': [{'date': str(d), 'quantity': q + e, 'guest_quantity': q, 'staff_quantity': e,
                       'expected_demand': round(m, 4)} for d, q, e, m in zip(days, allocation, staff, daily_mean)],
            'sensitivity': [{'demand_uplift_percent': percent,
                             **{key: round(value, 4) if value is not None else None
                                for key, value in outcomes(guest, 1 + percent / 100).items()}}
                            for percent in (10, 20)]}
