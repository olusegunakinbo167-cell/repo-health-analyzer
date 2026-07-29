"""Organization-level health score aggregation."""

from __future__ import annotations

import statistics
from collections import Counter
from datetime import UTC, datetime

from .models import (
    HealthScore,
    OrgHealthSummary,
    OrgRepoScore,
    RepoMetrics,
)


def aggregate_org_health(
    results: list[tuple[RepoMetrics, HealthScore]],
    org: str,
    *,
    failed_count: int = 0,
    top_n: int = 10,
) -> OrgHealthSummary:
    """Aggregate per-repo health scores into an organization-level summary.

    Args:
        results: List of (RepoMetrics, HealthScore) pairs for successfully analyzed repos.
        org: Organization / user login name.
        failed_count: Number of repos that failed analysis (excluded from results).
        top_n: Number of repos to include in top/bottom rankings.

    Returns:
        OrgHealthSummary with score distributions, category averages, and repo rankings.
    """
    if not results:
        return OrgHealthSummary(
            org=org,
            total_repos=failed_count,
            analyzed_repos=0,
            failed_repos=failed_count,
            avg_score=0.0,
            median_score=0.0,
            score_distribution={"A": 0, "B": 0, "C": 0, "D": 0, "F": 0},
            top_repos=[],
            bottom_repos=[],
            category_averages={
                "documentation": 0.0,
                "maintenance": 0.0,
                "ci_cd": 0.0,
                "governance": 0.0,
            },
            missing_files_stats={
                "readme": 0,
                "license": 0,
                "contributing": 0,
                "code_of_conduct": 0,
            },
            ci_adoption_rate=0.0,
            total_stars=0,
            timestamp=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        )

    scores = [h.total_score for _, h in results]
    avg_score = round(statistics.mean(scores), 2)
    median_score = round(statistics.median(scores), 2)

    # Grade distribution
    dist = Counter(h.grade for _, h in results)
    score_distribution = {
        "A": dist.get("A", 0),
        "B": dist.get("B", 0),
        "C": dist.get("C", 0),
        "D": dist.get("D", 0),
        "F": dist.get("F", 0),
    }

    # Build repo score summaries
    repo_scores = [
        OrgRepoScore(
            full_name=m.full_name,
            score=round(h.total_score, 2),
            grade=h.grade,
            stars=m.stars,
            language=m.language,
        )
        for m, h in results
    ]

    # Top / bottom N
    repo_scores_sorted = sorted(repo_scores, key=lambda r: r.score, reverse=True)
    top_repos = repo_scores_sorted[:top_n]
    bottom_repos = list(reversed(repo_scores_sorted[-top_n:]))

    # Category averages
    def cat_avg(attr: str) -> float:
        vals = [getattr(h, attr).score for _, h in results]
        return round(statistics.mean(vals), 2) if vals else 0.0

    category_averages = {
        "documentation": cat_avg("documentation"),
        "maintenance": cat_avg("maintenance"),
        "ci_cd": cat_avg("ci_cd"),
        "governance": cat_avg("governance"),
    }

    # Missing community files (count of repos MISSING each file)
    missing_files_stats = {
        "readme": sum(1 for m, _ in results if not m.community_files.readme),
        "license": sum(1 for m, _ in results if not m.community_files.license),
        "contributing": sum(1 for m, _ in results if not m.community_files.contributing),
        "code_of_conduct": sum(1 for m, _ in results if not m.community_files.code_of_conduct),
    }

    # CI/CD adoption rate (% of repos with at least one workflow)
    ci_count = sum(1 for m, _ in results if m.ci_cd.has_ci)
    ci_adoption_rate = round((ci_count / len(results) * 100.0), 2) if results else 0.0

    total_stars = sum(m.stars for m, _ in results)

    return OrgHealthSummary(
        org=org,
        total_repos=len(results) + failed_count,
        analyzed_repos=len(results),
        failed_repos=failed_count,
        avg_score=avg_score,
        median_score=median_score,
        score_distribution=score_distribution,
        top_repos=top_repos,
        bottom_repos=bottom_repos,
        category_averages=category_averages,
        missing_files_stats=missing_files_stats,
        ci_adoption_rate=ci_adoption_rate,
        total_stars=total_stars,
        timestamp=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    )
