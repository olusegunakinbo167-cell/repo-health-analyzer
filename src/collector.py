"""Repository health data collector."""

from __future__ import annotations

import os

from .github_client import GitHubClient
from .metrics.academic_impact import extract_from_files, resolve_paper_references
from .models import RepoMetrics
from .semantic_scholar_client import SemanticScholarClient, SemanticScholarAPIError


class RepoCollector:
    """Orchestrates collection of repository health metrics."""

    def __init__(
        self,
        client: GitHubClient | None = None,
        token: str | None = None,
        *,
        s2_api_key: str | None = None,
        skip_academic_impact: bool = False,
        s2_cache_path: str | None = None,
        s2_enable_cache: bool = True,
    ):
        self._client = client
        self._token = token
        self._owns_client = client is None
        self._s2_api_key = (
            s2_api_key
            or os.getenv("S2_API_KEY")
            or os.getenv("SEMANTIC_SCHOLAR_API_KEY")
        )
        self._skip_academic = skip_academic_impact or (
            os.getenv("REPO_HEALTH_SKIP_ACADEMIC", "").lower() in ("1", "true", "yes")
        )
        # Phase 4: S2 cache config
        self._s2_cache_path = s2_cache_path or os.getenv("S2_CACHE_PATH")
        self._s2_enable_cache = s2_enable_cache and os.getenv(
            "S2_DISABLE_CACHE", ""
        ).lower() not in ("1", "true", "yes")

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
        meta = await self._client.get_repo(owner, repo, include_sha=True)

        # Community files
        community = await self._client.check_community_files(owner, repo)

        # CI/CD
        ci_cd = await self._client.check_ci_cd(owner, repo)

        # Maintenance
        maintenance = await self._client.get_maintenance_activity(owner, repo)

        # Academic impact (paper references in docs)
        academic_impact = None
        if not self._skip_academic:
            try:
                doc_files = await self._client.get_documentation_text_files(owner, repo)
                if doc_files:
                    paper_refs = extract_from_files(doc_files)
                    if paper_refs:
                        # Resolve via S2 (with graceful degradation on rate limits)
                        # Phase 4: S2 response caching with 30-day TTL
                        try:
                            async with SemanticScholarClient(
                                api_key=self._s2_api_key,
                                cache_path=self._s2_cache_path,
                                enable_cache=self._s2_enable_cache,
                            ) as s2:
                                academic_impact = await resolve_paper_references(
                                    paper_refs, s2_client=s2
                                )
                        except SemanticScholarAPIError:
                            # S2 unavailable / rate limited — skip academic impact
                            # rather than failing the entire collection
                            academic_impact = None
            except Exception:
                # Never let academic impact collection break the main flow
                academic_impact = None

        return RepoMetrics(
            full_name=meta.full_name,
            description=meta.description,
            stars=meta.stars,
            language=meta.language,
            default_branch=meta.default_branch,
            commit_sha=meta.commit_sha,
            community_files=community,
            ci_cd=ci_cd,
            maintenance=maintenance,
            academic_impact=academic_impact,
        )

    async def collect_by_full_name(self, full_name: str) -> RepoMetrics:
        """Collect metrics by full repository name (owner/repo)."""
        if "/" not in full_name:
            raise ValueError(f"Repository must be in 'owner/repo' format, got: {full_name!r}")
        owner, repo = full_name.split("/", 1)
        return await self.collect(owner, repo)
