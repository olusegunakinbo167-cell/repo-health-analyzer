# tests/test_exporters.py
"""Tests for report exporters (JSON, Markdown, plugin status)."""

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from src.exporters import (
    JSONExporter,
    MarkdownExporter,
    ReportMetadata,
    export_report,
    get_exporter_for_path,
)
from src.exporters.base import PluginStatus
from src.exporters.plugin_status import check_all_plugins, check_plugin_status
from src.models import (
    CategoryScore,
    CiCdSetup,
    CommunityFiles,
    HealthScore,
    MaintenanceActivity,
    RepoMetrics,
)


def _make_test_objects():
    """Build test RepoMetrics and HealthScore objects."""
    metrics = RepoMetrics(
        full_name="octocat/Hello-World",
        description="Test repo",
        stars=42,
        language="Python",
        default_branch="main",
        commit_sha="abc123def456789",
        community_files=CommunityFiles(
            readme=True, license=True, contributing=False, code_of_conduct=True
        ),
        ci_cd=CiCdSetup(workflow_files=["ci.yml"], workflow_count=1),
        maintenance=MaintenanceActivity(
            commits_last_90_days=15,
            open_issues=3,
            closed_issues=12,
            stale_prs=1,
        ),
    )
    health = HealthScore(
        total_score=78.5,
        documentation=CategoryScore(
            "Documentation", 22.0, 25.0, [], ["Add CONTRIBUTING.md"]
        ),
        maintenance=CategoryScore("Maintenance", 20.0, 25.0, [], []),
        ci_cd=CategoryScore("CI/CD", 18.5, 25.0, [], []),
        governance=CategoryScore("Governance", 18.0, 25.0, [], []),
    )
    return metrics, health


# ── JSON exporter ──

def test_json_exporter_basic():
    metrics, health = _make_test_objects()
    exporter = JSONExporter()
    assert exporter.format_name == "json"
    assert ".json" in exporter.file_extensions

    output = exporter.export(metrics, health)
    data = json.loads(output)

    assert "metadata" in data
    assert "repository" in data
    assert "metrics" in data
    assert "health_score" in data

    assert data["repository"]["full_name"] == "octocat/Hello-World"
    assert data["health_score"]["total_score"] == 78.5


def test_json_exporter_with_plugin_statuses():
    metrics, health = _make_test_objects()
    exporter = JSONExporter()

    plugin_statuses = [
        PluginStatus(
            name="fandango",
            available=True,
            version=None,
            cli_path="/tmp/fandango.js",
            error=None,
        ),
        PluginStatus(
            name="embark",
            available=False,
            version=None,
            cli_path=None,
            error="CLI not found",
        ),
    ]

    output = exporter.export(
        metrics, health, plugin_statuses=plugin_statuses
    )
    data = json.loads(output)

    assert "plugins" in data
    assert len(data["plugins"]) == 2
    assert data["plugins"][0]["name"] == "fandango"
    assert data["plugins"][0]["available"] is True
    assert data["plugins"][1]["name"] == "embark"
    assert data["plugins"][1]["available"] is False
    assert "CLI not found" in data["plugins"][1]["error"]


def test_json_exporter_with_metadata():
    metrics, health = _make_test_objects()
    exporter = JSONExporter()

    metadata = ReportMetadata(
        repository="octocat/Hello-World",
        commit_sha="abc123def456789",
        timestamp="2026-07-25T10:00:00Z",
        tool_version="0.2.1",
    )

    output = exporter.export(metrics, health, metadata=metadata)
    data = json.loads(output)

    assert data["metadata"]["repository"] == "octocat/Hello-World"
    assert data["metadata"]["commit_sha"] == "abc123def456789"
    assert data["metadata"]["timestamp"] == "2026-07-25T10:00:00Z"
    assert data["metadata"]["tool_version"] == "0.2.1"


# ── Markdown exporter ──

def test_markdown_exporter_basic():
    metrics, health = _make_test_objects()
    exporter = MarkdownExporter()
    assert exporter.format_name == "markdown"
    assert ".md" in exporter.file_extensions

    output = exporter.export(metrics, health)

    assert "## Health Report" in output
    assert "octocat/Hello-World" in output
    assert "78.5" in output
    assert "Documentation" in output
    assert "Add CONTRIBUTING.md" in output


def test_markdown_exporter_with_plugin_statuses():
    metrics, health = _make_test_objects()
    exporter = MarkdownExporter()

    plugin_statuses = [
        PluginStatus(
            name="fandango",
            available=True,
            cli_path="/home/user/.openclaw/extensions/fandango/fandango.js",
            error=None,
        ),
        PluginStatus(
            name="embark",
            available=False,
            cli_path=None,
            error="embark CLI not found",
        ),
    ]

    output = exporter.export(
        metrics, health, plugin_statuses=plugin_statuses
    )

    assert "### Plugin Status" in output
    assert "| Plugin | Available | CLI Path |" in output
    assert "fandango" in output
    assert "embark" in output
    assert "✅" in output  # available
    assert "❌" in output  # not available


def test_markdown_exporter_with_metadata():
    metrics, health = _make_test_objects()
    exporter = MarkdownExporter()

    metadata = ReportMetadata(
        repository="octocat/Hello-World",
        commit_sha="abc123",
        timestamp="2026-07-25T10:00:00Z",
        tool_version="0.3.0",
    )

    output = exporter.export(metrics, health, metadata=metadata)

    assert "repo-health-analyzer v0.3.0" in output
    assert "2026-07-25 10:00:00 UTC" in output


# ── Exporter registry / file I/O ──

def test_get_exporter_for_path_json(tmp_path):
    from src.exporters import get_exporter_for_path

    exporter = get_exporter_for_path(tmp_path / "report.json")
    assert exporter.format_name == "json"


def test_get_exporter_for_path_markdown(tmp_path):
    from src.exporters import get_exporter_for_path

    for ext in (".md", ".markdown", ".mdown", ".mkd"):
        exporter = get_exporter_for_path(tmp_path / f"report{ext}")
        assert exporter.format_name == "markdown"


def test_get_exporter_for_path_with_format_hint(tmp_path):
    from src.exporters import get_exporter_for_path

    # Force JSON even with .txt extension
    exporter = get_exporter_for_path(tmp_path / "report.txt", format_hint="json")
    assert exporter.format_name == "json"


def test_get_exporter_for_path_unknown_extension(tmp_path):
    from src.exporters import get_exporter_for_path

    with pytest.raises(ValueError, match="Could not detect export format"):
        get_exporter_for_path(tmp_path / "report.unknown")


def test_export_report_json_to_file(tmp_path):
    metrics, health = _make_test_objects()
    output_path = tmp_path / "health-report.json"

    result_path = export_report(metrics, health, output_path)

    assert result_path == output_path
    assert output_path.exists()

    data = json.loads(output_path.read_text())
    assert data["repository"]["full_name"] == "octocat/Hello-World"
    assert data["health_score"]["total_score"] == 78.5


def test_export_report_markdown_to_file(tmp_path):
    metrics, health = _make_test_objects()
    output_path = tmp_path / "health-report.md"

    result_path = export_report(metrics, health, output_path)

    assert result_path == output_path
    assert output_path.exists()

    content = output_path.read_text()
    assert "## Health Report" in content
    assert "octocat/Hello-World" in content


def test_export_report_format_override(tmp_path):
    metrics, health = _make_test_objects()
    # .txt extension normally unknown, but format=json forces it
    output_path = tmp_path / "report.txt"

    result_path = export_report(
        metrics, health, output_path, format="json"
    )

    assert result_path.exists()
    data = json.loads(output_path.read_text())
    assert data["repository"]["full_name"] == "octocat/Hello-World"


def test_export_report_creates_parent_dirs(tmp_path):
    metrics, health = _make_test_objects()
    output_path = tmp_path / "nested" / "dir" / "report.json"

    export_report(metrics, health, output_path)

    assert output_path.exists()
    assert output_path.parent.exists()


# ── Plugin status checks ──

def test_check_plugin_status_fandango_found(monkeypatch):
    from src.metrics import fandango as fandango_mod

    # Clear cache, mock find to return a fake path
    fandango_mod._FANDANGO_CLI._cached_cli_path = None
    with patch.object(
        fandango_mod, "find_fandango_cli", return_value=Path("/fake/fandango.js")
    ):
        status = check_plugin_status("fandango")

    assert status.name == "fandango"
    assert status.available is True
    assert status.cli_path == "/fake/fandango.js"
    assert status.error is None


def test_check_plugin_status_embark_not_found(monkeypatch):
    from src.metrics import embark as embark_mod

    embark_mod._EMBARK_CLI._cached_cli_path = None
    with patch.object(
        embark_mod,
        "find_embark_cli",
        side_effect=FileNotFoundError("embark CLI not found"),
    ):
        status = check_plugin_status("embark")

    assert status.name == "embark"
    assert status.available is False
    assert status.cli_path is None
    assert "not found" in status.error.lower()


def test_check_plugin_status_unknown():
    status = check_plugin_status("nonexistent")
    assert status.name == "nonexistent"
    assert status.available is False
    assert "unknown plugin" in status.error.lower()


def test_check_all_plugins():
    # Should never raise, always returns 4 statuses
    statuses = check_all_plugins()
    assert len(statuses) == 4
    names = {s.name for s in statuses}
    assert names == {"fandango", "embark", "weather_service", "hackernews"}
    # Each status has required fields
    for s in statuses:
        assert isinstance(s.available, bool)
        assert s.name in ("fandango", "embark", "weather_service", "hackernews")
