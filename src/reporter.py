"""Report formatters for health scores."""

from __future__ import annotations

from io import StringIO

from rich.console import Console
from rich.table import Table
from rich.text import Text

from .models import BaselineDiff, HealthScore, RepoMetrics


def _score_style(score: float) -> str:
    """Color style for a 0–100 score."""
    if score >= 80:
        return "green"
    if score >= 60:
        return "yellow"
    return "red"


def _category_score_style(score: float, max_score: float = 25.0) -> str:
    """Color style for a category score (scaled to 0–100)."""
    pct = (score / max_score * 100.0) if max_score else 0.0
    return _score_style(pct)


def _delta_style(delta: float) -> str:
    if delta > 0.5:
        return "green"
    if delta < -0.5:
        return "red"
    return "dim"


def render_rich(
    metrics: RepoMetrics,
    health: HealthScore,
    baseline_diff: BaselineDiff | None = None,
) -> str:
    """Render a Rich-formatted terminal report. Returns the rendered string."""
    buf = StringIO()
    console = Console(file=buf, force_terminal=True, color_system="truecolor", width=100)

    # Header
    console.print()
    console.print(
        f"[bold]Health Report for {metrics.full_name}[/bold]",
        style="cyan",
    )
    desc = metrics.description or "(none)"
    sha = f" @ {metrics.commit_sha[:7]}" if metrics.commit_sha else ""
    console.print(f"Description: {desc}")
    console.print(
        f"Stars: {metrics.stars}  •  Language: {metrics.language or 'unknown'}  •  "
        f"Branch: {metrics.default_branch}{sha}"
    )
    console.print()

    # Overall score
    score_color = _score_style(health.total_score)
    score_text = f"Overall Health Score: {health.total_score:.1f} / 100  (Grade: {health.grade})"
    if baseline_diff:
        d = baseline_diff.delta
        d_color = _delta_style(d)
        sign = "+" if d > 0 else ""
        score_text += f" [{d_color}]({sign}{d:.1f} vs baseline)[/{d_color}]"
    console.print(Text.from_markup(score_text, style=f"bold {score_color}"))
    console.print()

    # Category breakdown table
    has_baseline = baseline_diff is not None
    table = Table(show_header=True, header_style="bold")
    table.add_column("Category", style="bold", width=16)
    table.add_column("Score", justify="right", width=14)
    if has_baseline:
        table.add_column("Δ", justify="right", width=8)
    table.add_column("Status", justify="center", width=8)
    table.add_column("Issues", width=50 if has_baseline else 60)

    cat_keys = ("documentation", "maintenance", "ci_cd", "governance")
    cat_objs = (
        health.documentation,
        health.maintenance,
        health.ci_cd,
        health.governance,
    )

    for key, cat in zip(cat_keys, cat_objs, strict=False):
        pct = cat.percentage
        status = "✓" if pct >= 80 else "⚠" if pct >= 60 else "✗"
        color = _category_score_style(cat.score, cat.max_score)
        score_text = f"[{color}]{cat.score:.1f} / {cat.max_score:.0f}[/{color}]"
        issues = "; ".join(cat.penalties) if cat.penalties else "—"

        row: list[str] = [cat.name, score_text]
        if has_baseline:
            cd = baseline_diff.categories[key]  # type: ignore[index]
            d_color = _delta_style(cd.delta)
            d_sign = "+" if cd.delta > 0 else ""
            delta_text = f"[{d_color}]{d_sign}{cd.delta:.1f}[/{d_color}]"
            row.append(delta_text)
        row.extend([f"[{color}]{status}[/{color}]", issues])
        table.add_row(*row)

    console.print(table)
    console.print()

    # Baseline summary
    if baseline_diff:
        b_commit = baseline_diff.baseline_commit or "unknown"
        b_ts = baseline_diff.baseline_timestamp or ""
        b_short = b_commit[:7] if len(b_commit) > 7 else b_commit
        console.print(
            f"[dim]Baseline: {baseline_diff.baseline_score:.1f} "
            f"({b_short}{' @ ' + b_ts[:10] if b_ts else ''})  "
            f"Δ {baseline_diff.delta:+.1f}[/dim]"
        )
        console.print()

    # Recommendations
    recs = health.all_recommendations()
    if recs:
        # Deduplicate preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for r in recs:
            if r not in seen:
                seen.add(r)
                unique.append(r)
        console.print("[bold]Recommendations[/bold]")
        for i, rec in enumerate(unique, 1):
            console.print(f"  {i}. {rec}")
        console.print()

    # Metrics snapshot
    cf = metrics.community_files
    ci = metrics.ci_cd
    maint = metrics.maintenance
    console.print("[dim]Metrics snapshot:[/dim]")
    console.print(
        f"  Community: README={cf.readme}, LICENSE={cf.license}, "
        f"CONTRIBUTING={cf.contributing}, CoC={cf.code_of_conduct}"
    )
    workflows = ", ".join(ci.workflow_files) or "(none)"
    console.print(f"  CI/CD: {ci.workflow_count} workflow(s) — {workflows}")
    console.print(
        f"  Maintenance: {maint.commits_last_90_days} commits/90d, "
        f"issues {maint.open_issues} open / {maint.closed_issues} closed, "
        f"{maint.stale_prs} stale PR(s)"
    )
    # Academic impact
    academic = getattr(metrics, "academic_impact", None)
    if academic and academic.paper_count > 0:
        fos_str = ", ".join(academic.fields_of_study[:3])
        if len(academic.fields_of_study) > 3:
            fos_str += ", …"
        console.print(
            f"  Academic: {academic.resolved_count}/{academic.paper_count} paper(s) "
            f"resolved, {academic.total_citations} total citations"
            + (f" — {fos_str}" if fos_str else "")
        )
    console.print()

    return buf.getvalue()


def render_markdown(
    metrics: RepoMetrics,
    health: HealthScore,
    baseline_diff: BaselineDiff | None = None,
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

    cat_keys = ("documentation", "maintenance", "ci_cd", "governance")
    cat_objs = (
        health.documentation,
        health.maintenance,
        health.ci_cd,
        health.governance,
    )

    for key, cat in zip(cat_keys, cat_objs, strict=False):
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
            lines.append(f"| {cat.name} | {cat.score:.1f} / {cat.max_score:.0f} | {status} |")
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
    for key, cat in zip(cat_keys, cat_objs, strict=False):
        pct = cat.percentage
        icon = "✅" if pct >= 80 else "⚠️" if pct >= 60 else "❌"
        summary_text = f"<summary><b>{icon} {cat.name} — {cat.score:.1f} / {cat.max_score:.0f}"
        if has_baseline:
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
        lines.append(f"| Workflow files | {', '.join(f'`{w}`' for w in ci.workflow_files)} |")
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
    lines.append("")
    lines.append("</details>")
    lines.append("")

    lines.append("---")
    lines.append("_Generated by repo-health-analyzer_")
    lines.append("")

    return "\n".join(lines)
