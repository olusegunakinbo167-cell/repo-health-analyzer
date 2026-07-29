"""Tests for the health scoring engine."""

from src.models import (
    CiCdSetup,
    CommunityFiles,
    HealthScore,
    MaintenanceActivity,
    RepoMetrics,
)
from src.scorer import (
    score_academic_impact,
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
    assert cat.score == 20.0
    assert cat.max_score == 20.0
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
    assert cat.score == 20.0
    assert cat.max_score == 20.0
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
    # 8 license + 12 stale (0 stale PRs) = 20
    assert cat.score == 20.0


# ----------------------------------------------------------------------
# Academic impact scoring tests
# ----------------------------------------------------------------------


def _make_mock_academic_impact(
    paper_count=0,
    citations_per_paper=None,
    influential_ratio=0.1,
    venue_prestige=0.5,
    recent_years=0,
    oa_ratio=1.0,
    field_match=True,
):
    """Build a mock AcademicImpact object for scoring tests."""
    from src.metrics.academic_impact import AcademicImpact, ResolvedPaper
    from src.metrics.academic_impact import PaperReference
    from src.semantic_scholar_client import S2Paper

    if paper_count == 0:
        return None

    if citations_per_paper is None:
        citations_per_paper = [100] * paper_count

    from datetime import datetime

    current_year = datetime.now().year
    papers = []
    for i in range(paper_count):
        citations = citations_per_paper[i] if i < len(citations_per_paper) else 10
        influential = int(citations * influential_ratio)
        # Recent papers if recent_years > 0
        year = current_year - (0 if i < recent_years else 5)
        s2 = S2Paper(
            paper_id=f"test-{i}",
            corpus_id=None,
            title=f"Paper {i}",
            abstract=None,
            year=year,
            venue="Test Venue",
            citation_count=citations,
            influential_citation_count=influential,
            reference_count=0,
            is_open_access=(i < int(paper_count * oa_ratio)),
            open_access_pdf_url=None,
            fields_of_study=["Computer Science"] if field_match else ["Biology"],
            external_ids={},
            authors=["A. Author"],
            tldr=None,
            publication_types=["JournalArticle"] if venue_prestige >= 0.7 else ["Preprint"],
            publication_date=f"{year}-06-01",
            journal_name="Test Journal" if venue_prestige >= 0.7 else None,
            citation_velocity=None,
        )
        ref = PaperReference(paper_id=f"test-{i}", id_type="doi", source_file="README.md")
        papers.append(ResolvedPaper(reference=ref, s2=s2))

    return AcademicImpact(papers_referenced=papers)


def test_score_academic_impact_none() -> None:
    """No academic impact data — score 0, neutral."""
    metrics = make_metrics()
    metrics.academic_impact = None
    cat = score_academic_impact(metrics)
    assert cat.score == 0.0
    assert cat.max_score == 10.0
    assert "No research papers" in cat.recommendations[0]


def test_score_academic_impact_single_low_citation_paper() -> None:
    """1 paper, low citations — minimal score."""
    metrics = make_metrics()
    metrics.language = "Python"
    metrics.academic_impact = _make_mock_academic_impact(
        paper_count=1,
        citations_per_paper=[5],
        influential_ratio=0.0,
        venue_prestige=0.2,
        recent_years=0,
        oa_ratio=1.0,
        field_match=True,
    )
    cat = score_academic_impact(metrics)
    # paper_presence 0.5 + citation 0 + ir 0 + venue ~0.2 + recency 0 + oa 0.5 + field 1.0
    # minus penalty for zero influential citations (-0.5)
    # minus penalty for all papers >5yr (-0.5 if year is old)
    # Score should be low, ~1.2–2.2 range
    assert 0.5 <= cat.score <= 3.0
    assert cat.max_score == 10.0


def test_score_academic_impact_high_impact_papers() -> None:
    """3 papers, high citations, recent, OA, good venue."""
    from datetime import datetime

    current_year = datetime.now().year
    metrics = make_metrics()
    metrics.language = "Python"
    # High velocity: need avg_citation_velocity >= 150 for max citation points
    # Use very recent papers with high citations
    impact = _make_mock_academic_impact(
        paper_count=3,
        citations_per_paper=[300, 200, 160],
        influential_ratio=0.25,
        venue_prestige=0.9,
        recent_years=3,
        oa_ratio=1.0,
        field_match=True,
    )
    # Force years to be current for high velocity
    for rp in impact.papers_referenced:
        if rp.s2:
            rp.s2.year = current_year
    metrics.academic_impact = impact
    cat = score_academic_impact(metrics)
    # paper 1.5 + citation 3.0 + ir 1.5 + venue ~1.0 + recency 1.0 + oa 0.5 + field 1.0 = 8.5+
    assert cat.score >= 7.0
    assert cat.score <= 10.0
    assert "h-index" in cat.recommendations[0].lower()


def test_score_academic_impact_penalty_unresolved() -> None:
    """Test penalties are applied."""
    metrics = make_metrics()
    impact = _make_mock_academic_impact(paper_count=2, citations_per_paper=[50, 50])
    # Simulate unresolved by adding unresolved refs
    from src.metrics.academic_impact import ResolvedPaper, PaperReference

    ref = PaperReference(paper_id="unresolved", id_type="doi", source_file="README.md")
    impact.papers_referenced.append(ResolvedPaper(reference=ref, s2=None))
    # Now 3 papers, 2 resolved → unresolved_ratio = 0.33 > 0.3 → penalty
    metrics.academic_impact = impact
    cat = score_academic_impact(metrics)
    assert any("could not be resolved" in p for p in cat.penalties)


# ----------------------------------------------------------------------
# Full repo scoring
# ----------------------------------------------------------------------


def test_score_repo_perfect() -> None:
    """Perfect repo scores 90-100 (academic_impact is 0 by default)."""
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
    # No academic_impact set → score 0 for that category
    # Total = 20 + 25 + 25 + 20 + 0 = 90
    health = score_repo(metrics)
    assert isinstance(health, HealthScore)
    assert health.total_score == 90.0
    assert health.grade == "A"
    assert health.documentation.score == 20.0
    assert health.maintenance.score == 25.0
    assert health.ci_cd.score == 25.0
    assert health.governance.score == 20.0
    assert health.academic_impact.score == 0.0


def test_score_repo_perfect_with_academic() -> None:
    """Perfect repo + academic impact scores 100."""
    from datetime import datetime

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
    metrics.language = "Python"
    current_year = datetime.now().year
    impact = _make_mock_academic_impact(
        paper_count=6,
        citations_per_paper=[300, 250, 200, 180, 160, 150],
        influential_ratio=0.25,
        venue_prestige=0.9,
        recent_years=6,
        oa_ratio=1.0,
        field_match=True,
    )
    for rp in impact.papers_referenced:
        if rp.s2:
            rp.s2.year = current_year
    metrics.academic_impact = impact

    health = score_repo(metrics)
    assert health.total_score == 100.0
    assert health.grade == "A"
    assert health.academic_impact.score == 10.0


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
    # Governance: 0 license + 12 (0 stale) = 12
    # Academic: 0
    # Total = 17
    assert health.total_score == 17.0
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
            academic_impact=health.academic_impact,
        )
        assert hs.grade == expected_grade
