"""CLI entrypoint for repo-health-analyzer."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any

from .github_client import GitHubClient


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="repo-health-analyzer",
        description="Analyze GitHub repository health metrics.",
    )
    parser.add_argument(
        "repository",
        help="Target repository in owner/repo format (e.g. 'octocat/Hello-World')",
    )
    parser.add_argument(
        "--token",
        dest="token",
        default=None,
        help="GitHub personal access token (default: GITHUB_TOKEN env var)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )
    return parser.parse_args(argv)


async def run(repository: str, token: str | None) -> dict[str, Any]:
    """Fetch repository metadata and rate limit info."""
    resolved_token = token or os.getenv("GITHUB_TOKEN")
    async with GitHubClient(token=resolved_token) as client:
        rate_limit = await client.get_rate_limit()
        repo = await client.get_repo_by_full_name(repository)
        return {
            "repository": {
                "full_name": repo.full_name,
                "description": repo.description,
                "stars": repo.stars,
                "language": repo.language,
                "default_branch": repo.default_branch,
            },
            "rate_limit": {
                "limit": rate_limit.limit,
                "remaining": rate_limit.remaining,
                "reset": rate_limit.reset,
                "used": rate_limit.used,
            },
        }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        result = asyncio.run(run(args.repository, args.token))
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        repo = result["repository"]
        rl = result["rate_limit"]
        print(f"Repository: {repo['full_name']}")
        print(f"  Description:    {repo['description'] or '(none)'}")
        print(f"  Stars:          {repo['stars']}")
        print(f"  Language:       {repo['language'] or '(unknown)'}")
        print(f"  Default branch: {repo['default_branch']}")
        print()
        print(f"Rate limit: {rl['remaining']}/{rl['limit']} remaining")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
