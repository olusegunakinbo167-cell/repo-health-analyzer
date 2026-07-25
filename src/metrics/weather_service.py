# metrics/weather_service.py
"""National Weather Service environment context wrapper.

Calls the local OpenClaw Weather Service CLI via subprocess.
All commands are read-only.

This module provides local environment context (weather conditions)
alongside repository health metrics, useful for correlating
run conditions with analysis results.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ._external_cli import (
    CLIInvalidJSONError,
    CLITimeoutError,
    ExternalCLIError,
)


def find_weather_service_cli() -> Path:
    """Locate the weather-service CLI.

    Search order:
    1. WEATHER_SERVICE_CLI env var override
    2. Known OpenClaw extension install locations
    3. shutil.which("weather-service") PATH lookup

    Returns
    -------
    Path to the weather-service executable.

    Raises
    ------
    FileNotFoundError
        If the CLI was not found in any location.
    """
    # 1. Env override
    env_path = os.getenv("WEATHER_SERVICE_CLI")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p

    # 2. Known install locations
    candidates = [
        Path.home() / ".openclaw" / "extensions" / "weather-service" / "weather-service",
        Path("/usr/lib/node_modules/openclaw/dist/extensions/weather-service/skills/weather-service/weather-service"),
        Path(__file__).parent.parent.parent / "extensions" / "weather-service" / "weather-service",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    # 3. PATH lookup
    which = shutil.which("weather-service")
    if which:
        return Path(which)

    tried = ", ".join(str(c) for c in candidates)
    raise FileNotFoundError(
        "weather-service CLI not found. "
        f"Tried: {tried}. Set WEATHER_SERVICE_CLI=/path/to/weather-service to override."
    )


def _run_weather_service(args: list[str], timeout: float = 20.0) -> Any:
    """Invoke weather-service and return parsed JSON output.

    The Weather Service CLI outputs JSON to stdout by default (NWS API responses).

    Raises
    ------
    CLITimeoutError
        Subprocess exceeded timeout.
    CLIInvalidJSONError
        CLI output could not be parsed as JSON.
    ExternalCLIError
        Other CLI failures.
    """
    cli_path = find_weather_service_cli()

    # weather-service is a Python script, invoke with python3
    cmd = ["python3", str(cli_path), *args]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise CLITimeoutError(f"weather-service CLI timed out after {timeout}s: {exc}") from exc

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""

    if proc.returncode != 0:
        err = stderr.strip() or stdout.strip() or "unknown error"
        raise ExternalCLIError(f"weather-service CLI failed (exit {proc.returncode}): {err}")

    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise CLIInvalidJSONError(
            f"weather-service CLI returned invalid JSON: {exc}\n{stdout[:500]}"
        ) from exc


# ── Public API ──


def get_forecast(location: str) -> dict[str, Any]:
    """Get weather forecast for a location.

    Parameters
    ----------
    location:
        Latitude,longitude pair (e.g. "37.7749,-122.4194").

    Returns
    -------
    NWS forecast GeoJSON with periods array.
    """
    if not location:
        raise ValueError("location is required")
    return _run_weather_service(["get-forecast", "--location", location])


def get_hourly_forecast(location: str) -> dict[str, Any]:
    """Get hourly weather forecast for a location.

    Parameters
    ----------
    location:
        Latitude,longitude pair (e.g. "37.7749,-122.4194").
    """
    if not location:
        raise ValueError("location is required")
    return _run_weather_service(["get-hourly-forecast", "--location", location])


def find_stations(location: str) -> dict[str, Any]:
    """Find nearby weather observation stations.

    Parameters
    ----------
    location:
        Latitude,longitude pair.
    """
    if not location:
        raise ValueError("location is required")
    return _run_weather_service(["find-stations", "--location", location])


def get_observation(station_id: str) -> dict[str, Any]:
    """Get latest observation from a weather station.

    Parameters
    ----------
    station_id:
        Station identifier (e.g. "KSFO").
    """
    if not station_id:
        raise ValueError("station_id is required")
    return _run_weather_service(["get-observation", "--station-id", station_id])


def get_alerts(area: str | None = None, location: str | None = None) -> dict[str, Any]:
    """Get active weather alerts.

    Parameters
    ----------
    area:
        State/area code (e.g. "CA").
    location:
        Latitude,longitude pair (alternative to area).

    At least one of area or location must be provided.
    """
    if not area and not location:
        raise ValueError("either area or location is required")
    args = ["get-alerts"]
    if area:
        args += ["--area", area]
    if location:
        args += ["--location", location]
    return _run_weather_service(args)


def get_points(location: str) -> dict[str, Any]:
    """Get NWS gridpoint info for a location.

    Parameters
    ----------
    location:
        Latitude,longitude pair.
    """
    if not location:
        raise ValueError("location is required")
    return _run_weather_service(["get-points", "--location", location])


def get_local_time(location: str) -> dict[str, Any]:
    """Get timezone info for a location.

    Parameters
    ----------
    location:
        Latitude,longitude pair.
    """
    if not location:
        raise ValueError("location is required")
    return _run_weather_service(["get-local-time", "--location", location])


def get_environment_context(location: str = "37.7749,-122.4194") -> dict[str, Any]:
    """Collect local environment weather context.

    Fetches forecast, alerts, and observation data for the given location.
    Failures in individual calls are captured, not raised — callers
    receive partial data with error notes.

    Parameters
    ----------
    location:
        Latitude,longitude pair. Defaults to San Francisco, CA
        (37.7749,-122.4194).

    Returns
    -------
    Dict with keys: location, forecast, alerts, observation, errors
    """
    result: dict[str, Any] = {
        "location": location,
        "forecast": None,
        "alerts": None,
        "observation": None,
        "errors": [],
    }

    # Forecast
    try:
        forecast_data = get_forecast(location)
        # Extract a compact summary from the first period
        periods = forecast_data.get("properties", {}).get("periods", [])
        if periods:
            first = periods[0]
            result["forecast"] = {
                "name": first.get("name"),
                "temperature": first.get("temperature"),
                "temperatureUnit": first.get("temperatureUnit"),
                "shortForecast": first.get("shortForecast"),
                "detailedForecast": first.get("detailedForecast"),
                "windSpeed": first.get("windSpeed"),
                "windDirection": first.get("windDirection"),
            }
        result["forecast_raw"] = forecast_data
    except Exception as exc:
        result["errors"].append(f"forecast: {exc}")

    # Alerts
    try:
        alerts_data = get_alerts(location=location)
        features = alerts_data.get("features", []) if isinstance(alerts_data, dict) else []
        result["alerts"] = {
            "count": len(features),
            "alerts": [
                {
                    "event": f.get("properties", {}).get("event"),
                    "severity": f.get("properties", {}).get("severity"),
                    "headline": f.get("properties", {}).get("headline"),
                }
                for f in features[:5]  # cap at 5
            ],
        }
        result["alerts_raw"] = alerts_data
    except Exception as exc:
        result["errors"].append(f"alerts: {exc}")

    # Try to get a nearby station observation
    try:
        stations_data = find_stations(location)
        features = stations_data.get("features", []) if isinstance(stations_data, dict) else []
        if features:
            station_id = features[0].get("properties", {}).get("stationIdentifier")
            if station_id:
                obs = get_observation(station_id)
                props = obs.get("properties", {}) if isinstance(obs, dict) else {}
                result["observation"] = {
                    "station_id": station_id,
                    "timestamp": props.get("timestamp"),
                    "temperature": props.get("temperature"),
                    "windSpeed": props.get("windSpeed"),
                    "relativeHumidity": props.get("relativeHumidity"),
                    "textDescription": props.get("textDescription"),
                }
                result["observation_raw"] = obs
    except Exception as exc:
        result["errors"].append(f"observation: {exc}")

    return result
