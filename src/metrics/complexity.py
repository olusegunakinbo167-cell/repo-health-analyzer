"""Cyclomatic complexity metric - AST-based analysis.

Measures independent code paths per function/method. High complexity
implies harder testing and higher defect risk. Maps to SonarQube /
Code Climate quality gates (A–E).
"""

from pathlib import Path
from typing import Any, Dict, List

try:
    from radon.complexity import cc_visit
except ImportError:  # pragma: no cover - exercised in test_complexity_missing_dep
    cc_visit = None  # type: ignore


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
            - available: bool (False if radon is not installed)
            - avg_complexity: float (mean CC across all functions)
            - max_complexity: int (highest CC in repo)
            - high_risk_functions: List[dict] where cc > 10
              each entry: {file: str, function: str, cc: int, lineno: int}
            - rating: str ("A" | "B" | "C" | "D" | "E")
            - total_functions: int
    """
    # Fail open if radon is not installed
    if cc_visit is None:
        return {
            "available": False,
            "avg_complexity": 0.0,
            "max_complexity": 0,
            "high_risk_functions": [],
            "rating": "A",
            "total_functions": 0,
        }

    root = Path(repo_path)
    if not root.exists():
        return {
            "available": True,
            "avg_complexity": 0.0,
            "max_complexity": 0,
            "high_risk_functions": [],
            "rating": "A",
            "total_functions": 0,
        }

    all_cc: List[int] = []
    high_risk: List[Dict[str, Any]] = []

    # Walk for *.py files, skip common noise dirs
    skip_dirs = {
        ".git", "__pycache__", ".venv", "venv", ".pytest_cache",
        "node_modules", ".mypy_cache", ".ruff_cache", "build", "dist",
        ".tox", ".eggs", "htmlcov",
    }

    for py_file in root.rglob("*.py"):
        # Skip files in ignored directories
        if any(part in skip_dirs for part in py_file.parts):
            continue

        try:
            source = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        try:
            results = cc_visit(source)
        except (SyntaxError, Exception):
            # Skip files that radon can't parse
            continue

        rel_path = str(py_file.relative_to(root))

        for item in results:
            cc = item.complexity
            all_cc.append(cc)

            if cc > 10:
                high_risk.append({
                    "file": rel_path,
                    "function": item.name,
                    "cc": cc,
                    "lineno": item.lineno,
                })

    if not all_cc:
        return {
            "available": True,
            "avg_complexity": 0.0,
            "max_complexity": 0,
            "high_risk_functions": [],
            "rating": "A",
            "total_functions": 0,
        }

    avg_cc = sum(all_cc) / len(all_cc)
    max_cc = max(all_cc)

    # Sort high-risk by CC descending, then by file/function
    high_risk.sort(key=lambda x: (-x["cc"], x["file"], x["function"]))

    return {
        "available": True,
        "avg_complexity": round(avg_cc, 2),
        "max_complexity": max_cc,
        "high_risk_functions": high_risk,
        "rating": _complexity_rating(avg_cc),
        "total_functions": len(all_cc),
    }
