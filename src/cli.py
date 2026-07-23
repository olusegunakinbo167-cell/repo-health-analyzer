"""CLI entrypoint for repo-health-analyzer."""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import os
import sys
from typing import Any

from .collector import RepoCollector
from .github_client import GitHubClient
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
    return parser.parse_args(argv)


async def run(repository: str, token: str | None) -> dict[str, Any]:
    """Collect repository metrics, score them, and return full payload."""
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
        return 0

    # Text output
    repo = result["repository"]
    hs = result["health_score"]
    metrics = result["metrics"]

    print(f"\nHealth Report for {repo['full_name']}")
    print("=" * 60)
    print(f"Description:    {repo['description'] or '(none)'}")
    print(f"Stars:          {repo['stars']}")
    print(f"Language:       {repo['language'] or '(unknown)'}")
    print(f"Default branch: {repo['default_branch']}")
    print()
    grade = _grade(hs["total_score"])
    print(f"Overall Health Score: {hs['total_score']:.1f} / 100  (Grade: {grade})")
    print()

    for key in ("documentation", "maintenance", "ci_cd", "governance"):
        cat = hs[key]
        print(f"{cat['name']:<18} {cat['score']:>5.1f} / {cat['max_score']:.0f}")
        if cat["penalties"]:
            for p in cat["penalties"]:
                print(f"  ⚠ {p}")
        print()

    # Recommendations
    all_recs: list[str] = []
    for key in ("documentation", "maintenance", "ci_cd", "governance"):
        all_recs.extend(hs[key]["recommendations"])

    if all_recs:
        # Deduplicate while preserving order
        seen: set[str] = set()
        unique_recs: list[str] = []
        for r in all_recs:
            if r not in seen:
                seen.add(r)
                unique_recs.append(r)
        print("Recommendations:")
        for i, rec in enumerate(unique_recs, 1):
            print(f"  {i}. {rec}")
        print()

    # Raw metrics summary
    cf = metrics["community_files"]
    ci = metrics["ci_cd"]
    maint = metrics["maintenance"]
    print("Metrics snapshot:")
    print(
        f"  Community files: README={cf['readme']}, LICENSE={cf['license']}, "
        f"CONTRIBUTING={cf['contributing']}, CoC={cf['code_of_conduct']}"
    )
    workflows = ", ".join(ci["workflow_files"]) or "(none)"
    print(f"  CI/CD: {ci['workflow_count']} workflow(s) — {workflows}")
    print(
        f"  Maintenance: {maint['commits_last_90_days']} commits/90d, "
        f"issues {maint['open_issues']} open / {maint['closed_issues']} closed, "
        f"{maint['stale_prs']} stale PR(s)"
    )
    print()

    rl = result["rate_limit"]
    print(f"Rate limit: {rl['remaining']}/{rl['limit']} remaining")
    print()
    return 0


def _grade(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


if __name__ == "__main__":
    raise SystemExit(main())
