from collections import Counter
from typing import List, Dict, Any

def calculate_bus_factor(commit_authors: List[str]) -> Dict[str, Any]:
    """
    Calculate bus factor risk from commit author history.

    Args:
        commit_authors: List of commit author identifiers (email/name) from git log.

    Returns:
        dict with bus_factor, top_author_share, is_high_risk, score, etc.
    """
    if not commit_authors:
        return {
            "bus_factor": 0,
            "top_author_share": 0.0,
            "is_high_risk": True,
            "score": 0,
            "unique_authors": 0,
        }

    counts = Counter(commit_authors)
    total = len(commit_authors)
    top_author, top_count = counts.most_common(1)[0]
    top_share = top_count / total

    is_high_risk = top_share > 0.70

    # Basic 0-100 score: penalize concentration.
    # 100 = perfectly distributed, 0 = single author owns everything.
    score = max(0, int(round((1.0 - top_share) / 0.70 * 100))) if top_share < 0.70 else 0

    return {
        "bus_factor": len([a for a, c in counts.items() if c / total >= 0.05]),
        "top_author": top_author,
        "top_author_share": round(top_share, 3),
        "is_high_risk": is_high_risk,
        "score": score,
        "unique_authors": len(counts),
    }
