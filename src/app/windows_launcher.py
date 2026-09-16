from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import webbrowser
from collections.abc import Callable, Sequence
from pathlib import Path

from src.infrastructure.app_config import has_database_config, load_env_file, load_runtime_env


def runtime_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path.cwd()


def open_windows_app_window(
    url: str,
    popen: Callable[[Sequence[str]], object] = subprocess.Popen,
    fallback: Callable[[str], object] = webbrowser.open,
) -> bool:
    try:
        popen(["msedge", f"--app={url}", "--new-window"])
        return True
    except OSError:
        fallback(url)
        return False


def open_app_window_later(
    url: str,
    delay_seconds: float = 1.5,
    opener: Callable[[str], object] = open_windows_app_window,
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
    open_app_window_later(f"http://localhost:{port}{path}")
    run_app_server()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
