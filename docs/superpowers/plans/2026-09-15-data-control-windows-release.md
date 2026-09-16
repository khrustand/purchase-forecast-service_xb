# Data Control And Windows Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add report data transparency and build a Windows launcher for the existing web service.

**Architecture:** Keep the current Python web server as the application. Add a small data-status payload builder in `src/app/web_server.py`, render that status on `/reports`, expose it at `/api/data-status`, and add `src/app/windows_launcher.py` plus `scripts/build_windows.ps1` for Windows packaging.

**Tech Stack:** Python 3.11 standard library, unittest, PyInstaller for optional Windows packaging, existing Supabase/local storage adapters.

**Spec:** `docs/superpowers/specs/2026-09-15-data-control-windows-release-design.md`

## Global Constraints

- All user-visible UI, reports, hints, errors, and documentation must be in Russian.
- Do not print or commit real `.env` secrets.
- Keep Docker and Supabase behavior compatible with the current service.
- Use TDD for behavior changes.
- Build artifacts stay in `dist/` and `build/`.

---

### Task 1: Data Status Payload

**Files:**
- Modify: `src/app/web_server.py`
- Test: `tests/test_reports_page.py`

**Interfaces:**
- Produces: `build_data_status() -> dict[str, Any]`
- Consumes: `REPORT_STORAGE.list()`, `REPORT_STORAGE.resolve(report_id)`, `REPORT_STORAGE.storage_label()`

- [ ] Write failing tests for storage label, report counts, readable status, and forecast readiness.
- [ ] Run `py -m unittest tests.test_reports_page` and verify the new tests fail.
- [ ] Implement `build_data_status()` in `src/app/web_server.py`.
- [ ] Run `py -m unittest tests.test_reports_page` and verify it passes.

### Task 2: Reports Page Data Control UI And API

**Files:**
- Modify: `src/app/web_server.py`
- Test: `tests/test_reports_page.py`

**Interfaces:**
- Consumes: `build_data_status()`
- Produces: `/api/data-status`, a Russian block on `/reports`

- [ ] Write failing tests for `/reports` HTML containing “Используется в расчете” and status summaries.
- [ ] Write a failing handler test or payload route check for `/api/data-status`.
- [ ] Implement rendering helpers for the data-control block.
- [ ] Add the `/api/data-status` GET route.
- [ ] Run `py -m unittest tests.test_reports_page`.

### Task 3: Windows Launcher

**Files:**
- Create: `src/app/windows_launcher.py`
- Test: `tests/test_windows_launcher.py`

**Interfaces:**
- Produces: `main() -> int`
- Produces: `open_browser_later(url: str, delay_seconds: float = 1.5) -> threading.Thread`

- [ ] Write failing tests that launcher sets `APP_PORT=8000` by default and opens `http://localhost:8000`.
- [ ] Implement launcher with standard library only.
- [ ] Run `py -m unittest tests.test_windows_launcher`.

### Task 4: Windows Build Script And Docs

**Files:**
- Create: `scripts/build_windows.ps1`
- Modify: `README.md`
- Modify: `.env.example`
- Test: existing unit tests and a PowerShell syntax check

**Interfaces:**
- Produces: `scripts/build_windows.ps1`
- Produces: `dist/purchase-forecast-service.exe` when PyInstaller is installed

- [ ] Add a PowerShell build script that installs/checks PyInstaller and builds `src.app.windows_launcher`.
- [ ] Document the Windows build and launch flow in README.
- [ ] Run `py -m unittest`.
- [ ] Run the build script or report the missing tool clearly.
