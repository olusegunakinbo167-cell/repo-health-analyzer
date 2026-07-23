"""Report formatters for health scores."""

from __future__ import annotations

from io import StringIO

from rich.console import Console
from rich.table import Table
from rich.text import Text

from .models import HealthScore, RepoMetrics


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


def render_rich(metrics: RepoMetrics, health: HealthScore) -> str:
    """Render a Rich-formatted terminal report. Returns the rendered string."""
    buf = StringIO()
    console = Console(file=buf, force_terminal=True, color_system="truecolor", width=100)

    # Header
    console.print()
    console.print(
        f"[bold]Health Report for {metrics.full_name}[/bold]",
        style="cyan",
    )
    console.print(f"Description: {metrics.description or '(none)'}")
    console.print(f"Stars: {metrics.stars}  •  Language: {metrics.language or 'unknown'}  •  "
                  f"Branch: {metrics.default_branch}")
    console.print()

    # Overall score
    score_color = _score_style(health.total_score)
    console.print(
        Text(
            f"Overall Health Score: {health.total_score:.1f} / 100  "
            f"(Grade: {health.grade})",
            style=f"bold {score_color}",
        )
    )
    console.print()

    # Category breakdown table
    table = Table(show_header=True, header_style="bold")
    table.add_column("Category", style="bold", width=16)
    table.add_column("Score", justify="right", width=12)
    table.add_column("Status", justify="center", width=10)
    table.add_column("Issues", width=60)

    for cat in (
        health.documentation,
        health.maintenance,
        health.ci_cd,
        health.governance,
    ):
        pct = cat.percentage
        status = "✓" if pct >= 80 else "⚠" if pct >= 60 else "✗"
        color = _category_score_style(cat.score, cat.max_score)
        score_text = f"[{color}]{cat.score:.1f} / {cat.max_score:.0f}[/{color}]"
        issues = "; ".join(cat.penalties) if cat.penalties else "—"
        table.add_row(cat.name, score_text, f"[{color}]{status}[/{color}]", issues)

    console.print(table)
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
    console.print()

    return buf.getvalue()


def render_markdown(metrics: RepoMetrics, health: HealthScore) -> str:
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
    lines.append(f"**Description:** {metrics.description or '_none_'}  ")
    lines.append(f"**Stars:** {metrics.stars}  |  "
                 f"**Language:** {metrics.language or 'unknown'}  |  "
                 f"**Branch:** `{metrics.default_branch}`")
    lines.append("")
    lines.append(f"### Overall Score: {health.total_score:.1f} / 100 — Grade **{health.grade}**")
    lines.append("")

    # Category breakdown table
    lines.append("| Category | Score | Status |")
    lines.append("|---|---:|---|")
    for cat in (
        health.documentation,
        health.maintenance,
        health.ci_cd,
        health.governance,
    ):
        pct = cat.percentage
        status = "✅" if pct >= 80 else "⚠️" if pct >= 60 else "❌"
        lines.append(f"| {cat.name} | {cat.score:.1f} / {cat.max_score:.0f} | {status} |")
    lines.append("")

    # Collapsible diagnostics per category
    for cat in (
        health.documentation,
        health.maintenance,
        health.ci_cd,
        health.governance,
    ):
        pct = cat.percentage
        icon = "✅" if pct >= 80 else "⚠️" if pct >= 60 else "❌"
        lines.append("<details>")
        summary = (
            f"<summary><b>{icon} {cat.name} — "
            f"{cat.score:.1f} / {cat.max_score:.0f}</b></summary>"
        )
        lines.append(summary)
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
    lines.append("")
    lines.append("</details>")
    lines.append("")

    lines.append("---")
    lines.append("_Generated by repo-health-analyzer_")
    lines.append("")

    return "\n".join(lines)
