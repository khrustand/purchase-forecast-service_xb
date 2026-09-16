from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser
from collections.abc import Callable
from pathlib import Path

from src.infrastructure.app_config import has_database_config, load_env_file, load_runtime_env


def runtime_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path.cwd()


def open_browser_later(
    url: str,
    delay_seconds: float = 1.5,
    opener: Callable[[str], object] = webbrowser.open,
) -> threading.Thread:
    def target() -> None:
        time.sleep(delay_seconds)
        opener(url)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread


def run_app_server() -> None:
    from src.app.web_server import run_server

    run_server()


def main() -> int:
    load_runtime_env(runtime_base_dir())
    port = os.environ.setdefault("APP_PORT", "8000")
    path = "" if has_database_config() else "/setup"
    open_browser_later(f"http://localhost:{port}{path}")
    run_app_server()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
