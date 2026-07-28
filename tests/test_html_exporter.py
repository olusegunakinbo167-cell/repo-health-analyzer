"""Tests for HTML report exporter."""

import json

from src.exporters import HTMLExporter, ReportMetadata
from src.exporters.base import PluginStatus
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
        description="Test repo <with> HTML & special chars",
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


def test_html_exporter_basic():
    metrics, health = _make_test_objects()
    exporter = HTMLExporter()
    assert exporter.format_name == "html"
    assert ".html" in exporter.file_extensions
    assert ".htm" in exporter.file_extensions

    output = exporter.export(metrics, health)

    # Basic structure
    assert "<!DOCTYPE html>" in output
    assert "<html" in output
    assert "</html>" in output

    # Repository info (HTML-escaped)
    assert "octocat/Hello-World" in output
    assert "Test repo &lt;with&gt; HTML &amp; special chars" in output

    # Health score
    assert "78.5" in output
    assert "Grade" in output

    # Categories
    assert "Documentation" in output
    assert "Maintenance" in output
    assert "CI/CD" in output
    assert "Governance" in output

    # Recommendations
    assert "Add CONTRIBUTING.md" in output


def test_html_exporter_with_metadata():
    metrics, health = _make_test_objects()
    exporter = HTMLExporter()

    metadata = ReportMetadata(
        repository="octocat/Hello-World",
        commit_sha="abc123",
        timestamp="2026-07-25T10:00:00Z",
        tool_version="0.3.0",
    )

    output = exporter.export(metrics, health, metadata=metadata)

    assert "repo-health-analyzer v0.3.0" in output
    assert "2026-07-25 10:00:00 UTC" in output


def test_html_exporter_with_plugin_statuses():
    metrics, health = _make_test_objects()
    exporter = HTMLExporter()

    plugin_statuses = [
        PluginStatus(
            name="fandango",
            available=True,
            version=None,
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

    output = exporter.export(metrics, health, plugin_statuses=plugin_statuses)

    assert "Plugin Status" in output
    assert "fandango" in output
    assert "embark" in output
    assert "✓" in output or "&#x2713;" in output or "available" in output.lower()


def test_html_exporter_with_environment_context():
    metrics, health = _make_test_objects()
    exporter = HTMLExporter()

    env_context = {
        "location": "40.7128,-74.0060",
        "forecast": {
            "temperature": 72,
            "temperatureUnit": "F",
            "shortForecast": "Partly Cloudy",
            "detailedForecast": "Partly cloudy with a slight chance of rain.",
            "windSpeed": "10 mph",
            "windDirection": "NW",
        },
        "alerts": {
            "count": 1,
            "alerts": [{"event": "Heat Advisory", "severity": "Moderate"}],
        },
        "observation": {
            "station_id": "KNYC",
            "textDescription": "Partly Cloudy",
        },
    }

    output = exporter.export(metrics, health, environment_context=env_context)

    assert "Environment Context" in output
    assert "40.7128,-74.0060" in output
    assert "Partly Cloudy" in output
    assert "72" in output
    assert "Heat Advisory" in output


def test_html_exporter_with_hn_context():
    metrics, health = _make_test_objects()
    exporter = HTMLExporter()

    hn_context = {
        "top_story_ids": [123, 456, 789],
        "stories": [
            {
                "id": 123,
                "title": "Test Story <with> HTML",
                "by": "testuser",
                "score": 150,
                "descendants": 42,
                "url": "https://example.com/article",
            },
            {
                "id": 456,
                "title": "Another Story & More",
                "by": "someone",
                "score": 89,
                "descendants": 12,
                "url": "",
            },
        ],
        "fetched_at": "2026-07-26T09:00:00Z",
    }

    output = exporter.export(metrics, health, hn_context=hn_context)

    assert "Hacker News Context" in output
    # HTML escaped
    assert "Test Story &lt;with&gt; HTML" in output
    assert "Another Story &amp; More" in output
    # Story metadata
    assert "testuser" in output
    assert "150" in output
    # Links
    assert "https://example.com/article" in output
    assert "news.ycombinator.com/item?id=123" in output


def test_html_exporter_xss_protection():
    """HTML exporter must escape all user-controlled content."""
    metrics, health = _make_test_objects()
    # Inject XSS payloads
    metrics.description = '<script>alert("xss")</script>'
    health.documentation.recommendations = ['Fix <img src=x onerror=alert(1)>']

    exporter = HTMLExporter()
    output = exporter.export(metrics, health)

    # Dangerous content must be escaped
    assert "<script>alert" not in output
    assert "&lt;script&gt;alert" in output
    assert "<img src=x onerror=" not in output
    assert "&lt;img src=x onerror=" in output


def test_html_exporter_self_contained():
    """HTML output must be self-contained (no external CSS/JS)."""
    metrics, health = _make_test_objects()
    exporter = HTMLExporter()
    output = exporter.export(metrics, health)

    # Inline CSS only
    assert "<style>" in output
    # No external resources
    assert '<link rel="stylesheet"' not in output
    assert '<script src=' not in output
    # No external images
    assert '<img src="http' not in output


def test_html_exporter_dark_mode():
    """HTML includes prefers-color-scheme dark mode support."""
    metrics, health = _make_test_objects()
    exporter = HTMLExporter()
    output = exporter.export(metrics, health)

    assert "prefers-color-scheme: dark" in output
    assert "--bg:" in output  # CSS variables


def test_html_exporter_baseline_with_missing_category():
    """HTML exporter handles BaselineDiff with None baseline/delta (schema evolution).

    When a category exists in current but not in baseline (e.g., new 'financial'
    category, or weight rebalancing 25pt → 20pt), CategoryDelta.baseline and
    CategoryDelta.delta are None.  The HTML exporter must render these gracefully
    with N/A / 'new' badges instead of crashing with AttributeError/TypeError
    during string formatting.
    """
    from unittest.mock import patch

    from src.models import BaselineDiff

    metrics, health = _make_test_objects()

    # Build a baseline with different max_scores (25pt → simulates weight rebalancing)
    baseline_health = HealthScore(
        total_score=70.0,
        documentation=CategoryScore("Documentation", 20.0, 25.0),
        maintenance=CategoryScore("Maintenance", 18.0, 25.0),
        ci_cd=CategoryScore("CI/CD", score=15.0, max_score=25.0),
        governance=CategoryScore("Governance", score=17.0, max_score=25.0),
    )

    # Current health has rebalanced weights (25pt → 20pt) + an extra category
    # Inject a fake "financial" category to trigger missing-baseline handling
    orig_categories = HealthScore.categories

    def patched_categories(self):
        cats = orig_categories(self)
        if self is health:
            cats = dict(cats)
            cats["financial"] = CategoryScore(
                "Financial", score=15.0, max_score=20.0, recommendations=["Add a CORPORATE_BACKER.md"]
            )
        return cats

    with patch.object(HealthScore, "categories", patched_categories):
        diff = BaselineDiff.compare(health, baseline_health)

        # Verify we have the expected None fields
        assert "financial" in diff.categories
        cd_fin = diff.categories["financial"]
        assert cd_fin.baseline is None
        assert cd_fin.delta is None
        assert cd_fin.percentage_delta is None

        # Documentation: 20/25 (80%) → 22/25 (88%)
        cd_doc = diff.categories["documentation"]
        assert cd_doc.baseline == 20.0
        assert cd_doc.current == 22.0
        assert cd_doc.delta == 2.0
        assert cd_doc.percentage_delta is not None

        # Export to HTML — this must NOT crash with TypeError/AttributeError
        # Keep the patch active during export so health.categories() includes financial,
        # allowing the category breakdown and baseline table to encounter the None values
        exporter = HTMLExporter()
        output = exporter.export(metrics, health, baseline_diff=diff)

    # Verify HTML output handles None baseline/delta gracefully
    # Missing category should show "new" badge or "N/A"
    assert "new" in output.lower() or "n/a" in output.lower() or "—" in output

    # Baseline comparison table must still render
    assert "Baseline Comparison" in output

    # Ensure no unformatted None leaked into HTML
    assert "None" not in output
    assert ">None<" not in output

    # Valid HTML
    assert "<!DOCTYPE html>" in output
    assert "</html>" in output


def test_html_exporter_baseline_percentage_delta():
    """HTML exporter shows percentage-point delta when category weights change."""
    from src.models import BaselineDiff

    metrics, health = _make_test_objects()
    # health fixture: documentation = 22.0 / 25.0 (88%)

    # Baseline with different max_score (weight rebalancing scenario)
    baseline_health = HealthScore(
        total_score=60.0,
        documentation=CategoryScore("Documentation", score=20.0, max_score=20.0),  # 100%
        maintenance=CategoryScore("Maintenance", score=15.0, max_score=20.0),
        ci_cd=CategoryScore("CI/CD", score=12.0, max_score=20.0),
        governance=CategoryScore("Governance", score=13.0, max_score=20.0),
    )

    diff = BaselineDiff.compare(health, baseline_health)

    cd_doc = diff.categories["documentation"]
    # 20/20 (100%) → 22/25 (88%) = -12pp
    # Raw delta: 22 - 20 = +2 pts (misleading!)
    # Percentage delta: 88 - 100 = -12pp
    assert cd_doc.baseline == 20.0
    assert cd_doc.current == 22.0
    assert cd_doc.delta == 2.0
    assert cd_doc.percentage_delta == -12.0
    assert cd_doc.baseline_max_score == 20.0
    assert cd_doc.max_score == 25.0

    # Export — must render percentage-point delta, not raw point delta
    exporter = HTMLExporter()
    output = exporter.export(metrics, health, baseline_diff=diff)

    # Should show "pp" (percentage points) since max_score changed 20 → 25
    assert "pp" in output
    # -12pp should appear (the normalized delta)
    assert "12" in output

    # No crash, valid HTML
    assert "<!DOCTYPE html>" in output
    assert "Baseline Comparison" in output
