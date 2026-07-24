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
from .config import RepoConfig, fetch_remote_config, load_config
from .github_client import GitHubClient
from .models import BaselineDiff, CategoryScore, HealthScore, RepoMetrics
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
        "--s2-api-key",
        dest="s2_api_key",
        default=None,
        help="Semantic Scholar API key for academic impact metrics "
        "(default: S2_API_KEY / SEMANTIC_SCHOLAR_API_KEY env var)",
    )
    parser.add_argument(
        "--skip-academic",
        action="store_true",
        help="Skip academic impact / paper reference scanning (faster, no S2 API calls)",
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
        "--config",
        metavar="PATH",
        type=Path,
        default=None,
        help="Path to local .repo-health.yml config file "
        "(default: auto-fetch from target repo root)",
    )
    parser.add_argument(
        "--baseline",
        metavar="PATH",
        type=Path,
        default=None,
        help="Path to a prior artifact JSON to compare against — "
        "category score deltas are shown in terminal and Markdown output",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable Rich color output in terminal",
    )
    return parser.parse_args(argv)


async def run(
    repository: str,
    token: str | None,
    config_path: Path | None = None,
    s2_api_key: str | None = None,
    skip_academic: bool = False,
) -> dict[str, Any]:
    """Collect repository metrics, score them, and return full payload.

    Returns a dict with serializable data plus live objects under
    '_metrics_obj', '_health_obj', and '_config_obj' for in-process rendering.
    """
    resolved_token = token or os.getenv("GITHUB_TOKEN")

    # Parse repository owner/name for config fetching
    if "/" not in repository:
        raise ValueError(f"Repository must be in 'owner/repo' format, got: {repository!r}")
    owner, repo_name = repository.split("/", 1)

    # Load config: explicit --config path, else try to fetch .repo-health.yml from target repo
    if config_path and config_path.exists():
        config = load_config(config_path)
    else:
        # Auto-fetch from target repo root
        try:
            config = await fetch_remote_config(owner, repo_name, token=resolved_token)
        except Exception:
            config = RepoConfig()

    async with GitHubClient(token=resolved_token) as gh_client:
        rate_limit = await gh_client.get_rate_limit()
        collector = RepoCollector(
            client=gh_client,
            s2_api_key=s2_api_key,
            skip_academic_impact=skip_academic,
        )
        metrics = await collector.collect_by_full_name(repository)

    health_score = score_repo(metrics, config=config)

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
        "config": {
            "weights": config.weights,
            "ignore_rules": sorted(config.ignore_rules),
        },
        "rate_limit": {
            "limit": rate_limit.limit,
            "remaining": rate_limit.remaining,
            "reset": rate_limit.reset,
            "used": rate_limit.used,
        },
        # Live objects for reporter (stripped before JSON output)
        "_metrics_obj": metrics,
        "_health_obj": health_score,
        "_config_obj": config,
    }


def load_baseline_health_score(path: Path) -> tuple[HealthScore, str | None, str | None]:
    """Load a HealthScore from a prior artifact JSON.

    Returns (health_score, commit_sha, timestamp).
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    # Artifact files have top-level health_score, metrics, repository, timestamp
    hs_data = data.get("health_score", {})
    repo_data = data.get("repository", {})
    timestamp = data.get("timestamp")

    def load_cat(key: str) -> CategoryScore:
        c = hs_data.get(key, {})
        return CategoryScore(
            name=c.get("name", key.title()),
            score=float(c.get("score", 0.0)),
            max_score=float(c.get("max_score", 25.0)),
            penalties=list(c.get("penalties", [])),
            recommendations=list(c.get("recommendations", [])),
        )

    health = HealthScore(
        total_score=float(hs_data.get("total_score", 0.0)),
        documentation=load_cat("documentation"),
        maintenance=load_cat("maintenance"),
        ci_cd=load_cat("ci_cd"),
        governance=load_cat("governance"),
    )
    commit_sha = repo_data.get("commit_sha")
    return health, commit_sha, timestamp


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        result = asyncio.run(
            run(
                args.repository,
                args.token,
                args.config,
                s2_api_key=getattr(args, "s2_api_key", None),
                skip_academic=getattr(args, "skip_academic", False),
            )
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    # Extract live objects for rendering
    metrics: RepoMetrics = result.pop("_metrics_obj")  # type: ignore[assignment]
    health: HealthScore = result.pop("_health_obj")  # type: ignore[assignment]
    config: RepoConfig = result.pop("_config_obj", None) or RepoConfig()  # type: ignore[assignment]

    # Load baseline if requested
    baseline_diff: BaselineDiff | None = None
    if args.baseline:
        try:
            baseline_health, baseline_commit, baseline_ts = load_baseline_health_score(
                args.baseline
            )
            baseline_diff = BaselineDiff.compare(
                health,
                baseline_health,
                baseline_commit=baseline_commit,
                baseline_timestamp=baseline_ts,
            )
            # Include baseline in result JSON
            result["baseline"] = {
                "score": baseline_diff.baseline_score,
                "delta": baseline_diff.delta,
                "commit_sha": baseline_diff.baseline_commit,
                "timestamp": baseline_diff.baseline_timestamp,
            }
        except Exception as exc:
            print(f"Warning: could not load baseline: {exc}", file=sys.stderr)

    # --save-artifact: write run telemetry JSON
    if args.save_artifact:
        artifact = {
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "repository": result["repository"],
            "metrics": result["metrics"],
            "health_score": result["health_score"],
            "config": result["config"],
            "tool_version": "0.1.0",
        }
        if baseline_diff:
            artifact["baseline"] = result.get("baseline")
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
        md = render_markdown(metrics, health, baseline_diff=baseline_diff)
        try:
            # If the path matches $GITHUB_STEP_SUMMARY, append
            if str(args.markdown) == os.getenv("GITHUB_STEP_SUMMARY", ""):
                with args.markdown.open("a", encoding="utf-8") as f:
                    f.write(md + "\n")
            else:
                args.markdown.parent.mkdir(parents=True, exist_ok=True)
                args.markdown.write_text(md, encoding="utf-8")
        except Exception as exc:
            print(f"Error writing markdown report: {exc}", file=sys.stderr)
            return 1
        # Confirmation to stderr if markdown was sole output
        if not args.json and not args.save_artifact:
            print(f"Wrote Markdown report to {args.markdown}", file=sys.stderr)

    # --json output
    if args.json:
        print(json.dumps(result, indent=2))
        # Continue to quality gate check — don't return early

    # Quality gate check
    # Gate is evaluated against the configured total weight sum, not fixed 100
    total_max = sum(config.weights.values())
    gate_failed = health.total_score < args.min_score * (total_max / 100.0)
    if gate_failed:
        gate_msg = (
            f"Quality gate FAILED: score {health.total_score:.1f} "
            f"is below threshold {args.min_score:.1f}"
        )
    else:
        gate_msg = None

    # Terminal output
    show_terminal = not args.json or gate_failed or args.markdown or args.save_artifact
    if show_terminal and not args.json:
        output = render_rich(metrics, health, baseline_diff=baseline_diff)
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
