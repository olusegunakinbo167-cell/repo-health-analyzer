# metrics/hn.py
"""Hacker News discussion context wrapper.

Calls the local OpenClaw Hacker News CLI at
/usr/lib/node_modules/openclaw/dist/extensions/hackernews/skills/hackernews/hackernews
via subprocess. All commands are read-only.

This module provides repository-adjacent HN discussion context — not part of
repository health scoring, but useful for understanding current community
conversations during analysis runs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ._external_cli import ExternalCLI


_HN_CLI = ExternalCLI(
    name="hackernews",
    cli_filename="hackernews",
    env_var="HACKERNEWS_CLI",
    candidates=[
        Path("/usr/lib/node_modules/openclaw/dist/extensions/hackernews/skills/hackernews/hackernews"),
        Path.home() / ".openclaw" / "extensions" / "hackernews" / "hackernews",
    ],
    json_flag="",  # HN CLI outputs JSON by default, no --json flag
    node_required=False,
    python_required=True,
)


def find_hn_cli() -> Path:
    """Locate the hackernews CLI."""
    return _HN_CLI.find_cli()


def _run_hn(args: list[str], timeout: float = 20.0) -> Any:
    """Invoke the hackernews CLI and return parsed JSON output."""
    return _HN_CLI.run_json(args, timeout=timeout, detect_waf_block=False)


# ── Public API ──


def top_stories(limit: int | None = None) -> list[int]:
    """Get top Hacker News story IDs.

    Parameters
    ----------
    limit:
        Maximum number of story IDs to return. If None, return all.

    Returns
    -------
    List of story item IDs, ranked by HN's top-stories algorithm.
    """
    args = ["top-stories"]
    if limit is not None:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        args += ["--limit", str(limit)]
    result = _run_hn(args)
    if isinstance(result, list):
        return result  # type: ignore[return-value]
    return []


def get_item(item_id: int) -> dict[str, Any]:
    """Get a Hacker News item (story, comment, etc.) by ID.

    Parameters
    ----------
    item_id:
        Hacker News item ID.

    Returns
    -------
    Item dict with keys varying by type. Stories typically include:
    id, type, by, time, title, url, score, descendants, kids, etc.
    """
    if not item_id or item_id < 1:
        raise ValueError("item_id is required and must be >= 1")
    return _run_hn(["get-item", "--id", str(item_id)])


def get_user(user_id: str, submitted_limit: int | None = None) -> dict[str, Any]:
    """Get a Hacker News user profile.

    Parameters
    ----------
    user_id:
        Hacker News username.
    submitted_limit:
        Maximum number of submitted item IDs to return in the profile.

    Returns
    -------
    User dict with keys: id, created, karma, about, submitted, etc.
    """
    if not user_id:
        raise ValueError("user_id is required")
    args = ["get-user", "--id", user_id]
    if submitted_limit is not None:
        if submitted_limit < 1:
            raise ValueError("submitted_limit must be >= 1")
        args += ["--submitted-limit", str(submitted_limit)]
    return _run_hn(args)


def new_stories(limit: int | None = None) -> list[int]:
    """Get newest Hacker News story IDs."""
    args = ["new-stories"]
    if limit is not None:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        args += ["--limit", str(limit)]
    result = _run_hn(args)
    return result if isinstance(result, list) else []


def best_stories(limit: int | None = None) -> list[int]:
    """Get best Hacker News story IDs."""
    args = ["best-stories"]
    if limit is not None:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        args += ["--limit", str(limit)]
    result = _run_hn(args)
    return result if isinstance(result, list) else []


def ask_stories(limit: int | None = None) -> list[int]:
    """Get Ask HN story IDs."""
    args = ["ask-stories"]
    if limit is not None:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        args += ["--limit", str(limit)]
    result = _run_hn(args)
    return result if isinstance(result, list) else []


def show_stories(limit: int | None = None) -> list[int]:
    """Get Show HN story IDs."""
    args = ["show-stories"]
    if limit is not None:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        args += ["--limit", str(limit)]
    result = _run_hn(args)
    return result if isinstance(result, list) else []


def job_stories(limit: int | None = None) -> list[int]:
    """Get job posting story IDs."""
    args = ["job-stories"]
    if limit is not None:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        args += ["--limit", str(limit)]
    result = _run_hn(args)
    return result if isinstance(result, list) else []


# ── Digest / context helpers ──


def get_hn_digest(
    top_limit: int = 10, fetch_items: bool = True
) -> dict[str, Any]:
    """Fetch a Hacker News discussion digest.

    Collects top story IDs via top-stories, then optionally fetches full
    item details for each story via get-item.

    Parameters
    ----------
    top_limit:
        Number of top stories to include. Default 10.
    fetch_items:
        If True (default), fetch full item details for each story ID.
        If False, return only the story IDs.

    Returns
    -------
    Dict with keys:
    - top_story_ids: list[int]
    - stories: list[dict] (only if fetch_items=True)
    - fetched_at: ISO-8601 UTC timestamp
    - errors: list[str] (item fetch errors, non-fatal)
    """
    from datetime import UTC, datetime

    fetched_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    story_ids = top_stories(limit=top_limit)

    if not fetch_items:
        return {
            "top_story_ids": story_ids,
            "fetched_at": fetched_at,
        }

    stories: list[dict[str, Any]] = []
    errors: list[str] = []

    for sid in story_ids:
        try:
            item = get_item(sid)
            stories.append(item)
        except Exception as exc:
            errors.append(f"item {sid}: {exc}")
            continue

    digest: dict[str, Any] = {
        "top_story_ids": story_ids,
        "stories": stories,
        "fetched_at": fetched_at,
    }
    if errors:
        digest["errors"] = errors

    return digest
