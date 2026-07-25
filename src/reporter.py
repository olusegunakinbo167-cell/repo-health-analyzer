# reporter.py
"""Report formatters for health scores.

Note: Markdown export has moved to src/exporters/markdown_exporter.py.
render_markdown() is kept here as a backwards-compat shim.
"""

from __future__ import annotations

from io import StringIO

from rich.console import Console
from rich.table import Table
from rich.text import Text

from .exporters.markdown_exporter import _render_markdown
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

    cat_keys = tuple(health.categories().keys())
    cat_objs = tuple(health.categories().values())

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
    # Financial impact
    financial = getattr(metrics, "financial", None)
    if financial and financial.tickers:
        tickers_str = ", ".join(financial.tickers)
        console.print(
            f"  Financial: {financial.backer_count} backer(s) [{tickers_str}], "
            f"{financial.composite_change_pct_90d:+.1f}% / 90d, "
            f"vol {financial.composite_volatility:.1f}%"
        )
    console.print()

    return buf.getvalue()


def render_markdown(
    metrics: RepoMetrics,
    health: HealthScore,
    baseline_diff: BaselineDiff | None = None,
) -> str:
    """Render a GitHub-flavored Markdown report.

    Backwards-compat shim — delegates to src.exporters.markdown_exporter.

    For new code, prefer:
        from src.exporters import MarkdownExporter
        MarkdownExporter().export(metrics, health, baseline_diff=...)
    """
    return _render_markdown(metrics, health, baseline_diff=baseline_diff)
