"""Repository health scoring engine."""

from __future__ import annotations

from .models import CategoryScore, HealthScore, RepoMetrics


def score_documentation(metrics: RepoMetrics) -> CategoryScore:
    """Score Documentation (0–25 pts) based on community files.

    - README: 10 pts
    - LICENSE: 5 pts
    - CONTRIBUTING.md: 5 pts
    - CODE_OF_CONDUCT.md: 5 pts
    """
    cf = metrics.community_files
    score = 0.0
    penalties: list[str] = []
    recommendations: list[str] = []

    if cf.readme:
        score += 10.0
    else:
        penalties.append("Missing README file")
        recommendations.append("Add a README.md describing the project, installation, and usage")

    if cf.license:
        score += 5.0
    else:
        penalties.append("Missing LICENSE file")
        recommendations.append("Add a LICENSE file to clarify usage terms (e.g., MIT, Apache-2.0)")

    if cf.contributing:
        score += 5.0
    else:
        penalties.append("Missing CONTRIBUTING.md")
        recommendations.append("Add CONTRIBUTING.md with guidelines for contributors")

    if cf.code_of_conduct:
        score += 5.0
    else:
        penalties.append("Missing CODE_OF_CONDUCT.md")
        recommendations.append(
            "Add CODE_OF_CONDUCT.md to set community standards (e.g., Contributor Covenant)"
        )

    return CategoryScore(
        name="Documentation",
        score=score,
        penalties=penalties,
        recommendations=recommendations,
    )


def score_maintenance(metrics: RepoMetrics) -> CategoryScore:
    """Score Maintenance (0–25 pts) based on commit velocity and issue close ratio.

    Commit velocity (0–15 pts):
      >= 20 commits/90d  → 15 pts
      >= 10 commits/90d  → 12 pts
      >=  5 commits/90d  →  8 pts
      >=  1 commits/90d  →  4 pts
      ==  0 commits/90d  →  0 pts

    Issue close ratio (0–10 pts):
      ratio >= 0.80 → 10 pts
      ratio >= 0.60 →  7 pts
      ratio >= 0.40 →  4 pts
      ratio <  0.40 →  1 pt
      no issues     →  5 pts (neutral, neither penalized nor rewarded)
    """
    maint = metrics.maintenance
    score = 0.0
    penalties: list[str] = []
    recommendations: list[str] = []

    # Commit velocity
    commits = maint.commits_last_90_days
    if commits >= 20:
        score += 15.0
    elif commits >= 10:
        score += 12.0
    elif commits >= 5:
        score += 8.0
    elif commits >= 1:
        score += 4.0
        penalties.append(f"Low commit activity: {commits} commit(s) in last 90 days")
        recommendations.append("Increase commit frequency — aim for at least 5 commits per quarter")
    else:
        penalties.append("No commits in the last 90 days — repository appears inactive")
        recommendations.append(
            "Resume active development or archive the repository if no longer maintained"
        )

    # Issue close ratio
    total_issues = maint.open_issues + maint.closed_issues
    if total_issues == 0:
        score += 5.0  # neutral
        penalties.append("No issues tracked — cannot assess issue response health")
        recommendations.append("Enable GitHub Issues to track bugs and feature requests")
    else:
        ratio = maint.issue_close_ratio
        closed = maint.closed_issues
        if ratio >= 0.80:
            score += 10.0
        elif ratio >= 0.60:
            score += 7.0
        elif ratio >= 0.40:
            score += 4.0
            penalties.append(
                f"Moderate issue close ratio: {ratio:.0%} "
                f"({closed} closed / {total_issues} total)"
            )
            recommendations.append("Triage open issues regularly to improve response time")
        else:
            score += 1.0
            penalties.append(
                f"Low issue close ratio: {ratio:.0%} "
                f"({closed} closed / {total_issues} total)"
            )
            recommendations.append(
                "Close or triage stale issues — a low close ratio signals poor maintenance"
            )

    return CategoryScore(
        name="Maintenance",
        score=score,
        penalties=penalties,
        recommendations=recommendations,
    )


def score_ci_cd(metrics: RepoMetrics) -> CategoryScore:
    """Score CI/CD (0–25 pts) based on workflow file presence.

    - 1+ workflows:     15 pts base
    - 2+ workflows:    +5 pts
    - 3+ workflows:    +5 pts
    - 0 workflows:      0 pts
    """
    ci = metrics.ci_cd
    score = 0.0
    penalties: list[str] = []
    recommendations: list[str] = []

    if ci.workflow_count >= 3:
        score = 25.0
    elif ci.workflow_count == 2:
        score = 20.0
        recommendations.append(
            "Consider adding additional CI workflows (e.g., security scanning, release automation)"
        )
    elif ci.workflow_count == 1:
        score = 15.0
        recommendations.append(
            "Add more CI/CD coverage — e.g., linting, testing on multiple platforms, Dependabot"
        )
    else:
        score = 0.0
        penalties.append("No GitHub Actions workflows found in .github/workflows/")
        recommendations.append(
            "Set up CI/CD with GitHub Actions — start with a basic test/lint workflow"
        )

    return CategoryScore(
        name="CI/CD",
        score=score,
        penalties=penalties,
        recommendations=recommendations,
    )


def score_governance(metrics: RepoMetrics) -> CategoryScore:
    """Score Governance (0–25 pts) based on stale PR ratio and license presence.

    License presence: 0–10 pts
      LICENSE present → 10 pts
      LICENSE missing →  0 pts

    Stale PR ratio: 0–15 pts
      0 stale PRs                    → 15 pts
      stale / (open+closed) <= 0.10  → 10 pts
      stale / (open+closed) <= 0.25  →  5 pts
      stale / (open+closed) >  0.25  →  0 pts
      no issues/PRs tracked          →  7 pts (neutral)

    Note: we approximate total PR volume using issue counts, since
    GitHub's open_issues_count includes PRs.
    """
    cf = metrics.community_files
    maint = metrics.maintenance

    score = 0.0
    penalties: list[str] = []
    recommendations: list[str] = []

    # License — 10 pts
    if cf.license:
        score += 10.0
    else:
        penalties.append("Repository has no LICENSE file — governance/compliance risk")
        recommendations.append("Add a LICENSE file (MIT, Apache-2.0, GPL-3.0, etc.)")

    # Stale PRs — 15 pts
    total_tracked = maint.open_issues + maint.closed_issues
    stale = maint.stale_prs

    if stale == 0:
        score += 15.0
    elif total_tracked == 0:
        score += 7.0
        penalties.append("No issues/PRs tracked — cannot assess PR governance")
    else:
        stale_ratio = stale / max(total_tracked, 1)
        if stale_ratio <= 0.10:
            score += 10.0
        elif stale_ratio <= 0.25:
            score += 5.0
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

    return CategoryScore(
        name="Governance",
        score=score,
        penalties=penalties,
        recommendations=recommendations,
    )


def score_repo(metrics: RepoMetrics) -> HealthScore:
    """Convert RepoMetrics to a 0–100 HealthScore."""
    documentation = score_documentation(metrics)
    maintenance = score_maintenance(metrics)
    ci_cd = score_ci_cd(metrics)
    governance = score_governance(metrics)

    total = documentation.score + maintenance.score + ci_cd.score + governance.score

    return HealthScore(
        total_score=round(total, 2),
        documentation=documentation,
        maintenance=maintenance,
        ci_cd=ci_cd,
        governance=governance,
    )
