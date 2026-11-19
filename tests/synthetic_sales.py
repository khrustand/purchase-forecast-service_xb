"""Синтетические XLSX для тестов: не требуют пользовательских выгрузок."""

from contextlib import contextmanager, ExitStack
from datetime import date, timedelta
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from xml.sax.saxutils import escape
from zipfile import ZipFile, ZIP_DEFLATED


def sales_workbook_bytes():
    days = [date(2026, 6, 1) + timedelta(days=i) for i in range(64)]
    rows = [[] for _ in range(5)] + [['Категория', 'Блюдо'] + [(d - date(1899, 12, 30)).days for d in days]]
    rows += [[category, name] + [quantity] * len(days) for category, name, quantity in [
        ('Супы', 'Суп лапша куриный 0,300', 20), ('Горячее', 'Тестовый обед', 40), ('Салаты', 'Тестовый салат', 10)]]
    def column(index):
        result = ''
        while index:
            index, rem = divmod(index - 1, 26)
            result = chr(65 + rem) + result
        return result
    sheet = '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
    for row_index, row in enumerate(rows, 1):
        sheet += f'<row r="{row_index}">'
        for col, value in enumerate(row, 1):
            ref = column(col) + str(row_index)
            sheet += (f'<c r="{ref}"><v>{value}</v></c>' if isinstance(value, int) else
                      f'<c r="{ref}" t="inlineStr"><is><t>{escape(value)}</t></is></c>')
        sheet += '</row>'
    sheet += '</sheetData></worksheet>'
    stream = BytesIO()
    with ZipFile(stream, 'w', ZIP_DEFLATED) as book:
        book.writestr('xl/workbook.xml', '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Продажи" sheetId="1" r:id="rId1"/></sheets></workbook>')
        book.writestr('xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/></Relationships>')
        book.writestr('xl/worksheets/sheet1.xml', sheet)
        # Несколько блоков данных проверяют также постраничную загрузку chunks.
        book.writestr('test-padding.txt', ''.join(sha256(str(i).encode()).hexdigest() for i in range(1000)))
    return stream.getvalue()


@contextmanager
def dashboard_fixture(web):
    with TemporaryDirectory() as directory, ExitStack() as stack:
        source = Path(directory) / 'sales.xlsx'
        source.write_bytes(sales_workbook_bytes())
        storage = SimpleNamespace(paths=lambda kind: [source] if kind == 'sales' else [], list=lambda: [],
                                  storage_label=lambda: 'Supabase')
        for name, value in [('REPORT_STORAGE', storage), ('DEFAULT_PREVIOUS_ORDERS_DIR', Path(directory) / 'no-menu'),
                            ('DEFAULT_MENU_STATE_PATH', Path(directory) / 'menu-state.json'),
                            ('DEFAULT_MENU_PRICES_PATH', Path(directory) / 'menu-prices.json')]:
            stack.enter_context(patch.object(web, name, value))
        stack.enter_context(patch.object(web, 'load_met_norway_forecast', return_value=None))
        stack.enter_context(patch.object(web, 'load_candidates', return_value=[]))
        yield
