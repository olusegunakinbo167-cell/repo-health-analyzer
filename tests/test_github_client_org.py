"""Tests for github_client.list_org_repos."""

import pytest
import respx
from httpx import Response

from src.github_client import GitHubClient
from src.models import OrgRepoInfo


def _repo_payload(
    full_name: str,
    stars: int = 0,
    fork: bool = False,
    archived: bool = False,
    language: str | None = "Python",
) -> dict:
    owner, name = full_name.split("/", 1)
    return {
        "full_name": full_name,
        "name": name,
        "description": f"Test repo {name}",
        "stargazers_count": stars,
        "language": language,
        "fork": fork,
        "archived": archived,
        "default_branch": "main",
        "html_url": f"https://github.com/{full_name}",
    }


@pytest.mark.asyncio
async def test_list_org_repos_pagination_and_filtering() -> None:
    """Paginated org repos, filters forks/archived, sorts by stars desc."""
    async with GitHubClient(token="test-token") as client:
        with respx.mock(base_url="https://api.github.com") as mock:
            # Page 1 with Link header pointing to page 2
            mock.get("/orgs/testorg/repos", params__contains={"page": 1}).mock(
                return_value=Response(
                    200,
                    json=[
                        _repo_payload("testorg/repo-a", stars=50, fork=False),
                        _repo_payload("testorg/repo-b", stars=10, fork=True),
                    ],
                    headers={
                        "Link": '<https://api.github.com/orgs/testorg/repos?page=2>; rel="next", '
                        '<https://api.github.com/orgs/testorg/repos?page=2>; rel="last"'
                    },
                )
            )
            # Page 2, last page (no Link header)
            mock.get("/orgs/testorg/repos", params__contains={"page": 2}).mock(
                return_value=Response(
                    200,
                    json=[
                        _repo_payload("testorg/repo-c", stars=100, fork=False),
                        _repo_payload("testorg/repo-d", stars=5, archived=True),
                    ],
                )
            )

            repos = await client.list_org_repos(
                "testorg", include_forks=False, include_archived=False
            )

            # forked repo-b and archived repo-d should be filtered out
            # remaining: repo-c (100 stars), repo-a (50 stars), sorted desc
            assert len(repos) == 2
            assert all(isinstance(r, OrgRepoInfo) for r in repos)
            assert repos[0].full_name == "testorg/repo-c"
            assert repos[0].stars == 100
            assert repos[1].full_name == "testorg/repo-a"
            assert repos[1].stars == 50


@pytest.mark.asyncio
async def test_list_org_repos_user_fallback() -> None:
    """404 on /orgs/{x}/repos falls back to /users/{x}/repos."""
    async with GitHubClient(token="test-token") as client:
        with respx.mock(base_url="https://api.github.com") as mock:
            # Org endpoint 404s
            mock.get("/orgs/someuser/repos").mock(return_value=Response(404, json={}))
            # User endpoint succeeds
            mock.get("/users/someuser/repos").mock(
                return_value=Response(
                    200,
                    json=[_repo_payload("someuser/myrepo", stars=7)],
                )
            )

            repos = await client.list_org_repos("someuser")
            assert len(repos) == 1
            assert repos[0].full_name == "someuser/myrepo"
            assert repos[0].stars == 7


@pytest.mark.asyncio
async def test_list_org_repos_include_forks_and_archived() -> None:
    """include_forks/include_archived flags control filtering."""
    async with GitHubClient(token="test-token") as client:
        with respx.mock(base_url="https://api.github.com") as mock:
            mock.get("/orgs/testorg/repos").mock(
                return_value=Response(
                    200,
                    json=[
                        _repo_payload("testorg/normal", stars=10),
                        _repo_payload("testorg/forked", stars=20, fork=True),
                        _repo_payload("testorg/old", stars=30, archived=True),
                    ],
                )
            )

            # Default: exclude forks and archived
            repos = await client.list_org_repos("testorg")
            assert [r.full_name for r in repos] == ["testorg/normal"]

            # Include forks
            repos = await client.list_org_repos("testorg", include_forks=True)
            full_names = {r.full_name for r in repos}
            assert full_names == {"testorg/normal", "testorg/forked"}

            # Include both
            repos = await client.list_org_repos(
                "testorg", include_forks=True, include_archived=True
            )
            full_names = {r.full_name for r in repos}
            assert full_names == {"testorg/normal", "testorg/forked", "testorg/old"}


@pytest.mark.asyncio
async def test_list_org_repos_min_stars() -> None:
    """min_stars filters out low-star repos."""
    async with GitHubClient(token="test-token") as client:
        with respx.mock(base_url="https://api.github.com") as mock:
            mock.get("/orgs/testorg/repos").mock(
                return_value=Response(
                    200,
                    json=[
                        _repo_payload("testorg/popular", stars=100),
                        _repo_payload("testorg/meh", stars=5),
                        _repo_payload("testorg/new", stars=0),
                    ],
                )
            )

            repos = await client.list_org_repos("testorg", min_stars=10)
            assert len(repos) == 1
            assert repos[0].full_name == "testorg/popular"


@pytest.mark.asyncio
async def test_list_org_repos_not_found_both_endpoints() -> None:
    """404 on both org and user endpoints raises HTTPStatusError."""
    import httpx

    async with GitHubClient(token="test-token") as client:
        with respx.mock(base_url="https://api.github.com") as mock:
            mock.get("/orgs/nope/repos").mock(return_value=Response(404, json={}))
            mock.get("/users/nope/repos").mock(return_value=Response(404, json={}))

            with pytest.raises(httpx.HTTPStatusError, match="not found"):
                await client.list_org_repos("nope")


@pytest.mark.asyncio
async def test_parse_link_header() -> None:
    """Link header parser extracts rel → url mapping correctly."""
    async with GitHubClient(token="test-token") as client:
        header = (
            '<https://api.github.com/orgs/x/repos?page=2>; rel="next", '
            '<https://api.github.com/orgs/x/repos?page=5>; rel="last"'
        )
        links = client._parse_link_header(header)
        assert links["next"] == "https://api.github.com/orgs/x/repos?page=2"
        assert links["last"] == "https://api.github.com/orgs/x/repos?page=5"

        # Empty / None
        assert client._parse_link_header(None) == {}
        assert client._parse_link_header("") == {}
