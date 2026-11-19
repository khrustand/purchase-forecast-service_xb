"""Локальные сценарии бюджета потерь по месяцам."""

import json
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock

from src.infrastructure.app_config import appdata_env_path


_lock = Lock()


def loss_plan_path() -> Path:
    return appdata_env_path().with_name('loss-plans.json')


def load_loss_plans(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def save_loss_plan(path: Path, month: str, revenue: str, remaining: str = '') -> None:
    try:
        month = date.fromisoformat(month + '-01').isoformat()[:7]
        values = [Decimal(value.strip().replace(' ', '').replace(',', '.'))
                  if value.strip() else None for value in (revenue, remaining)]
        if (values[0] is None or values[0] <= 0
                or any(value is not None and not Decimal(0) <= value <= Decimal('1000000000000')
                       for value in values)):
            raise ValueError
    except (ValueError, InvalidOperation):
        raise ValueError('Укажите месяц, положительную выручку и, при наличии, ожидаемые потери в рублях.') from None
    with _lock:
        plans = load_loss_plans(path)
        plans[month] = dict(zip(('revenue', 'remaining'), (round(float(v), 2) if v is not None else None for v in values)))
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as temporary:
            json.dump(plans, temporary, ensure_ascii=False, indent=2)
        temp_path = Path(temporary.name)
        try:
            temp_path.replace(path)
        finally:
            temp_path.unlink(missing_ok=True)
