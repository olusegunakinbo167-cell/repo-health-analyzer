"""Tests for the health scoring engine."""

from src.models import (
    CiCdSetup,
    CommunityFiles,
    HealthScore,
    MaintenanceActivity,
    RepoMetrics,
)
from src.scorer import (
    score_ci_cd,
    score_documentation,
    score_governance,
    score_maintenance,
    score_repo,
)


def make_metrics(
    *,
    readme=True,
    license=True,
    contributing=True,
    code_of_conduct=True,
    workflow_count=1,
    workflow_files=None,
    commits=10,
    open_issues=2,
    closed_issues=8,
    stale_prs=0,
) -> RepoMetrics:
    if workflow_files is None:
        workflow_files = ["ci.yml"] * workflow_count
    return RepoMetrics(
        full_name="o/r",
        description="Test",
        stars=0,
        language="Python",
        default_branch="main",
        community_files=CommunityFiles(
            readme=readme,
            license=license,
            contributing=contributing,
            code_of_conduct=code_of_conduct,
        ),
        ci_cd=CiCdSetup(
            workflow_files=workflow_files[:workflow_count],
            workflow_count=workflow_count,
        ),
        maintenance=MaintenanceActivity(
            commits_last_90_days=commits,
            open_issues=open_issues,
            closed_issues=closed_issues,
            stale_prs=stale_prs,
        ),
    )


def test_score_documentation_perfect() -> None:
    metrics = make_metrics()
    cat = score_documentation(metrics)
    assert cat.score == 25.0
    assert cat.penalties == []
    assert cat.recommendations == []


def test_score_documentation_missing_all() -> None:
    metrics = make_metrics(readme=False, license=False, contributing=False, code_of_conduct=False)
    cat = score_documentation(metrics)
    assert cat.score == 0.0
    assert len(cat.penalties) == 4
    assert len(cat.recommendations) == 4
    assert any("README" in p for p in cat.penalties)
    assert any("LICENSE" in p for p in cat.penalties)


def test_score_maintenance_active_high_close_ratio() -> None:
    metrics = make_metrics(commits=25, open_issues=2, closed_issues=18)
    cat = score_maintenance(metrics)
    # 15 pts commits + 10 pts close ratio = 25
    assert cat.score == 25.0
    assert cat.penalties == []


def test_score_maintenance_zero_commits() -> None:
    metrics = make_metrics(commits=0, open_issues=1, closed_issues=1)
    cat = score_maintenance(metrics)
    # 0 commits + 4 pts for 0.5 close ratio
    assert cat.score == 4.0
    assert any("No commits" in p for p in cat.penalties)
    assert any("active development" in r for r in cat.recommendations)


def test_score_maintenance_no_issues() -> None:
    """Brand-new repo with zero commits and zero issues."""
    metrics = make_metrics(commits=0, open_issues=0, closed_issues=0)
    cat = score_maintenance(metrics)
    # 0 commits + 5 neutral pts for no issues
    assert cat.score == 5.0
    assert any("No commits" in p for p in cat.penalties)
    assert any("No issues tracked" in p for p in cat.penalties)


def test_score_maintenance_low_close_ratio() -> None:
    metrics = make_metrics(commits=5, open_issues=80, closed_issues=20)
    cat = score_maintenance(metrics)
    # 8 pts commits + 1 pt close ratio
    assert cat.score == 9.0
    assert any("close ratio" in p.lower() for p in cat.penalties)


def test_score_ci_cd_none() -> None:
    metrics = make_metrics(workflow_count=0, workflow_files=[])
    cat = score_ci_cd(metrics)
    assert cat.score == 0.0
    assert any("No GitHub Actions" in p for p in cat.penalties)


def test_score_ci_cd_three_workflows() -> None:
    metrics = make_metrics(
        workflow_count=3, workflow_files=["ci.yml", "lint.yml", "release.yml"]
    )
    cat = score_ci_cd(metrics)
    assert cat.score == 25.0
    assert cat.penalties == []


def test_score_governance_perfect() -> None:
    metrics = make_metrics(license=True, stale_prs=0)
    cat = score_governance(metrics)
    assert cat.score == 25.0
    assert cat.penalties == []


def test_score_governance_no_license_stale_prs() -> None:
    metrics = make_metrics(license=False, open_issues=5, closed_issues=15, stale_prs=10)
    cat = score_governance(metrics)
    # 0 license + 0 stale PR score (10/20 = 0.5 > 0.25)
    assert cat.score == 0.0
    assert any("LICENSE" in p for p in cat.penalties)
    assert any("stale PR" in p for p in cat.penalties)


def test_score_governance_no_issues_tracked() -> None:
    """Edge case: no issues/PRs tracked at all."""
    metrics = make_metrics(license=True, open_issues=0, closed_issues=0, stale_prs=0)
    cat = score_governance(metrics)
    # 10 license + 15 stale (0 stale PRs)
    assert cat.score == 25.0


def test_score_repo_perfect() -> None:
    """Perfect repo scores 100."""
    metrics = make_metrics(
        readme=True,
        license=True,
        contributing=True,
        code_of_conduct=True,
        workflow_count=3,
        commits=25,
        open_issues=2,
        closed_issues=18,
        stale_prs=0,
    )
    health = score_repo(metrics)
    assert isinstance(health, HealthScore)
    assert health.total_score == 100.0
    assert health.grade == "A"
    assert health.documentation.score == 25.0
    assert health.maintenance.score == 25.0
    assert health.ci_cd.score == 25.0
    assert health.governance.score == 25.0


def test_score_repo_brand_new() -> None:
    """Brand-new repo with zero commits, no issues, no files, no CI."""
    metrics = make_metrics(
        readme=False,
        license=False,
        contributing=False,
        code_of_conduct=False,
        workflow_count=0,
        workflow_files=[],
        commits=0,
        open_issues=0,
        closed_issues=0,
        stale_prs=0,
    )
    health = score_repo(metrics)
    # Documentation: 0
    # Maintenance: 0 commits + 5 neutral = 5
    # CI/CD: 0
    # Governance: 0 license + 15 (0 stale) = 15
    # Total = 20
    assert health.total_score == 20.0
    assert health.grade == "F"
    assert len(health.all_recommendations()) > 0


def test_score_repo_grade_boundaries() -> None:
    """Verify grade boundaries A/B/C/D/F."""
    # Build a metrics object and patch scores via scorer internals
    # Easier: just check the grade property directly
    base = make_metrics()
    health = score_repo(base)

    for score, expected_grade in [
        (95, "A"),
        (85, "B"),
        (75, "C"),
        (65, "D"),
        (30, "F"),
    ]:
        hs = HealthScore(
            total_score=score,
            documentation=health.documentation,
            maintenance=health.maintenance,
            ci_cd=health.ci_cd,
            governance=health.governance,
        )
        assert hs.grade == expected_grade


# ── CI/CD & Code Quality (complexity) ──


def test_score_ci_cd_with_complexity_a() -> None:
    """CI/CD with complexity rating A contributes full points."""
    from src.models import CodeComplexity

    metrics = make_metrics(workflow_count=3)
    metrics.code_complexity = CodeComplexity(
        available=True,
        avg_complexity=3.2,
        max_complexity=8,
        total_functions=42,
        rating="A",
        high_risk_functions=[],
    )
    cat = score_ci_cd(metrics)
    # 20 pts workflows + 5 pts complexity = 25
    assert cat.score == 25.0
    assert cat.name == "CI/CD & Code Quality"
    assert not any("complexity" in p.lower() for p in cat.penalties)


def test_score_ci_cd_with_complexity_c() -> None:
    """Complexity rating C reduces CI/CD score."""
    from src.models import CodeComplexity

    metrics = make_metrics(workflow_count=3)
    metrics.code_complexity = CodeComplexity(
        available=True,
        avg_complexity=15.0,
        max_complexity=22,
        total_functions=30,
        rating="C",
        high_risk_functions=[
            {"file": "risky.py", "function": "foo", "cc": 18, "lineno": 42}
        ],
    )
    cat = score_ci_cd(metrics)
    # 20 pts workflows + 3 pts complexity = 23
    assert cat.score == 23.0
    assert any("complexity" in p.lower() for p in cat.penalties)


def test_score_ci_cd_with_complexity_e() -> None:
    """Complexity rating E gives zero complexity points."""
    from src.models import CodeComplexity

    metrics = make_metrics(workflow_count=2)
    metrics.code_complexity = CodeComplexity(
        available=True,
        avg_complexity=30.0,
        max_complexity=45,
        total_functions=10,
        rating="E",
        high_risk_functions=[],
    )
    cat = score_ci_cd(metrics)
    # 15 pts workflows + 0 pts complexity = 15
    assert cat.score == 15.0
    assert any("complexity" in p.lower() for p in cat.penalties)


def test_score_ci_cd_complexity_unavailable() -> None:
    """Missing complexity data does not penalize — score scales to 25."""
    from src.models import CodeComplexity

    metrics = make_metrics(workflow_count=3)
    # complexity.available = False — should not penalize
    metrics.code_complexity = CodeComplexity.unavailable()
    cat = score_ci_cd(metrics)
    # 3 workflows = 20 pts, scaled to 25-pt range = 25.0 points
    assert cat.score == 25.0
    assert cat.name == "CI/CD & Code Quality"


# ── Maintenance (churn) ──


def test_score_maintenance_with_low_churn() -> None:
    """Low churn contributes positively to maintenance score."""
    from src.models import CodeChurn

    metrics = make_metrics(commits=10, open_issues=2, closed_issues=8)
    metrics.code_churn = CodeChurn(
        available=True,
        churn_score=15,
        trend="stable",
        total_insertions=120,
        total_deletions=30,
        files_changed=5,
        hot_files=[],
    )
    cat = score_maintenance(metrics)
    # commits 10 → 8 pts, issue ratio 0.8 → 10 pts, churn 15 → 5 pts = 23
    # (commit velocity is scaled to 0–10 when churn is available)
    assert cat.score == 23.0
    assert any("churn" in r.lower() for r in cat.recommendations)


def test_score_maintenance_with_high_churn() -> None:
    """High rising churn penalizes maintenance score."""
    from src.models import CodeChurn

    metrics = make_metrics(commits=10, open_issues=2, closed_issues=8)
    metrics.code_churn = CodeChurn(
        available=True,
        churn_score=85,
        trend="rising",
        total_insertions=5000,
        total_deletions=3000,
        files_changed=25,
        hot_files=[{"file": "hot.py", "churn": 1200}],
    )
    cat = score_maintenance(metrics)
    # commits 10 → 8 pts, issue ratio 0.8 → 10 pts, churn 85/rising → 0 pts = 18
    assert cat.score == 18.0
    assert any("churn" in p.lower() for p in cat.penalties)


def test_score_maintenance_churn_unavailable() -> None:
    """Missing churn data does not penalize — legacy scoring path."""
    from src.models import CodeChurn

    metrics = make_metrics(commits=25, open_issues=2, closed_issues=18)
    metrics.code_churn = CodeChurn.unavailable()
    cat = score_maintenance(metrics)
    # churn unavailable → legacy path: commits 25 → 15 pts, issue ratio 0.9 → 10 pts = 25
    assert cat.score == 25.0

