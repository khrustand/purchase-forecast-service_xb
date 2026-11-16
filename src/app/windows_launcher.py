from __future__ import annotations

import os
import logging
import subprocess
import sys
import threading
import time
import webbrowser
from collections.abc import Callable, Sequence
from http.server import ThreadingHTTPServer
from pathlib import Path
from shutil import which

from src.infrastructure.app_config import has_database_config, load_env_file, load_runtime_env


def runtime_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path.cwd()


def open_windows_app_window(
    url: str,
    popen: Callable[[Sequence[str]], object] = subprocess.Popen,
    fallback: Callable[[str], object] = webbrowser.open,
    edge_executable: Callable[[], Path | None] = lambda: find_edge_executable(),
) -> object | None:
    profile_dir = Path(os.getenv("LOCALAPPDATA", str(runtime_base_dir()))) / "PurchaseForecastService" / "edge-profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    executable = edge_executable()
    if executable is None:
        fallback(url)
        return None
    try:
        return popen(
            [
                str(executable),
                f"--app={url}",
                "--new-window",
                "--no-first-run",
                f"--user-data-dir={profile_dir}",
            ]
        )
    except OSError:
        fallback(url)
        return None


def find_edge_executable(
    exists: Callable[[Path], bool] = Path.exists,
    command_lookup: Callable[[str], str | None] = which,
) -> Path | None:
    command_path = command_lookup("msedge")
    if command_path:
        return Path(command_path)
    candidates = [
        Path(os.getenv("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(os.getenv("ProgramFiles", r"C:\Program Files")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(os.getenv("LOCALAPPDATA", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
    ]
    for candidate in candidates:
        if exists(candidate):
            return candidate
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


def keep_server_alive(server_thread: threading.Thread) -> None:
    server_thread.join()


def wait_for_window_close(
    process: object | None,
    shutdown: Callable[[], object],
    monotonic: Callable[[], float] = time.monotonic,
    minimum_runtime_seconds: float = 1.0,
) -> bool:
    started_at = monotonic()
    if process is not None and hasattr(process, "wait"):
        process.wait()
        if monotonic() - started_at < minimum_runtime_seconds:
            return False
    shutdown()
    return True


def main() -> int:
    log_dir = Path(os.getenv('LOCALAPPDATA', str(runtime_base_dir()))) / 'PurchaseForecastService' / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=log_dir / 'app.log', encoding='utf-8', level=logging.ERROR)
    load_runtime_env(runtime_base_dir())
    port = os.environ.setdefault("APP_PORT", "8000")
    path = "" if has_database_config() else "/setup"
    server = create_app_server(int(port))
    server_thread = threading.Thread(target=run_app_server, args=(server,), daemon=True)
    server_thread.start()
    time.sleep(1.5)
    process = open_windows_app_window(f"http://localhost:{port}{path}")
    should_close_server = wait_for_window_close(process, shutdown=server.shutdown)
    if should_close_server:
        server.server_close()
    else:
        keep_server_alive(server_thread)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
