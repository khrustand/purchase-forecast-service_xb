"""Прогноз потока по числу чеков с сопоставлением одинаковых дней недели."""

from datetime import date, timedelta
from typing import Mapping, Iterable


def traffic_adjustment(checks: Mapping[date, int], sale_days: Iterable[date], target: date, cutoff: date) -> dict:
    recent = sorted((d for d in checks if d < cutoff and d.weekday() == target.weekday()), reverse=True)[:4]
    base_days = [d for d in sale_days if d < cutoff and d in checks and d.weekday() == target.weekday()]
    expected = sum(checks[d] for d in recent) / len(recent) if recent else None
    recent_expected = expected
    last_year_day = target - timedelta(days=364)
    paired = [d for d in recent if d - timedelta(days=364) in checks]
    last_year_recent = sum(checks[d - timedelta(days=364)] for d in paired)
    yoy_scale = (sum(checks[d] for d in paired) / last_year_recent
                 if len(paired) >= 3 and last_year_recent > 0 else None)
    last_year_checks = checks.get(last_year_day) if last_year_day < cutoff else None
    seasonal_expected = last_year_checks * yoy_scale if last_year_checks is not None and yoy_scale is not None else None
    if seasonal_expected is not None and expected is not None:
        expected = .5 * expected + .5 * seasonal_expected
    baseline = sum(checks[d] for d in base_days) / len(base_days) if base_days else None
    enough = len(recent) >= 2 and len(base_days) >= 2 and baseline and baseline > 0
    factor = max(.7, min(1.3, expected / baseline)) if enough else 1.0
    return {'factor': round(factor, 4), 'expected_checks': round(expected) if expected is not None else None,
            'recent_expected_checks': round(recent_expected) if recent_expected is not None else None,
            'last_year_date': last_year_day.isoformat(), 'last_year_checks': last_year_checks,
            'yoy_scale': round(yoy_scale, 4) if yoy_scale is not None else None,
            'seasonal_expected_checks': round(seasonal_expected) if seasonal_expected is not None else None,
            'seasonality_applied': seasonal_expected is not None,
            'baseline_checks': round(baseline) if baseline is not None else None,
            'history_points': len(recent), 'applied': bool(enough)}


def allocate_staff(demand: Mapping[str, float], portions: int = 5, balance: dict[str, float] | None = None) -> dict[str, int]:
    """Распределить общий план питания без добавления пяти порций к каждому SKU."""
    positive = {key: max(0, value) for key,value in demand.items()}
    total = sum(positive.values())
    result = {key: 0 for key in demand}
    if not total:
        return result
    credit = balance if balance is not None else {}
    for key,value in positive.items():
        credit[key] = credit.get(key, 0) + portions * value / total
    for _ in range(portions):
        key = max((k for k in positive if positive[k] > 0), key=lambda k: (credit[k], positive[k], k))
        result[key] += 1
        credit[key] -= 1
    return result
