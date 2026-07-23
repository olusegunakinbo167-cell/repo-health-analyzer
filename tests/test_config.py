"""Tests for config parsing."""


import pytest

from src.config import RepoConfig, load_config
from src.models import (
    CiCdSetup,
    CommunityFiles,
    MaintenanceActivity,
    RepoMetrics,
)
from src.scorer import score_documentation, score_repo


def make_metrics(**overrides) -> RepoMetrics:
    base = {
        "full_name": "o/r",
        "description": "Test",
        "stars": 0,
        "language": "Python",
        "default_branch": "main",
        "community_files": CommunityFiles(True, True, True, True),
        "ci_cd": CiCdSetup(["ci.yml"], 1),
        "maintenance": MaintenanceActivity(10, 2, 8, 0),
        "commit_sha": "abc123",
    }
    base.update(overrides)
    return RepoMetrics(**base)  # type: ignore[arg-type]


def test_repo_config_defaults() -> None:
    cfg = RepoConfig()
    assert cfg.weights["documentation"] == 25.0
    assert cfg.total_weight == 100.0
    assert cfg.is_ignored("missing_readme") is False


def test_load_config_weights_and_ignores(tmp_path) -> None:
    cfg_file = tmp_path / ".repo-health.yml"
    cfg_file.write_text(
        """
weights:
  documentation: 40
  maintenance: 30
  ci_cd: 20
  governance: 10
ignore:
  - missing_contributing
  - missing_code_of_conduct
  - no_ci
""",
        encoding="utf-8",
    )
    cfg = load_config(cfg_file)
    assert cfg.weights["documentation"] == 40.0
    assert cfg.weights["governance"] == 10.0
    assert cfg.is_ignored("missing_contributing")
    assert cfg.is_ignored("missing_code_of_conduct")
    assert cfg.is_ignored("no_ci")
    assert not cfg.is_ignored("missing_readme")


def test_load_config_missing_file(tmp_path) -> None:
    cfg = load_config(tmp_path / "nonexistent.yml")
    assert cfg.total_weight == 100.0
    assert len(cfg.ignore_rules) == 0


def test_load_config_filters_unknown_rules(tmp_path) -> None:
    cfg_file = tmp_path / ".repo-health.yml"
    cfg_file.write_text(
        "ignore:\n  - missing_readme\n  - not_a_real_rule\n  - missing_license\n",
        encoding="utf-8",
    )
    cfg = load_config(cfg_file)
    assert cfg.is_ignored("missing_readme")
    assert cfg.is_ignored("missing_license")
    assert "not_a_real_rule" not in cfg.ignore_rules


def test_scorer_respects_ignore_rules() -> None:
    """Missing files are forgiven when ignored in config."""
    metrics = make_metrics(
        community_files=CommunityFiles(
            readme=False, license=False, contributing=False, code_of_conduct=False
        )
    )
    # Without config: 0/25
    score_plain = score_documentation(metrics, None)
    assert score_plain.score == 0.0
    assert len(score_plain.penalties) == 4

    # With ignores: full score
    cfg = RepoConfig(
        ignore_rules={
            "missing_readme",
            "missing_license",
            "missing_contributing",
            "missing_code_of_conduct",
        }
    )
    score_ignored = score_documentation(metrics, cfg)
    assert score_ignored.score == 25.0
    assert score_ignored.penalties == []


def test_scorer_respects_custom_weights() -> None:
    """Category scores scale to configured weights."""
    # Use perfect maintenance stats to get full 25 raw points
    from src.models import MaintenanceActivity

    metrics = make_metrics()
    # Override to perfect maintenance: 25 commits, 90% close ratio
    metrics.maintenance = MaintenanceActivity(
        commits_last_90_days=25, open_issues=1, closed_issues=9, stale_prs=0
    )
    # Also need 3+ CI workflows for full CI/CD score
    from src.models import CiCdSetup

    metrics.ci_cd = CiCdSetup(
        workflow_files=["ci.yml", "lint.yml", "release.yml"], workflow_count=3
    )
    cfg = RepoConfig(
        weights={
            "documentation": 40.0,
            "maintenance": 30.0,
            "ci_cd": 20.0,
            "governance": 10.0,
        }
    )
    health = score_repo(metrics, cfg)
    # Perfect repo: each category should hit its configured max
    assert health.documentation.score == pytest.approx(40.0)
    assert health.maintenance.score == pytest.approx(30.0, abs=1.0)
    assert health.ci_cd.score == pytest.approx(20.0, abs=1.0)
    assert health.governance.score == pytest.approx(10.0)
    assert health.total_score == pytest.approx(100.0, abs=2.0)


def test_scorer_ignore_no_ci() -> None:
    """no_ci ignore gives full CI/CD points even with zero workflows."""
    metrics = make_metrics(ci_cd=CiCdSetup([], 0))
    plain = score_repo(metrics, None)
    assert plain.ci_cd.score < 5.0

    cfg = RepoConfig(ignore_rules={"no_ci"})
    ignored = score_repo(metrics, cfg)
    # CI/CD should be maxed out despite 0 workflows
    assert ignored.ci_cd.score == pytest.approx(ignored.ci_cd.max_score)
    assert ignored.ci_cd.penalties == []
