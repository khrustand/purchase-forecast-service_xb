"""Экспорт согласованного набора отчетов в отдельный приватный ZIP, без ключей."""

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from zipfile import ZipFile, ZIP_DEFLATED


def export_snapshot(storage, output: Path, project_root: Path, profile: Path, menu_state: Path,
                    revision: str, weather: Path | None = None,
                    forbidden_values: tuple[bytes, ...] = ()) -> dict:
    records = storage.list()
    metadata = {'format': 1, 'created_at': datetime.now(timezone.utc).isoformat(),
                'code_revision': revision, 'reports': len(records), 'files': {}}
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, 'x', compression=ZIP_DEFLATED) as archive:
        def add(name: str, content: bytes, source: Path | None = None):
            safe = PurePosixPath(name)
            if safe.is_absolute() or '..' in safe.parts or '\\' in name or name in metadata['files']:
                raise ValueError('Небезопасное или повторяющееся имя файла снимка.')
            if any(secret in content for secret in forbidden_values if len(secret) >= 8):
                raise ValueError('Обнаружено секретное значение, файл не включен в снимок: ' + name)
            if source:
                archive.write(source, name)
            else:
                archive.writestr(name, content)
            metadata['files'][name] = {'sha256': hashlib.sha256(content).hexdigest(), 'size': len(content)}

        manifest = []
        for report in records:
            if Path(report.stored_name).name != report.stored_name or '\\' in report.stored_name:
                raise ValueError('Некорректное имя отчета в реестре.')
            resolved = storage.resolve_record(report) if hasattr(storage, 'resolve_record') else storage.resolve(report.id)
            if not resolved:
                raise ValueError('Недоступен отчет: ' + report.original_name)
            content = resolved[1].read_bytes()
            if len(content) != report.size:
                raise ValueError('Размер отчета не совпадает с реестром: ' + report.original_name)
            add('reports/' + report.stored_name, content, resolved[1])
            manifest.append({**asdict(report), 'storage_path': ''})
        add('reports/manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2).encode())
        for subpath in ['menu-uploads', 'assortment-candidates.json']:
            source = profile / subpath
            files = sorted(source.rglob('*')) if source.is_dir() else [source]
            for file in files:
                if file.is_file() and file.suffix.lower() in ('.json', '.xlsx'):
                    add('localappdata/PurchaseForecastService/' + file.relative_to(profile).as_posix(), file.read_bytes(), file)
        state = menu_state.read_bytes() if menu_state.exists() else b'{"disabled": [], "own_production": []}'
        add('menu-state.json', state)
        examples = project_root / 'data/examples'
        for file in sorted(examples.glob('*')):
            if file.is_file():
                add('data/examples/' + file.name, file.read_bytes(), file)
        if weather and weather.is_file():
            add('weather.json', weather.read_bytes(), weather)
        # Эти файлы сохраняются для контекста; активный реестр остается только reports/.
        for directory in ['data/local', 'data/menu', 'Прошлые заказы', 'reports', '.codex/project', '.codex/starter']:
            source = project_root / directory
            if not source.exists():
                continue
            for file in sorted(source.rglob('*')):
                if file.is_file() and file.suffix.lower() in ('.md', '.json', '.csv', '.xlsx', '.html'):
                    add('reference/' + file.relative_to(project_root).as_posix(), file.read_bytes(), file)
        add('README.txt', ('Приватный снимок проекта. Не публиковать в GitHub.\n'
            'Секреты и .env не включены.\n'
            'Распакуйте вне репозитория. Из папки кода запустите:\n'
            'python -m scripts.run_handoff --root "ПУТЬ_К_СНИМКУ" --verify-only\n'
            'python -m scripts.run_handoff --root "ПУТЬ_К_СНИМКУ"\n'
            'Инструкция: docs/developer-handoff.md.\n').encode('utf-8'))
        if {r.id for r in storage.list()} != {r.id for r in records}:
            raise ValueError('Реестр изменился во время экспорта; создайте новый снимок.')
        archive.writestr('snapshot.json', json.dumps(metadata, ensure_ascii=False, indent=2).encode())
    return metadata


def verify_snapshot(root: Path) -> dict:
    root = root.resolve()
    metadata = json.loads((root / 'snapshot.json').read_text(encoding='utf-8'))
    if metadata.get('format') != 1:
        raise ValueError('Неподдерживаемый формат снимка.')
    for name, expected in metadata['files'].items():
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError('Путь снимка выходит за его директорию.')
        if not path.is_file() or path.stat().st_size != expected['size'] or hashlib.sha256(path.read_bytes()).hexdigest() != expected['sha256']:
            raise ValueError('Файл снимка отсутствует или изменен: ' + name)
    return metadata
