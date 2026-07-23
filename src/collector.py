"""Repository health data collector."""

from __future__ import annotations

from .github_client import GitHubClient
from .models import RepoMetrics


class RepoCollector:
    """Orchestrates collection of repository health metrics."""

    def __init__(self, client: GitHubClient | None = None, token: str | None = None):
        self._client = client
        self._token = token
        self._owns_client = client is None

    async def __aenter__(self) -> RepoCollector:
        if self._client is None:
            self._client = GitHubClient(token=self._token)
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.close()

    async def collect(self, owner: str, repo: str) -> RepoMetrics:
        """Collect full repository health metrics.

        Args:
            owner: Repository owner.
            repo: Repository name.

        Returns:
            RepoMetrics with community files, CI/CD, and maintenance activity.
        """
        if self._client is None:
            raise RuntimeError("Collector must be used as an async context manager")

        # Base metadata
        meta = await self._client.get_repo(owner, repo)

        # Community files
        community = await self._client.check_community_files(owner, repo)

        # CI/CD
        ci_cd = await self._client.check_ci_cd(owner, repo)

        # Maintenance
        maintenance = await self._client.get_maintenance_activity(owner, repo)

        return RepoMetrics(
            full_name=meta.full_name,
            description=meta.description,
            stars=meta.stars,
            language=meta.language,
            default_branch=meta.default_branch,
            community_files=community,
            ci_cd=ci_cd,
            maintenance=maintenance,
        )

    async def collect_by_full_name(self, full_name: str) -> RepoMetrics:
        """Collect metrics by full repository name (owner/repo)."""
        if "/" not in full_name:
            raise ValueError(f"Repository must be in 'owner/repo' format, got: {full_name!r}")
        owner, repo = full_name.split("/", 1)
        return await self.collect(owner, repo)
