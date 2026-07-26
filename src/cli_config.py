# cli_config.py
"""Local CLI defaults configuration loader.

Loads default values for `repo-health-analyzer analyze` CLI flags from a
local `.repo-health.json` file in the working directory.

This is separate from `.repo-health.yml`, which is:
  - fetched from the target repository being analyzed,
  - controls scoring weights / ignore rules,
  - YAML format.

`.repo-health.json` is:
  - local to the user's working directory (where the CLI is invoked),
  - controls CLI flag defaults (hn_digest, weather_location, output paths, etc.),
  - JSON format.

Precedence (highest to lowest):
  1. Explicit CLI flags
  2. `.repo-health.json` in cwd (or path from --cli-config)
  3. argparse built-in defaults
  4. Environment variables (for token / s2_api_key only)

The config file is entirely optional — if missing, all argparse defaults apply.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_FILENAMES = (".repo-health.json", "repo-health.json")


@dataclass(slots=True)
class CLIConfig:
    """Default values for `analyze` CLI flags, loaded from `.repo-health.json`.

    All fields are optional — None means "use argparse default".
    Explicit CLI flags always override these values.
    """

    # Auth / API keys
    token: str | None = None
    s2_api_key: str | None = None

    # Analysis options
    skip_academic: bool | None = None

    # Output options
    output: str | None = None
    output_format: str | None = None  # "json" | "markdown" | "auto"
    json: bool | None = None
    markdown: str | None = None
    min_score: float | None = None
    save_artifact: str | None = None

    # Repo scoring config
    config: str | None = None  # path to .repo-health.yml
    baseline: str | None = None

    # Environment / discussion context
    weather_location: str | None = None
    no_weather: bool | None = None
    hn_digest: bool | None = None
    hn_limit: int | None = None

    # Terminal
    no_color: bool | None = None

    def to_argparse_defaults(self) -> dict[str, Any]:
        """Convert to a dict suitable for ArgumentParser.set_defaults().

        Only includes fields that are not None. Path-like fields are
        converted to pathlib.Path objects to match argparse's type=Path.

        Returns
        -------
        dict[str, Any]
            Mapping of argparse dest names to default values.
        """
        defaults: dict[str, Any] = {}

        # Auth / API keys
        if self.token is not None:
            defaults["token"] = self.token
        if self.s2_api_key is not None:
            defaults["s2_api_key"] = self.s2_api_key

        # Analysis options
        if self.skip_academic is not None:
            defaults["skip_academic"] = self.skip_academic

        # Output options
        if self.output is not None:
            defaults["output"] = Path(self.output)
        if self.output_format is not None:
            defaults["output_format"] = self.output_format
        if self.json is not None:
            defaults["json"] = self.json
        if self.markdown is not None:
            defaults["markdown"] = Path(self.markdown)
        if self.min_score is not None:
            defaults["min_score"] = float(self.min_score)
        if self.save_artifact is not None:
            defaults["save_artifact"] = Path(self.save_artifact)

        # Repo scoring config
        if self.config is not None:
            defaults["config"] = Path(self.config)
        if self.baseline is not None:
            defaults["baseline"] = Path(self.baseline)

        # Environment / discussion context
        if self.weather_location is not None:
            defaults["weather_location"] = self.weather_location
        if self.no_weather is not None:
            defaults["no_weather"] = self.no_weather
        if self.hn_digest is not None:
            defaults["hn_digest"] = self.hn_digest
        if self.hn_limit is not None:
            defaults["hn_limit"] = int(self.hn_limit)

        # Terminal
        if self.no_color is not None:
            defaults["no_color"] = self.no_color

        return defaults


def find_cli_config(start_dir: Path | None = None) -> Path | None:
    """Find `.repo-health.json` in start_dir or cwd.

    Search order:
      1. start_dir / `.repo-health.json`
      2. start_dir / `repo-health.json`
      3. cwd / `.repo-health.json`
      4. cwd / `repo-health.json`

    Parameters
    ----------
    start_dir:
        Directory to search first. Defaults to current working directory.

    Returns
    -------
    Path | None
        Path to config file if found, else None.
    """
    search_dirs = []
    if start_dir:
        search_dirs.append(Path(start_dir))
    cwd = Path.cwd()
    if not start_dir or Path(start_dir).resolve() != cwd.resolve():
        search_dirs.append(cwd)

    for d in search_dirs:
        for filename in DEFAULT_CONFIG_FILENAMES:
            candidate = d / filename
            if candidate.is_file():
                return candidate
    return None


def load_cli_config(path: str | Path | None = None) -> CLIConfig:
    """Load CLI defaults from `.repo-health.json`.

    Parameters
    ----------
    path:
        Explicit path to config file. If None, searches cwd for
        `.repo-health.json` then `repo-health.json`.

    Returns
    -------
    CLIConfig
        Parsed config. If file is missing, returns empty CLIConfig
        (all fields None). If file exists but is invalid JSON,
        raises ValueError.
    """
    config_path: Path | None
    if path is not None:
        config_path = Path(path)
        if not config_path.is_file():
            raise FileNotFoundError(
                f"CLI config file not found: {config_path}"
            )
    else:
        config_path = find_cli_config()

    if config_path is None or not config_path.is_file():
        # No config file — return empty defaults
        return CLIConfig()

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid JSON in CLI config {config_path}: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise ValueError(
            f"CLI config {config_path} must be a JSON object, got {type(data).__name__}"
        )

    # Build CLIConfig, ignoring unknown keys
    kwargs: dict[str, Any] = {}
    valid_fields = set(CLIConfig.__dataclass_fields__.keys())

    for key, value in data.items():
        if key not in valid_fields:
            # Silently ignore unknown keys (forward compatibility)
            continue

        # Validate / coerce types
        if key in ("skip_academic", "json", "no_weather", "hn_digest", "no_color"):
            if not isinstance(value, bool):
                raise ValueError(
                    f"CLI config {config_path}: '{key}' must be boolean, got {type(value).__name__}"
                )
            kwargs[key] = value
        elif key == "min_score":
            try:
                kwargs[key] = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"CLI config {config_path}: '{key}' must be numeric, got {value!r}"
                ) from exc
        elif key == "hn_limit":
            try:
                v = int(value)
                if v < 1:
                    raise ValueError("hn_limit must be >= 1")
                kwargs[key] = v
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"CLI config {config_path}: '{key}' must be an integer >= 1, got {value!r}"
                ) from exc
        elif key == "output_format":
            if value not in ("json", "markdown", "auto"):
                raise ValueError(
                    f"CLI config {config_path}: 'output_format' must be 'json', 'markdown', or 'auto', got {value!r}"
                )
            kwargs[key] = value
        elif key in (
            "token",
            "s2_api_key",
            "output",
            "markdown",
            "save_artifact",
            "config",
            "baseline",
            "weather_location",
        ):
            if value is not None and not isinstance(value, str):
                raise ValueError(
                    f"CLI config {config_path}: '{key}' must be a string, got {type(value).__name__}"
                )
            kwargs[key] = value
        else:
            # Fallback — should not happen if valid_fields is complete
            kwargs[key] = value

    return CLIConfig(**kwargs)
