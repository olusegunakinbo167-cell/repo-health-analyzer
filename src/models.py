"""Data models for repository health metrics."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class CommunityFiles:
    """Presence of standard community health files."""

    readme: bool
    license: bool
    contributing: bool
    code_of_conduct: bool

    @property
    def score(self) -> int:
        """Count of present files (0–4)."""
        return sum(
            [
                self.readme,
                self.license,
                self.contributing,
                self.code_of_conduct,
            ]
        )


@dataclass(slots=True)
class CiCdSetup:
    """CI/CD workflow detection."""

    workflow_files: list[str]
    workflow_count: int

    @property
    def has_ci(self) -> bool:
        return self.workflow_count > 0


@dataclass(slots=True)
class MaintenanceActivity:
    """Repository maintenance signals."""

    commits_last_90_days: int
    open_issues: int
    closed_issues: int
    stale_prs: int  # PRs open > 30 days

    @property
    def issue_close_ratio(self) -> float:
        """Closed / (open + closed). Returns 0.0 if no issues tracked."""
        total = self.open_issues + self.closed_issues
        if total == 0:
            return 0.0
        return self.closed_issues / total


@dataclass(slots=True)
class RepoMetrics:
    """Aggregated repository health telemetry."""

    full_name: str
    description: str | None
    stars: int
    language: str | None
    default_branch: str

    community_files: CommunityFiles
    ci_cd: CiCdSetup
    maintenance: MaintenanceActivity
