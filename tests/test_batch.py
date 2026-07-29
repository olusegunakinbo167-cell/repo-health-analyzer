"""Tests for src/batch.py – OrgBatchRunner."""
import asyncio
from typing import List
import pytest
from src.batch import BatchOptions, OrgBatchRunner
from src.collector import RepoCollector
from src.config import RepoConfig
from src.models import CategoryScore, CiCdSetup, CommunityFiles, HealthScore, MaintenanceActivity, RepoMetrics

def make_metrics(full_name: str, stars: int=0) -> RepoMetrics:
    return RepoMetrics(full_name=full_name, description=f'Test {full_name}', stars=stars, language='Python', default_branch='main', community_files=CommunityFiles(True, True, True, True), ci_cd=CiCdSetup(['ci.yml'], 1), maintenance=MaintenanceActivity(10, 2, 8, 0))

def make_score(total: float) -> HealthScore:
    cat = lambda n, s: CategoryScore(name=n, score=s)
    return HealthScore(total_score=total, documentation=cat('Documentation', 20.0), maintenance=cat('Maintenance', 20.0), ci_cd=cat('CI/CD', 20.0), governance=cat('Governance', 20.0), academic_impact=CategoryScore('Academic Impact', 0.0, max_score=10.0))

class FakeCollector:
    """Fake RepoCollector that tracks concurrent calls."""

    def __init__(self, active: List[int], max_seen: List[int], fail_on: set[str] | None=None, delay: float=0.02):
        self._active = active
        self._max_seen = max_seen
        self._fail_on = fail_on or set()
        self._delay = delay

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def collect_by_full_name(self, full_name: str) -> RepoMetrics:
        if full_name in self._fail_on:
            raise RuntimeError(f'boom: {full_name}')
        self._active[0] += 1
        if self._active[0] > self._max_seen[0]:
            self._max_seen[0] = self._active[0]
        try:
            await asyncio.sleep(self._delay)
            return make_metrics(full_name)
        finally:
            self._active[0] -= 1

def make_fake_collector_factory(active: List[int], max_seen: List[int], fail_on: set[str] | None=None):

    def factory() -> RepoCollector:
        return FakeCollector(active, max_seen, fail_on=fail_on)
    return factory

@pytest.mark.asyncio
async def test_batch_concurrency_throttling() -> None:
    """Semaphore caps concurrent repo evaluations at configured limit."""
    active = [0]
    max_seen = [0]
    config = RepoConfig()
    runner = OrgBatchRunner(config, options=BatchOptions(concurrency=3), collector_factory=make_fake_collector_factory(active, max_seen))
    from src import batch as batch_mod
    orig_score_repo = batch_mod.score_repo

    def fake_score_repo(metrics, cfg):
        return make_score(80.0)
    batch_mod.score_repo = fake_score_repo
    try:
        repos = [f'org/repo-{i}' for i in range(10)]
        result = await runner.analyze_repos(repos, org='org')
    finally:
        batch_mod.score_repo = orig_score_repo
    assert result.org == 'org'
    assert len(result.repos) == 10
    assert len(result.failed) == 0
    assert max_seen[0] <= 3
    assert max_seen[0] >= 2

@pytest.mark.asyncio
async def test_batch_error_isolation() -> None:
    """Per-repo failures are captured; batch continues."""
    active = [0]
    max_seen = [0]
    fail_on = {'org/bad1', 'org/bad2'}
    config = RepoConfig()
    runner = OrgBatchRunner(config, options=BatchOptions(concurrency=2), collector_factory=make_fake_collector_factory(active, max_seen, fail_on=fail_on))
    from src import batch as batch_mod
    orig_score_repo = batch_mod.score_repo

    def fake_score_repo(metrics, cfg):
        return make_score(75.0)
    batch_mod.score_repo = fake_score_repo
    try:
        repos = ['org/good1', 'org/bad1', 'org/good2', 'org/bad2', 'org/good3']
        result = await runner.analyze_repos(repos, org='testorg')
    finally:
        batch_mod.score_repo = orig_score_repo
    assert len(result.repos) == 3
    assert len(result.failed) == 2
    failed_names = {name for name, _ in result.failed}
    assert failed_names == fail_on
    for _, err in result.failed:
        assert 'RuntimeError' in err
        assert 'boom' in err

@pytest.mark.asyncio
async def test_batch_results_sorted_by_score() -> None:
    """Results are sorted by score descending."""
    active = [0]
    max_seen = [0]
    config = RepoConfig()
    runner = OrgBatchRunner(config, options=BatchOptions(concurrency=2), collector_factory=make_fake_collector_factory(active, max_seen))
    from src import batch as batch_mod
    orig_score_repo = batch_mod.score_repo
    score_map = {'org/low': 40.0, 'org/high': 95.0, 'org/mid': 70.0}

    def fake_score_repo(metrics, cfg):
        return make_score(score_map.get(metrics.full_name, 60.0))
    batch_mod.score_repo = fake_score_repo
    try:
        repos = ['org/low', 'org/high', 'org/mid']
        result = await runner.analyze_repos(repos, org='org')
    finally:
        batch_mod.score_repo = orig_score_repo
    scores = [h.total_score for _, h in result.repos]
    assert scores == [95.0, 70.0, 40.0]

@pytest.mark.asyncio
async def test_batch_progress_callback() -> None:
    """Progress callback fires for each completed repo (success + failure)."""
    active = [0]
    max_seen = [0]
    fail_on = {'org/bad'}
    config = RepoConfig()
    runner = OrgBatchRunner(config, options=BatchOptions(concurrency=2), collector_factory=make_fake_collector_factory(active, max_seen, fail_on=fail_on))
    from src import batch as batch_mod
    orig_score_repo = batch_mod.score_repo
    batch_mod.score_repo = lambda m, c: make_score(80.0)
    progress: list[tuple[str, int, int]] = []

    def on_progress(full_name: str, completed: int, total: int) -> None:
        progress.append((full_name, completed, total))
    try:
        repos = ['org/a', 'org/bad', 'org/b']
        result = await runner.analyze_repos(repos, org='org', progress_callback=on_progress)
    finally:
        batch_mod.score_repo = orig_score_repo
    assert len(progress) == 3
    assert all((total == 3 for _, _, total in progress))
    completed_counts = sorted((c for _, c, _ in progress))
    assert completed_counts == [1, 2, 3]