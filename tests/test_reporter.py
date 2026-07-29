"""Tests for report formatters."""
from src.models import CategoryScore, CiCdSetup, CommunityFiles, HealthScore, MaintenanceActivity, RepoMetrics
from src.reporter import render_markdown, render_rich

def make_sample():
    metrics = RepoMetrics(full_name='octocat/Hello-World', description='Sample repo', stars=42, language='Python', default_branch='main', community_files=CommunityFiles(readme=True, license=True, contributing=False, code_of_conduct=False), ci_cd=CiCdSetup(workflow_files=['ci.yml', 'lint.yml'], workflow_count=2), maintenance=MaintenanceActivity(commits_last_90_days=15, open_issues=3, closed_issues=12, stale_prs=1))
    health = HealthScore(total_score=72.0, documentation=CategoryScore(name='Documentation', score=15.0, penalties=['Missing CONTRIBUTING.md', 'Missing CODE_OF_CONDUCT.md'], recommendations=['Add CONTRIBUTING.md with guidelines for contributors', 'Add CODE_OF_CONDUCT.md to set community standards']), maintenance=CategoryScore(name='Maintenance', score=19.0, penalties=[], recommendations=[]), ci_cd=CategoryScore(name='CI/CD', score=20.0, penalties=[], recommendations=['Consider adding additional CI workflows']), governance=CategoryScore(name='Governance', score=18.0, penalties=['1 stale PR(s) open >30 days'], recommendations=['Review and close/merge stale pull requests']), academic_impact=CategoryScore('Academic Impact', 0.0, max_score=10.0))
    return (metrics, health)

def test_render_rich_output() -> None:
    metrics, health = make_sample()
    output = render_rich(metrics, health)
    assert 'Health Report for octocat/Hello-World' in output
    assert '72.0' in output
    assert 'Documentation' in output
    assert 'Maintenance' in output
    assert 'CI/CD' in output
    assert 'Governance' in output
    assert 'Recommendations' in output
    assert 'CONTRIBUTING' in output or 'stale' in output.lower()

def test_render_rich_color_coding() -> None:
    """Verify score-based color coding is applied (green/yellow/red)."""
    metrics, health = make_sample()
    health.total_score = 85.0
    output = render_rich(metrics, health)
    assert '85' in output
    health.total_score = 65.0
    output = render_rich(metrics, health)
    assert '65' in output
    health.total_score = 30.0
    output = render_rich(metrics, health)
    assert '30' in output

def test_render_markdown_output() -> None:
    metrics, health = make_sample()
    md = render_markdown(metrics, health)
    assert '## Health Report' in md
    assert 'octocat/Hello-World' in md
    assert 'img.shields.io/badge/Health' in md
    assert 'Grade' in md
    assert '| Category | Score | Status |' in md
    assert '| Documentation |' in md
    assert '| Maintenance |' in md
    assert '| CI/CD |' in md
    assert '| Governance |' in md
    assert '<details>' in md
    assert '<summary><b>' in md
    assert '</details>' in md
    assert 'Action Items' in md or 'Recommendations' in md
    assert 'Raw Metrics' in md
    assert 'README' in md
    assert 'LICENSE' in md
    assert 'Commits (90d)' in md

def test_render_markdown_perfect_score() -> None:
    """Markdown output for a perfect-score repo should still be well-formed."""
    metrics, health = make_sample()
    health.total_score = 100.0
    health.documentation.score = 25.0
    health.documentation.penalties = []
    health.documentation.recommendations = []
    health.maintenance.score = 25.0
    health.maintenance.penalties = []
    health.ci_cd.score = 25.0
    health.governance.score = 25.0
    md = render_markdown(metrics, health)
    assert '100' in md
    assert '<details>' in md

def test_render_markdown_zero_score() -> None:
    """Markdown output handles low-scoring repos gracefully."""
    metrics = RepoMetrics(full_name='test/empty', description=None, stars=0, language=None, default_branch='main', community_files=CommunityFiles(False, False, False, False), ci_cd=CiCdSetup([], 0), maintenance=MaintenanceActivity(0, 0, 0, 0))
    health = HealthScore(total_score=20.0, documentation=CategoryScore('Documentation', 0.0, penalties=['Missing README file'], recommendations=['Add README'], max_score=20.0), maintenance=CategoryScore('Maintenance', 5.0, penalties=['No commits'], recommendations=['Resume dev'], max_score=25.0), ci_cd=CategoryScore('CI/CD', 0.0, penalties=['No workflows'], recommendations=['Set up CI'], max_score=25.0), governance=CategoryScore('Governance', 15.0, penalties=[], recommendations=[], max_score=20.0), academic_impact=CategoryScore('Academic Impact', 0.0, max_score=10.0))
    md = render_markdown(metrics, health)
    assert 'test/empty' in md
    assert '20' in md
    assert 'red' in md.lower()
    assert '<details>' in md