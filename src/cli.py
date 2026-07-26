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
from .reporter import render_rich
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

... [truncated for brevity in analysis — full 54KB file content was sent] ...
