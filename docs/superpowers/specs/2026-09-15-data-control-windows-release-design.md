# Data Control And Windows Release Design

## Goal

Add a transparent data-control screen for loaded culinary reports and package the existing local web service as a Windows application.

## Scope

- Extend the existing `/reports` page with a block that explains which files participate in the forecast.
- Add `/api/data-status` so the status can be verified and reused by future UI.
- Keep all user-visible text in Russian.
- Keep the current Docker and Supabase flow intact.
- Add a Windows launcher that starts the Python web server and opens `http://localhost:8000`.
- Add a Windows build script using PyInstaller.

## Data Status

The status model reports:

- active storage label;
- report counts by type;
- every loaded report with type, period, original name, size, resolved/readable status;
- whether sales data is ready;
- whether waste data is ready;
- whether the forecast can be calculated from uploaded files;
- a short Russian summary for the owner.

The forecast is considered ready when at least one sales file is readable. Waste files are useful but not mandatory.

## Windows Release

The first Windows release is a local web-app executable:

- `purchase-forecast-service.exe` starts the embedded Python server;
- the default port remains `8000`;
- the launcher opens the browser after a short delay;
- configuration stays in `.env`;
- build artifacts are written to `dist/` and are not committed.

This is intentionally not Electron or a native desktop rewrite. The current web UI remains the product surface.

## Verification

- Unit tests cover data-status payload and reports page rendering.
- Launcher tests cover environment defaults without opening a real browser.
- `py -m unittest` must pass.
- A local HTTP check must confirm `/api/data-status`, `/reports`, and `/health`.
- Windows build script must produce a PyInstaller command and, when PyInstaller is available, create the executable.
