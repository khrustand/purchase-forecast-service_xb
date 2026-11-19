"""Чтение отчетов о чеках и строк актов списания iiko без изменения источников."""

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal


def decimal_value(value: str | None) -> Decimal:
    return Decimal(str(value or '0').replace('\xa0', '').replace(' ', '').replace(',', '.'))


def text_date(value: str | None) -> date | None:
    match = re.search(r'(?<!\d)(\d{2}\.\d{2}\.\d{4})(?!\d)', str(value or ''))
    return datetime.strptime(match[1], '%d.%m.%Y').date() if match else None


@dataclass(frozen=True)
class ReceiptDay:
    day: date
    checks: int
    revenue: Decimal


@dataclass(frozen=True)
class WasteLine:
    day: date
    document: str
    code: str
    name: str
    unit: str
    quantity: Decimal
    cost: Decimal
    account: str

    @property
    def staff(self) -> bool:
        return 'сотрудник' in self.account.casefold() or 'персонал' in self.account.casefold()


def is_receipts(rows: list[list[str | None]]) -> bool:
    return any('Период' in row and 'Чеков' in row for row in rows[:15])


def receipt_days(rows: list[list[str | None]]) -> list[ReceiptDay]:
    header = next((i for i, r in enumerate(rows[:15]) if 'Период' in r and 'Чеков' in r), None)
    if header is None:
        return []
    names = rows[header]
    result = []
    for row in rows[header + 1:]:
        if not row or not (day := text_date(row[0])):
            continue
        checks = decimal_value(row[names.index('Чеков')])
        if checks < 0 or checks != int(checks):
            raise ValueError('Некорректное количество чеков')
        result.append(ReceiptDay(day, int(checks), decimal_value(row[names.index('Продажи')])))
    return result


def is_detailed_waste(rows: list[list[str | None]]) -> bool:
    return any('Код товара' in r and 'Количество, в ед. изм.' in r for r in rows[:20])


def waste_document(rows: list[list[str | None]]) -> str:
    if not is_detailed_waste(rows):
        return ''
    text = ' '.join(str(v or '') for r in rows[:8] for v in r)
    match = re.search(r'(?:№\s*|Номер док-та:\s*)(\d+)', text)
    if not match:
        raise ValueError('Номер акта списания не найден')
    return match[1]


def waste_lines(rows: list[list[str | None]]) -> list[WasteLine]:
    if not is_detailed_waste(rows):
        return []
    document = waste_document(rows)
    day = next((text_date(str(r[0])) for r in rows[:8] if r and str(r[0]).startswith('Дата и время:')), None)
    if day is None:
        raise ValueError('Дата документа списания не найдена')
    account = next((str(r[0]).partition(':')[2].strip() for r in rows[:8] if r and str(r[0]).startswith('На счет:')), '')
    index = next(i for i,r in enumerate(rows[:20]) if 'Код товара' in r and 'Количество, в ед. изм.' in r)
    headers = rows[index]
    result = []
    for row in rows[index + 1:]:
        if len(row) <= headers.index('Себестоимость всего, р.') or not row[1] or not str(row[1]).isdigit():
            continue
        result.append(WasteLine(day, document, str(row[1]), str(row[headers.index('Товар')]),
                      str(row[headers.index('Тип тары')] or ''),
                      decimal_value(row[headers.index('Количество, в ед. изм.')]),
                      decimal_value(row[headers.index('Себестоимость всего, р.')]), account))
    return result
