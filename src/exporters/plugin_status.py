# exporters/plugin_status.py
"""Plugin availability / health checks for external CLI extensions."""

from __future__ import annotations

from .base import PluginStatus


def check_plugin_status(name: str) -> PluginStatus:
    """Check if a named plugin CLI is available.

    Parameters
    ----------
    name:
        Plugin name: "fandango", "embark", or "weather_service".

    Returns
    -------
    PluginStatus
        Availability info. Never raises — errors are captured in the
        PluginStatus.error field.
    """
    name = name.lower()
    if name == "fandango":
        return _check_fandango()
    if name == "embark":
        return _check_embark()
    if name in ("weather", "weather_service", "weather-service"):
        return _check_weather_service()
    return PluginStatus(name=name, available=False, error=f"unknown plugin: {name}")


def _check_fandango() -> PluginStatus:
    try:
        from ..metrics.fandango import _FANDANGO_CLI, find_fandango_cli

        cli_path = find_fandango_cli()
        return PluginStatus(
            name="fandango",
            available=True,
            version=None,
            cli_path=str(cli_path),
            error=None,
        )
    except Exception as exc:
        # Clear cached CLI path so a subsequent check can retry
        try:
            _FANDANGO_CLI._cached_cli_path = None
        except Exception:
            pass
        return PluginStatus(
            name="fandango",
            available=False,
            version=None,
            cli_path=None,
            error=str(exc),
        )


def _check_embark() -> PluginStatus:
    try:
        from ..metrics.embark import _EMBARK_CLI, find_embark_cli

        cli_path = find_embark_cli()
        return PluginStatus(
            name="embark",
            available=True,
            version=None,
            cli_path=str(cli_path),
            error=None,
        )
    except Exception as exc:
        try:
            _EMBARK_CLI._cached_cli_path = None
        except Exception:
            pass
        return PluginStatus(
            name="embark",
            available=False,
            version=None,
            cli_path=None,
            error=str(exc),
        )


def _check_weather_service() -> PluginStatus:
    try:
        from ..metrics.weather_service import find_weather_service_cli

        cli_path = find_weather_service_cli()
        return PluginStatus(
            name="weather_service",
            available=True,
            version=None,
            cli_path=str(cli_path),
            error=None,
        )
    except Exception as exc:
        return PluginStatus(
            name="weather_service",
            available=False,
            version=None,
            cli_path=None,
            error=str(exc),
        )


def check_all_plugins() -> list[PluginStatus]:
    """Check all known plugins. Returns a list, never raises."""
    results: list[PluginStatus] = []
    for name in ("fandango", "embark", "weather_service"):
        try:
            results.append(check_plugin_status(name))
        except Exception as exc:  # pragma: no cover — defensive
            results.append(
                PluginStatus(name=name, available=False, error=str(exc))
            )
    return results
