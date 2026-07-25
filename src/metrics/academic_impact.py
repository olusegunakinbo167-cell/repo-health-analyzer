"""Academic impact metric — research paper references in repo docs.

Scans repository documentation (README, docs/, CITATION files, .bib)
for academic paper references (DOI, ArXiv, S2, PMID, etc.), resolves
them via Semantic Scholar, and aggregates citation metrics.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from ..semantic_scholar_client import S2Paper, SemanticScholarClient

# ----------------------------------------------------------------------
# Paper reference extraction
# ----------------------------------------------------------------------


# DOI: 10.<registrant>/<suffix>
# https://www.doi.org/doi_handbook/2_Numbering.html
DOI_RE = re.compile(
    r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b",
    re.IGNORECASE,
)

# ArXiv IDs
# New style: YYMM.NNNNN[vN]  (e.g. 1706.03762, 2301.12345v2)
# Old style: <archive>/<YYMMNNN>  (e.g. cs/0112017, quant-ph/9901001v3)
ARXIV_RE = re.compile(
    r"""
    (?:
        # arxiv.org URL
        arxiv\.org/abs/
        |
        # "arXiv:" prefix
        \barxiv:\s*
    )?
    (
        # old-style: archive/YYMMNNN
        [a-z\-]+(?:\.[a-z\-]+)?/\d{7}
        |
        # new-style: YYMM.NNNNN
        \d{4}\.\d{4,5}
    )
    (v\d+)?  # optional version
    \b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# S2 CorpusId (40-char hex SHA)
S2_CORPUS_RE = re.compile(r"\b[0-9a-f]{40}\b", re.IGNORECASE)

# PMID
PMID_RE = re.compile(r"\bPMID:?\s*(\d{7,8})\b", re.IGNORECASE)

# ACL Anthology ID (e.g. P19-1234, W18-1234, 2020.acl-main.123)
ACL_RE = re.compile(
    r"\b(?:ACL:)?([A-Z]\d{2}-\d{4}|\d{4}\.[a-z]+-[a-z]+\.\d+)\b",
    re.IGNORECASE,
)

# PubMed Central ID
PMCID_RE = re.compile(r"\bPMC\d+\b", re.IGNORECASE)


@dataclass(slots=True, frozen=True)
class PaperReference:
    """A single paper reference found in repository documentation."""

    paper_id: str  # normalized S2-compatible ID (e.g. "DOI:10.1038/...", "ArXiv:1706.03762")
    id_type: str  # "doi" | "arxiv" | "s2_corpus" | "pmid" | "acl" | "pmcid"
    source_file: str  # e.g. "README.md", "docs/paper_refs.md"
    context_snippet: str | None = None  # ~120 char surrounding text

    def s2_lookup_id(self) -> str:
        """Return the ID string suitable for S2 Graph API lookup."""
        if self.id_type == "doi":
            return f"DOI:{self.paper_id}"
        if self.id_type == "arxiv":
            # S2 expects "ArXiv:<id>" with capital A
            pid = self.paper_id
            if not pid.lower().startswith("arxiv:"):
                pid = f"ArXiv:{pid}"
            elif pid.startswith("arXiv:"):
                pid = "ArXiv:" + pid[6:]
            return pid
        if self.id_type == "pmid":
            return f"PMID:{self.paper_id}"
        if self.id_type == "acl":
            return f"ACL:{self.paper_id}"
        if self.id_type == "pmcid":
            # S2 uses "PubMedCentral:<id>"
            pmc = self.paper_id
            if pmc.upper().startswith("PMC"):
                return f"PubMedCentral:{pmc}"
            return f"PubMedCentral:PMC{pmc}"
        # s2_corpus — raw 40-char hex
        return self.paper_id


def _context(text: str, start: int, end: int, radius: int = 60) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    snippet = text[left:right].replace("\n", " ")
    snippet = re.sub(r"\s+", " ", snippet).strip()
    return snippet


def extract_paper_references(
    text: str, source_file: str = "unknown"
) -> list[PaperReference]:
    """Extract all paper references from a text blob.

    Returns a de-duplicated list of PaperReference objects.
    If the same paper appears multiple times (e.g. DOI + ArXiv for
    the same paper), both IDs are returned — S2 de-duplication happens
    at resolution time via corpusId.

    Args:
        text: File contents to scan.
        source_file: Filename for provenance tracking.

    Returns:
        List of PaperReference objects, de-duplicated by (id_type, paper_id).
    """
    seen: set[tuple[str, str]] = set()
    refs: list[PaperReference] = []

    def add_ref(pid: str, id_type: str, start: int, end: int) -> None:
        # Normalize
        if id_type == "doi":
            pid_norm = pid.lower().rstrip(".,;)]}")
        elif id_type == "arxiv":
            # Strip arXiv: prefix for storage, strip version suffix for dedup?
            # Keep version in stored ID but dedup ignoring version
            pid_norm = re.sub(r"^arxiv:\s*", "", pid, flags=re.IGNORECASE)
            pid_norm = pid_norm.lower()
        elif id_type == "s2_corpus":
            pid_norm = pid.lower()
        elif id_type == "pmid":
            pid_norm = pid.lstrip("0")
        elif id_type == "acl":
            pid_norm = pid
        elif id_type == "pmcid":
            pid_norm = pid.upper()
            if not pid_norm.startswith("PMC"):
                pid_norm = "PMC" + pid_norm
        else:
            pid_norm = pid

        # ArXiv dedup key strips version suffix
        if id_type == "arxiv":
            dedup_key = re.sub(r"v\d+$", "", pid_norm)
        else:
            dedup_key = pid_norm

        key = (id_type, dedup_key)
        if key in seen:
            return
        seen.add(key)

        ctx = _context(text, start, end)
        refs.append(
            PaperReference(
                paper_id=pid_norm,
                id_type=id_type,
                source_file=source_file,
                context_snippet=ctx,
            )
        )

    # DOI — scan first (most specific)
    for m in DOI_RE.finditer(text):
        # Avoid false positives from ArXiv URLs that contain doi-like strings
        # (DOI regex is fairly strict already)
        add_ref(m.group(0), "doi", m.start(), m.end())

    # ArXiv
    for m in ARXIV_RE.finditer(text):
        full_match = m.group(0)
        arxiv_id = m.group(1)
        version = m.group(2) or ""
        # Skip if this looks like it was already captured as part of a DOI
        # (DOI regex shouldn't match arXiv IDs, but be safe)
        if "10." in full_match and "/" in full_match and len(arxiv_id) > 15:
            continue
        pid = f"{arxiv_id}{version}"
        add_ref(pid, "arxiv", m.start(), m.end())

    # S2 CorpusId (40-char hex) — avoid matching git SHAs in code blocks
    # Heuristic: require word boundaries, and skip if surrounded by
    # typical git/code patterns.  Keep it simple for v1.
    for m in S2_CORPUS_RE.finditer(text):
        # Skip obvious git SHA contexts
        ctx_left = text[max(0, m.start() - 20) : m.start()].lower()
        if any(
            x in ctx_left
            for x in ["commit", "sha", "git", "hash", "checksum"]
        ):
            # Still include it — S2 CorpusIds ARE git-SHA-like, and
            # false negatives hurt more than false positives
            # (S2 lookup will just 404).  Keep for now.
            pass
        add_ref(m.group(0), "s2_corpus", m.start(), m.end())

    # PMID
    for m in PMID_RE.finditer(text):
        add_ref(m.group(1), "pmid", m.start(), m.end())

    # PubMed Central
    for m in PMCID_RE.finditer(text):
        add_ref(m.group(0), "pmcid", m.start(), m.end())

    # ACL Anthology — run last (most likely to false-positive)
    # Only match if "acl" appears nearby, or it matches the strict
    # ACL ID pattern with a letter prefix
    for m in ACL_RE.finditer(text):
        acl_id = m.group(1)
        # Heuristic: if no "acl" in surrounding text and the ID
        # doesn't start with a letter, skip (likely false positive)
        ctx = text[max(0, m.start() - 30) : m.end() + 30].lower()
        if "acl" not in ctx and not re.match(r"^[a-z]", acl_id, re.IGNORECASE):
            continue
        add_ref(acl_id, "acl", m.start(), m.end())

    return refs


def extract_from_files(files: dict[str, str]) -> list[PaperReference]:
    """Extract paper references from multiple files.

    Args:
        files: Mapping of filename → file contents.

    Returns:
        De-duplicated list across all files.
    """
    seen: set[tuple[str, str]] = set()
    all_refs: list[PaperReference] = []
    for fname, content in files.items():
        for ref in extract_paper_references(content, source_file=fname):
            # Global dedup across files
            dedup_key = (ref.id_type, ref.paper_id.lower())
            if ref.id_type == "arxiv":
                dedup_key = (
                    ref.id_type,
                    re.sub(r"v\d+$", "", ref.paper_id.lower()),
                )
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            all_refs.append(ref)
    return all_refs


# ----------------------------------------------------------------------
# Academic impact aggregation
# ----------------------------------------------------------------------


@dataclass(slots=True)
class ResolvedPaper:
    """A paper reference resolved via S2 with full metadata."""

    reference: PaperReference
    s2: S2Paper | None  # None if S2 lookup failed / not found


@dataclass(slots=True)
class AcademicImpact:
    """Academic impact metrics for a repository."""

    papers_referenced: list[ResolvedPaper] = field(default_factory=list)

    @property
    def paper_count(self) -> int:
        return len(self.papers_referenced)

    @property
    def resolved_count(self) -> int:
        return sum(1 for p in self.papers_referenced if p.s2 is not None)

    @property
    def total_citations(self) -> int:
        return sum(p.s2.citation_count for p in self.papers_referenced if p.s2)

    @property
    def total_influential_citations(self) -> int:
        return sum(
            p.s2.influential_citation_count
            for p in self.papers_referenced
            if p.s2
        )

    @property
    def avg_citations_per_paper(self) -> float:
        n = self.resolved_count
        return (self.total_citations / n) if n else 0.0

    @property
    def max_citations_single_paper(self) -> int:
        if not self.papers_referenced:
            return 0
        return max(
            (p.s2.citation_count for p in self.papers_referenced if p.s2),
            default=0,
        )

    @property
    def fields_of_study(self) -> list[str]:
        """Unique fields of study across all resolved papers, sorted."""
        fos: set[str] = set()
        for p in self.papers_referenced:
            if p.s2:
                fos.update(p.s2.fields_of_study)
        return sorted(fos)

    @property
    def open_access_count(self) -> int:
        return sum(
            1 for p in self.papers_referenced if p.s2 and p.s2.is_open_access
        )

    @property
    def open_access_ratio(self) -> float:
        n = self.resolved_count
        return (self.open_access_count / n) if n else 0.0

    def recent_papers_count(self, years: int = 3, current_year: int | None = None) -> int:
        """Count papers published within the last N years."""
        if current_year is None:
            import datetime

            current_year = datetime.datetime.now().year
        cutoff = current_year - years
        return sum(
            1
            for p in self.papers_referenced
            if p.s2 and p.s2.year is not None and p.s2.year >= cutoff
        )


# ----------------------------------------------------------------------
# Resolver
# ----------------------------------------------------------------------


async def resolve_paper_references(
    references: Iterable[PaperReference],
    s2_client: SemanticScholarClient | None = None,
    *,
    batch_size: int = 100,
) -> AcademicImpact:
    """Resolve paper references via S2 and build AcademicImpact.

    Args:
        references: Paper references to resolve.
        s2_client: Optional S2 client.  If None, a new one is created
            (using S2_API_KEY / SEMANTIC_SCHOLAR_API_KEY env if set).
        batch_size: Max papers per S2 batch request (S2 allows ~500).

    Returns:
        AcademicImpact with resolved papers and aggregated metrics.
    """
    refs = list(references)
    if not refs:
        return AcademicImpact(papers_referenced=[])

    close_client = False
    if s2_client is None:
        s2_client = SemanticScholarClient()
        close_client = True

    try:
        # Build S2 lookup IDs
        lookup_ids = [r.s2_lookup_id() for r in refs]

        # Batch resolve via S2
        resolved_map: dict[str, S2Paper] = {}
        for i in range(0, len(lookup_ids), batch_size):
            batch = lookup_ids[i : i + batch_size]
            try:
                papers = await s2_client.batch_get_papers(batch)
            except Exception:
                # On S2 failure (rate limit, network, etc.), leave unresolved
                papers = []

            # Map back — S2 batch preserves order, skips None entries.
            # We need to match by paper_id / external_ids.
            # Simplest: build a lookup dict by all known IDs.
            for p in papers:
                # Index by S2 paper_id
                resolved_map[p.paper_id.lower()] = p
                # Index by corpus_id
                if p.corpus_id:
                    resolved_map[str(p.corpus_id)] = p
                # Index by external IDs
                for k, v in p.external_ids.items():
                    if not v:
                        continue
                    # S2 external IDs are usually strings, but be defensive
                    v_str = str(v)
                    v_lower = v_str.lower()
                    k_upper = k.upper()
                    # DOI
                    if k_upper == "DOI":
                        resolved_map[f"doi:{v_lower}"] = p
                        resolved_map[v_lower] = p
                    # ArXiv
                    elif k.lower() == "arxiv":
                        arxiv_norm = v_lower
                        resolved_map[f"arxiv:{arxiv_norm}"] = p
                        resolved_map[arxiv_norm] = p
                        # Also index without version
                        arxiv_base = re.sub(r"v\d+$", "", arxiv_norm)
                        resolved_map[f"arxiv:{arxiv_base}"] = p
                        resolved_map[arxiv_base] = p
                    # PMID
                    elif k_upper == "PUBMED":
                        resolved_map[f"pmid:{v_str}"] = p
                        resolved_map[v_str] = p
                    # ACL
                    elif k_upper == "ACL":
                        resolved_map[f"acl:{v_lower}"] = p
                        resolved_map[v_lower] = p
                    # Generic fallback
                    else:
                        resolved_map[v_lower] = p

        # Match references to resolved papers
        resolved: list[ResolvedPaper] = []
        for ref in refs:
            s2_paper: S2Paper | None = None

            # Try direct lookup
            lookup_key = ref.s2_lookup_id().lower()
            # Strip prefixes for map lookup
            for prefix in (
                "doi:",
                "arxiv:",
                "pmid:",
                "acl:",
                "pubmedcentral:",
            ):
                if lookup_key.startswith(prefix):
                    bare = lookup_key[len(prefix) :]
                    s2_paper = resolved_map.get(bare) or resolved_map.get(lookup_key)
                    break
            else:
                s2_paper = resolved_map.get(lookup_key)

            # ArXiv version fallback
            if s2_paper is None and ref.id_type == "arxiv":
                base_id = re.sub(r"v\d+$", "", ref.paper_id.lower())
                s2_paper = resolved_map.get(base_id) or resolved_map.get(
                    f"arxiv:{base_id}"
                )

            resolved.append(ResolvedPaper(reference=ref, s2=s2_paper))

        return AcademicImpact(papers_referenced=resolved)

    finally:
        if close_client:
            await s2_client.close()


# ----------------------------------------------------------------------
# Scoring (Option B: documentation bonus)
# ----------------------------------------------------------------------


def score_academic_impact_bonus(
    impact: AcademicImpact | None,
) -> tuple[float, list[str], list[str]]:
    """Score academic impact as a documentation bonus (Option B).

    Returns (bonus_score, penalties, recommendations).
    Bonus is 0–5 pts, added on top of the base documentation score.

    Scoring:
    - Papers referenced: 0→0pts, 1-2→2pts, 3-5→3.5pts, 6+→5pts
    - High-impact papers bonus: if avg_citations >= 100 → +1 pt (capped at 5 total)
    - Recency bonus: if any paper <3yr old and base < 5 → round up to at least 2 pts

    Max bonus: 5.0 pts
    """
    if impact is None or impact.paper_count == 0:
        return 0.0, [], []

    # Lazy import to avoid circular dependency (scorer -> academic_impact -> definitions -> scorer)
    from ..definitions import resolve as _resolve

    n = impact.paper_count
    resolved = impact.resolved_count

    # Base score by paper count
    if n >= 6:
        score = 5.0
    elif n >= 3:
        score = 3.5
    elif n >= 1:
        score = 2.0
    else:
        score = 0.0

    penalties: list[str] = []
    recommendations: list[str] = []

    # High-impact bonus
    if impact.avg_citations_per_paper >= 100 and score < 5.0:
        score = min(5.0, score + 1.0)

    # Recency nudge
    if impact.recent_papers_count() > 0 and 0 < score < 2.0:
        score = 2.0

    # Penalties / recommendations — sourced from metric definitions registry
    if resolved < n:
        unresolved = n - resolved
        msg, rec = _resolve(
            "academic_impact", "academic_unresolved_papers", unresolved=unresolved
        )
        penalties.append(msg)
        if rec:
            recommendations.append(rec)

    if impact.open_access_ratio < 0.5 and resolved >= 2:
        msg, rec = _resolve("academic_impact", "academic_low_open_access")
        # academic_low_open_access has an empty message (it's a recommendation-only rule),
        # so use the recommendation field
        recommendations.append(rec or msg)

    if impact.recent_papers_count() == 0 and resolved > 0:
        msg, rec = _resolve("academic_impact", "academic_stale_papers")
        recommendations.append(rec or msg)

    return round(score, 2), penalties, recommendations
