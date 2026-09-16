# Standalone Windows Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Собрать самостоятельный Windows-запуск, который хранит Supabase-настройки в AppData и не требует ручного `.env` рядом с exe.

**Architecture:** Новый модуль `src/infrastructure/app_config.py` отвечает за поиск, чтение, запись и проверку runtime-конфигурации. `windows_launcher.py` загружает конфигурацию до импорта сервера. `web_server.py` получает setup-страницу и обработчик сохранения, который пересоздает `REPORT_STORAGE`.

**Tech Stack:** Python 3.11+ stdlib, `http.server`, Supabase storage adapter, PyInstaller.

**Spec:** `docs/superpowers/specs/2026-09-16-standalone-windows-setup-design.md`

## Global Constraints

- Все новые пользовательские тексты на русском языке.
- Секретный ключ Supabase не выводить в HTML и логи.
- `.env` рядом с exe имеет приоритет над AppData.
- AppData-файл хранится в `%APPDATA%\purchase-forecast-service\.env`.
- Docker/local режим не должен ломаться.

---

### Task 1: Runtime Configuration

**Files:**
- Create: `src/infrastructure/app_config.py`
- Test: `tests/test_app_config.py`

**Interfaces:**
- Produces: `load_env_file(path: Path) -> bool`, `appdata_env_path() -> Path`, `load_runtime_env(base_dir: Path | None = None) -> Path | None`, `write_appdata_env(values: Mapping[str, str]) -> Path`, `has_database_config() -> bool`, `AppConfigError`.

- [x] Write failing tests for load priority, AppData write and Supabase readiness.
- [x] Implement config module with allowlisted keys and no secret logging.
- [x] Run `py -m unittest tests.test_app_config`.

### Task 2: Setup Page

**Files:**
- Modify: `src/app/web_server.py`
- Test: `tests/test_setup_page.py`

**Interfaces:**
- Consumes: `write_appdata_env`, `has_database_config`, `AppConfigError`.
- Produces: `render_setup_html`, `save_setup_config`, `reload_report_storage`.

- [x] Write failing tests for Russian setup page, secret masking and validation.
- [x] Implement HTML renderer and save helper.
- [x] Add `/setup`, `POST /setup`, `/api/setup/status`.
- [x] Run `py -m unittest tests.test_setup_page`.

### Task 3: Launcher and Documentation

**Files:**
- Modify: `src/app/windows_launcher.py`
- Modify: `tests/test_windows_launcher.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `load_runtime_env`, `has_database_config`.

- [x] Update launcher to load portable/AppData config and open `/setup` when Supabase config is missing.
- [x] Update README Windows section.
- [x] Run `py -m unittest`.
- [x] Run `powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1`.
