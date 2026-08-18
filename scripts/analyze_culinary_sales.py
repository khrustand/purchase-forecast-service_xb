from __future__ import annotations

import argparse
import json
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zipfile import ZipFile


MAIN_NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
}
REL_NS = {
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}

ORDER_GROUPS = ("mon_tue", "wed_thu", "fri_sun")
ORDER_GROUP_LABELS = {
    "mon_tue": "ПН+ВТ",
    "wed_thu": "СР+ЧТ",
    "fri_sun": "ПТ+СБ+ВС",
}
ORDER_GROUP_DAYS = {
    "mon_tue": 2,
    "wed_thu": 2,
    "fri_sun": 3,
}
EXCLUDED_CATEGORIES = {"Завтраки", "Топпинги/Кулинария ТТ"}


@dataclass(frozen=True)
class SalesItem:
    category: str
    name: str
    total: float
    averages: dict[str, float]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Проанализировать XLSX с продажами кулинарии и собрать заказ."
    )
    parser.add_argument("--sales", type=Path, required=True)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2026, 6, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 7, 31))
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--safety-rate", type=float, default=0.10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    rows = read_xlsx(args.sales)
    items, complete_windows = analyze_sales(rows, args.start, args.end)
    selected = recommend_orders(items, args.limit, args.safety_rate)
    payload = build_payload(args.start, args.end, items, selected, complete_windows)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(render_markdown(payload), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def analyze_sales(
    rows: list[list[str | None]],
    start: date,
    end: date,
) -> tuple[list[SalesItem], dict[str, set[date]]]:
    header = rows[5]
    date_columns = []
    for index, value in enumerate(header):
        parsed_date = excel_date(value)
        if parsed_date and start <= parsed_date <= end:
            date_columns.append((index, parsed_date))

    complete_windows = complete_order_windows(date_columns)
    items: list[SalesItem] = []
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

        values_by_column = {
            index: number(row[index] if index < len(row) else None)
            for index, _ in date_columns
        }
        total = sum(values_by_column.values())
        if total <= 0:
            continue

        averages = {}
        for group in ORDER_GROUPS:
            group_period_totals = []
            for week_start in sorted(complete_windows[group]):
                period_total = sum(
                    values_by_column[index]
                    for index, day in date_columns
                    if week_start_for(day) == week_start and order_group_for(day) == group
                )
                group_period_totals.append(period_total)
            averages[group] = (
                sum(group_period_totals) / len(group_period_totals)
                if group_period_totals
                else 0
            )

        items.append(
            SalesItem(
                category=current_category,
                name=name,
                total=total,
                averages=averages,
            )
        )

    return items, complete_windows


def recommend_orders(
    items: list[SalesItem],
    limit: int,
    safety_rate: float,
) -> list[dict[str, object]]:
    selected = [
        item for item in sorted(items, key=lambda value: value.total, reverse=True)
        if item.total >= 20
    ][:limit]

    recommendations = []
    for item in selected:
        order = {}
        reasons = {}
        for group in ORDER_GROUPS:
            quantity, reason = recommended_quantity(item, group, safety_rate)
            order[group] = quantity
            reasons[group] = reason
        week_total = sum(order.values())
        if week_total <= 0:
            continue
        recommendations.append(
            {
                "category": item.category,
                "name": item.name,
                "sales_june_july": int(item.total),
                "order": order,
                "week_total": week_total,
                "reasons": reasons,
            }
        )

    return sorted(
        recommendations,
        key=lambda value: (str(value["category"]), str(value["name"])),
    )


def recommended_quantity(
    item: SalesItem,
    group: str,
    safety_rate: float,
) -> tuple[int, str]:
    average = item.averages[group]
    max_average = max(item.averages.values())
    if average <= 0:
        return 0, "нет продаж в окне"

    raw_quantity = math.ceil(average * (1 + safety_rate))
    if raw_quantity < 4:
        if average == max_average and item.total >= 35:
            return 4, "ротация слабой позиции"
        return 0, "низкий спрос в окне"
    if raw_quantity > 9:
        return 9, "потолок сильной позиции"
    return raw_quantity, "по среднему спросу + страховой запас"


def build_payload(
    start: date,
    end: date,
    all_items: list[SalesItem],
    recommendations: list[dict[str, object]],
    complete_windows: dict[str, set[date]],
) -> dict[str, object]:
    category_totals: dict[str, dict[str, int]] = {}
    for item in recommendations:
        category = str(item["category"])
        category_totals.setdefault(
            category,
            {"sku": 0, "sales": 0, "mon_tue": 0, "wed_thu": 0, "fri_sun": 0, "week": 0},
        )
        totals = category_totals[category]
        totals["sku"] += 1
        totals["sales"] += int(item["sales_june_july"])
        order = item["order"]
        assert isinstance(order, dict)
        for group in ORDER_GROUPS:
            totals[group] += int(order[group])
        totals["week"] += int(item["week_total"])

    return {
        "period": f"{start.isoformat()}..{end.isoformat()}",
        "all_items": len(all_items),
        "selected_items": len(recommendations),
        "complete_windows": {
            ORDER_GROUP_LABELS[group]: len(weeks)
            for group, weeks in complete_windows.items()
        },
        "category_totals": category_totals,
        "recommendations": recommendations,
    }


def render_markdown(payload: dict[str, object]) -> str:
    lines = [
        "# Расчет заказа кулинарии",
        "",
        f"Период анализа: {payload['period']}.",
        f"Позиций после фильтрации: {payload['selected_items']} из {payload['all_items']}.",
        "",
        "## Сводка по категориям",
        "",
        "| Категория | SKU | Продажи июнь-июль | ПН+ВТ | СР+ЧТ | ПТ+СБ+ВС | Итого неделя |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    category_totals = payload["category_totals"]
    assert isinstance(category_totals, dict)
    for category, raw_totals in sorted(category_totals.items()):
        totals = dict(raw_totals)
        lines.append(
            f"| {category} | {totals['sku']} | {totals['sales']} | "
            f"{totals['mon_tue']} | {totals['wed_thu']} | {totals['fri_sun']} | {totals['week']} |"
        )

    lines.extend(
        [
            "",
            "## Список заказа",
            "",
            "| Категория | Позиция | Продажи июнь-июль | ПН+ВТ | СР+ЧТ | ПТ+СБ+ВС | Итого неделя |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    recommendations = payload["recommendations"]
    assert isinstance(recommendations, list)
    for item in recommendations:
        order = item["order"]
        assert isinstance(order, dict)
        lines.append(
            f"| {item['category']} | {item['name']} | {item['sales_june_july']} | "
            f"{order['mon_tue']} | {order['wed_thu']} | {order['fri_sun']} | {item['week_total']} |"
        )

    lines.extend(
        [
            "",
            "## Механика",
            "",
            "- Исключены завтраки и топпинги.",
            "- Использованы только полные окна заказов: ПН+ВТ, СР+ЧТ, ПТ+СБ+ВС.",
            "- В заказ попадают позиции с продажами от 20 шт. за июнь-июль, максимум 40 активных SKU.",
            "- База заказа: средние продажи в соответствующем окне + 10% страхового запаса.",
            "- Если позиция активна, минимум заказа 4 шт.",
            "- Сильные позиции ограничены потолком 9 шт. на одно окно, чтобы снижать риск списаний.",
        ]
    )
    return "\n".join(lines) + "\n"


def read_xlsx(path: Path, sheet_name: str | None = None) -> list[list[str | None]]:
    with ZipFile(path) as archive:
        strings = shared_strings(archive)
        name, sheet_path = select_sheet(archive, sheet_name)
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


def order_group_for(day: date) -> str:
    weekday = day.weekday()
    if weekday in (0, 1):
        return "mon_tue"
    if weekday in (2, 3):
        return "wed_thu"
    return "fri_sun"


def week_start_for(day: date) -> date:
    return day - timedelta(days=day.weekday())


def complete_order_windows(date_columns: list[tuple[int, date]]) -> dict[str, set[date]]:
    windows: dict[str, dict[date, list[date]]] = {group: {} for group in ORDER_GROUPS}
    for _, day in date_columns:
        group = order_group_for(day)
        windows[group].setdefault(week_start_for(day), []).append(day)
    return {
        group: {
            week_start
            for week_start, days in group_windows.items()
            if len(days) == ORDER_GROUP_DAYS[group]
        }
        for group, group_windows in windows.items()
    }


if __name__ == "__main__":
    raise SystemExit(main())
