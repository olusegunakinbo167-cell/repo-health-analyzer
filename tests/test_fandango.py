"""Tests for Fandango movie showtimes wrapper."""

import json
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from src.metrics import fandango


# ── CLI discovery ──

def test_find_fandango_cli_env_override(tmp_path, monkeypatch):
    fake_cli = tmp_path / "fandango.js"
    fake_cli.write_text("#!/usr/bin/env node\n")
    monkeypatch.setenv("FANDANGO_CLI", str(fake_cli))
    # Clear cached CLI path so env var is checked
    from src.metrics import fandango as fandango_mod

    fandango_mod._FANDANGO_CLI._cached_cli_path = None
    try:
        result = fandango.find_fandango_cli()
        assert result == fake_cli
    finally:
        fandango_mod._FANDANGO_CLI._cached_cli_path = None


def test_find_fandango_cli_not_found(monkeypatch):
    monkeypatch.delenv("FANDANGO_CLI", raising=False)
    # Patch the internal ExternalCLI instance's candidates list
    from src.metrics import fandango as fandango_mod

    with patch.object(fandango_mod._FANDANGO_CLI, "candidates", []):
        # Clear cached CLI path
        fandango_mod._FANDANGO_CLI._cached_cli_path = None
        with patch("shutil.which", return_value=None):
            with pytest.raises(FileNotFoundError, match="fandango.*CLI.*not found"):
                fandango.find_fandango_cli()


# ── search_movies ──

def test_search_movies_success(monkeypatch):
    fake_output = {
        "query": "odyssey",
        "count": 1,
        "movies": [
            {
                "id": "241283",
                "title": "The Odyssey (2026)",
                "url": "https://www.fandango.com/the-odyssey-2026-241283/movie-overview",
            }
        ],
    }
    mock_proc = Mock()
    mock_proc.returncode = 0
    mock_proc.stdout = json.dumps(fake_output)
    mock_proc.stderr = ""

    with patch("subprocess.run", return_value=mock_proc) as mock_run:
        with patch.object(fandango, "find_fandango_cli", return_value=Path("/fake/fandango.js")):
            result = fandango.search_movies("odyssey", limit=20)

    assert result["query"] == "odyssey"
    assert result["count"] == 1
    assert result["movies"][0]["id"] == "241283"
    # Verify subprocess was called correctly
    args = mock_run.call_args[0][0]
    assert args[0] == "node"
    assert "search-movies" in args
    assert "--query" in args
    assert "odyssey" in args
    assert "--json" in args


def test_search_movies_empty_query():
    with pytest.raises(ValueError, match="query is required"):
        fandango.search_movies("")


# ── movie_showtimes ──

def test_movie_showtimes_zip(monkeypatch):
    fake_output = {
        "date": "2026-07-25",
        "movieId": "241283",
        "hasShowtimes": True,
        "theaters": [
            {
                "id": "aawjb",
                "name": "Violet Crown Austin",
                "distance": 0.5,
                "showtimes": [
                    {
                        "date": "9:20a",
                        "isAvailable": True,
                        "formats": ["Standard"],
                        "showtimeHashCode": "v2-abc123",
                        "ticketingDate": "2026-07-25+09:20",
                    }
                ],
            }
        ],
    }
    mock_proc = Mock(returncode=0, stdout=json.dumps(fake_output), stderr="")

    with patch("subprocess.run", return_value=mock_proc) as mock_run:
        with patch.object(fandango, "find_fandango_cli", return_value=Path("/fake/fandango.js")):
            result = fandango.movie_showtimes(
                movie_id="241283",
                date="2026-07-25",
                zip_code="78701",
                format_filter="IMAX",
            )

    assert result["movieId"] == "241283"
    assert len(result["theaters"]) == 1
    assert result["theaters"][0]["name"] == "Violet Crown Austin"
    # Verify CLI args
    args = mock_run.call_args[0][0]
    assert "movie-showtimes" in args
    assert "--movie-id" in args
    assert "241283" in args
    assert "--zip" in args
    assert "78701" in args
    assert "--format" in args
    assert "IMAX" in args


def test_movie_showtimes_latlong(monkeypatch):
    mock_proc = Mock(returncode=0, stdout=json.dumps({"theaters": []}), stderr="")
    with patch("subprocess.run", return_value=mock_proc) as mock_run:
        with patch.object(fandango, "find_fandango_cli", return_value=Path("/fake/fandango.js")):
            fandango.movie_showtimes(
                movie_id="123",
                date="2026-07-25",
                lat=30.2672,
                long=-97.7431,
            )
    args = mock_run.call_args[0][0]
    assert "--lat" in args
    assert "30.2672" in args
    assert "--long" in args
    assert "-97.7431" in args


def test_movie_showtimes_missing_location():
    with pytest.raises(ValueError, match="provide zip_code OR lat/long"):
        fandango.movie_showtimes(movie_id="123", date="2026-07-25")


def test_movie_showtimes_missing_movie_id():
    with pytest.raises(ValueError, match="movie_id is required"):
        fandango.movie_showtimes(movie_id="", date="2026-07-25", zip_code="78701")


# ── theater_showtimes ──

def test_theater_showtimes(monkeypatch):
    fake_output = {
        "date": "2026-07-25",
        "theater": {"id": "aawjb", "name": "Violet Crown Austin"},
        "movies": [
            {"id": "241283", "title": "The Odyssey (2026)", "showtimes": []}
        ],
    }
    mock_proc = Mock(returncode=0, stdout=json.dumps(fake_output), stderr="")
    with patch("subprocess.run", return_value=mock_proc):
        with patch.object(fandango, "find_fandango_cli", return_value=Path("/fake/fandango.js")):
            result = fandango.theater_showtimes(
                theater_id="aawjb", date="2026-07-25", movie_id="241283", format_filter="IMAX"
            )
    assert result["theater"]["id"] == "aawjb"


def test_theater_showtimes_missing_id():
    with pytest.raises(ValueError, match="theater_id is required"):
        fandango.theater_showtimes(theater_id="")


# ── theater_calendar ──

def test_theater_calendar(monkeypatch):
    fake_output = {
        "theaterId": "aawjb",
        "dates": [{"date": "2026-07-25", "hasShowtime": True}],
    }
    mock_proc = Mock(returncode=0, stdout=json.dumps(fake_output), stderr="")
    with patch("subprocess.run", return_value=mock_proc) as mock_run:
        with patch.object(fandango, "find_fandango_cli", return_value=Path("/fake/fandango.js")):
            result = fandango.theater_calendar("aawjb", start_date="2026-07-25")
    assert result["theaterId"] == "aawjb"
    args = mock_run.call_args[0][0]
    assert "theater-calendar" in args
    assert "--start-date" in args
    assert "2026-07-25" in args


# ── seat_map ──

def test_seat_map(monkeypatch):
    fake_output = {
        "theaterId": "aawjb",
        "theaterName": "Violet Crown Austin",
        "totalSeatCount": 55,
        "availableSeatCount": 44,
        "takenSeatCount": 11,
        "seats": [
            {"id": "1-1", "row": "1", "column": 1, "status": "A", "isAvailable": True, "isWheelchair": False},
            {"id": "1-2", "row": "1", "column": 2, "status": "X", "isAvailable": False, "isWheelchair": False},
        ],
    }
    mock_proc = Mock(returncode=0, stdout=json.dumps(fake_output), stderr="")
    with patch("subprocess.run", return_value=mock_proc):
        with patch.object(fandango, "find_fandango_cli", return_value=Path("/fake/fandango.js")):
            result = fandango.seat_map("v2-abc123")
    assert result["availableSeatCount"] == 44
    assert result["totalSeatCount"] == 55
    assert len(result["seats"]) == 2


def test_seat_map_missing_hash():
    with pytest.raises(ValueError, match="showtime_hash_code is required"):
        fandango.seat_map("")


# ── subprocess error handling ──

def test_run_fandango_cli_failure(monkeypatch):
    """CLI returns non-zero exit code."""
    mock_proc = Mock(returncode=1, stdout="", stderr="movie not found")
    with patch("subprocess.run", return_value=mock_proc):
        with patch.object(fandango, "find_fandango_cli", return_value=Path("/fake/fandango.js")):
            with pytest.raises(RuntimeError, match=r"fandango CLI failed.*exit 1.*movie not found"):
                fandango.search_movies("test")


def test_run_fandango_invalid_json(monkeypatch):
    """CLI returns invalid JSON."""
    mock_proc = Mock(returncode=0, stdout="not json {{{", stderr="")
    with patch("subprocess.run", return_value=mock_proc):
        with patch.object(fandango, "find_fandango_cli", return_value=Path("/fake/fandango.js")):
            with pytest.raises(RuntimeError, match="returned invalid JSON"):
                fandango.search_movies("test")


def test_run_fandango_timeout(monkeypatch):
    """CLI times out."""
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="node", timeout=20.0)):
        with patch.object(fandango, "find_fandango_cli", return_value=Path("/fake/fandango.js")):
            with pytest.raises(RuntimeError, match="timed out after"):
                fandango.search_movies("test")
