"""CLI entrypoint for repo-health-analyzer."""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import os
import sys
from pathlib import Path
from typing import Any

from rich.console import Console

from .collector import RepoCollector
from .github_client import GitHubClient
from .models import HealthScore, RepoMetrics
from .reporter import render_markdown, render_rich
from .scorer import score_repo


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
    parser.add_argument(
        "--markdown",
        metavar="PATH",
        type=Path,
        default=None,
        help="Write a GitHub-flavored Markdown report to PATH "
        "(suitable for $GITHUB_STEP_SUMMARY or PR comments)",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable Rich color output in terminal",
    )
    return parser.parse_args(argv)


async def run(repository: str, token: str | None) -> dict[str, Any]:
    """Collect repository metrics, score them, and return full payload.

    Returns a dict with serializable data plus live objects under
    '_metrics_obj' and '_health_obj' for in-process rendering.
    """
    resolved_token = token or os.getenv("GITHUB_TOKEN")

    async with GitHubClient(token=resolved_token) as gh_client:
        rate_limit = await gh_client.get_rate_limit()
        collector = RepoCollector(client=gh_client)
        metrics = await collector.collect_by_full_name(repository)

    health_score = score_repo(metrics)

    return {
        "repository": {
            "full_name": metrics.full_name,
            "description": metrics.description,
            "stars": metrics.stars,
            "language": metrics.language,
            "default_branch": metrics.default_branch,
        },
        "metrics": dataclasses.asdict(metrics),
        "health_score": dataclasses.asdict(health_score),
        "rate_limit": {
            "limit": rate_limit.limit,
            "remaining": rate_limit.remaining,
            "reset": rate_limit.reset,
            "used": rate_limit.used,
        },
        # Live objects for reporter (stripped before JSON output)
        "_metrics_obj": metrics,
        "_health_obj": health_score,
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

    # Extract live objects for rendering
    metrics: RepoMetrics = result.pop("_metrics_obj")  # type: ignore[assignment]
    health: HealthScore = result.pop("_health_obj")  # type: ignore[assignment]

    # --markdown output
    if args.markdown:
        md = render_markdown(metrics, health)
        try:
            args.markdown.write_text(md, encoding="utf-8")
        except Exception as exc:
            print(f"Error writing markdown report: {exc}", file=sys.stderr)
            return 1
        # If --markdown was the only output requested (no --json),
        # also print a short confirmation to stderr so CI logs are clear
        if not args.json:
            print(f"Wrote Markdown report to {args.markdown}", file=sys.stderr)

    # --json output (do this after markdown so live objects are stripped)
    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    # Default: Rich terminal output (unless --markdown was used without --json,
    # in which case we still print the terminal report)
    output = render_rich(metrics, health)
    console = Console(no_color=args.no_color)
    console.print(output, end="")

    rl = result["rate_limit"]
    console.print(f"Rate limit: {rl['remaining']}/{rl['limit']} remaining\n", style="dim")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
