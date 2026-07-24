"""Cyclomatic complexity metric - AST-based analysis.

Measures independent code paths per function/method. High complexity
implies harder testing and higher defect risk. Maps to SonarQube /
Code Climate quality gates (A–E).
"""

from typing import Any, Dict


# SonarQube-aligned complexity rating thresholds
# Rating: A = avg ≤ 5, B = ≤ 10, C = ≤ 20, D = ≤ 25, E = > 25
_RATING_THRESHOLDS = [
    (5, "A"),
    (10, "B"),
    (20, "C"),
    (25, "D"),
]


def _complexity_rating(avg_cc: float) -> str:
    """Map average cyclomatic complexity to A/B/C/D/E rating."""
    for threshold, rating in _RATING_THRESHOLDS:
        if avg_cc <= threshold:
            return rating
    return "E"


def calculate_complexity(repo_path: str) -> Dict[str, Any]:
    """
    Calculate cyclomatic complexity for a repository.

    Uses radon (cc_visit) for AST-based CC analysis per function.

    Args:
        repo_path: Path to the repository root to scan.

    Returns:
        dict with:
            - avg_complexity: float (mean CC across all functions)
            - max_complexity: int (highest CC in repo)
            - high_risk_functions: List[dict] where cc > 10
              each entry: {file: str, function: str, cc: int, lineno: int}
            - rating: str ("A" | "B" | "C" | "D" | "E")
            - total_functions: int
    """
    # TODO: implement radon.cc_visit analysis
    # from radon.complexity import cc_visit
    # Walk repo_path for *.py files
    # results = cc_visit(source_code)
    # Aggregate per-function CC scores
    # Build high_risk_functions list (cc > 10)
    # Compute avg/max, map to rating
    raise NotImplementedError("calculate_complexity not yet implemented - see issue #3")
