"""Concurrent organization-wide repository health analysis."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Awaitable

from .collector import RepoCollector
from .config import RepoConfig
from .models import HealthScore, OrgAnalysisResult, RepoMetrics
from .scorer import score_repo


@dataclass(slots=True)
class BatchOptions:
    """Configuration for batch analysis runs."""

    concurrency: int = 4
    skip_academic: bool = False
    s2_api_key: str | None = None


class OrgBatchRunner:
    """Concurrent batch analyzer for GitHub organizations / users.

    Executes repository health evaluations in parallel using an
    asyncio.Semaphore to throttle concurrency. Failures are captured
    per-repository and do not abort the batch.
    """

    def __init__(
        self,
        config: RepoConfig,
        *,
        token: str | None = None,
        options: BatchOptions | None = None,
        collector_factory: Callable[[], RepoCollector] | None = None,
    ):
        self.config = config
        self.token = token
        self.options = options or BatchOptions()
        self._collector_factory = collector_factory

    def _make_collector(self) -> RepoCollector:
        """Create a RepoCollector instance.

        Uses collector_factory if provided (useful for testing),
        otherwise constructs a standard RepoCollector with the configured
        token / academic impact options.
        """
        if self._collector_factory is not None:
            return self._collector_factory()
        return RepoCollector(
            token=self.token,
            s2_api_key=self.options.s2_api_key,
            skip_academic_impact=self.options.skip_academic,
        )

    async def analyze_repos(
        self,
        repos: list[str],
        *,
        org: str = "unknown",
        progress_callback: Callable[[str, int, int], None | Awaitable[None]] | None = None,
    ) -> OrgAnalysisResult:
        """Analyze a list of repositories concurrently.

        Args:
            repos: List of repository full names ("owner/repo").
            org: Organization / user name for the result metadata.
            progress_callback: Optional callback invoked after each repo
                completes (success or failure). Signature:
                callback(full_name, completed_count, total_count)

        Returns:
            OrgAnalysisResult with successful (metrics, score) pairs
            and a list of (full_name, error) failures.
        """
        semaphore = asyncio.Semaphore(max(1, self.options.concurrency))
        results: list[tuple[RepoMetrics, HealthScore]] = []
        failed: list[tuple[str, str]] = []
        completed = 0
        total = len(repos)
        lock = asyncio.Lock()

        async def analyze_one(full_name: str) -> None:
            nonlocal completed
            async with semaphore:
                try:
                    async with self._make_collector() as collector:
                        metrics = await collector.collect_by_full_name(full_name)
                        health = score_repo(metrics, self.config)
                    async with lock:
                        results.append((metrics, health))
                except Exception as exc:
                    async with lock:
                        failed.append((full_name, f"{type(exc).__name__}: {exc}"))
                finally:
                    async with lock:
                        completed += 1
                        current_completed = completed
                    if progress_callback:
                        cb_result = progress_callback(
                            full_name, current_completed, total
                        )
                        if asyncio.iscoroutine(cb_result):
                            await cb_result

        await asyncio.gather(*(analyze_one(r) for r in repos))
        # Sort results by score descending for stable output
        results.sort(key=lambda pair: pair[1].total_score, reverse=True)
        return OrgAnalysisResult(org=org, repos=results, failed=failed)
