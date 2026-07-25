# tests/test_weather_service.py
"""Tests for the weather_service metrics module."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from src.metrics import weather_service
from src.metrics._external_cli import (
    CLIInvalidJSONError,
    CLITimeoutError,
    ExternalCLIError,
)


def test_find_weather_service_cli_env_override(tmp_path: Path, monkeypatch: mock.MagicMock) -> None:
    """CLI discovery respects WEATHER_SERVICE_CLI env var."""
    fake_cli = tmp_path / "weather-service"
    fake_cli.write_text("#!/usr/bin/env python3\n")
    monkeypatch.setenv("WEATHER_SERVICE_CLI", str(fake_cli))

    found = weather_service.find_weather_service_cli()
    assert found == fake_cli


def test_find_weather_service_cli_not_found(monkeypatch: mock.MagicMock) -> None:
    """CLI discovery raises FileNotFoundError when not found."""
    monkeypatch.delenv("WEATHER_SERVICE_CLI", raising=False)
    # Patch Path.exists to always return False, and shutil.which to return None
    with mock.patch("src.metrics.weather_service.Path.exists", return_value=False):
        with mock.patch("src.metrics.weather_service.shutil.which", return_value=None):
            with pytest.raises(FileNotFoundError, match="weather-service CLI not found"):
                weather_service.find_weather_service_cli()


def test_get_forecast_success(monkeypatch: mock.MagicMock) -> None:
    """get_forecast returns parsed JSON."""
    fake_response = {"properties": {"periods": [{"name": "Tonight", "temperature": 55}]}}
    with mock.patch("src.metrics.weather_service._run_weather_service", return_value=fake_response) as m:
        result = weather_service.get_forecast("37.7749,-122.4194")
    assert result == fake_response
    m.assert_called_once_with(["get-forecast", "--location", "37.7749,-122.4194"])


def test_get_forecast_missing_location() -> None:
    """get_forecast requires location arg."""
    with pytest.raises(ValueError, match="location is required"):
        weather_service.get_forecast("")


def test_get_hourly_forecast_success(monkeypatch: mock.MagicMock) -> None:
    """get_hourly_forecast returns parsed JSON."""
    fake_response = {"properties": {"periods": []}}
    with mock.patch("src.metrics.weather_service._run_weather_service", return_value=fake_response) as m:
        result = weather_service.get_hourly_forecast("37.7749,-122.4194")
    assert result == fake_response
    m.assert_called_once()


def test_find_stations_success() -> None:
    """find_stations returns station list."""
    fake_response = {"features": []}
    with mock.patch("src.metrics.weather_service._run_weather_service", return_value=fake_response):
        result = weather_service.find_stations("37.7749,-122.4194")
    assert result == fake_response


def test_get_observation_success() -> None:
    """get_observation returns station observation."""
    fake_response = {"properties": {"temperature": {"value": 15}}}
    with mock.patch("src.metrics.weather_service._run_weather_service", return_value=fake_response):
        result = weather_service.get_observation("KSFO")
    assert result == fake_response


def test_get_observation_missing_station_id() -> None:
    """get_observation requires station_id."""
    with pytest.raises(ValueError, match="station_id is required"):
        weather_service.get_observation("")


def test_get_alerts_by_area() -> None:
    """get_alerts accepts area code."""
    fake_response = {"features": []}
    with mock.patch("src.metrics.weather_service._run_weather_service", return_value=fake_response) as m:
        result = weather_service.get_alerts(area="CA")
    assert result == fake_response
    m.assert_called_once_with(["get-alerts", "--area", "CA"])


def test_get_alerts_by_location() -> None:
    """get_alerts accepts location."""
    fake_response = {"features": []}
    with mock.patch("src.metrics.weather_service._run_weather_service", return_value=fake_response) as m:
        result = weather_service.get_alerts(location="37.7749,-122.4194")
    m.assert_called_once_with(["get-alerts", "--location", "37.7749,-122.4194"])


def test_get_alerts_missing_args() -> None:
    """get_alerts requires area or location."""
    with pytest.raises(ValueError, match="either area or location is required"):
        weather_service.get_alerts()


def test_get_points_success() -> None:
    """get_points returns gridpoint info."""
    fake_response = {"properties": {}}
    with mock.patch("src.metrics.weather_service._run_weather_service", return_value=fake_response):
        result = weather_service.get_points("37.7749,-122.4194")
    assert result == fake_response


def test_get_local_time_success() -> None:
    """get_local_time returns timezone info."""
    fake_response = {"timezone": "America/Los_Angeles"}
    with mock.patch("src.metrics.weather_service._run_weather_service", return_value=fake_response):
        result = weather_service.get_local_time("37.7749,-122.4194")
    assert result == fake_response


def test_get_environment_context_success() -> None:
    """get_environment_context aggregates forecast, alerts, observation."""
    forecast_response = {
        "properties": {
            "periods": [
                {
                    "name": "Tonight",
                    "temperature": 55,
                    "temperatureUnit": "F",
                    "shortForecast": "Clear",
                    "detailedForecast": "Clear skies.",
                    "windSpeed": "5 mph",
                    "windDirection": "W",
                }
            ]
        }
    }
    alerts_response = {"features": []}
    stations_response = {
        "features": [
            {"properties": {"stationIdentifier": "KSFO"}}
        ]
    }
    obs_response = {
        "properties": {
            "timestamp": "2026-07-25T20:00:00+00:00",
            "temperature": {"value": 15, "unitCode": "wmoUnit:degC"},
            "textDescription": "Clear",
        }
    }

    def fake_run(args: list[str], timeout: float = 20.0):
        if args[0] == "get-forecast":
            return forecast_response
        elif args[0] == "get-alerts":
            return alerts_response
        elif args[0] == "find-stations":
            return stations_response
        elif args[0] == "get-observation":
            return obs_response
        raise AssertionError(f"unexpected args: {args}")

    with mock.patch("src.metrics.weather_service._run_weather_service", side_effect=fake_run):
        result = weather_service.get_environment_context("37.7749,-122.4194")

    assert result["location"] == "37.7749,-122.4194"
    assert result["forecast"]["shortForecast"] == "Clear"
    assert result["forecast"]["temperature"] == 55
    assert result["alerts"]["count"] == 0
    assert result["observation"]["station_id"] == "KSFO"
    assert result["errors"] == []


def test_get_environment_context_partial_failure() -> None:
    """get_environment_context captures errors, doesn't raise."""
    def fake_run(args: list[str], timeout: float = 20.0):
        if args[0] == "get-forecast":
            raise ExternalCLIError("NWS down")
        return {"features": []}

    with mock.patch("src.metrics.weather_service._run_weather_service", side_effect=fake_run):
        result = weather_service.get_environment_context("37.7749,-122.4194")

    assert result["forecast"] is None
    assert any("forecast" in e for e in result["errors"])
    # Other calls should still have been attempted
    assert result["location"] == "37.7749,-122.4194"


def test_run_weather_service_timeout(monkeypatch: mock.MagicMock) -> None:
    """_run_weather_service raises CLITimeoutError on timeout."""
    # Mock find_cli to return a fake path
    with mock.patch("src.metrics.weather_service.find_weather_service_cli", return_value=Path("/fake/weather-service")):
        with mock.patch("src.metrics.weather_service.subprocess.run", side_effect=mock.Mock(side_effect=Exception("timeout"))):
            # Actually subprocess.TimeoutExpired
            import subprocess

            with mock.patch("src.metrics.weather_service.subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 1)):
                with pytest.raises(CLITimeoutError):
                    weather_service._run_weather_service(["get-forecast", "--location", "0,0"], timeout=0.1)


def test_run_weather_service_invalid_json() -> None:
    """_run_weather_service raises CLIInvalidJSONError on bad JSON."""
    fake_proc = mock.Mock()
    fake_proc.returncode = 0
    fake_proc.stdout = "not json {"
    fake_proc.stderr = ""

    with mock.patch("src.metrics.weather_service.find_weather_service_cli", return_value=Path("/fake/weather-service")):
        with mock.patch("src.metrics.weather_service.subprocess.run", return_value=fake_proc):
            with pytest.raises(CLIInvalidJSONError):
                weather_service._run_weather_service(["get-forecast", "--location", "0,0"])
