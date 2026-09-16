from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path


APP_NAME = "purchase-forecast-service"
ENV_FILENAME = ".env"
KNOWN_ENV_KEYS = (
    "STORAGE_BACKEND",
    "SUPABASE_URL",
    "SUPABASE_ANON_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_STORAGE_BUCKET",
    "DATABASE_URL",
    "APP_PORT",
    "APP_USERNAME",
    "APP_PASSWORD",
    "REPORT_UPLOAD_DIR",
    "WEATHER_PROVIDER",
    "WEATHER_LATITUDE",
    "WEATHER_LONGITUDE",
    "WEATHER_TIMEZONE",
    "WEATHER_CACHE_PATH",
    "WEATHER_CACHE_TTL_MINUTES",
    "WEATHER_USER_AGENT",
    "TZ",
)


class AppConfigError(ValueError):
    pass


def load_env_file(path: Path, override: bool = False) -> bool:
    if not path.exists():
        return False
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if override:
            os.environ[key] = value.strip()
        else:
            os.environ.setdefault(key, value.strip())
    return True


def appdata_env_path() -> Path:
    root = os.getenv("APPDATA")
    if root:
        base = Path(root)
    else:
        base = Path.home() / "AppData" / "Roaming"
    return base / APP_NAME / ENV_FILENAME


def load_runtime_env(base_dir: Path | None = None) -> Path | None:
    root = base_dir or Path.cwd()
    candidates = [root / ENV_FILENAME, appdata_env_path()]
    for candidate in candidates:
        if load_env_file(candidate):
            return candidate
    return None


def write_appdata_env(values: Mapping[str, str]) -> Path:
    prepared = _prepare_env_values(values)
    path = appdata_env_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{key}={prepared[key]}" for key in KNOWN_ENV_KEYS if key in prepared]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for key, value in prepared.items():
        os.environ[key] = value
    return path


def has_database_config() -> bool:
    backend = os.getenv("STORAGE_BACKEND", "").strip().lower()
    if backend != "supabase":
        return False
    return bool(os.getenv("SUPABASE_URL", "").strip() and os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip())


def _prepare_env_values(values: Mapping[str, str]) -> dict[str, str]:
    prepared: dict[str, str] = {"STORAGE_BACKEND": "supabase"}
    for key in KNOWN_ENV_KEYS:
        value = values.get(key)
        if value is None:
            continue
        stripped = value.strip()
        if stripped:
            prepared[key] = stripped
    prepared["SUPABASE_STORAGE_BUCKET"] = prepared.get("SUPABASE_STORAGE_BUCKET", "uploads")
    if not prepared.get("SUPABASE_URL") or not prepared.get("SUPABASE_SERVICE_ROLE_KEY"):
        raise AppConfigError("Укажите URL проекта Supabase и secret key.")
    return prepared
