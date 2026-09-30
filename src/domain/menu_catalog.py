from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from pathlib import Path
from zipfile import ZipFile

from scripts.analyze_culinary_strategy import (
    MAIN_NS,
    REL_NS,
    cell_value,
    clean,
    column_index,
    normalize_name,
    number,
    shared_strings,
)


@dataclass(frozen=True)
class MenuCatalogItem:
    sku: str
    name: str
    normalized_name: str
    group: str
    times_ordered: int
    average_order_quantity: float
    last_order_quantity: int
    enabled: bool = True


@dataclass(frozen=True)
class MenuCatalogState:
    disabled: set[str]


def extract_order_menu_items(rows: list[list[str | None]]) -> list[MenuCatalogItem]:
    header_index = _find_header_index(rows)
    if header_index is None:
        return []
    header = [clean(value).lower() for value in rows[header_index]]
    sku_index = _index_of(header, "артикул")
    name_index = _index_of(header, "товар")
    package_index = _index_of(header, "к-во фасовок")
    total_index = _index_of(header, "общее к-во")
    if sku_index is None or name_index is None:
        return []

    result = []
    for row in rows[header_index + 1 :]:
        sku = clean(row[sku_index] if sku_index < len(row) else None)
        raw_name = clean(row[name_index] if name_index < len(row) else None)
        quantity = _row_quantity(row, package_index, total_index)
        if not sku or not raw_name or quantity <= 0:
            continue
        name = clean_menu_name(raw_name, sku)
        if not name or "снято" in name.lower():
            continue
        result.append(
            MenuCatalogItem(
                sku=sku,
                name=name,
                normalized_name=normalize_name(name),
                group=classify_menu_group(name),
                times_ordered=1,
                average_order_quantity=float(quantity),
                last_order_quantity=int(quantity),
            )
        )
    return result


def build_menu_catalog(order_dir: Path) -> list[MenuCatalogItem]:
    aggregate: dict[str, dict[str, object]] = {}
    if not order_dir.exists():
        return []
    for path in sorted(order_dir.glob("*.xlsx")):
        try:
            rows = read_culinary_order_sheet(path)
        except Exception:
            continue
        for item in extract_order_menu_items(rows):
            bucket = aggregate.setdefault(
                item.normalized_name,
                {
                    "sku": item.sku,
                    "name": item.name,
                    "group": item.group,
                    "quantities": [],
                },
            )
            bucket["sku"] = item.sku
            bucket["name"] = item.name
            bucket["group"] = item.group
            quantities = bucket["quantities"]
            assert isinstance(quantities, list)
            quantities.append(item.last_order_quantity)

    catalog = []
    for normalized_name, values in aggregate.items():
        quantities = values["quantities"]
        assert isinstance(quantities, list)
        average = sum(float(value) for value in quantities) / len(quantities)
        catalog.append(
            MenuCatalogItem(
                sku=str(values["sku"]),
                name=str(values["name"]),
                normalized_name=normalized_name,
                group=str(values["group"]),
                times_ordered=len(quantities),
                average_order_quantity=round(average, 1),
                last_order_quantity=int(quantities[-1]),
            )
        )
    return sorted(catalog, key=lambda item: (item.group, item.name))


def apply_menu_state(items: list[MenuCatalogItem], state: MenuCatalogState) -> list[MenuCatalogItem]:
    return [replace(item, enabled=item.normalized_name not in state.disabled) for item in items]


def enabled_menu_names(items: list[MenuCatalogItem]) -> set[str]:
    return {item.normalized_name for item in items if item.enabled}


def load_menu_state(path: Path) -> MenuCatalogState:
    if not path.exists():
        return MenuCatalogState(disabled=set())
    payload = json.loads(path.read_text(encoding="utf-8"))
    disabled = payload.get("disabled", [])
    return MenuCatalogState(disabled={str(value) for value in disabled})


def save_menu_state(path: Path, state: MenuCatalogState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"disabled": sorted(state.disabled)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def toggle_menu_item(path: Path, normalized_name: str, enabled: bool) -> MenuCatalogState:
    state = load_menu_state(path)
    disabled = set(state.disabled)
    if enabled:
        disabled.discard(normalized_name)
    else:
        disabled.add(normalized_name)
    updated = MenuCatalogState(disabled=disabled)
    save_menu_state(path, updated)
    return updated


def clean_menu_name(value: str, sku: str = "") -> str:
    name = value.replace("*", "")
    if sku:
        name = re.sub(rf"^\s*{re.escape(sku)}\s+", "", name)
    name = re.sub(r"^\s*\d{5,}\s+", "", name)
    name = re.sub(r"\s+", " ", name)
    return name.strip()


def classify_menu_group(name: str) -> str:
    normalized = normalize_name(name)
    if "суп" in normalized or "борщ" in normalized or "фо-бо" in normalized:
        return "Супы"
    if "салат" in normalized or "винегрет" in normalized or "оливье" in normalized or "сельдь" in normalized:
        return "Салаты"
    if "ролл" in normalized or "онигири" in normalized or "темаки" in normalized:
        return "Роллы"
    if "блины" in normalized or "омлет" in normalized:
        return "Завтраки"
    return "Горячее"


def read_culinary_order_sheet(path: Path) -> list[list[str | None]]:
    with ZipFile(path) as archive:
        strings = shared_strings(archive)
        sheet_path = _select_sheet_by_prefix(archive, "Кулинария")
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


def _select_sheet_by_prefix(archive: ZipFile, prefix: str) -> str:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    relationship_map = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in relationships.findall("rel:Relationship", REL_NS)
    }
    for sheet in workbook.findall("a:sheets/a:sheet", MAIN_NS):
        if not sheet.attrib["name"].startswith(prefix):
            continue
        relationship_id = sheet.attrib[
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        ]
        target = relationship_map[relationship_id]
        return "xl/" + target.lstrip("/") if not target.startswith("xl/") else target
    raise ValueError(f"Лист Excel с префиксом {prefix!r} не найден")


def _find_header_index(rows: list[list[str | None]]) -> int | None:
    for index, row in enumerate(rows):
        normalized = {clean(value).lower() for value in row}
        if "артикул" in normalized and "товар" in normalized:
            return index
    return None


def _index_of(values: list[str], needle: str) -> int | None:
    for index, value in enumerate(values):
        if value == needle:
            return index
    return None


def _row_quantity(row: list[str | None], package_index: int | None, total_index: int | None) -> int:
    candidates = []
    if total_index is not None and total_index < len(row):
        candidates.append(number(row[total_index]))
    if package_index is not None and package_index < len(row):
        candidates.append(number(row[package_index]))
    return int(max(candidates or [0]))
