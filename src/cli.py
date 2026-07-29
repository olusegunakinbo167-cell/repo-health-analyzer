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


# ── Embark / dog DNA subcommand ──

def _add_embark_subparsers(subparsers: argparse._SubParsersAction) -> None:
    embark = subparsers.add_parser(
        "embark",
        help="Dog breed traits and genetic health information (via Embark)",
        description="Dog breed traits and genetic health information (via Embark). "
        "Fun dev-downtime subcommand — not part of repo health scoring.",
    )
    e_sub = embark.add_subparsers(dest="embark_cmd", required=True)

    # breeds search
    p = e_sub.add_parser("breeds", help="Search dog breeds")
    p.add_argument("--query", help="Breed name search term (optional, omit for all)")
    p.add_argument("--live", action="store_true", help="Force live scrape (may trigger CF WAF)")
    p.add_argument("--json", action="store_true", help="Output raw JSON")
    p.set_defaults(func=cmd_embark_breeds)

    # breeds get
    p = e_sub.add_parser("breed", help="Get full breed profile")
    p.add_argument("--breed-slug", required=True, help="Breed slug (e.g. golden-retriever)")
    p.add_argument("--json", action="store_true", help="Output raw JSON")
    p.set_defaults(func=cmd_embark_breed_get)

    # health search
    p = e_sub.add_parser("health-search", help="Search genetic health conditions")
    p.add_argument("--query", help="Condition/gene search term (optional, omit for all)")
    p.add_argument("--json", action="store_true", help="Output raw JSON")
    p.set_defaults(func=cmd_embark_health_search)

    # health get
    p = e_sub.add_parser("health", help="Get health condition detail")
    p.add_argument("--condition-slug", required=True, help="Condition slug (e.g. mdr1-drug-sensitivity)")
    p.add_argument("--json", action="store_true", help="Output raw JSON")
    p.set_defaults(func=cmd_embark_health_get)

    # traits
    p = e_sub.add_parser("traits", help="List/search genetic traits")
    p.add_argument("--query", help="Trait/gene search term (optional, omit for all)")
    p.add_argument("--live", action="store_true", help="Force live scrape (may trigger CF WAF)")
    p.add_argument("--json", action="store_true", help="Output raw JSON")
    p.set_defaults(func=cmd_embark_traits)


def cmd_embark_breeds(args: argparse.Namespace) -> int:
    from .metrics.embark import search_breeds

    try:
        result = search_breeds(query=args.query, live=args.live)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        # Friendly CF WAF hint
        if "waf" in str(exc).lower() or "cloudflare" in str(exc).lower():
            print(
                "Hint: Embark is behind Cloudflare Bot Management. "
                "Set EMBARK_COOKIE or EMBARK_COOKIE_FILE with a browser session cookie, "
                "or use cached mode (omit --live).",
                file=sys.stderr,
            )
        return 1
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    console = Console()
    q = args.query or "(all)"
    console.print(f"[bold]Breeds matching \"{q}\"[/bold] — {len(result)} result(s)\n")
    if not result:
        console.print("No matches.", style="dim")
        return 0
    tbl = Table(show_header=True)
    tbl.add_column("Name")
    tbl.add_column("Slug", style="cyan")
    tbl.add_column("URL", style="dim")
    for b in result:
        tbl.add_row(b.get("name", "?"), b.get("slug", "?"), b.get("url", ""))
    console.print(tbl)
    return 0


def cmd_embark_breed_get(args: argparse.Namespace) -> int:
    from .metrics.embark import get_breed

    try:
        result = get_breed(args.breed_slug)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        if "waf" in str(exc).lower() or "cloudflare" in str(exc).lower():
            print(
                "Hint: Embark is behind Cloudflare Bot Management. "
                "Set EMBARK_COOKIE or EMBARK_COOKIE_FILE with a browser session cookie.",
                file=sys.stderr,
            )
        return 1
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    console = Console()
    console.print(f"[bold]{result.get('name', args.breed_slug)}[/bold]")
    console.print(f"[dim]{result.get('url', '')}[/dim]\n")
    for key in ("description", "fun_fact", "about", "physical_characteristics", "playtime", "grooming", "health_aging"):
        val = result.get(key)
        if val:
            label = key.replace("_", " ").title()
            console.print(f"[bold]{label}:[/bold] {val}\n")
    size = result.get("size")
    weight = result.get("weight_lbs")
    if size:
        console.print(f"[bold]Size:[/bold] {size.get('height_inches_min')}–{size.get('height_inches_max')} inches")
    if weight:
        console.print(f"[bold]Weight:[/bold] {weight.get('min')}–{weight.get('max')} lbs")
    conditions = result.get("health_conditions_tested", [])
    if conditions:
        console.print(f"\n[bold]Health conditions tested ({len(conditions)}):[/bold]")
        for c in conditions:
            console.print(f"  • {c.get('name', '?')} [dim]({c.get('slug', '?')})[/dim]")
    return 0


def cmd_embark_health_search(args: argparse.Namespace) -> int:
    from .metrics.embark import search_health

    try:
        result = search_health(query=args.query)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        if "waf" in str(exc).lower() or "cloudflare" in str(exc).lower():
            print(
                "Hint: Embark is behind Cloudflare Bot Management. "
                "Set EMBARK_COOKIE or EMBARK_COOKIE_FILE with a browser session cookie.",
                file=sys.stderr,
            )
        return 1
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    console = Console()
    q = args.query or "(all)"
    console.print(f"[bold]Health conditions matching \"{q}\"[/bold] — {len(result)} result(s)\n")
    if not result:
        console.print("No matches.", style="dim")
        return 0
    tbl = Table(show_header=True)
    tbl.add_column("Name")
    tbl.add_column("Gene", style="cyan")
    tbl.add_column("Category", style="dim")
    tbl.add_column("Slug", style="dim")
    for c in result:
        tbl.add_row(
            c.get("name", "?"),
            c.get("gene") or "—",
            c.get("category") or "—",
            c.get("slug", "?"),
        )
    console.print(tbl)
    return 0


def cmd_embark_health_get(args: argparse.Namespace) -> int:
    from .metrics.embark import get_health

    try:
        result = get_health(args.condition_slug)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        if "waf" in str(exc).lower() or "cloudflare" in str(exc).lower():
            print(
                "Hint: Embark is behind Cloudflare Bot Management. "
                "Set EMBARK_COOKIE or EMBARK_COOKIE_FILE with a browser session cookie.",
                file=sys.stderr,
            )
        return 1
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    console = Console()
    console.print(f"[bold]{result.get('name', args.condition_slug)}[/bold]")
    console.print(f"[dim]{result.get('url', '')}[/dim]\n")
    if result.get("gene_names"):
        console.print(f"[bold]Gene:[/bold] {result['gene_names']}")
    if result.get("inheritance_type"):
        console.print(f"[bold]Inheritance:[/bold] {result['inheritance_type']}\n")
    if result.get("description"):
        console.print(f"{result['description']}\n")
    for key, label in [
        ("signs_symptoms", "Signs & Symptoms"),
        ("diagnosis", "Diagnosis"),
        ("treatment", "Treatment"),
    ]:
        val = result.get(key)
        if val:
            console.print(f"[bold]{label}:[/bold] {val}\n")
    breeds = result.get("affected_breeds", [])
    if breeds:
        console.print(f"[bold]Affected breeds ({len(breeds)}):[/bold]")
        for b in breeds[:20]:
            console.print(f"  • {b.get('name', '?')} [dim]({b.get('slug', '?')})[/dim]")
        if len(breeds) > 20:
            console.print(f"  [dim]… and {len(breeds) - 20} more[/dim]")
    return 0


def cmd_embark_traits(args: argparse.Namespace) -> int:
    from .metrics.embark import list_traits

    try:
        result = list_traits(query=args.query, live=args.live)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        if "waf" in str(exc).lower() or "cloudflare" in str(exc).lower():
            print(
                "Hint: Embark is behind Cloudflare Bot Management. "
                "Set EMBARK_COOKIE or EMBARK_COOKIE_FILE with a browser session cookie, "
                "or use cached mode (omit --live).",
                file=sys.stderr,
            )
        return 1
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    console = Console()
    q = args.query or "(all)"
    console.print(f"[bold]Traits matching \"{q}\"[/bold] — {len(result)} result(s)\n")
    if not result:
        console.print("No matches.", style="dim")
        return 0
    tbl = Table(show_header=True)
    tbl.add_column("Trait")
    tbl.add_column("Gene", style="cyan")
    tbl.add_column("Category", style="dim")
    for t in result:
        tbl.add_row(
            t.get("name", "?"),
            t.get("gene", "?"),
            t.get("category") or "—",
        )
    console.print(tbl)
    return 0


# ── Weather Service / environment context subcommand ──

def _add_weather_subparsers(subparsers: argparse._SubParsersAction) -> None:
    weather = subparsers.add_parser(
        "weather",
        help="National Weather Service forecasts and alerts (via weather-service)",
        description="National Weather Service forecasts, observations, and alerts "
        "(via weather-service). "
        "Fun dev-downtime subcommand — not part of repo health scoring, "
        "but environment context is collected during `analyze` runs.",
    )
    w_sub = weather.add_subparsers(dest="weather_cmd", required=True)

    # forecast
    p = w_sub.add_parser("forecast", help="Get weather forecast for a location")
    p.add_argument(
        "--location",
        default="37.7749,-122.4194",
        help="Latitude,longitude pair (default: 37.7749,-122.4194 — San Francisco, CA)",
    )
    p.add_argument("--json", action="store_true", help="Output raw JSON")
    p.set_defaults(func=cmd_weather_forecast)

    # hourly
    p = w_sub.add_parser("hourly", help="Get hourly forecast for a location")
    p.add_argument(
        "--location",
        default="37.7749,-122.4194",
        help="Latitude,longitude pair (default: 37.7749,-122.4194)",
    )
    p.add_argument("--json", action="store_true", help="Output raw JSON")
    p.set_defaults(func=cmd_weather_hourly)

    # alerts
    p = w_sub.add_parser("alerts", help="Get active weather alerts")
    grp = p.add_mutually_exclusive_group(required=False)
    grp.add_argument("--area", help="State/area code (e.g. CA)")
    grp.add_argument(
        "--location",
        help="Latitude,longitude pair",
    )
    p.add_argument("--json", action="store_true", help="Output raw JSON")
    p.set_defaults(func=cmd_weather_alerts)

    # observation
    p = w_sub.add_parser("observation", help="Get latest observation from a station")
    p.add_argument("--station-id", required=True, help="Station identifier (e.g. KSFO)")
    p.add_argument("--json", action="store_true", help="Output raw JSON")
    p.set_defaults(func=cmd_weather_observation)

    # stations
    p = w_sub.add_parser("stations", help="Find nearby weather stations")
    p.add_argument(
        "--location",
        default="37.7749,-122.4194",
        help="Latitude,longitude pair (default: 37.7749,-122.4194)",
    )
    p.add_argument("--json", action="store_true", help="Output raw JSON")
    p.set_defaults(func=cmd_weather_stations)

    # context
    p = w_sub.add_parser(
        "context", help="Collect full environment weather context (forecast + alerts + observation)"
    )
    p.add_argument(
        "--location",
        default="37.7749,-122.4194",
        help="Latitude,longitude pair (default: 37.7749,-122.4194)",
    )
    p.add_argument("--json", action="store_true", help="Output raw JSON")
    p.set_defaults(func=cmd_weather_context)


def cmd_weather_forecast(args: argparse.Namespace) -> int:
    from .metrics.weather_service import get_forecast

    try:
        result = get_forecast(args.location)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    console = Console()
    periods = result.get("properties", {}).get("periods", [])
    console.print(f"[bold]Forecast — {args.location}[/bold]  {len(periods)} period(s)\n")
    for p in periods[:8]:
        name = p.get("name", "?")
        temp = p.get("temperature", "?")
        unit = p.get("temperatureUnit", "")
        short = p.get("shortForecast", "")
        console.print(f"[bold]{name}:[/bold] {temp}°{unit} — {short}")
    return 0


def cmd_weather_hourly(args: argparse.Namespace) -> int:
    from .metrics.weather_service import get_hourly_forecast

    try:
        result = get_hourly_forecast(args.location)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    console = Console()
    periods = result.get("properties", {}).get("periods", [])
    console.print(f"[bold]Hourly forecast — {args.location}[/bold]\n")
    for p in periods[:12]:
        start = p.get("startTime", "?")
        temp = p.get("temperature", "?")
        unit = p.get("temperatureUnit", "")
        short = p.get("shortForecast", "")
        console.print(f"{start}  {temp}°{unit}  {short}")
    return 0


def cmd_weather_alerts(args: argparse.Namespace) -> int:
    from .metrics.weather_service import get_alerts

    # Default to CA if neither area nor location provided
    area = args.area or None
    location = args.location or None
    if not area and not location:
        area = "CA"

    try:
        result = get_alerts(area=area, location=location)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    console = Console()
    features = result.get("features", [])
    where = args.area or args.location or "CA"
    console.print(f"[bold]Active alerts — {where}[/bold]  {len(features)} alert(s)\n")
    if not features:
        console.print("No active alerts.", style="dim")
        return 0
    for f in features:
        props = f.get("properties", {})
        event = props.get("event", "?")
        severity = props.get("severity", "?")
        headline = props.get("headline", "")
        console.print(f"[bold]{event}[/bold] [{severity}]")
        if headline:
            console.print(f"  {headline}")
        console.print()
    return 0


def cmd_weather_observation(args: argparse.Namespace) -> int:
    from .metrics.weather_service import get_observation

    try:
        result = get_observation(args.station_id)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    console = Console()
    props = result.get("properties", {})
    console.print(f"[bold]Observation — {args.station_id}[/bold]\n")
    ts = props.get("timestamp", "?")
    desc = props.get("textDescription", "?")
    console.print(f"Time: {ts}")
    console.print(f"Conditions: {desc}")
    temp = props.get("temperature", {})
    if temp:
        console.print(f"Temperature: {temp.get('value')} {temp.get('unitCode', '')}")
    wind = props.get("windSpeed", {})
    if wind:
        console.print(f"Wind: {wind.get('value')} {wind.get('unitCode', '')}")
    rh = props.get("relativeHumidity", {})
    if rh:
        console.print(f"Humidity: {rh.get('value')} {rh.get('unitCode', '')}")
    return 0


def cmd_weather_stations(args: argparse.Namespace) -> int:
    from .metrics.weather_service import find_stations

    try:
        result = find_stations(args.location)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    console = Console()
    features = result.get("features", [])
    console.print(f"[bold]Weather stations near {args.location}[/bold]  {len(features)} found\n")
    tbl = Table(show_header=True)
    tbl.add_column("ID", style="cyan")
    tbl.add_column("Name")
    tbl.add_column("Distance", justify="right")
    for f in features[:20]:
        props = f.get("properties", {})
        sid = props.get("stationIdentifier", "?")
        name = props.get("name", "?")
        dist = props.get("distance", {})
        dist_str = ""
        if isinstance(dist, dict):
            dist_str = f"{dist.get('value', '?')} {dist.get('unitCode', '').split(':')[-1]}"
        elif dist:
            dist_str = str(dist)
        tbl.add_row(sid, name, dist_str)
    console.print(tbl)
    return 0


def cmd_weather_context(args: argparse.Namespace) -> int:
    from .metrics.weather_service import get_environment_context

    try:
        result = get_environment_context(args.location)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    console = Console()
    console.print(f"[bold]Environment context — {result['location']}[/bold]\n")
    fc = result.get("forecast")
    if fc:
        console.print(
            f"[bold]Forecast:[/bold] {fc.get('shortForecast')} — "
            f"{fc.get('temperature')}°{fc.get('temperatureUnit', '')}"
        )
        console.print(f"  {fc.get('detailedForecast')}\n")
    alerts = result.get("alerts", {})
    console.print(f"[bold]Alerts:[/bold] {alerts.get('count', 0)} active")
    for a in alerts.get("alerts", []):
        console.print(f"  • {a.get('event')} [{a.get('severity')}]")
    console.print()
    obs = result.get("observation")
    if obs:
        console.print(
            f"[bold]Observation ({obs.get('station_id')}):[/bold] {obs.get('textDescription', '?')}"
        )
    errors = result.get("errors", [])
    if errors:
        console.print(f"\n[dim]Errors: {', '.join(errors)}[/dim]")
    return 0


# ── Hacker News / discussion context subcommand ──

def _add_hn_subparsers(subparsers: argparse._SubParsersAction) -> None:
    hn = subparsers.add_parser(
        "hn",
        help="Hacker News discussions and community context (via hackernews CLI)",
        description="Hacker News discussions, Ask HN, Show HN, and job postings "
        "(via hackernews CLI). "
        "Fun dev-downtime subcommand — not part of repo health scoring, "
        "but discussion context can be collected during `analyze` runs with --hn-digest.",
    )
    h_sub = hn.add_subparsers(dest="hn_cmd", required=True)

    # top-stories
    p = h_sub.add_parser("top", help="Get top Hacker News story IDs")
    p.add_argument("--limit", type=int, default=10, help="Max results (default: 10)")
    p.add_argument("--json", action="store_true", help="Output raw JSON")
    p.set_defaults(func=cmd_hn_top)

    # get-item
    p = h_sub.add_parser("item", help="Get a Hacker News item by ID")
    p.add_argument("--id", dest="item_id", type=int, required=True, help="Hacker News item ID")
    p.add_argument("--json", action="store_true", help="Output raw JSON")
    p.set_defaults(func=cmd_hn_item)

    # digest
    p = h_sub.add_parser(
        "digest", help="Fetch HN discussion digest (top stories + full item details)"
    )
    p.add_argument("--limit", type=int, default=10, help="Number of top stories (default: 10)")
    p.add_argument("--ids-only", action="store_true", help="Return IDs only, skip fetching items")
    p.add_argument("--json", action="store_true", help="Output raw JSON")
    p.set_defaults(func=cmd_hn_digest)

    # new-stories
    p = h_sub.add_parser("new", help="Get newest Hacker News story IDs")
    p.add_argument("--limit", type=int, default=10, help="Max results (default: 10)")
    p.add_argument("--json", action="store_true", help="Output raw JSON")
    p.set_defaults(func=cmd_hn_new)

    # best-stories
    p = h_sub.add_parser("best", help="Get best Hacker News story IDs")
    p.add_argument("--limit", type=int, default=10, help="Max results (default: 10)")
    p.add_argument("--json", action="store_true", help="Output raw JSON")
    p.set_defaults(func=cmd_hn_best)

    # ask-stories
    p = h_sub.add_parser("ask", help="Get Ask HN story IDs")
    p.add_argument("--limit", type=int, default=10, help="Max results (default: 10)")
    p.add_argument("--json", action="store_true", help="Output raw JSON")
    p.set_defaults(func=cmd_hn_ask)

    # show-stories
    p = h_sub.add_parser("show", help="Get Show HN story IDs")
    p.add_argument("--limit", type=int, default=10, help="Max results (default: 10)")
    p.add_argument("--json", action="store_true", help="Output raw JSON")
    p.set_defaults(func=cmd_hn_show)

    # job-stories
    p = h_sub.add_parser("jobs", help="Get Hacker News job posting IDs")
    p.add_argument("--limit", type=int, default=10, help="Max results (default: 10)")
    p.add_argument("--json", action="store_true", help="Output raw JSON")
    p.set_defaults(func=cmd_hn_jobs)

    # get-user
    p = h_sub.add_parser("user", help="Get a Hacker News user profile")
    p.add_argument("--id", dest="user_id", required=True, help="Hacker News username")
    p.add_argument("--submitted-limit", type=int, help="Max submitted item IDs to return")
    p.add_argument("--json", action="store_true", help="Output raw JSON")
    p.set_defaults(func=cmd_hn_user)


def cmd_hn_top(args: argparse.Namespace) -> int:
    from .metrics.hn import top_stories

    try:
        result = top_stories(limit=args.limit)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    console = Console()
    console.print(f"[bold]Top HN stories[/bold] — {len(result)} ID(s)\n")
    for i, sid in enumerate(result, 1):
        console.print(f"  {i}. {sid}")
    return 0


def cmd_hn_item(args: argparse.Namespace) -> int:
    from .metrics.hn import get_item

    try:
        result = get_item(args.item_id)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    console = Console()
    console.print(f"[bold]{result.get('title', args.item_id)}[/bold]")
    if result.get("url"):
        console.print(f"[dim]{result['url']}[/dim]\n")
    console.print(f"by {result.get('by', '?')}  "
                  f"score: {result.get('score', '?')}  "
                  f"comments: {result.get('descendants', 0)}")
    return 0


def cmd_hn_digest(args: argparse.Namespace) -> int:
    from .metrics.hn import get_hn_digest

    try:
        result = get_hn_digest(top_limit=args.limit, fetch_items=not args.ids_only)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    console = Console()
    stories = result.get("stories", [])
    ids = result.get("top_story_ids", [])
    console.print(f"[bold]HN Digest[/bold] — {len(ids)} story ID(s), "
                  f"{len(stories)} fetched\n")
    for i, s in enumerate(stories, 1):
        title = s.get("title", "?")
        score = s.get("score", "?")
        by = s.get("by", "?")
        comments = s.get("descendants", 0)
        url = s.get("url", "")
        console.print(f"[bold]{i}. {title}[/bold]")
        console.print(f"   by {by}  score: {score}  comments: {comments}")
        if url:
            console.print(f"   [dim]{url}[/dim]")
        console.print()
    errors = result.get("errors", [])
    if errors:
        console.print(f"[dim]Errors: {', '.join(errors)}[/dim]")
    return 0


def _cmd_hn_stories(args: argparse.Namespace, fn, label: str) -> int:
    try:
        result = fn(limit=args.limit)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    console = Console()
    console.print(f"[bold]{label}[/bold] — {len(result)} ID(s)\n")
    for i, sid in enumerate(result, 1):
        console.print(f"  {i}. {sid}")
    return 0


def cmd_hn_new(args: argparse.Namespace) -> int:
    from .metrics.hn import new_stories
    return _cmd_hn_stories(args, new_stories, "New HN stories")


def cmd_hn_best(args: argparse.Namespace) -> int:
    from .metrics.hn import best_stories
    return _cmd_hn_stories(args, best_stories, "Best HN stories")


def cmd_hn_ask(args: argparse.Namespace) -> int:
    from .metrics.hn import ask_stories
    return _cmd_hn_stories(args, ask_stories, "Ask HN stories")


def cmd_hn_show(args: argparse.Namespace) -> int:
    from .metrics.hn import show_stories
    return _cmd_hn_stories(args, show_stories, "Show HN stories")


def cmd_hn_jobs(args: argparse.Namespace) -> int:
    from .metrics.hn import job_stories
    return _cmd_hn_stories(args, job_stories, "HN job postings")


def cmd_hn_user(args: argparse.Namespace) -> int:
    from .metrics.hn import get_user

    try:
        result = get_user(args.user_id, submitted_limit=args.submitted_limit)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    console = Console()
    console.print(f"[bold]{result.get('id', args.user_id)}[/bold]")
    console.print(f"Karma: {result.get('karma', '?')}  "
                  f"Created: {result.get('created', '?')}")
    about = result.get("about")
    if about:
        console.print(f"\n{about}")
    submitted = result.get("submitted", [])
    if submitted:
        console.print(f"\n[dim]{len(submitted)} submitted item(s)[/dim]")
    return 0


# ── Repo health analysis ──

def _extract_cli_config_path(argv: list[str] | None) -> str | None:
    """Pre-scan argv for --cli-config <path> so we can load defaults early.

    Returns the config path if --cli-config was passed, else None.
    This allows `.repo-health.json` defaults to be applied as argparse
    defaults, so explicit CLI flags correctly override them.
    """
    if argv is None:
        argv = sys.argv[1:]
    # Simple scan — look for --cli-config <path>
    for i, arg in enumerate(argv):
        if arg == "--cli-config" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--cli-config="):
            return arg.split("=", 1)[1]
    return None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    # Pre-scan for --cli-config so we can load .repo-health.json defaults
    # before building the full parser. This ensures CLI flags override
    # config file values (argparse defaults < CLI args).
    cli_config_path = _extract_cli_config_path(argv)
    try:
        from .cli_config import load_cli_config

        cli_defaults = load_cli_config(cli_config_path)
        cli_defaults_dict = cli_defaults.to_argparse_defaults()
    except Exception as exc:
        # Config load errors are fatal — bad config should fail fast
        # unless the user explicitly passed --cli-config (then it's intentional)
        if cli_config_path is not None:
            print(f"Error loading CLI config: {exc}", file=sys.stderr)
            sys.exit(2)
        # Auto-discovered config failed — ignore and use argparse defaults
        cli_defaults_dict = {}

    parser = argparse.ArgumentParser(
        prog="repo-health-analyzer",
        description="Analyze GitHub repository health metrics.",
    )
    subparsers = parser.add_subparsers(dest="command")

    # movies subcommand
    _add_movies_subparsers(subparsers)

    # embark subcommand
    _add_embark_subparsers(subparsers)

    # weather subcommand
    _add_weather_subparsers(subparsers)

    # hn subcommand
    _add_hn_subparsers(subparsers)

    # analyze (default) — repository health check
    analyze = subparsers.add_parser(
        "analyze",
        help="Analyze a GitHub repository (default command)",
        description="Analyze GitHub repository health metrics.",
    )

    # --cli-config: path to local CLI defaults JSON file
    # This is parsed early (see _extract_cli_config_path above) so that
    # values from .repo-health.json can be used as argparse defaults.
    # Explicit CLI flags always override config file values.
    analyze.add_argument(
        "--cli-config",
        metavar="PATH",
        type=Path,
        default=None,
        help="Path to CLI defaults config file (default: auto-discover "
        ".repo-health.json in cwd). "
        "Config file values are used as defaults; explicit CLI flags override them.",
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
    academic_grp = analyze.add_mutually_exclusive_group()
    academic_grp.add_argument(
        "--skip-academic",
        action="store_true",
        dest="skip_academic",
        help="Skip academic impact / paper reference scanning (faster, no S2 API calls)",
    )
    academic_grp.add_argument(
        "--no-skip-academic",
        action="store_false",
        dest="skip_academic",
        help=argparse.SUPPRESS,  # override for --skip-academic when set in .repo-health.json
    )
    # Academic impact export options
    analyze.add_argument(
        "--academic-max-papers",
        type=int,
        default=20,
        metavar="N",
        help="Max referenced papers to include in Markdown/HTML exports "
        "(default: 20, 0 = unlimited)",
    )
    analyze.add_argument(
        "--academic-no-tldr",
        action="store_true",
        dest="academic_no_tldr",
        help="Omit paper TLDRs from Markdown/HTML exports (shorter reports)",
    )
    analyze.add_argument(
        "--academic-include-unresolved",
        action="store_true",
        dest="academic_include_unresolved",
        help="Include unresolved paper references in exports (default: resolved only)",
    )
    # New unified output options
    analyze.add_argument(
        "-o",
        "--output",
        dest="output",
        metavar="PATH",
        type=Path,
        default=None,
        help="Write health report to PATH (format auto-detected from extension, "
        "override with --format)",
    )
    analyze.add_argument(
        "--format",
        dest="output_format",
        choices=("json", "markdown", "html", "auto"),
        default="auto",
        help="Output format for --output (default: auto-detect from file extension)",
    )
    # Backwards-compat output flags
    json_grp = analyze.add_mutually_exclusive_group()
    json_grp.add_argument(
        "--json",
        action="store_true",
        dest="json",
        help="Output results as JSON to stdout (deprecated: use -o report.json)",
    )
    json_grp.add_argument(
        "--no-json",
        action="store_false",
        dest="json",
        help=argparse.SUPPRESS,
    )
    analyze.add_argument(
        "--markdown",
        metavar="PATH",
        type=Path,
        default=None,
        help="Write a GitHub-flavored Markdown report to PATH "
        "(deprecated: use -o report.md)",
    )
    analyze.add_argument(
        "--html",
        "--html-output",
        dest="html_output",
        metavar="PATH",
        type=Path,
        default=None,
        help="Write a self-contained HTML report to PATH "
        "(use -o report.html --format html for explicit format control)",
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
        help="Save complete run metadata to a JSON file "
        "(deprecated: use -o artifact.json --format json)",
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
        "--weather-location",
        metavar="LAT,LONG",
        default="37.7749,-122.4194",
        help="Latitude,longitude for local environment weather context "
        "(default: 37.7749,-122.4194 — San Francisco, CA). "
        "Set to empty string to skip weather collection.",
    )
    weather_grp = analyze.add_mutually_exclusive_group()
    weather_grp.add_argument(
        "--no-weather",
        action="store_true",
        dest="no_weather",
        help="Skip weather / environment context collection during analysis",
    )
    weather_grp.add_argument(
        "--weather",
        action="store_false",
        dest="no_weather",
        help=argparse.SUPPRESS,  # override for --no-weather when set in .repo-health.json
    )
    hn_grp = analyze.add_mutually_exclusive_group()
    hn_grp.add_argument(
        "--hn-digest",
        action="store_true",
        dest="hn_digest",
        help="Collect Hacker News discussion context during analysis — "
        "fetches current top stories via HN API and attaches to run_summary.json",
    )
    hn_grp.add_argument(
        "--no-hn-digest",
        action="store_false",
        dest="hn_digest",
        help=argparse.SUPPRESS,  # override for --hn-digest when set in .repo-health.json
    )
    analyze.add_argument(
        "--hn-limit",
        type=int,
        default=10,
        metavar="N",
        help="Number of HN top stories to include with --hn-digest (default: 10)",
    )
    color_grp = analyze.add_mutually_exclusive_group()
    color_grp.add_argument(
        "--no-color",
        action="store_true",
        dest="no_color",
        help="Disable Rich color output in terminal",
    )
    color_grp.add_argument(
        "--color",
        action="store_false",
        dest="no_color",
        help=argparse.SUPPRESS,  # override for --no-color when set in .repo-health.json
    )
    analyze.set_defaults(func=cmd_analyze)

    # Apply CLI config file defaults (if .repo-health.json was found).
    # Explicit CLI flags override these because argparse processes CLI args
    # after set_defaults().
    if cli_defaults_dict:
        analyze.set_defaults(**cli_defaults_dict)

    # Backwards compat: if first arg isn't a known subcommand, treat as
    # `analyze <repo> ...` — this preserves the old
    # `repo-health-analyzer owner/repo [...]` invocation, and also ensures
    # invalid repo format errors come from run() validation (not argparse),
    # matching pre-subparser behavior.
    if argv is None:
        argv = sys.argv[1:]
    if argv and not argv[0].startswith("-") and argv[0] not in ("movies", "embark", "weather", "hn", "analyze"):
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

    def load_cat(key: str, default_max: float = 25.0) -> CategoryScore:
        c = hs_data.get(key, {})
        return CategoryScore(
            name=c.get("name", key.title()),
            score=float(c.get("score", 0.0)),
            max_score=float(c.get("max_score", default_max)),
            penalties=list(c.get("penalties", [])),
            recommendations=list(c.get("recommendations", [])),
        )

    health = HealthScore(
        total_score=float(hs_data.get("total_score", 0.0)),
        documentation=load_cat("documentation", 20.0),
        maintenance=load_cat("maintenance", 25.0),
        ci_cd=load_cat("ci_cd", 25.0),
        governance=load_cat("governance", 20.0),
        academic_impact=load_cat("academic_impact", 10.0),
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

    # Collect plugin statuses for export
    plugin_statuses: list = []
    try:
        from .exporters.plugin_status import check_all_plugins

        plugin_statuses = check_all_plugins()
    except Exception:
        # Plugin status collection is best-effort — don't fail the analysis
        plugin_statuses = []

    # Collect environment context (weather) for export
    environment_context: dict[str, Any] | None = None
    no_weather = getattr(args, "no_weather", False)
    weather_location = getattr(args, "weather_location", "37.7749,-122.4194")
    if not no_weather and weather_location:
        try:
            from .metrics.weather_service import get_environment_context

            environment_context = get_environment_context(weather_location)
        except Exception:
            # Weather collection is best-effort — don't fail the analysis
            environment_context = None

    # Collect Hacker News discussion context for export
    hn_context: dict[str, Any] | None = None
    hn_digest_enabled = getattr(args, "hn_digest", False)
    hn_limit = getattr(args, "hn_limit", 10)
    if hn_digest_enabled:
        try:
            from .metrics.hn import get_hn_digest

            hn_context = get_hn_digest(top_limit=hn_limit, fetch_items=True)
        except Exception:
            # HN collection is best-effort — don't fail the analysis
            hn_context = None

    # ── Export handling ──
    # Academic export options
    academic_max_papers = getattr(args, "academic_max_papers", 20)
    academic_include_tldr = not getattr(args, "academic_no_tldr", False)
    academic_include_unresolved = getattr(args, "academic_include_unresolved", False)

    # New unified --output / -o flag
    output_path = getattr(args, "output", None)
    output_format = getattr(args, "output_format", "auto")

    wrote_output_file = False

    if output_path:
        try:
            from .exporters import export_report
            from .exporters.base import ReportMetadata

            metadata = ReportMetadata(
                repository=metrics.full_name,
                commit_sha=metrics.commit_sha,
                timestamp=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            )
            export_report(
                metrics,
                health,
                output_path,
                format=output_format,
                baseline_diff=baseline_diff,
                plugin_statuses=plugin_statuses,
                metadata=metadata,
                environment_context=environment_context,
                hn_context=hn_context,
                academic_max_papers=academic_max_papers,
                academic_include_tldr=academic_include_tldr,
                academic_include_unresolved=academic_include_unresolved,
            )
            wrote_output_file = True
        except Exception as exc:
            print(f"Error writing output: {exc}", file=sys.stderr)
            return 1

    # ── Backwards-compat output flags ──

    # --save-artifact: write run telemetry JSON (deprecated: use -o artifact.json)
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
        if environment_context:
            artifact["environment_context"] = environment_context
        if hn_context:
            artifact["hn_context"] = hn_context
        try:
            args.save_artifact.parent.mkdir(parents=True, exist_ok=True)
            args.save_artifact.write_text(
                json.dumps(artifact, indent=2), encoding="utf-8"
            )
            wrote_output_file = True
        except Exception as exc:
            print(f"Error writing artifact: {exc}", file=sys.stderr)
            return 1

    # --markdown output (deprecated: use -o report.md)
    if args.markdown:
        try:
            from .exporters import MarkdownExporter
            from .exporters.base import ReportMetadata

            metadata = ReportMetadata(
                repository=metrics.full_name,
                commit_sha=metrics.commit_sha,
                timestamp=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            )
            exporter = MarkdownExporter()
            md = exporter.export(
                metrics,
                health,
                baseline_diff=baseline_diff,
                plugin_statuses=plugin_statuses,
                metadata=metadata,
                environment_context=environment_context,
                hn_context=hn_context,
                academic_max_papers=academic_max_papers,
                academic_include_tldr=academic_include_tldr,
                academic_include_unresolved=academic_include_unresolved,
            )
            # If the path matches $GITHUB_STEP_SUMMARY, append
            if str(args.markdown) == os.getenv("GITHUB_STEP_SUMMARY", ""):
                with args.markdown.open("a", encoding="utf-8") as f:
                    f.write(md + "\n")
            else:
                args.markdown.parent.mkdir(parents=True, exist_ok=True)
                args.markdown.write_text(md, encoding="utf-8")
            wrote_output_file = True
        except Exception as exc:
            print(f"Error writing markdown report: {exc}", file=sys.stderr)
            return 1
        # Confirmation to stderr if markdown was sole output
        if not args.json and not args.save_artifact and not output_path and not getattr(args, "html_output", None):
            print(f"Wrote Markdown report to {args.markdown}", file=sys.stderr)

    # --html / --html-output
    html_output = getattr(args, "html_output", None)
    if html_output:
        try:
            from .exporters import HTMLExporter
            from .exporters.base import ReportMetadata

            metadata = ReportMetadata(
                repository=metrics.full_name,
                commit_sha=metrics.commit_sha,
                timestamp=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            )
            exporter = HTMLExporter()
            html_content = exporter.export(
                metrics,
                health,
                baseline_diff=baseline_diff,
                plugin_statuses=plugin_statuses,
                metadata=metadata,
                environment_context=environment_context,
                hn_context=hn_context,
                academic_max_papers=academic_max_papers,
                academic_include_tldr=academic_include_tldr,
                academic_include_unresolved=academic_include_unresolved,
            )
            html_output.parent.mkdir(parents=True, exist_ok=True)
            html_output.write_text(html_content, encoding="utf-8")
            wrote_output_file = True
        except Exception as exc:
            print(f"Error writing HTML report: {exc}", file=sys.stderr)
            return 1
        # Confirmation to stderr if HTML was sole output
        if not args.json and not args.save_artifact and not output_path and not args.markdown:
            print(f"Wrote HTML report to {html_output}", file=sys.stderr)

    # --json output to stdout (deprecated: use -o report.json)
    if args.json:
        # Use the new JSON exporter for consistency (includes plugin statuses)
        try:
            from .exporters import JSONExporter
            from .exporters.base import ReportMetadata

            metadata = ReportMetadata(
                repository=metrics.full_name,
                commit_sha=metrics.commit_sha,
                timestamp=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            )
            exporter = JSONExporter()
            json_output = exporter.export(
                metrics,
                health,
                baseline_diff=baseline_diff,
                plugin_statuses=plugin_statuses,
                metadata=metadata,
                environment_context=environment_context,
                hn_context=hn_context,
                academic_max_papers=academic_max_papers,
                academic_include_tldr=academic_include_tldr,
                academic_include_unresolved=academic_include_unresolved,
            )
            print(json_output)
        except Exception:
            # Fall back to legacy result dict if exporter fails
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
    # Show terminal output if: no --json stdout, or gate failed, or any file output was requested
    # (file outputs suppress terminal by default to avoid noise in CI)
    html_output = getattr(args, "html_output", None)
    has_file_output = bool(output_path or args.markdown or html_output or args.save_artifact)
    show_terminal = (not args.json) or gate_failed
    # Suppress terminal if a file output was requested and gate passed
    if has_file_output and not gate_failed:
        show_terminal = False

    if show_terminal:
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
