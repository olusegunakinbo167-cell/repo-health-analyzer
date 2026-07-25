# definitions.py
"""Metric definitions registry — static YAML-backed rule metadata."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


@dataclass(slots=True, frozen=True)
class MetricDef:
    """Structured metadata for a single scoring rule."""

    rule_id: str
    category: str
    severity: str  # high|medium|low|info|none
    title: str
    description: str
    recommendation: str
    message_template: str | None = None
    references: list[str] | None = None
    tags: list[str] | None = None
    weight_raw: int | float | None = None

    def render_message(self, **ctx: Any) -> str:
        """Render the penalty/finding message with runtime context."""
        template = self.message_template or self.title
        try:
            return template.format(**ctx)
        except KeyError:
            # Missing template var — fall back to unrendered title
            return self.title


class DefinitionsRegistry:
    """Loads and resolves metric definitions from YAML."""

    def __init__(self, definitions_path: Path | None = None) -> None:
        if yaml is None:
            raise RuntimeError(
                "PyYAML is required for metric definitions (pip install pyyaml)"
            )

        # Resolution order:
        # 1. explicit path arg
        # 2. ./definitions/metrics.yaml (project root, user override)
        # 3. src/definitions/metrics.yaml (package-bundled data)
        # 4. ../definitions/metrics.yaml (repo-root, dev fallback)
        candidates: list[Path] = []
        if definitions_path:
            candidates.append(definitions_path)

        cwd_def = Path.cwd() / "definitions" / "metrics.yaml"
        candidates.append(cwd_def)

        # package-bundled: src/definitions/metrics.yaml
        pkg_bundled = Path(__file__).resolve().parent / "definitions" / "metrics.yaml"
        candidates.append(pkg_bundled)

        # dev fallback: repo_root/definitions/metrics.yaml
        repo_bundled = (
            Path(__file__).resolve().parent.parent / "definitions" / "metrics.yaml"
        )
        candidates.append(repo_bundled)

        def_path: Path | None = None
        for c in candidates:
            if c.exists():
                def_path = c
                break

        if def_path is None:
            raise FileNotFoundError(
                "No metric definitions file found. Searched: "
                + ", ".join(str(c) for c in candidates)
            )

        with def_path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}

        self._defs: dict[tuple[str, str], MetricDef] = {}
        metrics_node = data.get("metrics", {})

        for category, rules in metrics_node.items():
            if not isinstance(rules, dict):
                continue
            for rule_id, rule_data in rules.items():
                md = MetricDef(
                    rule_id=rule_id,
                    category=category,
                    severity=rule_data.get("severity", "medium"),
                    title=rule_data.get("title", rule_id),
                    description=rule_data.get("description", ""),
                    recommendation=rule_data.get("recommendation", ""),
                    message_template=rule_data.get("message_template"),
                    references=rule_data.get("references"),
                    tags=rule_data.get("tags"),
                    weight_raw=rule_data.get("weight_raw"),
                )
                self._defs[(category, rule_id)] = md

        self.def_path = def_path

    def get(self, category: str, rule_id: str) -> MetricDef | None:
        """Look up a metric definition by category + rule_id."""
        return self._defs.get((category, rule_id))

    def resolve(
        self, category: str, rule_id: str, **ctx: Any
    ) -> tuple[str, str]:
        """Resolve a rule to (message, recommendation).

        Returns the rendered message (with template vars substituted) and
        the recommendation text. Falls back to rule_id if definition is missing.

        Parameters
        ----------
        category: scoring category (documentation, maintenance, ci_cd, governance)
        rule_id: rule identifier matching definitions/metrics.yaml
        **ctx: template variables for message_template interpolation
               (e.g. commits=3, ratio=0.42, closed=5, total=12)

        Returns
        -------
        (message, recommendation)
        """
        md = self.get(category, rule_id)
        if md is None:
            # Definition missing — graceful fallback so scorer never crashes
            return (rule_id, "")
        message = md.render_message(**ctx)
        return (message, md.recommendation)

    def all_for_category(self, category: str) -> dict[str, MetricDef]:
        """Get all metric definitions for a category."""
        return {
            rule_id: md
            for (cat, rule_id), md in self._defs.items()
            if cat == category
        }


# Module-level singleton — lazy loaded on first access
_registry: DefinitionsRegistry | None = None


def get_registry(definitions_path: Path | None = None) -> DefinitionsRegistry:
    """Get the global definitions registry (singleton).

    Parameters
    ----------
    definitions_path: optional explicit path to a metrics.yaml file.
        If provided, forces a fresh registry load from that path.
        Otherwise returns the cached singleton.
    """
    global _registry
    if _registry is None or definitions_path is not None:
        _registry = DefinitionsRegistry(definitions_path)
    return _registry


def resolve(category: str, rule_id: str, **ctx: Any) -> tuple[str, str]:
    """Convenience wrapper: resolve(category, rule_id, **ctx) → (message, recommendation)."""
    return get_registry().resolve(category, rule_id, **ctx)


def resolve_finding(
    category: str, rule_id: str, **ctx: Any
) -> "Finding":  # type: ignore[name-defined]  # Forward ref to avoid circular import
    """Resolve a rule to a structured Finding object with full metadata.

    Returns a Finding with severity, description, references, tags, etc.
    — everything needed for rich exporter rendering.

    Parameters
    ----------
    category: scoring category (documentation, maintenance, ci_cd, governance)
    rule_id: rule identifier matching definitions/metrics.yaml
    **ctx: template variables for message_template interpolation

    Returns
    -------
    Finding with all metric metadata populated.
    """
    # Local import to avoid circular dependency (models -> definitions)
    from .models import Finding

    md = get_registry().get(category, rule_id)
    if md is None:
        # Definition missing — graceful fallback
        return Finding(
            rule_id=rule_id,
            category=category,
            severity="medium",
            message=rule_id,
            description="",
            recommendation="",
            references=[],
            tags=[],
            weight_raw=None,
        )

    message = md.render_message(**ctx)
    return Finding(
        rule_id=rule_id,
        category=category,
        severity=md.severity,
        message=message,
        description=md.description,
        recommendation=md.recommendation,
        references=(md.references or []),
        tags=(md.tags or []),
        weight_raw=md.weight_raw,
    )


def reset_registry() -> None:
    """Clear the cached registry singleton (primarily for testing)."""
    global _registry
    _registry = None
