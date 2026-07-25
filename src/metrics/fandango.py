# metrics/fandango.py
"""Fandango movie showtimes / theater / seat availability wrapper.

Calls the local OpenClaw Fandango CLI at ~/.openclaw/extensions/fandango/fandango.js
via subprocess. All commands are read-only — no ticket purchasing.

This is a fun dev-downtime subcommand, not part of repository health scoring.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ._external_cli import ExternalCLI


_FANDANGO_CLI = ExternalCLI(
    name="fandango",
    cli_filename="fandango.js",
    env_var="FANDANGO_CLI",
    candidates=[
        Path.home() / ".openclaw" / "extensions" / "fandango" / "fandango.js",
        Path("/home/ubuntu/.openclaw/workspace/extensions/fandango/fandango.js"),
    ],
    json_flag="--json",
    node_required=True,
)


def find_fandango_cli() -> Path:
    """Locate the fandango.js CLI."""
    return _FANDANGO_CLI.find_cli()


def _run_fandango(args: list[str], timeout: float = 20.0) -> Any:
    """Invoke fandango.js with --json and return parsed output."""
    return _FANDANGO_CLI.run_json(args, timeout=timeout)


# ── Public API ──

def search_movies(query: str, limit: int = 20) -> dict[str, Any]:
    """Search for movies by title. Returns {query, count, movies: [{id, title, url, ...}]}."""
    if not query:
        raise ValueError("query is required")
    return _run_fandango(["search-movies", "--query", query, "--limit", str(limit)])


def movie_showtimes(
    movie_id: str,
    date: str,
    zip_code: str | None = None,
    lat: float | None = None,
    long: float | None = None,
    format_filter: str | None = None,
    chain_code: str | None = None,
) -> dict[str, Any]:
    """Find showtimes for a movie near a ZIP code or lat/long.

    Returns {date, movieId, hasShowtimes, theaters: [{id, name, distance, address, showtimes: [...]}]}.
    Each showtime includes showtimeHashCode — feed to seat_map().
    """
    if not movie_id:
        raise ValueError("movie_id is required")
    if not date:
        raise ValueError("date is required (YYYY-MM-DD)")
    if not zip_code and (lat is None or long is None):
        raise ValueError("provide zip_code OR lat/long")

    args = ["movie-showtimes", "--movie-id", str(movie_id), "--date", date]
    if zip_code:
        args += ["--zip", str(zip_code)]
    else:
        args += ["--lat", str(lat), "--long", str(long)]
    if format_filter:
        args += ["--format", format_filter]
    if chain_code:
        args += ["--chain-code", chain_code]
    return _run_fandango(args)


def theater_showtimes(
    theater_id: str,
    date: str | None = None,
    movie_id: str | None = None,
    format_filter: str | None = None,
) -> dict[str, Any]:
    """List all movies and showtimes at a specific theater."""
    if not theater_id:
        raise ValueError("theater_id is required")
    args = ["theater-showtimes", "--theater-id", theater_id]
    if date:
        args += ["--date", date]
    if movie_id:
        args += ["--movie-id", str(movie_id)]
    if format_filter:
        args += ["--format", format_filter]
    return _run_fandango(args)


def theater_calendar(theater_id: str, start_date: str | None = None) -> dict[str, Any]:
    """Check available showtime dates for a theater."""
    if not theater_id:
        raise ValueError("theater_id is required")
    args = ["theater-calendar", "--theater-id", theater_id]
    if start_date:
        args += ["--start-date", start_date]
    return _run_fandango(args)


def seat_map(showtime_hash_code: str) -> dict[str, Any]:
    """Read seat availability for a showtime.

    Get showtimeHashCode from movie_showtimes() or theater_showtimes().
    Returns {theaterId, theaterName, totalSeatCount, availableSeatCount, takenSeatCount, seats: [...] }.
    """
    if not showtime_hash_code:
        raise ValueError("showtime_hash_code is required")
    return _run_fandango(["seat-map", "--showtime", showtime_hash_code])
