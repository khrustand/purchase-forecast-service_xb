"""Запуск отдельной локальной копии снимка без .env и доступа к Supabase."""

import argparse
import json
import os
from pathlib import Path

from src.infrastructure.handoff import verify_snapshot


def configure_profile(root: Path):
    if not (root / 'reports/manifest.json').is_file():
        raise ValueError('В снимке не найден реестр reports/manifest.json.')
    os.environ.update(STORAGE_BACKEND='local', REPORT_UPLOAD_DIR=str(root / 'reports'),
                      LOCALAPPDATA=str(root / 'localappdata'), APP_USERNAME='', APP_PASSWORD='',
                      WEATHER_CACHE_PATH=str(root / 'weather.json'), WEATHER_PROVIDER='met-no',
                      TZ='Europe/Moscow')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    root = args.root.resolve()
    if args.verify_only:
        metadata = verify_snapshot(root)
        print(json.dumps({'reports': metadata['reports'], 'files_verified': len(metadata['files'])}))
        return
    configure_profile(root)
    os.chdir(root)
    from src.app import web_server as web
    web.DEFAULT_MENU_STATE_PATH = root / 'menu-state.json'
    web.DEFAULT_MENU_PRICES_PATH = root / 'menu-prices.json'
    server = web.DashboardServer(('127.0.0.1', args.port), web.DashboardHandler)
    print(f'Отдельная копия: http://127.0.0.1:{args.port}. Остановка: Ctrl+C.')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
