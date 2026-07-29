"""JSON exporter for organization-level health reports."""

from __future__ import annotations

import dataclasses
import json
from typing import Any

from ..models import HealthScore, OrgHealthSummary, RepoMetrics


class OrgJSONExporter:
    """Export an organization health summary as JSON."""

    format_name = "org-json"
    file_extensions = (".json",)

    def export(
        self,
        summary: OrgHealthSummary,
        results: list[tuple[RepoMetrics, HealthScore]] | None = None,
        *,
        include_per_repo: bool = True,
    ) -> str:
        """Export an org health report as JSON.

        Args:
            summary: Aggregated organization health summary.
            results: Optional per-repo (metrics, health) pairs to include
                in the output under "repositories".
            include_per_repo: If True and results is provided, include
                detailed per-repository scores in the output.

        Returns:
            Pretty-printed JSON report.
        """
        envelope: dict[str, Any] = {
            "organization": summary.org,
            "timestamp": summary.timestamp,
            "summary": {
                "total_repos": summary.total_repos,
                "analyzed_repos": summary.analyzed_repos,
                "failed_repos": summary.failed_repos,
                "total_stars": summary.total_stars,
            },
            "scores": {
                "avg_score": summary.avg_score,
                "median_score": summary.median_score,
                "distribution": summary.score_distribution,
            },
            "category_averages": summary.category_averages,
            "community_files": {
                "missing": summary.missing_files_stats,
            },
            "ci_cd": {
                "adoption_rate": summary.ci_adoption_rate,
            },
            "top_repos": [dataclasses.asdict(r) for r in summary.top_repos],
            "bottom_repos": [dataclasses.asdict(r) for r in summary.bottom_repos],
        }

        if include_per_repo and results:
            repos_out = []
            for metrics, health in results:
                repos_out.append(
                    {
                        "full_name": metrics.full_name,
                        "description": metrics.description,
                        "stars": metrics.stars,
                        "language": metrics.language,
                        "score": health.total_score,
                        "grade": health.grade,
                        "categories": {
                            "documentation": health.documentation.score,
                            "maintenance": health.maintenance.score,
                            "ci_cd": health.ci_cd.score,
                            "governance": health.governance.score,
                        },
                        "community_files": dataclasses.asdict(
                            metrics.community_files
                        ),
                        "ci_cd_workflows": metrics.ci_cd.workflow_count,
                    }
                )
            envelope["repositories"] = repos_out

        return json.dumps(envelope, indent=2)
