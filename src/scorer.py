"""Repository health scoring engine."""

from __future__ import annotations

from .config import RepoConfig
from .metrics.academic_impact import score_academic_impact_bonus
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

    Default weights (raw):
    - README: 10 pts
    - LICENSE: 5 pts
    - CONTRIBUTING.md: 5 pts
    - CODE_OF_CONDUCT.md: 5 pts
    Total raw: 25 pts (scaled to config weight)

    Academic impact bonus (Option B): up to +5 pts, capped at category max.
    Repos that reference research papers in their docs get a bonus reflecting
    academic grounding.  See metrics.academic_impact.score_academic_impact_bonus.
    """
    config = config or RepoConfig()
    cf = metrics.community_files
    raw_score = 0.0
    penalties: list[str] = []
    recommendations: list[str] = []

    # README — 10 pts
    if cf.readme or config.is_ignored("missing_readme"):
        raw_score += 10.0
    else:
        penalties.append("Missing README file")
        recommendations.append("Add a README.md describing the project, installation, and usage")

    # LICENSE — 5 pts
    if cf.license or config.is_ignored("missing_license"):
        raw_score += 5.0
    else:
        penalties.append("Missing LICENSE file")
        recommendations.append("Add a LICENSE file to clarify usage terms (e.g., MIT, Apache-2.0)")

    # CONTRIBUTING — 5 pts
    if cf.contributing or config.is_ignored("missing_contributing"):
        raw_score += 5.0
    else:
        penalties.append("Missing CONTRIBUTING.md")
        recommendations.append("Add CONTRIBUTING.md with guidelines for contributors")

    # CODE_OF_CONDUCT — 5 pts
    if cf.code_of_conduct or config.is_ignored("missing_code_of_conduct"):
        raw_score += 5.0
    else:
        penalties.append("Missing CODE_OF_CONDUCT.md")
        recommendations.append(
            "Add CODE_OF_CONDUCT.md to set community standards (e.g., Contributor Covenant)"
        )

    # Academic impact bonus (Option B) — up to +5 pts, capped at 25 raw
    academic_impact = getattr(metrics, "academic_impact", None)
    ignore_academic = config.is_ignored("academic_impact") if config else False
    if academic_impact and not ignore_academic:
        bonus, acad_penalties, acad_recs = score_academic_impact_bonus(
            academic_impact
        )
        if bonus > 0:
            raw_score = min(25.0, raw_score + bonus)
            # Add a positive signal (not a penalty)
            n_papers = academic_impact.paper_count
            n_resolved = academic_impact.resolved_count
            if n_resolved > 0:
                recommendations.append(
                    f"Academic impact: {n_resolved} research paper(s) referenced "
                    f"({academic_impact.total_citations} total citations)"
                )
        penalties.extend(acad_penalties)
        recommendations.extend(acad_recs)

    weight = config.weight_for("documentation")
    score = _apply_weight(raw_score, 25.0, weight)

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
    """Score Maintenance based on commit velocity, issue close ratio, bus factor, and code churn.

    Commit velocity (raw 0–15 pts, or 0–10 pts when churn data is available):
      >= 20 commits/90d  → 15 / 10 pts
      >= 10 commits/90d  → 12 / 8 pts
      >=  5 commits/90d  →  8 / 5 pts
      >=  1 commits/90d  →  4 / 2 pts
      ==  0 commits/90d  →  0 pts

    Issue close ratio (raw 0–10 pts):
      ratio >= 0.80 → 10 pts
      ratio >= 0.60 →  7 pts
      ratio >= 0.40 →  4 pts
      ratio <  0.40 →  1 pt
      no issues     →  5 pts (neutral)

    Code churn (raw 0–5 pts, only when churn data is available):
      churn_score <= 25 → 5 pts (low churn, stable)
      churn_score <= 50 → 3 pts
      churn_score <= 75 → 1 pt
      churn_score >  75 → 0 pts (high churn, instability risk)
      Trend: falling → +1 pt, rising → −1 pt

    Bus factor (penalty, 0–5 pts deducted):
      top_author > 70% → −5 pts, high maintainer risk
      top_author <= 70% → 0 pts
      no commit_author data → 0 pts (backwards compat)

    When churn data is unavailable, commit velocity uses the 0–15 pt scale
    and the category totals 25 pts, preserving backwards compatibility with
    existing tests. When churn is available, commit velocity is scaled to
    0–10 pts, churn contributes 0–5 pts, and the total remains 25 pts.
    """
    config = config or RepoConfig()
    maint = metrics.maintenance
    raw_score = 0.0
    penalties: list[str] = []
    recommendations: list[str] = []

    # Detect whether churn data is available — affects commit velocity scaling
    churn = getattr(metrics, "code_churn", None)
    ignore_churn = config.is_ignored("code_churn") if config else False
    churn_available = bool(churn and not ignore_churn and churn.available)

    # Commit velocity — 0–15 pts (legacy) or 0–10 pts (with churn)
    commits = maint.commits_last_90_days
    ignore_low_commit = config.is_ignored("low_commit_activity")
    ignore_no_commits = config.is_ignored("no_commits")

    if churn_available:
        # Scaled 0–10 pt range when churn contributes the remaining 5 pts
        if commits >= 20:
            raw_score += 10.0
        elif commits >= 10:
            raw_score += 8.0
        elif commits >= 5:
            raw_score += 5.0
        elif commits >= 1:
            if ignore_low_commit:
                raw_score += 10.0
            else:
                raw_score += 2.0
                penalties.append(f"Low commit activity: {commits} commit(s) in last 90 days")
                recommendations.append(
                    "Increase commit frequency — aim for at least 5 commits per quarter"
                )
        else:  # 0 commits
            if ignore_no_commits or ignore_low_commit:
                raw_score += 10.0
            else:
                penalties.append("No commits in the last 90 days — repository appears inactive")
                recommendations.append(
                    "Resume active development or archive the repository if no longer maintained"
                )
    else:
        # Legacy 0–15 pt range — preserves backwards compatibility
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

    # Issue close ratio — 0–10 pts (unchanged)
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

    # Code churn — 0–5 pts (only when available)
    if churn_available:
        churn_score = churn.churn_score
        trend = churn.trend

        # Base churn points (lower score = more stable = better)
        if churn_score <= 25:
            churn_points = 5.0
        elif churn_score <= 50:
            churn_points = 3.0
        elif churn_score <= 75:
            churn_points = 1.0
        else:
            churn_points = 0.0

        # Trend adjustment
        if trend == "falling" and churn_points < 5.0:
            churn_points = min(5.0, churn_points + 1.0)
        elif trend == "rising" and churn_points > 0.0:
            churn_points = max(0.0, churn_points - 1.0)

        raw_score += churn_points

        # Surface churn signals
        if churn_score > 50:
            hot_files = churn.hot_files[:3]
            hot_names = ", ".join(f["file"] for f in hot_files) if hot_files else "unknown"
            penalties.append(
                f"High code churn detected (score {churn_score}/100, trend: {trend})"
            )
            recommendations.append(
                f"Investigate churn hotspots: {hot_names} — "
                "frequent changes may indicate unstable areas or technical debt"
            )
        elif churn_score <= 25:
            recommendations.append(
                f"Code churn: low and stable (score {churn_score}/100, trend: {trend})"
            )

        # Rising trend warning (even if absolute score is low)
        if trend == "rising" and churn_score > 25:
            penalties.append(f"Churn trend is rising — instability risk increasing")
            recommendations.append(
                "Review recent changes for root cause of increasing churn — "
                "consider stabilizing high-churn files"
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

    # When churn is unavailable, raw_score max is 25 (15 commit + 10 issue)
    # When churn is available, raw_score max is 25 (10 commit + 10 issue + 5 churn)
    raw_max = 25.0

    weight = config.weight_for("maintenance")
    score = _apply_weight(raw_score, raw_max, weight)

    return CategoryScore(
        name="Maintenance",
        score=score,
        max_score=weight,
        penalties=penalties,
        recommendations=recommendations,
    )


def score_ci_cd(metrics: RepoMetrics, config: RepoConfig | None = None) -> CategoryScore:
    """Score CI/CD & Code Quality.

    Workflow scoring (raw 0–20 pts):
    - 3+ workflows:    20 pts
    - 2 workflows:     15 pts
    - 1 workflow:      10 pts
    - 0 workflows:      0 pts

    Code complexity scoring (raw 0–5 pts):
    - Rating A: 5 pts
    - Rating B: 5 pts
    - Rating C: 3 pts
    - Rating D: 1 pt
    - Rating E: 0 pts
    - Unavailable / not analyzed: 0 pts (score scaled to 25, no penalty)

    Total raw: 25 pts (scaled to config weight)
    """
    config = config or RepoConfig()
    ci = metrics.ci_cd
    raw_score = 0.0
    penalties: list[str] = []
    recommendations: list[str] = []

    ignore_no_ci = config.is_ignored("no_ci")

    # Workflow count — 0–20 pts
    workflow_score = 0.0
    if ci.workflow_count >= 3:
        workflow_score = 20.0
    elif ci.workflow_count == 2:
        workflow_score = 15.0
        recommendations.append(
            "Consider adding additional CI workflows (e.g., security scanning, release automation)"
        )
    elif ci.workflow_count == 1:
        workflow_score = 10.0
        recommendations.append(
            "Add more CI/CD coverage — e.g., linting, testing on multiple platforms, Dependabot"
        )
    else:
        if ignore_no_ci:
            workflow_score = 20.0
        else:
            workflow_score = 0.0
            penalties.append("No GitHub Actions workflows found in .github/workflows/")
            recommendations.append(
                "Set up CI/CD with GitHub Actions — start with a basic test/lint workflow"
            )

    raw_score = workflow_score

    # Code complexity — 0–5 pts
    complexity = getattr(metrics, "code_complexity", None)
    ignore_complexity = config.is_ignored("code_complexity") if config else False

    complexity_points = 0.0
    complexity_available = False

    if complexity and not ignore_complexity and complexity.available:
        complexity_available = True
        rating = complexity.rating
        avg_cc = complexity.avg_complexity
        total_funcs = complexity.total_functions

        if rating in ("A", "B"):
            complexity_points = 5.0
            if total_funcs > 0:
                recommendations.append(
                    f"Code complexity: {rating} — avg CC {avg_cc:.1f} "
                    f"across {total_funcs} function(s)"
                )
        elif rating == "C":
            complexity_points = 3.0
            penalties.append(
                f"Moderate code complexity: rating {rating} "
                f"(avg CC {avg_cc:.1f}, {total_funcs} functions)"
            )
            recommendations.append(
                "Refactor high-complexity functions — aim for CC ≤ 10 per function"
            )
        elif rating == "D":
            complexity_points = 1.0
            penalties.append(
                f"High code complexity: rating {rating} "
                f"(avg CC {avg_cc:.1f}, {total_funcs} functions)"
            )
            recommendations.append(
                "High complexity increases defect risk — refactor complex functions, "
                "add unit tests for high-CC paths"
            )
        else:  # Rating E
            complexity_points = 0.0
            penalties.append(
                f"Very high code complexity: rating {rating} "
                f"(avg CC {avg_cc:.1f}, {total_funcs} functions)"
            )
            recommendations.append(
                "Critical complexity debt — prioritize refactoring high-CC functions "
                "before adding features"
            )

        # Flag individual high-risk functions
        high_risk = complexity.high_risk_functions
        if high_risk:
            n_risk = len(high_risk)
            worst = high_risk[0]
            recommendations.append(
                f"{n_risk} high-risk function(s) with CC > 10 "
                f"(worst: {worst['function']} at CC {worst['cc']} "
                f"in {worst['file']}:{worst['lineno']})"
            )

        raw_score += complexity_points

    # If complexity data is unavailable, scale workflow score to 25-pt range
    # so missing optional dependencies don't penalize the repo
    if not complexity_available:
        raw_max = 25.0
        raw_score = (raw_score / 20.0 * 25.0) if raw_score > 0 else 0.0
    else:
        raw_max = 25.0

    weight = config.weight_for("ci_cd")
    score = _apply_weight(raw_score, raw_max, weight)

    return CategoryScore(
        name="CI/CD & Code Quality",
        score=score,
        max_score=weight,
        penalties=penalties,
        recommendations=recommendations,
    )


def score_governance(
    metrics: RepoMetrics, config: RepoConfig | None = None
) -> CategoryScore:
    """Score Governance based on stale PR ratio and license presence.

    License presence: raw 0–10 pts
      LICENSE present → 10 pts
      LICENSE missing →  0 pts

    Stale PR ratio: raw 0–15 pts
      0 stale PRs                    → 15 pts
      stale / (open+closed) <= 0.10  → 10 pts
      stale / (open+closed) <= 0.25  →  5 pts
      stale / (open+closed) >  0.25  →  0 pts
      no issues/PRs tracked          →  7 pts (neutral)
    """
    config = config or RepoConfig()
    cf = metrics.community_files
    maint = metrics.maintenance

    raw_score = 0.0
    penalties: list[str] = []
    recommendations: list[str] = []

    # License — 10 pts
    ignore_license = config.is_ignored("missing_license")
    if cf.license or ignore_license:
        raw_score += 10.0
    else:
        penalties.append("Repository has no LICENSE file — governance/compliance risk")
        recommendations.append("Add a LICENSE file (MIT, Apache-2.0, GPL-3.0, etc.)")

    # Stale PRs — 15 pts
    total_tracked = maint.open_issues + maint.closed_issues
    stale = maint.stale_prs
    ignore_stale = config.is_ignored("stale_prs")
    ignore_no_issues = config.is_ignored("no_issues_tracked")

    if stale == 0:
        raw_score += 15.0
    elif total_tracked == 0:
        raw_score += 7.0
        if not ignore_no_issues:
            penalties.append("No issues/PRs tracked — cannot assess PR governance")
    else:
        stale_ratio = stale / max(total_tracked, 1)
        if ignore_stale:
            raw_score += 15.0
        elif stale_ratio <= 0.10:
            raw_score += 10.0
        elif stale_ratio <= 0.25:
            raw_score += 5.0
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
    score = _apply_weight(raw_score, 25.0, weight)

    return CategoryScore(
        name="Governance",
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

    total = documentation.score + maintenance.score + ci_cd.score + governance.score

    return HealthScore(
        total_score=round(total, 2),
        documentation=documentation,
        maintenance=maintenance,
        ci_cd=ci_cd,
        governance=governance,
    )
