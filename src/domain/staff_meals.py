"""Подтвержденные исключения питания; фактический выбор не назначается заранее."""
import re
from typing import Mapping


def staff_meal_allowed(name: str) -> bool:
    normalized = re.sub(r'^\d+\s+', '', name.casefold().replace('*','').strip())
    return not normalized.startswith(('онигири', 'темаки'))


def eligible_staff_demand(demand: Mapping[str, float]) -> dict[str, float]:
    return {name: quantity if staff_meal_allowed(name) else 0 for name,quantity in demand.items()}
