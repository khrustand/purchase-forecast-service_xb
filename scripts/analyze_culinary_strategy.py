from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zipfile import ZipFile


MAIN_NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_NS = {"rel": "http://schemas.openxmlformats.org/package/2006/relationships"}
WEEKDAY_LABELS = {
    0: "ПН",
    1: "ВТ",
    2: "СР",
    3: "ЧТ",
    4: "ПТ",
    5: "СБ",
    6: "ВС",
}
EXCLUDED_CATEGORIES = {"Топпинги/Кулинария ТТ"}
DAILY_MENU_QUOTAS = {
    "Супы": 8,
    "Горячее": 9,
}
FLEX_MENU_CATEGORIES = {"Завтраки", "Салаты", "Роллы"}
FLEX_MENU_TARGET = 17
HIGH_WASTE_RISK = "высокий риск списаний"


@dataclass(frozen=True)
class DailySalesItem:
    category: str
    name: str
    by_date: dict[date, float]

    @property
    def total(self) -> float:
        return sum(self.by_date.values())

    @property
    def active_days(self) -> int:
        return sum(1 for value in self.by_date.values() if value > 0)

    @property
    def average_per_day(self) -> float:
        return self.total / len(self.by_date) if self.by_date else 0

    @property
    def demand_days_average(self) -> float:
        values = [value for value in self.by_date.values() if value > 0]
        return sum(values) / len(values) if values else 0

    @property
    def variation(self) -> float:
        values = list(self.by_date.values())
        average = self.average_per_day
        if len(values) < 2 or average == 0:
            return 0
        return statistics.pstdev(values) / average


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Построить стратегию заказов кулинарии без шаблонной методики бланка."
    )
    parser.add_argument("--sales", type=Path, required=True)
    parser.add_argument("--waste", type=Path)
    parser.add_argument("--shelf-life", type=Path)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2026, 6, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 7, 31))
    parser.add_argument("--days", type=int, default=2)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    rows = read_xlsx(args.sales)
    items = extract_items(rows, args.start, args.end)
    waste_counts = extract_waste_counts(args.waste, items, args.start, args.end) if args.waste else {}
    shelf_life = extract_shelf_life(args.shelf_life, items) if args.shelf_life else {}
    recommendations = build_recommendations(items, args.days, waste_counts, shelf_life)
    daily_menu = build_daily_menu(recommendations)
    payload = {
        "period": f"{args.start.isoformat()}..{args.end.isoformat()}",
        "days": args.days,
        "items_total": len(items),
        "sales_total": int(sum(item.total for item in items)),
        "category_summary": category_summary(items, recommendations),
        "top_items": top_items(items, 15),
        "waste_leaders": waste_leaders(recommendations),
        "daily_menu": daily_menu,
        "daily_menu_summary": daily_menu_summary(daily_menu),
        "recommendations": recommendations,
        "mechanics": [
            "не используем группы ПН+ВТ / СР+ЧТ / ПТ+СБ+ВС из бланка как правило заказа",
            "считаем базовый спрос по каждому SKU из фактических продаж за июнь-июль",
            "сопоставляем акты списания с позициями по названию и считаем частоту попадания в списания",
            "сверяем сроки хранения с файлом по срокам годности: по умолчанию готовая кулинария считается на 3 дня, найденные 2-дневные позиции ограничивают запас",
            "оцениваем стабильность: сколько дней позиция реально продавалась и насколько скачет спрос",
            "делим позиции на A/B/C по доле продаж и стабильности",
            "штрафуем позиции с частыми списаниями и слабым спросом",
            "собираем дневную ротацию из 34 позиций: 8 супов, 9 вторых, 17 завтраков и салатов",
            "в основную витрину сначала ставим позиции без высокого риска списаний, высокорисковые берем только как вынужденную подмену",
            "для заказа на N дней берем среднедневной спрос, добавляем запас по классу и уменьшаем запас при риске списаний",
            "остатки пока не вычитаются, потому что их нет в выгрузке продаж",
        ],
    }

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(render_markdown(payload), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def extract_items(rows: list[list[str | None]], start: date, end: date) -> list[DailySalesItem]:
    daily_period = daily_sales_period(rows)
    if daily_period is not None:
        day = daily_period[0]
        if not start <= day <= end:
            return []
        items = []
        for row in rows[4:]:
            if len(row) < 5:
                continue
            category, name = clean(row[0]), clean(row[1])
            if not category or not name or name.lower().startswith(('итого', 'всего')):
                continue
            quantity = number(row[4])
            if quantity > 0 and category not in EXCLUDED_CATEGORIES:
                items.append(DailySalesItem(category, name, {day: quantity}))
        return items
    header = rows[5]
    date_columns = [
        (index, parsed)
        for index, value in enumerate(header)
        for parsed in [excel_date(value)]
        if parsed and start <= parsed <= end
    ]
    items: list[DailySalesItem] = []
    current_category = ""

    for row in rows[6:]:
        if not row:
            continue
        category = clean(row[0] if len(row) > 0 else None)
        name = clean(row[1] if len(row) > 1 else None)
        if category:
            current_category = category
        if not name or "всего" in name.lower() or "всего" in current_category.lower():
            continue
        if current_category in EXCLUDED_CATEGORIES:
            continue

        by_date = {
            day: number(row[index])
            for index, day in date_columns
            if index < len(row) and row[index] is not None and str(row[index]).strip() != ""
        }
        if sum(by_date.values()) <= 0:
            continue
        items.append(DailySalesItem(current_category, name, by_date))

    return items


def daily_sales_period(rows: list[list[str | None]]) -> tuple[date, date] | None:
    """Распознать суточный отчет с количеством и выручкой вместо колонок дат."""
    if len(rows) < 4 or rows[3][:2] != ['Категория', 'Элемент номенклатуры']:
        return None
    if len(rows[3]) < 5 or rows[3][4] != 'Количество':
        return None
    text = ' '.join(str(value or '') for row in rows[:3] for value in row)
    match = re.search(r'За период:\s*с\s*(\d{2}\.\d{2}\.\d{4})\s*по\s*(\d{2}\.\d{2}\.\d{4})', text)
    if not match:
        raise ValueError('в суточном отчете не найден период')
    start, end = (datetime.strptime(value, '%d.%m.%Y').date() for value in match.groups())
    if start != end:
        raise ValueError('сводный отчет за несколько дней не содержит разбивки продаж по датам')
    return start, end


def build_recommendations(
    items: list[DailySalesItem],
    days: int,
    waste_counts: dict[str, int],
    shelf_life: dict[str, dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    sorted_items = sorted(items, key=lambda item: item.total, reverse=True)
    total_sales = sum(item.total for item in sorted_items) or 1
    cumulative = 0.0
    recommendations = []

    for item in sorted_items:
        cumulative += item.total
        share = cumulative / total_sales
        abc_class = abc_class_for(share)
        stability = stability_for(item)
        safety_rate = safety_rate_for(abc_class, stability)
        waste_count = waste_counts.get(normalize_name(item.name), 0)
        waste_risk = waste_risk_for(item, waste_count)
        shelf = shelf_life_for(item, shelf_life or {})
        shelf_life_days = int(shelf["days"])
        shelf_life_source = str(shelf["source"])
        if waste_risk == "высокий риск списаний":
            safety_rate = 0
        elif waste_risk == "средний риск списаний":
            safety_rate = min(safety_rate, 0.05)
        if shelf_life_days <= days:
            safety_rate = 0
        effective_days = min(days, shelf_life_days)
        raw_order = item.average_per_day * effective_days * (1 + safety_rate)
        rounded_order = round_order(raw_order, item, abc_class)
        if rounded_order <= 0:
            continue
        recommendations.append(
            {
                "category": item.category,
                "name": item.name,
                "sales_june_july": int(item.total),
                "active_days": item.active_days,
                "average_per_day": round(item.average_per_day, 2),
                "demand_days_average": round(item.demand_days_average, 2),
                "variation": round(item.variation, 2),
                "abc_class": abc_class,
                "stability": stability,
                "waste_count": waste_count,
                "waste_risk": waste_risk,
                "shelf_life_days": shelf_life_days,
                "shelf_life_source": shelf_life_source,
                "shelf_life_risk": shelf_life_risk_for(shelf_life_days, days),
                "menu_score": round(menu_score(item, waste_count), 2),
                "order_for_2_days": rounded_order,
                "strategy": strategy_for(abc_class, stability, rounded_order, waste_risk),
            }
        )

    return sorted(
        recommendations,
        key=lambda value: (str(value["category"]), -int(value["order_for_2_days"]), str(value["name"])),
    )


def abc_class_for(cumulative_share: float) -> str:
    if cumulative_share <= 0.80:
        return "A"
    if cumulative_share <= 0.95:
        return "B"
    return "C"


def stability_for(item: DailySalesItem) -> str:
    if item.active_days < 8:
        return "редкий спрос"
    if item.variation <= 1.2:
        return "стабильный спрос"
    if item.variation <= 2.0:
        return "плавающий спрос"
    return "рваный спрос"


def safety_rate_for(abc_class: str, stability: str) -> float:
    if abc_class == "A" and stability == "стабильный спрос":
        return 0.20
    if abc_class == "A":
        return 0.15
    if abc_class == "B":
        return 0.10
    return 0.00


def round_order(value: float, item: DailySalesItem, abc_class: str) -> int:
    rounded = math.ceil(value)
    if rounded <= 0:
        return 0
    if abc_class == "A":
        return max(3, rounded)
    if abc_class == "B":
        return max(2, rounded)
    if item.active_days >= 8 and item.total >= 20:
        return max(1, min(2, rounded))
    return 0


def waste_risk_for(item: DailySalesItem, waste_count: int) -> str:
    if waste_count >= 8 and item.average_per_day < 1.5:
        return "высокий риск списаний"
    if waste_count >= 5:
        return "средний риск списаний"
    if waste_count >= 1:
        return "низкий риск списаний"
    return "списаний не найдено"


def shelf_life_risk_for(shelf_life_days: int, order_days: int) -> str:
    if shelf_life_days < order_days:
        return "срок меньше горизонта заказа"
    if shelf_life_days == order_days:
        return "без запаса сверх горизонта"
    return "срок покрывает горизонт заказа"


def shelf_life_for(
    item: DailySalesItem,
    shelf_life: dict[str, dict[str, object]],
) -> dict[str, object]:
    return shelf_life.get(
        normalize_name(item.name),
        {"days": 3, "source": "правило по умолчанию: готовая кулинария 3 дня"},
    )


def menu_score(item: DailySalesItem, waste_count: int) -> float:
    return item.total + item.active_days * 1.5 - waste_count * 8


def strategy_for(abc_class: str, stability: str, order: int, waste_risk: str) -> str:
    if waste_risk == "высокий риск списаний":
        return "заказывать реже или исключить из ежедневной витрины"
    if waste_risk == "средний риск списаний" and abc_class != "A":
        return "оставить только в ротации, без страхового запаса"
    if abc_class == "A":
        return "держать регулярно, контролировать остаток каждый заказ"
    if abc_class == "B":
        return "заказывать осторожно, усиливать при росте продаж"
    if order > 0:
        return "держать в ротации, не ставить во все дни"
    return "не заказывать без ручной причины"


def build_daily_menu(recommendations: list[dict[str, object]]) -> list[dict[str, object]]:
    selected: list[dict[str, object]] = []
    by_category: dict[str, list[dict[str, object]]] = {}
    for item in recommendations:
        by_category.setdefault(str(item["category"]), []).append(item)

    def sort_key(item: dict[str, object]) -> tuple[float, int]:
        return (float(item["menu_score"]), int(item["sales_june_july"]))

    def select_for_menu(candidates: list[dict[str, object]], limit: int) -> list[dict[str, object]]:
        sorted_candidates = sorted(candidates, key=sort_key, reverse=True)
        primary = [item for item in sorted_candidates if str(item["waste_risk"]) != HIGH_WASTE_RISK]
        fallback = [item for item in sorted_candidates if str(item["waste_risk"]) == HIGH_WASTE_RISK]
        return (primary + fallback)[:limit]

    for category, limit in DAILY_MENU_QUOTAS.items():
        selected.extend(select_for_menu(by_category.get(category, []), limit))

    flex_items = [
        item
        for category in FLEX_MENU_CATEGORIES
        for item in by_category.get(category, [])
    ]
    selected.extend(select_for_menu(flex_items, FLEX_MENU_TARGET))

    return sorted(
        [
            {
                "category": item["category"],
                "name": item["name"],
                "order_for_2_days": item["order_for_2_days"],
                "sales_june_july": item["sales_june_july"],
                "shelf_life_days": item["shelf_life_days"],
                "waste_count": item["waste_count"],
                "waste_risk": item["waste_risk"],
                "active_days": item.get("active_days", 0),
                "average_per_day": item.get("average_per_day", 0),
                "abc_class": item.get("abc_class", "-"),
                "stability": item.get("stability", "нет оценки"),
                "shelf_life_risk": item["shelf_life_risk"],
                "menu_role": menu_role_for(item),
                "strategy": item["strategy"],
            }
            for item in selected
        ],
        key=lambda value: (str(value["category"]), str(value["name"])),
    )


def menu_role_for(item: dict[str, object]) -> str:
    if str(item["waste_risk"]) == HIGH_WASTE_RISK:
        return "резерв: только если не хватает безопасных позиций"
    return "основная витрина"


def daily_menu_summary(daily_menu: list[dict[str, object]]) -> dict[str, object]:
    target_total = sum(DAILY_MENU_QUOTAS.values()) + FLEX_MENU_TARGET
    high_risk_count = sum(1 for item in daily_menu if str(item["waste_risk"]) == HIGH_WASTE_RISK)
    by_category: dict[str, int] = {}
    for item in daily_menu:
        by_category[str(item["category"])] = by_category.get(str(item["category"]), 0) + 1
    return {
        "target_total": target_total,
        "actual_total": len(daily_menu),
        "shortfall": max(0, target_total - len(daily_menu)),
        "high_risk_count": high_risk_count,
        "by_category": by_category,
    }


def extract_shelf_life(path: Path, items: list[DailySalesItem]) -> dict[str, dict[str, object]]:
    result = {normalize_name(item.name): {"days": 3, "source": "правило по умолчанию: готовая кулинария 3 дня"} for item in items}
    item_names = {normalize_name(item.name): item.name for item in items}
    for sheet_name in ("Хранение и реализация сырья для", "Хранение и сроки годности"):
        try:
            rows = read_xlsx(path, sheet_name)
        except ValueError:
            continue
        for row in rows:
            row_text = " ".join(clean(value) for value in row if clean(value))
            if not row_text:
                continue
            shelf_days = parse_shelf_life_days(row_text)
            if shelf_days is None:
                continue
            shelf_name = normalize_shelf_name(clean(row[1] if len(row) > 1 else row[0]))
            if not shelf_name:
                continue
            for item_key, item_name in item_names.items():
                if shelf_name_matches_item(shelf_name, item_key):
                    current_days = int(result[item_key]["days"])
                    if shelf_days <= current_days:
                        result[item_key] = {
                            "days": shelf_days,
                            "source": f"{sheet_name}: {shelf_name}",
                        }
    return result


def parse_shelf_life_days(value: str) -> int | None:
    normalized = normalize_name(value)
    matches = re.findall(r"(\d+)\s*(час|часа|часов|ч\.|сут|суток|дня|дней|день)", normalized)
    days: list[int] = []
    for amount_raw, unit in matches:
        amount = int(amount_raw)
        if unit.startswith("час") or unit == "ч.":
            if amount >= 24:
                days.append(max(1, math.ceil(amount / 24)))
        else:
            days.append(amount)
    relevant_days = [day for day in days if 2 <= day <= 3]
    return min(relevant_days) if relevant_days else None


def normalize_shelf_name(value: str) -> str:
    normalized = normalize_name(value)
    normalized = re.sub(r"\bп\s*/?\s*ф\b", "", normalized)
    normalized = normalized.replace("(точки)", "")
    normalized = re.sub(r"\([^)]*\)", "", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def shelf_name_matches_item(shelf_name: str, item_name: str) -> bool:
    if not shelf_name or len(shelf_name) < 5:
        return False
    if shelf_name in item_name or item_name in shelf_name:
        return True
    stop_words = {
        "салат",
        "суп",
        "паста",
        "соус",
        "готовая",
        "смесь",
        "начинки",
        "ассортименте",
        "точки",
        "куриной",
        "куриный",
    }
    shelf_words = {
        word
        for word in re.findall(r"[а-яёa-z0-9]+", shelf_name)
        if len(word) >= 5 and word not in stop_words
    }
    item_words = set(re.findall(r"[а-яёa-z0-9]+", item_name))
    return len(shelf_words & item_words) >= 2


def waste_leaders(recommendations: list[dict[str, object]], limit: int = 20) -> list[dict[str, object]]:
    items = [item for item in recommendations if int(item["waste_count"]) > 0]
    return sorted(
        [
            {
                "category": item["category"],
                "name": item["name"],
                "sales_june_july": item["sales_june_july"],
                "shelf_life_days": item["shelf_life_days"],
                "waste_count": item["waste_count"],
                "waste_risk": item["waste_risk"],
                "active_days": item.get("active_days", 0),
                "average_per_day": item.get("average_per_day", 0),
                "abc_class": item.get("abc_class", "-"),
                "stability": item.get("stability", "нет оценки"),
                "strategy": item["strategy"],
            }
            for item in items
        ],
        key=lambda value: (-int(value["waste_count"]), str(value["category"]), str(value["name"])),
    )[:limit]


def category_summary(
    items: list[DailySalesItem],
    recommendations: list[dict[str, object]],
) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for item in items:
        summary.setdefault(item.category, {"sales": 0, "sku": 0, "order_for_2_days": 0})
        summary[item.category]["sales"] += int(item.total)
        summary[item.category]["sku"] += 1
    for item in recommendations:
        category = str(item["category"])
        summary.setdefault(category, {"sales": 0, "sku": 0, "order_for_2_days": 0})
        summary[category]["order_for_2_days"] += int(item["order_for_2_days"])
    return dict(sorted(summary.items()))


def top_items(items: list[DailySalesItem], limit: int) -> list[dict[str, object]]:
    return [
        {
            "category": item.category,
            "name": item.name,
            "sales_june_july": int(item.total),
            "active_days": item.active_days,
            "average_per_day": round(item.average_per_day, 2),
        }
        for item in sorted(items, key=lambda value: value.total, reverse=True)[:limit]
    ]


def render_markdown(payload: dict[str, object]) -> str:
    lines = [
        "# Стратегия заказов кулинарии",
        "",
        f"Период анализа: {payload['period']}.",
        f"Горизонт заказа: {payload['days']} дня.",
        f"Позиций в анализе: {payload['items_total']}.",
        f"Продаж за период: {payload['sales_total']} шт.",
        "",
        "## Механика",
        "",
    ]
    mechanics = payload["mechanics"]
    assert isinstance(mechanics, list)
    lines.extend(f"- {item}" for item in mechanics)
    lines.extend(
        [
            "",
            "## Сводка по категориям",
            "",
            "| Категория | SKU | Продажи июнь-июль | Заказ на 2 дня |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    category_summary_raw = payload["category_summary"]
    assert isinstance(category_summary_raw, dict)
    for category, totals in category_summary_raw.items():
        lines.append(
            f"| {category} | {totals['sku']} | {totals['sales']} | {totals['order_for_2_days']} |"
        )

    lines.extend(
        [
            "",
            "## Ротация меню на день",
            "",
            "Цель: 34 позиции в день: 8 супов, 9 вторых, 17 завтраков и салатов.",
            "",
        ]
    )
    menu_summary = payload["daily_menu_summary"]
    assert isinstance(menu_summary, dict)
    lines.extend(
        [
            f"Фактически подобрано: {menu_summary['actual_total']} из {menu_summary['target_total']} позиций.",
            f"Недобор до цели: {menu_summary['shortfall']} поз.",
            f"Высокорисковых резервных позиций в подборе: {menu_summary['high_risk_count']}.",
            "",
            "| Категория | Позиция | Заказ на 2 дня | Продажи | Срок, дней | Списания, попаданий | Риск | Роль в меню | Стратегия |",
            "| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- |",
        ]
    )
    daily_menu = payload["daily_menu"]
    assert isinstance(daily_menu, list)
    for item in daily_menu:
        lines.append(
            f"| {item['category']} | {item['name']} | {item['order_for_2_days']} | "
            f"{item['sales_june_july']} | {item['shelf_life_days']} | {item['waste_count']} | {item['waste_risk']} | "
            f"{item['menu_role']} | {item['strategy']} |"
        )

    lines.extend(
        [
            "",
            "## Кандидаты на редкий заказ или исключение",
            "",
            "| Категория | Позиция | Продажи | Срок, дней | Списания, попаданий | Риск | Стратегия |",
            "| --- | --- | ---: | ---: | ---: | --- | --- |",
        ]
    )
    waste_items = payload["waste_leaders"]
    assert isinstance(waste_items, list)
    for item in waste_items:
        lines.append(
            f"| {item['category']} | {item['name']} | {item['sales_june_july']} | "
            f"{item['shelf_life_days']} | {item['waste_count']} | {item['waste_risk']} | {item['strategy']} |"
        )

    lines.extend(
        [
            "",
            "## Рекомендации заказа",
            "",
            "| Категория | Позиция | Продажи | Дней с продажами | Среднее в день | Класс | Стабильность | Срок, дней | Риск срока | Списания | Риск списаний | Заказ на 2 дня | Стратегия |",
            "| --- | --- | ---: | ---: | ---: | --- | --- | ---: | --- | ---: | --- | ---: | --- |",
        ]
    )
    recommendations = payload["recommendations"]
    assert isinstance(recommendations, list)
    for item in recommendations:
        lines.append(
            f"| {item['category']} | {item['name']} | {item['sales_june_july']} | "
            f"{item['active_days']} | {item['average_per_day']} | {item['abc_class']} | "
            f"{item['stability']} | {item['shelf_life_days']} | {item['shelf_life_risk']} | "
            f"{item['waste_count']} | {item['waste_risk']} | "
            f"{item['order_for_2_days']} | {item['strategy']} |"
        )
    return "\n".join(lines) + "\n"


def extract_waste_counts(
    path: Path,
    items: list[DailySalesItem],
    start: date,
    end: date,
) -> dict[str, int]:
    rows = read_xlsx(path)
    names = {normalize_name(item.name): item.name for item in items}
    counts = {normalized: 0 for normalized in names}
    for row in rows[4:]:
        if len(row) < 4:
            continue
        day = parse_datetime(row[0])
        if day is None or not (start <= day <= end):
            continue
        goods = normalize_name(row[3])
        if not goods:
            continue
        for normalized_name in names:
            if normalized_name and normalized_name in goods:
                counts[normalized_name] += 1
    return counts


def parse_datetime(value: str | None) -> date | None:
    if not value:
        return None
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            return datetime.strptime(str(value), fmt).date()
        except ValueError:
            continue
    return None


def normalize_name(value: str | None) -> str:
    normalized = clean(value).lower()
    normalized = normalized.replace("ё", "е")
    normalized = normalized.replace("*", "")
    normalized = re.sub(r"\s+,", ",", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def read_xlsx(path: Path, sheet_name: str | None = None) -> list[list[str | None]]:
    with ZipFile(path) as archive:
        strings = shared_strings(archive)
        _, sheet_path = select_sheet(archive, sheet_name)
        root = ET.fromstring(archive.read(sheet_path))
        rows = []
        for row in root.findall("a:sheetData/a:row", MAIN_NS):
            values: list[str | None] = []
            for cell in row.findall("a:c", MAIN_NS):
                index = column_index(cell.attrib["r"])
                while len(values) <= index:
                    values.append(None)
                values[index] = cell_value(cell, strings)
            rows.append(values)
        return rows


def shared_strings(archive: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return [
        "".join(text.text or "" for text in item.findall(".//a:t", MAIN_NS))
        for item in root.findall("a:si", MAIN_NS)
    ]


def select_sheet(archive: ZipFile, sheet_name: str | None) -> tuple[str, str]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    relationship_map = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in relationships.findall("rel:Relationship", REL_NS)
    }
    for sheet in workbook.findall("a:sheets/a:sheet", MAIN_NS):
        name = sheet.attrib["name"]
        if sheet_name is not None and name != sheet_name:
            continue
        relationship_id = sheet.attrib[
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        ]
        target = relationship_map[relationship_id]
        path = "xl/" + target.lstrip("/") if not target.startswith("xl/") else target
        return name, path
    raise ValueError("Лист Excel не найден")


def cell_value(cell: ET.Element, strings: list[str]) -> str | None:
    value = cell.find("a:v", MAIN_NS)
    if value is None:
        inline = cell.find("a:is/a:t", MAIN_NS)
        return inline.text if inline is not None else None
    if cell.attrib.get("t") == "s":
        return strings[int(value.text or 0)]
    return value.text


def column_index(cell_reference: str) -> int:
    letters = "".join(char for char in cell_reference if char.isalpha())
    index = 0
    for char in letters:
        index = index * 26 + ord(char.upper()) - ord("A") + 1
    return index - 1


def excel_date(value: str | None) -> date | None:
    try:
        serial = int(float(value or ""))
    except ValueError:
        return None
    if 30000 <= serial <= 60000:
        return (datetime(1899, 12, 30) + timedelta(days=serial)).date()
    return None


def clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def number(value: str | None) -> float:
    if value in (None, ""):
        return 0
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
