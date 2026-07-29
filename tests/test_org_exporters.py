"""Tests for org-level JSON and Markdown exporters."""

import json

from src.exporters.org_json_exporter import OrgJSONExporter
from src.exporters.org_markdown_exporter import OrgMarkdownExporter, render_org_index_table
from src.models import (
    CategoryScore,
    CiCdSetup,
    CommunityFiles,
    HealthScore,
    MaintenanceActivity,
    OrgHealthSummary,
    OrgRepoScore,
    RepoMetrics,
)


def make_metrics(
    full_name: str, stars: int = 10, language: str | None = "Python"
) -> RepoMetrics:
    return RepoMetrics(
        full_name=full_name,
        description=f"Test {full_name}",
        stars=stars,
        language=language,
        default_branch="main",
        community_files=CommunityFiles(True, True, False, True),
        ci_cd=CiCdSetup(["ci.yml"], 1),
        maintenance=MaintenanceActivity(10, 2, 8, 0),
    )


def make_score(total: float) -> HealthScore:
    cat = lambda n, s: CategoryScore(name=n, score=s)
    return HealthScore(
        total_score=total,
        documentation=cat("Documentation", 20.0),
        maintenance=cat("Maintenance", 18.0),
        ci_cd=cat("CI/CD", 20.0),
        governance=cat("Governance", 17.0),
    )


def make_summary() -> OrgHealthSummary:
    return OrgHealthSummary(
        org="testorg",
        total_repos=5,
        analyzed_repos=3,
        failed_repos=2,
        avg_score=80.0,
        median_score=82.0,
        score_distribution={"A": 1, "B": 1, "C": 0, "D": 1, "F": 0},
        top_repos=[
            OrgRepoScore("testorg/repo-a", 92.5, "A", 100, "Python"),
            OrgRepoScore("testorg/repo-b", 82.0, "B", 50, "Go"),
        ],
        bottom_repos=[
            OrgRepoScore("testorg/repo-c", 65.0, "D", 5, "Rust"),
        ],
        category_averages={
            "documentation": 20.0,
            "maintenance": 18.5,
            "ci_cd": 19.0,
            "governance": 17.5,
        },
        missing_files_stats={
            "readme": 0,
            "license": 1,
            "contributing": 2,
            "code_of_conduct": 0,
        },
        ci_adoption_rate=66.67,
        total_stars=155,
        timestamp="2026-01-15T12:00:00Z",
    )


def test_org_json_exporter_basic() -> None:
    """Org JSON exporter includes summary fields and per-repo data."""
    summary = make_summary()
    results = [
        (make_metrics("testorg/repo-a", 100, "Python"), make_score(92.5)),
        (make_metrics("testorg/repo-b", 50, "Go"), make_score(82.0)),
        (make_metrics("testorg/repo-c", 5, "Rust"), make_score(65.0)),
    ]

    exporter = OrgJSONExporter()
    output = exporter.export(summary, results)
    data = json.loads(output)

    assert data["organization"] == "testorg"
    assert data["summary"]["analyzed_repos"] == 3
    assert data["summary"]["failed_repos"] == 2
    assert data["scores"]["avg_score"] == 80.0
    assert data["scores"]["distribution"]["A"] == 1
    assert data["community_files"]["missing"]["contributing"] == 2
    assert data["ci_cd"]["adoption_rate"] == 66.67

    # Per-repo section
    assert "repositories" in data
    assert len(data["repositories"]) == 3
    repo0 = data["repositories"][0]
    assert repo0["full_name"] == "testorg/repo-a"
    assert repo0["score"] == 92.5
    assert repo0["grade"] == "A"
    assert repo0["stars"] == 100
    assert "categories" in repo0


def test_org_json_exporter_without_per_repo() -> None:
    """include_per_repo=False omits the repositories array."""
    summary = make_summary()
    exporter = OrgJSONExporter()
    output = exporter.export(summary, results=None, include_per_repo=False)
    data = json.loads(output)
    assert "repositories" not in data
    assert data["organization"] == "testorg"


def test_org_markdown_exporter_full() -> None:
    """Org Markdown exporter includes all required sections."""
    summary = make_summary()
    results = [
        (make_metrics("testorg/repo-a", 100, "Python"), make_score(92.5)),
        (make_metrics("testorg/repo-b", 50, "Go"), make_score(82.0)),
        (make_metrics("testorg/repo-c", 5, "Rust"), make_score(65.0)),
    ]

    exporter = OrgMarkdownExporter()
    md = exporter.export(summary, results)

    # Header
    assert "# Organization Health Report" in md
    assert "testorg" in md
    assert "Analyzed:** 3 / 5" in md
    assert "Failed:** 2" in md

    # Scores
    assert "Average score:** 80.0" in md
    assert "Median score:** 82.0" in md

    # Grade distribution table
    assert "Grade Distribution" in md
    assert "| **A** | 1 |" in md
    assert "| **B** | 1 |" in md

    # Category averages
    assert "Category Averages" in md
    assert "Documentation" in md
    assert "CI/CD" in md

    # Community files heatmap
    assert "Community Files" in md
    assert "LICENSE" in md
    assert "CONTRIBUTING.md" in md

    # CI/CD adoption
    assert "CI/CD Adoption" in md
    assert "66.7%" in md or "66.67%" in md

    # Top / bottom repos
    assert "Top Repositories" in md
    assert "testorg/repo-a" in md
    assert "Repositories Needing Attention" in md
    assert "testorg/repo-c" in md

    # Full repo table
    assert "All Repositories" in md
    assert "| Repository | Score | Grade | Stars | Language |" in md


def test_org_markdown_exporter_no_results() -> None:
    """Exporter handles empty results gracefully."""
    summary = OrgHealthSummary(
        org="empty",
        total_repos=0,
        analyzed_repos=0,
        failed_repos=0,
        avg_score=0.0,
        median_score=0.0,
        score_distribution={"A": 0, "B": 0, "C": 0, "D": 0, "F": 0},
        top_repos=[],
        bottom_repos=[],
        category_averages={
            "documentation": 0.0,
            "maintenance": 0.0,
            "ci_cd": 0.0,
            "governance": 0.0,
        },
        missing_files_stats={
            "readme": 0,
            "license": 0,
            "contributing": 0,
            "code_of_conduct": 0,
        },
        ci_adoption_rate=0.0,
        total_stars=0,
        timestamp="2026-01-15T12:00:00Z",
    )
    exporter = OrgMarkdownExporter()
    md = exporter.export(summary, results=[])
    assert "empty" in md
    assert "Analyzed:** 0 / 0" in md


def test_render_org_index_table() -> None:
    """Index table renders links to per-repo markdown files."""
    results = [
        (make_metrics("acme/foo", 20, "Python"), make_score(90.0)),
        (make_metrics("acme/bar", 5, "Go"), make_score(60.0)),
    ]
    md = render_org_index_table(results)
    assert "# Repository Index" in md
    # Sorted by score descending
    assert md.find("acme/foo") < md.find("acme/bar")
    # Links to repos/owner-repo.md
    assert "[acme/foo](repos/acme-foo.md)" in md
    assert "[acme/bar](repos/acme-bar.md)" in md
    assert "| 90.0 |" in md
    assert "| 60.0 |" in md
