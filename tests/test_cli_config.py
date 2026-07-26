"""Tests for CLI config file loading (.repo-health.json)."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.cli_config import CLIConfig, find_cli_config, load_cli_config


def test_cli_config_empty():
    """Empty CLIConfig produces empty argparse defaults."""
    cfg = CLIConfig()
    defaults = cfg.to_argparse_defaults()
    assert defaults == {}


def test_cli_config_to_argparse_defaults():
    """CLIConfig correctly converts to argparse defaults dict."""
    cfg = CLIConfig(
        hn_digest=True,
        hn_limit=5,
        weather_location="40.7128,-74.0060",
        no_weather=False,
        output="report.json",
        output_format="json",
        min_score=80.0,
        no_color=True,
        skip_academic=True,
    )
    defaults = cfg.to_argparse_defaults()
    assert defaults["hn_digest"] is True
    assert defaults["hn_limit"] == 5
    assert defaults["weather_location"] == "40.7128,-74.0060"
    assert defaults["no_weather"] is False
    assert defaults["min_score"] == 80.0
    assert defaults["no_color"] is True
    assert defaults["skip_academic"] is True
    # Path fields are converted to Path objects
    assert defaults["output"] == Path("report.json")
    assert defaults["output_format"] == "json"


def test_find_cli_config_not_found(tmp_path, monkeypatch):
    """find_cli_config returns None when no config file exists."""
    monkeypatch.chdir(tmp_path)
    result = find_cli_config()
    assert result is None


def test_find_cli_config_dot_prefixed(tmp_path, monkeypatch):
    """find_cli_config prefers .repo-health.json over repo-health.json."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "repo-health.json").write_text('{}')
    (tmp_path / ".repo-health.json").write_text('{}')
    result = find_cli_config()
    assert result is not None
    assert result.name == ".repo-health.json"


def test_load_cli_config_missing(tmp_path, monkeypatch):
    """load_cli_config returns empty CLIConfig when file is missing."""
    monkeypatch.chdir(tmp_path)
    cfg = load_cli_config()
    assert isinstance(cfg, CLIConfig)
    assert cfg.hn_digest is None
    assert cfg.weather_location is None


def test_load_cli_config_valid(tmp_path):
    """load_cli_config correctly parses a valid JSON config file."""
    config_path = tmp_path / ".repo-health.json"
    config_path.write_text(
        json.dumps(
            {
                "hn_digest": True,
                "hn_limit": 7,
                "weather_location": "40.7128,-74.0060",
                "no_weather": False,
                "output": "out/report.json",
                "output_format": "json",
                "min_score": 85.5,
                "skip_academic": True,
                "no_color": True,
            }
        )
    )
    cfg = load_cli_config(config_path)
    assert cfg.hn_digest is True
    assert cfg.hn_limit == 7
    assert cfg.weather_location == "40.7128,-74.0060"
    assert cfg.no_weather is False
    assert cfg.output == "out/report.json"
    assert cfg.output_format == "json"
    assert cfg.min_score == 85.5
    assert cfg.skip_academic is True
    assert cfg.no_color is True


def test_load_cli_config_invalid_json(tmp_path):
    """load_cli_config raises ValueError on invalid JSON."""
    config_path = tmp_path / ".repo-health.json"
    config_path.write_text("{ invalid json }")
    with pytest.raises(ValueError, match="Invalid JSON"):
        load_cli_config(config_path)


def test_load_cli_config_invalid_types(tmp_path):
    """load_cli_config validates field types."""
    config_path = tmp_path / ".repo-health.json"

    # hn_digest must be boolean
    config_path.write_text(json.dumps({"hn_digest": "yes"}))
    with pytest.raises(ValueError, match="hn_digest.*must be boolean"):
        load_cli_config(config_path)

    # hn_limit must be >= 1
    config_path.write_text(json.dumps({"hn_limit": 0}))
    with pytest.raises(ValueError, match="hn_limit.*>= 1"):
        load_cli_config(config_path)

    # min_score must be numeric
    config_path.write_text(json.dumps({"min_score": "high"}))
    with pytest.raises(ValueError, match="min_score.*must be numeric"):
        load_cli_config(config_path)

    # output_format must be valid
    config_path.write_text(json.dumps({"output_format": "xml"}))
    with pytest.raises(ValueError, match="output_format.*must be.*json.*markdown.*auto"):
        load_cli_config(config_path)


def test_load_cli_config_unknown_keys_ignored(tmp_path):
    """Unknown keys in config file are silently ignored (forward compat)."""
    config_path = tmp_path / ".repo-health.json"
    config_path.write_text(
        json.dumps(
            {
                "hn_digest": True,
                "unknown_field": "ignored",
                "future_option": 123,
            }
        )
    )
    cfg = load_cli_config(config_path)
    assert cfg.hn_digest is True
    # Unknown keys don't raise, just ignored


def test_cli_config_flag_precedence_hn_digest(tmp_path, monkeypatch):
    """CLI --hn-digest / --no-hn-digest flags override config file."""
    from src.cli import parse_args

    # Create config with hn_digest = True
    config_path = tmp_path / ".repo-health.json"
    config_path.write_text(json.dumps({"hn_digest": True, "hn_limit": 3}))
    monkeypatch.chdir(tmp_path)

    # Config default applies when no CLI flag given
    args = parse_args(["analyze", "owner/repo"])
    assert args.hn_digest is True
    assert args.hn_limit == 3

    # --no-hn-digest overrides config true → false
    args = parse_args(["analyze", "owner/repo", "--no-hn-digest"])
    assert args.hn_digest is False

    # --hn-digest explicitly reinforces config
    args = parse_args(["analyze", "owner/repo", "--hn-digest"])
    assert args.hn_digest is True


def test_cli_config_flag_precedence_skip_academic(tmp_path, monkeypatch):
    """CLI --skip-academic / --no-skip-academic flags override config file."""
    from src.cli import parse_args

    config_path = tmp_path / ".repo-health.json"
    config_path.write_text(json.dumps({"skip_academic": True}))
    monkeypatch.chdir(tmp_path)

    args = parse_args(["analyze", "owner/repo"])
    assert args.skip_academic is True

    # Override true → false
    args = parse_args(["analyze", "owner/repo", "--no-skip-academic"])
    assert args.skip_academic is False


def test_cli_config_flag_precedence_weather(tmp_path, monkeypatch):
    """CLI --no-weather / --weather flags override config file."""
    from src.cli import parse_args

    config_path = tmp_path / ".repo-health.json"
    config_path.write_text(
        json.dumps({"weather_location": "40.7128,-74.0060", "no_weather": True})
    )
    monkeypatch.chdir(tmp_path)

    args = parse_args(["analyze", "owner/repo"])
    assert args.no_weather is True
    assert args.weather_location == "40.7128,-74.0060"

    # --weather overrides config no_weather=true → false
    args = parse_args(["analyze", "owner/repo", "--weather"])
    assert args.no_weather is False

    # CLI --weather-location overrides config
    args = parse_args(
        ["analyze", "owner/repo", "--weather-location", "37.7749,-122.4194"]
    )
    assert args.weather_location == "37.7749,-122.4194"


def test_cli_config_flag_precedence_color(tmp_path, monkeypatch):
    """CLI --no-color / --color flags override config file."""
    from src.cli import parse_args

    config_path = tmp_path / ".repo-health.json"
    config_path.write_text(json.dumps({"no_color": True}))
    monkeypatch.chdir(tmp_path)

    args = parse_args(["analyze", "owner/repo"])
    assert args.no_color is True

    # --color overrides config
    args = parse_args(["analyze", "owner/repo", "--color"])
    assert args.no_color is False


def test_cli_config_explicit_cli_config_path(tmp_path, monkeypatch):
    """--cli-config PATH loads config from explicit path, not cwd."""
    from src.cli import parse_args

    # Config in /tmp, run from different dir
    config_path = tmp_path / "my-config.json"
    config_path.write_text(json.dumps({"hn_digest": True, "hn_limit": 9}))

    other_dir = tmp_path / "other"
    other_dir.mkdir()
    monkeypatch.chdir(other_dir)

    # Without --cli-config, no config found
    args = parse_args(["analyze", "owner/repo"])
    assert args.hn_digest is False  # argparse default

    # With --cli-config, values loaded
    args = parse_args(
        ["analyze", "owner/repo", "--cli-config", str(config_path)]
    )
    assert args.hn_digest is True
    assert args.hn_limit == 9


def test_cli_config_output_paths(tmp_path, monkeypatch):
    """Config file output paths (output, markdown, save_artifact, etc.) work."""
    from src.cli import parse_args

    config_path = tmp_path / ".repo-health.json"
    config_path.write_text(
        json.dumps(
            {
                "output": "reports/health.json",
                "min_score": 75.0,
                "baseline": "baseline.json",
            }
        )
    )
    monkeypatch.chdir(tmp_path)

    args = parse_args(["analyze", "owner/repo"])
    assert str(args.output) == "reports/health.json"
    assert args.min_score == 75.0
    assert str(args.baseline) == "baseline.json"

    # CLI --output overrides config
    args = parse_args(["analyze", "owner/repo", "-o", "custom.json"])
    assert str(args.output) == "custom.json"

    # CLI --min-score overrides config
    args = parse_args(["analyze", "owner/repo", "--min-score", "90"])
    assert args.min_score == 90.0
