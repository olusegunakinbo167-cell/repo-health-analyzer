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
class CategoryScore:
    """Score breakdown for a single health category."""

    name: str
    score: float  # 0.0–25.0
    max_score: float = 25.0
    penalties: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

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
    """Score delta for a single category vs baseline.

    When a category exists in the current score but not in the baseline
    (schema evolution), `baseline`, `delta`, and `percentage_delta` are None
    and the category is excluded from overall score comparison.
    """

    name: str
    current: float
    baseline: float | None
    delta: float | None
    max_score: float
    # Normalized percentage delta (current% - baseline%) for comparing
    # categories with different max_score weights (e.g., 25pt → 20pt)
    percentage_delta: float | None = None
    # max_score of the baseline category (may differ from current max_score
    # during schema evolution / weight rebalancing)
    baseline_max_score: float | None = None

    @property
    def sign(self) -> str:
        if self.delta is None:
            return "?"
        if self.delta > 0.05:
            return "+"
        if self.delta < -0.05:
            return ""
        return "±"

    @property
    def trend(self) -> str:
        if self.delta is None:
            return "?"
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
        # Track totals for comparable categories only (exclude missing baseline cats)
        comparable_current_total = 0.0
        comparable_baseline_total = 0.0

        cur_cats = current.categories()
        base_cats = baseline.categories()

        for key, cur_cat in cur_cats.items():

            # Schema evolution: baseline may lack category (e.g., financial)
            if key not in base_cats or base_cats[key] is None:
                # Category missing in baseline — mark as None, exclude from overall delta
                cats[key] = CategoryDelta(
                    name=cur_cat.name,
                    current=cur_cat.score,
                    baseline=None,
                    delta=None,
                    max_score=cur_cat.max_score,
                    percentage_delta=None,
                    baseline_max_score=None,
                )
                continue

            base_cat = base_cats[key]
            base_score = base_cat.score

            # Raw point delta (kept for backwards compat / reporter display)
            raw_delta = round(cur_cat.score - base_score, 2)

            # Normalized percentage delta — handles weight rebalancing
            # e.g., 20/25 (80%) → 16/20 (80%) = 0% delta, not -4 pts
            cur_pct = (cur_cat.score / cur_cat.max_score * 100.0) if cur_cat.max_score else 0.0
            base_pct = (base_score / base_cat.max_score * 100.0) if base_cat.max_score else 0.0
            pct_delta = round(cur_pct - base_pct, 2)

            cats[key] = CategoryDelta(
                name=cur_cat.name,
                current=cur_cat.score,
                baseline=base_score,
                delta=raw_delta,
                max_score=cur_cat.max_score,
                percentage_delta=pct_delta,
                baseline_max_score=base_cat.max_score,
            )

            # Accumulate comparable totals (exclude categories missing in baseline)
            comparable_current_total += cur_cat.score
            comparable_baseline_total += base_score

        # Overall delta: sum of comparable categories only
        # (excludes categories that didn't exist in the baseline)
        overall_delta = round(
            comparable_current_total - comparable_baseline_total, 2
        )

        return cls(
            current_score=round(comparable_current_total, 2),
            baseline_score=round(comparable_baseline_total, 2),
            delta=overall_delta,
            baseline_commit=baseline_commit,
            baseline_timestamp=baseline_timestamp,
            categories=cats,
        )


# ----------------------------------------------------------------------
# Organization batch analysis models
# ----------------------------------------------------------------------


@dataclass(slots=True)
class OrgRepoInfo:
    """Repository metadata from org/user repo listing."""

    full_name: str
    name: str
    description: str | None
    stars: int
    language: str | None
    fork: bool
    archived: bool
    default_branch: str
    html_url: str


@dataclass(slots=True)
class OrgRepoScore:
    """Repository score summary for org-level reporting."""

    full_name: str
    score: float
    grade: str
    stars: int
    language: str | None


@dataclass(slots=True)
class OrgHealthSummary:
    """Aggregated health summary for an entire organization or user."""

    org: str
    total_repos: int
    analyzed_repos: int
    failed_repos: int
    avg_score: float
    median_score: float
    score_distribution: dict[str, int]
    top_repos: list[OrgRepoScore]
    bottom_repos: list[OrgRepoScore]
    category_averages: dict[str, float]
    missing_files_stats: dict[str, int]
    ci_adoption_rate: float
    total_stars: int
    timestamp: str


@dataclass(slots=True)
class OrgAnalysisResult:
    """Full result of an organization-wide batch analysis."""

    org: str
    repos: list[tuple[RepoMetrics, HealthScore]]
    failed: list[tuple[str, str]]
