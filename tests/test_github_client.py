"""Tests for github_client."""

import pytest
import respx
from httpx import Response

from src.github_client import GitHubClient, RateLimitInfo, RepoMetadata


@pytest.mark.asyncio
async def test_get_rate_limit() -> None:
    async with GitHubClient(token="test-token") as client:
        with respx.mock(base_url="https://api.github.com") as mock:
            mock.get("/rate_limit").mock(
                return_value=Response(
                    200,
                    json={
                        "resources": {
                            "core": {
                                "limit": 5000,
                                "remaining": 4999,
                                "reset": 1720000000,
                                "used": 1,
                            }
                        }
                    },
                )
            )
            rl = await client.get_rate_limit()
            assert isinstance(rl, RateLimitInfo)
            assert rl.limit == 5000
            assert rl.remaining == 4999
            assert rl.reset == 1720000000
            assert rl.used == 1


@pytest.mark.asyncio
async def test_get_repo() -> None:
    async with GitHubClient(token="test-token") as client:
        with respx.mock(base_url="https://api.github.com") as mock:
            mock.get("/repos/octocat/Hello-World").mock(
                return_value=Response(
                    200,
                    json={
                        "full_name": "octocat/Hello-World",
                        "description": "Test repo",
                        "stargazers_count": 42,
                        "language": "Python",
                        "default_branch": "main",
                    },
                )
            )
            repo = await client.get_repo("octocat", "Hello-World")
            assert isinstance(repo, RepoMetadata)
            assert repo.full_name == "octocat/Hello-World"
            assert repo.description == "Test repo"
            assert repo.stars == 42
            assert repo.language == "Python"
            assert repo.default_branch == "main"


@pytest.mark.asyncio
async def test_get_repo_by_full_name_invalid() -> None:
    async with GitHubClient(token="test-token") as client:
        with pytest.raises(ValueError, match="owner/repo"):
            await client.get_repo_by_full_name("invalid-format")
