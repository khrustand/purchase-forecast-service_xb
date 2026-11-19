"""Постоянная папка загруженных меню вне временного каталога exe."""

import os
from pathlib import Path


def menu_upload_directory() -> Path:
    return Path(os.getenv('LOCALAPPDATA', str(Path.home()))) / 'PurchaseForecastService' / 'menu-uploads'
