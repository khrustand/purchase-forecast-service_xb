from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from scripts.analyze_culinary_strategy import (
    build_daily_menu,
    build_recommendations,
    extract_items,
    extract_shelf_life,
    extract_waste_counts,
    read_xlsx,
)
from src.app.web_server import (
    DEFAULT_ORDER_CYCLE_DAYS,
    DEFAULT_SALES_PATH,
    DEFAULT_SHELF_LIFE_PATH,
    DEFAULT_WASTE_PATH,
    _latest_sales_day,
    _period_quantity,
    _weather_factor,
    _weather_summary,
    _with_decision_explanations,
)


def main() -> int:
    start_day = date(2026, 6, 1)
    sales_rows = read_xlsx(DEFAULT_SALES_PATH)
    scanned_items = extract_items(sales_rows, start_day, date(2026, 8, 31))
    end_day = _latest_sales_day(scanned_items) or date(2026, 8, 3)
    items = extract_items(sales_rows, start_day, end_day)
    waste_counts = extract_waste_counts(DEFAULT_WASTE_PATH, items, start_day, end_day)
    shelf_life = extract_shelf_life(DEFAULT_SHELF_LIFE_PATH, items)
    recommendations = build_recommendations(items, DEFAULT_ORDER_CYCLE_DAYS, waste_counts, shelf_life)
    menu = _with_decision_explanations(build_daily_menu(recommendations))
    item_by_name = {item.name: item for item in items}

    rows = []
    cursor = start_day
    while cursor <= end_day:
        if cursor.weekday() == 4 and cursor + timedelta(days=2) <= end_day:
            period_days = [cursor + timedelta(days=offset) for offset in range(3)]
            actual_all = sum(
                int(sum(source.by_date.get(day, 0) for day in period_days))
                for source in item_by_name.values()
            )
            actual_menu = 0
            for item in menu:
                source = item_by_name.get(str(item["name"]))
                actual_menu += int(sum(source.by_date.get(day, 0) for day in period_days)) if source else 0
            current_model = sum(_period_quantity(item, period_days) for item in menu)
            linear_model = sum(_linear_period_quantity(item, period_days) for item in menu)
            rows.append(
                {
                    "start": cursor,
                    "end": period_days[-1],
                    "actual_menu": actual_menu,
                    "actual_all": actual_all,
                    "current_model": current_model,
                    "linear_model": linear_model,
                    "weather": _weather_summary(period_days),
                }
            )
        cursor += timedelta(days=1)

    print(f"Период данных: {start_day.isoformat()}..{end_day.isoformat()}")
    print("| Пт+Сб+Вс | Факт по меню | Факт все SKU | Текущая модель | Разница | Старая 3-дн. модель | Разница | Погода |")
    print("| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
    for row in rows:
        print(
            f"| {row['start'].isoformat()}..{row['end'].isoformat()} "
            f"| {row['actual_menu']} "
            f"| {row['actual_all']} "
            f"| {row['current_model']} "
            f"| {row['current_model'] - row['actual_menu']:+} "
            f"| {row['linear_model']} "
            f"| {row['linear_model'] - row['actual_menu']:+} "
            f"| {row['weather']} |"
        )
    if rows:
        average_actual = sum(row["actual_menu"] for row in rows) / len(rows)
        average_actual_all = sum(row["actual_all"] for row in rows) / len(rows)
        average_current = sum(row["current_model"] for row in rows) / len(rows)
        average_linear = sum(row["linear_model"] for row in rows) / len(rows)
        current_over_count = sum(1 for row in rows if row["current_model"] > row["actual_menu"])
        linear_over_count = sum(1 for row in rows if row["linear_model"] > row["actual_menu"])
        print("")
        print(f"Средний факт по меню: {average_actual:.1f}")
        print(f"Средний факт все SKU: {average_actual_all:.1f}")
        print(f"Средняя текущая модель: {average_current:.1f}")
        print(f"Средняя старая 3-дн. модель: {average_linear:.1f}")
        print(f"Текущая модель выше факта: {current_over_count} из {len(rows)} окон")
        print(f"Старая 3-дн. модель выше факта: {linear_over_count} из {len(rows)} окон")
    return 0


def _linear_period_quantity(item: dict[str, object], period_days: list[date]) -> int:
    base_daily = int(item["order_for_2_days"]) / DEFAULT_ORDER_CYCLE_DAYS
    shelf_life_days = int(item.get("shelf_life_days", 3))
    effective_days = min(len(period_days), shelf_life_days)
    quantity = base_daily * effective_days * _weather_factor(str(item["category"]), period_days)
    return max(1, round(quantity))


if __name__ == "__main__":
    raise SystemExit(main())
