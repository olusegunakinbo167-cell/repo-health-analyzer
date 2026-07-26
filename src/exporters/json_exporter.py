# exporters/json_exporter.py
"""JSON report exporter."""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from typing import Any

from ..models import BaselineDiff, HealthScore, RepoMetrics
from .base import Exporter, PluginStatus, ReportMetadata


class JSONExporter:
    """Export a health report as JSON."""

    format_name = "json"
    file_extensions = (".json",)

    def export(
        self,
        metrics: RepoMetrics,
        health: HealthScore,
        *,
        baseline_diff: BaselineDiff | None = None,
        plugin_statuses: list[PluginStatus] | None = None,
        metadata: ReportMetadata | None = None,
        environment_context: dict[str, Any] | None = None,
    ) -> str:
        """Export a health report as JSON.

        Returns
        -------
        str
            Pretty-printed JSON report.
        """
        # Build metadata
        if metadata is None:
            metadata = ReportMetadata(
                repository=metrics.full_name,
                commit_sha=metrics.commit_sha,
                timestamp=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            )

        # Build envelope
        envelope: dict[str, Any] = {
            "metadata": dataclasses.asdict(metadata),
            "repository": {
                "full_name": metrics.full_name,
                "description": metrics.description,
                "stars": metrics.stars,
                "language": metrics.language,
                "default_branch": metrics.default_branch,
                "commit_sha": metrics.commit_sha,
            },
            "metrics": dataclasses.asdict(metrics),
            "health_score": dataclasses.asdict(health),
        }

        # Baseline (optional)
        if baseline_diff:
            envelope["baseline"] = {
                "score": baseline_diff.baseline_score,
                "delta": baseline_diff.delta,
                "commit_sha": baseline_diff.baseline_commit,
                "timestamp": baseline_diff.baseline_timestamp,
                "categories": {
                    key: dataclasses.asdict(cat_delta)
                    for key, cat_delta in baseline_diff.categories.items()
                },
            }

        # Plugin statuses (optional)
        if plugin_statuses:
            envelope["plugins"] = [
                dataclasses.asdict(ps) for ps in plugin_statuses
            ]

        # Environment context (optional)
        if environment_context:
            envelope["environment_context"] = environment_context

        return json.dumps(envelope, indent=2)
