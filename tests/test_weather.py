import os
from datetime import date
from unittest import TestCase
from unittest.mock import patch

from src.infrastructure.weather import parse_forecast_payload


class WeatherForecastTests(TestCase):
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
