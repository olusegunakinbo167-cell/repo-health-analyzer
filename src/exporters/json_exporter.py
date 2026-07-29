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
        hn_context: dict[str, Any] | None = None,
        # Academic impact export options
        academic_max_papers: int = 20,
        academic_include_tldr: bool = True,
        academic_include_unresolved: bool = False,
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
        metrics_dict = dataclasses.asdict(metrics)
        # Enrich academic_impact with computed properties
        academic = getattr(metrics, "academic_impact", None)
        if academic and "academic_impact" in metrics_dict:
            ai = metrics_dict["academic_impact"]
            if ai is not None:
                # Add computed impact scores
                ai["citation_velocity_per_year"] = academic.citation_velocity_per_year
                ai["avg_citation_velocity"] = academic.avg_citation_velocity
                ai["h_index"] = academic.h_index
                ai["venue_prestige_score"] = academic.venue_prestige_score
                ai["recency_weighted_citations"] = academic.recency_weighted_citations
                ai["impact_tier"] = academic.impact_tier
                ai["influential_ratio"] = academic.influential_ratio
                ai["open_access_ratio"] = academic.open_access_ratio
                # Filter / trim papers_referenced according to export options
                papers = academic.papers_referenced
                # Apply unresolved filter
                if not academic_include_unresolved:
                    papers = [rp for rp in papers if rp.s2 is not None]
                # Apply max_papers limit (0 = unlimited)
                if academic_max_papers > 0 and len(papers) > academic_max_papers:
                    papers = papers[:academic_max_papers]
                # Rebuild papers_referenced in metrics_dict to match filtered list
                if "papers_referenced" in ai:
                    # Map filtered papers back to dict form
                    filtered_dicts = []
                    paper_to_idx = {id(rp): i for i, rp in enumerate(academic.papers_referenced)}
                    for rp in papers:
                        orig_idx = paper_to_idx.get(id(rp))
                        if orig_idx is not None and orig_idx < len(ai["papers_referenced"]):
                            filtered_dicts.append(ai["papers_referenced"][orig_idx])
                    ai["papers_referenced"] = filtered_dicts
                # Enrich resolved papers with S2 metadata
                if "papers_referenced" in ai:
                    for i, rp in enumerate(papers):
                        if i < len(ai["papers_referenced"]) and rp.s2:
                            s2d = ai["papers_referenced"][i].get("s2", {})
                            # Ensure key S2 fields are present and correctly named for export
                            tldr_val = rp.s2.tldr if academic_include_tldr else None
                            s2d.update({
                                "tldr": tldr_val,
                                "publication_types": rp.s2.publication_types or [],
                                "publication_date": rp.s2.publication_date,
                                "journal_name": rp.s2.journal_name,
                                "citation_velocity": rp.s2.citation_velocity,
                                # arXiv link if available
                                "arxiv_id": rp.s2.external_ids.get("ArXiv") if rp.s2.external_ids else None,
                            })
                            # Add arXiv URL if we have an arXiv ID
                            arxiv_id = s2d.get("arxiv_id")
                            if arxiv_id:
                                s2d["arxiv_url"] = f"https://arxiv.org/abs/{arxiv_id}"
                            # Add DOI URL if available
                            doi = rp.s2.external_ids.get("DOI") if rp.s2.external_ids else None
                            if doi:
                                s2d["doi_url"] = f"https://doi.org/{doi}"

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
            "metrics": metrics_dict,
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

        # Hacker News context (optional)
        if hn_context:
            envelope["hn_context"] = hn_context

        return json.dumps(envelope, indent=2)
