"""Запуск веб-панели с локальными настройками проекта."""

from pathlib import Path

from src.infrastructure.app_config import load_runtime_env


def main() -> None:
    load_runtime_env(Path(__file__).resolve().parent.parent)
    # Настройки нужны до создания хранилища при импорте сервера.
    from src.app.web_server import run_server

    run_server()


if __name__ == "__main__":
    main()
