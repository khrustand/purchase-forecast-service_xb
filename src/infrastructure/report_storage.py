from __future__ import annotations

import json
import os
import re
import threading
import uuid
import base64
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from scripts.analyze_culinary_strategy import excel_date, read_xlsx


ALLOWED_REPORT_TYPES = {"sales": "Продажи", "waste": "Списания"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
CHUNK_BYTES = 4 * 1024
CHUNK_PAGE_SIZE = 1
_MANIFEST_LOCK = threading.Lock()
HttpRequest = Callable[[str, str, dict[str, str], bytes | None], tuple[int, bytes]]


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
    storage_path: str = ""


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
        validate_report_content(report_type, original_name, content)

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

    def storage_label(self) -> str:
        return "Локальное хранилище"

    def _read_manifest(self) -> list[dict[str, object]]:
        if not self.manifest_path.exists():
            return []
        try:
            payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as error:
            raise ReportValidationError("Реестр загруженных отчетов поврежден.") from error
        return payload if isinstance(payload, list) else []


class SupabaseReportStorage:
    def __init__(
        self,
        url: str,
        service_role_key: str,
        bucket: str = "uploads",
        cache_root: Path | None = None,
        request: HttpRequest | None = None,
    ) -> None:
        self.url = url.rstrip("/")
        self.service_role_key = service_role_key
        self.bucket = bucket
        self.cache_root = cache_root or Path(os.getenv("REPORT_UPLOAD_DIR", "data/uploads")) / "supabase-cache"
        self.request = request or _default_request

    def list(self) -> list[MonthlyReport]:
        payload = self._select_reports()
        reports = [MonthlyReport(**item) for item in payload]
        return sorted(reports, key=lambda item: (item.period_start, item.uploaded_at), reverse=True)

    def save(self, report_type: str, original_name: str, content: bytes) -> MonthlyReport:
        validate_report_content(report_type, original_name, content)
        with TemporaryDirectory() as directory:
            temporary_path = Path(directory) / safe_display_name(original_name)
            temporary_path.write_bytes(content)
            try:
                period_start, period_end = detect_period(temporary_path, report_type)
            except Exception as error:
                raise ReportValidationError(f"Не удалось прочитать период отчета: {error}") from error

        duplicate = next(
            (
                item
                for item in self.list()
                if item.report_type == report_type
                and item.period_start == period_start.isoformat()
                and item.period_end == period_end.isoformat()
            ),
            None,
        )
        if duplicate is not None:
            raise ReportValidationError("Отчет этого типа за указанный период уже загружен.")

        report_id = uuid.uuid4().hex
        stored_name = f"{report_type}-{report_id}.xlsx"
        storage_path = f"reports/{report_type}/{period_start.isoformat()}_{period_end.isoformat()}/{stored_name}"
        try:
            self._upload_object(storage_path, content)
        except Exception:
            storage_path = f"chunks:{report_id}"
            report = self._build_report(
                report_id,
                report_type,
                original_name,
                stored_name,
                period_start,
                period_end,
                content,
                storage_path,
            )
            self._insert_report(report)
            try:
                self._insert_chunks(report_id, content)
            except Exception as error:
                self._delete_report(report_id)
                if isinstance(error, ReportValidationError):
                    raise
                raise ReportValidationError("РќРµ СѓРґР°Р»РѕСЃСЊ СЃРѕС…СЂР°РЅРёС‚СЊ XLSX РєСѓСЃРєР°РјРё РІ Supabase.") from error
            return report
        report = self._build_report(
            report_id,
            report_type,
            original_name,
            stored_name,
            period_start,
            period_end,
            content,
            storage_path,
        )
        self._insert_report(report)
        return report

    def resolve(self, report_id: str) -> tuple[MonthlyReport, Path] | None:
        if not re.fullmatch(r"[a-f0-9]{32}", report_id):
            return None
        report = next((item for item in self.list() if item.id == report_id), None)
        if report is None:
            return None
        path = self.cache_root / report.stored_name
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.stat().st_size != report.size:
            if not report.storage_path:
                return None
            if report.storage_path.startswith("chunks:"):
                path.write_bytes(self._download_chunks(report.id))
            else:
                path.write_bytes(self._download_object(report.storage_path))
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

    def storage_label(self) -> str:
        return "Supabase"

    def _headers(self) -> dict[str, str]:
        return {
            "apikey": self.service_role_key,
            "Authorization": f"Bearer {self.service_role_key}",
        }

    def _select_reports(self) -> list[dict[str, object]]:
        status, body = self.request(
            "GET",
            f"{self.url}/rest/v1/uploaded_reports?select=*&order=period_start.desc,uploaded_at.desc",
            {**self._headers(), "Accept": "application/json"},
            None,
        )
        if status >= 400:
            raise ReportValidationError("Не удалось получить список отчетов из Supabase.")
        payload = json.loads(body.decode("utf-8") or "[]")
        return payload if isinstance(payload, list) else []

    def _insert_report(self, report: MonthlyReport) -> None:
        payload = json.dumps(asdict(report), ensure_ascii=False).encode("utf-8")
        status, _body = self.request(
            "POST",
            f"{self.url}/rest/v1/uploaded_reports",
            {
                **self._headers(),
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            payload,
        )
        if status >= 400:
            raise ReportValidationError("Файл загружен, но не удалось сохранить запись отчета в Supabase.")

    def _build_report(
        self,
        report_id: str,
        report_type: str,
        original_name: str,
        stored_name: str,
        period_start: date,
        period_end: date,
        content: bytes,
        storage_path: str,
    ) -> MonthlyReport:
        return MonthlyReport(
            id=report_id,
            report_type=report_type,
            original_name=safe_display_name(original_name),
            stored_name=stored_name,
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
            uploaded_at=datetime.now(timezone.utc).isoformat(),
            size=len(content),
            storage_path=storage_path,
        )

    def _delete_report(self, report_id: str) -> None:
        self.request(
            "DELETE",
            f"{self.url}/rest/v1/uploaded_reports?id=eq.{quote(report_id)}",
            {**self._headers(), "Prefer": "return=minimal"},
            None,
        )

    def _insert_chunks(self, report_id: str, content: bytes) -> None:
        for index, offset in enumerate(range(0, len(content), CHUNK_BYTES)):
            chunk = {
                "report_id": report_id,
                "chunk_index": index,
                "content_base64": base64.b64encode(content[offset : offset + CHUNK_BYTES]).decode("ascii"),
            }
            payload = json.dumps(chunk, ensure_ascii=False).encode("utf-8")
            status, _body = self.request(
                "POST",
                f"{self.url}/rest/v1/uploaded_report_chunks",
                {
                    **self._headers(),
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal",
                },
                payload,
            )
            if status >= 400:
                raise ReportValidationError("Не удалось сохранить XLSX кусками в Supabase.")

    def _download_chunks(self, report_id: str) -> bytes:
        status, body = self.request(
            "GET",
            f"{self.url}/rest/v1/uploaded_report_chunks?report_id=eq.{quote(report_id)}&select=chunk_index,content_base64&order=chunk_index.asc",
            {**self._headers(), "Accept": "application/json"},
            None,
        )
        if status >= 400:
            raise ReportValidationError("Не удалось скачать куски XLSX из Supabase.")
        payload = json.loads(body.decode("utf-8") or "[]")
        if not isinstance(payload, list) or not payload:
            raise ReportValidationError("Куски XLSX в Supabase не найдены.")
        return b"".join(base64.b64decode(str(item["content_base64"])) for item in payload)

    def _download_chunks(self, report_id: str) -> bytes:
        chunks: list[dict[str, object]] = []
        offset = 0
        while True:
            status, body = self.request(
                "GET",
                f"{self.url}/rest/v1/uploaded_report_chunks?report_id=eq.{quote(report_id)}&select=chunk_index,content_base64&order=chunk_index.asc&limit={CHUNK_PAGE_SIZE}&offset={offset}",
                {**self._headers(), "Accept": "application/json"},
                None,
            )
            if status >= 400:
                raise ReportValidationError("РќРµ СѓРґР°Р»РѕСЃСЊ СЃРєР°С‡Р°С‚СЊ РєСѓСЃРєРё XLSX РёР· Supabase.")
            payload = json.loads(body.decode("utf-8") or "[]")
            if not isinstance(payload, list):
                raise ReportValidationError("РљСѓСЃРєРё XLSX РІ Supabase РЅРµ РЅР°Р№РґРµРЅС‹.")
            chunks.extend(payload)
            if len(payload) < CHUNK_PAGE_SIZE:
                break
            offset += CHUNK_PAGE_SIZE
        if not chunks:
            raise ReportValidationError("РљСѓСЃРєРё XLSX РІ Supabase РЅРµ РЅР°Р№РґРµРЅС‹.")
        return b"".join(base64.b64decode(str(item["content_base64"])) for item in chunks)

    def _upload_object(self, storage_path: str, content: bytes) -> None:
        status, _body = self.request(
            "POST",
            f"{self.url}/storage/v1/object/{quote(self.bucket)}/{_quote_path(storage_path)}",
            {
                **self._headers(),
                "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "x-upsert": "false",
            },
            content,
        )
        if status >= 400:
            raise ReportValidationError("Не удалось загрузить XLSX в Supabase Storage.")

    def _download_object(self, storage_path: str) -> bytes:
        status, body = self.request(
            "GET",
            f"{self.url}/storage/v1/object/{quote(self.bucket)}/{_quote_path(storage_path)}",
            self._headers(),
            None,
        )
        if status >= 400:
            raise ReportValidationError("Не удалось скачать XLSX из Supabase Storage.")
        return body


def create_report_storage() -> MonthlyReportStorage | SupabaseReportStorage:
    backend = os.getenv("STORAGE_BACKEND", "local").strip().lower()
    if backend in {"", "local"}:
        return MonthlyReportStorage()
    if backend != "supabase":
        raise ReportValidationError("Неизвестный режим хранения отчетов.")
    url = os.getenv("SUPABASE_URL", "").strip()
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    bucket = os.getenv("SUPABASE_STORAGE_BUCKET", "uploads").strip() or "uploads"
    if not url or not service_role_key:
        raise ReportValidationError("Для Supabase-хранилища нужны SUPABASE_URL и SUPABASE_SERVICE_ROLE_KEY.")
    return SupabaseReportStorage(url=url, service_role_key=service_role_key, bucket=bucket)


def validate_report_content(report_type: str, original_name: str, content: bytes) -> None:
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


def _default_request(method: str, url: str, headers: dict[str, str], data: bytes | None = None) -> tuple[int, bytes]:
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, response.read()
    except HTTPError as error:
        return error.code, error.read()
    except URLError as error:
        raise ReportValidationError(f"Supabase недоступен: {error.reason}") from error


def _quote_path(value: str) -> str:
    return "/".join(quote(part, safe="") for part in value.split("/"))
