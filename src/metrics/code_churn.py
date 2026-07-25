"""Code churn metric - git history analysis.

Measures how frequently files/lines are modified. High-churn hotspots
indicate unstable areas and maintenance risk. Complements bus factor
(who owns the churn).
"""

import datetime
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

try:
    from git import Repo
    from git.exc import InvalidGitRepositoryError
except ImportError:  # pragma: no cover - exercised in test_churn_missing_dep
    Repo = None  # type: ignore
    InvalidGitRepositoryError = Exception  # type: ignore


def calculate_churn(repo_path: str, window_days: int = 90) -> Dict[str, Any]:
    """
    Calculate code churn from git history.

    Parses git commit history for insertions/deletions per file
    over a rolling window.

    Args:
        repo_path: Path to the git repository to analyze.
        window_days: Lookback window in days (default: 90).

    Returns:
        dict with:
            - available: bool (False if GitPython is not installed)
            - churn_score: int (0-100, normalized)
            - hot_files: List[dict] top 10 files by churn count
            - trend: str ("rising" | "stable" | "falling")
            - total_insertions: int
            - total_deletions: int
            - files_changed: int
    """
    # Fail open if GitPython is not installed
    if Repo is None:
        return {
            "available": False,
            "churn_score": 0,
            "hot_files": [],
            "trend": "stable",
            "total_insertions": 0,
            "total_deletions": 0,
            "files_changed": 0,
        }

    try:
        repo = Repo(repo_path)
    except (InvalidGitRepositoryError, Exception):
        return {
            "available": True,
            "churn_score": 0,
            "hot_files": [],
            "trend": "stable",
            "total_insertions": 0,
            "total_deletions": 0,
            "files_changed": 0,
        }

    # Cutoff date for the analysis window
    since_date = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=window_days)
    since_str = since_date.strftime("%Y-%m-%d")

    try:
        commits = list(repo.iter_commits(since=since_str))
    except Exception:
        commits = []

    if not commits:
        return {
            "available": True,
            "churn_score": 0,
            "hot_files": [],
            "trend": "stable",
            "total_insertions": 0,
            "total_deletions": 0,
            "files_changed": 0,
        }

    # Aggregate churn per file
    file_churn: Dict[str, int] = defaultdict(int)
    total_insertions = 0
    total_deletions = 0

    # For trend detection: split window into first half / second half
    mid_date = since_date + datetime.timedelta(days=window_days / 2)
    churn_first_half = 0
    churn_second_half = 0

    for commit in commits:
        commit_date = commit.committed_datetime
        if commit_date.tzinfo is None:
            commit_date = commit_date.replace(tzinfo=datetime.timezone.utc)

        try:
            stats = commit.stats
            commit_insertions = stats.total.get("insertions", 0)
            commit_deletions = stats.total.get("deletions", 0)
        except Exception:
            commit_insertions = 0
            commit_deletions = 0
            stats_files = {}
        else:
            stats_files = stats.files

        total_insertions += commit_insertions
        total_deletions += commit_deletions
        commit_churn = commit_insertions + commit_deletions

        # Trend bucketing
        if commit_date < mid_date:
            churn_first_half += commit_churn
        else:
            churn_second_half += commit_churn

        # Per-file aggregation
        for filepath, fstat in stats_files.items():
            file_churn[filepath] += fstat.get("insertions", 0) + fstat.get("deletions", 0)

    total_churn = total_insertions + total_deletions

    # Churn score: normalize by repo size
    # Count total lines in tracked Python / source files as a rough repo size
    repo_root = Path(repo_path)
    total_lines = 0
    skip_dirs = {".git", "__pycache__", ".venv", "venv", "node_modules", ".pytest_cache", "build", "dist"}
    for ext in ("*.py", "*.js", "*.ts", "*.go", "*.rs", "*.java", "*.c", "*.cpp", "*.cs"):
        for f in repo_root.rglob(ext):
            if any(part in skip_dirs for part in f.parts):
                continue
            try:
                with f.open("r", encoding="utf-8", errors="ignore") as fh:
                    total_lines += sum(1 for _ in fh)
            except Exception:
                continue

    if total_lines > 0:
        # churn per 1000 LOC, capped at 100
        churn_score = min(100, int((total_churn / total_lines) * 100))
    else:
        churn_score = min(100, total_churn // 10)

    # Top hot files
    hot_files = sorted(
        [{"file": fp, "churn": ch} for fp, ch in file_churn.items()],
        key=lambda x: x["churn"],
        reverse=True,
    )[:10]

    # Trend: compare second half vs first half
    # rising if second_half > first_half * 1.2
    # falling if second_half < first_half * 0.8
    # else stable
    if churn_first_half == 0:
        trend = "rising" if churn_second_half > 0 else "stable"
    else:
        ratio = churn_second_half / churn_first_half
        if ratio > 1.2:
            trend = "rising"
        elif ratio < 0.8:
            trend = "falling"
        else:
            trend = "stable"

    return {
        "available": True,
        "churn_score": churn_score,
        "hot_files": hot_files,
        "trend": trend,
        "total_insertions": total_insertions,
        "total_deletions": total_deletions,
        "files_changed": len(file_churn),
    }
