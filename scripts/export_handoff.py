"""Создать приватный снимок данных вне Git; облачное хранилище только читается."""

import argparse
import json
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from src.infrastructure.app_config import appdata_env_path, load_env_file
from src.infrastructure.handoff import export_snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--env-file', type=Path)
    args = parser.parse_args()
    project = Path(__file__).resolve().parent.parent
    output = args.output.resolve()
    if output.is_relative_to(project):
        parser.error('Приватный снимок нужно сохранять вне репозитория.')
    env_path = args.env_file or (appdata_env_path() if appdata_env_path().exists() else project / '.env')
    load_env_file(env_path, override=True)
    profile = Path(os.getenv('LOCALAPPDATA', str(Path.home()))) / 'PurchaseForecastService'
    weather = Path(os.getenv('WEATHER_CACHE_PATH', str(profile / 'data/uploads/met_norway_forecast.json')))
    if not weather.is_absolute():
        weather = (profile if env_path == appdata_env_path() else project) / weather
    forbidden = tuple(os.environ[key].encode() for key in (
        'APP_PASSWORD', 'SUPABASE_SERVICE_ROLE_KEY', 'SUPABASE_ANON_KEY', 'DATABASE_URL') if os.environ.get(key))
    git = 'git'
    if Path('C:/Program Files/Git/cmd/git.exe').exists():
        git = 'C:/Program Files/Git/cmd/git.exe'
    revision = subprocess.check_output([git, 'rev-parse', 'HEAD'], cwd=project, text=True).strip()
    with TemporaryDirectory(prefix='purchase-forecast-export-') as temp:
        if os.getenv('STORAGE_BACKEND', '').lower() == 'supabase':
            os.environ['REPORT_UPLOAD_DIR'] = temp
        from src.infrastructure.report_storage import create_report_storage
        metadata = export_snapshot(create_report_storage(), output, project, profile,
                                   profile / 'data/menu/menu-state.json', revision, weather, forbidden)
    print(json.dumps({'reports': metadata['reports'], 'files': len(metadata['files']), 'output': str(output)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
