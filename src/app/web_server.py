from __future__ import annotations

import json
import os
import base64
import hmac
from email import policy
from email.parser import BytesParser
from html import escape
from datetime import date, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from src.app.cli import load_purchase_items
from src.domain.planning import build_purchase_calendar, estimate_calendar_budget
from scripts.analyze_culinary_strategy import (
    build_daily_menu,
    build_recommendations,
    daily_menu_summary,
    extract_items,
    extract_shelf_life,
    extract_waste_counts,
    normalize_name,
    parse_datetime,
    read_xlsx,
    waste_leaders,
)
from src.infrastructure.report_storage import (
    ALLOWED_REPORT_TYPES,
    MAX_UPLOAD_BYTES,
    ReportValidationError,
    create_report_storage,
)
from src.infrastructure.app_config import (
    AppConfigError,
    appdata_env_path,
    has_database_config,
    write_appdata_env,
)
from src.infrastructure.paths import project_path
from src.infrastructure.weather import load_met_norway_forecast


DEFAULT_ITEMS_PATH = project_path("data/examples/purchase_items.json")
DEFAULT_SALES_PATH = project_path("data/local/culinary_sales_june_july.xlsx")
DEFAULT_WASTE_PATH = project_path("data/local/culinary_waste_june_july.xlsx")
DEFAULT_SHELF_LIFE_PATH = project_path("data/local/Хранение и сроки годности, реализации.xlsx")
DEFAULT_ORDER_CYCLE_DAYS = 2
REPORT_STORAGE = create_report_storage()
WEEKDAY_LABELS = {0: "ПН", 1: "ВТ", 2: "СР", 3: "ЧТ", 4: "ПТ", 5: "СБ", 6: "ВС"}


def _weather_day(summary: str, temperature: int, rain: bool = False) -> dict[str, object]:
    return {"summary": summary, "temperature": temperature, "rain": rain}


WEATHER_BY_DATE = {
    date(2026, 6, 1): _weather_day("переменная облачность, до +19", 19),
    date(2026, 6, 2): _weather_day("переменная облачность, до +16", 16),
    date(2026, 6, 3): _weather_day("переменная облачность, до +22", 22),
    date(2026, 6, 4): _weather_day("малооблачно, до +23", 23),
    date(2026, 6, 5): _weather_day("облачно с прояснениями, до +23", 23),
    date(2026, 6, 6): _weather_day("ясно, до +22", 22),
    date(2026, 6, 7): _weather_day("переменная облачность, до +24", 24),
    date(2026, 6, 8): _weather_day("небольшая облачность, до +27", 27),
    date(2026, 6, 9): _weather_day("небольшая облачность, до +27", 27),
    date(2026, 6, 10): _weather_day("переменная облачность, до +28", 28),
    date(2026, 6, 11): _weather_day("переменная облачность, до +29", 29),
    date(2026, 6, 12): _weather_day("переменная облачность, до +30", 30),
    date(2026, 6, 13): _weather_day("переменная облачность, до +29", 29),
    date(2026, 6, 14): _weather_day("слабый ливневый дождь, до +14", 14, True),
    date(2026, 6, 15): _weather_day("облачно с прояснениями, до +22", 22),
    date(2026, 6, 16): _weather_day("переменная облачность, до +15", 15),
    date(2026, 6, 17): _weather_day("облачно с прояснениями, до +17", 17),
    date(2026, 6, 18): _weather_day("переменная облачность, до +15", 15),
    date(2026, 6, 19): _weather_day("облачно с прояснениями, до +21", 21),
    date(2026, 6, 20): _weather_day("облачно с прояснениями, до +19", 19),
    date(2026, 6, 21): _weather_day("ясно, до +22", 22),
    date(2026, 6, 22): _weather_day("гроза, до +20", 20, True),
    date(2026, 6, 23): _weather_day("ясно, до +22", 22),
    date(2026, 6, 24): _weather_day("переменная облачность, до +20", 20),
    date(2026, 6, 25): _weather_day("переменная облачность, до +15", 15),
    date(2026, 6, 26): _weather_day("небольшая облачность, до +19", 19),
    date(2026, 6, 27): _weather_day("переменная облачность, до +20", 20),
    date(2026, 6, 28): _weather_day("облачно с прояснениями, до +21", 21),
    date(2026, 6, 29): _weather_day("облачно с прояснениями, до +21", 21),
    date(2026, 6, 30): _weather_day("переменная облачность, до +24", 24),
    date(2026, 7, 1): _weather_day("переменная облачность, до +27", 27),
    date(2026, 7, 2): _weather_day("переменная облачность, до +29", 29),
    date(2026, 7, 3): _weather_day("переменная облачность, до +24", 24),
    date(2026, 7, 4): _weather_day("сильный ливневый дождь, до +19", 19, True),
    date(2026, 7, 5): _weather_day("переменная облачность, до +19", 19),
    date(2026, 7, 6): _weather_day("облачно с прояснениями, до +21", 21),
    date(2026, 7, 7): _weather_day("ливневый дождь, до +19", 19, True),
    date(2026, 7, 8): _weather_day("ливневый дождь, до +21", 21, True),
    date(2026, 7, 9): _weather_day("слабый ливневый дождь, до +18", 18, True),
    date(2026, 7, 10): _weather_day("переменная облачность, до +24", 24),
    date(2026, 7, 11): _weather_day("переменная облачность, до +28", 28),
    date(2026, 7, 12): _weather_day("ливневый дождь, до +19", 19, True),
    date(2026, 7, 13): _weather_day("переменная облачность, до +21", 21),
    date(2026, 7, 14): _weather_day("облачно с прояснениями, до +23", 23),
    date(2026, 7, 15): _weather_day("переменная облачность, до +20", 20),
    date(2026, 7, 16): _weather_day("облачность с просветами, до +18", 18),
    date(2026, 7, 17): _weather_day("ясно, до +18", 18),
    date(2026, 7, 18): _weather_day("ясно, до +23", 23),
    date(2026, 7, 19): _weather_day("ясно, до +25", 25),
    date(2026, 7, 20): _weather_day("ясно, до +27", 27),
    date(2026, 7, 21): _weather_day("облачно, небольшой дождь, до +22", 22, True),
    date(2026, 7, 22): _weather_day("переменная облачность, небольшой дождь, до +22", 22, True),
    date(2026, 7, 23): _weather_day("переменная облачность, до +18", 18),
    date(2026, 7, 24): _weather_day("облачно, небольшой дождь, до +23", 23, True),
    date(2026, 7, 25): _weather_day("переменная облачность, до +25", 25),
    date(2026, 7, 26): _weather_day("облачно, дождь, до +22", 22, True),
    date(2026, 7, 27): _weather_day("переменная облачность, дождь, гроза, до +26", 26, True),
    date(2026, 7, 28): _weather_day("облачно, небольшой дождь, до +26", 26, True),
    date(2026, 7, 29): _weather_day("переменная облачность, до +29", 29),
    date(2026, 7, 30): _weather_day("переменная облачность, дождь, гроза, до +25", 25, True),
    date(2026, 7, 31): _weather_day("тепло, до +27", 27),
    date(2026, 8, 1): _weather_day("жарко, до +30", 30),
    date(2026, 8, 2): _weather_day("жарко, до +30", 30),
    date(2026, 8, 3): _weather_day("жарко, до +31", 31),
    date(2026, 8, 4): _weather_day("тепло, грозы, до +29", 29, True),
    date(2026, 8, 5): _weather_day("умеренно тепло, до +22", 22),
    date(2026, 8, 6): _weather_day("умеренно тепло, до +22", 22),
    date(2026, 8, 7): _weather_day("умеренно тепло, до +23", 23),
    date(2026, 8, 8): _weather_day("прохладнее, до +21", 21),
    date(2026, 8, 9): _weather_day("тепло, до +24", 24),
    date(2026, 8, 10): _weather_day("тепло, вечером дождь, до +25", 25, True),
}

WEATHER_BY_DATE = {
    date(2026, 6, 1): _weather_day("облачность 47%, до +16", 16),
    date(2026, 6, 2): _weather_day("облачность 32%, до +19.5", 20),
    date(2026, 6, 3): _weather_day("облачность 36%, до +20.5", 21),
    date(2026, 6, 4): _weather_day("осадки 1 мм, до +21.5", 22, True),
    date(2026, 6, 5): _weather_day("облачность 29%, до +25", 25),
    date(2026, 6, 6): _weather_day("осадки 1 мм, до +24.5", 25, True),
    date(2026, 6, 7): _weather_day("облачность 32%, до +21", 21),
    date(2026, 6, 8): _weather_day("облачность 40%, до +21.5", 22),
    date(2026, 6, 9): _weather_day("осадки 3 мм, до +25", 25, True),
    date(2026, 6, 10): _weather_day("облачность 71%, до +19.5", 20),
    date(2026, 6, 11): _weather_day("облачность 40%, до +19", 19),
    date(2026, 6, 12): _weather_day("облачность 46%, до +19", 19),
    date(2026, 6, 13): _weather_day("осадки 1 мм, до +20", 20, True),
    date(2026, 6, 14): _weather_day("облачность 49%, до +19.5", 20),
    date(2026, 6, 15): _weather_day("осадки 3 мм, до +20", 20, True),
    date(2026, 6, 16): _weather_day("облачность 69%, до +17.5", 18),
    date(2026, 6, 17): _weather_day("осадки 7 мм, до +12", 12, True),
    date(2026, 6, 18): _weather_day("осадки 1 мм, до +13.5", 14, True),
    date(2026, 6, 19): _weather_day("облачность 41%, до +19.5", 20),
    date(2026, 6, 20): _weather_day("облачность 30%, до +21.5", 22),
    date(2026, 6, 21): _weather_day("облачность 39%, до +24", 24),
    date(2026, 6, 22): _weather_day("облачность 15%, до +24", 24),
    date(2026, 6, 23): _weather_day("облачность 33%, до +18", 18),
    date(2026, 6, 24): _weather_day("осадки 1 мм, до +12", 12, True),
    date(2026, 6, 25): _weather_day("облачность 39%, до +20", 20),
    date(2026, 6, 26): _weather_day("облачность 54%, до +19", 19),
    date(2026, 6, 27): _weather_day("облачность 91%, до +19", 19),
    date(2026, 6, 28): _weather_day("облачность 21%, до +24.5", 25),
    date(2026, 6, 29): _weather_day("облачность 67%, до +23", 23),
    date(2026, 6, 30): _weather_day("облачность 33%, до +23.5", 24),
    date(2026, 7, 1): _weather_day("облачность 20%, до +25.5", 26),
    date(2026, 7, 2): _weather_day("осадки 5 мм, до +14", 14, True),
    date(2026, 7, 3): _weather_day("облачность 74%, до +18.5", 19),
    date(2026, 7, 4): _weather_day("осадки 3 мм, до +21", 21, True),
    date(2026, 7, 5): _weather_day("осадки 6 мм, до +19", 19, True),
    date(2026, 7, 6): _weather_day("осадки 2 мм, до +17", 17, True),
    date(2026, 7, 7): _weather_day("осадки 1 мм, до +16", 16, True),
    date(2026, 7, 8): _weather_day("облачность 65%, до +19.5", 20),
    date(2026, 7, 9): _weather_day("облачность 67%, до +19.5", 20),
    date(2026, 7, 10): _weather_day("облачность 59%, до +23.5", 24),
    date(2026, 7, 11): _weather_day("осадки 1 мм, до +28.5", 29, True),
    date(2026, 7, 12): _weather_day("облачность 23%, до +28.5", 29),
    date(2026, 7, 13): _weather_day("облачность 19%, до +26", 26),
    date(2026, 7, 14): _weather_day("облачность 13%, до +22", 22),
    date(2026, 7, 15): _weather_day("облачность 25%, до +23", 23),
    date(2026, 7, 16): _weather_day("облачность 8%, до +19.5", 20),
    date(2026, 7, 17): _weather_day("облачность 16%, до +23", 23),
    date(2026, 7, 18): _weather_day("облачность 5%, до +26", 26),
    date(2026, 7, 19): _weather_day("облачность 48%, до +20.5", 21),
    date(2026, 7, 20): _weather_day("облачность 60%, до +17.5", 18),
    date(2026, 7, 21): _weather_day("осадки 5 мм, до +12", 12, True),
    date(2026, 7, 22): _weather_day("облачность 84%, до +18.5", 19),
    date(2026, 7, 23): _weather_day("облачность 49%, до +18.5", 19),
    date(2026, 7, 24): _weather_day("осадки 1 мм, до +21.5", 22, True),
    date(2026, 7, 25): _weather_day("облачность 26%, до +21.5", 22),
    date(2026, 7, 26): _weather_day("облачность 38%, до +23.5", 24),
    date(2026, 7, 27): _weather_day("облачность 36%, до +26.5", 27),
    date(2026, 7, 28): _weather_day("осадки 1 мм, до +18.5", 19, True),
    date(2026, 7, 29): _weather_day("облачность 30%, до +21", 21),
    date(2026, 7, 30): _weather_day("облачность 5%, до +23", 23),
    date(2026, 7, 31): _weather_day("облачность 5%, до +26.5", 27),
    date(2026, 8, 1): _weather_day("дождь, до +27", 27, True),
    date(2026, 8, 2): _weather_day("облачно, до +23", 23),
    date(2026, 8, 3): _weather_day("дождь, до +22", 22, True),
    date(2026, 8, 4): _weather_day("облачно, до +18", 18),
    date(2026, 8, 5): _weather_day("дождь, до +18", 18, True),
    date(2026, 8, 6): _weather_day("облачно, до +18", 18),
    date(2026, 8, 7): _weather_day("облачно, до +19", 19),
    date(2026, 8, 8): _weather_day("облачно, до +20", 20),
    date(2026, 8, 9): _weather_day("облачно, до +17", 17),
    date(2026, 8, 10): _weather_day("дождь, до +15", 15, True),
    date(2026, 8, 11): _weather_day("статистический прогноз, до +21", 21),
    date(2026, 8, 12): _weather_day("статистический прогноз, до +21", 21),
    date(2026, 8, 13): _weather_day("статистический прогноз, до +21", 21),
    date(2026, 8, 19): _weather_day("сильный дождь, до +16.5", 17, True),
    date(2026, 8, 20): _weather_day("облачно, до +18.6", 19),
    date(2026, 8, 21): _weather_day("небольшой дождь, до +20.1", 20, True),
    date(2026, 8, 22): _weather_day("небольшой дождь, до +20.3", 20, True),
    date(2026, 8, 23): _weather_day("дождь, до +17.7", 18, True),
    date(2026, 8, 24): _weather_day("ливень, до +17.7", 18, True),
}

CATEGORY_LABELS = {
    "lunches": "Обеды",
    "salads": "Салаты",
    "rolls": "Роллы",
    "hot_meals": "Горячие блюда",
}

ITEM_LABELS = {
    "chicken lunch": "Обед с курицей",
    "caesar salad": "Салат Цезарь",
    "chicken roll": "Ролл с курицей",
    "soup of the day": "Суп дня",
    "pasta with chicken": "Паста с курицей",
}

UNIT_LABELS = {
    "pcs": "шт.",
}


def build_dashboard_payload(
    items_path: Path = DEFAULT_ITEMS_PATH,
    start_day: date | None = None,
    horizon_days: int = 14,
) -> dict[str, Any]:
    start = start_day or date.today()
    items = load_purchase_items(items_path)
    events = build_purchase_calendar(items, start, horizon_days)
    budget = estimate_calendar_budget(events)

    return {
        "generated_at": date.today().isoformat(),
        "start_day": start.isoformat(),
        "horizon_days": horizon_days,
        "order_cycle_days": DEFAULT_ORDER_CYCLE_DAYS,
        "budget": _localize_budget(budget),
        "budget_total": sum(budget.values()),
        "events": [
            {
                "day": event.day.isoformat(),
                "item_name": _item_label(event.item_name),
                "category": _category_label(event.category),
                "quantity": event.quantity,
                "unit": _unit_label(event.unit),
                "estimated_price": event.estimated_price,
            }
            for event in events
        ],
        "forecast_logic": [
            "берем продажи и списания за последние периоды по каждой позиции",
            "считаем средний спрос на 2 дня и добавляем страховой запас",
            "вычитаем текущий остаток и подтвержденные поставки",
            "округляем заказ до кратности поставщика или производственной партии",
            "помечаем позиции с риском нехватки, списаний или нехваткой истории",
        ],
        "demand_factors": {
            "status": "демо-логика",
            "summary": "Погода и день недели пока не подключены к расчету автоматически.",
            "effect": "Холод и дождь могут поднимать спрос на супы и горячие обеды; жара чаще смещает спрос в салаты и роллы. После твоих выгрузок эти коэффициенты лучше считать по факту продаж.",
        },
        "next_data": [
            "список позиций кулинарии: SKU, название, категория, себестоимость, срок годности",
            "заказы и продажи за последние периоды по дням",
            "остатки перед заказом и фактические списания",
            "кратность заказа или производственной партии",
            "пометки по дням: будни, выходные, погода, акции, локальные события",
        ],
        "culinary_strategy": build_culinary_strategy_payload(reference_day=start - timedelta(days=1)),
    }


def build_culinary_strategy_payload(
    sales_path: Path = DEFAULT_SALES_PATH,
    waste_path: Path = DEFAULT_WASTE_PATH,
    shelf_life_path: Path = DEFAULT_SHELF_LIFE_PATH,
    start_day: date = date(2026, 6, 1),
    end_day: date | None = None,
    order_days: int = DEFAULT_ORDER_CYCLE_DAYS,
    reference_day: date | None = None,
) -> dict[str, Any] | None:
    live_weather = load_met_norway_forecast()
    if live_weather is not None:
        WEATHER_BY_DATE.update(live_weather.days)
    uploaded_sales_paths = REPORT_STORAGE.paths("sales")
    effective_sales_paths = uploaded_sales_paths or ([sales_path] if sales_path.exists() else [])
    if not effective_sales_paths:
        return None

    uploaded_reports = REPORT_STORAGE.list() if uploaded_sales_paths else []
    uploaded_sales = [item for item in uploaded_reports if item.report_type == "sales"]
    effective_start_day = (
        min(date.fromisoformat(item.period_start) for item in uploaded_sales)
        if uploaded_sales and start_day == date(2026, 6, 1)
        else start_day
    )
    scan_end_day = end_day or date(2100, 12, 31)
    scanned_items = _merge_sales_items(
        [extract_items(read_xlsx(path), effective_start_day, scan_end_day) for path in effective_sales_paths]
    )
    actual_end_day = end_day or _latest_sales_day(scanned_items) or scan_end_day
    items = scanned_items
    uploaded_waste_paths = REPORT_STORAGE.paths("waste")
    effective_waste_paths = uploaded_waste_paths or ([waste_path] if waste_path.exists() else [])
    waste_counts = _combined_waste_counts(effective_waste_paths, items, effective_start_day, actual_end_day)
    waste_by_date = _combined_waste_by_date(effective_waste_paths, items, effective_start_day, actual_end_day)
    shelf_life = extract_shelf_life(shelf_life_path, items) if shelf_life_path.exists() else {}
    recommendations = build_recommendations(items, order_days, waste_counts, shelf_life)
    daily_menu = _with_decision_explanations(build_daily_menu(recommendations))
    forecast_reference_day = reference_day or date.today() - timedelta(days=1)
    rain_impact = _rain_sales_impact(items, effective_start_day, actual_end_day)

    return {
        "period": f"{effective_start_day.isoformat()}..{actual_end_day.isoformat()}",
        "weather_city": "Санкт-Петербург",
        "weather_source": live_weather.source if live_weather else "встроенные данные",
        "weather_updated_at": live_weather.updated_at if live_weather else None,
        "weather_stale": live_weather.stale if live_weather else False,
        "order_days": order_days,
        "total_quantity": sum(int(item["order_for_2_days"]) for item in daily_menu),
        "summary": daily_menu_summary(daily_menu),
        "category_totals": _category_totals(daily_menu),
        "role_groups": _group_menu_by_role(daily_menu),
        "retrospective_orders": _retrospective_orders(items, daily_menu, reference_day=forecast_reference_day),
        "future_orders": _future_orders(
            items,
            daily_menu,
            waste_by_date,
            reference_day=forecast_reference_day,
            count=4,
            rain_traffic_factor=float(rain_impact["applied_factor"]),
        ),
        "rain_sales_impact": rain_impact,
        "weather_sales_summary": _weather_sales_summary(items, effective_start_day, actual_end_day),
        "waste_leaders": _with_decision_explanations(waste_leaders(recommendations, limit=12)),
    }


def _merge_sales_items(groups: list[list[Any]]) -> list[Any]:
    merged: dict[tuple[str, str], Any] = {}
    for items in groups:
        for item in items:
            key = (item.category, item.name)
            if key not in merged:
                merged[key] = item
                continue
            current = merged[key]
            by_date = dict(current.by_date)
            for day, quantity in item.by_date.items():
                by_date[day] = by_date.get(day, 0) + quantity
            merged[key] = type(item)(item.category, item.name, by_date)
    return list(merged.values())


def _combined_waste_counts(
    paths: list[Path], items: list[Any], start_day: date, end_day: date
) -> dict[str, int]:
    combined: dict[str, int] = {}
    for path in paths:
        for name, count in extract_waste_counts(path, items, start_day, end_day).items():
            combined[name] = combined.get(name, 0) + count
    return combined


def _combined_waste_by_date(
    paths: list[Path], items: list[Any], start_day: date, end_day: date
) -> dict[str, dict[date, int]]:
    combined: dict[str, dict[date, int]] = {}
    for path in paths:
        for name, values in _waste_counts_by_date(path, items, start_day, end_day).items():
            target = combined.setdefault(name, {})
            for day, count in values.items():
                target[day] = target.get(day, 0) + count
    return combined


def _waste_counts_by_date(
    waste_path: Path,
    items: list[Any],
    start_day: date,
    end_day: date,
) -> dict[str, dict[date, int]]:
    rows = read_xlsx(waste_path)
    normalized_names = [normalize_name(item.name) for item in items]
    counts = {name: {} for name in normalized_names}
    for row in rows[4:]:
        if len(row) < 4:
            continue
        day = parse_datetime(row[0])
        if day is None or not (start_day <= day <= end_day):
            continue
        goods = normalize_name(row[3])
        if not goods:
            continue
        for item_name in normalized_names:
            if item_name and item_name in goods:
                counts[item_name][day] = counts[item_name].get(day, 0) + 1
    return counts


def _latest_sales_day(items: list[Any]) -> date | None:
    days = [
        day
        for item in items
        for day, quantity in item.by_date.items()
        if quantity > 0
    ]
    return max(days) if days else None


def _with_decision_explanations(items: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            **item,
            "risk_reason": _risk_reason(item),
            "decision_reason": _decision_reason(item),
        }
        for item in items
    ]


def _risk_reason(item: dict[str, object]) -> str:
    waste_count = int(item.get("waste_count", 0))
    average = float(item.get("average_per_day", 0))
    active_days = int(item.get("active_days", 0))
    if waste_count >= 8 and average < 1.5:
        return f"{waste_count} попаданий в списания и средний спрос {average:g} шт./день"
    if waste_count >= 5:
        return f"{waste_count} попаданий в списания: запас ограничен"
    if waste_count >= 1:
        return f"{waste_count} попаданий в списания: нужен контроль остатка"
    return f"списаний не найдено; продажи были в {active_days} дн."


def _decision_reason(item: dict[str, object]) -> str:
    abc_class = str(item.get("abc_class", "-"))
    stability = str(item.get("stability", "нет оценки"))
    shelf_life_days = int(item.get("shelf_life_days", 3))
    return f"класс {abc_class}, {stability}, срок {shelf_life_days} дн."


def _category_totals(items: list[dict[str, object]]) -> list[dict[str, object]]:
    totals: dict[str, dict[str, object]] = {}
    for item in items:
        category = str(item["category"])
        totals.setdefault(category, {"category": category, "items": 0, "quantity": 0})
        totals[category]["items"] = int(totals[category]["items"]) + 1
        totals[category]["quantity"] = int(totals[category]["quantity"]) + int(item["order_for_2_days"])
    return sorted(totals.values(), key=lambda value: str(value["category"]))


def _group_menu_by_role(items: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    groups = {"base": [], "rotation": [], "reserve": []}
    for item in items:
        strategy = str(item["strategy"])
        menu_role = str(item["menu_role"])
        waste_risk = str(item["waste_risk"])
        if "резерв" in menu_role or "высокий риск" in waste_risk:
            groups["reserve"].append(item)
        elif "держать регулярно" in strategy:
            groups["base"].append(item)
        else:
            groups["rotation"].append(item)
    return groups


def _retrospective_orders(
    sales_items: list[Any],
    menu_items: list[dict[str, object]],
    reference_day: date,
) -> list[dict[str, object]]:
    item_by_name = {item.name: item for item in sales_items}
    start = reference_day - timedelta(days=reference_day.weekday() + 7)
    periods = [(start, 2), (start + timedelta(days=2), 2), (start + timedelta(days=4), 3)]
    return [
        _retrospective_period(period_start, days, menu_items, item_by_name)
        for period_start, days in periods
    ]


def _retrospective_period(
    period_start: date,
    days: int,
    menu_items: list[dict[str, object]],
    item_by_name: dict[str, Any],
) -> dict[str, object]:
    period_days = [period_start + timedelta(days=offset) for offset in range(days)]
    rows = []
    total_actual = 0
    total_model = 0
    for item in menu_items:
        source = item_by_name.get(str(item["name"]))
        actual = int(sum(source.by_date.get(day, 0) for day in period_days)) if source else 0
        model_quantity = _period_quantity(item, period_days)
        total_actual += actual
        total_model += model_quantity
        rows.append(
            {
                "name": item["name"],
                "category": item["category"],
                "actual_sales": actual,
                "model_quantity": model_quantity,
                "difference": model_quantity - actual,
            }
        )
    return {
        "label": _period_label(period_start, days),
        "start": period_start.isoformat(),
        "end": period_days[-1].isoformat(),
        "days": days,
        "weather": _weather_summary(period_days),
        "actual_sales": total_actual,
        "model_quantity": total_model,
        "difference": total_model - total_actual,
        "coverage_note": _coverage_note(period_days, item_by_name),
        "rows": sorted(rows, key=lambda item: abs(int(item["difference"])), reverse=True)[:10],
    }


def _future_orders(
    sales_items: list[Any],
    menu_items: list[dict[str, object]],
    waste_by_date: dict[str, dict[date, int]],
    reference_day: date,
    count: int,
    rain_traffic_factor: float = 0.88,
) -> list[dict[str, object]]:
    starts = []
    cursor = reference_day + timedelta(days=1)
    while len(starts) < count:
        if cursor.weekday() in (0, 2, 4):
            starts.append(cursor)
        cursor += timedelta(days=1)
    return [
        _future_period(
            start,
            3 if start.weekday() == 4 else 2,
            menu_items,
            sales_items,
            waste_by_date,
            rain_traffic_factor,
        )
        for start in starts
    ]


def _future_period(
    period_start: date,
    days: int,
    menu_items: list[dict[str, object]],
    sales_items: list[Any],
    waste_by_date: dict[str, dict[date, int]],
    rain_traffic_factor: float,
) -> dict[str, object]:
    period_days = [period_start + timedelta(days=offset) for offset in range(days)]
    item_by_name = {item.name: item for item in sales_items}
    previous_period_days = _previous_matching_period_days(period_start, days, sales_items)
    rows = [
        {
            **item,
            "forecast_quantity": _period_quantity(item, period_days, rain_traffic_factor),
            "weather_factor": round(_weather_factor(str(item["category"]), period_days, rain_traffic_factor), 2),
            "previous_period_sales": _sales_for_period(str(item["name"]), previous_period_days, item_by_name),
            "previous_period_waste": _waste_for_period(str(item["name"]), previous_period_days, waste_by_date),
            "previous_period_label": _period_range_label(previous_period_days),
        }
        for item in menu_items
    ]
    rows = [
        {
            **item,
            "daily_forecast": (
                _weekday_daily_forecast(
                    item_by_name.get(str(item["name"])),
                    str(item["category"]),
                    period_days,
                    rain_traffic_factor,
                )
                if days == 3
                else _daily_distribution(
                    item_by_name.get(str(item["name"])),
                    str(item["category"]),
                    period_days,
                    int(item["forecast_quantity"]),
                    rain_traffic_factor,
                )
            ),
        }
        for item in rows
    ]
    if days == 3:
        rows = [
            {**item, "forecast_quantity": sum(int(day["quantity"]) for day in item["daily_forecast"])}
            for item in rows
        ]
    daily_totals = [
        {
            "date": day.isoformat(),
            "weekday": WEEKDAY_LABELS[day.weekday()],
            "quantity": sum(
                int(next(entry["quantity"] for entry in item["daily_forecast"] if entry["date"] == day.isoformat()))
                for item in rows
            ),
            "weather": str(WEATHER_BY_DATE.get(day, {"summary": "нет данных"})["summary"]),
            "weather_available": day in WEATHER_BY_DATE,
            "rain": bool(WEATHER_BY_DATE.get(day, {}).get("rain")),
            "traffic_factor": round(_weather_factor("", [day], rain_traffic_factor), 2),
            "weather_adjustment_percent": round(
                (_weather_factor("", [day], rain_traffic_factor) - 1) * 100
            ),
        }
        for day in period_days
    ]
    return {
        "label": _period_label(period_start, days),
        "start": period_start.isoformat(),
        "end": period_days[-1].isoformat(),
        "days": days,
        "order_policy": _order_policy(period_days),
        "previous_period": _period_range_label(previous_period_days),
        "shelf_life_mix": _shelf_life_mix(rows),
        "weather": _weather_summary(period_days),
        "rain_traffic_factor": round(rain_traffic_factor, 2),
        "total_quantity": sum(int(item["forecast_quantity"]) for item in rows),
        "daily_totals": daily_totals,
        "rows": sorted(rows, key=lambda item: (str(item["category"]), str(item["name"]))),
    }


def _daily_distribution(
    source: Any | None,
    category: str,
    period_days: list[date],
    total_quantity: int,
    rain_traffic_factor: float,
) -> list[dict[str, object]]:
    weights = []
    for day in period_days:
        historic = [] if source is None else [
            quantity
            for historic_day, quantity in source.by_date.items()
            if historic_day.weekday() == day.weekday()
        ]
        weekday_average = sum(historic) / len(historic) if historic else 1.0
        weights.append(max(0.05, weekday_average) * _weather_factor(category, [day], rain_traffic_factor))
    weight_total = sum(weights) or len(period_days)
    raw = [total_quantity * weight / weight_total for weight in weights]
    quantities = [int(value) for value in raw]
    remaining = total_quantity - sum(quantities)
    order = sorted(range(len(raw)), key=lambda index: raw[index] - quantities[index], reverse=True)
    for index in order[:remaining]:
        quantities[index] += 1
    return [
        {
            "date": day.isoformat(),
            "weekday": WEEKDAY_LABELS[day.weekday()],
            "quantity": quantities[index],
            "weather_factor": round(_weather_factor(category, [day], rain_traffic_factor), 2),
        }
        for index, day in enumerate(period_days)
    ]


def _weekday_daily_forecast(
    source: Any | None,
    category: str,
    period_days: list[date],
    rain_traffic_factor: float,
) -> list[dict[str, object]]:
    observed_values = list(source.by_date.values()) if source is not None else []
    fallback_average = sum(observed_values) / len(observed_values) if observed_values else 0.0
    result = []
    for day in period_days:
        matching_values = (
            [quantity for historic_day, quantity in source.by_date.items() if historic_day.weekday() == day.weekday()]
            if source is not None
            else []
        )
        weekday_average = sum(matching_values) / len(matching_values) if matching_values else fallback_average
        factor = _weather_factor(category, [day], rain_traffic_factor)
        result.append(
            {
                "date": day.isoformat(),
                "weekday": WEEKDAY_LABELS[day.weekday()],
                "quantity": max(0, round(weekday_average * factor)),
                "weather_factor": round(factor, 2),
                "history_points": len(matching_values),
            }
        )
    return result


def _previous_matching_period_days(
    period_start: date,
    days: int,
    sales_items: list[Any],
) -> list[date]:
    available_days = {day for item in sales_items for day in item.by_date}
    cursor = period_start - timedelta(days=7)
    while cursor >= min(available_days, default=period_start):
        candidate_days = [cursor + timedelta(days=offset) for offset in range(days)]
        if all(day in available_days for day in candidate_days):
            return candidate_days
        cursor -= timedelta(days=7)
    return []


def _sales_for_period(
    item_name: str,
    period_days: list[date],
    item_by_name: dict[str, Any],
) -> int | None:
    item = item_by_name.get(item_name)
    if item is None or not period_days:
        return None
    observed = [item.by_date[day] for day in period_days if day in item.by_date]
    return int(sum(observed)) if observed else None


def _waste_for_period(
    item_name: str,
    period_days: list[date],
    waste_by_date: dict[str, dict[date, int]],
) -> int:
    item_waste = waste_by_date.get(normalize_name(item_name), {})
    return sum(item_waste.get(day, 0) for day in period_days)


def _period_range_label(period_days: list[date]) -> str:
    if not period_days:
        return "нет прошлого периода"
    return f"{period_days[0].isoformat()}..{period_days[-1].isoformat()}"


def _cap_weekend_rows(
    rows: list[dict[str, object]],
    menu_items: list[dict[str, object]],
    sales_items: list[Any],
) -> list[dict[str, object]]:
    cap = _weekend_volume_cap(menu_items, sales_items)
    total = sum(int(item["forecast_quantity"]) for item in rows)
    if cap is None or total <= cap:
        return rows
    scale = cap / total
    capped_rows = []
    for item in rows:
        capped_rows.append(
            {
                **item,
                "forecast_quantity": max(1, round(int(item["forecast_quantity"]) * scale)),
                "weekend_cap_reason": f"объем снижен до исторического потолка Пт+Сб+Вс: {cap} шт.",
            }
        )
    return _rebalance_to_total(capped_rows, cap)


def _weekend_volume_cap(menu_items: list[dict[str, object]], sales_items: list[Any]) -> int | None:
    item_by_name = {item.name: item for item in sales_items}
    all_days = sorted({day for item in sales_items for day in item.by_date})
    if not all_days:
        return None
    weekend_totals = []
    cursor = all_days[0]
    end_day = all_days[-1]
    while cursor + timedelta(days=2) <= end_day:
        if cursor.weekday() == 4:
            period_days = [cursor + timedelta(days=offset) for offset in range(3)]
            total = 0
            for item in menu_items:
                source = item_by_name.get(str(item["name"]))
                total += int(sum(source.by_date.get(day, 0) for day in period_days)) if source else 0
            weekend_totals.append(total)
        cursor += timedelta(days=1)
    if len(weekend_totals) < 3:
        return None
    ordered = sorted(weekend_totals)
    percentile_index = round((len(ordered) - 1) * 0.75)
    return ordered[percentile_index]


def _rebalance_to_total(rows: list[dict[str, object]], target_total: int) -> list[dict[str, object]]:
    current_total = sum(int(item["forecast_quantity"]) for item in rows)
    if current_total == target_total:
        return rows
    direction = -1 if current_total > target_total else 1
    remaining = abs(current_total - target_total)
    sorted_indexes = sorted(
        range(len(rows)),
        key=lambda index: (
            int(rows[index].get("shelf_life_days", 3)),
            int(rows[index].get("waste_count", 0)),
            int(rows[index]["forecast_quantity"]),
        ),
        reverse=direction < 0,
    )
    while remaining > 0 and sorted_indexes:
        changed = False
        for index in sorted_indexes:
            quantity = int(rows[index]["forecast_quantity"])
            if direction < 0 and quantity <= 1:
                continue
            rows[index]["forecast_quantity"] = quantity + direction
            remaining -= 1
            changed = True
            if remaining == 0:
                break
        if not changed:
            break
    return rows


def _period_quantity(
    item: dict[str, object], period_days: list[date], rain_traffic_factor: float = 0.88
) -> int:
    base_daily = int(item["order_for_2_days"]) / DEFAULT_ORDER_CYCLE_DAYS
    shelf_life_days = int(item.get("shelf_life_days", 3))
    target_days = min(len(period_days), DEFAULT_ORDER_CYCLE_DAYS)
    effective_days = min(target_days, shelf_life_days)
    quantity = base_daily * effective_days * _weather_factor(
        str(item["category"]), period_days, rain_traffic_factor
    )
    return max(1, round(quantity))


def _order_policy(period_days: list[date]) -> str:
    if len(period_days) >= 3:
        return "трехдневное окно: пятница, суббота и воскресенье рассчитаны отдельно по истории соответствующего дня недели; позиции со сроком 2 дня требуют отдельного пополнения на воскресенье"
    return "двухдневное окно: считаем базовый объем на 2 дня"


def _shelf_life_mix(rows: list[dict[str, object]]) -> str:
    three_day_items = sum(1 for item in rows if int(item.get("shelf_life_days", 3)) >= 3)
    short_items = len(rows) - three_day_items
    return f"{three_day_items} поз. со сроком 3 дня, {short_items} поз. со сроком 2 дня"


def _weather_sales_summary(items: list[Any], start_day: date, end_day: date) -> list[dict[str, object]]:
    category_names = ["Супы", "Горячее", "Завтраки", "Салаты", "Роллы"]
    groups: dict[tuple[str, str], dict[str, object]] = {}
    for day in _date_range(start_day, end_day):
        weather = WEATHER_BY_DATE.get(day)
        observed_items = [item for item in items if day in item.by_date]
        if not weather or not observed_items:
            continue
        month = _month_label(day)
        bucket = _weather_bucket(weather)
        key = (month, bucket)
        groups.setdefault(
            key,
            {
                "month": month,
                "weather_bucket": bucket,
                "days": 0,
                "temperature_avg": 0.0,
                "sales_total": 0.0,
                "category_sales": {category: 0.0 for category in category_names},
            },
        )
        group = groups[key]
        group["days"] = int(group["days"]) + 1
        group["temperature_avg"] = float(group["temperature_avg"]) + int(weather["temperature"])
        day_total = 0.0
        category_sales = group["category_sales"]
        assert isinstance(category_sales, dict)
        for item in observed_items:
            quantity = float(item.by_date[day])
            day_total += quantity
            if item.category in category_sales:
                category_sales[item.category] = float(category_sales[item.category]) + quantity
        group["sales_total"] = float(group["sales_total"]) + day_total

    result = []
    for group in groups.values():
        days = int(group["days"])
        category_sales = group["category_sales"]
        assert isinstance(category_sales, dict)
        result.append(
            {
                "month": group["month"],
                "weather_bucket": group["weather_bucket"],
                "days": days,
                "temperature_avg": round(float(group["temperature_avg"]) / days, 1),
                "sales_per_day": round(float(group["sales_total"]) / days, 1),
                "category_sales_per_day": {
                    category: round(float(category_sales[category]) / days, 1)
                    for category in category_names
                },
            }
        )
    return sorted(result, key=lambda item: (_month_order(str(item["month"])), str(item["weather_bucket"])))


def _rain_sales_impact(items: list[Any], start_day: date, end_day: date) -> dict[str, object]:
    """Estimate rain impact after removing the ordinary weekday pattern."""
    daily_sales = {}
    for day in _date_range(start_day, end_day):
        observed_values = [float(item.by_date[day]) for item in items if day in item.by_date]
        if day in WEATHER_BY_DATE and observed_values:
            daily_sales[day] = sum(observed_values)
    dry_by_weekday: dict[int, list[float]] = {}
    for day, quantity in daily_sales.items():
        if not WEATHER_BY_DATE[day].get("rain"):
            dry_by_weekday.setdefault(day.weekday(), []).append(quantity)

    normalized_rain = []
    rainy_sales = []
    dry_sales = []
    for day, quantity in daily_sales.items():
        if WEATHER_BY_DATE[day].get("rain"):
            baseline = dry_by_weekday.get(day.weekday(), [])
            if baseline and sum(baseline) > 0:
                normalized_rain.append(quantity / (sum(baseline) / len(baseline)))
            rainy_sales.append(quantity)
        else:
            dry_sales.append(quantity)

    observed_factor = sum(normalized_rain) / len(normalized_rain) if normalized_rain else 0.88
    applied_factor = min(0.95, max(0.70, observed_factor))
    return {
        "method": "продажи в дождь относительно сухих дней того же дня недели",
        "rain_days": len(rainy_sales),
        "dry_days": len(dry_sales),
        "rain_sales_per_day": round(sum(rainy_sales) / len(rainy_sales), 1) if rainy_sales else None,
        "dry_sales_per_day": round(sum(dry_sales) / len(dry_sales), 1) if dry_sales else None,
        "observed_factor": round(observed_factor, 2),
        "applied_factor": round(applied_factor, 2),
        "applied_change_percent": round((applied_factor - 1) * 100),
        "note": "Коэффициент ограничен диапазоном 0,70–0,95: дождливый день всегда снижает общий трафик, но не более чем на 30%.",
    }


def _date_range(start_day: date, end_day: date) -> list[date]:
    return [start_day + timedelta(days=offset) for offset in range((end_day - start_day).days + 1)]


def _weather_bucket(weather: dict[str, object]) -> str:
    temperature = int(weather.get("temperature", 22))
    has_rain = bool(weather.get("rain"))
    if has_rain and temperature >= 27:
        return "жара + осадки"
    if has_rain:
        return "осадки"
    if temperature >= 27:
        return "жара"
    if temperature <= 18:
        return "прохладно"
    return "умеренно"


def _month_label(day: date) -> str:
    return {
        6: "июнь",
        7: "июль",
        8: "август",
    }.get(day.month, day.strftime("%m.%Y"))


def _month_order(month: str) -> int:
    return {"июнь": 6, "июль": 7, "август": 8}.get(month, 99)


def _weather_factor(
    category: str, period_days: list[date], rain_traffic_factor: float = 0.88
) -> float:
    factors = []
    for day in period_days:
        weather = WEATHER_BY_DATE.get(day, {})
        factor = rain_traffic_factor if weather.get("rain") else 1.0
        temperature = int(weather.get("temperature", 22))
        if weather.get("rain") and category == "Супы":
            factor += 0.06
        if weather.get("rain") and category == "Горячее":
            factor += 0.03
        if weather.get("rain") and category == "Салаты":
            factor -= 0.04
        if temperature >= 27 and category == "Салаты":
            factor += 0.08
        if temperature >= 27 and category in {"Супы", "Горячее"}:
            factor -= 0.03
        if day.weekday() >= 5 and category == "Завтраки":
            factor += 0.05
        factors.append(max(0.70, factor))
    return sum(factors) / len(factors) if factors else 1.0


def _weather_summary(period_days: list[date]) -> str:
    return "; ".join(
        f"{day.strftime('%d.%m')}: {WEATHER_BY_DATE.get(day, {'summary': 'нет данных'})['summary']}"
        for day in period_days
    )


def _coverage_note(period_days: list[date], item_by_name: dict[str, Any]) -> str:
    covered_days = {
        day
        for item in item_by_name.values()
        for day in period_days
        if day in item.by_date
    }
    if len(covered_days) == len(period_days):
        return "полный период в выгрузке"
    return f"в выгрузке есть {len(covered_days)} из {len(period_days)} дней"


def _period_label(period_start: date, days: int) -> str:
    labels = {
        0: "Пн+Вт",
        2: "Ср+Чт",
        4: "Пт+Сб+Вс",
    }
    return labels.get(period_start.weekday(), f"{days} дн.")


def render_orders_workspace(strategy: dict[str, Any] | None) -> str:
    if strategy is None:
        return "<section class='workspace'><h2>Ближайший заказ</h2><div class='signal-box'>Загрузите отчет продаж, чтобы построить прогноз.</div></section>"

    current = strategy["future_orders"][0]
    following = strategy["future_orders"][1:]
    day_headings = "".join(
        f"<th>{escape(str(day['weekday']))}<span>{escape(str(day['date']))}</span></th>"
        for day in current["daily_totals"]
    )
    rows = "".join(_render_operational_row(item) for item in current["rows"])
    next_cards = "".join(
        f"<a class='next-order-card' href='/?start={period['start']}&days=14'>"
        f"<span>{escape(str(period['label']))} · {escape(str(period['start']))}—{escape(str(period['end']))}</span>"
        f"<strong>{period['total_quantity']} шт.</strong><small>{escape(str(period['weather']))}</small></a>"
        for period in following
    )
    rain_days = sum(1 for day in current["daily_totals"] if day["rain"])
    missing_weather = sum(1 for day in current["daily_totals"] if not day["weather_available"])
    short_shelf = sum(1 for item in current["rows"] if int(item["shelf_life_days"]) < int(current["days"]))
    alerts = []
    if rain_days:
        alerts.append(f"Осадки повлияли на {rain_days} дн. заказа")
    if missing_weather:
        alerts.append(f"Нет прогноза погоды на {missing_weather} дн.")
    if short_shelf:
        alerts.append(f"{short_shelf} поз. требуют дополнительной поставки")
    alert_html = "".join(f"<span class='alert-chip'>{escape(alert)}</span>" for alert in alerts) or "<span class='ok-chip'>Критичных предупреждений нет</span>"
    updated = strategy["weather_updated_at"] or "нет данных"

    return f"""
    <section class="workspace order-focus">
      <div class="workspace-head">
        <div><span class="eyebrow">Ближайший заказ</span><h2>{current['label']} · {current['start']}—{current['end']}</h2>
        <div class="muted">Продажи учтены по {strategy['period'].split('..')[-1]} · погода: {escape(str(strategy['weather_source']))}, {escape(str(updated))}</div></div>
        <div class="order-total"><span>Заказать</span><strong>{current['total_quantity']}</strong><small>штук</small></div>
      </div>
      <div class="daily-strip">{_render_daily_totals(current['daily_totals'])}</div>
      <div class="alert-row">{alert_html}</div>
      <div class="table-wrap">
        <table class="order-table"><thead><tr><th>Позиция</th>{day_headings}<th>Итого</th><th>Статус</th><th></th></tr></thead><tbody>{rows}</tbody></table>
      </div>
    </section>
    <section class="next-orders"><div class="section-title"><div><span class="eyebrow">Далее</span><h2>Следующие заказы</h2></div><a href="/analytics">Открыть аналитику →</a></div><div class="next-order-grid">{next_cards}</div></section>
    <dialog id="item-dialog"><button class="dialog-close" aria-label="Закрыть">×</button><div id="dialog-content"></div></dialog>
    """


def _render_operational_row(item: dict[str, object]) -> str:
    day_cells = "".join(f"<td class='number'>{day['quantity']}</td>" for day in item["daily_forecast"])
    status = str(item.get("waste_risk", "контроль"))
    details = (
        f"Категория: {item['category']}\n"
        f"Срок хранения: {item['shelf_life_days']} дн.\n"
        f"Продажи прошлого окна: {item['previous_period_sales'] if item['previous_period_sales'] is not None else 'нет данных'}\n"
        f"Списания прошлого окна: {item['previous_period_waste']}\n"
        f"Погодный коэффициент: ×{item['weather_factor']}\n"
        f"Решение: {item.get('decision_reason', item.get('strategy', 'нет данных'))}\n"
        f"Риск: {_future_risk_context(item)}"
    )
    return (
        f"<tr><td><strong>{escape(str(item['name']))}</strong><span>{escape(str(item['category']))}</span></td>"
        f"{day_cells}<td class='number total-cell'>{item['forecast_quantity']}</td>"
        f"<td><i class='{_risk_class(status)}'>{escape(status)}</i></td>"
        f"<td><button class='detail-button' data-name='{escape(str(item['name']), quote=True)}' data-details='{escape(details, quote=True)}'>Подробнее</button></td></tr>"
    )


def render_culinary_strategy_html(strategy: dict[str, Any] | None) -> str:
    if strategy is None:
        return """
        <section>
          <h2>Заказ кулинарии</h2>
          <div class="signal-box">Файлы продаж кулинарии не найдены. Сейчас показана демо-панель.</div>
        </section>
        """

    summary = strategy["summary"]
    category_cards = "\n".join(
        f"""
        <div class="category-card">
          <span>{escape(str(item["category"]))}</span>
          <strong>{item["quantity"]} шт.</strong>
          <small>{item["items"]} поз.</small>
        </div>
        """
        for item in strategy["category_totals"]
    )
    base_rows = _render_strategy_rows(strategy["role_groups"]["base"])
    rotation_rows = _render_strategy_rows(strategy["role_groups"]["rotation"])
    reserve_rows = _render_strategy_rows(strategy["role_groups"]["reserve"])
    waste_rows = _render_waste_rows(strategy["waste_leaders"])
    future_orders = _render_future_orders(strategy["future_orders"])
    retrospective_orders = _render_retrospective_orders(strategy["retrospective_orders"])
    weather_sales = _render_weather_sales_summary(strategy["weather_sales_summary"])
    rain_impact = strategy["rain_sales_impact"]

    return f"""
    <section class="workspace">
      <div class="workspace-head">
        <div>
          <h2>Заказ кулинарии на {strategy["order_days"]} дня</h2>
          <div class="muted">Период анализа: {strategy["period"]}</div>
        </div>
        <div class="pill">Меню: {summary["actual_total"]} / {summary["target_total"]}</div>
      </div>

      <div class="metrics compact">
        <div class="metric"><span>Объем заказа</span><strong>{strategy["total_quantity"]} шт.</strong></div>
        <div class="metric"><span>Недобор до цели</span><strong>{summary["shortfall"]} поз.</strong></div>
        <div class="metric"><span>Резерв с высоким риском</span><strong>{summary["high_risk_count"]} поз.</strong></div>
      </div>

      <div class="category-strip">{category_cards}</div>

      <h2>Будущие заказы по датам</h2>
      <div class="signal-box"><strong>Учет дождя: {rain_impact["applied_change_percent"]:+}% к общему потоку.</strong> Факт: {rain_impact["rain_sales_per_day"]} продаж/день в {rain_impact["rain_days"]} дождливых дней против {rain_impact["dry_sales_per_day"]} в {rain_impact["dry_days"]} сухих. Нормализованный коэффициент по дням недели: ×{rain_impact["observed_factor"]}; для заказа применяется безопасный коэффициент ×{rain_impact["applied_factor"]}.</div>
      <div class="future-orders">{future_orders}</div>

      <h2>Ретроспектива прошлой недели</h2>
      <div class="retrospective-orders">{retrospective_orders}</div>

      <h2>Спрос по погоде: {strategy["weather_city"]}</h2>
      <p class="muted">Источник: {escape(str(strategy["weather_source"]))}; обновление: {escape(str(strategy["weather_updated_at"] or "нет данных"))}{"; используется сохраненный прогноз" if strategy["weather_stale"] else ""}</p>
      <div class="weather-summary">{weather_sales}</div>

      <div class="tabs">
        <input checked id="tab-base" name="menu-tab" type="radio">
        <label for="tab-base">Постоянно</label>
        <input id="tab-rotation" name="menu-tab" type="radio">
        <label for="tab-rotation">Ротация</label>
        <input id="tab-reserve" name="menu-tab" type="radio">
        <label for="tab-reserve">Резерв</label>
        <input id="tab-waste" name="menu-tab" type="radio">
        <label for="tab-waste">Исключить</label>

        <div class="tab-panel base-panel">{base_rows}</div>
        <div class="tab-panel rotation-panel">{rotation_rows}</div>
        <div class="tab-panel reserve-panel">{reserve_rows}</div>
        <div class="tab-panel waste-panel">{waste_rows}</div>
      </div>
    </section>
    """


def _render_future_orders(periods: list[dict[str, object]]) -> str:
    return "\n".join(
        f"""
        <details class="period-card" {"open" if index == 0 else ""}>
          <summary>
            <strong>{period["label"]}: {period["start"]} - {period["end"]}</strong>
            <span>{period["total_quantity"]} шт.</span>
          </summary>
          <p>{escape(str(period["order_policy"]))}</p>
          <p class="muted">Продажи в таблице: прошлое сопоставимое окно {escape(str(period["previous_period"]))}</p>
          <p class="muted">{escape(str(period["shelf_life_mix"]))}</p>
          <p class="muted">{escape(str(period["weather"]))}</p>
          <p class="muted"><strong>Дождь:</strong> общий клиентский поток ×{period["rain_traffic_factor"]}; внутри категорий сохраняется поправка на горячее и холодное меню.</p>
          <div class="daily-strip">{_render_daily_totals(period["daily_totals"])}</div>
          {_strategy_table(_render_future_rows(period["rows"]), "Продажи прошлого окна", "Списания прошлого окна", show_daily=True)}
        </details>
        """
        for index, period in enumerate(periods)
    )


def _render_daily_totals(days: list[dict[str, object]]) -> str:
    return "".join(
        f"<div class='daily-card'><span>{escape(str(day['weekday']))}, {escape(str(day['date']))}</span>"
        f"<strong>{day['quantity']} шт.</strong><small>{escape(str(day['weather']))}</small>"
        f"<small>{_daily_weather_effect(day)}</small></div>"
        for day in days
    )


def _daily_weather_effect(day: dict[str, object]) -> str:
    if not day.get("weather_available"):
        return "Погодных данных нет — поправка не применяется"
    prefix = "Дождь: поток " if day["rain"] else "Без осадков: поток "
    return f"{prefix}×{day['traffic_factor']} ({day['weather_adjustment_percent']:+}%)"


def _render_daily_forecast(days: list[dict[str, object]]) -> str:
    return "<br>".join(
        f"<strong>{escape(str(day['weekday']))}: {day['quantity']} шт.</strong> "
        f"<small>погода ×{day['weather_factor']}</small>"
        for day in days
    )


def _render_future_rows(items: list[dict[str, object]]) -> str:
    return "\n".join(
        f"""
        <tr>
          <td><strong>{escape(str(item["name"]))}</strong><span>{escape(str(item["category"]))}</span></td>
          <td>{item["forecast_quantity"]} шт.</td>
          <td>{_render_daily_forecast(item["daily_forecast"])}</td>
          <td>{item["shelf_life_days"]} дн.</td>
          <td>{item["previous_period_sales"] if item["previous_period_sales"] is not None else "нет данных"}<span>{escape(str(item["previous_period_label"]))}</span></td>
          <td>{item["previous_period_waste"]}<span>{escape(str(item["previous_period_label"]))}</span></td>
          <td>{_render_risk_cell(item, _future_risk_context(item))}</td>
          <td>{_render_decision_cell(item)}</td>
        </tr>
        """
        for item in items
    )


def _future_risk_context(item: dict[str, object]) -> str:
    previous_waste = int(item.get("previous_period_waste", 0))
    previous_sales_raw = item.get("previous_period_sales")
    previous_sales = int(previous_sales_raw) if previous_sales_raw is not None else None
    sales_signal = str(previous_sales) if previous_sales is not None else "нет данных"
    signals = [f"прошлое окно: продажи {sales_signal}, списания {previous_waste}"]
    if previous_waste > 0:
        signals.append("свежий сигнал списаний: снижать запас или заменить SKU")
    signals.append(f"погодный коэффициент x{item['weather_factor']}")
    return "; ".join(signals)


def _render_retrospective_orders(periods: list[dict[str, object]]) -> str:
    return "\n".join(
        f"""
        <div class="retro-card">
          <strong>{period["label"]}: {period["start"]} - {period["end"]}</strong>
          <span>{period["actual_sales"]} факт / {period["model_quantity"]} модель / {period["difference"]:+} разница</span>
          <small>{escape(str(period["coverage_note"]))}</small>
          <p>{escape(str(period["weather"]))}</p>
        </div>
        """
        for period in periods
    )


def _render_strategy_rows(items: list[dict[str, object]]) -> str:
    rows = "\n".join(
        f"""
        <tr>
          <td><strong>{escape(str(item["name"]))}</strong><span>{escape(str(item["category"]))}</span></td>
          <td>{item["order_for_2_days"]} шт.</td>
          <td>{item["shelf_life_days"]} дн.</td>
          <td>{item["sales_june_july"]}</td>
          <td>{item["waste_count"]}</td>
          <td>{_render_risk_cell(item)}</td>
          <td>{_render_decision_cell(item)}</td>
        </tr>
        """
        for item in items
    )
    return _strategy_table(rows)


def _render_waste_rows(items: list[dict[str, object]]) -> str:
    rows = "\n".join(
        f"""
        <tr>
          <td><strong>{escape(str(item["name"]))}</strong><span>{escape(str(item["category"]))}</span></td>
          <td>-</td>
          <td>{item["shelf_life_days"]} дн.</td>
          <td>{item["sales_june_july"]}</td>
          <td>{item["waste_count"]}</td>
          <td>{_render_risk_cell(item)}</td>
          <td>{_render_decision_cell(item)}</td>
        </tr>
        """
        for item in items
    )
    return _strategy_table(rows)


def _render_risk_cell(item: dict[str, object], extra: str | None = None) -> str:
    details = str(item.get("risk_reason", "основание не рассчитано"))
    cap_reason = item.get("weekend_cap_reason")
    if cap_reason:
        details = f"{details}; {cap_reason}"
    if extra:
        details = f"{details}; {extra}"
    return (
        f'<i class="{_risk_class(str(item["waste_risk"]))}">{escape(str(item["waste_risk"]))}</i>'
        f"<span>{escape(details)}</span>"
    )


def _render_decision_cell(item: dict[str, object]) -> str:
    return (
        f"<strong>{escape(str(item['strategy']))}</strong>"
        f"<span>{escape(str(item.get('decision_reason', 'основание не рассчитано')))}</span>"
    )


def _render_weather_sales_summary(rows: list[dict[str, object]]) -> str:
    body = "\n".join(
        f"""
        <tr>
          <td>{escape(str(row["month"]))}</td>
          <td><strong>{escape(str(row["weather_bucket"]))}</strong><span>средняя t: +{row["temperature_avg"]}°C</span></td>
          <td>{row["days"]}</td>
          <td>{row["sales_per_day"]}</td>
          <td>{row["category_sales_per_day"].get("Супы", 0)}</td>
          <td>{row["category_sales_per_day"].get("Горячее", 0)}</td>
          <td>{row["category_sales_per_day"].get("Завтраки", 0)}</td>
          <td>{row["category_sales_per_day"].get("Салаты", 0)}</td>
        </tr>
        """
        for row in rows
    )
    return f"""
    <table class="strategy-table">
      <thead>
        <tr>
          <th>Месяц</th>
          <th>Погода</th>
          <th>Дней</th>
          <th>Продаж/день</th>
          <th>Супы</th>
          <th>Горячее</th>
          <th>Завтраки</th>
          <th>Салаты</th>
        </tr>
      </thead>
      <tbody>{body}</tbody>
    </table>
    """


def _strategy_table(
    rows: str,
    sales_heading: str = "Продажи",
    waste_heading: str = "Списания",
    show_daily: bool = False,
) -> str:
    daily_heading = "<th>По дням</th>" if show_daily else ""
    return f"""
    <table class="strategy-table">
      <thead>
        <tr>
          <th>Позиция</th>
          <th>Заказ</th>
          {daily_heading}
          <th>Срок</th>
          <th>{escape(sales_heading)}</th>
          <th>{escape(waste_heading)}</th>
          <th>Риск</th>
          <th>Решение</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
    """


def _risk_class(value: str) -> str:
    if "высокий" in value:
        return "risk high"
    if "средний" in value:
        return "risk medium"
    return "risk low"


def render_dashboard_html(payload: dict[str, Any], view: str = "orders") -> str:
    events = payload["events"][:14]
    budget = payload["budget"]
    max_budget = max([*budget.values(), 1])

    budget_rows = "\n".join(
        f"""
        <div class="budget-row">
          <div>
            <strong>{category}</strong>
            <span>{_format_money(amount)} ₽</span>
          </div>
          <div class="bar"><i style="width: {round(amount / max_budget * 100)}%"></i></div>
        </div>
        """
        for category, amount in budget.items()
    )
    event_rows = "\n".join(
        f"""
        <tr>
          <td>{event["day"]}</td>
          <td>{event["category"]}</td>
          <td>{event["item_name"]}</td>
          <td>{_format_number(event["quantity"])} {event["unit"]}</td>
          <td>{_format_money(event["estimated_price"])} ₽</td>
        </tr>
        """
        for event in events
    )
    forecast_logic = "\n".join(f"<li>{item}</li>" for item in payload["forecast_logic"])
    next_data = "\n".join(f"<li>{item}</li>" for item in payload["next_data"])
    demand_factors = payload["demand_factors"]
    culinary_strategy = (
        render_culinary_strategy_html(payload.get("culinary_strategy"))
        if view == "analytics"
        else render_orders_workspace(payload.get("culinary_strategy"))
    )

    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Заказы кулинарии</title>
  <style>
    :root {{
      --bg: #f6f2ec;
      --panel: #ffffff;
      --panel-soft: #eef1ec;
      --ink: #20231f;
      --muted: #687069;
      --line: #ded8ce;
      --green: #365f4c;
      --tomato: #a84732;
      --amber: #c28b2c;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: Inter, Segoe UI, Arial, sans-serif;
      letter-spacing: 0;
    }}
    main {{
      width: min(1180px, calc(100% - 32px));
      margin: 0 auto;
      padding: 24px 0 40px;
    }}
    header {{
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 16px;
      padding: 8px 0 18px;
      border-bottom: 1px solid var(--line);
    }}
    nav {{ display: flex; gap: 6px; flex-wrap: wrap; margin-top: 12px; }}
    nav a {{ color: var(--muted); text-decoration: none; padding: 7px 10px; border-radius: 7px; }}
    nav a.active, nav a:hover {{ color: var(--green); background: var(--panel-soft); }}
    h1 {{ margin: 0; font-size: 30px; line-height: 1.1; }}
    h2 {{ margin: 0 0 12px; font-size: 18px; }}
    .muted {{ color: var(--muted); }}
    .grid {{
      display: grid;
      grid-template-columns: 1.1fr 0.9fr;
      gap: 16px;
      margin-top: 16px;
    }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      margin-top: 16px;
    }}
    .metric, section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    .metric {{ padding: 14px; min-height: 88px; }}
    .metric span {{ display: block; color: var(--muted); font-size: 13px; }}
    .metric strong {{ display: block; margin-top: 8px; font-size: 24px; }}
    section {{ padding: 16px; }}
    .budget-row {{ display: grid; gap: 8px; padding: 10px 0; }}
    .budget-row + .budget-row {{ border-top: 1px solid var(--line); }}
    .budget-row div:first-child {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
    }}
    .bar {{
      height: 8px;
      background: var(--panel-soft);
      border-radius: 999px;
      overflow: hidden;
    }}
    .bar i {{
      display: block;
      height: 100%;
      background: linear-gradient(90deg, var(--green), var(--tomato), var(--amber));
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }}
    th, td {{
      padding: 10px 8px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
    }}
    th {{ color: var(--muted); font-weight: 600; }}
    ul {{ margin: 0; padding-left: 18px; }}
    li + li {{ margin-top: 8px; }}
    .signal-box {{
      padding: 14px;
      background: var(--panel-soft);
      border-radius: 8px;
      line-height: 1.45;
    }}
    .workspace {{ margin-top: 16px; }}
    .legacy-dashboard {{ display: none; }}
    .eyebrow {{ display: block; color: var(--green); font-size: 12px; font-weight: 800; text-transform: uppercase; letter-spacing: .08em; margin-bottom: 5px; }}
    .order-focus {{ padding: 22px; }}
    .order-focus h2 {{ font-size: 25px; margin-bottom: 5px; }}
    .order-total {{ min-width: 150px; padding: 14px 18px; border-radius: 10px; background: var(--green); color: white; display: grid; grid-template-columns: auto auto; align-items: baseline; gap: 0 8px; }}
    .order-total span {{ grid-column: 1 / -1; font-size: 12px; opacity: .8; }}
    .order-total strong {{ font-size: 36px; line-height: 1; }}
    .order-total small {{ opacity: .8; }}
    .alert-row {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0 16px; }}
    .alert-chip, .ok-chip {{ padding: 7px 10px; border-radius: 999px; font-size: 12px; font-weight: 700; }}
    .alert-chip {{ background: #f7e6bd; color: #775009; }}
    .ok-chip {{ background: #dfece3; color: #28513d; }}
    .table-wrap {{ overflow-x: auto; }}
    .order-table th span, .order-table td span {{ display: block; color: var(--muted); font-size: 11px; margin-top: 3px; }}
    .order-table .number {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .order-table .total-cell {{ font-weight: 800; color: var(--green); }}
    .detail-button {{ border: 0; background: transparent; color: var(--green); cursor: pointer; font-weight: 700; padding: 6px; }}
    .next-orders {{ margin-top: 16px; }}
    .section-title {{ display: flex; justify-content: space-between; align-items: end; gap: 12px; }}
    .next-order-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }}
    .next-order-card {{ display: grid; gap: 7px; padding: 14px; border: 1px solid var(--line); border-radius: 8px; text-decoration: none; color: var(--ink); background: #fbfaf7; }}
    .next-order-card:hover {{ border-color: var(--green); }}
    .next-order-card strong {{ font-size: 23px; color: var(--green); }}
    .next-order-card small {{ color: var(--muted); line-height: 1.35; }}
    dialog {{ width: min(480px, calc(100% - 24px)); height: 100%; max-height: none; margin: 0 0 0 auto; border: 0; padding: 42px 24px 24px; box-shadow: -12px 0 40px #0003; }}
    dialog::backdrop {{ background: #17201a66; }}
    .dialog-close {{ position: absolute; right: 16px; top: 12px; border: 0; background: transparent; font-size: 28px; cursor: pointer; }}
    #dialog-content h2 {{ font-size: 22px; }}
    #dialog-content p {{ white-space: pre-line; line-height: 1.6; color: var(--muted); }}
    .workspace-head {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: start;
      margin-bottom: 12px;
    }}
    .pill {{
      border: 1px solid var(--green);
      color: var(--green);
      border-radius: 999px;
      padding: 8px 12px;
      white-space: nowrap;
      font-weight: 700;
    }}
    .compact {{ margin-top: 0; }}
    .category-strip {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      margin: 12px 0 16px;
    }}
    .category-card {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: #fbfaf7;
    }}
    .category-card span,
    .category-card small,
    .strategy-table td span {{
      display: block;
      color: var(--muted);
      font-size: 12px;
    }}
    .category-card strong {{
      display: block;
      margin: 6px 0 2px;
      font-size: 22px;
    }}
    .tabs {{
      display: grid;
      grid-template-columns: repeat(4, max-content) 1fr;
      gap: 8px;
      align-items: center;
    }}
    .tabs input {{
      position: absolute;
      opacity: 0;
      pointer-events: none;
    }}
    .tabs label {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 8px 12px;
      cursor: pointer;
      font-weight: 700;
      color: var(--muted);
      background: #fbfaf7;
    }}
    #tab-base:checked + label,
    #tab-rotation:checked + label,
    #tab-reserve:checked + label,
    #tab-waste:checked + label {{
      background: var(--green);
      border-color: var(--green);
      color: #fff;
    }}
    .tab-panel {{
      display: none;
      grid-column: 1 / -1;
      margin-top: 8px;
      overflow-x: auto;
    }}
    #tab-base:checked ~ .base-panel,
    #tab-rotation:checked ~ .rotation-panel,
    #tab-reserve:checked ~ .reserve-panel,
    #tab-waste:checked ~ .waste-panel {{
      display: block;
    }}
    .strategy-table th:nth-child(2),
    .strategy-table th:nth-child(3),
    .strategy-table th:nth-child(4),
    .strategy-table th:nth-child(5),
    .strategy-table td:nth-child(2),
    .strategy-table td:nth-child(3),
    .strategy-table td:nth-child(4),
    .strategy-table td:nth-child(5) {{
      text-align: right;
      white-space: nowrap;
    }}
    .risk {{
      display: inline-block;
      border-radius: 999px;
      padding: 5px 8px;
      font-style: normal;
      font-size: 12px;
      font-weight: 700;
      white-space: nowrap;
    }}
    .risk.high {{ background: #f5d7cf; color: #8d2f1c; }}
    .risk.medium {{ background: #f7e6bd; color: #775009; }}
    .risk.low {{ background: #dfece3; color: #28513d; }}
    .future-orders,
    .retrospective-orders {{
      display: grid;
      gap: 10px;
      margin: 8px 0 18px;
    }}
    .daily-strip {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 8px;
      margin: 12px 0;
    }}
    .daily-card {{
      display: grid;
      gap: 4px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      background: #fff;
    }}
    .daily-card strong {{ font-size: 20px; color: var(--green); }}
    .daily-card small {{ color: var(--muted); }}
    .weather-summary {{
      overflow-x: auto;
      margin: 8px 0 18px;
    }}
    .period-card,
    .retro-card {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfaf7;
      padding: 12px;
    }}
    .period-card summary {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      cursor: pointer;
      font-weight: 700;
    }}
    .period-card p,
    .retro-card p {{
      margin: 10px 0;
      color: var(--muted);
      line-height: 1.4;
    }}
    .retro-card span,
    .retro-card small {{
      display: block;
      margin-top: 6px;
      color: var(--muted);
    }}
    @media (max-width: 820px) {{
      main {{ width: min(100% - 20px, 680px); padding-top: 16px; }}
      header {{ align-items: start; flex-direction: column; }}
      .grid, .metrics, .category-strip, .next-order-grid {{ grid-template-columns: 1fr; }}
      .workspace-head {{ flex-direction: column; }}
      .tabs {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .tabs label {{ text-align: center; }}
      table {{ font-size: 13px; }}
      th, td {{ padding: 8px 6px; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>Заказы кулинарии</h1>
        <div class="muted">Обеды, салаты, роллы и горячие блюда на ближайшие периоды</div>
        <nav><a class="{'active' if view == 'orders' else ''}" href="/">Заказы</a><a class="{'active' if view == 'analytics' else ''}" href="/analytics">Аналитика</a><a href="/reports">Отчёты</a><a href="/settings">Настройки</a></nav>
      </div>
      <div><a href="/reports">Ежемесячные отчеты</a><div class="muted">{payload["start_day"]} · {payload["horizon_days"]} дней</div></div>
    </header>

    {culinary_strategy}

    <div class="legacy-dashboard">
    <div class="metrics">
      <div class="metric"><span>Сумма заказов</span><strong>{_format_money(payload["budget_total"])} ₽</strong></div>
      <div class="metric"><span>Цикл заказа</span><strong>{payload["order_cycle_days"]} дня</strong></div>
      <div class="metric"><span>Позиций в плане</span><strong>{len(payload["events"])}</strong></div>
    </div>

    <div class="grid">
      <section>
        <h2>Бюджет по категориям</h2>
        {budget_rows}
      </section>

      <section>
        <h2>Логика прогноза</h2>
        <ul>{forecast_logic}</ul>
      </section>
    </div>

    <div class="grid">
      <section>
        <h2>Ближайшие заказы</h2>
        <table>
          <thead>
            <tr><th>Дата</th><th>Категория</th><th>Позиция</th><th>Количество</th><th>Цена</th></tr>
          </thead>
          <tbody>{event_rows}</tbody>
        </table>
      </section>

      <section>
        <h2>Факторы спроса</h2>
        <div class="signal-box">
          <strong>{demand_factors["status"]}</strong><br>
          <span class="muted">{demand_factors["summary"]}</span>
          <p>{demand_factors["effect"]}</p>
        </div>
      </section>
    </div>

    <div class="grid">
      <section>
        <h2>Что прислать для расчета</h2>
        <ul>{next_data}</ul>
      </section>
    </div>
    </div>
  </main>
  <script>
    const dialog = document.getElementById('item-dialog');
    document.querySelectorAll('.detail-button').forEach(button => button.addEventListener('click', () => {{
      const content = document.getElementById('dialog-content');
      content.replaceChildren();
      const label = document.createElement('span'); label.className = 'eyebrow'; label.textContent = 'Детали позиции';
      const title = document.createElement('h2'); title.textContent = button.dataset.name;
      const details = document.createElement('p'); details.textContent = button.dataset.details;
      content.append(label, title, details);
      dialog.showModal();
    }}));
    document.querySelector('.dialog-close')?.addEventListener('click', () => dialog.close());
    dialog?.addEventListener('click', event => {{ if (event.target === dialog) dialog.close(); }});
  </script>
</body>
</html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send_json({"status": "ok"})
            return
        if parsed.path == "/setup":
            params = parse_qs(parsed.query)
            self._send_html(render_setup_html(params.get("error", [""])[0], params.get("message", [""])[0]))
            return
        if parsed.path == "/api/setup/status":
            self._send_json(
                {
                    "configured": has_database_config(),
                    "config_path": str(appdata_env_path()),
                    "storage": REPORT_STORAGE.storage_label(),
                }
            )
            return
        if not self._authorize():
            return
        if parsed.path == "/":
            self._send_html(render_dashboard_html(_payload_from_query(parsed.query)))
            return
        if parsed.path == "/api/dashboard":
            self._send_json(_payload_from_query(parsed.query))
            return
        if parsed.path == "/api/data-status":
            self._send_json(build_data_status())
            return
        if parsed.path == "/analytics":
            self._send_html(render_dashboard_html(_payload_from_query(parsed.query), view="analytics"))
            return
        if parsed.path == "/settings":
            self._send_html(render_settings_html())
            return
        if parsed.path == "/reports":
            params = parse_qs(parsed.query)
            self._send_html(render_reports_html(params.get("message", [""])[0], params.get("error", [""])[0]))
            return
        if parsed.path.startswith("/reports/files/"):
            self._send_report_file(parsed.path.rsplit("/", 1)[-1])
            return
        self._send_error_page(HTTPStatus.NOT_FOUND, "Страница не найдена")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/setup":
            if has_database_config() and not self._authorize():
                return
            fields = self._read_form_urlencoded()
            try:
                save_setup_config(fields)
            except AppConfigError as error:
                self._send_html(render_setup_html(error=str(error), values=fields))
                return
            self._redirect(f"/reports?message={_url_quote('Настройки сохранены')}")
            return
        if not self._authorize():
            return
        if parsed.path != "/reports/upload":
            self._send_error_page(HTTPStatus.NOT_FOUND, "Страница не найдена")
            return
        try:
            report = self._read_upload()
        except ReportValidationError as error:
            self._redirect(f"/reports?error={_url_quote(str(error))}")
            return
        self._redirect(f"/reports?message={_url_quote(f'Загружен отчет {report.original_name}')}")

    def _read_form_urlencoded(self) -> dict[str, str]:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        body = self.rfile.read(content_length).decode("utf-8", errors="replace")
        parsed = parse_qs(body, keep_blank_values=True)
        return {key: values[0] if values else "" for key, values in parsed.items()}

    def _read_upload(self):
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ReportValidationError("Некорректный размер запроса.") from error
        if content_length <= 0 or content_length > MAX_UPLOAD_BYTES + 64 * 1024:
            raise ReportValidationError("Размер запроса превышает допустимый лимит.")
        content_type = self.headers.get("Content-Type", "")
        if not content_type.startswith("multipart/form-data"):
            raise ReportValidationError("Ожидается форма с файлом XLSX.")
        body = self.rfile.read(content_length)
        message = BytesParser(policy=policy.default).parsebytes(
            f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + body
        )
        fields: dict[str, tuple[str | None, bytes]] = {}
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if not name:
                continue
            fields[name] = (part.get_filename(), part.get_payload(decode=True) or b"")
        report_type = fields.get("report_type", (None, b""))[1].decode("utf-8", errors="replace")
        filename, content = fields.get("file", (None, b""))
        if not filename:
            raise ReportValidationError("Выберите XLSX-файл.")
        return REPORT_STORAGE.save(report_type, filename, content)

    def _send_report_file(self, report_id: str) -> None:
        resolved = REPORT_STORAGE.resolve(report_id)
        if resolved is None:
            self._send_error_page(HTTPStatus.NOT_FOUND, "Отчет не найден")
            return
        report, path = resolved
        content = path.read_bytes()
        safe_name = report.original_name.encode("ascii", "ignore").decode() or "report.xlsx"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.send_header("Content-Disposition", f'attachment; filename="{safe_name}"')
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _authorize(self) -> bool:
        username = os.getenv("APP_USERNAME")
        password = os.getenv("APP_PASSWORD")
        if not username and not password:
            return True
        if not username or not password:
            self._send_error_page(HTTPStatus.INTERNAL_SERVER_ERROR, "Авторизация настроена не полностью")
            return False
        expected = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()
        if hmac.compare_digest(self.headers.get("Authorization", ""), expected):
            return True
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("WWW-Authenticate", 'Basic realm="purchase-forecast"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def _redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        print(
            json.dumps(
                {
                    "level": "info",
                    "event": "http_request",
                    "client": self.address_string(),
                    "message": format % args,
                },
                ensure_ascii=False,
            )
        )

    def _send_html(self, content: str) -> None:
        encoded = content.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_error_page(self, status: HTTPStatus, message: str) -> None:
        content = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{status.value}</title><style>
body{{font-family:Arial,sans-serif;background:#f5f6f8;color:#17202a;margin:0}}main{{max-width:760px;margin:40px auto;padding:0 20px}}
section{{background:white;border-radius:14px;padding:22px;box-shadow:0 4px 18px #00000010}}a{{color:#176b55}}
</style></head><body><main><section><h1>{status.value}</h1><p>{escape(message)}</p><p><a href="/">Вернуться к прогнозу</a></p></section></main></body></html>"""
        encoded = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_json(self, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def build_data_status(storage: Any | None = None) -> dict[str, Any]:
    active_storage = storage or REPORT_STORAGE
    reports = active_storage.list()
    counts = {"sales": 0, "waste": 0}
    readable_counts = {"sales": 0, "waste": 0}
    rows = []

    for report in reports:
        if report.report_type in counts:
            counts[report.report_type] += 1
        try:
            resolved = active_storage.resolve(report.id)
        except Exception:
            resolved = None
        readable = resolved is not None
        if readable and report.report_type in readable_counts:
            readable_counts[report.report_type] += 1
        rows.append(
            {
                "id": report.id,
                "type": report.report_type,
                "type_label": ALLOWED_REPORT_TYPES.get(report.report_type, report.report_type),
                "period": f"{report.period_start} — {report.period_end}",
                "period_start": report.period_start,
                "period_end": report.period_end,
                "original_name": report.original_name,
                "size": report.size,
                "readable": readable,
                "status": "доступен" if readable else "ошибка чтения",
            }
        )

    sales_ready = readable_counts["sales"] > 0
    waste_ready = readable_counts["waste"] > 0
    if sales_ready and waste_ready:
        summary = "Продажи участвуют в расчете, списания учитываются."
    elif sales_ready:
        summary = "Продажи участвуют в расчете, списания пока не учитываются."
    else:
        summary = "Для прогноза нужно загрузить читаемый отчет продаж."

    return {
        "storage": active_storage.storage_label(),
        "counts": counts,
        "readable_counts": readable_counts,
        "sales_ready": sales_ready,
        "waste_ready": waste_ready,
        "forecast_ready": sales_ready,
        "summary": summary,
        "reports": rows,
    }


def _count_label(value: int) -> str:
    if value % 10 == 1 and value % 100 != 11:
        return f"{value} файл"
    if value % 10 in {2, 3, 4} and value % 100 not in {12, 13, 14}:
        return f"{value} файла"
    return f"{value} файлов"


def render_data_status_block(status: dict[str, Any]) -> str:
    rows = "".join(
        "<tr>"
        f"<td>{escape(str(item['type_label']))}</td>"
        f"<td>{escape(str(item['period']))}</td>"
        f"<td>{escape(str(item['original_name']))}</td>"
        f"<td>{escape(str(item['status']))}</td>"
        "</tr>"
        for item in status["reports"]
    ) or "<tr><td colspan='4'>Файлы для расчета пока не загружены.</td></tr>"
    ready_class = "ok" if status["forecast_ready"] else "error"
    sales_count = _count_label(int(status["counts"]["sales"]))
    waste_count = _count_label(int(status["counts"]["waste"]))
    return f"""
<section>
  <h2>Используется в расчете</h2>
  <p class="{ready_class}">{escape(str(status["summary"]))}</p>
  <p class="muted">Хранилище: {escape(str(status["storage"]))}. Продажи: {sales_count}. Списания: {waste_count}.</p>
  <table><thead><tr><th>Тип</th><th>Период</th><th>Файл</th><th>Статус</th></tr></thead><tbody>{rows}</tbody></table>
</section>"""


def render_reports_html(message: str = "", error: str = "") -> str:
    rows = "".join(
        f"<tr><td>{escape(ALLOWED_REPORT_TYPES[item.report_type])}</td>"
        f"<td>{escape(item.period_start)} — {escape(item.period_end)}</td>"
        f"<td>{escape(item.original_name)}</td><td>{item.size / 1024:.1f} КБ</td>"
        f"<td><a href='/reports/files/{item.id}'>Скачать</a></td></tr>"
        for item in REPORT_STORAGE.list()
    ) or "<tr><td colspan='5'>Загруженных отчетов пока нет.</td></tr>"
    notice = f"<p class='ok'>{escape(message)}</p>" if message else ""
    failure = f"<p class='error'>{escape(error)}</p>" if error else ""
    storage_info = f"<p class='muted'>Хранилище: {escape(REPORT_STORAGE.storage_label())}</p>"
    notice = storage_info + notice + render_data_status_block(build_data_status())
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ежемесячные отчеты</title><style>
body{{font-family:Arial,sans-serif;background:#f5f6f8;color:#17202a;margin:0}}main{{max-width:1100px;margin:30px auto;padding:0 20px}}
section{{background:white;border-radius:14px;padding:22px;margin:18px 0;box-shadow:0 4px 18px #00000010}}label{{display:block;margin:12px 0 5px}}
input,select,button{{font:inherit;padding:10px}}button{{background:#176b55;color:white;border:0;border-radius:8px;cursor:pointer}}table{{width:100%;border-collapse:collapse}}th,td{{padding:10px;border-bottom:1px solid #ddd;text-align:left}}.ok{{color:#176b55}}.error{{color:#b42318}}.muted{{color:#607069}}a{{color:#176b55}}
</style></head><body><main><p><a href="/">← К прогнозу</a></p><h1>Ежемесячная отчетность</h1>
{notice}{failure}<section><h2>Загрузить файл</h2><form method="post" action="/reports/upload" enctype="multipart/form-data">
<label for="report_type">Тип отчета</label><select id="report_type" name="report_type"><option value="sales">Продажи</option><option value="waste">Списания</option></select>
<label for="file">Файл XLSX</label><input id="file" name="file" type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" required>
<p><button type="submit">Загрузить отчет</button></p></form><p>Максимальный размер — 10 МБ. Период определяется по датам внутри книги.</p></section>
<section><h2>Архив файлов</h2><table><thead><tr><th>Тип</th><th>Период</th><th>Файл</th><th>Размер</th><th></th></tr></thead><tbody>{rows}</tbody></table></section>
</main></body></html>"""


def reload_report_storage() -> None:
    global REPORT_STORAGE
    REPORT_STORAGE = create_report_storage()


def save_setup_config(values: dict[str, str]) -> Path:
    prepared = {
        "SUPABASE_URL": values.get("SUPABASE_URL", ""),
        "SUPABASE_SERVICE_ROLE_KEY": values.get("SUPABASE_SERVICE_ROLE_KEY", ""),
        "SUPABASE_STORAGE_BUCKET": values.get("SUPABASE_STORAGE_BUCKET", "") or "uploads",
        "APP_USERNAME": values.get("APP_USERNAME", ""),
        "APP_PASSWORD": values.get("APP_PASSWORD", ""),
        "APP_PORT": os.getenv("APP_PORT", "8000"),
    }
    path = write_appdata_env(prepared)
    reload_report_storage()
    return path


def render_setup_html(error: str = "", message: str = "", values: dict[str, str] | None = None) -> str:
    values = values or {}
    notice = f"<p class='ok'>{escape(message)}</p>" if message else ""
    failure = f"<p class='error'>{escape(error)}</p>" if error else ""
    supabase_url = escape(values.get("SUPABASE_URL", os.getenv("SUPABASE_URL", "")))
    bucket = escape(values.get("SUPABASE_STORAGE_BUCKET", os.getenv("SUPABASE_STORAGE_BUCKET", "uploads") or "uploads"))
    username = escape(values.get("APP_USERNAME", os.getenv("APP_USERNAME", "")))
    configured = "подключена" if has_database_config() else "не настроена"
    config_path = escape(str(appdata_env_path()))
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Первичная настройка</title><style>
body{{font-family:Arial,sans-serif;background:#f5f6f8;color:#17202a;margin:0}}main{{max-width:860px;margin:30px auto;padding:0 20px}}
section{{background:white;border-radius:14px;padding:22px;margin:18px 0;box-shadow:0 4px 18px #00000010}}label{{display:block;margin:14px 0 5px}}
input,button{{font:inherit;padding:10px;box-sizing:border-box}}input{{width:100%;max-width:680px}}button{{background:#176b55;color:white;border:0;border-radius:8px;cursor:pointer}}.ok{{color:#176b55}}.error{{color:#b42318}}.muted{{color:#607069}}a{{color:#176b55}}
</style></head><body><main><h1>Первичная настройка</h1>
<section>
  <p class="muted">База данных сейчас: {configured}. Настройки будут сохранены в {config_path}.</p>
  {notice}{failure}
  <form method="post" action="/setup">
    <label for="SUPABASE_URL">URL проекта Supabase</label>
    <input id="SUPABASE_URL" name="SUPABASE_URL" value="{supabase_url}" placeholder="https://example.supabase.co" required>
    <label for="SUPABASE_SERVICE_ROLE_KEY">Secret key Supabase</label>
    <input id="SUPABASE_SERVICE_ROLE_KEY" name="SUPABASE_SERVICE_ROLE_KEY" type="password" autocomplete="new-password" required>
    <label for="SUPABASE_STORAGE_BUCKET">Bucket для отчетов</label>
    <input id="SUPABASE_STORAGE_BUCKET" name="SUPABASE_STORAGE_BUCKET" value="{bucket}" placeholder="uploads">
    <label for="APP_USERNAME">Логин для входа в сервис</label>
    <input id="APP_USERNAME" name="APP_USERNAME" value="{username}" placeholder="manager">
    <label for="APP_PASSWORD">Пароль для входа в сервис</label>
    <input id="APP_PASSWORD" name="APP_PASSWORD" type="password" autocomplete="new-password">
    <p><button type="submit">Сохранить настройки</button></p>
  </form>
</section>
<section><p><a href="/reports">Перейти к отчетам</a></p></section>
</main></body></html>"""


def render_settings_html() -> str:
    return """<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Настройки прогноза</title><style>
body{font-family:Inter,Segoe UI,Arial,sans-serif;background:#f6f2ec;color:#20231f;margin:0}main{max-width:820px;margin:30px auto;padding:0 20px}
section{background:white;border:1px solid #ded8ce;border-radius:10px;padding:22px;margin:18px 0}dt{font-weight:700;margin-top:14px}dd{margin:4px 0;color:#687069}a{color:#365f4c}
</style></head><body><main><p><a href="/">← Заказы</a> · <a href="/analytics">Аналитика</a> · <a href="/reports">Отчёты</a></p>
<h1>Настройки</h1><section><h2>Текущая конфигурация</h2><dl>
<dt>Город</dt><dd>Санкт-Петербург, 59.9343 / 30.3351</dd>
<dt>Погода</dt><dd>MET Norway, обновление раз в 180 минут</dd>
<dt>Расписание заказов</dt><dd>Пн+Вт, Ср+Чт, Пт+Сб+Вс</dd>
<dt>Отсутствующие значения</dt><dd>Не считаются нулевыми продажами</dd>
</dl><p>Изменяемые настройки будут добавлены после проверки нового рабочего экрана.</p></section></main></body></html>"""


def _url_quote(value: str) -> str:
    from urllib.parse import quote

    return quote(value)


def server_port() -> int:
    return int(os.getenv("PORT", os.getenv("APP_PORT", "8000")))


def run_server() -> None:
    port = server_port()
    server = ThreadingHTTPServer(("0.0.0.0", port), DashboardHandler)
    print(json.dumps({"level": "info", "event": "server_started", "port": port}))
    server.serve_forever()


def _payload_from_query(query: str) -> dict[str, Any]:
    params = parse_qs(query)
    start_raw = params.get("start", [date.today().isoformat()])[0]
    days_raw = params.get("days", ["14"])[0]
    return build_dashboard_payload(
        start_day=date.fromisoformat(start_raw),
        horizon_days=int(days_raw),
    )


def _localize_budget(budget: dict[str, float]) -> dict[str, float]:
    return {_category_label(category): amount for category, amount in budget.items()}


def _category_label(category: str) -> str:
    return CATEGORY_LABELS.get(category, category)


def _item_label(item_name: str) -> str:
    return ITEM_LABELS.get(item_name, item_name)


def _unit_label(unit: str) -> str:
    return UNIT_LABELS.get(unit, unit)


def _format_money(value: float) -> str:
    return _format_number(value)


def _format_number(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


if __name__ == "__main__":
    run_server()
