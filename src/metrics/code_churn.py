"""Code churn metric - git history analysis.

Measures how frequently files/lines are modified. High-churn hotspots
indicate unstable areas and maintenance risk. Complements bus factor
(who owns the churn).
"""

from typing import Any, Dict


def calculate_churn(repo_path: str, window_days: int = 90) -> Dict[str, Any]:
    """
    Calculate code churn from git history.

    Parses `git log --numstat` for insertions/deletions per file
    over a rolling window.

    Args:
        repo_path: Path to the git repository to analyze.
        window_days: Lookback window in days (default: 90).

    Returns:
        dict with:
            - churn_score: int (0-100, normalized)
            - hot_files: List[dict] top 10 files by churn count
            - trend: str ("rising" | "stable" | "falling")
            - total_insertions: int
            - total_deletions: int
            - files_changed: int
    """
    # TODO: implement git log --numstat parsing
    # git log --since="90 days ago" --pretty=format:"%H|%ad" --numstat
    # Aggregate per-file insertions + deletions
    # Compute churn_score, hot_files, trend
    raise NotImplementedError("calculate_churn not yet implemented - see issue #3")
