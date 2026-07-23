"""CLI entrypoint for repo-health-analyzer."""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import os
import sys
from datetime import UTC, datetime
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
        "--min-score",
        type=float,
        default=70.0,
        help="Quality gate threshold — exit with code 1 if health score is below this "
        "(default: 70.0)",
    )
    parser.add_argument(
        "--save-artifact",
        metavar="PATH",
        type=Path,
        default=None,
        help="Save complete run metadata (metrics, health_score, timestamp, repo SHA) "
        "to a JSON file",
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
            "commit_sha": metrics.commit_sha,
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

    # --save-artifact: write run telemetry JSON
    if args.save_artifact:
        artifact = {
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "repository": result["repository"],
            "metrics": result["metrics"],
            "health_score": result["health_score"],
            "tool_version": "0.1.0",
        }
        try:
            args.save_artifact.parent.mkdir(parents=True, exist_ok=True)
            args.save_artifact.write_text(
                json.dumps(artifact, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            print(f"Error writing artifact: {exc}", file=sys.stderr)
            return 1

    # --markdown output
    if args.markdown:
        md = render_markdown(metrics, health)
        try:
            # If the path is a directory or ends with a separator, or
            # GITHUB_STEP_SUMMARY env var points to it, append to it
            # (GitHub Actions $GITHUB_STEP_SUMMARY is a file to append to)
            if str(args.markdown) == os.getenv("GITHUB_STEP_SUMMARY", ""):
                with args.markdown.open("a", encoding="utf-8") as f:
                    f.write(md + "\n")
            else:
                args.markdown.parent.mkdir(parents=True, exist_ok=True)
                args.markdown.write_text(md, encoding="utf-8")
        except Exception as exc:
            print(f"Error writing markdown report: {exc}", file=sys.stderr)
            return 1
        # If --markdown was the only output requested (no --json),
        # also print a short confirmation to stderr so CI logs are clear
        if not args.json and not args.save_artifact:
            print(f"Wrote Markdown report to {args.markdown}", file=sys.stderr)

    # --json output
    if args.json:
        print(json.dumps(result, indent=2))
        # Continue to quality gate check — don't return early

    # Quality gate check
    gate_failed = health.total_score < args.min_score
    if gate_failed:
        gate_msg = (
            f"Quality gate FAILED: score {health.total_score:.1f} "
            f"is below threshold {args.min_score:.1f}"
        )
    else:
        gate_msg = None

    # Terminal output (skip if --json was the only output and gate passed)
    # Always show terminal output unless --json was explicitly requested alone
    show_terminal = not args.json or gate_failed or args.markdown or args.save_artifact
    if show_terminal and not args.json:
        output = render_rich(metrics, health)
        console = Console(no_color=args.no_color)
        console.print(output, end="")
        rl = result["rate_limit"]
        console.print(
            f"Rate limit: {rl['remaining']}/{rl['limit']} remaining\n", style="dim"
        )

    # Quality gate failure — exit 1 after all output is done
    if gate_failed:
        console = Console(no_color=args.no_color, stderr=True)
        console.print(f"❌ {gate_msg}", style="bold red")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
