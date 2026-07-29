# exporters/markdown_exporter.py
"""Markdown report exporter."""

from __future__ import annotations

from typing import Any

from ..models import BaselineDiff, HealthScore, RepoMetrics
from .base import Exporter, PluginStatus, ReportMetadata


class MarkdownExporter:
    """Export a health report as GitHub-flavored Markdown."""

    format_name = "markdown"
    file_extensions = (".md", ".markdown", ".mdown", ".mkd")

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
        """Export a health report as Markdown.

        Returns
        -------
        str
            GitHub-flavored Markdown report.
        """
        return _render_markdown(
            metrics,
            health,
            baseline_diff=baseline_diff,
            plugin_statuses=plugin_statuses,
            metadata=metadata,
            environment_context=environment_context,
            hn_context=hn_context,
            academic_max_papers=academic_max_papers,
            academic_include_tldr=academic_include_tldr,
            academic_include_unresolved=academic_include_unresolved,
        )


def _render_markdown(
    metrics: RepoMetrics,
    health: HealthScore,
    baseline_diff: BaselineDiff | None = None,
    plugin_statuses: list[PluginStatus] | None = None,
    metadata: ReportMetadata | None = None,
    environment_context: dict[str, Any] | None = None,
    hn_context: dict[str, Any] | None = None,
    academic_max_papers: int = 20,
    academic_include_tldr: bool = True,
    academic_include_unresolved: bool = False,
) -> str:
    """Render a GitHub-flavored Markdown report.

    Includes collapsible diagnostic sections suitable for $GITHUB_STEP_SUMMARY
    or PR comments.
    """

    def badge_color(score: float) -> str:
        if score >= 80:
            return "brightgreen"
        if score >= 60:
            return "yellow"
        return "red"

    overall_color = badge_color(health.total_score)

    lines: list[str] = []
    lines.append(f"## Health Report — `{metrics.full_name}`")
    lines.append("")
    lines.append(
        f"![Score](https://img.shields.io/badge/"
        f"Health-{health.total_score:.0f}--{overall_color}) "
        f"![Grade](https://img.shields.io/badge/Grade-{health.grade}-blue)"
    )
    lines.append("")
    desc = metrics.description or "_none_"
    sha = f" @ `{metrics.commit_sha[:7]}`" if metrics.commit_sha else ""
    lines.append(f"**Description:** {desc}  ")
    lines.append(
        f"**Stars:** {metrics.stars}  |  "
        f"**Language:** {metrics.language or 'unknown'}  |  "
        f"**Branch:** `{metrics.default_branch}`{sha}"
    )
    lines.append("")

    # Overall score with baseline
    score_line = f"### Overall Score: {health.total_score:.1f} / 100 — Grade **{health.grade}**"
    if baseline_diff:
        d = baseline_diff.delta
        arrow = "▲" if d > 0.5 else "▼" if d < -0.5 else "■"
        sign = "+" if d > 0 else ""
        score_line += f"  {arrow} {sign}{d:.1f} vs baseline"
        if baseline_diff.baseline_commit:
            bc = baseline_diff.baseline_commit[:7]
            score_line += f" (`{bc}`)"
    lines.append(score_line)
    lines.append("")

    # Category breakdown table
    has_baseline = baseline_diff is not None
    if has_baseline:
        lines.append("| Category | Score | Δ | Status |")
        lines.append("|---|---:|---:|---|")
    else:
        lines.append("| Category | Score | Status |")
        lines.append("|---|---:|---|")

    cat_keys = ("documentation", "maintenance", "ci_cd", "governance", "academic_impact")
    cat_objs = (
        health.documentation,
        health.maintenance,
        health.ci_cd,
        health.governance,
        health.academic_impact,
    )

    for key, cat in zip(cat_keys, cat_objs, strict=False):
        pct = cat.percentage
        status = "✅" if pct >= 80 else "⚠️" if pct >= 60 else "❌"
        if has_baseline:
            cd = baseline_diff.categories.get(key)
            if cd and cd.delta is not None:
                d_sign = "+" if cd.delta > 0 else ""
                # Show percentage delta if weights differ, otherwise raw delta
                use_pct = (
                    cd.baseline_max_score is not None
                    and abs(cd.max_score - cd.baseline_max_score) > 0.01
                )
                if use_pct and cd.percentage_delta is not None:
                    delta_val = f"{cd.percentage_delta:+.1f}pp"
                else:
                    delta_val = f"{d_sign}{cd.delta:.1f}"
                delta_col = f"{delta_val} {cd.trend}"
            else:
                delta_col = "— new"
            lines.append(
                f"| {cat.name} | {cat.score:.1f} / {cat.max_score:.0f} | "
                f"{delta_col} | {status} |"
            )
        else:
            lines.append(
                f"| {cat.name} | {cat.score:.1f} / {cat.max_score:.0f} | {status} |"
            )
    lines.append("")

    # Baseline summary box
    if baseline_diff:
        lines.append("<details>")
        lines.append("<summary><b>📊 Baseline Comparison</b></summary>")
        lines.append("")
        lines.append("| Metric | Baseline | Current | Δ |")
        lines.append("|---|---:|---:|---:|")
        bs = baseline_diff.baseline_score
        cs = baseline_diff.current_score
        d = baseline_diff.delta
        lines.append(f"| **Overall** | {bs:.1f} | {cs:.1f} | {d:+.1f} |")
        for key in cat_keys:
            cd = baseline_diff.categories[key]
            if cd.baseline is None or cd.delta is None:
                baseline_str = "—"
                delta_str = "new"
            else:
                baseline_str = f"{cd.baseline:.1f}"
                # Show percentage delta if max_score changed
                use_pct = (
                    cd.baseline_max_score is not None
                    and abs(cd.max_score - cd.baseline_max_score) > 0.01
                    and cd.percentage_delta is not None
                )
                if use_pct:
                    delta_str = f"{cd.percentage_delta:+.1f}pp"
                else:
                    delta_str = f"{cd.delta:+.1f}"
            lines.append(
                f"| {cd.name} | {baseline_str} | {cd.current:.1f} | {delta_str} |"
            )
        if baseline_diff.baseline_commit:
            lines.append("")
            lines.append(
                f"_Baseline commit: `{baseline_diff.baseline_commit}`"
                + (
                    f" @ {baseline_diff.baseline_timestamp[:10]}"
                    if baseline_diff.baseline_timestamp
                    else ""
                )
                + "_"
            )
        lines.append("")
        lines.append("</details>")
        lines.append("")

    # Collapsible diagnostics per category
    for key, cat in zip(cat_keys, cat_objs, strict=False):
        pct = cat.percentage
        icon = "✅" if pct >= 80 else "⚠️" if pct >= 60 else "❌"
        summary_text = (
            f"<summary><b>{icon} {cat.name} — {cat.score:.1f} / {cat.max_score:.0f}"
        )
        if has_baseline:
            cd = baseline_diff.categories[key]  # type: ignore[index]
            if cd.delta is not None:
                d_sign = "+" if cd.delta > 0 else ""
                summary_text += f" ({d_sign}{cd.delta:.1f})"
            else:
                summary_text += " (new)"
        summary_text += "</b></summary>"
        lines.append("<details>")
        lines.append(summary_text)
        lines.append("")
        if cat.penalties:
            lines.append("**Issues:**")
            lines.append("")
            for p in cat.penalties:
                lines.append(f"- {p}")
            lines.append("")
        if cat.recommendations:
            lines.append("**Recommendations:**")
            lines.append("")
            for r in cat.recommendations:
                lines.append(f"- {r}")
            lines.append("")
        if not cat.penalties and not cat.recommendations:
            lines.append("_No issues — looking good!_")
            lines.append("")
        lines.append("</details>")
        lines.append("")

    # All recommendations summary
    recs = health.all_recommendations()
    if recs:
        seen: set[str] = set()
        unique: list[str] = []
        for r in recs:
            if r not in seen:
                seen.add(r)
                unique.append(r)
        lines.append("### Action Items")
        lines.append("")
        for i, rec in enumerate(unique, 1):
            lines.append(f"{i}. {rec}")
        lines.append("")

    # Plugin status section
    if plugin_statuses:
        lines.append("### Plugin Status")
        lines.append("")
        lines.append("| Plugin | Available | CLI Path |")
        lines.append("|---|---|---|")
        for ps in plugin_statuses:
            icon = "✅" if ps.available else "❌"
            cli_path = f"`{ps.cli_path}`" if ps.cli_path else "—"
            if ps.error and not ps.available:
                # Truncate long errors for table readability
                err = ps.error[:60] + "…" if len(ps.error) > 60 else ps.error
                cli_path = f"_{err}_"
            lines.append(f"| {ps.name} | {icon} | {cli_path} |")
        lines.append("")

    # Environment context section
    if environment_context:
        lines.append("### Environment Context")
        lines.append("")
        loc = environment_context.get("location", "?")
        lines.append(f"**Location:** `{loc}`")
        lines.append("")
        fc = environment_context.get("forecast")
        if fc:
            temp = fc.get("temperature", "?")
            unit = fc.get("temperatureUnit", "")
            short = fc.get("shortForecast", "?")
            lines.append(f"**Forecast:** {short} — {temp}°{unit}")
            wind = fc.get("windSpeed")
            if wind:
                wind_dir = fc.get("windDirection", "")
                lines.append(f"  <br>Wind: {wind} {wind_dir}")
            lines.append("")
        alerts = environment_context.get("alerts", {})
        alert_count = alerts.get("count", 0) if isinstance(alerts, dict) else 0
        lines.append(f"**Active weather alerts:** {alert_count}")
        if alert_count > 0 and isinstance(alerts, dict):
            for a in alerts.get("alerts", [])[:3]:
                evt = a.get("event", "?")
                sev = a.get("severity", "?")
                lines.append(f"- {evt} [{sev}]")
        lines.append("")
        obs = environment_context.get("observation")
        if obs:
            sid = obs.get("station_id", "?")
            desc = obs.get("textDescription", "?")
            lines.append(f"**Observation ({sid}):** {desc}")
            lines.append("")
        errors = environment_context.get("errors", [])
        if errors:
            lines.append(f"_Weather data errors: {', '.join(errors)}_")
            lines.append("")

    # Hacker News context section
    if hn_context:
        lines.append("### Hacker News Context")
        lines.append("")
        stories = hn_context.get("stories", [])
        story_ids = hn_context.get("top_story_ids", [])
        fetched_at = hn_context.get("fetched_at", "")
        lines.append(f"**Top {len(story_ids)} HN discussions**")
        if fetched_at:
            lines.append(f"  <br>_Fetched: {fetched_at[:19].replace('T', ' ')} UTC_")
        lines.append("")
        for i, s in enumerate(stories[:10], 1):
            title = s.get("title", "?")
            score = s.get("score", "?")
            by = s.get("by", "?")
            comments = s.get("descendants", 0)
            url = s.get("url", "")
            item_id = s.get("id", "")
            hn_url = f"https://news.ycombinator.com/item?id={item_id}" if item_id else ""
            lines.append(f"{i}. **{title}**")
            lines.append(f"   <br>by {by} · {score} points · {comments} comments")
            if url:
                lines.append(f"   <br>[link]({url}) · [HN]({hn_url})")
            elif hn_url:
                lines.append(f"   <br>[HN]({hn_url})")
            lines.append("")
        errors = hn_context.get("errors", [])
        if errors:
            lines.append(f"_HN fetch errors: {', '.join(errors)}_")
            lines.append("")

    # Academic Impact — dedicated section with S2 metadata
    academic = getattr(metrics, "academic_impact", None)
    if academic and academic.paper_count > 0:
        lines.append("### 📚 Academic Impact")
        lines.append("")
        # Impact tier badge
        tier = academic.impact_tier
        tier_emoji = {
            "exceptional": "🌟",
            "high": "🔥",
            "moderate": "📈",
            "low": "📄",
            "none": "—",
        }.get(tier, "📄")
        lines.append(
            f"**Impact Tier:** {tier_emoji} `{tier}`  |  "
            f"**Papers:** {academic.resolved_count}/{academic.paper_count} resolved  |  "
            f"**Citations:** {academic.total_citations:,}"
        )
        lines.append("")
        # Impact metrics table
        lines.append("| Metric | Value |")
        lines.append("|---|---|")
        lines.append(
            f"| Citation velocity | {academic.avg_citation_velocity:.1f} cites/yr (avg) |")
        lines.append(
            f"| Total velocity | {academic.citation_velocity_per_year:.1f} cites/yr |")
        lines.append(f"| h-index | {academic.h_index} |")
        venue_score = academic.venue_prestige_score
        venue_label = (
            "Top-tier" if venue_score >= 0.8
            else "Conference" if venue_score >= 0.6
            else "Mixed" if venue_score >= 0.3
            else "Preprint"
        )
        lines.append(
            f"| Venue prestige | {venue_score:.2f} — {venue_label} |")
        lines.append(
            f"| Influential citations | {academic.total_influential_citations:,} "
            f"({academic.influential_ratio:.0%}) |")
        lines.append(
            f"| Recency-weighted cites | {academic.recency_weighted_citations:.0f} |")
        if academic.fields_of_study:
            fos = ", ".join(academic.fields_of_study[:5])
            if len(academic.fields_of_study) > 5:
                fos += ", …"
            lines.append(f"| Fields of study | {fos} |")
        lines.append(
            f"| Open-access | {academic.open_access_count}/{academic.resolved_count} "
            f"({academic.open_access_ratio:.0%}) |")
        recent = academic.recent_papers_count()
        lines.append(f"| Recent papers (<3yr) | {recent} |")
        lines.append("")
        # Referenced papers with TLDRs
        if academic_include_unresolved:
            papers_to_show = academic.papers_referenced
        else:
            papers_to_show = [
                rp for rp in academic.papers_referenced if rp.s2 is not None
            ]
        # Apply max_papers limit
        if academic_max_papers > 0 and len(papers_to_show) > academic_max_papers:
            papers_to_show = papers_to_show[:academic_max_papers]
            truncated = True
        else:
            truncated = False
        resolved_papers = [rp for rp in papers_to_show if rp.s2 is not None]
        unresolved_count = sum(1 for rp in papers_to_show if rp.s2 is None)
        if papers_to_show:
            total_resolved = academic.resolved_count
            summary_label = f"📖 Referenced Papers ({len(resolved_papers)} shown"
            if unresolved_count > 0:
                summary_label += f", {unresolved_count} unresolved"
            if truncated:
                summary_label += f" — {academic.paper_count - len(papers_to_show)} more not shown"
            summary_label += ")"
            lines.append("<details>")
            lines.append(f"<summary><b>{summary_label}</b></summary>")
            lines.append("")
            for i, rp in enumerate(papers_to_show, 1):
                p = rp.s2
                if not p:
                    # Unresolved paper
                    ref = rp.reference
                    lines.append(f"**{i}. `{ref.id_type}:{ref.paper_id}`** _(unresolved)_  ")
                    lines.append(f"_Source: {ref.source_file}_")
                    lines.append("")
                    continue
                title = p.title or "Untitled"
                year = f" ({p.year})" if p.year else ""
                cites = f"{p.citation_count:,}" if p.citation_count else "0"
                # Build paper links
                links: list[str] = []
                if p.external_ids:
                    arxiv_id = p.external_ids.get("ArXiv")
                    if arxiv_id:
                        links.append(f"[arXiv](https://arxiv.org/abs/{arxiv_id})")
                    doi = p.external_ids.get("DOI")
                    if doi:
                        links.append(f"[DOI](https://doi.org/{doi})")
                if p.open_access_pdf_url:
                    links.append(f"[PDF]({p.open_access_pdf_url})")
                link_str = f" — {' · '.join(links)}" if links else ""
                lines.append(f"**{i}. {title}**{year}{link_str}")
                lines.append("")
                # Authors
                if p.authors:
                    authors_str = ", ".join(p.authors[:4])
                    if len(p.authors) > 4:
                        authors_str += f" _et al._ (+{len(p.authors)-4})"
                    lines.append(f"_{authors_str}_  ")
                # Venue / journal
                venue_parts: list[str] = []
                if p.venue:
                    venue_parts.append(p.venue)
                if p.journal_name and p.journal_name != p.venue:
                    venue_parts.append(p.journal_name)
                if p.publication_types:
                    pt = ", ".join(p.publication_types)
                    venue_parts.append(f"`{pt}`")
                if venue_parts:
                    lines.append(f"{' · '.join(venue_parts)}  ")
                # Citation velocity for this paper
                if p.year:
                    from datetime import datetime as _dt
                    age = max(1, _dt.now().year - p.year + 1)
                    velocity = p.citation_count / age
                    lines.append(
                        f"**{cites} citations** — {velocity:.1f} cites/yr  ")
                else:
                    lines.append(f"**{cites} citations**  ")
                # TLDR
                if academic_include_tldr and p.tldr:
                    lines.append(f"")
                    lines.append(f"> {p.tldr}")
                    lines.append("")
                lines.append("")
            lines.append("</details>")
            lines.append("")

    # Raw metrics — collapsible
    lines.append("<details>")
    lines.append("<summary><b>📊 Raw Metrics</b></summary>")
    lines.append("")
    cf = metrics.community_files
    ci = metrics.ci_cd
    maint = metrics.maintenance
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| README | {'✅' if cf.readme else '❌'} |")
    lines.append(f"| LICENSE | {'✅' if cf.license else '❌'} |")
    lines.append(f"| CONTRIBUTING.md | {'✅' if cf.contributing else '❌'} |")
    lines.append(f"| CODE_OF_CONDUCT.md | {'✅' if cf.code_of_conduct else '❌'} |")
    lines.append(f"| CI/CD workflows | {ci.workflow_count} |")
    if ci.workflow_files:
        lines.append(
            f"| Workflow files | {', '.join(f'`{w}`' for w in ci.workflow_files)} |"
        )
    lines.append(f"| Commits (90d) | {maint.commits_last_90_days} |")
    lines.append(f"| Open issues | {maint.open_issues} |")
    lines.append(f"| Closed issues | {maint.closed_issues} |")
    lines.append(f"| Issue close ratio | {maint.issue_close_ratio:.0%} |")
    lines.append(f"| Stale PRs (>30d) | {maint.stale_prs} |")
    if metrics.commit_sha:
        lines.append(f"| Commit SHA | `{metrics.commit_sha}` |")
    # Academic impact (summary in raw metrics too)
    academic = getattr(metrics, "academic_impact", None)
    if academic and academic.paper_count > 0:
        lines.append(f"| Referenced papers | {academic.paper_count} |")
        lines.append(f"| Resolved papers | {academic.resolved_count} |")
        lines.append(f"| Total citations | {academic.total_citations:,} |")
        lines.append(
            f"| Avg citations/paper | {academic.avg_citations_per_paper:.1f} |"
        )
        lines.append(
            f"| Citation velocity | {academic.avg_citation_velocity:.1f} cites/yr |")
        lines.append(
            f"| h-index | {academic.h_index} |")
        lines.append(
            f"| Venue prestige | {academic.venue_prestige_score:.2f} |")
        lines.append(f"| Impact tier | {academic.impact_tier} |")
        if academic.fields_of_study:
            fos = ", ".join(academic.fields_of_study[:5])
            if len(academic.fields_of_study) > 5:
                fos += ", …"
            lines.append(f"| Fields of study | {fos} |")
        lines.append(
            f"| Open-access papers | {academic.open_access_count} / {academic.resolved_count} |"
        )
        recent = academic.recent_papers_count()
        lines.append(f"| Recent papers (<3yr) | {recent} |")
    lines.append("")
    lines.append("</details>")
    lines.append("")

    # Metadata footer
    if metadata:
        lines.append("---")
        lines.append(
            f"_Generated by repo-health-analyzer v{metadata.tool_version} "
            f"@ {metadata.timestamp[:19].replace('T', ' ')} UTC_"
        )
    else:
        lines.append("---")
        lines.append("_Generated by repo-health-analyzer_")
    lines.append("")

    return "\n".join(lines)
