# scorer.py
"""Repository health scoring engine."""

from __future__ import annotations

from .config import RepoConfig
from .definitions import resolve, resolve_finding
from .metrics.academic_impact import score_academic_impact_bonus
from .metrics.bus_factor import calculate_bus_factor
from .models import CategoryScore, Finding, HealthScore, RepoMetrics


def _apply_weight(raw_score: float, raw_max: float, target_max: float) -> float:
    """Scale a raw category score to a configured weight."""
    if raw_max == 0:
        return 0.0
    return (raw_score / raw_max) * target_max


def _append_finding(
    findings: list[Finding],
    penalties: list[str],
    recommendations: list[str],
    finding: Finding,
    *,
    add_penalty: bool = True,
    add_recommendation: bool = True,
) -> None:
    """Append a finding to findings list and mirror to string lists (BC).

    Parameters
    ----------
    findings: list to append Finding to
    penalties: list to append message to (if add_penalty)
    recommendations: list to append recommendation to (if add_recommendation)
    finding: the Finding object
    add_penalty: whether to mirror finding.message into penalties
    add_recommendation: whether to mirror finding.recommendation into recommendations
    """
    findings.append(finding)
    if add_penalty:
        penalties.append(finding.message)
    if add_recommendation and finding.recommendation:
        recommendations.append(finding.recommendation)


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
    findings: list[Finding] = []

    # README — 10 pts
    if cf.readme or config.is_ignored("missing_readme"):
        raw_score += 10.0
    else:
        f = resolve_finding("documentation", "missing_readme")
        _append_finding(findings, penalties, recommendations, f)

    # LICENSE — 5 pts
    if cf.license or config.is_ignored("missing_license"):
        raw_score += 5.0
    else:
        f = resolve_finding("documentation", "missing_license")
        _append_finding(findings, penalties, recommendations, f)

    # CONTRIBUTING — 5 pts
    if cf.contributing or config.is_ignored("missing_contributing"):
        raw_score += 5.0
    else:
        f = resolve_finding("documentation", "missing_contributing")
        _append_finding(findings, penalties, recommendations, f)

    # CODE_OF_CONDUCT — 5 pts
    if cf.code_of_conduct or config.is_ignored("missing_code_of_conduct"):
        raw_score += 5.0
    else:
        f = resolve_finding("documentation", "missing_code_of_conduct")
        _append_finding(findings, penalties, recommendations, f)

    # Academic impact bonus (Option B) — up to +5 pts, capped at 25 raw
    academic_impact = getattr(metrics, "academic_impact", None)
    ignore_academic = config.is_ignored("academic_impact") if config else False
    if academic_impact and not ignore_academic:
        bonus, acad_penalties, acad_recs, acad_findings = score_academic_impact_bonus(
            academic_impact
        )
        if bonus > 0:
            raw_score = min(25.0, raw_score + bonus)
            # Add a positive signal (not a penalty)
            n_resolved = academic_impact.resolved_count
            if n_resolved > 0:
                pf = resolve_finding(
                    "academic_impact",
                    "papers_found",
                    resolved=n_resolved,
                    total_citations=academic_impact.total_citations,
                )
                # Positive finding — add to findings and recommendations only
                findings.append(pf)
                recommendations.append(pf.message)
        # Merge academic findings
        findings.extend(acad_findings)
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
        findings=findings,
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
    findings: list[Finding] = []

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
            f = resolve_finding(
                "maintenance", "low_commit_activity", commits=commits
            )
            _append_finding(findings, penalties, recommendations, f)
    else:  # 0 commits
        if ignore_no_commits or ignore_low_commit:
            raw_score += 15.0
        else:
            f = resolve_finding("maintenance", "no_commits")
            _append_finding(findings, penalties, recommendations, f)

    # Issue close ratio
    total_issues = maint.open_issues + maint.closed_issues
    ignore_no_issues = config.is_ignored("no_issues_tracked")
    ignore_low_ratio = config.is_ignored("low_issue_close_ratio")

    if total_issues == 0:
        raw_score += 5.0  # neutral
        if not ignore_no_issues:
            f = resolve_finding("maintenance", "no_issues_tracked")
            _append_finding(findings, penalties, recommendations, f)
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
                f = resolve_finding(
                    "maintenance",
                    "low_issue_close_ratio",
                    ratio=ratio,
                    closed=closed,
                    total=total_issues,
                )
                _append_finding(findings, penalties, recommendations, f)
        else:
            if ignore_low_ratio:
                raw_score += 10.0
            else:
                raw_score += 1.0
                f = resolve_finding(
                    "maintenance",
                    "low_issue_close_ratio",
                    ratio=ratio,
                    closed=closed,
                    total=total_issues,
                )
                _append_finding(findings, penalties, recommendations, f)

    # Bus factor / maintainer concentration risk
    # Only score if commit_author data is present (backwards compat with existing tests)
    if maint.commit_authors:
        bf = calculate_bus_factor(maint.commit_authors)
        if bf["is_high_risk"]:
            raw_score = max(0.0, raw_score - 5.0)
            top_share = bf["top_author_share"]
            f = resolve_finding(
                "maintenance", "bus_factor_risk", top_share=top_share
            )
            _append_finding(findings, penalties, recommendations, f)

    weight = config.weight_for("maintenance")
    score = _apply_weight(raw_score, 25.0, weight)

    return CategoryScore(
        name="Maintenance",
        score=score,
        max_score=weight,
        penalties=penalties,
        recommendations=recommendations,
        findings=findings,
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
    findings: list[Finding] = []

    ignore_no_ci = config.is_ignored("no_ci")

    if ci.workflow_count >= 3:
        raw_score = 25.0
    elif ci.workflow_count == 2:
        raw_score = 20.0
        f = resolve_finding("ci_cd", "ci_two_workflows")
        # Info-level finding — recommendation only, no penalty
        _append_finding(
            findings, penalties, recommendations, f, add_penalty=False
        )
    elif ci.workflow_count == 1:
        raw_score = 15.0
        f = resolve_finding("ci_cd", "ci_single_workflow")
        _append_finding(
            findings, penalties, recommendations, f, add_penalty=False
        )
    else:
        if ignore_no_ci:
            raw_score = 25.0
        else:
            raw_score = 0.0
            f = resolve_finding("ci_cd", "no_ci")
            _append_finding(findings, penalties, recommendations, f)

    weight = config.weight_for("ci_cd")
    score = _apply_weight(raw_score, 25.0, weight)

    return CategoryScore(
        name="CI/CD",
        score=score,
        max_score=weight,
        penalties=penalties,
        recommendations=recommendations,
        findings=findings,
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
    findings: list[Finding] = []

    # License — 10 pts
    ignore_license = config.is_ignored("missing_license")
    if cf.license or ignore_license:
        raw_score += 10.0
    else:
        f = resolve_finding("governance", "license_governance_risk")
        _append_finding(findings, penalties, recommendations, f)

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
            f = resolve_finding("governance", "no_issues_governance")
            # Original scorer adds penalty but NO recommendation for this case
            _append_finding(
                findings, penalties, recommendations, f, add_recommendation=False
            )
    else:
        stale_ratio = stale / max(total_tracked, 1)
        if ignore_stale:
            raw_score += 15.0
        elif stale_ratio <= 0.10:
            raw_score += 10.0
        elif stale_ratio <= 0.25:
            raw_score += 5.0
            f = resolve_finding(
                "governance",
                "stale_prs",
                stale=stale,
                stale_ratio=stale_ratio,
            )
            _append_finding(findings, penalties, recommendations, f)
        else:
            f = resolve_finding(
                "governance",
                "stale_prs_high",
                stale=stale,
                stale_ratio=stale_ratio,
            )
            _append_finding(findings, penalties, recommendations, f)

    weight = config.weight_for("governance")
    score = _apply_weight(raw_score, 25.0, weight)

    return CategoryScore(
        name="Governance",
        score=score,
        max_score=weight,
        penalties=penalties,
        recommendations=recommendations,
        findings=findings,
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
