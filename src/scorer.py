"""Repository health scoring engine."""

from __future__ import annotations

from .config import RepoConfig
from .metrics.bus_factor import calculate_bus_factor
from .models import CategoryScore, HealthScore, RepoMetrics


def _apply_weight(raw_score: float, raw_max: float, target_max: float) -> float:
    """Scale a raw category score to a configured weight."""
    if raw_max == 0:
        return 0.0
    return (raw_score / raw_max) * target_max


def score_documentation(
    metrics: RepoMetrics, config: RepoConfig | None = None
) -> CategoryScore:
    """Score Documentation based on community files.

    Default weights (raw, 20 pt scale):
    - README: 8 pts
    - LICENSE: 4 pts
    - CONTRIBUTING.md: 4 pts
    - CODE_OF_CONDUCT.md: 4 pts
    Total raw: 20 pts (scaled to config weight)
    """
    config = config or RepoConfig()
    cf = metrics.community_files
    raw_score = 0.0
    penalties: list[str] = []
    recommendations: list[str] = []

    # README — 8 pts
    if cf.readme or config.is_ignored("missing_readme"):
        raw_score += 8.0
    else:
        penalties.append("Missing README file")
        recommendations.append("Add a README.md describing the project, installation, and usage")

    # LICENSE — 4 pts
    if cf.license or config.is_ignored("missing_license"):
        raw_score += 4.0
    else:
        penalties.append("Missing LICENSE file")
        recommendations.append("Add a LICENSE file to clarify usage terms (e.g., MIT, Apache-2.0)")

    # CONTRIBUTING — 4 pts
    if cf.contributing or config.is_ignored("missing_contributing"):
        raw_score += 4.0
    else:
        penalties.append("Missing CONTRIBUTING.md")
        recommendations.append("Add CONTRIBUTING.md with guidelines for contributors")

    # CODE_OF_CONDUCT — 4 pts
    if cf.code_of_conduct or config.is_ignored("missing_code_of_conduct"):
        raw_score += 4.0
    else:
        penalties.append("Missing CODE_OF_CONDUCT.md")
        recommendations.append(
            "Add CODE_OF_CONDUCT.md to set community standards (e.g., Contributor Covenant)"
        )

    weight = config.weight_for("documentation")
    score = _apply_weight(raw_score, 20.0, weight)

    return CategoryScore(
        name="Documentation",
        score=score,
        max_score=weight,
        penalties=penalties,
        recommendations=recommendations,
    )


def score_maintenance(
    metrics: RepoMetrics, config: RepoConfig | None = None
) -> CategoryScore:
    """Score Maintenance based on commit velocity, issue close ratio, and bus factor.

    Commit velocity (raw 0–15 pts):
      >= 20 commits/90d  → 15 pts
      >= 10 commits/90d  → 12 pts
      >=  5 commits/90d  →  8 pts
      >=  1 commits/90d  →  4 pts
      ==  0 commits/90d  →  0 pts

    Issue close ratio (raw 0–10 pts):
      ratio >= 0.80 → 10 pts
      ratio >= 0.60 →  7 pts
      ratio >= 0.40 →  4 pts
      ratio <  0.40 →  1 pt
      no issues     →  5 pts (neutral)

    Bus factor (penalty, 0–5 pts deducted):
      top_author > 70% → −5 pts, high maintainer risk
      top_author <= 70% → 0 pts
      no commit_author data → 0 pts (backwards compat)
    """
    config = config or RepoConfig()
    maint = metrics.maintenance
    raw_score = 0.0
    penalties: list[str] = []
    recommendations: list[str] = []

    # Commit velocity
    commits = maint.commits_last_90_days
    ignore_low_commit = config.is_ignored("low_commit_activity")
    ignore_no_commits = config.is_ignored("no_commits")

    if commits >= 20:
        raw_score += 15.0
    elif commits >= 10:
        raw_score += 12.0
    elif commits >= 5:
        raw_score += 8.0
    elif commits >= 1:
        if ignore_low_commit:
            raw_score += 15.0
        else:
            raw_score += 4.0
            penalties.append(f"Low commit activity: {commits} commit(s) in last 90 days")
            recommendations.append(
                "Increase commit frequency — aim for at least 5 commits per quarter"
            )
    else:  # 0 commits
        if ignore_no_commits or ignore_low_commit:
            raw_score += 15.0
        else:
            penalties.append("No commits in the last 90 days — repository appears inactive")
            recommendations.append(
                "Resume active development or archive the repository if no longer maintained"
            )

    # Issue close ratio
    total_issues = maint.open_issues + maint.closed_issues
    ignore_no_issues = config.is_ignored("no_issues_tracked")
    ignore_low_ratio = config.is_ignored("low_issue_close_ratio")

    if total_issues == 0:
        raw_score += 5.0  # neutral
        if not ignore_no_issues:
            penalties.append("No issues tracked — cannot assess issue response health")
            recommendations.append("Enable GitHub Issues to track bugs and feature requests")
    else:
        ratio = maint.issue_close_ratio
        closed = maint.closed_issues
        if ratio >= 0.80:
            raw_score += 10.0
        elif ratio >= 0.60:
            raw_score += 7.0
        elif ratio >= 0.40:
            if ignore_low_ratio:
                raw_score += 10.0
            else:
                raw_score += 4.0
                penalties.append(
                    f"Moderate issue close ratio: {ratio:.0%} "
                    f"({closed} closed / {total_issues} total)"
                )
                recommendations.append("Triage open issues regularly to improve response time")
        else:
            if ignore_low_ratio:
                raw_score += 10.0
            else:
                raw_score += 1.0
                penalties.append(
                    f"Low issue close ratio: {ratio:.0%} "
                    f"({closed} closed / {total_issues} total)"
                )
                recommendations.append(
                    "Close or triage stale issues — a low close ratio signals poor maintenance"
                )

    # Bus factor / maintainer concentration risk
    # Only score if commit_author data is present (backwards compat with existing tests)
    if maint.commit_authors:
        bf = calculate_bus_factor(maint.commit_authors)
        if bf["is_high_risk"]:
            raw_score = max(0.0, raw_score - 5.0)
            top_share = bf["top_author_share"]
            penalties.append(
                f"High maintainer concentration risk (bus factor): "
                f"top author owns {top_share:.0%} of commits"
            )
            recommendations.append(
                "Distribute knowledge across more contributors — "
                "add co-maintainers and document key processes"
            )

    weight = config.weight_for("maintenance")
    score = _apply_weight(raw_score, 25.0, weight)

    return CategoryScore(
        name="Maintenance",
        score=score,
        max_score=weight,
        penalties=penalties,
        recommendations=recommendations,
    )


def score_ci_cd(metrics: RepoMetrics, config: RepoConfig | None = None) -> CategoryScore:
    """Score CI/CD based on workflow file presence.

    Raw scoring:
    - 1+ workflows:     15 pts base
    - 2+ workflows:    +5 pts
    - 3+ workflows:    +5 pts
    - 0 workflows:      0 pts
    """
    config = config or RepoConfig()
    ci = metrics.ci_cd
    raw_score = 0.0
    penalties: list[str] = []
    recommendations: list[str] = []

    ignore_no_ci = config.is_ignored("no_ci")

    if ci.workflow_count >= 3:
        raw_score = 25.0
    elif ci.workflow_count == 2:
        raw_score = 20.0
        recommendations.append(
            "Consider adding additional CI workflows (e.g., security scanning, release automation)"
        )
    elif ci.workflow_count == 1:
        raw_score = 15.0
        recommendations.append(
            "Add more CI/CD coverage — e.g., linting, testing on multiple platforms, Dependabot"
        )
    else:
        if ignore_no_ci:
            raw_score = 25.0
        else:
            raw_score = 0.0
            penalties.append("No GitHub Actions workflows found in .github/workflows/")
            recommendations.append(
                "Set up CI/CD with GitHub Actions — start with a basic test/lint workflow"
            )

    weight = config.weight_for("ci_cd")
    score = _apply_weight(raw_score, 25.0, weight)

    return CategoryScore(
        name="CI/CD",
        score=score,
        max_score=weight,
        penalties=penalties,
        recommendations=recommendations,
    )


def score_governance(
    metrics: RepoMetrics, config: RepoConfig | None = None
) -> CategoryScore:
    """Score Governance based on stale PR ratio and license presence.

    License presence: raw 0–8 pts
      LICENSE present → 8 pts
      LICENSE missing → 0 pts

    Stale PR ratio: raw 0–12 pts
      0 stale PRs                    → 12 pts
      stale / (open+closed) <= 0.10  →  8 pts
      stale / (open+closed) <= 0.25  →  4 pts
      stale / (open+closed) >  0.25  →  0 pts
      no issues/PRs tracked          →  6 pts (neutral)
    Total raw: 20 pts
    """
    config = config or RepoConfig()
    cf = metrics.community_files
    maint = metrics.maintenance

    raw_score = 0.0
    penalties: list[str] = []
    recommendations: list[str] = []

    # License — 8 pts
    ignore_license = config.is_ignored("missing_license")
    if cf.license or ignore_license:
        raw_score += 8.0
    else:
        penalties.append("Repository has no LICENSE file — governance/compliance risk")
        recommendations.append("Add a LICENSE file (MIT, Apache-2.0, GPL-3.0, etc.)")

    # Stale PRs — 12 pts
    total_tracked = maint.open_issues + maint.closed_issues
    stale = maint.stale_prs
    ignore_stale = config.is_ignored("stale_prs")
    ignore_no_issues = config.is_ignored("no_issues_tracked")

    if stale == 0:
        raw_score += 12.0
    elif total_tracked == 0:
        raw_score += 6.0
        if not ignore_no_issues:
            penalties.append("No issues/PRs tracked — cannot assess PR governance")
    else:
        stale_ratio = stale / max(total_tracked, 1)
        if ignore_stale:
            raw_score += 12.0
        elif stale_ratio <= 0.10:
            raw_score += 8.0
        elif stale_ratio <= 0.25:
            raw_score += 4.0
            penalties.append(
                f"{stale} stale PR(s) open >30 days ({stale_ratio:.0%} of tracked items)"
            )
            recommendations.append("Review and close/merge stale pull requests")
        else:
            penalties.append(
                f"{stale} stale PR(s) open >30 days ({stale_ratio:.0%} of tracked items) "
                "— high governance debt"
            )
            recommendations.append(
                "Urgently triage stale PRs — consider closing abandoned PRs or "
                "requesting rebase"
            )

    weight = config.weight_for("governance")
    score = _apply_weight(raw_score, 20.0, weight)

    return CategoryScore(
        name="Governance",
        score=score,
        max_score=weight,
        penalties=penalties,
        recommendations=recommendations,
    )


def score_academic_impact(
    metrics: RepoMetrics, config: RepoConfig | None = None
) -> CategoryScore:
    """Score Academic Impact based on research paper references.

    Scoring rubric (raw 0–10 pts):

    1. Paper presence (0–2.0 pts):
       1 paper → 0.5, 2 → 1.0, 3-5 → 1.5, 6+ → 2.0

    2. Citation impact, age-normalized (0–3.0 pts):
       avg_citation_velocity < 10/yr  → 0
       10–50/yr  → 1.0
       50–150/yr → 2.0
       150+/yr   → 3.0

    3. Influential citation ratio (0–1.5 pts):
       < 5%  → 0
       5–10% → 0.5
       10–20% → 1.0
       20%+  → 1.5

    4. Venue quality (0–1.0 pts):
       venue_prestige_score scaled directly (0.0–1.0)

    5. Recency (0–1.0 pts):
       ≥1 paper < 2yr old → 1.0
       ≥1 paper < 3yr old → 0.5
       else → 0

    6. Open access (0–0.5 pts):
       OA_ratio >= 0.5 → 0.5

    7. Field relevance (0–1.0 pts):
       At least one paper FoS overlaps repo language/domain → 1.0
       (heuristic mapping, best-effort)

    Penalties:
    - unresolved_ratio > 0.3 → −0.5
    - all papers > 5yr old  → −0.5
    - zero influential citations across all papers → −0.5

    Floor: 0, Cap: max_score
    """
    config = config or RepoConfig()
    impact = getattr(metrics, "academic_impact", None)

    penalties: list[str] = []
    recommendations: list[str] = []

    if impact is None or impact.paper_count == 0:
        # No academic impact data — score 0, neutral (not penalized)
        weight = config.weight_for("academic_impact")
        return CategoryScore(
            name="Academic Impact",
            score=0.0,
            max_score=weight,
            penalties=[],
            recommendations=[
                "No research papers referenced in documentation — "
                "consider citing foundational papers if applicable"
            ],
        )

    n = impact.paper_count
    resolved = impact.resolved_count
    raw_score = 0.0

    # 1. Paper presence (0–2.0)
    if n >= 6:
        paper_score = 2.0
    elif n >= 3:
        paper_score = 1.5
    elif n >= 2:
        paper_score = 1.0
    elif n >= 1:
        paper_score = 0.5
    else:
        paper_score = 0.0
    raw_score += paper_score

    # 2. Citation impact, age-normalized (0–3.0)
    vel = impact.avg_citation_velocity
    if vel >= 150:
        citation_score = 3.0
    elif vel >= 50:
        citation_score = 2.0
    elif vel >= 10:
        citation_score = 1.0
    else:
        citation_score = 0.0
    raw_score += citation_score

    # 3. Influential citation ratio (0–1.5)
    ir = impact.influential_ratio
    if ir >= 0.20:
        ir_score = 1.5
    elif ir >= 0.10:
        ir_score = 1.0
    elif ir >= 0.05:
        ir_score = 0.5
    else:
        ir_score = 0.0
    raw_score += ir_score

    # 4. Venue quality (0–1.0)
    venue_score = max(0.0, min(1.0, impact.venue_prestige_score))
    raw_score += venue_score

    # 5. Recency (0–1.0)
    recent_2yr = impact.recent_papers_count(years=2)
    recent_3yr = impact.recent_papers_count(years=3)
    if recent_2yr > 0:
        recency_score = 1.0
    elif recent_3yr > 0:
        recency_score = 0.5
    else:
        recency_score = 0.0
    raw_score += recency_score

    # 6. Open access (0–0.5)
    oa_score = 0.5 if impact.open_access_ratio >= 0.5 else 0.0
    raw_score += oa_score

    # 7. Field relevance (0–1.0)
    # Simple heuristic: map repo language to common FoS
    lang_fos_map = {
        "python": {"computer science", "engineering"},
        "javascript": {"computer science"},
        "typescript": {"computer science"},
        "java": {"computer science", "engineering"},
        "go": {"computer science"},
        "rust": {"computer science", "engineering"},
        "c": {"computer science", "engineering"},
        "c++": {"computer science", "engineering", "physics"},
        "r": {"medicine", "biology", "mathematics"},
        "julia": {"mathematics", "physics", "computer science"},
    }
    repo_lang = (metrics.language or "").lower()
    paper_fos = {f.lower() for f in impact.fields_of_study}
    expected_fos = lang_fos_map.get(repo_lang, set())
    field_relevance_score = 0.0
    if expected_fos & paper_fos:
        field_relevance_score = 1.0
    elif paper_fos:
        # Papers exist but FoS doesn't match language — still give partial credit
        # for having academic grounding at all
        field_relevance_score = 0.5
    raw_score += field_relevance_score

    # Penalties
    if resolved > 0:
        unresolved_ratio = (n - resolved) / n if n else 0
        if unresolved_ratio > 0.3:
            raw_score = max(0.0, raw_score - 0.5)
            penalties.append(
                f"{n - resolved}/{n} referenced paper(s) could not be resolved via Semantic Scholar"
            )

        # All papers > 5yr old?
        recent_5yr = impact.recent_papers_count(years=5)
        if recent_5yr == 0:
            raw_score = max(0.0, raw_score - 0.5)
            penalties.append("All referenced papers are older than 5 years")
            recommendations.append(
                "Referenced papers are all older than 5 years — "
                "check if newer related work exists"
            )

        # Zero influential citations?
        if impact.total_influential_citations == 0:
            raw_score = max(0.0, raw_score - 0.5)
            penalties.append("Referenced papers have zero influential citations")

    # Positive signal / recommendations
    if resolved > 0:
        recommendations.append(
            f"Academic impact: {resolved} research paper(s) referenced "
            f"({impact.total_citations} total citations, h-index {impact.h_index}, "
            f"tier: {impact.impact_tier})"
        )

    if impact.open_access_ratio < 0.5 and resolved >= 2:
        recommendations.append(
            "Consider referencing open-access versions of papers where available"
        )

    # Cap and floor
    raw_score = max(0.0, min(10.0, raw_score))

    weight = config.weight_for("academic_impact")
    score = _apply_weight(raw_score, 10.0, weight)

    return CategoryScore(
        name="Academic Impact",
        score=score,
        max_score=weight,
        penalties=penalties,
        recommendations=recommendations,
    )


def score_repo(metrics: RepoMetrics, config: RepoConfig | None = None) -> HealthScore:
    """Convert RepoMetrics to a HealthScore."""
    config = config or RepoConfig()
    documentation = score_documentation(metrics, config)
    maintenance = score_maintenance(metrics, config)
    ci_cd = score_ci_cd(metrics, config)
    governance = score_governance(metrics, config)
    academic_impact = score_academic_impact(metrics, config)

    total = (
        documentation.score
        + maintenance.score
        + ci_cd.score
        + governance.score
        + academic_impact.score
    )

    return HealthScore(
        total_score=round(total, 2),
        documentation=documentation,
        maintenance=maintenance,
        ci_cd=ci_cd,
        governance=governance,
        academic_impact=academic_impact,
    )
