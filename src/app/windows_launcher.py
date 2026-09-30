from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import webbrowser
from collections.abc import Callable, Sequence
from http.server import ThreadingHTTPServer
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
) -> object | None:
    try:
        return popen(["msedge", f"--app={url}", "--new-window"])
    except OSError:
        fallback(url)
        return None


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


def create_app_server(port: int) -> ThreadingHTTPServer:
    from src.app.web_server import DashboardHandler

    return ThreadingHTTPServer(("0.0.0.0", port), DashboardHandler)


def run_app_server(server: ThreadingHTTPServer) -> None:
    server.serve_forever()


def wait_for_window_close(process: object | None, shutdown: Callable[[], object]) -> None:
    if process is not None and hasattr(process, "wait"):
        process.wait()
    shutdown()


def main() -> int:
    load_runtime_env(runtime_base_dir())
    port = os.environ.setdefault("APP_PORT", "8000")
    path = "" if has_database_config() else "/setup"
    server = create_app_server(int(port))
    server_thread = threading.Thread(target=run_app_server, args=(server,), daemon=True)
    server_thread.start()
    time.sleep(1.5)
    process = open_windows_app_window(f"http://localhost:{port}{path}")
    wait_for_window_close(process, shutdown=server.shutdown)
    server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
