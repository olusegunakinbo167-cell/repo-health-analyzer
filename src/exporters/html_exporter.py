# exporters/html_exporter.py
"""HTML report exporter."""

from __future__ import annotations

import html
from typing import Any

from ..models import BaselineDiff, HealthScore, RepoMetrics
from .base import Exporter, PluginStatus, ReportMetadata


class HTMLExporter:
    """Export a health report as a self-contained HTML document."""

    format_name = "html"
    file_extensions = (".html", ".htm")

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
    ) -> str:
        """Export a health report as HTML.

        Returns
        -------
        str
            Self-contained HTML report with inline CSS.
        """
        return _render_html(
            metrics,
            health,
            baseline_diff=baseline_diff,
            plugin_statuses=plugin_statuses,
            metadata=metadata,
            environment_context=environment_context,
            hn_context=hn_context,
        )


def _h(text: Any | None) -> str:
    """HTML-escape text."""
    if text is None:
        return ""
    return html.escape(str(text), quote=True)


def _render_html(
    metrics: RepoMetrics,
    health: HealthScore,
    baseline_diff: BaselineDiff | None = None,
    plugin_statuses: list[PluginStatus] | None = None,
    metadata: ReportMetadata | None = None,
    environment_context: dict[str, Any] | None = None,
    hn_context: dict[str, Any] | None = None,
) -> str:
    """Render a self-contained HTML report."""

    def score_color(score: float) -> str:
        if score >= 80:
            return "#22c55e"  # green
        if score >= 60:
            return "#eab308"  # yellow
        return "#ef4444"  # red

    def score_label(score: float) -> str:
        if score >= 80:
            return "Good"
        if score >= 60:
            return "Fair"
        return "Needs Work"

    overall_color = score_color(health.total_score)
    overall_status = score_label(health.total_score)

    # Build category rows
    cat_keys = ("documentation", "maintenance", "ci_cd", "governance")
    cat_objs = (
        health.documentation,
        health.maintenance,
        health.ci_cd,
        health.governance,
    )

    category_rows = []
    for key, cat in zip(cat_keys, cat_objs, strict=False):
        pct = cat.percentage
        color = score_color(pct)
        status_icon = "✓" if pct >= 80 else "⚠" if pct >= 60 else "✗"
        bar_width = max(2, min(100, pct))

        delta_html = ""
        if baseline_diff:
            cd = baseline_diff.categories[key]
            d = cd.delta
            arrow = "▲" if d > 0.5 else "▼" if d < -0.5 else "■"
            sign = "+" if d > 0 else ""
            delta_color = "#22c55e" if d > 0.5 else "#ef4444" if d < -0.5 else "#6b7280"
            delta_html = f'<span style="color:{delta_color};font-weight:600;margin-left:8px">{arrow} {sign}{d:.1f}</span>'

        # Penalties / recommendations
        issues_html = ""
        if cat.penalties or cat.recommendations:
            issues_html += '<ul class="issues">'
            for p in cat.penalties:
                issues_html += f"<li><strong>Issue:</strong> {_h(p)}</li>"
            for r in cat.recommendations:
                issues_html += f"<li><strong>Recommendation:</strong> {_h(r)}</li>"
            issues_html += "</ul>"

        category_rows.append(
            f"""
      <div class="category-card">
        <div class="category-header">
          <span class="category-name">{_h(cat.name)}</span>
          <span class="category-score" style="color:{color}">{cat.score:.1f} / {cat.max_score:.0f} {status_icon}{delta_html}</span>
        </div>
        <div class="progress-track">
          <div class="progress-bar" style="width:{bar_width}%;background:{color}"></div>
        </div>
        {issues_html}
      </div>"""
        )

    # Baseline comparison table
    baseline_html = ""
    if baseline_diff:
        d = baseline_diff.delta
        arrow = "▲" if d > 0.5 else "▼" if d < -0.5 else "■"
        sign = "+" if d > 0 else ""
        baseline_rows = [
            f'<tr><td><strong>Overall</strong></td>'
            f"<td>{baseline_diff.baseline_score:.1f}</td>"
            f"<td>{baseline_diff.current_score:.1f}</td>"
            f"<td><strong>{sign}{d:.1f} {arrow}</strong></td></tr>"
        ]
        for key in cat_keys:
            cd = baseline_diff.categories[key]
            baseline_rows.append(
                f"<tr><td>{_h(cd.name)}</td>"
                f"<td>{cd.baseline:.1f}</td>"
                f"<td>{cd.current:.1f}</td>"
                f"<td>{cd.delta:+.1f} {cd.trend}</td></tr>"
            )
        baseline_commit_html = ""
        if baseline_diff.baseline_commit:
            bc = _h(baseline_diff.baseline_commit[:12])
            ts = ""
            if baseline_diff.baseline_timestamp:
                ts = f" @ {_h(baseline_diff.baseline_timestamp[:10])}"
            baseline_commit_html = f"<p class=\"muted\">Baseline commit: <code>{bc}</code>{ts}</p>"
        baseline_html = f"""
    <section class="card">
      <h2>📊 Baseline Comparison</h2>
      <table class="baseline-table">
        <thead><tr><th>Metric</th><th>Baseline</th><th>Current</th><th>Δ</th></tr></thead>
        <tbody>
          {''.join(baseline_rows)}
        </tbody>
      </table>
      {baseline_commit_html}
    </section>"""

    # Plugin status
    plugin_html = ""
    if plugin_statuses:
        plugin_rows = []
        for ps in plugin_statuses:
            icon = "✓" if ps.available else "✗"
            color = "#22c55e" if ps.available else "#ef4444"
            cli_path = _h(ps.cli_path) if ps.cli_path else "—"
            if ps.error and not ps.available:
                err = _h(ps.error[:80] + ("…" if len(ps.error) > 80 else ""))
                cli_path = f'<span class="muted">{err}</span>'
            plugin_rows.append(
                f'<tr><td>{_h(ps.name)}</td>'
                f'<td style="color:{color};font-weight:600">{icon}</td>'
                f'<td><code>{cli_path}</code></td></tr>'
            )
        plugin_html = f"""
    <section class="card">
      <h2>Plugin Status</h2>
      <table class="plugin-table">
        <thead><tr><th>Plugin</th><th>Available</th><th>CLI Path</th></tr></thead>
        <tbody>{''.join(plugin_rows)}</tbody>
      </table>
    </section>"""

    # Environment / weather context
    weather_html = ""
    if environment_context:
        loc = _h(environment_context.get("location", "?"))
        fc = environment_context.get("forecast") or {}
        alerts = environment_context.get("alerts", {}) or {}
        obs = environment_context.get("observation") or {}

        forecast_html = ""
        if fc:
            temp = _h(fc.get("temperature", "?"))
            unit = _h(fc.get("temperatureUnit", ""))
            short = _h(fc.get("shortForecast", "?"))
            detailed = _h(fc.get("detailedForecast", ""))
            wind = fc.get("windSpeed", "")
            wind_dir = fc.get("windDirection", "")
            wind_html = f"<br>Wind: {_h(wind)} {_h(wind_dir)}" if wind else ""
            forecast_html = f"""
        <p><strong>{short}</strong> — {temp}°{unit}{wind_html}</p>
        <p class="muted">{detailed}</p>"""

        alerts_html = ""
        alert_count = alerts.get("count", 0) if isinstance(alerts, dict) else 0
        if alert_count > 0 and isinstance(alerts, dict):
            alert_items = []
            for a in alerts.get("alerts", [])[:5]:
                evt = _h(a.get("event", "?"))
                sev = _h(a.get("severity", "?"))
                alert_items.append(f"<li><strong>{evt}</strong> [{sev}]</li>")
            if alert_items:
                alerts_html = f"<ul>{''.join(alert_items)}</ul>"

        obs_html = ""
        if obs:
            sid = _h(obs.get("station_id", "?"))
            desc = _h(obs.get("textDescription", "?"))
            obs_html = f"<p><strong>Observation ({sid}):</strong> {desc}</p>"

        errors = environment_context.get("errors", [])
        errors_html = ""
        if errors:
            errors_html = f"<p class=\"muted\">Weather errors: {_h(', '.join(errors))}</p>"

        weather_html = f"""
    <section class="card">
      <h2>🌤️ Environment Context</h2>
      <p><strong>Location:</strong> <code>{loc}</code> &nbsp;|&nbsp; <strong>Active alerts:</strong> {alert_count}</p>
      {forecast_html}
      {alerts_html}
      {obs_html}
      {errors_html}
    </section>"""

    # Hacker News context
    hn_html = ""
    if hn_context:
        stories = hn_context.get("stories", [])
        story_ids = hn_context.get("top_story_ids", [])
        fetched_at = hn_context.get("fetched_at", "")
        fetched_str = ""
        if fetched_at:
            fetched_str = f'<span class="muted">Fetched: {_h(fetched_at[:19].replace("T", " "))} UTC</span>'

        story_items = []
        for i, s in enumerate(stories[:10], 1):
            title = _h(s.get("title", "?"))
            score = s.get("score", "?")
            by = _h(s.get("by", "?"))
            comments = s.get("descendants", 0)
            url = s.get("url", "")
            item_id = s.get("id", "")
            hn_url = f"https://news.ycombinator.com/item?id={item_id}" if item_id else ""

            link_html = ""
            if url:
                link_html = f'<a href="{_h(url)}" target="_blank" rel="noopener">link</a> · '
            if hn_url:
                link_html += f'<a href="{_h(hn_url)}" target="_blank" rel="noopener">HN</a>'

            story_items.append(
                f"""<li class="hn-story">
          <div class="hn-title">{i}. {title}</div>
          <div class="hn-meta">by {by} · {score} points · {comments} comments{(' · ' + link_html) if link_html else ''}</div>
        </li>"""
            )

        errors = hn_context.get("errors", [])
        errors_html = ""
        if errors:
            errors_html = f"<p class=\"muted\">HN fetch errors: {_h(', '.join(errors))}</p>"

        hn_html = f"""
    <section class="card">
      <h2>💬 Hacker News Context</h2>
      <p><strong>Top {len(story_ids)} HN discussions</strong><br>{fetched_str}</p>
      <ol class="hn-list">
        {''.join(story_items)}
      </ol>
      {errors_html}
    </section>"""

    # Raw metrics
    cf = metrics.community_files
    ci = metrics.ci_cd
    maint = metrics.maintenance

    def check(v: bool) -> str:
        return '<span style="color:#22c55e">✓</span>' if v else '<span style="color:#ef4444">✗</span>'

    workflow_files_html = ""
    if ci.workflow_files:
        files = ", ".join(f"<code>{_h(w)}</code>" for w in ci.workflow_files)
        workflow_files_html = f"<tr><td>Workflow files</td><td>{files}</td></tr>"

    commit_sha_html = ""
    if metrics.commit_sha:
        commit_sha_html = f"<tr><td>Commit SHA</td><td><code>{_h(metrics.commit_sha)}</code></td></tr>"

    # Academic impact (optional)
    academic_html = ""
    academic = getattr(metrics, "academic_impact", None)
    if academic and getattr(academic, "paper_count", 0) > 0:
        fos = ", ".join(_h(f) for f in (academic.fields_of_study or [])[:5])
        if len(getattr(academic, "fields_of_study", []) or []) > 5:
            fos += ", …"
        academic_html = f"""
      <tr><td>Referenced papers</td><td>{academic.paper_count}</td></tr>
      <tr><td>Resolved papers</td><td>{academic.resolved_count}</td></tr>
      <tr><td>Total citations</td><td>{academic.total_citations}</td></tr>
      <tr><td>Avg citations/paper</td><td>{academic.avg_citations_per_paper:.1f}</td></tr>
      <tr><td>Fields of study</td><td>{fos}</td></tr>
      <tr><td>Open-access papers</td><td>{academic.open_access_count} / {academic.resolved_count}</td></tr>
      <tr><td>Recent papers (&lt;3yr)</td><td>{academic.recent_papers_count()}</td></tr>"""

    # Metadata footer
    meta_html = "Generated by repo-health-analyzer"
    if metadata:
        ts = _h(metadata.timestamp[:19].replace("T", " "))
        meta_html = f"Generated by repo-health-analyzer v{_h(metadata.tool_version)} @ {ts} UTC"

    # --- Full HTML document ---
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Health Report — {_h(metrics.full_name)}</title>
<style>
  :root {{
    --bg: #f8fafc;
    --card-bg: #ffffff;
    --text: #1e293b;
    --muted: #64748b;
    --border: #e2e8f0;
    --code-bg: #f1f5f9;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #0f172a;
      --card-bg: #1e293b;
      --text: #e2e8f0;
      --muted: #94a3b8;
      --border: #334155;
      --code-bg: #0f172a;
    }}
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    padding: 24px;
  }}
  .container {{ max-width: 860px; margin: 0 auto; }}
  header {{ margin-bottom: 28px; }}
  h1 {{ font-size: 1.6rem; margin-bottom: 6px; }}
  h2 {{ font-size: 1.15rem; margin-bottom: 12px; color: var(--text); }}
  .subtitle {{ color: var(--muted); font-size: 0.9rem; }}
  .subtitle code {{ background: var(--code-bg); padding: 1px 5px; border-radius: 4px; font-size: 0.85em; }}
  .card {{
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 20px 22px;
    margin-bottom: 18px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
  }}
  .score-hero {{
    text-align: center;
    padding: 28px 20px;
  }}
  .score-number {{
    font-size: 3.2rem;
    font-weight: 700;
    line-height: 1.1;
  }}
  .score-label {{
    font-size: 1.05rem;
    color: var(--muted);
    margin-top: 4px;
  }}
  .category-card {{ margin-bottom: 14px; }}
  .category-card:last-child {{ margin-bottom: 0; }}
  .category-header {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 6px;
    font-size: 0.95rem;
  }}
  .category-name {{ font-weight: 600; }}
  .category-score {{ font-variant-numeric: tabular-nums; }}
  .progress-track {{
    height: 8px;
    background: var(--border);
    border-radius: 4px;
    overflow: hidden;
    margin-bottom: 6px;
  }}
  .progress-bar {{ height: 100%; border-radius: 4px; transition: width 0.4s; }}
  .issues {{
    margin: 6px 0 0 18px;
    font-size: 0.88rem;
    color: var(--muted);
  }}
  .issues li {{ margin-bottom: 3px; }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.9rem;
  }}
  th, td {{
    text-align: left;
    padding: 7px 10px;
    border-bottom: 1px solid var(--border);
  }}
  th {{ color: var(--muted); font-weight: 600; font-size: 0.82rem; text-transform: uppercase; letter-spacing: 0.03em; }}
  code {{
    background: var(--code-bg);
    padding: 1px 5px;
    border-radius: 4px;
    font-size: 0.85em;
    font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
  }}
  .muted {{ color: var(--muted); font-size: 0.88rem; }}
  .hn-list {{
    list-style: none;
    padding: 0;
  }}
  .hn-story {{
    padding: 10px 0;
    border-bottom: 1px solid var(--border);
  }}
  .hn-story:last-child {{ border-bottom: none; }}
  .hn-title {{ font-weight: 600; font-size: 0.93rem; margin-bottom: 2px; }}
  .hn-meta {{ color: var(--muted); font-size: 0.82rem; }}
  .hn-meta a {{ color: #3b82f6; text-decoration: none; }}
  .hn-meta a:hover {{ text-decoration: underline; }}
  footer {{
    text-align: center;
    color: var(--muted);
    font-size: 0.82rem;
    margin-top: 24px;
    padding-top: 16px;
    border-top: 1px solid var(--border);
  }}
  a {{ color: #3b82f6; }}
  @media (max-width: 560px) {{
    body {{ padding: 14px; }}
    .card {{ padding: 16px; }}
    .score-number {{ font-size: 2.4rem; }}
  }}
</style>
</head>
<body>
<div class="container">

<header>
  <h1>Health Report — <code>{_h(metrics.full_name)}</code></h1>
  <div class="subtitle">
    {_h(metrics.description or 'No description')} · ⭐ {_h(metrics.stars)} · {_h(metrics.language or 'unknown')}
    · Branch <code>{_h(metrics.default_branch)}</code>
    {f' · Commit <code>{_h(metrics.commit_sha[:12])}</code>' if metrics.commit_sha else ''}
  </div>
</header>

<section class="card score-hero">
  <div class="score-number" style="color:{overall_color}">{health.total_score:.1f} / 100</div>
  <div class="score-label">Grade <strong>{_h(health.grade)}</strong> · {overall_status}</div>
</section>

<section class="card">
  <h2>Category Breakdown</h2>
  {''.join(category_rows)}
</section>

{baseline_html}
{plugin_html}
{weather_html}
{hn_html}

<section class="card">
  <h2>Raw Metrics</h2>
  <table>
    <tbody>
      <tr><td>README</td><td>{check(cf.readme)}</td></tr>
      <tr><td>LICENSE</td><td>{check(cf.license)}</td></tr>
      <tr><td>CONTRIBUTING.md</td><td>{check(cf.contributing)}</td></tr>
      <tr><td>CODE_OF_CONDUCT.md</td><td>{check(cf.code_of_conduct)}</td></tr>
      <tr><td>CI/CD workflows</td><td>{ci.workflow_count}</td></tr>
      {workflow_files_html}
      <tr><td>Commits (90d)</td><td>{maint.commits_last_90_days}</td></tr>
      <tr><td>Open issues</td><td>{maint.open_issues}</td></tr>
      <tr><td>Closed issues</td><td>{maint.closed_issues}</td></tr>
      <tr><td>Issue close ratio</td><td>{maint.issue_close_ratio:.0%}</td></tr>
      <tr><td>Stale PRs (&gt;30d)</td><td>{maint.stale_prs}</td></tr>
      {commit_sha_html}
      {academic_html}
    </tbody>
  </table>
</section>

<footer>{meta_html}</footer>

</div>
</body>
</html>"""
