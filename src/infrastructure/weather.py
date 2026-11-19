from __future__ import annotations

import json
import os
import gzip
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


MET_NORWAY_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
SYMBOL_LABELS = {
    "clearsky": "ясно",
    "fair": "малооблачно",
    "partlycloudy": "переменная облачность",
    "cloudy": "облачно",
    "fog": "туман",
    "lightrain": "небольшой дождь",
    "rain": "дождь",
    "heavyrain": "сильный дождь",
    "lightrainshowers": "небольшие ливни",
    "rainshowers": "ливни",
    "heavyrainshowers": "сильные ливни",
    "sleet": "дождь со снегом",
    "snow": "снег",
}


@dataclass(frozen=True)
class WeatherForecast:
    days: dict[date, dict[str, object]]
    source: str
    updated_at: str | None
    stale: bool = False


def load_met_norway_forecast() -> WeatherForecast | None:
    if os.getenv("WEATHER_PROVIDER", "met-no").lower() != "met-no":
        return None
    cache_path = Path(os.getenv("WEATHER_CACHE_PATH", "data/uploads/met_norway_forecast.json"))
    ttl_minutes = int(os.getenv("WEATHER_CACHE_TTL_MINUTES", "180"))
    cached = _read_cache(cache_path)
    cached_forecast = None
    if cached:
        try:
            cached_forecast = parse_forecast_payload(cached['payload'])
        except (ValueError, TypeError, KeyError):
            cached = None
    if cached and cached_forecast and _cache_is_fresh(cached, ttl_minutes):
        return cached_forecast

    try:
        payload = _fetch_payload()
        forecast = parse_forecast_payload(payload)
        try:
            _write_cache(cache_path, payload)
        except OSError:
            pass  # Рабочий сетевой прогноз используем и без записи кэша.
        return forecast
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        if cached_forecast:
            return WeatherForecast(cached_forecast.days, cached_forecast.source, cached_forecast.updated_at, stale=True)
        return None


def parse_forecast_payload(payload: dict[str, Any]) -> WeatherForecast:
    timezone_name = os.getenv("WEATHER_TIMEZONE", "Europe/Moscow")
    try:
        local_timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        local_timezone = timezone(timedelta(hours=int(os.getenv("WEATHER_UTC_OFFSET_HOURS", "3"))))
    grouped: dict[date, dict[str, Any]] = {}
    for entry in payload["properties"]["timeseries"]:
        timestamp = datetime.fromisoformat(entry["time"].replace("Z", "+00:00")).astimezone(local_timezone)
        day = grouped.setdefault(timestamp.date(), {"temperatures": [], "rain": 0.0, "symbols": []})
        details = entry["data"]["instant"]["details"]
        day["temperatures"].append(float(details["air_temperature"]))
        interval = entry["data"].get("next_1_hours") or entry["data"].get("next_6_hours") or {}
        day["rain"] += float(interval.get("details", {}).get("precipitation_amount", 0.0))
        symbol = interval.get("summary", {}).get("symbol_code")
        if symbol:
            day["symbols"].append(str(symbol))

    result = {}
    for forecast_day, values in grouped.items():
        symbol = Counter(values["symbols"]).most_common(1)[0][0] if values["symbols"] else "cloudy"
        label = _symbol_label(symbol)
        rain_amount = round(float(values["rain"]), 1)
        minimum = round(min(values["temperatures"]), 1)
        maximum = round(max(values["temperatures"]), 1)
        result[forecast_day] = {
            "summary": f"{label}, {minimum:+g}…{maximum:+g} °C, осадки {rain_amount:g} мм",
            "temperature": round(maximum),
            "temperature_min": minimum,
            "temperature_max": maximum,
            "precipitation_mm": rain_amount,
            "rain": rain_amount > 0 or "rain" in symbol or "sleet" in symbol,
            "condition": label,
            "source": "MET Norway",
        }
    return WeatherForecast(
        days=result,
        source="MET Norway",
        updated_at=payload.get("properties", {}).get("meta", {}).get("updated_at"),
    )


def _symbol_label(symbol: str) -> str:
    normalized = symbol.removesuffix("_day").removesuffix("_night").removesuffix("_polartwilight")
    return SYMBOL_LABELS.get(normalized, normalized.replace("_", " "))


def _fetch_payload() -> dict[str, Any]:
    latitude = os.getenv("WEATHER_LATITUDE", "59.9343")
    longitude = os.getenv("WEATHER_LONGITUDE", "30.3351")
    url = f"{MET_NORWAY_URL}?lat={latitude}&lon={longitude}"
    user_agent = os.getenv(
        "WEATHER_USER_AGENT",
        "purchase-forecast-service/1.0 github.com/khrustand/purchase-forecast-service_xb",
    )
    request = Request(url, headers={"User-Agent": user_agent, "Accept-Encoding": "gzip"})
    with urlopen(request, timeout=8) as response:
        content = response.read()
        if response.headers.get("Content-Encoding") == "gzip":
            content = gzip.decompress(content)
        return json.loads(content.decode("utf-8"))


def _read_cache(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _cache_is_fresh(cache: dict[str, Any], ttl_minutes: int) -> bool:
    try:
        fetched_at = datetime.fromisoformat(str(cache["fetched_at"]))
        age = datetime.now(timezone.utc) - fetched_at
        return timedelta(0) <= age < timedelta(minutes=ttl_minutes)
    except (KeyError, TypeError, ValueError):
        return False


def _write_cache(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"fetched_at": datetime.now(timezone.utc).isoformat(), "payload": payload}),
        encoding="utf-8",
    )
