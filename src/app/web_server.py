from __future__ import annotations

import json
import os
import base64
import hmac
import re
import logging
from dataclasses import replace
from email import policy
from email.parser import BytesParser
from html import escape
from datetime import date, datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from src.app.cli import load_purchase_items
from src.app.analytics_views import render_loss_kpi, render_matrix, render_traffic
from src.app.category_orders import check_category_reserves, render_category_reserves
from src.app.loss_planning import monthly_loss_plan, render_monthly_loss_plan
from src.infrastructure.loss_plans import loss_plan_path, save_loss_plan
from src.app.demand_views import model_details, number, render_demand_method
from src.app.order_exports import OrderExportStore, prepare_order_download
from src.app.order_navigation import upcoming_order_dates, render_order_date_tabs
from src.app.order_finance import (
    finance_cells, finance_details, status_details, status_explanation, assortment_status,
    order_totals, render_order_totals,
)
from src.app.order_interactions import ORDER_DETAILS_SCRIPT
from src.infrastructure.order_workbook import MIME_TYPE as ORDER_WORKBOOK_MIME
from src.domain.menu_catalog import (
    apply_menu_state,
    build_menu_catalog,
    enabled_menu_names,
    load_menu_state,
    toggle_menu_item,
    toggle_menu_supply_type,
)
from src.domain.planning import build_purchase_calendar, estimate_calendar_budget
from src.domain.production import daily_production_plan
from src.domain.demand_planning import plan_demand, recent_history, DEFAULT_SERVICE_LEVEL, DEFAULT_PROFIT_TOLERANCE
from src.domain.culinary import is_culinary_category
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
    validate_report_content,
    SupabaseReportStorage,
)
from src.infrastructure.app_config import (
    AppConfigError,
    appdata_env_path,
    has_database_config,
    write_appdata_env,
)
from src.infrastructure.paths import project_path
from src.infrastructure.weather import load_met_norway_forecast
from src.infrastructure.report_formats import is_detailed_waste, waste_lines, receipt_days
from src.infrastructure.report_analytics import (
    product_key, load_receipt_series, dish_economics, read_detailed_waste,
    monthly_loss_kpi, traffic_history, loss_group_totals,
)
from src.infrastructure.assortment_catalog import load_candidates
from src.infrastructure.menu_uploads import menu_upload_directory
from src.domain.assortment import rank_profit_rows, propose_matrix
from src.domain.order_policy import (
    DISPLAY_CAPACITY, STAFF_PORTIONS, MOSCOW, moscow_now, earliest_delivery,
    delivery_deadline,
)
from src.domain.traffic import traffic_adjustment, allocate_staff
from src.domain.staff_meals import eligible_staff_demand


DEFAULT_ITEMS_PATH = project_path("data/examples/purchase_items.json")
DEFAULT_SALES_PATH = project_path("data/local/culinary_sales_june_july.xlsx")
DEFAULT_WASTE_PATH = project_path("data/local/culinary_waste_june_july.xlsx")
DEFAULT_SHELF_LIFE_PATH = project_path("data/local/Хранение и сроки годности, реализации.xlsx")
BUNDLED_PREVIOUS_ORDERS_DIR = project_path("Прошлые заказы")
DEFAULT_PREVIOUS_ORDERS_DIR = menu_upload_directory()
DEFAULT_MENU_STATE_PATH = project_path("data/menu/menu-state.json")
DEFAULT_ORDER_CYCLE_DAYS = 2
MAX_BATCH_FILES = 100
MAX_BATCH_UPLOAD_MB = 250
MAX_BATCH_UPLOAD_BYTES = MAX_BATCH_UPLOAD_MB * 1024 * 1024
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
    now: datetime | None = None,
    service_level: float = DEFAULT_SERVICE_LEVEL,
    profit_tolerance: float = DEFAULT_PROFIT_TOLERANCE,
    loss_month: date | None = None,
) -> dict[str, Any]:
    clock = now or moscow_now()
    clock = clock.replace(tzinfo=MOSCOW) if clock.tzinfo is None else clock.astimezone(MOSCOW)
    default_start = clock.date() + timedelta(days=1 if clock.hour >= 18 else 0)
    start = max(start_day or default_start, clock.date())
    delivery_start = earliest_delivery(clock, start)
    items = load_purchase_items(items_path)
    events = build_purchase_calendar(items, start, horizon_days)
    budget = estimate_calendar_budget(events)

    return {
        "generated_at": clock.date().isoformat(),
        "start_day": start.isoformat(),
        "order_dates": upcoming_order_dates(clock),
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
            "оцениваем разброс продаж в недавних сопоставимых днях и окнах поставок",
            "учитываем стоимость непроданной порции и упущенный вклад при нехватке",
            "добавляем резерв к желаемому наличию в пределах допустимой цены потерь",
            "распределяем пять порций питания в день между всей кулинарией один раз",
            "проверяем срок годности и показываем неопределенность без технической кратности",
        ],
        "demand_factors": {
            "status": "демо-логика",
            "summary": "В рабочем прогнозе учитываются погода и история продаж по дням недели. Статус источника и коэффициенты показаны в расчете.",
            "effect": "Холод и дождь могут поднимать спрос на супы и горячие обеды; жара чаще смещает спрос в салаты и роллы. После твоих выгрузок эти коэффициенты лучше считать по факту продаж.",
        },
        "next_data": [
            "список позиций кулинарии: SKU, название, категория, себестоимость, срок годности",
            "заказы и продажи за последние периоды по дням",
            "остатки перед заказом и фактические списания",
            "кратность заказа или производственной партии",
            "пометки по дням: будни, выходные, погода, акции, локальные события",
        ],
        "culinary_strategy": build_culinary_strategy_payload(
            reference_day=delivery_start - timedelta(days=1), production_start_day=start,
            ordering_now=clock, service_level=service_level, profit_tolerance=profit_tolerance, loss_month=loss_month),
    }


def build_culinary_strategy_payload(
    sales_path: Path = DEFAULT_SALES_PATH,
    waste_path: Path = DEFAULT_WASTE_PATH,
    shelf_life_path: Path = DEFAULT_SHELF_LIFE_PATH,
    start_day: date = date(2026, 6, 1),
    end_day: date | None = None,
    order_days: int = DEFAULT_ORDER_CYCLE_DAYS,
    reference_day: date | None = None,
    production_start_day: date | None = None,
    ordering_now: datetime | None = None,
    service_level: float = DEFAULT_SERVICE_LEVEL,
    profit_tolerance: float = DEFAULT_PROFIT_TOLERANCE,
    loss_month: date | None = None,
) -> dict[str, Any] | None:
    live_weather = load_met_norway_forecast()
    # Не оставляем предыдущий сетевой прогноз активным после отключения провайдера.
    for day in list(WEATHER_BY_DATE):
        if WEATHER_BY_DATE[day].get('source') == 'MET Norway':
            del WEATHER_BY_DATE[day]
    if live_weather is not None:
        WEATHER_BY_DATE.update(live_weather.days)
    uploaded_sales_paths = REPORT_STORAGE.paths("sales")
    allow_local_fallback = REPORT_STORAGE.storage_label() != 'Supabase'
    effective_sales_paths = uploaded_sales_paths or ([sales_path] if allow_local_fallback and sales_path.exists() else [])
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
    menu_state = load_menu_state(DEFAULT_MENU_STATE_PATH)
    menu_catalog = apply_menu_state(_read_menu_catalog(), menu_state)
    enabled_names = {product_key(item.name) for item in menu_catalog if item.enabled}
    disabled_names = {product_key(name) for name in menu_state.disabled} | {product_key(item.name) for item in menu_catalog if not item.enabled}
    own_production_names = {product_key(item.name) for item in menu_catalog if item.own_production}
    menu_coverage = build_menu_coverage(scanned_items, menu_catalog)
    items = [
        item
        for item in scanned_items
        if product_key(item.name) not in disabled_names
        and (not enabled_names or product_key(item.name) in enabled_names)
        and 'снэк' not in item.category.casefold() and 'снек' not in item.category.casefold()
    ]
    items = align_sales_with_menu(items, menu_catalog)
    uploaded_waste_paths = REPORT_STORAGE.paths("waste")
    effective_waste_paths = uploaded_waste_paths or ([waste_path] if allow_local_fallback and waste_path.exists() else [])
    waste_counts = _combined_waste_counts(effective_waste_paths, items, effective_start_day, actual_end_day)
    waste_by_date = _combined_waste_by_date(effective_waste_paths, items, effective_start_day, actual_end_day)
    shelf_life = {normalize_name(item.name): {'days': 3, 'source': 'Подтверждено пользователем: 3 дня'} for item in items}
    for item in items:
        if normalize_name(item.name).startswith(('онигири ', 'темаки ', 'блины ')):
            shelf_life[normalize_name(item.name)] = {'days': 2, 'source': 'Подтверждено пользователем: 2 дня'}
    recommendations = build_recommendations(items, order_days, waste_counts, shelf_life, include_low_volume=True)
    economics = dish_economics(effective_sales_paths, effective_waste_paths,
                              date(actual_end_day.year, actual_end_day.month, 1), actual_end_day)
    profit_ranks = {row['key']: index for index,row in enumerate(rank_profit_rows(economics['rows']))}
    known_economics = {row['key']: row for row in economics['rows']}
    recommendations = [row for row in recommendations if product_key(str(row['name'])) not in known_economics
                       or product_key(str(row['name'])) in profit_ranks]
    recommendations.sort(key=lambda row: (profit_ranks.get(product_key(str(row['name'])), 10000),
                                          -float(row['menu_score'])))
    tt_prefixes = ('каша овсяная ', 'каша рисовая ', 'омлет с ветчиной ', 'сырники классические ', 'запеканка ')
    recommendations = [row for row in recommendations
                       if product_key(str(row['name'])) not in own_production_names
                       and not product_key(str(row['name'])).startswith(tt_prefixes)]
    daily_menu = _with_supply_types(
        _with_decision_explanations(build_daily_menu(recommendations, ranked=True, capacity=DISPLAY_CAPACITY)),
        own_production_names,
    )
    matrix = propose_matrix(load_candidates(menu_catalog), economics['rows'], DISPLAY_CAPACITY)
    if len(matrix['rows']) == DISPLAY_CAPACITY and economics['rows'] and menu_catalog:
        historical = {product_key(str(row['name'])): row for row in build_daily_menu(
            recommendations, ranked=True, capacity=len(recommendations))}
        selected = []
        for candidate in matrix['rows']:
            key = candidate['key']
            row = historical.get(key)
            if row is None and candidate['role'] != 'experiment':
                continue
            if row is None:
                row = {'category': candidate['category'], 'name': candidate['name'], 'order_for_2_days': 3,
                       'sales_june_july': 0, 'shelf_life_days': 2 if key.startswith(('онигири ', 'темаки ', 'блины ')) else 3,
                       'waste_count': 0, 'waste_risk': 'нет истории: тест', 'active_days': 0,
                       'average_per_day': 0, 'abc_class': 'новинка', 'stability': 'нет истории',
                       'shelf_life_risk': 'контроль срока', 'menu_role': 'основная витрина',
                       'strategy': 'Тест: 3 порции на поставку, спрос и маржа пока не подтверждены.'}
            selected.append({**row, 'matrix_role': candidate['role'], 'is_experiment': candidate['role'] == 'experiment'})
        daily_menu = _with_supply_types(_with_decision_explanations(selected), own_production_names)
    forecast_reference_day = reference_day or date.today() - timedelta(days=1)
    rain_impact = _rain_sales_impact(items, effective_start_day, actual_end_day)
    receipts, receipt_conflicts = load_receipt_series(REPORT_STORAGE.paths('receipts'))
    checks = {day: row.checks for day,row in receipts.items()}

    production_start = production_start_day or forecast_reference_day + timedelta(days=1)
    forecast_as_of = production_start
    if ordering_now is not None:
        local_clock = ordering_now.replace(tzinfo=MOSCOW) if ordering_now.tzinfo is None else ordering_now.astimezone(MOSCOW)
        forecast_as_of = min(production_start, local_clock.date() + timedelta(days=1 if local_clock.hour >= 18 else 0))
    production_horizon = max(14, (production_start - forecast_as_of).days + 14)
    production_items = [
        {'key': product_key(item.name), 'name': item.name, 'category': item.group}
        for item in menu_catalog if item.enabled and item.own_production
        and not any(tag in item.group.casefold() for tag in ('снэк', 'снек'))
    ]
    for item in scanned_items:
        key = product_key(item.name)
        if key.startswith(tt_prefixes) and key not in disabled_names and key not in {p['key'] for p in production_items}:
            production_items.append({'key': key, 'name': item.name, 'category': 'Завтраки'})
            own_production_names.add(key)
    production_history: dict[str, dict[date, float]] = {}
    for item in scanned_items:
        values = production_history.setdefault(product_key(item.name), {})
        for day, quantity in item.by_date.items():
            values[day] = values.get(day, 0) + quantity
    production_factors = {
        (item['key'], forecast_as_of + timedelta(days=offset)):
        _weather_factor(item['category'], [forecast_as_of + timedelta(days=offset)], float(rain_impact['applied_factor']))
        for item in production_items for offset in range(production_horizon)
    }
    production = daily_production_plan(production_items, forecast_as_of, production_horizon, production_history, production_factors)
    staff_plan = {}
    staff_balance: dict[str, float] = {}
    production_keys = {p['key'] for p in production_items}
    supplier_menu = [row for row in daily_menu if product_key(str(row['name'])) not in production_keys]
    for entry in production:
        day = date.fromisoformat(entry['date'])
        demand = {}
        for row in supplier_menu:
            key = product_key(str(row['name']))
            if row.get('is_experiment'):
                demand[key] = 0
                continue
            if day.weekday() == 6 and int(row.get('shelf_life_days', 3)) <= 2:
                demand[key] = 0
                continue
            history = recent_history(production_history.get(key, {}), forecast_as_of)
            matching = [q for d,q in history.items() if d < forecast_as_of and d.weekday() == day.weekday()]
            values = matching or [q for d,q in history.items() if d < forecast_as_of]
            demand[key] = sum(values) / len(values) if values else 0
        for row in entry['rows']:
            demand[row['key']] = float(row['base_quantity'] or 0)
        staff_plan[entry['date']] = allocate_staff(eligible_staff_demand(demand), STAFF_PORTIONS, staff_balance)
        for row in entry['rows']:
            history = recent_history(production_history.get(row['key'], {}), forecast_as_of)
            adjustment = traffic_adjustment(checks, history, day, forecast_as_of)
            row['receipt_factor'] = adjustment['factor']
            row['staff_quantity'] = staff_plan[entry['date']].get(row['key'], 0)
            price, cost = _unit_economics(known_economics.get(row['key']))
            model = plan_demand(history, [day], forecast_as_of, [row['staff_quantity']],
                                [row['weather_factor'] * adjustment['factor']], price, cost, service_level,
                                profit_tolerance=profit_tolerance)
            row.update(model=model, quantity=model['quantity'], guest_quantity=model['guest_quantity'],
                       need=model['quantity'], batch_size=1, batch_extra=0)
        entry['total'] = sum(row['quantity'] or 0 for row in entry['rows'])
    for entry in production:
        day = date.fromisoformat(entry['date'])
        entry['weather'] = str(WEATHER_BY_DATE.get(day, {}).get('summary', 'нет прогноза; погодная поправка не применяется'))

    future = _future_orders(items, supplier_menu, waste_by_date, forecast_reference_day, 4,
                            float(rain_impact['applied_factor']), checks)
    rain_factor = float(rain_impact['applied_factor'])

    def group_factors(category, days, history):
        return [_weather_factor(category, [day], rain_factor)
                * traffic_adjustment(checks, history, day, forecast_as_of)['factor'] for day in days]

    for period in future:
        def plan_supplier_row(row, guest_limit=None):
            key = product_key(str(row['name']))
            usable = min(period['days'], int(row['shelf_life_days']))
            days = [date.fromisoformat(d['date']) for d in row['daily_forecast'][:usable]]
            history = recent_history(production_history.get(key, {}), forecast_as_of)
            staff = [staff_plan.get(str(day), {}).get(key, 0) for day in days]
            factors, adjustments = [], []
            for day in days:
                adjustment = traffic_adjustment(checks, history, day, forecast_as_of)
                adjustments.append(adjustment['factor'])
                factors.append(_weather_factor(str(row['category']), [day], float(rain_impact['applied_factor'])) * adjustment['factor'])
            price, cost = _unit_economics(known_economics.get(key))
            model = plan_demand(history, days, forecast_as_of, staff, factors, price, cost,
                                service_level, trial_quantity=3 if row.get('is_experiment') else None,
                                profit_tolerance=profit_tolerance, guest_limit=guest_limit)
            row['model'] = model
            for index, entry in enumerate(row['daily_forecast']):
                planned = model['daily'][index] if index < len(model['daily']) else {'quantity':0, 'guest_quantity':0, 'staff_quantity':0}
                entry.update(planned, receipt_factor=adjustments[index] if index < usable else 1)
            row['staff_quantity'] = sum(d['staff_quantity'] for d in row['daily_forecast'])
            row['forecast_quantity'] = sum(d['quantity'] for d in row['daily_forecast'])
            row['quantity_unknown'] = model['quantity'] is None
            row['display_extra'] = 0
            row['remaining_is_expiry_risk'] = usable >= int(row['shelf_life_days'])
        for row in period['rows']:
            plan_supplier_row(row)
        period['category_reserves'] = check_category_reserves(
            period['rows'], production_history,
            [date.fromisoformat(day['date']) for day in period['daily_totals']],
            forecast_as_of, service_level, group_factors, plan_supplier_row,
        )
        period['deadline'] = delivery_deadline(date.fromisoformat(period['start'])).isoformat()
        period['display_extra'] = sum(row['display_extra'] for row in period['rows'])
        period['supplier_quantity'] = sum(row['forecast_quantity'] for row in period['rows'])
        period['production_quantity'] = sum(d['total'] for d in production if period['start'] <= d['date'] <= period['end'])
        period['total_quantity'] = period['supplier_quantity'] + period['production_quantity']
        period['staff_quantity'] = sum(sum(staff_plan.get(d['date'], {}).values()) for d in period['daily_totals'])
        for day in period['daily_totals']:
            day['quantity'] = sum(next(d['quantity'] for d in row['daily_forecast'] if d['date'] == day['date']) for row in period['rows'])
            day['quantity'] += sum(p['total'] for p in production if p['date'] == day['date'])

    traffic_forecast = [dict(date=entry['date'], **traffic_adjustment(
        checks, {day for item in items for day in item.by_date},
        date.fromisoformat(entry['date']), forecast_as_of))
        for period in future for entry in period['daily_totals']]

    return {
        'monthly_loss_plan': monthly_loss_plan(loss_month, effective_sales_paths, effective_waste_paths, receipts)
            if loss_month else None,
        'production_days': [day for day in production if day['date'] >= production_start.isoformat()][:7],
        'forecast_as_of': forecast_as_of.isoformat(),
        'staff_daily_portions': STAFF_PORTIONS,
        'staff_meals_policy': {'daily_need': STAFF_PORTIONS, 'excluded': ['онигири', 'темаки'],
                              'priority': 'годные порции с истекающим сегодня сроком, затем другие блюда витрины',
                              'actual_expiring_stock_known': False,
                              'allocation_is_forecast': True},
        'receipt_days': len(checks),
        'receipt_conflicts': receipt_conflicts,
        'economics': economics,
        'loss_kpi': monthly_loss_kpi(economics, receipts, loss_group_totals(
            effective_sales_paths, effective_waste_paths,
            date(actual_end_day.year, actual_end_day.month, 1), actual_end_day)),
        'matrix_proposal': {**matrix, 'applied_to_order': len(daily_menu) == DISPLAY_CAPACITY and bool(economics['rows'])},
        'menu_source': _menu_source_info(menu_catalog, known_economics),
        'traffic_history': traffic_history(receipts, actual_end_day),
        'traffic_forecast': traffic_forecast,
        'ordering_now': ordering_now.isoformat() if ordering_now else None,
        'demand_model': {'name': 'Спрос, прибыль и наличие', 'service_level': service_level,
                         'profit_tolerance': profit_tolerance,
                         'batch_constraints': False, 'stockout_times_known': False},
        'unavailable_reports': list(getattr(REPORT_STORAGE, 'unavailable_reports', {}).values()),
        "period": f"{effective_start_day.isoformat()}..{actual_end_day.isoformat()}",
        "weather_city": "Санкт-Петербург",
        "weather_source": live_weather.source if live_weather else "встроенные данные",
        "weather_updated_at": live_weather.updated_at if live_weather else None,
        "weather_stale": live_weather.stale if live_weather else False,
        "order_days": order_days,
        "menu_catalog": {
            "total": len(menu_catalog),
            "enabled": sum(1 for item in menu_catalog if item.enabled),
            "disabled": sum(1 for item in menu_catalog if not item.enabled),
            "own_production": sum(1 for item in menu_catalog if item.own_production),
        },
        "menu_coverage": menu_coverage,
        "total_quantity": sum(int(item["order_for_2_days"]) for item in daily_menu),
        "summary": daily_menu_summary(daily_menu),
        "category_totals": _category_totals(daily_menu),
        "role_groups": _group_menu_by_role(daily_menu),
        "retrospective_orders": _retrospective_orders(items, daily_menu, reference_day=forecast_reference_day),
        "future_orders": future,
        "rain_sales_impact": rain_impact,
        "weather_sales_summary": _weather_sales_summary(items, effective_start_day, actual_end_day),
        "waste_leaders": _with_decision_explanations(waste_leaders(recommendations, limit=12)),
    }


def align_sales_with_menu(items: list[Any], menu_catalog: list[Any]) -> list[Any]:
    """Использовать рабочие группы меню, сохраняя исходные файлы отчетов."""
    catalog = {product_key(item.name): item for item in menu_catalog}
    groups = {'Супы', 'Горячее', 'Салаты', 'Завтраки', 'Роллы'}
    aligned = []
    for item in items:
        menu_item = catalog.get(product_key(item.name))
        if menu_item is not None:
            item = replace(item, name=menu_item.name,
                           category=menu_item.group if menu_item.group in groups else item.category)
        aligned.append(item)
    return _merge_sales_items([aligned])


def _unit_economics(row: dict | None) -> tuple[float | None, float | None]:
    if not row or row.get('sold', 0) <= 0:
        return None, None
    price = row['revenue'] / row['sold']
    cost = (row['revenue'] - row['gross_profit']) / row['sold']
    return (price, cost) if price > 0 and 0 < cost <= price else (None, None)


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


def load_current_menu_catalog() -> list[Any]:
    catalog = _read_menu_catalog()
    return apply_menu_state(catalog, load_menu_state(DEFAULT_MENU_STATE_PATH))


def _read_menu_catalog() -> list[Any]:
    source = DEFAULT_PREVIOUS_ORDERS_DIR
    if source == menu_upload_directory() and not list(source.glob('*.xlsx')):
        source = BUNDLED_PREVIOUS_ORDERS_DIR
    return build_menu_catalog(source)


def _menu_source_info(menu_catalog: list[Any], economics: dict) -> dict:
    paths = list(DEFAULT_PREVIOUS_ORDERS_DIR.glob('*.xlsx'))
    latest = max(paths, key=lambda p: p.stat().st_mtime_ns) if paths else None
    return {'filename': latest.name if latest else 'исторические заказы', 'available': len(menu_catalog),
            'without_november_sales': [{'sku': getattr(item, 'sku', ''), 'name': item.name}
                for item in menu_catalog if item.enabled and product_key(item.name) not in economics],
            'notice': 'Перечень без количеств включает все активные блюда. Пометка «снято» исключает блюдо. Отсутствие продаж не доказывает, что блюдо новое.'}


def build_menu_coverage(sales_items: list[Any], menu_items: list[Any]) -> dict[str, Any]:
    menu_names = {product_key(item.normalized_name) for item in menu_items}
    enabled_names = {product_key(item.normalized_name) for item in menu_items if item.enabled}
    disabled_names = {product_key(item.normalized_name) for item in menu_items if not item.enabled}
    own_names = {product_key(item.normalized_name) for item in menu_items if item.own_production}
    own_names.update(product_key(item.name) for item in sales_items if product_key(item.name).startswith(
        ('каша овсяная ', 'каша рисовая ', 'омлет с ветчиной ', 'сырники классические ', 'запеканка ')))
    buckets = {
        "in_menu": {"items": 0, "quantity": 0, "rows": []},
        "own_production": {"items": 0, "quantity": 0, "rows": []},
        "outside_menu": {"items": 0, "quantity": 0, "rows": []},
        "disabled": {"items": 0, "quantity": 0, "rows": []},
    }
    for item in sales_items:
        normalized = product_key(item.name)
        if any(tag in item.category.casefold() for tag in ('снэк', 'снек')):
            continue
        if normalized not in menu_names and not is_culinary_category(item.category):
            continue
        quantity = sum(int(value) for value in item.by_date.values())
        if normalized in own_names:
            bucket_name = "own_production"
            reason = "собственное производство"
        elif normalized in disabled_names:
            bucket_name = "disabled"
            reason = "выключено в меню"
        elif normalized not in menu_names:
            bucket_name = "outside_menu"
            reason = "нет в текущем меню"
        else:
            bucket_name = "in_menu"
            reason = "есть в меню"
        row = {
            "name": item.name,
            "category": item.category,
            "quantity": quantity,
            "reason": reason,
        }
        bucket = buckets[bucket_name]
        bucket["items"] = int(bucket["items"]) + 1
        bucket["quantity"] = int(bucket["quantity"]) + quantity
        bucket["rows"].append(row)
    for bucket in buckets.values():
        bucket["rows"] = sorted(
            bucket["rows"],
            key=lambda row: (-int(row["quantity"]), str(row["category"]), str(row["name"])),
        )[:12]
    return {
        **buckets,
        'period_start': str(min((day for item in sales_items for day in item.by_date), default='')),
        'period_end': str(max((day for item in sales_items for day in item.by_date), default='')),
        "menu_enabled_items": len(enabled_names),
        "menu_disabled_items": len(disabled_names),
        "menu_own_production_items": len(own_names),
    }


def _with_supply_types(items: list[dict[str, object]], own_production_names: set[str]) -> list[dict[str, object]]:
    result = []
    for item in items:
        supply_type = "own_production" if product_key(str(item["name"])) in own_production_names else "supplier"
        result.append(
            {
                **item,
                "supply_type": supply_type,
                "supply_label": "Собственное производство" if supply_type == "own_production" else "Поставка",
            }
        )
    return result


def save_menu_order_upload(filename: str, content: bytes, target_dir: Path = DEFAULT_PREVIOUS_ORDERS_DIR) -> Path:
    if not filename.lower().endswith(".xlsx"):
        raise ReportValidationError("Для меню нужен XLSX-файл заказа в производство.")
    if not content:
        raise ReportValidationError("Файл пустой.")
    from tempfile import TemporaryDirectory
    from src.domain.menu_catalog import read_culinary_order_sheet, extract_order_menu_items
    with TemporaryDirectory() as directory:
        check_path = Path(directory) / 'menu.xlsx'
        check_path.write_bytes(content)
        try:
            rows = read_culinary_order_sheet(check_path)
            if not extract_order_menu_items(rows, include_unordered=True):
                raise ValueError('нет доступных блюд с артикулом и названием')
        except Exception as error:
            raise ReportValidationError('Не удалось прочитать меню: нужны колонки «Артикул» и «Товар».') from error
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-zА-Яа-яЁё0-9._ -]+", "_", Path(filename).name).strip()
    if not safe_name:
        safe_name = "previous-order.xlsx"
    if not safe_name.lower().endswith(".xlsx"):
        safe_name += ".xlsx"
    path = target_dir / safe_name
    path.write_bytes(content)
    return path


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
    if is_detailed_waste(rows):
        for line in waste_lines(rows):
            if line.staff or not start_day <= line.day <= end_day:
                continue
            for item_name in normalized_names:
                if product_key(item_name) == product_key(line.name):
                    counts[item_name][line.day] = counts[item_name].get(line.day, 0) + 1
        return counts
    for row in rows[4:]:
        if len(row) < 4:
            continue
        if len(row) > 10 and any(word in str(row[10]).casefold() for word in ('сотрудник', 'персонал')):
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
        for day in item.by_date
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
    checks: dict[date, int] | None = None,
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
            checks,
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
    checks: dict[date, int] | None = None,
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
        for item in rows:
            if int(item.get('shelf_life_days', 3)) <= 2:
                for entry in item['daily_forecast'][2:]:
                    entry['quantity'] = 0
                    entry['shelf_life_note'] = 'Пятничная партия: только пятница и суббота'
    if checks:
        for item in rows:
            source = item_by_name.get(str(item['name']))
            for entry in item['daily_forecast']:
                adjustment = traffic_adjustment(checks, source.by_date if source else {}, date.fromisoformat(entry['date']), period_start)
                entry['receipt_factor'] = adjustment['factor']
                entry['quantity'] = max(0, round(entry['quantity'] * adjustment['factor']))
    if days == 3 or checks:
        rows = [
            {**item, "forecast_quantity": sum(int(day["quantity"]) for day in item["daily_forecast"])}
            for item in rows
        ]
    for item in rows:
        if item.get('is_experiment'):
            usable = min(days, int(item['shelf_life_days']))
            trial = _daily_distribution(None, str(item['category']), period_days[:usable], 3, rain_traffic_factor)
            quantities = {entry['date']: entry['quantity'] for entry in trial}
            for entry in item['daily_forecast']:
                entry['quantity'] = quantities.get(entry['date'], 0)
                entry['receipt_factor'] = 1.0
            item['forecast_quantity'] = 3
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
        "supplier_quantity": sum(
            int(item["forecast_quantity"]) for item in rows if item.get("supply_type") != "own_production"
        ),
        "production_quantity": sum(
            int(item["forecast_quantity"]) for item in rows if item.get("supply_type") == "own_production"
        ),
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
        return "трехдневное окно: пятница, суббота и воскресенье рассчитаны отдельно по истории соответствующего дня недели; пятничные позиции со сроком 2 дня рассчитаны только на пятницу и субботу, без воскресного пополнения"
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
        f"<a class='next-order-card' href='/?start={period['start']}&days=14&service={round(strategy.get('demand_model', {}).get('service_level', DEFAULT_SERVICE_LEVEL) * 100)}&reserve_cost={round(strategy.get('demand_model', {}).get('profit_tolerance', DEFAULT_PROFIT_TOLERANCE) * 100)}'>"
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
        alerts.append(f"{short_shelf} поз. с коротким сроком: воскресенье исключено")
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
      <p>Заказ до <strong>{escape(str(current.get('deadline', ''))).replace('T', ' ')}</strong> (Москва).
      Поставка утром до открытия. Правило: на послезавтра до 18:00 МСК, только Пн/Ср/Пт.</p>
      <p>В плане питание сотрудников: {current.get('staff_quantity', 0)} порций по поставке и ТТ вместе.
      Дополнение до рекомендуемых 3 порций на заказанную позицию: {current.get('display_extra', 0)} шт.; это запас для выкладки, а не дополнительный спрос.</p>
      <div class="alert-row">{alert_html}</div>
      <div class="table-wrap">
        <table class="order-table"><thead><tr><th>Позиция</th>{day_headings}<th>Итого</th><th>Статус</th><th></th></tr></thead><tbody>{rows}</tbody></table>
      </div>
    </section>
    <section class="next-orders"><div class="section-title"><div><span class="eyebrow">Далее</span><h2>Следующие заказы</h2></div><a href="/analytics">Открыть аналитику →</a></div><div class="next-order-grid">{next_cards}</div></section>
    <dialog id="item-dialog"><button class="dialog-close" aria-label="Закрыть">×</button><div id="dialog-content"></div></dialog>
    """


def _render_menu_coverage_block(coverage: dict[str, Any]) -> str:
    if not coverage:
        return ""
    outside = coverage.get("outside_menu", {"items": 0, "quantity": 0, "rows": []})
    disabled = coverage.get("disabled", {"items": 0, "quantity": 0, "rows": []})
    in_menu = coverage.get("in_menu", {"items": 0, "quantity": 0, "rows": []})
    outside_rows = _render_menu_coverage_rows(outside.get("rows", []), empty="Вне меню позиций не найдено.")
    disabled_rows = _render_menu_coverage_rows(disabled.get("rows", []), empty="Выключенных позиций с продажами не найдено.")
    return f"""
      <div class="menu-coverage">
        <div class="coverage-summary">
          <div><span>В меню</span><strong>{in_menu.get("items", 0)} поз. / {in_menu.get("quantity", 0)} шт.</strong></div>
          <div><span>Вне меню</span><strong>{outside.get("items", 0)} поз. / {outside.get("quantity", 0)} шт.</strong></div>
          <div><span>Выключено</span><strong>{disabled.get("items", 0)} поз. / {disabled.get("quantity", 0)} шт.</strong></div>
        </div>
        <details {"open" if int(outside.get("items", 0)) else ""}>
          <summary>Позиции вне меню, которые могут объяснять расхождение</summary>
          <table class="mini-table"><thead><tr><th>Позиция</th><th>Категория</th><th>Продажи</th><th>Причина</th></tr></thead><tbody>{outside_rows}</tbody></table>
        </details>
        <details>
          <summary>Выключенные позиции с продажами</summary>
          <table class="mini-table"><thead><tr><th>Позиция</th><th>Категория</th><th>Продажи</th><th>Причина</th></tr></thead><tbody>{disabled_rows}</tbody></table>
        </details>
      </div>
    """


def _render_menu_coverage_rows(rows: list[dict[str, object]], empty: str) -> str:
    if not rows:
        return f"<tr><td colspan='4'>{escape(empty)}</td></tr>"
    return "".join(
        f"<tr><td>{escape(str(row['name']))}</td><td>{escape(str(row['category']))}</td>"
        f"<td class='number'>{row['quantity']}</td><td>{escape(str(row['reason']))}</td></tr>"
        for row in rows
    )


def _render_operational_row(item: dict[str, object]) -> str:
    day_cells = "".join(f"<td class='number'><strong>{day['quantity']}</strong><br><small>гости {day.get('guest_quantity', day['quantity'])} + питание {day.get('staff_quantity', 0)}</small></td>" for day in item["daily_forecast"])
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
          <h2>Базовый расчет действующего меню</h2>
          <div class="muted">Период анализа: {strategy["period"]}</div>
        </div>
        <div class="pill">Меню: {summary["actual_total"]} / {summary["target_total"]}</div>
      </div>

      <div class="metrics compact">
        <div class="metric"><span>База на {strategy['order_days']} дня, до питания и поправок</span><strong>{strategy["total_quantity"]} шт.</strong></div>
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
    cards = []
    for day in days:
        quantity = f"{day['quantity']} шт." if day['quantity'] is not None else 'Нет данных'
        missing = day.get('missing', 0)
        coverage = f"<small>Неполный итог: без {missing} поз.</small>" if missing else ''
        cards.append(
            f"<div class='daily-card'><span>{escape(str(day['weekday']))}, {escape(str(day['date']))}</span>"
            f"<strong>{quantity}</strong>{coverage}<small>{escape(str(day['weather']))}</small>"
            f"<small>{_daily_weather_effect(day)}</small></div>"
        )
    return "".join(cards)


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
        f"<a class='next-order-card' href='/?start={period['start']}&days=14&service={round(strategy.get('demand_model', {}).get('service_level', DEFAULT_SERVICE_LEVEL) * 100)}&reserve_cost={round(strategy.get('demand_model', {}).get('profit_tolerance', DEFAULT_PROFIT_TOLERANCE) * 100)}'>"
        f"<span>{escape(str(period['label']))} · {escape(str(period['start']))}—{escape(str(period['end']))}</span>"
        f"<strong>{period['total_quantity']} шт.</strong>"
        f"<small>Поставка: {period.get('supplier_quantity', period['total_quantity'])} · Собственное: {period.get('production_quantity', 0)}</small>"
        f"<small>{escape(str(period['weather']))}</small></a>"
        for period in following
    )
    rain_days = sum(1 for day in current["daily_totals"] if day["rain"])
    missing_weather = sum(1 for day in current["daily_totals"] if not day["weather_available"])
    short_shelf = sum(1 for item in current["rows"] if int(item["shelf_life_days"]) < int(current["days"]))
    menu_coverage = _render_menu_coverage_block(strategy.get("menu_coverage", {}))
    alerts = []
    if rain_days:
        alerts.append(f"Осадки повлияли на {rain_days} дн. заказа")
    if missing_weather:
        alerts.append(f"Нет прогноза погоды на {missing_weather} дн.")
    if short_shelf:
        alerts.append(f"{short_shelf} поз. с коротким сроком: воскресенье исключено")
    alert_html = "".join(f"<span class='alert-chip'>{escape(alert)}</span>" for alert in alerts) or "<span class='ok-chip'>Критичных предупреждений нет</span>"
    updated = strategy["weather_updated_at"] or "нет данных"

    return f"""
    <section class="workspace order-focus">
      <div class="workspace-head">
        <div><span class="eyebrow">Ближайший заказ</span><h2>{current['label']} · {current['start']}—{current['end']}</h2>
        <div class="muted">Продажи учтены по {strategy['period'].split('..')[-1]} · погода: {escape(str(strategy['weather_source']))}, {escape(str(updated))}</div></div>
        <div class="order-totals">
          <div class="order-total"><span>Всего план</span><strong>{current['total_quantity']}</strong><small>штук</small></div>
          <div class="order-total supplier"><span>Заказать</span><strong>{current.get('supplier_quantity', current['total_quantity'])}</strong><small>поставка</small></div>
          <div class="order-total production"><span>Произвести</span><strong>{current.get('production_quantity', 0)}</strong><small>собственное</small></div>
        </div>
      </div>
      <div class="daily-strip">{_render_daily_totals(current['daily_totals'])}</div>
      <div class="alert-row">{alert_html}</div>
      {menu_coverage}
      <div class="table-wrap">
        <table class="order-table"><thead><tr><th>Позиция</th><th>Тип</th>{day_headings}<th>Итого</th><th>Статус</th><th></th></tr></thead><tbody>{rows}</tbody></table>
      </div>
    </section>
    <section class="next-orders"><div class="section-title"><div><span class="eyebrow">Далее</span><h2>Следующие заказы</h2></div><a href="/analytics">Открыть аналитику →</a></div><div class="next-order-grid">{next_cards}</div></section>
    <dialog id="item-dialog"><button class="dialog-close" aria-label="Закрыть">×</button><div id="dialog-content"></div></dialog>
    """


def _render_operational_row(item: dict[str, object]) -> str:
    day_cells = "".join(f"<td class='number'><strong>{day['quantity']}</strong><br><small>гости {day.get('guest_quantity', day['quantity'])} + питание {day.get('staff_quantity', 0)}</small></td>" for day in item["daily_forecast"])
    status = str(item.get("waste_risk", "контроль"))
    supply_type = str(item.get("supply_type", "supplier"))
    supply_label = "Собственное" if supply_type == "own_production" else "Поставка"
    supply_class = "production" if supply_type == "own_production" else "supplier"
    details = (
        f"Тип: {item.get('supply_label', supply_label)}\n"
        f"Категория: {item['category']}\n"
        f"Срок хранения: {item['shelf_life_days']} дн.\n"
        f"Продажи прошлого окна: {item['previous_period_sales'] if item['previous_period_sales'] is not None else 'нет данных'}\n"
        f"Списания прошлого окна: {item['previous_period_waste']}\n"
        f"Погодный коэффициент: x{item['weather_factor']}\n"
        f"Решение: {item.get('decision_reason', item.get('strategy', 'нет данных'))}\n"
        f"Риск: {_future_risk_context(item)}"
    )
    return (
        f"<tr class='{supply_class}'><td><strong>{escape(str(item['name']))}</strong><span>{escape(str(item['category']))}</span></td>"
        f"<td><span class='type-chip {supply_class}'>{escape(supply_label)}</span></td>"
        f"{day_cells}<td class='number total-cell'>{item['forecast_quantity']}</td>"
        f"<td><i class='{_risk_class(status)}'>{escape(status)}</i></td>"
        f"<td><button class='detail-button' data-name='{escape(str(item['name']), quote=True)}' data-details='{escape(details, quote=True)}'>Подробнее</button></td></tr>"
    )


def render_orders_workspace(strategy: dict[str, Any] | None, export_url: str = '') -> str:
    if strategy is None:
        return "<section class='workspace'><h2>Ближайший заказ</h2><div class='signal-box'>Загрузите отчет продаж, чтобы построить прогноз.</div></section>"

    current = strategy["future_orders"][0]
    day_headings = "".join(
        f"<th>{escape(str(day['weekday']))}<span>{escape(str(day['date']))}</span></th>"
        for day in current["daily_totals"]
    )
    supplier_rows = current["rows"]
    rows = "".join(_render_operational_row(item) for item in supplier_rows)
    summary = order_totals(supplier_rows, [day["date"] for day in current["daily_totals"]])
    totals = render_order_totals(summary)
    supplier_days = [
        {**day, 'quantity': total['value'], 'missing': total['missing']}
        for day, total in zip(current['daily_totals'], summary['daily'])
    ]
    supplier_staff = sum(row.get('staff_quantity', 0) for row in supplier_rows)
    quantity = summary['quantity']['value']
    order_badge = f'<strong>{quantity}</strong><small>порций</small>' if quantity is not None else '<small>Нет данных</small>'
    missing = summary['quantity']['missing']
    order_coverage = f'<span>Неполный итог: без {missing} поз.</span>' if missing else ''
    rain_days = sum(1 for day in current["daily_totals"] if day["rain"])
    missing_weather = sum(1 for day in current["daily_totals"] if not day["weather_available"])
    short_shelf = sum(1 for item in current["rows"] if int(item["shelf_life_days"]) < int(current["days"]))
    alerts = []
    if rain_days:
        alerts.append(f"Осадки повлияли на {rain_days} дн. заказа")
    if missing_weather:
        alerts.append(f"Нет прогноза погоды на {missing_weather} дн.")
    if short_shelf:
        alerts.append(f"{short_shelf} поз. с коротким сроком: воскресенье исключено")
    alert_html = "".join(f"<span class='alert-chip'>{escape(alert)}</span>" for alert in alerts) or "<span class='ok-chip'>Критичных предупреждений нет</span>"
    updated = strategy["weather_updated_at"] or "нет данных"

    export_html = (
        f'<div class="order-export"><a href="{escape(export_url, quote=True)}" download>Скачать Excel: кулинария + ТТ</a>'
        '<p class="muted">Поставка с общим количеством по блюдам и отдельный план ТТ по дням. '
        'Каждый лист настроен на печать на одной странице А4.</p></div>'
        if export_url else ''
    )
    return f"""
    <section class="workspace order-focus">
      <div class="workspace-head">
        <div><span class="eyebrow">Ближайший заказ</span><h2>{current['label']} · {current['start']}—{current['end']}</h2>
        <div class="muted">Продажи учтены по {strategy['period'].split('..')[-1]} · погода: {escape(str(strategy['weather_source']))}, {escape(str(updated))}</div></div>
        <div class="order-totals">
          <div class="order-total supplier"><span>Заказать</span>{order_badge}{order_coverage}</div>
        </div>
      </div>
      <div class="daily-strip">{_render_daily_totals(supplier_days)}</div>
      {export_html}
      <div class="table-wrap">
        <table class="order-table"><thead><tr><th>Позиция</th>{day_headings}<th>Итого</th><th>Цена продажи<br>порции, ₽</th><th>Стоимость всех<br>порций, ₽</th><th>Маржа порции<br>₽ / %</th><th>Маржа плана<br>₽ / %</th><th>Статус</th><th></th></tr></thead><tbody>{rows}</tbody>{totals}</table>
      </div>
      <p class="muted">Итоги относятся к поставке; ТТ показана отдельно. Цены за порцию и проценты не суммируются. Неполные денежные итоги помечены. Формулы и роль блюда в меню — в «Подробнее».</p>
      <p>Заказ до <strong>{escape(str(current.get('deadline', ''))).replace('T', ' ')}</strong> (Москва).
      Поставка утром до открытия. Правило: на послезавтра до 18:00 МСК, только Пн/Ср/Пт.</p>
      <p>В эту поставку включено питание сотрудников: {supplier_staff} порций.
      Потребность рассчитана без технической кратности и минимальных партий. Резерв на колебания спроса указан в «Подробнее».</p>
      <div class="alert-row">{alert_html}</div>
      {_render_order_calculation_block(strategy, current)}
      {render_category_reserves(current.get('category_reserves', []))}
    </section>
    <dialog id="item-dialog"><button class="dialog-close" aria-label="Закрыть">×</button><div id="dialog-content"></div></dialog>
    """


def _render_order_calculation_block(strategy: dict[str, Any], current: dict[str, Any]) -> str:
    return f"""
      <section class="calculation-box">
        <h3>Как рассчитан заказ</h3>
        <ol>
          <li><strong>Период:</strong> {escape(str(current['label']))}, {escape(str(current['start']))}—{escape(str(current['end']))}; окно {current['days']} дн.</li>
          <li><strong>База:</strong> продажи из отчетов за {escape(str(strategy['period']))}; нулевые отсутствующие дни не подставляются.</li>
          <li><strong>Меню:</strong> в расчет попадают включенные позиции меню; отключенные позиции исключаются вручную.</li>
          <li><strong>Тип:</strong> поставка и собственное производство задаются в «Меню»; подтвержденные 5 блюд ТТ считаются отдельно от 32 мест поставки.</li>
          <li><strong>Корректировки:</strong> срок годности ограничивает окно спроса, чеки и погода применяются один раз. Частота прошлых списаний не вычитается из спроса: риск остатка оценивается отдельно, известные потери влияют на выбор блюд.</li>
          <li><strong>Итог:</strong> экономический объем с резервом к желаемому наличию, ограниченным допустимой ценой потерь, плюс порции питания, отнесенные к поставке. Партии и минимальные объемы для обычных блюд не применяются. Расчет показывает потребность; фактический доступный остаток здесь не вычитается.</li>
        </ol>
      </section>
    """


def _render_operational_row(item: dict[str, object]) -> str:
    day_cells = "".join(f"<td class='number'><strong>{'—' if item.get('quantity_unknown') else day['quantity']}</strong></td>" for day in item['daily_forecast'])
    status, role = assortment_status(item)
    supply_type = str(item.get("supply_type", "supplier"))
    supply_label = "Собственное" if supply_type == "own_production" else "Поставка"
    supply_class = "production" if supply_type == "own_production" else "supplier"
    details_html = _render_item_details(item, supply_label)
    return (
        f"<tr class='{supply_class}'><td><strong>{escape(str(item['name']))}</strong><span>{escape(str(item['category']))}</span></td>"
        f"{day_cells}<td class='number total-cell'>{'нет данных' if item.get('quantity_unknown') else item['forecast_quantity']}</td>"
        + finance_cells(item)
        + f"<td><i class='menu-status {role}' title='{escape(status_explanation(item), quote=True)}'>{escape(status)}</i></td>"
        + f"<td><button class='detail-button' data-name='{escape(str(item['name']), quote=True)}'>Подробнее</button><template>{details_html}</template></td></tr>"
    )


def _render_item_details(item: dict[str, object], supply_label: str) -> str:
    previous_sales = item["previous_period_sales"] if item["previous_period_sales"] is not None else "нет данных"
    daily_rows = "".join(
        f"<li>{escape(str(day['weekday']))} {escape(str(day['date']))}: <strong>{day['quantity']} шт.</strong>, коэффициент погоды x{day.get('weather_factor', item.get('weather_factor', 1))}</li>"
        for day in item["daily_forecast"]
    )
    return f"""
      <div class="detail-panel">
        <span class="eyebrow">Детали позиции</span>
        <h2>{escape(str(item['name']))}</h2>
        <dl>
          <dt>Категория</dt><dd>{escape(str(item['category']))}</dd>
          <dt>Итог к заказу</dt><dd>{item['forecast_quantity']} шт.</dd>
          <dt>Продажи за весь период</dt><dd>{item.get('sales_june_july', 0)} шт.</dd>
          <dt>Средний спрос</dt><dd>{item.get('average_per_day', 0)} шт./день</dd>
          <dt>Продажи прошлого окна</dt><dd>{previous_sales}</dd>
          <dt>Списания прошлого окна</dt><dd>{item['previous_period_waste']}</dd>
          <dt>Срок хранения</dt><dd>{item['shelf_life_days']} дн.</dd>
          <dt>Погодный коэффициент</dt><dd>x{item['weather_factor']}</dd>
          <dt>Решение</dt><dd>{escape(str(item.get('decision_reason', item.get('strategy', 'нет данных'))))}</dd>
          <dt>Риск</dt><dd>{escape(_future_risk_context(item))}</dd>
        </dl>
        <h3>Разбивка по дням</h3>
        <ul>{daily_rows}</ul>
        {finance_details(item)}
        {status_details(item)}
        {model_details(item.get('model', {}), item.get('remaining_is_expiry_risk', True))}
      </div>
    """


def render_production_workspace(strategy: dict[str, Any] | None) -> str:
    if not strategy:
        return '<section><h2>Кулинария ТТ</h2><p>Загрузите продажи и отметьте собственные позиции в <a href="/menu">управлении меню</a>.</p></section>'
    days = strategy.get('production_days', [])
    if not days or not days[0]['rows']:
        return '<section><h2>Кулинария ТТ</h2><p>Нет включенных собственных позиций. Выберите тип «Собственное» в <a href="/menu">управлении меню</a>.</p></section>'
    headings = ''.join(f"<th>{day['date']}<br>{WEEKDAY_LABELS[date.fromisoformat(day['date']).weekday()]}</th>" for day in days)
    rows = []
    for index, item in enumerate(days[0]['rows']):
        cells = []
        for day in days:
            row = day['rows'][index]
            quantity = row['quantity'] if row['quantity'] is not None else 'нет данных'
            model = row.get('model', {})
            risk = number(model.get('stockout_probability') * 100) if model.get('stockout_probability') is not None else '—'
            cells.append(f"<td><strong>{quantity}</strong><br><small>средний спрос {number(model.get('expected_demand'))}; резерв {model.get('reserve', '—')}<br>гостям с резервом {row.get('guest_quantity', quantity)} + питание {row.get('staff_quantity', 0)}<br>остаток ≈{number(model.get('expected_remaining'))}; модельный риск нехватки {risk}%<br>погода ×{row['weather_factor']} · чеки ×{row.get('receipt_factor', 1)}<br>наблюдений {model.get('history_points', 0)}</small></td>")
        rows.append(f"<tr><td><strong>{escape(item['name'])}</strong><br>{escape(item['category'])}</td>{''.join(cells)}</tr>")
    totals = ''.join(f"<td><strong>{day['total']}</strong><br><small>без истории: {day['missing_history']}</small></td>" for day in days)
    weather = ''.join(f"<td><small>{escape(day['weather'])}</small></td>" for day in days)
    return f'''<section class="workspace"><h2>Кулинария ТТ</h2>
    <form method="get" action="/production"><input type="hidden" name="service" value="{round(strategy.get('demand_model', {}).get('service_level', DEFAULT_SERVICE_LEVEL) * 100)}"><input type="hidden" name="reserve_cost" value="{round(strategy.get('demand_model', {}).get('profit_tolerance', DEFAULT_PROFIT_TOLERANCE) * 100)}"><label>Начало плана <input type="date" name="start" value="{days[0]['date']}" required></label> <button type="submit">Рассчитать неделю</button></form>
    <p>Ежедневный план на 7 дней. Собственные позиции меню и подтвержденные блюда ТТ: каши, омлет с ветчиной, запеканка, сырники. Готовить на текущий день, остаток на завтра не переносить. Без квот поставщика.</p>
    <p class="muted">Весь указанный выпуск готовится к открытию, без условной второй партии. Техническая кратность сейчас не ограничивает расчет: здесь потребность по спросу, прибыли и риску нехватки. Сырники указаны в отчетных порциях «2 шт.», количество изделий вдвое больше. Отсутствующие дни не считаются нулевыми. Питание включено один раз. План на весь день: не готовьте его повторно сверх уже выпущенного.</p>
    <div class="table-wrap"><table><thead><tr><th>Позиция / группа</th>{headings}</tr></thead><tbody>{''.join(rows)}<tr><th>Итого к производству</th>{totals}</tr><tr><th>Погода</th>{weather}</tr></tbody></table></div></section>'''


def render_staff_and_economics(strategy: dict[str, Any] | None, view: str) -> str:
    if not strategy:
        return ''
    staff_note = ('В заказе показаны порции питания, отнесенные к поставке.' if view == 'orders' else
                  'В план включено 5 порций сотрудникам в день, суммарно по поставке и ТТ.')
    block = f'''<section class="calculation-box"><h3>Питание сотрудников и динамика спроса</h3>
    <p>{staff_note} Питание отсутствует в реализации и списывается отдельными актами, поэтому добавляется к гостевому спросу. Выбор блюд оценивается по структуре продаж и может отличаться от факта.</p>
    <p>Загружены чеки за {strategy.get('receipt_days', 0)} дней. Учитываются недавние одинаковые дни недели и аналог будущего дня год назад с поправкой на текущую динамику. Ограничение ×0,7…1,3. Конфликтов дат: {strategy.get('receipt_conflicts', 0)}. <a href="/analytics#traffic">История прошлого года и расчет потока</a>. Питание не входит в целевые списания 2%.</p></section>'''
    source = strategy.get('menu_source', {})
    missing = source.get('without_november_sales', [])
    listing = ''.join(f"<li>{escape(str(row['sku']))} — {escape(row['name'])}</li>" for row in missing)
    block = f'''<section class="calculation-box"><h3>Источник текущего ассортимента</h3>
    <p>{escape(source.get('filename', ''))}: доступных блюд {source.get('available', 0)}; в матрице до 32, ТТ отдельно.
    {escape(source.get('notice', ''))}</p><details><summary>Нет ноябрьских продаж: {len(missing)} блюд</summary><ul>{listing}</ul></details></section>''' + block
    if view != 'analytics':
        return render_demand_method(strategy, view) + block + render_loss_kpi(strategy.get('loss_kpi', {}))
    economics = strategy.get('economics', {})
    rows = ''.join(f"<tr><td>{escape(r['name'])}</td><td>{r['sold']:g}</td><td>{r['revenue']:.2f}</td><td>{r['gross_profit']:.2f}</td><td>{r['waste_quantity']:g}</td><td>{r['waste_cost']:.2f}</td><td>{r['staff_cost']:.2f}</td><td>{r['profit_after_known_costs']:.2f}</td><td>{r['margin_after_known_costs'] if r['margin_after_known_costs'] is not None else '—'}</td></tr>" for r in economics.get('rows', []))
    loss_plan = strategy.get('monthly_loss_plan')
    return ((render_monthly_loss_plan(loss_plan) if loss_plan else '')
            + render_demand_method(strategy, view) + block + render_loss_kpi(strategy.get('loss_kpi', {}))
            + render_matrix(strategy.get('matrix_proposal', {}))
            + render_traffic(strategy.get('traffic_history', {}), strategy.get('traffic_forecast', []))
            + _render_menu_coverage_block(strategy.get('menu_coverage', {}))) + f'''<section><h2>Прибыль по каждому блюду после известных списаний</h2>
    <p>{economics.get('start', '')}—{economics.get('end', '')}. Продажи: {economics.get('sales_days', 0)} дней; подробные акты: {economics.get('detailed_waste_days', 0)} дней.</p>
    <p>{escape(economics.get('notice', ''))} Ноль в колонке акта означает отсутствие найденной строки, а не подтвержденное отсутствие потерь. Себестоимость проданного уже вычтена в валовой прибыли и второй раз не вычитается. Питание вычитается по известным отдельным актам; плановые 5 порций не заменяют фактическую стоимость.</p>
    <div class="table-wrap"><table><thead><tr><th>Блюдо</th><th>Продано</th><th>Выручка, ₽</th><th>Валовая прибыль, ₽</th><th>Списано порций</th><th>Потери, ₽</th><th>Питание, ₽</th><th>После известных затрат, ₽</th><th>Маржа, %</th></tr></thead><tbody>{rows}</tbody></table></div></section>'''


def render_weather_status(strategy: dict[str, Any] | None) -> str:
    if not strategy:
        return ''
    source = escape(str(strategy.get('weather_source', 'нет данных')))
    updated = escape(str(strategy.get('weather_updated_at') or 'нет данных'))
    stale = ' Используется сохраненный устаревший прогноз.' if strategy.get('weather_stale') else ''
    periods = strategy.get('future_orders', [])
    days = periods[0]['daily_totals'] if periods else []
    available = sum(bool(day['weather_available']) for day in days)
    status = f'Есть данные на {available} из {len(days)} дней ближайшего заказа.' if days else 'Нет периода заказа.'
    missing = strategy.get('unavailable_reports', [])
    warning = ('<p class="alert-chip">Расчет неполный: недоступные отчеты пропущены: '
               + escape('; '.join(missing)) + '. Проверьте архив отчетов.</p>') if missing else ''
    return f'''{warning}<section class="calculation-box"><h3>Как учитывается погода</h3>
    <p>Источник: {source}. Обновление: {updated}.{stale} {status}</p>
    <p>Дождь меняет поток покупателей; температура и осадки дополнительно корректируют категории. Коэффициент ×1 означает отсутствие изменения, ×0,9 — снижение на 10%. Если прогноза на дату нет, применяется ×1. Для заказа точный коэффициент позиции указан в «Подробнее», для «Кулинарии ТТ» — в каждой ячейке.</p></section>'''


def render_dashboard_html(payload: dict[str, Any], view: str = "orders", export_url: str = '') -> str:
    events = payload["events"][:14]
    budget = payload["budget"]
    max_budget = max([*budget.values(), 1])
    service_percent = round(payload.get('culinary_strategy', {}).get('demand_model', {}).get('service_level', DEFAULT_SERVICE_LEVEL) * 100) if payload.get('culinary_strategy') else 85
    reserve_percent = round(payload.get('culinary_strategy', {}).get('demand_model', {}).get('profit_tolerance', DEFAULT_PROFIT_TOLERANCE) * 100) if payload.get('culinary_strategy') else 5
    dates = payload.get('order_dates', [])
    periods = (payload.get('culinary_strategy') or {}).get('future_orders', [])
    selected_order = periods[0]['start'] if periods else (dates[0] if dates else '')
    order_date_tabs = render_order_date_tabs(dates, selected_order, service_percent, reserve_percent) if view == 'orders' else ''

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
        else (render_production_workspace(payload.get("culinary_strategy")) if view == 'production'
              else render_orders_workspace(payload.get("culinary_strategy"), export_url=export_url))
    )
    weather_section = render_weather_status(payload.get('culinary_strategy'))
    culinary_strategy += render_staff_and_economics(payload.get('culinary_strategy'), view)
    culinary_strategy = culinary_strategy + weather_section if view == 'orders' else weather_section + culinary_strategy

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
    .order-date-tabs {{ display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 8px; margin: 16px 0; }}
    .order-date-tabs a {{ text-align: center; font-size: 14px; padding: 12px 6px; border: 1px solid var(--line); background: var(--panel); white-space: nowrap; }}
    .order-date-tabs a.active, .order-date-tabs a.active:hover {{ color: white; background: var(--green); border-color: var(--green); }}
    .order-date-tabs a:focus-visible {{ outline: 2px solid var(--green); outline-offset: 3px; }}
    @media (max-width: 900px) {{ .order-date-tabs {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }} }}
    @media (max-width: 480px) {{ .order-date-tabs {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} }}
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
    .order-totals {{ display: grid; grid-template-columns: 1fr; }}
    .order-total {{ min-width: 150px; padding: 14px 18px; border-radius: 10px; background: var(--green); color: white; display: grid; grid-template-columns: auto auto; align-items: baseline; gap: 0 8px; }}
    .order-total.supplier {{ background: #265f8f; }}
    .order-total.production {{ background: #7a5230; }}
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
    .order-summary {{ background: var(--panel-soft); }}
    .order-summary th, .order-summary td {{ border-top: 2px solid var(--green); }}
    .order-summary small {{ display: block; max-width: 145px; color: #775009; font-weight: normal; }}
    .menu-status {{ display: inline-block; border-radius: 999px; padding: 6px 9px; font-size: 12px; font-weight: 700; white-space: nowrap; font-style: normal; }}
    .menu-status.core {{ background: #dfece3; color: #28513d; }}
    .menu-status.rotation {{ background: #f7e6bd; color: #775009; }}
    .menu-status.trial {{ background: #e7f0f8; color: #265f8f; }}
    .menu-status.unknown {{ background: #eee; color: #555; }}
    .type-chip {{ display: inline-block; padding: 5px 8px; border-radius: 999px; font-size: 12px; font-weight: 800; white-space: nowrap; }}
    .type-chip.supplier {{ background: #e7f0f8; color: #265f8f; }}
    .type-chip.production {{ background: #f4ece4; color: #7a5230; }}
    .menu-coverage {{ margin: 16px 0; padding: 14px; border: 1px solid var(--line); border-radius: 8px; background: #fbfaf7; }}
    .coverage-summary {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 10px; }}
    .coverage-summary.four {{ grid-template-columns: repeat(4, 1fr); }}
    .coverage-summary div {{ padding: 10px; background: white; border: 1px solid var(--line); border-radius: 8px; }}
    .coverage-summary span {{ display: block; color: var(--muted); font-size: 12px; margin-bottom: 4px; }}
    .coverage-summary strong {{ font-size: 16px; }}
    .menu-coverage details {{ margin-top: 10px; }}
    .menu-coverage summary {{ cursor: pointer; font-weight: 800; color: var(--green); }}
    .mini-table {{ margin-top: 8px; font-size: 13px; }}
    .mini-table .number {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .calculation-box {{ margin: 16px 0; padding: 16px; border: 1px solid var(--line); border-radius: 8px; background: #fff; }}
    .calculation-box h3 {{ margin: 0 0 10px; }}
    .calculation-box ol {{ margin: 0; padding-left: 20px; line-height: 1.55; color: var(--muted); }}
    .detail-button {{ border: 0; background: transparent; color: var(--green); cursor: pointer; font-weight: 700; padding: 6px; }}
    .order-export {{ margin-top: 20px; padding-top: 18px; border-top: 1px solid var(--line); }}
    .order-export a {{ display: inline-block; padding: 12px 18px; background: var(--green); color: white; border-radius: 10px; text-decoration: none; font-weight: 700; }}
    .order-total.production a {{ color: inherit; }}
    .order-table .order-finance {{ min-width: 115px; font-variant-numeric: tabular-nums; }}
    .order-table .order-finance small {{ display: block; max-width: 145px; white-space: normal; font-weight: normal; }}
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
    .detail-panel dl {{ display: grid; grid-template-columns: 150px 1fr; gap: 8px 12px; margin: 16px 0; }}
    .detail-panel dt {{ font-weight: 800; color: var(--ink); }}
    .detail-panel dd {{ margin: 0; color: var(--muted); }}
    .detail-panel h3 {{ margin-top: 18px; font-size: 16px; }}
    .detail-panel ul {{ padding-left: 20px; color: var(--muted); line-height: 1.5; }}
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
      .order-totals {{ grid-template-columns: 1fr; min-width: 0; width: 100%; }}
      .tabs {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .detail-panel dl {{ grid-template-columns: 1fr; }}
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
        <nav><a class="{'active' if view == 'orders' else ''}" href="/?service={service_percent}&reserve_cost={reserve_percent}">Заказы</a><a class="{'active' if view == 'production' else ''}" href="/production?start={selected_order if view == 'orders' else payload['start_day']}&amp;service={service_percent}&amp;reserve_cost={reserve_percent}">Кулинария ТТ</a><a class="{'active' if view == 'analytics' else ''}" href="/analytics?service={service_percent}&reserve_cost={reserve_percent}">Аналитика</a><a href="/menu">Меню</a><a href="/reports">Отчёты</a><a href="/settings">Настройки</a></nav>
      </div>
      <div><a href="/reports">Ежемесячные отчеты</a><div class="muted">{payload["start_day"]} · {payload["horizon_days"]} дней</div></div>
    </header>

    {order_date_tabs}

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
  <script src="/assets/orders.js" defer></script>
</body>
</html>"""


def selected_upload_files(parts: list[tuple[str, str | None, bytes]]) -> list[tuple[str, bytes]]:
    files = [(filename, content) for name, filename, content in parts if name == 'file' and filename]
    if not files:
        raise ReportValidationError('Выберите XLSX-файлы.')
    if len(files) > MAX_BATCH_FILES:
        raise ReportValidationError(f'За один раз можно загрузить не более {MAX_BATCH_FILES} файлов.')
    if sum(len(content) for _, content in files) > MAX_BATCH_UPLOAD_BYTES:
        raise ReportValidationError(f'Общий размер файлов превышает {MAX_BATCH_UPLOAD_MB} МБ.')
    return files


def save_upload_batch(files: list[tuple[str, bytes]], save: Any) -> tuple[str, str]:
    saved = []
    errors = []
    for filename, content in files:
        try:
            validate_report_content('sales', filename, content)
            save(filename, content)
            saved.append(Path(filename).name)
        except (ReportValidationError, OSError) as error:
            errors.append(f'{Path(filename).name}: {error}')
    return (f'Загружено: {len(saved)} из {len(files)}. ' + '; '.join(saved), '; '.join(errors))


class DashboardServer(ThreadingHTTPServer):
    def __init__(self, *args: Any, **kwargs: Any):
        self.order_exports = OrderExportStore()
        super().__init__(*args, **kwargs)


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self._serve_request(self._handle_get)

    def do_POST(self) -> None:
        self._serve_request(self._handle_post)

    def _serve_request(self, action: Any) -> None:
        try:
            action()
        except (BrokenPipeError, ConnectionResetError):
            return
        except ReportValidationError:
            self._send_error_page(HTTPStatus.SERVICE_UNAVAILABLE, 'Не удалось прочитать отчеты. Проверьте подключение и доступность файлов в разделе «Отчёты».')
        except Exception as error:
            logging.getLogger(__name__).exception('request_failed')
            self.log_message('request_failed: %s', type(error).__name__)
            self._send_error_page(HTTPStatus.INTERNAL_SERVER_ERROR, 'Не удалось выполнить запрос. Обновите страницу или проверьте доступность отчетов.')

    def _handle_get(self) -> None:
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
        if parsed.path == '/assets/orders.js':
            content = ORDER_DETAILS_SCRIPT.encode('utf-8')
            self.send_response(HTTPStatus.OK)
            self.send_header('Content-Type', 'application/javascript; charset=utf-8')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return
        if parsed.path == "/":
            payload = _payload_from_query(parsed.query)
            strategy = payload.get('culinary_strategy')
            export_url = ''
            if strategy:
                token = self.server.order_exports.add(prepare_order_download(strategy))
                export_url = f'/orders/export.xlsx?snapshot={token}'
            self._send_html(render_dashboard_html(payload, export_url=export_url))
            return
        if parsed.path == '/orders/export.xlsx':
            token = parse_qs(parsed.query).get('snapshot', [''])[0]
            download = self.server.order_exports.get(token)
            if download is None:
                self._send_error_page(HTTPStatus.GONE, 'Снимок заказа больше недоступен. Обновите страницу заказа и скачайте Excel еще раз.')
                return
            self.send_response(HTTPStatus.OK)
            self.send_header('Content-Type', ORDER_WORKBOOK_MIME)
            self.send_header('Content-Disposition', f'attachment; filename="{download.filename}"')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Length', str(len(download.content)))
            self.end_headers()
            self.wfile.write(download.content)
            return
        if parsed.path == "/api/dashboard":
            self._send_json(_payload_from_query(parsed.query))
            return
        if parsed.path == "/api/data-status":
            self._send_json(build_data_status())
            return
        if parsed.path == "/analytics":
            params = parse_qs(parsed.query)
            default_month = max(moscow_now().date().replace(day=1), date(2026, 12, 1))
            try:
                month = date.fromisoformat(params.get('loss_month', [default_month.isoformat()[:7]])[0] + '-01')
            except ValueError:
                self._send_error_page(HTTPStatus.BAD_REQUEST, 'Укажите месяц в формате ГГГГ-ММ.')
                return
            self._send_html(render_dashboard_html(_payload_from_query(parsed.query, loss_month=month), view="analytics"))
            return
        if parsed.path == '/production':
            self._send_html(render_dashboard_html(_payload_from_query(parsed.query), view='production'))
            return
        if parsed.path == "/menu":
            params = parse_qs(parsed.query)
            self._send_html(
                render_menu_html(
                    load_current_menu_catalog(),
                    params.get("message", [""])[0],
                    params.get("error", [""])[0],
                )
            )
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

    def _handle_post(self) -> None:
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
        if parsed.path == "/analytics/loss-plan":
            if self.headers.get('Sec-Fetch-Site') == 'cross-site':
                self._send_error_page(HTTPStatus.FORBIDDEN, 'Откройте форму в разделе «Аналитика».')
                return
            fields = self._read_form_urlencoded()
            try:
                save_loss_plan(loss_plan_path(), fields.get('month', ''), fields.get('revenue', ''), fields.get('remaining', ''))
            except ValueError as error:
                self._send_error_page(HTTPStatus.BAD_REQUEST, str(error))
                return
            self._redirect(f"/analytics?loss_month={_url_quote(fields['month'])}#loss-plan")
            return
        if parsed.path == "/menu/toggle":
            fields = self._read_form_urlencoded()
            toggle_menu_item(DEFAULT_MENU_STATE_PATH, fields.get("name", ""), fields.get("action") == "enable")
            self._redirect(f"/menu?message={_url_quote('Меню обновлено')}")
            return
        if parsed.path == "/menu/supply":
            fields = self._read_form_urlencoded()
            toggle_menu_supply_type(
                DEFAULT_MENU_STATE_PATH,
                fields.get("name", ""),
                fields.get("type") == "own_production",
            )
            self._redirect(f"/menu?message={_url_quote('Тип позиции обновлен')}")
            return
        if parsed.path == "/menu/upload":
            try:
                parts = self._read_multipart_parts()
                files = selected_upload_files(parts)
            except ReportValidationError as error:
                self._redirect(f"/menu?error={_url_quote(str(error))}")
                return
            successes, errors = save_upload_batch(files, lambda name, content: save_menu_order_upload(name, content, DEFAULT_PREVIOUS_ORDERS_DIR))
            self._redirect(f"/menu?message={_url_quote(successes)}&error={_url_quote(errors)}")
            return
        if parsed.path != "/reports/upload":
            self._send_error_page(HTTPStatus.NOT_FOUND, "Страница не найдена")
            return
        try:
            parts = self._read_multipart_parts()
            files = selected_upload_files(parts)
            fields = {name: content for name, filename, content in parts if filename is None}
            report_type = fields.get('report_type', b'').decode('utf-8', errors='replace')
        except ReportValidationError as error:
            self._redirect(f"/reports?error={_url_quote(str(error))}")
            return
        successes, errors = save_upload_batch(files, lambda name, content: REPORT_STORAGE.save(report_type, name, content))
        self._redirect(f"/reports?message={_url_quote(successes)}&error={_url_quote(errors)}")

    def _read_form_urlencoded(self) -> dict[str, str]:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        body = self.rfile.read(content_length).decode("utf-8", errors="replace")
        parsed = parse_qs(body, keep_blank_values=True)
        return {key: values[0] if values else "" for key, values in parsed.items()}

    def _read_upload(self):
        fields = self._read_multipart_fields()
        report_type = fields.get("report_type", (None, b""))[1].decode("utf-8", errors="replace")
        filename, content = fields.get("file", (None, b""))
        if not filename:
            raise ReportValidationError("Выберите XLSX-файл.")
        return REPORT_STORAGE.save(report_type, filename, content)

    def _read_xlsx_upload(self) -> tuple[str, bytes]:
        fields = self._read_multipart_fields()
        filename, content = fields.get("file", (None, b""))
        if not filename:
            raise ReportValidationError("Выберите XLSX-файл.")
        return filename, content

    def _read_multipart_fields(self) -> dict[str, tuple[str | None, bytes]]:
        return {name: (filename, content) for name, filename, content in self._read_multipart_parts()}

    def _read_multipart_parts(self) -> list[tuple[str, str | None, bytes]]:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ReportValidationError("Некорректный размер запроса.") from error
        if content_length <= 0 or content_length > MAX_BATCH_UPLOAD_BYTES + 256 * 1024:
            raise ReportValidationError("Размер запроса превышает допустимый лимит.")
        content_type = self.headers.get("Content-Type", "")
        if not content_type.startswith("multipart/form-data"):
            raise ReportValidationError("Ожидается форма с файлом XLSX.")
        body = self.rfile.read(content_length)
        message = BytesParser(policy=policy.default).parsebytes(
            f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + body
        )
        fields: list[tuple[str, str | None, bytes]] = []
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if not name:
                continue
            fields.append((name, part.get_filename(), part.get_payload(decode=True) or b""))
        return fields

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
    counts = {key: 0 for key in ALLOWED_REPORT_TYPES}
    readable_counts = {key: 0 for key in ALLOWED_REPORT_TYPES}
    rows = []

    for report in reports:
        if report.report_type in counts:
            counts[report.report_type] += 1
        try:
            resolved = (active_storage.resolve_record(report) if isinstance(active_storage, SupabaseReportStorage)
                        else active_storage.resolve(report.id))
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
                "source": 'Этот компьютер' if report.storage_path == 'local-supplement' else active_storage.storage_label(),
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
        f"<td>{escape(str(item['original_name']))}<br><small>{escape(str(item.get('source', '')))}</small></td>"
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
  <p class="muted">Хранилище: {escape(str(status["storage"]))}. Продажи: {sales_count}. Списания: {waste_count}. Чеки: {_count_label(int(status["counts"].get("receipts", 0)))}.</p>
  <table><thead><tr><th>Тип</th><th>Период</th><th>Файл</th><th>Статус</th></tr></thead><tbody>{rows}</tbody></table>
</section>"""


def render_menu_html(items: list[Any], message: str = "") -> str:
    rows = "".join(_render_menu_row(item) for item in items) or (
        "<tr><td colspan='7'>Позиции меню пока не найдены. Добавьте XLSX-файлы в папку "
        "«Прошлые заказы».</td></tr>"
    )
    notice = f"<p class='ok'>{escape(message)}</p>" if message else ""
    enabled_count = sum(1 for item in items if item.enabled)
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Управление меню</title><style>
body{{font-family:Arial,sans-serif;background:#f5f6f8;color:#17202a;margin:0}}main{{max-width:1180px;margin:30px auto;padding:0 20px}}
section{{background:white;border-radius:14px;padding:22px;margin:18px 0;box-shadow:0 4px 18px #00000010}}table{{width:100%;border-collapse:collapse}}
th,td{{padding:10px;border-bottom:1px solid #ddd;text-align:left;vertical-align:top}}button{{font:inherit;padding:8px 10px;border:0;border-radius:8px;cursor:pointer}}
.primary{{background:#176b55;color:white}}.secondary{{background:#eceff1;color:#17202a}}.muted{{color:#607069}}.ok{{color:#176b55}}a{{color:#176b55}}
.disabled{{color:#7a7f86;background:#fafafa}}.number{{text-align:right;font-variant-numeric:tabular-nums}}
</style></head><body><main><p><a href="/">← Заказы</a> · <a href="/production">Кулинария ТТ</a> · <a href="/analytics">Аналитика</a> · <a href="/reports">Отчёты</a></p>
<h1>Управление меню</h1>{notice}
<section><p class="muted">Источник меню: лист «Кулинария» из папки «Прошлые заказы». В расчет заказов попадают только включенные позиции.</p>
<p><strong>{enabled_count}</strong> включено из <strong>{len(items)}</strong> позиций.</p></section>
<section><table><thead><tr><th>Статус</th><th>Группа</th><th>Артикул</th><th>Позиция</th><th>Заказы</th><th>Среднее</th><th></th></tr></thead><tbody>{rows}</tbody></table></section>
</main></body></html>"""


def _render_menu_row(item: Any) -> str:
    action = "disable" if item.enabled else "enable"
    button_label = "Исключить из расчета" if item.enabled else "Вернуть в расчет"
    button_class = "secondary" if item.enabled else "primary"
    status = "в расчете" if item.enabled else "исключено"
    row_class = "" if item.enabled else " class='disabled'"
    return f"""<tr{row_class}>
<td>{status}</td>
<td>{escape(item.group)}</td>
<td>{escape(item.sku)}</td>
<td>{escape(item.name)}</td>
<td class="number">{item.times_ordered}</td>
<td class="number">{_format_number(float(item.average_order_quantity))}</td>
<td><form method="post" action="/menu/toggle">
<input type="hidden" name="name" value="{escape(item.normalized_name)}">
<input type="hidden" name="action" value="{action}">
<button class="{button_class}" type="submit">{button_label}</button>
</form></td>
</tr>"""


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
    storage_info = f"<p class='muted'>Хранилище: {escape(REPORT_STORAGE.storage_label())}. Чеки и подробные акты хранятся на этом компьютере (AppData), пока не настроена миграция облачной базы.</p>"
    notice = storage_info + notice + render_data_status_block(build_data_status())
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ежемесячные отчеты</title><style>
body{{font-family:Arial,sans-serif;background:#f5f6f8;color:#17202a;margin:0}}main{{max-width:1100px;margin:30px auto;padding:0 20px}}
section{{background:white;border-radius:14px;padding:22px;margin:18px 0;box-shadow:0 4px 18px #00000010}}label{{display:block;margin:12px 0 5px}}
input,select,button{{font:inherit;padding:10px}}button{{background:#176b55;color:white;border:0;border-radius:8px;cursor:pointer}}table{{width:100%;border-collapse:collapse}}th,td{{padding:10px;border-bottom:1px solid #ddd;text-align:left}}.ok{{color:#176b55}}.error{{color:#b42318}}.muted{{color:#607069}}a{{color:#176b55}}
</style></head><body><main><p><a href="/">← К прогнозу</a></p><h1>Ежемесячная отчетность</h1>
{notice}{failure}<section><h2>Загрузить файл</h2><form method="post" action="/reports/upload" enctype="multipart/form-data">
<label for="report_type">Тип отчета</label><select id="report_type" name="report_type"><option value="sales">Продажи</option><option value="waste">Списания</option><option value="receipts">Чеки / поток гостей</option></select>
<label for="file">Файл XLSX</label><input id="file" name="file" type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" multiple required>
<p><button type="submit">Загрузить отчеты</button></p></form><p>До {MAX_BATCH_FILES} файлов за один раз, не более {MAX_BATCH_UPLOAD_MB} МБ суммарно и 10 МБ на файл. Можно выбрать ежедневные отчеты сразу за месяц. Каждый файл проверяется отдельно; ошибки не отменяют успешно загруженные файлы. Период определяется по датам внутри книги.</p></section>
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
</style></head><body><main><p><a href="/">← Заказы</a> · <a href="/production">Кулинария ТТ</a> · <a href="/analytics">Аналитика</a> · <a href="/reports">Отчёты</a></p>
<h1>Настройки</h1><section><h2>Текущая конфигурация</h2><dl>
<dt>Город</dt><dd>Санкт-Петербург, 59.9343 / 30.3351</dd>
<dt>Погода</dt><dd>MET Norway, обновление раз в 180 минут</dd>
<dt>Расписание заказов</dt><dd>Пн+Вт, Ср+Чт, Пт+Сб+Вс</dd>
<dt>Отсутствующие значения</dt><dd>Не считаются нулевыми продажами</dd>
</dl><p>Изменяемые настройки будут добавлены после проверки нового рабочего экрана.</p></section></main></body></html>"""


def render_menu_html(items: list[Any], message: str = "", error: str = "") -> str:
    rows = "".join(_render_menu_row(item) for item in items) or (
        "<tr><td colspan='7'>Позиции меню пока не найдены. Загрузите XLSX-файл заказа в производство.</td></tr>"
    )
    notice = f"<p class='ok'>{escape(message)}</p>" if message else ""
    failure = f"<p class='error'>{escape(error)}</p>" if error else ""
    enabled_count = sum(1 for item in items if item.enabled)
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Управление меню</title><style>
body{{font-family:Arial,sans-serif;background:#f5f6f8;color:#17202a;margin:0}}main{{max-width:1180px;margin:30px auto;padding:0 20px}}
section{{background:white;border-radius:14px;padding:22px;margin:18px 0;box-shadow:0 4px 18px #00000010}}table{{width:100%;border-collapse:collapse}}
th,td{{padding:10px;border-bottom:1px solid #ddd;text-align:left;vertical-align:top}}button{{font:inherit;padding:8px 10px;border:0;border-radius:8px;cursor:pointer}}
input{{font:inherit;padding:10px}}.primary{{background:#176b55;color:white}}.secondary{{background:#eceff1;color:#17202a}}.muted{{color:#607069}}.ok{{color:#176b55}}.error{{color:#b42318}}a{{color:#176b55}}
.disabled{{color:#7a7f86;background:#fafafa}}.number{{text-align:right;font-variant-numeric:tabular-nums}}
</style></head><body><main><p><a href="/">← Заказы</a> · <a href="/production">Кулинария ТТ</a> · <a href="/analytics">Аналитика</a> · <a href="/reports">Отчёты</a></p>
<h1>Управление меню</h1>{notice}{failure}
<section><h2>Добавить данные</h2><form method="post" action="/menu/upload" enctype="multipart/form-data">
<label for="file">XLSX-файл заказа в производство</label>
<p><input id="file" name="file" type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" multiple required></p>
<p><button class="primary" type="submit">Загрузить заказы</button></p>
</form><p class="muted">Нужен файл с листом «Кулинария» и колонками «Артикул», «Товар», «К-во фасовок» или «Общее к-во». После загрузки позиции сразу появятся ниже.</p></section>
<section><p class="muted">Источник меню: лист «Кулинария» из загруженных прошлых заказов. В расчет заказов попадают только включенные позиции.</p>
<p><strong>{enabled_count}</strong> включено из <strong>{len(items)}</strong> позиций.</p></section>
<section><table><thead><tr><th>Статус</th><th>Группа</th><th>Артикул</th><th>Позиция</th><th>Заказы</th><th>Среднее</th><th></th></tr></thead><tbody>{rows}</tbody></table></section>
</main></body></html>"""


def _render_menu_row(item: Any) -> str:
    action = "disable" if item.enabled else "enable"
    button_label = "Исключить из расчета" if item.enabled else "Вернуть в расчет"
    button_class = "secondary" if item.enabled else "primary"
    status = "в расчете" if item.enabled else "исключено"
    row_class = "" if item.enabled else " class='disabled'"
    return f"""<tr{row_class}>
<td>{status}</td>
<td>{escape(item.group)}</td>
<td>{escape(item.sku)}</td>
<td>{escape(item.name)}</td>
<td class="number">{item.times_ordered}</td>
<td class="number">{_format_number(float(item.average_order_quantity))}</td>
<td><form method="post" action="/menu/toggle">
<input type="hidden" name="name" value="{escape(item.normalized_name)}">
<input type="hidden" name="action" value="{action}">
<button class="{button_class}" type="submit">{button_label}</button>
</form></td>
</tr>"""


def _render_menu_coverage_block(coverage: dict[str, Any]) -> str:
    if not coverage:
        return ""
    outside = coverage.get("outside_menu", {"items": 0, "quantity": 0, "rows": []})
    disabled = coverage.get("disabled", {"items": 0, "quantity": 0, "rows": []})
    own = coverage.get("own_production", {"items": 0, "quantity": 0, "rows": []})
    in_menu = coverage.get("in_menu", {"items": 0, "quantity": 0, "rows": []})
    outside_rows = _render_menu_coverage_rows(outside.get("rows", []), empty="Вне меню позиций не найдено.")
    disabled_rows = _render_menu_coverage_rows(disabled.get("rows", []), empty="Выключенных позиций с продажами не найдено.")
    own_rows = _render_menu_coverage_rows(own.get("rows", []), empty="Собственных позиций с продажами не найдено.")
    return f"""
      <div class="menu-coverage">
        <div class="coverage-summary four">
          <div><span>В заказе</span><strong>{in_menu.get("items", 0)} поз. / {in_menu.get("quantity", 0)} шт.</strong></div>
          <div><span>Собственное</span><strong>{own.get("items", 0)} поз. / {own.get("quantity", 0)} шт.</strong></div>
          <div><span>Вне меню</span><strong>{outside.get("items", 0)} поз. / {outside.get("quantity", 0)} шт.</strong></div>
          <div><span>Исключено</span><strong>{disabled.get("items", 0)} поз. / {disabled.get("quantity", 0)} шт.</strong></div>
        </div>
        <details {"open" if int(own.get("items", 0)) else ""}>
          <summary>Собственная продукция: видна, но не попадает в заказ</summary>
          <table class="mini-table"><thead><tr><th>Позиция</th><th>Категория</th><th>Продажи</th><th>Причина</th></tr></thead><tbody>{own_rows}</tbody></table>
        </details>
        <details {"open" if int(outside.get("items", 0)) else ""}>
          <summary>Позиции вне меню, которые могут объяснять расхождение</summary>
          <table class="mini-table"><thead><tr><th>Позиция</th><th>Категория</th><th>Продажи</th><th>Причина</th></tr></thead><tbody>{outside_rows}</tbody></table>
        </details>
        <details>
          <summary>Выключенные позиции с продажами</summary>
          <table class="mini-table"><thead><tr><th>Позиция</th><th>Категория</th><th>Продажи</th><th>Причина</th></tr></thead><tbody>{disabled_rows}</tbody></table>
        </details>
      </div>
    """


def render_menu_html(items: list[Any], message: str = "", error: str = "") -> str:
    rows = "".join(_render_menu_row(item) for item in items) or (
        "<tr><td colspan='8'>Позиции меню пока не найдены. Загрузите XLSX-файл заказа в производство.</td></tr>"
    )
    notice = f"<p class='ok'>{escape(message)}</p>" if message else ""
    failure = f"<p class='error'>{escape(error)}</p>" if error else ""
    enabled_count = sum(1 for item in items if item.enabled and not item.own_production)
    own_count = sum(1 for item in items if item.own_production)
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Управление меню</title><style>
body{{font-family:Arial,sans-serif;background:#f5f6f8;color:#17202a;margin:0}}main{{max-width:1180px;margin:30px auto;padding:0 20px}}
section{{background:white;border-radius:14px;padding:22px;margin:18px 0;box-shadow:0 4px 18px #00000010}}table{{width:100%;border-collapse:collapse}}
th,td{{padding:10px;border-bottom:1px solid #ddd;text-align:left;vertical-align:top}}button{{font:inherit;padding:8px 10px;border:0;border-radius:8px;cursor:pointer}}
input{{font:inherit;padding:10px}}.primary{{background:#176b55;color:white}}.secondary{{background:#eceff1;color:#17202a}}.muted{{color:#607069}}.ok{{color:#176b55}}.error{{color:#b42318}}a{{color:#176b55}}
.disabled{{color:#7a7f86;background:#fafafa}}.badge{{display:inline-block;padding:4px 7px;border-radius:999px;background:#e7efe9;color:#176b55;font-size:12px;font-weight:700}}.number{{text-align:right;font-variant-numeric:tabular-nums}}
</style></head><body><main><p><a href="/">← Заказы</a> · <a href="/production">Кулинария ТТ</a> · <a href="/analytics">Аналитика</a> · <a href="/reports">Отчёты</a></p>
<h1>Управление меню</h1>{notice}{failure}
<section><h2>Добавить данные</h2><form method="post" action="/menu/upload" enctype="multipart/form-data">
<label for="file">XLSX-файл заказа в производство</label>
<p><input id="file" name="file" type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" multiple required></p>
<p><button class="primary" type="submit">Загрузить заказы</button></p>
</form><p class="muted">Нужен файл с листом «Кулинария» и колонками «Артикул», «Товар», «К-во фасовок» или «Общее к-во».</p></section>
<section><p class="muted">Позиции со звездочкой в исходном файле помечаются как «Собственное» и не попадают в расчет заказа.</p>
<p><strong>{enabled_count}</strong> в заказе, <strong>{own_count}</strong> собственное, всего <strong>{len(items)}</strong> позиций.</p></section>
<section><table><thead><tr><th>Статус</th><th>Тип</th><th>Группа</th><th>Артикул</th><th>Позиция</th><th>Заказы</th><th>Среднее</th><th></th></tr></thead><tbody>{rows}</tbody></table></section>
</main></body></html>"""


def _render_menu_row(item: Any) -> str:
    action = "disable" if item.enabled else "enable"
    button_label = "Исключить из расчета" if item.enabled else "Вернуть в расчет"
    button_class = "secondary" if item.enabled else "primary"
    item_type = "<span class='badge'>Собственное</span>" if item.own_production else "Поставка"
    status = "собственное" if item.own_production else ("в расчете" if item.enabled else "исключено")
    row_class = "" if item.enabled and not item.own_production else " class='disabled'"
    control = "не участвует" if item.own_production else f"""<form method="post" action="/menu/toggle">
<input type="hidden" name="name" value="{escape(item.normalized_name)}">
<input type="hidden" name="action" value="{action}">
<button class="{button_class}" type="submit">{button_label}</button>
</form>"""
    return f"""<tr{row_class}>
<td>{status}</td>
<td>{item_type}</td>
<td>{escape(item.group)}</td>
<td>{escape(item.sku)}</td>
<td>{escape(item.name)}</td>
<td class="number">{item.times_ordered}</td>
<td class="number">{_format_number(float(item.average_order_quantity))}</td>
<td>{control}</td>
</tr>"""


def _render_menu_coverage_block(coverage: dict[str, Any]) -> str:
    if not coverage:
        return ''
    groups = [('in_menu', 'Сопоставлено с поставляемым меню'),
              ('own_production', 'Кулинария ТТ'), ('outside_menu', 'Вне рабочего меню'),
              ('disabled', 'Выключено в меню')]
    summary = ''.join(f"<div><span>{label}</span><strong>{coverage.get(key, {}).get('items', 0)} поз. / {coverage.get(key, {}).get('quantity', 0)} шт.</strong></div>"
                      for key,label in groups)
    detail = ''.join(f"<details><summary>{label}: исторические продажи</summary><table class='mini-table'>"
                     "<thead><tr><th>Позиция</th><th>Категория</th><th>Продано</th><th>Сопоставление</th></tr></thead>"
                     f"<tbody>{_render_menu_coverage_rows(coverage[key]['rows'], empty='Нет строк.')}</tbody></table></details>"
                     for key,label in groups if coverage.get(key, {}).get('items'))
    return f"""<section id="reconciliation"><h2>Историческая сверка продаж и меню</h2>
    <p>{coverage.get('period_start', '')}—{coverage.get('period_end', '')}. Это продажи за весь указанный период,
    а не ближайший заказ и не остаток. «Вне рабочего меню» — ранее проданные блюда, не включенные в текущую поставку.
    Кофе, выпечка, упаковка и снеки исключены. В подробностях показаны первые 12 позиций каждой группы.</p>
    <div class="coverage-summary four">{summary}</div>{detail}</section>"""


def render_menu_html(items: list[Any], message: str = "", error: str = "") -> str:
    rows = "".join(_render_menu_row(item) for item in items) or (
        "<tr><td colspan='8'>Позиции меню пока не найдены. Загрузите XLSX-файл заказа в производство.</td></tr>"
    )
    notice = f"<p class='ok'>{escape(message)}</p>" if message else ""
    failure = f"<p class='error'>{escape(error)}</p>" if error else ""
    enabled_count = sum(1 for item in items if item.enabled)
    own_count = sum(1 for item in items if item.own_production)
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Управление меню</title><style>
body{{font-family:Arial,sans-serif;background:#f5f6f8;color:#17202a;margin:0}}main{{max-width:1180px;margin:30px auto;padding:0 20px}}
section{{background:white;border-radius:14px;padding:22px;margin:18px 0;box-shadow:0 4px 18px #00000010}}table{{width:100%;border-collapse:collapse}}
th,td{{padding:10px;border-bottom:1px solid #ddd;text-align:left;vertical-align:top}}button{{font:inherit;padding:8px 10px;border:0;border-radius:8px;cursor:pointer}}
input{{font:inherit;padding:10px}}.primary{{background:#176b55;color:white}}.secondary{{background:#eceff1;color:#17202a}}.muted{{color:#607069}}.ok{{color:#176b55}}.error{{color:#b42318}}a{{color:#176b55}}
.disabled{{color:#7a7f86;background:#fafafa}}.badge{{display:inline-block;padding:4px 7px;border-radius:999px;background:#e7efe9;color:#176b55;font-size:12px;font-weight:700}}.number{{text-align:right;font-variant-numeric:tabular-nums}}
</style></head><body><main><p><a href="/">← Заказы</a> · <a href="/production">Кулинария ТТ</a> · <a href="/analytics">Аналитика</a> · <a href="/reports">Отчёты</a></p>
<h1>Управление меню</h1>{notice}{failure}
<section><h2>Добавить данные</h2><form method="post" action="/menu/upload" enctype="multipart/form-data">
<label for="file">XLSX-файл заказа в производство</label>
<p><input id="file" name="file" type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" multiple required></p>
<p><button class="primary" type="submit">Загрузить заказы</button></p>
</form><p class="muted">Нужен файл с листом «Кулинария» и колонками «Артикул», «Товар», «К-во фасовок» или «Общее к-во».</p></section>
<section><p class="muted">Позиции со звездочкой в исходном файле помечаются как «Собственное». Они попадают в прогноз, но выводятся в блок производства, а не поставки.</p>
<p><strong>{enabled_count}</strong> участвует в прогнозе, <strong>{own_count}</strong> собственное, всего <strong>{len(items)}</strong> позиций.</p></section>
<section><table><thead><tr><th>Статус</th><th>Тип</th><th>Группа</th><th>Артикул</th><th>Позиция</th><th>Заказы</th><th>Среднее</th><th></th></tr></thead><tbody>{rows}</tbody></table></section>
</main></body></html>"""


def _render_menu_row(item: Any) -> str:
    action = "disable" if item.enabled else "enable"
    button_label = "Исключить из расчета" if item.enabled else "Вернуть в расчет"
    button_class = "secondary" if item.enabled else "primary"
    item_type = "<span class='badge'>Собственное</span>" if item.own_production else "Поставка"
    status = "в прогнозе" if item.enabled else "исключено"
    row_class = "" if item.enabled else " class='disabled'"
    control = f"""<form method="post" action="/menu/toggle">
<input type="hidden" name="name" value="{escape(item.normalized_name)}">
<input type="hidden" name="action" value="{action}">
<button class="{button_class}" type="submit">{button_label}</button>
</form>"""
    return f"""<tr{row_class}>
<td>{status}</td>
<td>{item_type}</td>
<td>{escape(item.group)}</td>
<td>{escape(item.sku)}</td>
<td>{escape(item.name)}</td>
<td class="number">{item.times_ordered}</td>
<td class="number">{_format_number(float(item.average_order_quantity))}</td>
<td>{control}</td>
</tr>"""


def render_menu_html(items: list[Any], message: str = "", error: str = "") -> str:
    rows = "".join(_render_menu_row(item) for item in items) or (
        "<tr><td colspan='8'>Позиции меню пока не найдены. Загрузите XLSX-файл заказа в производство.</td></tr>"
    )
    notice = f"<p class='ok'>{escape(message)}</p>" if message else ""
    failure = f"<p class='error'>{escape(error)}</p>" if error else ""
    enabled_count = sum(1 for item in items if item.enabled)
    own_count = sum(1 for item in items if item.own_production)
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Управление меню</title><style>
body{{font-family:Arial,sans-serif;background:#f5f6f8;color:#17202a;margin:0}}main{{max-width:1180px;margin:30px auto;padding:0 20px}}
section{{background:white;border-radius:14px;padding:22px;margin:18px 0;box-shadow:0 4px 18px #00000010}}table{{width:100%;border-collapse:collapse}}
th,td{{padding:10px;border-bottom:1px solid #ddd;text-align:left;vertical-align:top}}button{{font:inherit;padding:8px 10px;border:0;border-radius:8px;cursor:pointer}}
input{{font:inherit;padding:10px}}.primary{{background:#176b55;color:white}}.secondary{{background:#eceff1;color:#17202a}}.muted{{color:#607069}}.ok{{color:#176b55}}.error{{color:#b42318}}a{{color:#176b55}}
.disabled{{color:#7a7f86;background:#fafafa}}.badge{{display:inline-block;padding:4px 7px;border-radius:999px;background:#e7efe9;color:#176b55;font-size:12px;font-weight:700}}.number{{text-align:right;font-variant-numeric:tabular-nums}}
.actions{{display:flex;gap:8px;flex-wrap:wrap}}.actions form{{display:inline}}
</style></head><body><main><p><a href="/">← Заказы</a> · <a href="/production">Кулинария ТТ</a> · <a href="/analytics">Аналитика</a> · <a href="/reports">Отчёты</a></p>
<h1>Управление меню</h1>{notice}{failure}
<section><h2>Добавить данные</h2><form method="post" action="/menu/upload" enctype="multipart/form-data">
<label for="file">XLSX-файл заказа в производство</label>
<p><input id="file" name="file" type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" multiple required></p>
<p><button class="primary" type="submit">Загрузить заказы</button></p>
</form><p class="muted">Нужен файл с листом «Кулинария» и колонками «Артикул», «Товар», «К-во фасовок» или «Общее к-во».</p></section>
<section><p class="muted">Звездочка в исходном файле считается технической пометкой и не меняет тип позиции. Тип «Поставка» или «Собственное» задается вручную здесь.</p>
<p><strong>{enabled_count}</strong> участвует в прогнозе, <strong>{own_count}</strong> собственное, всего <strong>{len(items)}</strong> позиций.</p></section>
<section><table><thead><tr><th>Статус</th><th>Тип</th><th>Группа</th><th>Артикул</th><th>Позиция</th><th>Заказы</th><th>Среднее</th><th></th></tr></thead><tbody>{rows}</tbody></table></section>
</main></body></html>"""


def _render_menu_row(item: Any) -> str:
    action = "disable" if item.enabled else "enable"
    button_label = "Исключить из расчета" if item.enabled else "Вернуть в расчет"
    button_class = "secondary" if item.enabled else "primary"
    next_type = "supplier" if item.own_production else "own_production"
    supply_button = "Сделать поставкой" if item.own_production else "Сделать собственным"
    item_type = "<span class='badge'>Собственное</span>" if item.own_production else "Поставка"
    status = "в прогнозе" if item.enabled else "исключено"
    row_class = "" if item.enabled else " class='disabled'"
    control = f"""<div class="actions"><form method="post" action="/menu/toggle">
<input type="hidden" name="name" value="{escape(item.normalized_name)}">
<input type="hidden" name="action" value="{action}">
<button class="{button_class}" type="submit">{button_label}</button>
</form><form method="post" action="/menu/supply">
<input type="hidden" name="name" value="{escape(item.normalized_name)}">
<input type="hidden" name="type" value="{next_type}">
<button class="secondary" type="submit">{supply_button}</button>
</form></div>"""
    return f"""<tr{row_class}>
<td>{status}</td>
<td>{item_type}</td>
<td>{escape(item.group)}</td>
<td>{escape(item.sku)}</td>
<td>{escape(item.name)}</td>
<td class="number">{item.times_ordered}</td>
<td class="number">{_format_number(float(item.average_order_quantity))}</td>
<td>{control}</td>
</tr>"""


def _url_quote(value: str) -> str:
    from urllib.parse import quote

    return quote(value)


def server_port() -> int:
    return int(os.getenv("PORT", os.getenv("APP_PORT", "8000")))


def run_server() -> None:
    port = server_port()
    server = DashboardServer(("0.0.0.0", port), DashboardHandler)
    print(json.dumps({"level": "info", "event": "server_started", "port": port}))
    server.serve_forever()


def _payload_from_query(query: str, *, loss_month: date | None = None) -> dict[str, Any]:
    params = parse_qs(query)
    start_raw = params.get("start", [None])[0]
    days_raw = params.get("days", ["14"])[0]
    return build_dashboard_payload(
        start_day=date.fromisoformat(start_raw) if start_raw else None,
        horizon_days=int(days_raw),
        service_level=float(params.get('service', ['85'])[0]) / 100,
        profit_tolerance=float(params.get('reserve_cost', ['5'])[0]) / 100,
        **({'loss_month': loss_month} if loss_month is not None else {}),
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
