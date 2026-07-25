# test_definitions.py
"""Tests for the metric definitions registry."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src import definitions as defs_module
from src.definitions import DefinitionsRegistry, MetricDef, get_registry, reset_registry, resolve


@pytest.fixture(autouse=True)
def _reset_registry():
    """Clear the global registry singleton before/after each test."""
    reset_registry()
    yield
    reset_registry()


def test_registry_loads_bundled_definitions():
    """Registry loads the bundled definitions/metrics.yaml by default."""
    reg = get_registry()
    # def_path should point to the bundled definitions file
    assert reg.def_path.exists()
    assert reg.def_path.name == "metrics.yaml"
    # Spot check: known rule exists
    md = reg.get("documentation", "missing_readme")
    assert md is not None
    assert md.rule_id == "missing_readme"
    assert md.category == "documentation"
    assert md.severity == "high"


def test_all_14_rules_present():
    """All expected rules are loadable from the bundled definitions.

    14 core rules + 5 academic_impact rules = 19 total.
    """
    reg = get_registry()
    expected = [
        ("documentation", "missing_readme"),
        ("documentation", "missing_license"),
        ("documentation", "missing_contributing"),
        ("documentation", "missing_code_of_conduct"),
        ("maintenance", "low_commit_activity"),
        ("maintenance", "no_commits"),
        ("maintenance", "low_issue_close_ratio"),
        ("maintenance", "no_issues_tracked"),
        ("maintenance", "bus_factor_risk"),
        ("ci_cd", "no_ci"),
        ("ci_cd", "ci_single_workflow"),
        ("ci_cd", "ci_two_workflows"),
        ("governance", "license_governance_risk"),
        ("governance", "stale_prs"),
        ("governance", "stale_prs_high"),
        ("governance", "no_issues_governance"),
        ("academic_impact", "no_papers_found"),
        ("academic_impact", "papers_found"),
        ("academic_impact", "academic_unresolved_papers"),
        ("academic_impact", "academic_low_open_access"),
        ("academic_impact", "academic_stale_papers"),
    ]
    for category, rule_id in expected:
        md = reg.get(category, rule_id)
        assert md is not None, f"Missing rule: {category}/{rule_id}"
        assert md.title
        assert md.description  # description should be non-empty


def test_resolve_basic():
    """resolve() returns (message, recommendation) for a static rule."""
    msg, rec = resolve("documentation", "missing_readme")
    assert "README" in msg
    assert "README" in rec or "readme" in rec.lower()
    assert len(msg) > 0
    assert len(rec) > 0


def test_resolve_with_template_vars():
    """Message templates interpolate runtime variables."""
    # commit activity
    msg, rec = resolve("maintenance", "low_commit_activity", commits=3)
    assert "3 commit" in msg
    # issue close ratio with format spec
    msg, rec = resolve(
        "maintenance", "low_issue_close_ratio",
        ratio=0.42, closed=5, total=12,
    )
    assert "42%" in msg
    assert "5 closed" in msg
    assert "12 total" in msg
    # bus factor
    msg, rec = resolve("maintenance", "bus_factor_risk", top_share=0.85)
    assert "85%" in msg
    # stale PRs
    msg, rec = resolve("governance", "stale_prs", stale=4, stale_ratio=0.15)
    assert "4 stale" in msg
    assert "15%" in msg
    # academic impact
    msg, rec = resolve("academic_impact", "papers_found", resolved=3, total_citations=127)
    assert "3" in msg
    assert "127" in msg


def test_resolve_missing_rule_fallback():
    """Missing rule IDs fall back gracefully to rule_id string."""
    msg, rec = resolve("documentation", "nonexistent_rule_xyz")
    assert msg == "nonexistent_rule_xyz"
    assert rec == ""


def test_resolve_missing_template_var_fallback():
    """Missing template variables fall back to unrendered title."""
    md = MetricDef(
        rule_id="test_rule",
        category="test",
        severity="medium",
        title="Test Title",
        description="",
        recommendation="",
        message_template="Value is {missing_var}",
    )
    # missing_var not provided — should fall back to title
    assert md.render_message() == "Test Title"
    # with var provided — should render template
    assert md.render_message(missing_var=42) == "Value is 42"


def test_override_path_takes_precedence():
    """Explicit definitions_path overrides bundled definitions."""
    with tempfile.TemporaryDirectory() as td:
        override_path = Path(td) / "custom_metrics.yaml"
        override_path.write_text(
            """
version: 1
metrics:
  documentation:
    missing_readme:
      severity: low
      title: "OVERRIDE: No README"
      description: "Custom description"
      recommendation: "Custom recommendation"
""",
            encoding="utf-8",
        )
        reg = DefinitionsRegistry(override_path)
        md = reg.get("documentation", "missing_readme")
        assert md is not None
        assert md.title == "OVERRIDE: No README"
        assert md.description == "Custom description"
        assert md.severity == "low"


def test_cwd_override_priority():
    """./definitions/metrics.yaml shadows the bundled copy."""
    # Save current working directory
    import os
    orig_cwd = os.getcwd()
    try:
        with tempfile.TemporaryDirectory() as td:
            # Create a fake project root with definitions/metrics.yaml
            def_dir = Path(td) / "definitions"
            def_dir.mkdir()
            override_file = def_dir / "metrics.yaml"
            override_file.write_text(
                """
version: 1
metrics:
  documentation:
    missing_readme:
      severity: info
      title: "CWD OVERRIDE"
      description: "from cwd"
      recommendation: "fix it"
""",
                encoding="utf-8",
            )
            # Chdir into the temp project root
            os.chdir(td)
            reset_registry()
            reg = get_registry()
            # Should have loaded from ./definitions/metrics.yaml, not bundled
            assert reg.def_path == override_file
            md = reg.get("documentation", "missing_readme")
            assert md is not None
            assert md.title == "CWD OVERRIDE"
    finally:
        os.chdir(orig_cwd)
        reset_registry()


def test_get_registry_singleton():
    """get_registry() returns the same instance (singleton)."""
    r1 = get_registry()
    r2 = get_registry()
    assert r1 is r2
    # Explicit path forces reload
    with tempfile.TemporaryDirectory() as td:
        custom_path = Path(td) / "m.yaml"
        custom_path.write_text(
            "version: 1\nmetrics:\n  x:\n    y:\n"
            '      severity: low\n      title: t\n      description: d\n'
            '      recommendation: r\n',
            encoding="utf-8",
        )
        r3 = get_registry(custom_path)
        assert r3 is not r1
        assert r3.def_path == custom_path


def test_all_for_category():
    """all_for_category() returns all rules in a category."""
    reg = get_registry()
    docs = reg.all_for_category("documentation")
    assert len(docs) == 4
    assert "missing_readme" in docs
    assert "missing_license" in docs
    assert "missing_contributing" in docs
    assert "missing_code_of_conduct" in docs
    # Check types
    for rule_id, md in docs.items():
        assert isinstance(md, MetricDef)
        assert md.category == "documentation"
        assert md.rule_id == rule_id


def test_metric_def_fields():
    """MetricDef captures all expected metadata fields."""
    reg = get_registry()
    md = reg.get("documentation", "missing_readme")
    assert md is not None
    assert md.severity == "high"
    assert md.weight_raw == 10
    assert "README" in md.title
    assert len(md.description) > 20
    assert len(md.recommendation) > 10
    assert md.references is not None
    assert len(md.references) > 0
    assert "onboarding" in md.tags or "discoverability" in md.tags


def test_academic_impact_rules():
    """Academic impact bonus rules are present and resolvable."""
    msg, rec = resolve(
        "academic_impact", "papers_found",
        resolved=2, total_citations=56,
    )
    assert "2" in msg
    assert "56" in msg
    # no_papers_found should exist too
    md = get_registry().get("academic_impact", "no_papers_found")
    assert md is not None
    assert md.severity == "info"


# ----------------------------------------------------------------------
# v2: Finding / resolve_finding() tests
# ----------------------------------------------------------------------


def test_resolve_finding_basic():
    """resolve_finding() returns a full Finding with all metadata."""
    from src.definitions import resolve_finding

    f = resolve_finding("documentation", "missing_readme")
    assert f.rule_id == "missing_readme"
    assert f.category == "documentation"
    assert f.severity == "high"
    assert "README" in f.message
    assert len(f.description) > 20
    assert len(f.recommendation) > 10
    assert f.references is not None
    assert len(f.references) > 0
    assert "onboarding" in f.tags or "discoverability" in f.tags
    assert f.weight_raw == 10


def test_resolve_finding_with_template_vars():
    """resolve_finding() interpolates template variables into message."""
    from src.definitions import resolve_finding

    # commit activity
    f = resolve_finding("maintenance", "low_commit_activity", commits=7)
    assert "7 commit" in f.message
    assert f.severity == "medium"
    assert "velocity" in f.tags

    # issue close ratio with format spec
    f = resolve_finding(
        "maintenance", "low_issue_close_ratio",
        ratio=0.33, closed=1, total=3,
    )
    assert "33%" in f.message
    assert "1 closed" in f.message

    # bus factor
    f = resolve_finding("maintenance", "bus_factor_risk", top_share=0.92)
    assert "92%" in f.message
    assert f.severity == "high"
    assert "bus_factor" in f.tags


def test_resolve_finding_missing_rule_fallback():
    """Missing rule IDs produce a fallback Finding (graceful degradation)."""
    from src.definitions import resolve_finding

    f = resolve_finding("documentation", "nonexistent_xyz")
    assert f.rule_id == "nonexistent_xyz"
    assert f.message == "nonexistent_xyz"
    assert f.severity == "medium"
    assert f.recommendation == ""


def test_category_score_findings_field():
    """CategoryScore.findings is populated alongside penalties/recommendations."""
    from src.definitions import reset_registry
    from src.models import CategoryScore, CommunityFiles, CiCdSetup, MaintenanceActivity, RepoMetrics
    from src.scorer import score_documentation

    reset_registry()

    # Repo missing all community files → 4 findings
    metrics = RepoMetrics(
        full_name="test/repo",
        description=None,
        stars=0,
        language="Python",
        default_branch="main",
        community_files=CommunityFiles(
            readme=False, license=False, contributing=False, code_of_conduct=False
        ),
        ci_cd=CiCdSetup(workflow_files=[], workflow_count=0),
        maintenance=MaintenanceActivity(
            commits_last_90_days=10, open_issues=0, closed_issues=0, stale_prs=0
        ),
    )
    cat = score_documentation(metrics)
    assert len(cat.findings) == 4
    assert len(cat.penalties) == 4
    assert len(cat.recommendations) == 4
    # Findings should mirror penalties/recommendations (BC)
    assert cat.findings[0].message == cat.penalties[0]
    assert cat.findings[0].recommendation == cat.recommendations[0]
    # Full metadata present
    assert cat.findings[0].severity in ("high", "medium", "low", "info", "none")
    assert len(cat.findings[0].description) > 0


def test_finding_dataclass_fields():
    """Finding dataclass has all expected fields and types."""
    from src.models import Finding

    f = Finding(
        rule_id="test_rule",
        category="test",
        severity="high",
        message="Test message",
        description="Test description",
        recommendation="Test recommendation",
        references=["https://example.com"],
        tags=["tag1", "tag2"],
        weight_raw=5,
    )
    assert f.rule_id == "test_rule"
    assert f.severity == "high"
    assert f.references == ["https://example.com"]
    assert f.tags == ["tag1", "tag2"]
    assert f.weight_raw == 5
