from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date
from pathlib import Path

from src.app.web_server import build_dashboard_payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Сформировать отчет заказа на выбранную дату.")
    parser.add_argument("--date", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    strategy = build_dashboard_payload(start_day=args.date, horizon_days=7)["culinary_strategy"]
    if strategy is None:
        raise SystemExit("Не найдены данные продаж кулинарии.")
    order = strategy["future_orders"][0]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_report(strategy, order), encoding="utf-8")
    print(f"Отчет сохранен: {args.output}")
    return 0


def render_report(strategy: dict[str, object], order: dict[str, object]) -> str:
    rows = list(order["rows"])
    primary = [item for item in rows if "резерв" not in str(item["menu_role"])]
    reserve = [item for item in rows if item not in primary]
    category_totals: dict[str, int] = defaultdict(int)
    for item in primary:
        category_totals[str(item["category"])] += int(item["forecast_quantity"])

    lines = [
        f"# Заказ кулинарии на {order['start']}–{order['end']}",
        "",
        f"Дата формирования: {order['start']}. Окно заказа: {order['start']}..{order['end']}.",
        f"История продаж модели: {strategy['period']}.",
        f"Погода: {order['weather']}.",
        "",
        "## Итог",
        "",
        f"Основной заказ: **{sum(int(item['forecast_quantity']) for item in primary)} шт., {len(primary)} SKU**.",
        f"Резерв с высоким риском списаний: **{sum(int(item['forecast_quantity']) for item in reserve)} шт., {len(reserve)} SKU** — не заказывать без проверки витрины и остатков.",
        "",
        "Дневная разбивка: " + ", ".join(
            f"{day['weekday']} {day['date']} — **{day['quantity']} шт.**"
            for day in order["daily_totals"]
        ) + ".",
        "",
        "| Категория | Основной заказ, шт. |",
        "| --- | ---: |",
    ]
    lines.extend(f"| {category} | {quantity} |" for category, quantity in sorted(category_totals.items()))
    lines.extend([
        "",
        "## Что заказать",
        "",
        "| Категория | Позиция | Заказ | По дням | Продажи за период | Прошлое окно | Списания | Почему |",
        "| --- | --- | ---: | --- | ---: | ---: | ---: | --- |",
    ])
    for item in primary:
        daily = " / ".join(
            f"{day['weekday']}: {day['quantity']}" for day in item["daily_forecast"]
        )
        reason = (
            f"{item['decision_reason']}; {item['risk_reason']}; "
            f"погода ×{item['weather_factor']}"
        )
        lines.append(
            f"| {item['category']} | {item['name']} | {item['forecast_quantity']} | "
            f"{daily} | "
            f"{item['sales_june_july']} | {item['previous_period_sales']} | "
            f"{item['waste_count']} | {reason} |"
        )

    lines.extend([
        "",
        "## Резерв — сначала проверить остаток",
        "",
        "| Категория | Позиция | Возможный объем | Причина ограничения |",
        "| --- | --- | ---: | --- |",
    ])
    for item in reserve:
        lines.append(
            f"| {item['category']} | {item['name']} | {item['forecast_quantity']} | "
            f"{item['risk_reason']}; {item['strategy']} |"
        )

    lines.extend([
        "",
        "## Логика и ограничения",
        "",
        "- База — продажи по SKU за 01.06–03.08.2026; более старые апрель–май используются для проверки общего сезонного направления.",
        "- Для дождливого прохладного окна модель мягко повышает горячее и супы, снижает салаты; погода не заменяет историю продаж.",
        "- Страховой запас уменьшается при частых списаниях и сроке годности 2 дня.",
        "- Остатки на 19.08 в данных отсутствуют. Перед отправкой поставщику из каждой строки нужно вычесть фактический пригодный остаток.",
        "- В актах есть факт попадания SKU в списание, но нет точного количества списанных единиц.",
        "- Если поставщик принимает только партии от 4 шт., строки на 1–3 шт. следует объединить с ротацией или не заказывать без ручного подтверждения.",
    ])
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
