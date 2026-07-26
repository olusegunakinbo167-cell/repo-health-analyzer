"""Tests for Hacker News discussion context wrapper."""

import json
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from src.metrics import hn
from src.metrics._external_cli import (
    CLIInvalidJSONError,
    CLITimeoutError,
    ExternalCLIError,
)


# ── CLI discovery ──

def test_find_hn_cli_env_override(tmp_path, monkeypatch):
    fake_cli = tmp_path / "hackernews"
    fake_cli.write_text("#!/usr/bin/env python3\n")
    monkeypatch.setenv("HACKERNEWS_CLI", str(fake_cli))
    # Clear cached path
    hn._HN_CLI._cached_cli_path = None
    try:
        result = hn.find_hn_cli()
        assert result == fake_cli
    finally:
        hn._HN_CLI._cached_cli_path = None


def test_find_hn_cli_not_found(monkeypatch):
    monkeypatch.delenv("HACKERNEWS_CLI", raising=False)
    from src.metrics import hn as hn_mod

    with patch.object(hn_mod._HN_CLI, "candidates", []):
        hn_mod._HN_CLI._cached_cli_path = None
        with patch("shutil.which", return_value=None):
            with pytest.raises(FileNotFoundError, match="hackernews.*CLI.*not found"):
                hn.find_hn_cli()


# ── top_stories ──

def test_top_stories_success(monkeypatch):
    fake_output = [49047453, 49054107, 49051361]
    mock_proc = Mock()
    mock_proc.returncode = 0
    mock_proc.stdout = json.dumps(fake_output)
    mock_proc.stderr = ""

    with patch("subprocess.run", return_value=mock_proc) as mock_run:
        with patch.object(hn._HN_CLI, "find_cli", return_value=Path("/fake/hn")):
            result = hn.top_stories(limit=3)

    assert result == fake_output
    args = mock_run.call_args[0][0]
    assert args[0] == "python3"
    assert args[1] == "/fake/hn"
    assert "top-stories" in args
    assert "--limit" in args
    assert "3" in args


def test_top_stories_no_limit(monkeypatch):
    """top_stories with no limit should omit --limit flag."""
    mock_proc = Mock(returncode=0, stdout="[]", stderr="")
    with patch("subprocess.run", return_value=mock_proc) as mock_run:
        with patch.object(hn._HN_CLI, "find_cli", return_value=Path("/fake/hn")):
            hn.top_stories()
    args = mock_run.call_args[0][0]
    assert "--limit" not in args


def test_top_stories_invalid_limit():
    with pytest.raises(ValueError, match="limit must be >= 1"):
        hn.top_stories(limit=0)


# ── get_item ──

def test_get_item_success(monkeypatch):
    fake_output = {
        "id": 49047453,
        "type": "story",
        "by": "olexsmir",
        "title": "A shell colon does nothing. Use it anyway",
        "score": 134,
        "descendants": 50,
        "url": "https://refp.se/articles/your-shell-and-the-magic-colon",
    }
    mock_proc = Mock(returncode=0, stdout=json.dumps(fake_output), stderr="")
    with patch("subprocess.run", return_value=mock_proc) as mock_run:
        with patch.object(hn._HN_CLI, "find_cli", return_value=Path("/fake/hn")):
            result = hn.get_item(49047453)

    assert result["id"] == 49047453
    assert result["title"] == "A shell colon does nothing. Use it anyway"
    args = mock_run.call_args[0][0]
    assert "get-item" in args
    assert "--id" in args
    assert "49047453" in args


def test_get_item_invalid_id():
    with pytest.raises(ValueError, match="item_id is required"):
        hn.get_item(0)


# ── get_user ──

def test_get_user_success(monkeypatch):
    fake_output = {
        "id": "pg",
        "karma": 157123,
        "created": 1160418092,
        "about": "Founder, Y Combinator",
        "submitted": [123, 456, 789],
    }
    mock_proc = Mock(returncode=0, stdout=json.dumps(fake_output), stderr="")
    with patch("subprocess.run", return_value=mock_proc) as mock_run:
        with patch.object(hn._HN_CLI, "find_cli", return_value=Path("/fake/hn")):
            result = hn.get_user("pg", submitted_limit=3)

    assert result["id"] == "pg"
    assert result["karma"] == 157123
    args = mock_run.call_args[0][0]
    assert "get-user" in args
    assert "--id" in args
    assert "pg" in args
    assert "--submitted-limit" in args
    assert "3" in args


def test_get_user_missing_id():
    with pytest.raises(ValueError, match="user_id is required"):
        hn.get_user("")


# ── other story feeds ──

def test_new_stories(monkeypatch):
    mock_proc = Mock(returncode=0, stdout="[1,2,3]", stderr="")
    with patch("subprocess.run", return_value=mock_proc):
        with patch.object(hn._HN_CLI, "find_cli", return_value=Path("/fake/hn")):
            result = hn.new_stories(limit=5)
    assert result == [1, 2, 3]


def test_best_stories(monkeypatch):
    mock_proc = Mock(returncode=0, stdout="[10,20]", stderr="")
    with patch("subprocess.run", return_value=mock_proc):
        with patch.object(hn._HN_CLI, "find_cli", return_value=Path("/fake/hn")):
            result = hn.best_stories(limit=2)
    assert result == [10, 20]


def test_ask_stories(monkeypatch):
    mock_proc = Mock(returncode=0, stdout="[100]", stderr="")
    with patch("subprocess.run", return_value=mock_proc):
        with patch.object(hn._HN_CLI, "find_cli", return_value=Path("/fake/hn")):
            result = hn.ask_stories()
    assert result == [100]


def test_show_stories(monkeypatch):
    mock_proc = Mock(returncode=0, stdout="[200, 201]", stderr="")
    with patch("subprocess.run", return_value=mock_proc):
        with patch.object(hn._HN_CLI, "find_cli", return_value=Path("/fake/hn")):
            result = hn.show_stories(limit=2)
    assert result == [200, 201]


def test_job_stories(monkeypatch):
    mock_proc = Mock(returncode=0, stdout="[300]", stderr="")
    with patch("subprocess.run", return_value=mock_proc):
        with patch.object(hn._HN_CLI, "find_cli", return_value=Path("/fake/hn")):
            result = hn.job_stories()
    assert result == [300]


# ── get_hn_digest ──

def test_get_hn_digest_success(monkeypatch):
    """Digest fetches top story IDs then get_item for each."""
    # Mock top_stories
    with patch.object(hn, "top_stories", return_value=[111, 222]) as mock_top:
        # Mock get_item
        def fake_get_item(item_id):
            return {"id": item_id, "title": f"Story {item_id}", "score": 100}

        with patch.object(hn, "get_item", side_effect=fake_get_item) as mock_get:
            result = hn.get_hn_digest(top_limit=2, fetch_items=True)

    mock_top.assert_called_once_with(limit=2)
    assert mock_get.call_count == 2
    assert result["top_story_ids"] == [111, 222]
    assert len(result["stories"]) == 2
    assert result["stories"][0]["id"] == 111
    assert "fetched_at" in result
    assert "errors" not in result


def test_get_hn_digest_ids_only(monkeypatch):
    """Digest with fetch_items=False returns IDs only."""
    with patch.object(hn, "top_stories", return_value=[1, 2, 3]):
        with patch.object(hn, "get_item") as mock_get:
            result = hn.get_hn_digest(top_limit=3, fetch_items=False)

    mock_get.assert_not_called()
    assert result["top_story_ids"] == [1, 2, 3]
    assert "stories" not in result


def test_get_hn_digest_partial_failure(monkeypatch):
    """Digest continues on per-item fetch errors."""
    with patch.object(hn, "top_stories", return_value=[111, 222, 333]):
        def fake_get_item(item_id):
            if item_id == 222:
                raise ExternalCLIError("item not found")
            return {"id": item_id, "title": f"Story {item_id}"}

        with patch.object(hn, "get_item", side_effect=fake_get_item):
            result = hn.get_hn_digest(top_limit=3, fetch_items=True)

    # Should have 2 successes, 1 error
    assert len(result["stories"]) == 2
    assert result["stories"][0]["id"] == 111
    assert result["stories"][1]["id"] == 333
    assert "errors" in result
    assert len(result["errors"]) == 1
    assert "222" in result["errors"][0]


# ── error handling ──

def test_hn_cli_failure(monkeypatch):
    """CLI returns non-zero with error."""
    mock_proc = Mock()
    mock_proc.returncode = 1
    mock_proc.stdout = ""
    mock_proc.stderr = "item not found"

    with patch("subprocess.run", return_value=mock_proc):
        with patch.object(hn._HN_CLI, "find_cli", return_value=Path("/fake/hn")):
            with pytest.raises(ExternalCLIError, match="item not found"):
                hn.get_item(99999999)


def test_hn_invalid_json(monkeypatch):
    """CLI returns invalid JSON."""
    mock_proc = Mock(returncode=0, stdout="not json {{{", stderr="")
    with patch("subprocess.run", return_value=mock_proc):
        with patch.object(hn._HN_CLI, "find_cli", return_value=Path("/fake/hn")):
            with pytest.raises(CLIInvalidJSONError, match="returned invalid JSON"):
                hn.top_stories()


def test_hn_timeout(monkeypatch):
    """CLI times out."""
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="hn", timeout=20.0)):
        with patch.object(hn._HN_CLI, "find_cli", return_value=Path("/fake/hn")):
            with pytest.raises(CLITimeoutError, match="timed out"):
                hn.top_stories()
