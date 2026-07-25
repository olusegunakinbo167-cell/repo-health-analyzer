# exporters/__init__.py
"""Report exporters for health analysis results."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from ..models import BaselineDiff, HealthScore, RepoMetrics
from .base import Exporter, PluginStatus, ReportMetadata
from .json_exporter import JSONExporter
from .markdown_exporter import MarkdownExporter

__all__ = [
    "Exporter",
    "PluginStatus",
    "ReportMetadata",
    "JSONExporter",
    "MarkdownExporter",
    "ExporterRegistry",
    "export_report",
    "get_exporter_for_path",
    "detect_format_from_path",
]


# ── Exporter registry ──

ExporterRegistry: dict[str, Exporter] = {
    "json": JSONExporter(),
    "markdown": MarkdownExporter(),
}

# File extension → format name
_EXTENSION_MAP: dict[str, str] = {}
for fmt_name, exporter in ExporterRegistry.items():
    for ext in exporter.file_extensions:
        _EXTENSION_MAP[ext.lower()] = fmt_name


def detect_format_from_path(path: Path | str) -> str | None:
    """Detect export format from a file path extension.

    Returns
    -------
    str | None
        Format name ("json", "markdown") or None if unknown.
    """
    suffix = Path(path).suffix.lower()
    return _EXTENSION_MAP.get(suffix)


def get_exporter_for_path(
    path: Path | str, format_hint: str | None = None
) -> Exporter:
    """Get an exporter for a target output path.

    Parameters
    ----------
    path:
        Output file path. Used to auto-detect format if format_hint is None.
    format_hint:
        Explicit format name ("json", "markdown"). If provided, overrides
        path-based auto-detection.

    Returns
    -------
    Exporter
        The exporter instance.

    Raises
    ------
    ValueError
        If format could not be determined or is not supported.
    """
    fmt = format_hint
    if fmt is None or fmt == "auto":
        fmt = detect_format_from_path(path)

    if fmt is None:
        raise ValueError(
            f"Could not detect export format from path: {path}. "
            f"Supported extensions: {sorted(_EXTENSION_MAP.keys())}. "
            f"Use --format to specify explicitly."
        )

    fmt = fmt.lower()
    try:
        return ExporterRegistry[fmt]
    except KeyError:
        raise ValueError(
            f"Unsupported export format: {fmt}. "
            f"Supported: {', '.join(sorted(ExporterRegistry.keys()))}"
        ) from None


def export_report(
    metrics: RepoMetrics,
    health: HealthScore,
    output_path: Path | str,
    *,
    format: Literal["json", "markdown", "auto"] | str = "auto",
    baseline_diff: BaselineDiff | None = None,
    plugin_statuses: list[PluginStatus] | None = None,
    metadata: ReportMetadata | None = None,
) -> Path:
    """Export a health report to disk.

    Parameters
    ----------
    metrics:
        Repository metrics.
    health:
        Health score.
    output_path:
        Destination file path.
    format:
        Export format name, or "auto" to detect from output_path extension.
    baseline_diff:
        Optional baseline comparison.
    plugin_statuses:
        Optional plugin availability statuses.
    metadata:
        Optional report metadata. If omitted, a default is constructed.

    Returns
    -------
    Path
        The output file path (resolved).
    """
    output_path = Path(output_path)
    exporter = get_exporter_for_path(output_path, format_hint=format)

    # Build default metadata if not provided
    if metadata is None:
        from datetime import UTC, datetime

        metadata = ReportMetadata(
            repository=metrics.full_name,
            commit_sha=metrics.commit_sha,
            timestamp=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        )

    content = exporter.export(
        metrics,
        health,
        baseline_diff=baseline_diff,
        plugin_statuses=plugin_statuses,
        metadata=metadata,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")

    return output_path
