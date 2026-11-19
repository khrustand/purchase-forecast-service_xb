"""Small OOXML order export; the installed application needs only Python stdlib."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from io import BytesIO
import re
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile


MIME_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL_NS = 'http://schemas.openxmlformats.org/package/2006/relationships'


@dataclass(frozen=True)
class OrderLine:
    sku: str
    name: str
    category: str
    quantities: tuple[int | None, ...]

    @property
    def total(self) -> int | None:
        return None if None in self.quantities else sum(q for q in self.quantities if q is not None)


@dataclass(frozen=True)
class OrderSheet:
    name: str
    title: str
    dates: tuple[date, ...]
    lines: tuple[OrderLine, ...]
    totals_label: str
    by_day: bool = False

    @property
    def columns(self) -> int:
        return 4 + (len(self.dates) if self.by_day else 0)


def _xml(root: ET.Element) -> bytes:
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def _column(number: int) -> str:
    result = ''
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _text(value: str) -> str:
    # Invalid XML controls can occur in imported item names. All text is literal,
    # including names that begin with =, +, - or @ (never spreadsheet formulas).
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]', '', str(value))[:32767]


def _cell(row: ET.Element, ref: str, value: str | int, style: int = 0,
          formula: str | None = None) -> None:
    attributes = {'r': ref, 's': str(style)}
    if formula is not None:
        if isinstance(value, str):
            attributes['t'] = 'str'
        cell = ET.SubElement(row, 'c', attributes)
        ET.SubElement(cell, 'f').text = formula
        ET.SubElement(cell, 'v').text = str(value)
    elif isinstance(value, int):
        cell = ET.SubElement(row, 'c', attributes)
        ET.SubElement(cell, 'v').text = str(value)
    else:
        attributes['t'] = 'inlineStr'
        cell = ET.SubElement(row, 'c', attributes)
        ET.SubElement(ET.SubElement(cell, 'is'), 't', {'xml:space': 'preserve'}).text = _text(value)


def _sum_formula(row: ET.Element, ref: str, area: str, values: list[int | None], style: int) -> None:
    if not values:
        _cell(row, ref, 0, style)
        return
    complete = all(value is not None for value in values)
    formula = f'IF(COUNT({area})={len(values)},SUM({area}),"нет данных")'
    _cell(row, ref, sum(value for value in values if value is not None) if complete else 'нет данных',
          style, formula)


def _sheet_xml(sheet: OrderSheet) -> bytes:
    day_count = len(sheet.dates)
    if not 1 <= day_count <= 7:
        raise ValueError('Для выгрузки нужны даты заказа.')
    for line in sheet.lines:
        if len(line.quantities) != day_count:
            raise ValueError('Дни позиций не совпадают с периодом выгрузки.')
        if any(value is not None and (not isinstance(value, int) or value < 0) for value in line.quantities):
            raise ValueError('Количество порций должно быть целым неотрицательным числом.')

    last_col = _column(sheet.columns)
    footer = 3 + len(sheet.lines)
    root = ET.Element('worksheet', {'xmlns': NS})
    ET.SubElement(root, 'sheetPr').append(ET.Element('pageSetUpPr', {'fitToPage': '1'}))
    ET.SubElement(root, 'dimension', {'ref': f'A1:{last_col}{footer}'})
    view = ET.SubElement(ET.SubElement(root, 'sheetViews'), 'sheetView', {'workbookViewId': '0', 'showGridLines': '0'})
    ET.SubElement(view, 'pane', {'ySplit': '2', 'topLeftCell': 'A3', 'activePane': 'bottomLeft', 'state': 'frozen'})
    ET.SubElement(view, 'selection', {'pane': 'bottomLeft', 'activeCell': 'A3', 'sqref': 'A3'})
    ET.SubElement(root, 'sheetFormatPr', {'defaultRowHeight': '16'})
    cols = ET.SubElement(root, 'cols')
    widths = [12, 46, 18] + [15] * day_count + [12] if sheet.by_day else [12, 58, 18, 12]
    for number, width in enumerate(widths, 1):
        ET.SubElement(cols, 'col', {'min': str(number), 'max': str(number), 'width': str(width), 'customWidth': '1'})
    data = ET.SubElement(root, 'sheetData')
    row = ET.SubElement(data, 'row', {'r': '1', 'ht': '26', 'customHeight': '1'})
    for number in range(1, sheet.columns + 1):
        _cell(row, f'{_column(number)}1', sheet.title if number == 1 else '', 1)
    row = ET.SubElement(data, 'row', {'r': '2', 'ht': '28', 'customHeight': '1'})
    headers = ['Артикул', 'Название', 'Категория']
    headers.extend([*sheet.dates, 'Итого, порц.'] if sheet.by_day else ['Порций\nк заказу'])
    for number, value in enumerate(headers, 1):
        ref = f'{_column(number)}2'
        if isinstance(value, date):
            _cell(row, ref, (value - date(1899, 12, 30)).days, 3)
        else:
            _cell(row, ref, value, 2)
    for index, line in enumerate(sheet.lines, 3):
        height = 30 if sheet.by_day or len(line.name) > 56 or len(line.category) > 20 else 16
        row = ET.SubElement(data, 'row', {'r': str(index), 'ht': str(height), 'customHeight': '1'})
        for number, value in enumerate((line.sku, line.name, line.category), 1):
            _cell(row, f'{_column(number)}{index}', value, 5 if number == 1 else 4)
        if sheet.by_day:
            for number, value in enumerate(line.quantities, 4):
                _cell(row, f'{_column(number)}{index}', value if value is not None else 'нет данных',
                      6 if value is not None else 9)
            _sum_formula(row, f'{last_col}{index}', f'D{index}:{_column(sheet.columns - 1)}{index}',
                         list(line.quantities), 6)
        else:
            value = line.total
            _cell(row, f'D{index}', value if value is not None else 'нет данных', 6 if value is not None else 9)
    row = ET.SubElement(data, 'row', {'r': str(footer), 'ht': '30' if sheet.by_day else '20', 'customHeight': '1'})
    for col, value in zip('ABC', (sheet.totals_label, '', '')):
        _cell(row, f'{col}{footer}', value, 7)
    if sheet.by_day:
        for offset in range(day_count):
            col = _column(offset + 4)
            _sum_formula(row, f'{col}{footer}', f'{col}3:{col}{footer - 1}',
                         [line.quantities[offset] for line in sheet.lines], 8)
    _sum_formula(row, f'{last_col}{footer}', f'{last_col}3:{last_col}{footer - 1}',
                 [line.total for line in sheet.lines], 8)
    merged = ET.SubElement(root, 'mergeCells', {'count': '2'})
    for ref in (f'A1:{last_col}1', f'A{footer}:C{footer}'):
        ET.SubElement(merged, 'mergeCell', {'ref': ref})
    ET.SubElement(root, 'printOptions', {'horizontalCentered': '1'})
    ET.SubElement(root, 'pageMargins', {'left': '0.35', 'right': '0.35', 'top': '0.4', 'bottom': '0.4', 'header': '0.15', 'footer': '0.15'})
    ET.SubElement(root, 'pageSetup', {'paperSize': '9', 'orientation': 'landscape' if sheet.by_day else 'portrait',
                                     'fitToWidth': '1', 'fitToHeight': '1'})
    return _xml(root)


def _styles() -> bytes:
    root = ET.Element('styleSheet', {'xmlns': NS})
    formats = ET.SubElement(root, 'numFmts', {'count': '1'})
    ET.SubElement(formats, 'numFmt', {'numFmtId': '164', 'formatCode': r'dd\.mm\.yyyy'})
    fonts = ET.SubElement(root, 'fonts', {'count': '4'})
    for size, color, bold in [(10, 'FF20231F', False), (11, 'FF20231F', True),
                               (10, 'FFFFFFFF', True), (10, 'FF20231F', True)]:
        font = ET.SubElement(fonts, 'font')
        ET.SubElement(font, 'sz', {'val': str(size)})
        ET.SubElement(font, 'name', {'val': 'Arial'})
        ET.SubElement(font, 'color', {'rgb': color})
        if bold:
            ET.SubElement(font, 'b')
    fills = ET.SubElement(root, 'fills', {'count': '5'})
    for pattern, color in [('none', None), ('gray125', None), ('solid', 'FF365F4C'),
                            ('solid', 'FFEEF1EC'), ('solid', 'FFFCE4DF')]:
        fill = ET.SubElement(ET.SubElement(fills, 'fill'), 'patternFill', {'patternType': pattern})
        if color:
            ET.SubElement(fill, 'fgColor', {'rgb': color})
    border = ET.SubElement(ET.SubElement(root, 'borders', {'count': '1'}), 'border')
    for edge in ('left', 'right', 'top', 'bottom', 'diagonal'):
        ET.SubElement(border, edge)
    ET.SubElement(ET.SubElement(root, 'cellStyleXfs', {'count': '1'}), 'xf', {'numFmtId': '0', 'fontId': '0', 'fillId': '0', 'borderId': '0'})
    xfs = ET.SubElement(root, 'cellXfs', {'count': '10'})
    # Default, title, header, date header, text, SKU, quantity, totals label and number, missing.
    for font, fill, fmt, align, wrap in [
        (0, 0, 0, 'left', False), (1, 0, 0, 'left', True), (2, 2, 0, 'center', True), (2, 2, 164, 'center', True),
        (0, 0, 0, 'left', True), (0, 0, 49, 'left', False), (0, 0, 1, 'right', False),
        (3, 3, 0, 'left', False), (3, 3, 1, 'right', True), (0, 4, 0, 'right', True),
    ]:
        xf = ET.SubElement(xfs, 'xf', {'fontId': str(font), 'fillId': str(fill), 'borderId': '0',
                                      'numFmtId': str(fmt), 'xfId': '0', 'applyFont': '1', 'applyFill': '1',
                                      'applyAlignment': '1', 'applyNumberFormat': '1'})
        ET.SubElement(xf, 'alignment', {'horizontal': align, 'vertical': 'center', 'wrapText': '1' if wrap else '0'})
    ET.SubElement(ET.SubElement(root, 'cellStyles', {'count': '1'}), 'cellStyle', {'name': 'Normal', 'xfId': '0', 'builtinId': '0'})
    return _xml(root)


def build_order_workbook(sheets: tuple[OrderSheet, ...]) -> bytes:
    """Return a real .xlsx with typed quantities, cached totals and Excel formulas."""
    content_types = ET.Element('Types', {'xmlns': 'http://schemas.openxmlformats.org/package/2006/content-types'})
    for extension, mime in [('rels', 'application/vnd.openxmlformats-package.relationships+xml'), ('xml', 'application/xml')]:
        ET.SubElement(content_types, 'Default', {'Extension': extension, 'ContentType': mime})
    workbook = ET.Element('workbook', {'xmlns': NS, 'xmlns:r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'})
    entries = ET.SubElement(workbook, 'sheets')
    relations = ET.Element('Relationships', {'xmlns': REL_NS})
    defined = ET.SubElement(workbook, 'definedNames')
    for index, sheet in enumerate(sheets, 1):
        ET.SubElement(entries, 'sheet', {'name': sheet.name, 'sheetId': str(index), 'r:id': f'rId{index}'})
        ET.SubElement(relations, 'Relationship', {'Id': f'rId{index}', 'Type': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet', 'Target': f'worksheets/sheet{index}.xml'})
        ET.SubElement(content_types, 'Override', {'PartName': f'/xl/worksheets/sheet{index}.xml', 'ContentType': 'application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'})
        ET.SubElement(defined, 'definedName', {'name': '_xlnm.Print_Area', 'localSheetId': str(index - 1)}).text = (
            f"'{sheet.name}'!$A$1:${_column(sheet.columns)}${len(sheet.lines) + 3}"
        )
    ET.SubElement(workbook, 'calcPr', {'calcId': '191029', 'fullCalcOnLoad': '1'})
    for name, mime in [('workbook', 'sheet.main'), ('styles', 'styles')]:
        ET.SubElement(content_types, 'Override', {'PartName': f'/xl/{name}.xml', 'ContentType': f'application/vnd.openxmlformats-officedocument.spreadsheetml.{mime}+xml'})
    ET.SubElement(relations, 'Relationship', {'Id': 'styles', 'Type': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles', 'Target': 'styles.xml'})
    package = ET.Element('Relationships', {'xmlns': REL_NS})
    ET.SubElement(package, 'Relationship', {'Id': 'workbook', 'Type': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument', 'Target': 'xl/workbook.xml'})
    output = BytesIO()
    with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', _xml(content_types))
        archive.writestr('_rels/.rels', _xml(package))
        archive.writestr('xl/workbook.xml', _xml(workbook))
        archive.writestr('xl/_rels/workbook.xml.rels', _xml(relations))
        archive.writestr('xl/styles.xml', _styles())
        for index, sheet in enumerate(sheets, 1):
            archive.writestr(f'xl/worksheets/sheet{index}.xml', _sheet_xml(sheet))
    return output.getvalue()
