# exporters/markdown_exporter.py
"""Markdown report exporter."""

from __future__ import annotations

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
        )


def _render_markdown(
    metrics: RepoMetrics,
    health: HealthScore,
    baseline_diff: BaselineDiff | None = None,
    plugin_statuses: list[PluginStatus] | None = None,
    metadata: ReportMetadata | None = None,
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

    cat_items = list(health.categories().items())

    for key, cat in cat_items:
        pct = cat.percentage
        status = "✅" if pct >= 80 else "⚠️" if pct >= 60 else "❌"
        if has_baseline:
            cd = baseline_diff.categories[key]  # type: ignore[index]
            d_sign = "+" if cd.delta > 0 else ""
            delta_col = f"{d_sign}{cd.delta:.1f} {cd.trend}"
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
        for key, cat in cat_items:
            if key not in baseline_diff.categories:
                continue
            cd = baseline_diff.categories[key]
            lines.append(
                f"| {cd.name} | {cd.baseline:.1f} | {cd.current:.1f} | {cd.delta:+.1f} |"
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
    for key, cat in cat_items:
        pct = cat.percentage
        icon = "✅" if pct >= 80 else "⚠️" if pct >= 60 else "❌"
        summary_text = (
            f"<summary><b>{icon} {cat.name} — {cat.score:.1f} / {cat.max_score:.0f}"
        )
        if has_baseline and key in baseline_diff.categories:  # type: ignore[union-attr]
            cd = baseline_diff.categories[key]  # type: ignore[index]
            d_sign = "+" if cd.delta > 0 else ""
            summary_text += f" ({d_sign}{cd.delta:.1f})"
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
    # Academic impact
    academic = getattr(metrics, "academic_impact", None)
    if academic and academic.paper_count > 0:
        lines.append(f"| Referenced papers | {academic.paper_count} |")
        lines.append(f"| Resolved papers | {academic.resolved_count} |")
        lines.append(f"| Total citations | {academic.total_citations} |")
        lines.append(
            f"| Avg citations/paper | {academic.avg_citations_per_paper:.1f} |"
        )
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
    # Financial impact
    financial = getattr(metrics, "financial", None)
    if financial and financial.tickers:
        lines.append(f"| Backer tickers | {', '.join(financial.tickers)} |")
        lines.append(f"| Backer count | {financial.backer_count} |")
        lines.append(f"| 90d change | {financial.composite_change_pct_90d:+.1f}% |")
        lines.append(f"| Volatility (ann.) | {financial.composite_volatility:.1f}% |")
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
