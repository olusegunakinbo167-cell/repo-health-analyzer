"""Markdown exporter for organization-level health reports."""

from __future__ import annotations

from ..models import HealthScore, OrgHealthSummary, OrgRepoScore, RepoMetrics


class OrgMarkdownExporter:
    """Export an organization health summary as GitHub-flavored Markdown."""

    format_name = "org-markdown"
    file_extensions = (".md", ".markdown")

    def export(
        self,
        summary: OrgHealthSummary,
        results: list[tuple[RepoMetrics, HealthScore]] | None = None,
        *,
        include_per_repo_table: bool = True,
    ) -> str:
        """Export an org health report as Markdown.

        Args:
            summary: Aggregated organization health summary.
            results: Optional per-repo (metrics, health) pairs to render
                a full repository table.
            include_per_repo_table: Include a full sortable table of all repos.

        Returns:
            GitHub-flavored Markdown report.
        """
        return _render_org_markdown(
            summary, results, include_per_repo_table=include_per_repo_table
        )


def _render_org_markdown(
    summary: OrgHealthSummary,
    results: list[tuple[RepoMetrics, HealthScore]] | None = None,
    *,
    include_per_repo_table: bool = True,
) -> str:
    lines: list[str] = []

    # Header
    lines.append(f"# Organization Health Report — `{summary.org}`")
    lines.append("")
    lines.append(
        f"**Analyzed:** {summary.analyzed_repos} / {summary.total_repos} repositories  "
    )
    if summary.failed_repos > 0:
        lines.append(f"**Failed:** {summary.failed_repos}  ")
    lines.append(f"**Total stars:** {summary.total_stars}  ")
    lines.append(f"**Generated:** {summary.timestamp[:19].replace('T', ' ')} UTC")
    lines.append("")

    # Overall scores
    lines.append("## Overall Scores")
    lines.append("")
    lines.append(f"- **Average score:** {summary.avg_score:.1f} / 100")
    lines.append(f"- **Median score:** {summary.median_score:.1f} / 100")
    lines.append("")

    # Score distribution
    dist = summary.score_distribution
    total_graded = sum(dist.values())
    lines.append("### Grade Distribution")
    lines.append("")
    lines.append("| Grade | Count | % |")
    lines.append("|---|---:|---:|")
    for grade in ("A", "B", "C", "D", "F"):
        count = dist.get(grade, 0)
        pct = (count / total_graded * 100.0) if total_graded else 0.0
        bar = "█" * min(int(pct / 5), 20)
        lines.append(f"| **{grade}** | {count} | {pct:.1f}% {bar} |")
    lines.append("")

    # Category averages
    lines.append("### Category Averages")
    lines.append("")
    lines.append("| Category | Avg Score |")
    lines.append("|---|---:|")
    cat_labels = {
        "documentation": "Documentation",
        "maintenance": "Maintenance",
        "ci_cd": "CI/CD",
        "governance": "Governance",
    }
    for key, label in cat_labels.items():
        avg = summary.category_averages.get(key, 0.0)
        lines.append(f"| {label} | {avg:.1f} / 25.0 |")
    lines.append("")

    # Community files heatmap
    lines.append("### Community Files")
    lines.append("")
    lines.append("| File | Missing in N repos |")
    lines.append("|---|---:|")
    file_labels = {
        "readme": "README",
        "license": "LICENSE",
        "contributing": "CONTRIBUTING.md",
        "code_of_conduct": "CODE_OF_CONDUCT.md",
    }
    for key, label in file_labels.items():
        missing = summary.missing_files_stats.get(key, 0)
        lines.append(f"| {label} | {missing} |")
    lines.append("")

    # CI/CD adoption
    lines.append("### CI/CD Adoption")
    lines.append("")
    lines.append(f"**{summary.ci_adoption_rate:.1f}%** of repositories have CI/CD workflows.")
    lines.append("")

    # Top repos
    if summary.top_repos:
        lines.append("### Top Repositories")
        lines.append("")
        lines.append("| Rank | Repository | Score | Grade | Stars | Language |")
        lines.append("|---:|---|---:|---|---|---|")
        for i, r in enumerate(summary.top_repos, 1):
            lang = r.language or "—"
            lines.append(
                f"| {i} | `{r.full_name}` | {r.score:.1f} | {r.grade} | "
                f"{r.stars} | {lang} |"
            )
        lines.append("")

    # Bottom repos
    if summary.bottom_repos:
        lines.append("### Repositories Needing Attention")
        lines.append("")
        lines.append("| Rank | Repository | Score | Grade | Stars | Language |")
        lines.append("|---:|---|---:|---|---|---|")
        for i, r in enumerate(summary.bottom_repos, 1):
            lang = r.language or "—"
            lines.append(
                f"| {i} | `{r.full_name}` | {r.score:.1f} | {r.grade} | "
                f"{r.stars} | {lang} |"
            )
        lines.append("")

    # Full per-repo table
    if include_per_repo_table and results:
        lines.append("## All Repositories")
        lines.append("")
        lines.append("| Repository | Score | Grade | Stars | Language |")
        lines.append("|---|---:|---|---|---|")
        # results are already sorted by score desc from aggregator/batch
        sorted_results = sorted(
            results, key=lambda pair: pair[1].total_score, reverse=True
        )
        for metrics, health in sorted_results:
            lang = metrics.language or "—"
            lines.append(
                f"| `{metrics.full_name}` | {health.total_score:.1f} | "
                f"{health.grade} | {metrics.stars} | {lang} |"
            )
        lines.append("")

    # Footer
    lines.append("---")
    lines.append("_Generated by repo-health-analyzer_")
    lines.append("")

    return "\n".join(lines)


def render_org_index_table(
    results: list[tuple[RepoMetrics, HealthScore]],
) -> str:
    """Render a compact index table of all repositories.

    Suitable for a separate `index.md` file linking to per-repo reports.
    """
    lines: list[str] = []
    lines.append("# Repository Index")
    lines.append("")
    lines.append("| Repository | Score | Grade | Stars | Language |")
    lines.append("|---|---:|---|---|---|")
    sorted_results = sorted(
        results, key=lambda pair: pair[1].total_score, reverse=True
    )
    for metrics, health in sorted_results:
        lang = metrics.language or "—"
        # Link to per-repo markdown file (owner-repo.md convention)
        repo_file = metrics.full_name.replace("/", "-") + ".md"
        repo_link = f"[{metrics.full_name}](repos/{repo_file})"
        lines.append(
            f"| {repo_link} | {health.total_score:.1f} | "
            f"{health.grade} | {metrics.stars} | {lang} |"
        )
    lines.append("")
    return "\n".join(lines)
