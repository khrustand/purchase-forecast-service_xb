from __future__ import annotations

import json
import os
import re
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from scripts.analyze_culinary_strategy import excel_date, read_xlsx


ALLOWED_REPORT_TYPES = {"sales": "Продажи", "waste": "Списания"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
_MANIFEST_LOCK = threading.Lock()


@dataclass(frozen=True)
class MonthlyReport:
    id: str
    report_type: str
    original_name: str
    stored_name: str
    period_start: str
    period_end: str
    uploaded_at: str
    size: int


class ReportValidationError(ValueError):
    pass


class MonthlyReportStorage:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(os.getenv("REPORT_UPLOAD_DIR", "data/uploads"))
        self.manifest_path = self.root / "manifest.json"

    def list(self) -> list[MonthlyReport]:
        payload = self._read_manifest()
        reports = [MonthlyReport(**item) for item in payload]
        return sorted(reports, key=lambda item: (item.period_start, item.uploaded_at), reverse=True)

    def save(self, report_type: str, original_name: str, content: bytes) -> MonthlyReport:
        if report_type not in ALLOWED_REPORT_TYPES:
            raise ReportValidationError("Неизвестный тип отчета.")
        if not content:
            raise ReportValidationError("Файл пуст.")
        if len(content) > MAX_UPLOAD_BYTES:
            raise ReportValidationError("Файл превышает лимит 10 МБ.")
        if Path(original_name).suffix.lower() != ".xlsx":
            raise ReportValidationError("Поддерживаются только файлы XLSX.")
        if not content.startswith(b"PK"):
            raise ReportValidationError("Файл не является корректной книгой XLSX.")

        self.root.mkdir(parents=True, exist_ok=True)
        report_id = uuid.uuid4().hex
        stored_name = f"{report_type}-{report_id}.xlsx"
        path = self.root / stored_name
        path.write_bytes(content)
        try:
            period_start, period_end = detect_period(path, report_type)
        except Exception as error:
            path.unlink(missing_ok=True)
            raise ReportValidationError(f"Не удалось прочитать период отчета: {error}") from error

        report = MonthlyReport(
            id=report_id,
            report_type=report_type,
            original_name=safe_display_name(original_name),
            stored_name=stored_name,
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
            uploaded_at=datetime.now(timezone.utc).isoformat(),
            size=len(content),
        )
        with _MANIFEST_LOCK:
            reports = self._read_manifest()
            duplicate = next(
                (
                    item
                    for item in reports
                    if item.get("report_type") == report_type
                    and item.get("period_start") == report.period_start
                    and item.get("period_end") == report.period_end
                ),
                None,
            )
            if duplicate is not None:
                path.unlink(missing_ok=True)
                raise ReportValidationError("Отчет этого типа за указанный период уже загружен.")
            reports.append(asdict(report))
            temporary = self.manifest_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.manifest_path)
        return report

    def resolve(self, report_id: str) -> tuple[MonthlyReport, Path] | None:
        if not re.fullmatch(r"[a-f0-9]{32}", report_id):
            return None
        report = next((item for item in self.list() if item.id == report_id), None)
        if report is None:
            return None
        path = (self.root / report.stored_name).resolve()
        if path.parent != self.root.resolve() or not path.is_file():
            return None
        return report, path

    def paths(self, report_type: str) -> list[Path]:
        paths = []
        for item in self.list():
            if item.report_type != report_type:
                continue
            resolved = self.resolve(item.id)
            if resolved is not None:
                paths.append(resolved[1])
        return paths

    def _read_manifest(self) -> list[dict[str, object]]:
        if not self.manifest_path.exists():
            return []
        try:
            payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as error:
            raise ReportValidationError("Реестр загруженных отчетов поврежден.") from error
        return payload if isinstance(payload, list) else []


def detect_period(path: Path, report_type: str) -> tuple[date, date]:
    rows = read_xlsx(path)
    if report_type == "sales":
        if len(rows) < 7:
            raise ValueError("в отчете продаж нет строк данных")
        dates = [parsed for value in rows[5] for parsed in [excel_date(value)] if parsed]
    else:
        dates = [parsed for row in rows[4:] if row for parsed in [parse_report_date(row[0])] if parsed]
    if not dates:
        raise ValueError("даты не найдены")
    return min(dates), max(dates)


def parse_report_date(value: str | None) -> date | None:
    try:
        return datetime.strptime(str(value), "%d.%m.%Y %H:%M").date()
    except (TypeError, ValueError):
        return None


def safe_display_name(value: str) -> str:
    name = Path(value.replace("\\", "/")).name
    return re.sub(r"[\x00-\x1f]", "", name)[:200] or "report.xlsx"
