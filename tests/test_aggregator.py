"""Tests for org-level health aggregation."""
from src.aggregator import aggregate_org_health
from src.models import CategoryScore, CiCdSetup, CommunityFiles, HealthScore, MaintenanceActivity, RepoMetrics

def make_metrics(full_name: str, stars: int=0, language: str | None='Python', *, readme: bool=True, license: bool=True, contributing: bool=True, code_of_conduct: bool=True, has_ci: bool=True) -> RepoMetrics:
    return RepoMetrics(full_name=full_name, description=f'Test repo {full_name}', stars=stars, language=language, default_branch='main', community_files=CommunityFiles(readme=readme, license=license, contributing=contributing, code_of_conduct=code_of_conduct), ci_cd=CiCdSetup(workflow_files=['ci.yml'] if has_ci else [], workflow_count=1 if has_ci else 0), maintenance=MaintenanceActivity(commits_last_90_days=10, open_issues=2, closed_issues=8, stale_prs=0))

def make_score(total: float, doc: float=20.0, maint: float=25.0, ci: float=25.0, gov: float=20.0) -> HealthScore:
    return HealthScore(total_score=total, documentation=CategoryScore(name='Documentation', score=doc, max_score=20.0), maintenance=CategoryScore(name='Maintenance', score=maint, max_score=25.0), ci_cd=CategoryScore(name='CI/CD', score=ci, max_score=25.0), governance=CategoryScore(name='Governance', score=gov, max_score=20.0), academic_impact=CategoryScore('Academic Impact', 0.0, max_score=10.0))

def test_aggregate_org_health_basic() -> None:
    """Basic aggregation: scores, distributions, rankings."""
    results = [(make_metrics('org/repo-a', stars=100), make_score(95.0, 20, 25, 25, 20)), (make_metrics('org/repo-b', stars=50), make_score(82.0, 18, 22, 22, 18)), (make_metrics('org/repo-c', stars=10), make_score(65.0, 15, 18, 17, 15))]
    summary = aggregate_org_health(results, 'org')
    assert summary.org == 'org'
    assert summary.analyzed_repos == 3
    assert summary.failed_repos == 0
    assert summary.total_repos == 3
    assert summary.total_stars == 160
    assert summary.avg_score == 80.67
    assert summary.median_score == 82.0
    assert summary.score_distribution == {'A': 1, 'B': 1, 'C': 0, 'D': 1, 'F': 0}
    assert len(summary.top_repos) == 3
    assert summary.top_repos[0].full_name == 'org/repo-a'
    assert summary.top_repos[0].grade == 'A'
    assert summary.bottom_repos[0].full_name == 'org/repo-c'
    assert summary.category_averages['documentation'] == 17.67
    assert summary.category_averages['maintenance'] == 21.67
    assert summary.category_averages['ci_cd'] == 21.33
    assert summary.category_averages['governance'] == 17.67

def test_aggregate_org_health_missing_files_and_ci() -> None:
    """Missing community files and CI adoption rate."""
    results = [(make_metrics('org/good', readme=True, license=True, contributing=True, code_of_conduct=True, has_ci=True), make_score(90.0)), (make_metrics('org/missing-readme', readme=False, license=True, contributing=True, code_of_conduct=True, has_ci=True), make_score(80.0)), (make_metrics('org/missing-all', readme=False, license=False, contributing=False, code_of_conduct=False, has_ci=False), make_score(40.0))]
    summary = aggregate_org_health(results, 'org')
    assert summary.missing_files_stats['readme'] == 2
    assert summary.missing_files_stats['license'] == 1
    assert summary.missing_files_stats['contributing'] == 1
    assert summary.missing_files_stats['code_of_conduct'] == 1
    assert summary.ci_adoption_rate == 66.67

def test_aggregate_org_health_empty() -> None:
    """Empty results produce a zeroed summary."""
    summary = aggregate_org_health([], 'emptyorg', failed_count=2)
    assert summary.org == 'emptyorg'
    assert summary.analyzed_repos == 0
    assert summary.failed_repos == 2
    assert summary.total_repos == 2
    assert summary.avg_score == 0.0
    assert summary.top_repos == []
    assert summary.bottom_repos == []
    assert summary.ci_adoption_rate == 0.0

def test_aggregate_org_health_top_n_limit() -> None:
    """top_n parameter limits the ranked repo lists."""
    results = [(make_metrics(f'org/repo-{i:02d}', stars=i), make_score(float(100 - i))) for i in range(20)]
    summary = aggregate_org_health(results, 'org', top_n=5)
    assert len(summary.top_repos) == 5
    assert len(summary.bottom_repos) == 5
    assert summary.top_repos[0].score == 100.0
    assert summary.bottom_repos[0].score == 81.0
    summary2 = aggregate_org_health(results[:3], 'org', top_n=10)
    assert len(summary2.top_repos) == 3
    assert len(summary2.bottom_repos) == 3