"""Data models for repository health metrics."""

from __future__ import annotations

from dataclasses import dataclass, field


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
    commit_authors: list[str] = field(default_factory=list)

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
    commit_sha: str | None = None
    # Optional: academic impact (paper references in repo docs)
    # Import is TYPE_CHECKING guarded to avoid circular import
    academic_impact: "AcademicImpact | None" = None  # type: ignore[name-defined]


# ----------------------------------------------------------------------
# Scoring models
# ----------------------------------------------------------------------


@dataclass(slots=True)
class Finding:
    """Structured diagnostic finding with full metric metadata.

    Carries rich rule metadata from definitions/metrics.yaml for
    exporter rendering (severity badges, descriptions, documentation links).

    The penalties/recommendations string lists in CategoryScore are
    retained for backwards compatibility — findings is additive.
    """

    rule_id: str
    category: str
    severity: str  # high|medium|low|info|none
    message: str  # rendered, with template variables substituted
    description: str
    recommendation: str
    references: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    weight_raw: float | int | None = None


@dataclass(slots=True)
class CategoryScore:
    """Score breakdown for a single health category."""

    name: str
    score: float  # 0.0–25.0
    max_score: float = 25.0
    penalties: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    @property
    def percentage(self) -> float:
        if self.max_score == 0:
            return 0.0
        return (self.score / self.max_score) * 100.0


@dataclass(slots=True)
class HealthScore:
    """Overall repository health score (0–100)."""

    total_score: float
    documentation: CategoryScore
    maintenance: CategoryScore
    ci_cd: CategoryScore
    governance: CategoryScore

    @property
    def grade(self) -> str:
        """Letter grade based on total score."""
        # Grade against a 0–100 scale regardless of custom weights
        # Normalize to 100-point scale
        total_max = (
            self.documentation.max_score
            + self.maintenance.max_score
            + self.ci_cd.max_score
            + self.governance.max_score
        )
        s = (self.total_score / total_max * 100.0) if total_max else 0.0
        if s >= 90:
            return "A"
        if s >= 80:
            return "B"
        if s >= 70:
            return "C"
        if s >= 60:
            return "D"
        return "F"

    def all_recommendations(self) -> list[str]:
        """Flattened list of all recommendations across categories."""
        recs: list[str] = []
        for cat in (
            self.documentation,
            self.maintenance,
            self.ci_cd,
            self.governance,
        ):
            recs.extend(cat.recommendations)
        return recs

    def categories(self) -> dict[str, CategoryScore]:
        return {
            "documentation": self.documentation,
            "maintenance": self.maintenance,
            "ci_cd": self.ci_cd,
            "governance": self.governance,
        }


# ----------------------------------------------------------------------
# Baseline comparison
# ----------------------------------------------------------------------


@dataclass(slots=True)
class CategoryDelta:
    """Score delta for a single category vs baseline."""

    name: str
    current: float
    baseline: float
    delta: float
    max_score: float

    @property
    def sign(self) -> str:
        if self.delta > 0.05:
            return "+"
        if self.delta < -0.05:
            return ""
        return "±"

    @property
    def trend(self) -> str:
        if self.delta > 0.5:
            return "▲"
        if self.delta < -0.5:
            return "▼"
        return "■"


@dataclass(slots=True)
class BaselineDiff:
    """Comparison of current HealthScore against a baseline."""

    current_score: float
    baseline_score: float
    delta: float
    baseline_commit: str | None = None
    baseline_timestamp: str | None = None
    categories: dict[str, CategoryDelta] = field(default_factory=dict)

    @classmethod
    def compare(
        cls,
        current: HealthScore,
        baseline: HealthScore,
        baseline_commit: str | None = None,
        baseline_timestamp: str | None = None,
    ) -> BaselineDiff:
        cats: dict[str, CategoryDelta] = {}
        for key in ("documentation", "maintenance", "ci_cd", "governance"):
            cur_cat = current.categories()[key]
            base_cat = baseline.categories()[key]
            cats[key] = CategoryDelta(
                name=cur_cat.name,
                current=cur_cat.score,
                baseline=base_cat.score,
                delta=round(cur_cat.score - base_cat.score, 2),
                max_score=cur_cat.max_score,
            )
        return cls(
            current_score=current.total_score,
            baseline_score=baseline.total_score,
            delta=round(current.total_score - baseline.total_score, 2),
            baseline_commit=baseline_commit,
            baseline_timestamp=baseline_timestamp,
            categories=cats,
        )
