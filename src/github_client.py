"""Async GitHub API wrapper using httpx."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

GITHUB_API_BASE = "https://api.github.com"


@dataclass
class RepoMetadata:
    """Repository metadata from the GitHub API."""

    full_name: str
    description: str | None
    stars: int
    language: str | None
    default_branch: str


@dataclass
class RateLimitInfo:
    """GitHub API rate limit status."""

    limit: int
    remaining: int
    reset: int
    used: int


class GitHubClient:
    """Async GitHub API client."""

    def __init__(
        self, token: str | None = None, timeout: float = 30.0, trust_env: bool = False
    ) -> None:
        self.token = token or os.getenv("GITHUB_TOKEN")
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "repo-health-analyzer/0.1.0",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        self._client = httpx.AsyncClient(
            base_url=GITHUB_API_BASE,
            headers=headers,
            timeout=timeout,
            follow_redirects=True,
            trust_env=trust_env,
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> GitHubClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    async def get_rate_limit(self) -> RateLimitInfo:
        """Fetch current API rate limit status.

        Returns:
            RateLimitInfo with limit, remaining, reset timestamp, and used count.
        """
        resp = await self._client.get("/rate_limit")
        resp.raise_for_status()
        data = resp.json()
        core = data["resources"]["core"]
        return RateLimitInfo(
            limit=core["limit"],
            remaining=core["remaining"],
            reset=core["reset"],
            used=core["used"],
        )

    async def get_repo(self, owner: str, repo: str) -> RepoMetadata:
        """Fetch basic repository metadata.

        Args:
            owner: Repository owner / organization.
            repo: Repository name.

        Returns:
            RepoMetadata containing description, stars, language, and default branch.

        Raises:
            httpx.HTTPStatusError: If the repository is not found or API request fails.
        """
        resp = await self._client.get(f"/repos/{owner}/{repo}")
        resp.raise_for_status()
        data = resp.json()
        return RepoMetadata(
            full_name=data["full_name"],
            description=data.get("description"),
            stars=data["stargazers_count"],
            language=data.get("language"),
            default_branch=data["default_branch"],
        )

    async def get_repo_by_full_name(self, full_name: str) -> RepoMetadata:
        """Fetch repository metadata by full name (owner/repo).

        Args:
            full_name: Repository in "owner/repo" format.

        Returns:
            RepoMetadata for the repository.
        """
        if "/" not in full_name:
            raise ValueError(f"Repository must be in 'owner/repo' format, got: {full_name!r}")
        owner, repo = full_name.split("/", 1)
        return await self.get_repo(owner, repo)
