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
from rich.table import Table

from .collector import RepoCollector
from .config import RepoConfig, fetch_remote_config, load_config
from .github_client import GitHubClient
from .models import BaselineDiff, CategoryScore, HealthScore, RepoMetrics
from .reporter import render_markdown, render_rich
from .scorer import score_repo


# ── Fandango / movies subcommand ──

def _add_movies_subparsers(subparsers: argparse._SubParsersAction) -> None:
    movies = subparsers.add_parser(
        "movies",
        help="Movie showtimes, theater listings, and seat availability (via Fandango)",
        description="Movie showtimes, theater listings, and seat availability (via Fandango). "
        "Fun dev-downtime subcommand — not part of repo health scoring.",
    )
    m_sub = movies.add_subparsers(dest="movies_cmd", required=True)

    # search
    p = m_sub.add_parser("search", help="Search for movies by title")
    p.add_argument("query", help="Movie title search term")
    p.add_argument("--limit", type=int, default=20, help="Max results (default: 20)")
    p.add_argument("--json", action="store_true", help="Output raw JSON")
    p.set_defaults(func=cmd_movies_search)

    # movie-showtimes
    p = m_sub.add_parser("showtimes", help="Find showtimes for a specific movie near a location")
    p.add_argument("--movie-id", required=True, help="Fandango movie ID")
    p.add_argument("--date", required=True, help="Date YYYY-MM-DD")
    loc = p.add_mutually_exclusive_group(required=True)
    loc.add_argument("--zip", help="US ZIP code (5-digit)")
    loc.add_argument("--latlong", nargs=2, type=float, metavar=("LAT", "LONG"), help="Latitude Longitude")
    p.add_argument("--format", dest="format_filter", help="Filter by format (IMAX, 3D, Standard, …)")
    p.add_argument("--chain", dest="chain_code", help="Filter by chain code (e.g. AMC)")
    p.add_argument("--json", action="store_true", help="Output raw JSON")
    p.set_defaults(func=cmd_movies_showtimes)

    # theater-showtimes
    p = m_sub.add_parser("theater", help="List movies and showtimes at a theater")
    p.add_argument("--theater-id", required=True, help="Fandango theater ID")
    p.add_argument("--date", help="Date YYYY-MM-DD (default: today)")
    p.add_argument("--movie-id", help="Filter to a specific movie")
    p.add_argument("--format", dest="format_filter", help="Filter by format")
    p.add_argument("--json", action="store_true", help="Output raw JSON")
    p.set_defaults(func=cmd_movies_theater)

    # theater-calendar
    p = m_sub.add_parser("calendar", help="Available showtime dates for a theater")
    p.add_argument("--theater-id", required=True, help="Fandango theater ID")
    p.add_argument("--start-date", help="Start date YYYY-MM-DD")
    p.add_argument("--json", action="store_true", help="Output raw JSON")
    p.set_defaults(func=cmd_movies_calendar)

    # seat-map
    p = m_sub.add_parser("seats", help="Seat availability for a showtime")
    p.add_argument("showtime_hash", help="showtimeHashCode from showtimes output")
    p.add_argument("--render", action="store_true", help="Render a terminal seat map")
    p.add_argument("--json", action="store_true", help="Output raw JSON")
    p.set_defaults(func=cmd_movies_seats)


def cmd_movies_search(args: argparse.Namespace) -> int:
    from .metrics.fandango import search_movies

    try:
        result = search_movies(args.query, limit=args.limit)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    movies = result.get("movies", [])
    console = Console()
    console.print(f"[bold]\"{result.get('query')}\"[/bold] — {result.get('count', 0)} result(s)")
    if not movies:
        console.print("No matches in Fandango's current in-theaters / coming-soon listings.", style="dim")
        return 0
    tbl = Table(show_header=True)
    tbl.add_column("ID", style="cyan")
    tbl.add_column("Title")
    tbl.add_column("URL", style="dim")
    for m in movies:
        tbl.add_row(str(m.get("id", "?")), m.get("title", "?"), m.get("url", ""))
    console.print(tbl)
    return 0


def cmd_movies_showtimes(args: argparse.Namespace) -> int:
    from .metrics.fandango import movie_showtimes

    lat = long = None
    if args.latlong:
        lat, long = args.latlong
    try:
        result = movie_showtimes(
            movie_id=args.movie_id,
            date=args.date,
            zip_code=args.zip,
            lat=lat,
            long=long,
            format_filter=args.format_filter,
            chain_code=args.chain_code,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    console = Console()
    theaters = result.get("theaters", [])
    console.print(f"[bold]Movie {result.get('movieId')} — {result.get('date')} — {len(theaters)} theater(s)[/bold]\n")
    for th in theaters:
        name = th.get("name", "?")
        tid = th.get("id", "?")
        dist = th.get("distance")
        dist_s = f" — {dist:.1f} mi" if isinstance(dist, (int, float)) else ""
        console.print(f"[bold]{name}[/bold] ({tid}){dist_s}", style="cyan")
        addr = th.get("address")
        if addr:
            city = th.get("city", "")
            state = th.get("state", "")
            zipc = th.get("zip", "")
            console.print(f"  {addr}, {city}, {state} {zipc}".strip(" ,"), style="dim")
        for st in th.get("showtimes", []):
            t = st.get("ticketingDate") or st.get("date")
            formats = ", ".join(st.get("formats", []))
            h = st.get("showtimeHashCode", "")
            h_s = f"  [dim]hash={h[:16]}…[/dim]" if h else ""
            console.print(f"  {t}  [{formats}]{h_s}")
        console.print()
    return 0


def cmd_movies_theater(args: argparse.Namespace) -> int:
    from .metrics.fandango import theater_showtimes

    try:
        result = theater_showtimes(
            theater_id=args.theater_id,
            date=args.date,
            movie_id=args.movie_id,
            format_filter=args.format_filter,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    console = Console()
    th = result.get("theater", {})
    console.print(f"[bold]{th.get('name', '?')} ({th.get('id', '?')}) — {result.get('date', '?')}[/bold]\n")
    for m in result.get("movies", []):
        console.print(f"[bold]{m.get('title', '?')}[/bold] [dim]({m.get('id', '?')})[/dim]")
        for st in m.get("showtimes", []):
            t = st.get("ticketingDate") or st.get("date")
            formats = ", ".join(st.get("formats", []))
            h = st.get("showtimeHashCode", "")
            h_s = f"  [dim]hash={h[:16]}…[/dim]" if h else ""
            console.print(f"  {t}  [{formats}]{h_s}")
        console.print()
    return 0


def cmd_movies_calendar(args: argparse.Namespace) -> int:
    from .metrics.fandango import theater_calendar

    try:
        result = theater_calendar(args.theater_id, start_date=args.start_date)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    console = Console()
    console.print(f"[bold]Theater {args.theater_id} — calendar[/bold]")
    for d in result.get("dates", []):
        mark = " ✓" if d.get("hasShowtime") else ""
        console.print(f"  {d.get('date')}{mark}")
    return 0


def cmd_movies_seats(args: argparse.Namespace) -> int:
    from .metrics.fandango import seat_map

    try:
        result = seat_map(args.showtime_hash)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if args.json and not args.render:
        print(json.dumps(result, indent=2))
        return 0
    console = Console()
    name = result.get("theaterName") or result.get("theaterId", "?")
    avail = result.get("availableSeatCount", 0)
    total = result.get("totalSeatCount", 0)
    console.print(f"[bold]{name} — {avail}/{total} available[/bold]\n")
    if args.render:
        seats = result.get("seats", [])
        by_row: dict[str, list] = {}
        for s in seats:
            by_row.setdefault(s["row"], []).append(s)
        console.print("     SCREEN")
        console.print("  " + "─" * 40)
        for row in sorted(by_row.keys(), key=lambda x: (len(x), x)):
            row_seats = sorted(by_row[row], key=lambda s: s["column"])
            glyphs = []
            for s in row_seats:
                if s.get("isWheelchair"):
                    glyphs.append("▣" if s.get("isAvailable") else "▦")
                else:
                    glyphs.append("□" if s.get("isAvailable") else "☒")
            console.print(f"{row:>3}  {' '.join(glyphs)}")
        console.print("\n[dim]□ open   ☒ taken   ▣ open wheelchair   ▦ taken wheelchair[/dim]")
    if args.json:
        print(json.dumps(result, indent=2))
    return 0


# ── Repo health analysis ──

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="repo-health-analyzer",
        description="Analyze GitHub repository health metrics.",
    )
    subparsers = parser.add_subparsers(dest="command")

    # movies subcommand
    _add_movies_subparsers(subparsers)

    # analyze (default) — repository health check
    analyze = subparsers.add_parser(
        "analyze",
        help="Analyze a GitHub repository (default command)",
        description="Analyze GitHub repository health metrics.",
    )
    analyze.add_argument(
        "repository",
        help="Target repository in owner/repo format (e.g. 'octocat/Hello-World')",
    )
    analyze.add_argument(
        "--token",
        dest="token",
        default=None,
        help="GitHub personal access token (default: GITHUB_TOKEN env var)",
    )
    analyze.add_argument(
        "--s2-api-key",
        dest="s2_api_key",
        default=None,
        help="Semantic Scholar API key for academic impact metrics "
        "(default: S2_API_KEY / SEMANTIC_SCHOLAR_API_KEY env var)",
    )
    analyze.add_argument(
        "--skip-academic",
        action="store_true",
        help="Skip academic impact / paper reference scanning (faster, no S2 API calls)",
    )
    analyze.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )
    analyze.add_argument(
        "--markdown",
        metavar="PATH",
        type=Path,
        default=None,
        help="Write a GitHub-flavored Markdown report to PATH "
        "(suitable for $GITHUB_STEP_SUMMARY or PR comments)",
    )
    analyze.add_argument(
        "--min-score",
        type=float,
        default=70.0,
        help="Quality gate threshold — exit with code 1 if health score is below this "
        "(default: 70.0)",
    )
    analyze.add_argument(
        "--save-artifact",
        metavar="PATH",
        type=Path,
        default=None,
        help="Save complete run metadata (metrics, health_score, timestamp, repo SHA) "
        "to a JSON file",
    )
    analyze.add_argument(
        "--config",
        metavar="PATH",
        type=Path,
        default=None,
        help="Path to local .repo-health.yml config file "
        "(default: auto-fetch from target repo root)",
    )
    analyze.add_argument(
        "--baseline",
        metavar="PATH",
        type=Path,
        default=None,
        help="Path to a prior artifact JSON to compare against — "
        "category score deltas are shown in terminal and Markdown output",
    )
    analyze.add_argument(
        "--no-color",
        action="store_true",
        help="Disable Rich color output in terminal",
    )
    analyze.set_defaults(func=cmd_analyze)

    # Backwards compat: if first arg isn't a known subcommand, treat as
    # `analyze <repo> ...` — this preserves the old
    # `repo-health-analyzer owner/repo [...]` invocation, and also ensures
    # invalid repo format errors come from run() validation (not argparse),
    # matching pre-subparser behavior.
    if argv is None:
        argv = sys.argv[1:]
    if argv and not argv[0].startswith("-") and argv[0] not in ("movies", "analyze"):
        # Rewrite: repo-health-analyzer owner/repo ... → repo-health-analyzer analyze owner/repo ...
        argv = ["analyze", *argv]

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


def cmd_analyze(args: argparse.Namespace) -> int:
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
            "tool_version": "0.2.0",
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


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    # Dispatch to subcommand func if present
    if hasattr(args, "func"):
        return args.func(args)
    # No subcommand matched — show help
    parse_args(["--help"])
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
