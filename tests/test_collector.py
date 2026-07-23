"""Tests for the repository health collector."""

from datetime import UTC, datetime, timedelta

import pytest
import respx
from httpx import Response

from src.collector import RepoCollector
from src.github_client import GitHubClient
from src.models import CiCdSetup, CommunityFiles, MaintenanceActivity


@pytest.mark.asyncio
async def test_check_community_files_all_present() -> None:
    async with GitHubClient(token="test") as client:
        with respx.mock(base_url="https://api.github.com") as mock:
            # README found on first try
            mock.get("/repos/o/r/contents/README").mock(return_value=Response(200, json={}))
            # LICENSE found
            mock.get("/repos/o/r/contents/LICENSE").mock(return_value=Response(200, json={}))
            # CONTRIBUTING found
            mock.get("/repos/o/r/contents/CONTRIBUTING.md").mock(
                return_value=Response(200, json={})
            )
            # CODE_OF_CONDUCT found
            mock.get("/repos/o/r/contents/CODE_OF_CONDUCT.md").mock(
                return_value=Response(200, json={})
            )

            cf = await client.check_community_files("o", "r")
            assert isinstance(cf, CommunityFiles)
            assert cf.readme is True
            assert cf.license is True
            assert cf.contributing is True
            assert cf.code_of_conduct is True
            assert cf.score == 4


@pytest.mark.asyncio
async def test_check_community_files_missing() -> None:
    async with GitHubClient(token="test") as client:
        with respx.mock(base_url="https://api.github.com") as mock:
            # README variants all 404
            for name in ["README", "README.md", "README.rst", "readme.md", "Readme.md"]:
                mock.get(f"/repos/o/r/contents/{name}").mock(return_value=Response(404, json={}))
            # LICENSE variants all 404
            for name in [
                "LICENSE",
                "LICENSE.md",
                "LICENSE.txt",
                "license",
                "license.md",
            ]:
                mock.get(f"/repos/o/r/contents/{name}").mock(return_value=Response(404, json={}))
            # CONTRIBUTING / CoC 404
            mock.get("/repos/o/r/contents/CONTRIBUTING.md").mock(
                return_value=Response(404, json={})
            )
            mock.get("/repos/o/r/contents/CODE_OF_CONDUCT.md").mock(
                return_value=Response(404, json={})
            )

            cf = await client.check_community_files("o", "r")
            assert cf.score == 0
            assert not cf.readme
            assert not cf.license
            assert not cf.contributing
            assert not cf.code_of_conduct


@pytest.mark.asyncio
async def test_check_ci_cd_with_workflows() -> None:
    async with GitHubClient(token="test") as client:
        with respx.mock(base_url="https://api.github.com") as mock:
            mock.get("/repos/o/r/contents/.github/workflows").mock(
                return_value=Response(
                    200,
                    json=[
                        {"name": "ci.yml", "type": "file"},
                        {"name": "release.yaml", "type": "file"},
                        {"name": "README.md", "type": "file"},
                    ],
                )
            )
            ci = await client.check_ci_cd("o", "r")
            assert isinstance(ci, CiCdSetup)
            assert ci.workflow_count == 2
            assert ci.has_ci is True
            assert ci.workflow_files == ["ci.yml", "release.yaml"]


@pytest.mark.asyncio
async def test_check_ci_cd_no_workflows() -> None:
    async with GitHubClient(token="test") as client:
        with respx.mock(base_url="https://api.github.com") as mock:
            mock.get("/repos/o/r/contents/.github/workflows").mock(
                return_value=Response(404, json={})
            )
            ci = await client.check_ci_cd("o", "r")
            assert ci.workflow_count == 0
            assert ci.has_ci is False
            assert ci.workflow_files == []


@pytest.mark.asyncio
async def test_get_commits_last_90_days() -> None:
    async with GitHubClient(token="test") as client:
        with respx.mock(base_url="https://api.github.com") as mock:
            mock.get("/repos/o/r/commits").mock(
                return_value=Response(200, json=[{}, {}, {}])
            )
            count = await client.get_commits_last_90_days("o", "r")
            assert count == 3


@pytest.mark.asyncio
async def test_get_issue_counts() -> None:
    async with GitHubClient(token="test") as client:
        with respx.mock(base_url="https://api.github.com") as mock:
            mock.get("/repos/o/r").mock(
                return_value=Response(200, json={"open_issues_count": 12})
            )
            mock.get("/search/issues").mock(
                return_value=Response(200, json={"total_count": 88})
            )
            open_issues, closed_issues = await client.get_issue_counts("o", "r")
            assert open_issues == 12
            assert closed_issues == 88


@pytest.mark.asyncio
async def test_get_stale_pr_count() -> None:
    now = datetime.now(UTC)
    old_date = (now - timedelta(days=45)).strftime("%Y-%m-%dT%H:%M:%SZ")
    recent_date = (now - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")

    async with GitHubClient(token="test") as client:
        with respx.mock(base_url="https://api.github.com") as mock:
            mock.get("/repos/o/r/pulls").mock(
                return_value=Response(
                    200,
                    json=[
                        {"created_at": old_date},
                        {"created_at": recent_date},
                        {"created_at": old_date},
                    ],
                )
            )
            stale = await client.get_stale_pr_count("o", "r", stale_days=30)
            assert stale == 2


@pytest.mark.asyncio
async def test_get_maintenance_activity() -> None:
    now = datetime.now(UTC)
    old_date = (now - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ")

    async with GitHubClient(token="test") as client:
        with respx.mock(base_url="https://api.github.com") as mock:
            mock.get("/repos/o/r/commits").mock(
                return_value=Response(200, json=[{}, {}])
            )
            mock.get("/repos/o/r").mock(
                return_value=Response(200, json={"open_issues_count": 5})
            )
            mock.get("/search/issues").mock(
                return_value=Response(200, json={"total_count": 15})
            )
            mock.get("/repos/o/r/pulls").mock(
                return_value=Response(200, json=[{"created_at": old_date}])
            )

            maint = await client.get_maintenance_activity("o", "r")
            assert isinstance(maint, MaintenanceActivity)
            assert maint.commits_last_90_days == 2
            assert maint.open_issues == 5
            assert maint.closed_issues == 15
            assert maint.stale_prs == 1
            assert maint.issue_close_ratio == pytest.approx(0.75)


@pytest.mark.asyncio
async def test_collector_collect_full() -> None:
    now = datetime.now(UTC)
    recent_date = (now - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")

    async with GitHubClient(token="test") as client:
        collector = RepoCollector(client=client)
        with respx.mock(base_url="https://api.github.com") as mock:
            # get_repo
            mock.get("/repos/o/r").mock(
                return_value=Response(
                    200,
                    json={
                        "full_name": "o/r",
                        "description": "Test",
                        "stargazers_count": 10,
                        "language": "Python",
                        "default_branch": "main",
                        "open_issues_count": 3,
                    },
                )
            )
            # community files
            mock.get("/repos/o/r/contents/README").mock(return_value=Response(200, json={}))
            mock.get("/repos/o/r/contents/LICENSE").mock(return_value=Response(200, json={}))
            mock.get("/repos/o/r/contents/CONTRIBUTING.md").mock(
                return_value=Response(404, json={})
            )
            mock.get("/repos/o/r/contents/CODE_OF_CONDUCT.md").mock(
                return_value=Response(404, json={})
            )
            # CI/CD
            mock.get("/repos/o/r/contents/.github/workflows").mock(
                return_value=Response(
                    200, json=[{"name": "test.yml", "type": "file"}]
                )
            )
            # commits
            mock.get("/repos/o/r/commits").mock(
                return_value=Response(200, json=[{}, {}, {}, {}])
            )
            # issue search
            mock.get("/search/issues").mock(
                return_value=Response(200, json={"total_count": 7})
            )
            # PRs
            mock.get("/repos/o/r/pulls").mock(
                return_value=Response(200, json=[{"created_at": recent_date}])
            )

            metrics = await collector.collect("o", "r")
            assert metrics.full_name == "o/r"
            assert metrics.stars == 10
            assert metrics.community_files.readme is True
            assert metrics.community_files.license is True
            assert metrics.community_files.contributing is False
            assert metrics.ci_cd.has_ci is True
            assert metrics.ci_cd.workflow_count == 1
            assert metrics.maintenance.commits_last_90_days == 4
            assert metrics.maintenance.open_issues == 3
            assert metrics.maintenance.closed_issues == 7
            assert metrics.maintenance.stale_prs == 0
