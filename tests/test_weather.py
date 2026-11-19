import os
from datetime import date
from unittest import TestCase
from unittest.mock import patch

from src.infrastructure.weather import parse_forecast_payload, load_met_norway_forecast, _cache_is_fresh
from tempfile import TemporaryDirectory
from pathlib import Path


class WeatherForecastTests(TestCase):
    def test_unset_provider_uses_weather_and_readonly_cache_keeps_forecast(self):
        payload = {'properties': {'timeseries': [self._entry('2026-11-16T09:00:00Z', 5, 'rain', .4)]}}
        with patch.dict(os.environ, {}, clear=True), \
             patch('src.infrastructure.weather._read_cache', return_value=None), \
             patch('src.infrastructure.weather._fetch_payload', return_value=payload) as fetch, \
             patch('src.infrastructure.weather._write_cache', side_effect=PermissionError):
            forecast = load_met_norway_forecast()
        self.assertIn(date(2026,11,16), forecast.days)
        fetch.assert_called_once()

    def test_invalid_cache_does_not_prevent_fresh_forecast(self):
        payload = {'properties': {'timeseries': [self._entry('2026-11-16T09:00:00Z', 5, 'rain', .4)]}}
        with patch.dict(os.environ, {'WEATHER_PROVIDER': 'met-no'}), \
             patch('src.infrastructure.weather._read_cache', return_value={'payload': {}}), \
             patch('src.infrastructure.weather._fetch_payload', return_value=payload), \
             patch('src.infrastructure.weather._write_cache'):
            self.assertIsNotNone(load_met_norway_forecast())
        self.assertFalse(_cache_is_fresh({'fetched_at': 'invalid'}, 180))

    def test_explicit_off_is_respected(self):
        with patch.dict(os.environ, {'WEATHER_PROVIDER': 'off'}), \
             patch('src.infrastructure.weather._fetch_payload') as fetch:
            self.assertIsNone(load_met_norway_forecast())
        fetch.assert_not_called()

    def test_aggregates_hourly_met_forecast_by_local_day(self) -> None:
        payload = {
            "properties": {
                "meta": {"updated_at": "2026-09-06T08:29:46Z"},
                "timeseries": [
                    self._entry("2026-09-07T06:00:00Z", 10.0, "clearsky_day", 0.0),
                    self._entry("2026-09-07T12:00:00Z", 15.0, "lightrain", 0.4),
                ],
            }
        }

        with patch.dict(os.environ, {"WEATHER_TIMEZONE": "Europe/Moscow"}):
            forecast = parse_forecast_payload(payload)

        day = forecast.days[date(2026, 9, 7)]
        self.assertEqual(day["temperature_min"], 10.0)
        self.assertEqual(day["temperature_max"], 15.0)
        self.assertEqual(day["precipitation_mm"], 0.4)
        self.assertTrue(day["rain"])
        self.assertEqual(forecast.source, "MET Norway")

    @staticmethod
    def _entry(timestamp: str, temperature: float, symbol: str, rain: float) -> dict[str, object]:
        return {
            "time": timestamp,
            "data": {
                "instant": {"details": {"air_temperature": temperature}},
                "next_1_hours": {
                    "summary": {"symbol_code": symbol},
                    "details": {"precipitation_amount": rain},
                },
            },
        }
