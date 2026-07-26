# exporters/base.py
"""Exporter contract and shared report data structures."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ..models import BaselineDiff, HealthScore, RepoMetrics


@dataclass(slots=True)
class PluginStatus:
    """Availability / health status for an external CLI plugin."""

    name: str
    available: bool
    version: str | None = None
    cli_path: str | None = None
    error: str | None = None


@dataclass(slots=True)
class ReportMetadata:
    """Metadata included in every exported report."""

    repository: str
    commit_sha: str | None
    timestamp: str
    tool_version: str = "0.2.0"


class Exporter(Protocol):
    """Export a health report to a specific format."""

    format_name: str
    file_extensions: tuple[str, ...]

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
        """Export a health report.

        Returns
        -------
        str
            Rendered report content (JSON string, Markdown, etc.).
        """
        ...
