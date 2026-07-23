"""Repository health analyzer configuration parsing."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


# Known rule IDs that can be ignored via config
KNOWN_RULES = {
    "missing_readme",
    "missing_license",
    "missing_contributing",
    "missing_code_of_conduct",
    "no_ci",
    "low_commit_activity",
    "no_commits",
    "low_issue_close_ratio",
    "no_issues_tracked",
    "stale_prs",
}


@dataclass(slots=True)
class RepoConfig:
    """Analyzer configuration loaded from .repo-health.yml."""

    weights: dict[str, float] = field(
        default_factory=lambda: {
            "documentation": 25.0,
            "maintenance": 25.0,
            "ci_cd": 25.0,
            "governance": 25.0,
        }
    )
    ignore_rules: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        # Normalize weights — ensure all 4 categories present, coerce to float
        defaults = {
            "documentation": 25.0,
            "maintenance": 25.0,
            "ci_cd": 25.0,
            "governance": 25.0,
        }
        for key, default_val in defaults.items():
            self.weights.setdefault(key, default_val)
        # Filter to known categories only
        self.weights = {k: float(v) for k, v in self.weights.items() if k in defaults}
        # Fill missing with defaults
        for key, default_val in defaults.items():
            self.weights.setdefault(key, default_val)
        # Normalize ignore_rules to a set of strings
        if isinstance(self.ignore_rules, list):  # type: ignore[unreachable]
            self.ignore_rules = set(self.ignore_rules)

    @property
    def total_weight(self) -> float:
        return sum(self.weights.values())

    def weight_for(self, category: str) -> float:
        return self.weights.get(category, 25.0)

    def is_ignored(self, rule_id: str) -> bool:
        return rule_id in self.ignore_rules


def load_config(path: str | Path) -> RepoConfig:
    """Load configuration from a local .repo-health.yml file."""
    if yaml is None:
        raise RuntimeError("PyYAML is required to parse .repo-health.yml (pip install pyyaml)")
    p = Path(path)
    if not p.exists():
        return RepoConfig()
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return RepoConfig()

    weights = data.get("weights", {})
    if not isinstance(weights, dict):
        weights = {}

    ignore = data.get("ignore", [])
    if isinstance(ignore, str):
        ignore = [ignore]
    if not isinstance(ignore, (list, set, tuple)):
        ignore = []

    # Filter ignore list to known rules
    ignore_set = {str(r).strip() for r in ignore if str(r).strip() in KNOWN_RULES}

    return RepoConfig(weights=dict(weights), ignore_rules=ignore_set)


async def fetch_remote_config(
    owner: str,
    repo: str,
    branch: str = "main",
    token: str | None = None,
) -> RepoConfig:
    """Fetch .repo-health.yml from a GitHub repository root.

    Returns default RepoConfig if file is missing or unparsable.
    """
    if yaml is None:
        return RepoConfig()

    import base64

    import httpx

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "repo-health-analyzer/0.1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = f"https://api.github.com/repos/{owner}/{repo}/contents/.repo-health.yml"
    params = {"ref": branch} if branch else {}

    try:
        async with httpx.AsyncClient(
            headers=headers, timeout=10.0, follow_redirects=True
        ) as client:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                return RepoConfig()
            data = resp.json()
            content_b64 = data.get("content", "")
            if not content_b64:
                return RepoConfig()
            content = base64.b64decode(content_b64).decode("utf-8")
            parsed = yaml.safe_load(content) or {}
    except Exception:
        return RepoConfig()

    if not isinstance(parsed, dict):
        return RepoConfig()

    weights = parsed.get("weights", {})
    if not isinstance(weights, dict):
        weights = {}

    ignore = parsed.get("ignore", [])
    if isinstance(ignore, str):
        ignore = [ignore]
    if not isinstance(ignore, (list, set, tuple)):
        ignore = []

    ignore_set = {str(r).strip() for r in ignore if str(r).strip() in KNOWN_RULES}
    return RepoConfig(weights=dict(weights), ignore_rules=ignore_set)
