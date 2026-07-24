"""Tests for metrics modules."""

import pytest

from src.metrics.bus_factor import calculate_bus_factor
from src.models import CiCdSetup, CommunityFiles, MaintenanceActivity, RepoMetrics
from src.scorer import score_maintenance


def test_calculate_bus_factor_high_risk() -> None:
    # Top author owns 80% → high risk
    authors = ["alice@example.com"] * 80 + ["bob@example.com"] * 20
    bf = calculate_bus_factor(authors)
    assert bf["is_high_risk"] is True
    assert bf["top_author_share"] == pytest.approx(0.8, rel=0.01)
    assert bf["score"] == 0
    assert bf["unique_authors"] == 2


def test_calculate_bus_factor_low_risk() -> None:
    # Evenly distributed → low risk
    authors = (
        ["alice@example.com"] * 30
        + ["bob@example.com"] * 30
        + ["carol@example.com"] * 40
    )
    bf = calculate_bus_factor(authors)
    assert bf["is_high_risk"] is False
    assert bf["top_author_share"] == pytest.approx(0.4, rel=0.01)
    assert 0 < bf["score"] <= 100


def test_calculate_bus_factor_empty() -> None:
    bf = calculate_bus_factor([])
    assert bf["is_high_risk"] is True
    assert bf["score"] == 0
    assert bf["bus_factor"] == 0


def make_metrics_with_authors(commit_authors: list[str]) -> RepoMetrics:
    return RepoMetrics(
        full_name="o/r",
        description="Test",
        stars=0,
        language="Python",
        default_branch="main",
        community_files=CommunityFiles(
            readme=True, license=True, contributing=True, code_of_conduct=True
        ),
        ci_cd=CiCdSetup(workflow_files=["ci.yml"], workflow_count=1),
        maintenance=MaintenanceActivity(
            commits_last_90_days=25,
            open_issues=2,
            closed_issues=18,
            stale_prs=0,
            commit_authors=commit_authors,
        ),
    )


def test_score_maintenance_bus_factor_penalty() -> None:
    """High maintainer concentration deducts 5 pts from maintenance score."""
    # 80 commits from alice, 20 from bob → 80% concentration → high risk
    authors = ["alice@example.com"] * 80 + ["bob@example.com"] * 20
    metrics = make_metrics_with_authors(authors)
    cat = score_maintenance(metrics)
    # Normally 15 (commits) + 10 (close ratio) = 25 pts
    # Bus factor penalty: −5 → 20 pts
    assert cat.score == 20.0
    assert any("bus factor" in p.lower() for p in cat.penalties)
    assert any("co-maintainers" in r.lower() for r in cat.recommendations)


def test_score_maintenance_bus_factor_ok() -> None:
    """Well-distributed commits incur no bus factor penalty."""
    authors = (
        ["alice@example.com"] * 30
        + ["bob@example.com"] * 30
        + ["carol@example.com"] * 40
    )
    metrics = make_metrics_with_authors(authors)
    cat = score_maintenance(metrics)
    # No penalty, full 25 pts
    assert cat.score == 25.0
    assert not any("bus factor" in p.lower() for p in cat.penalties)
