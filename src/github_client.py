"""Async GitHub API wrapper using httpx."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from .models import CiCdSetup, CommunityFiles, MaintenanceActivity

GITHUB_API_BASE = "https://api.github.com"


@dataclass
class RepoMetadata:
    """Repository metadata from the GitHub API."""

    full_name: str
    description: str | None
    stars: int
    language: str | None
    default_branch: str
    commit_sha: str | None = None


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

    # ------------------------------------------------------------------
    # Core metadata
    # ------------------------------------------------------------------

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

    async def get_head_sha(self, owner: str, repo: str, branch: str) -> str | None:
        """Get the HEAD commit SHA for a branch.

        Returns None if the branch cannot be resolved.
        """
        resp = await self._client.get(f"/repos/{owner}/{repo}/commits/{branch}")
        if resp.status_code != 200:
            return None
        data = resp.json()
        return data.get("sha")

    async def get_repo(
        self, owner: str, repo: str, include_sha: bool = False
    ) -> RepoMetadata:
        """Fetch basic repository metadata.

        Args:
            owner: Repository owner / organization.
            repo: Repository name.
            include_sha: If True, also fetch the HEAD commit SHA of the default branch.

        Returns:
            RepoMetadata containing description, stars, language, default branch, and commit SHA.

        Raises:
            httpx.HTTPStatusError: If the repository is not found or API request fails.
        """
        resp = await self._client.get(f"/repos/{owner}/{repo}")
        resp.raise_for_status()
        data = resp.json()
        default_branch = data["default_branch"]
        commit_sha: str | None = None
        if include_sha:
            commit_sha = await self.get_head_sha(owner, repo, default_branch)
        return RepoMetadata(
            full_name=data["full_name"],
            description=data.get("description"),
            stars=data["stargazers_count"],
            language=data.get("language"),
            default_branch=default_branch,
            commit_sha=commit_sha,
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

    # ------------------------------------------------------------------
    # Community files
    # ------------------------------------------------------------------

    async def _file_exists(self, owner: str, repo: str, path: str) -> bool:
        """Check if a file exists in the repository root via the contents API."""
        resp = await self._client.get(f"/repos/{owner}/{repo}/contents/{path}")
        return resp.status_code == 200

    async def check_community_files(self, owner: str, repo: str) -> CommunityFiles:
        """Verify existence of standard community health files.

        Checks for:
        - README (README, README.md, README.rst, case-insensitive)
        - LICENSE (LICENSE, LICENSE.md, LICENSE.txt)
        - CONTRIBUTING.md
        - CODE_OF_CONDUCT.md
        """
        readme_names = ["README", "README.md", "README.rst", "readme.md", "Readme.md"]
        license_names = ["LICENSE", "LICENSE.md", "LICENSE.txt", "license", "license.md"]

        readme_found = False
        for name in readme_names:
            if await self._file_exists(owner, repo, name):
                readme_found = True
                break

        license_found = False
        for name in license_names:
            if await self._file_exists(owner, repo, name):
                license_found = True
                break

        contributing_found = await self._file_exists(owner, repo, "CONTRIBUTING.md")
        coc_found = await self._file_exists(owner, repo, "CODE_OF_CONDUCT.md")

        return CommunityFiles(
            readme=readme_found,
            license=license_found,
            contributing=contributing_found,
            code_of_conduct=coc_found,
        )

    # ------------------------------------------------------------------
    # CI/CD
    # ------------------------------------------------------------------

    async def check_ci_cd(self, owner: str, repo: str) -> CiCdSetup:
        """Check for GitHub Actions workflow files in .github/workflows/.

        Returns:
            CiCdSetup with a list of workflow filenames and count.
        """
        resp = await self._client.get(f"/repos/{owner}/{repo}/contents/.github/workflows")
        if resp.status_code != 200:
            return CiCdSetup(workflow_files=[], workflow_count=0)

        entries = resp.json()
        if not isinstance(entries, list):
            return CiCdSetup(workflow_files=[], workflow_count=0)

        workflows = [
            e["name"]
            for e in entries
            if e.get("type") == "file"
            and e.get("name", "").endswith((".yml", ".yaml"))
        ]
        return CiCdSetup(workflow_files=sorted(workflows), workflow_count=len(workflows))

    # ------------------------------------------------------------------
    # Maintenance activity
    # ------------------------------------------------------------------

    async def get_commits_last_90_days(self, owner: str, repo: str) -> int:
        """Count commits in the last 90 days."""
        since = (datetime.now(UTC) - timedelta(days=90)).isoformat().replace("+00:00", "Z")
        resp = await self._client.get(
            f"/repos/{owner}/{repo}/commits",
            params={"since": since, "per_page": 100},
        )
        resp.raise_for_status()
        commits = resp.json()
        # Note: GitHub paginates at 100; for MVP we count the first page.
        # A production collector would follow Link headers.
        return len(commits) if isinstance(commits, list) else 0

    async def get_issue_counts(self, owner: str, repo: str) -> tuple[int, int]:
        """Get open and closed issue counts.

        Returns:
            (open_issues, closed_issues)
        """
        # Use the search API for counts, fallback to repo metadata
        resp = await self._client.get(f"/repos/{owner}/{repo}")
        resp.raise_for_status()
        data = resp.json()
        open_issues = data.get("open_issues_count", 0)

        # Closed count via search (issues only, exclude PRs)
        search_resp = await self._client.get(
            "/search/issues",
            params={"q": f"repo:{owner}/{repo} type:issue state:closed", "per_page": 1},
        )
        if search_resp.status_code == 200:
            closed_count = search_resp.json().get("total_count", 0)
        else:
            closed_count = 0

        return open_issues, closed_count

    async def get_stale_pr_count(
        self, owner: str, repo: str, stale_days: int = 30
    ) -> int:
        """Count open PRs older than stale_days."""
        cutoff = datetime.now(UTC) - timedelta(days=stale_days)
        resp = await self._client.get(
            f"/repos/{owner}/{repo}/pulls",
            params={"state": "open", "per_page": 100, "sort": "created", "direction": "asc"},
        )
        resp.raise_for_status()
        prs = resp.json()
        if not isinstance(prs, list):
            return 0

        stale = 0
        for pr in prs:
            created_at = pr.get("created_at")
            if not created_at:
                continue
            try:
                created = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=UTC
                )
            except ValueError:
                continue
            if created < cutoff:
                stale += 1
        return stale

    async def get_maintenance_activity(self, owner: str, repo: str) -> MaintenanceActivity:
        """Collect maintenance activity signals."""
        commits = await self.get_commits_last_90_days(owner, repo)
        open_issues, closed_issues = await self.get_issue_counts(owner, repo)
        stale_prs = await self.get_stale_pr_count(owner, repo, stale_days=30)
        return MaintenanceActivity(
            commits_last_90_days=commits,
            open_issues=open_issues,
            closed_issues=closed_issues,
            stale_prs=stale_prs,
        )
