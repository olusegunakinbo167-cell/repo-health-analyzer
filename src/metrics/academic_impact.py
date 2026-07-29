"""Academic impact metric — research paper references in repo docs.

Scans repository documentation (README, docs/, CITATION files, .bib)
for academic paper references (DOI, ArXiv, S2, PMID, etc.), resolves
them via Semantic Scholar, and aggregates citation metrics.
"""

from __future__ import annotations

import datetime
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

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


# ----------------------------------------------------------------------
# File-level safety / ReDoS protection constants
# ----------------------------------------------------------------------

# Maximum file size to parse for citations (2 MB)
# Larger files are rejected/truncated to prevent memory exhaustion
MAX_CITATION_FILE_SIZE = 2 * 1024 * 1024

# Maximum number of regex matches per pattern per file
# Prevents ReDoS / runaway matching on pathological inputs
MAX_REGEX_MATCHES = 10_000

# Markdown chunk size for large files (64 KB)
# Files larger than this are processed in overlapping chunks
MARKDOWN_CHUNK_SIZE = 64 * 1024
MARKDOWN_CHUNK_OVERLAP = 512  # bytes overlap to avoid splitting IDs

# Binary detection: if >30% of first 8KB are NUL or non-printable control chars,
# treat file as binary and skip
BINARY_DETECTION_BYTES = 8192
BINARY_THRESHOLD = 0.30


def _is_binary_content(data: bytes | str) -> bool:
    """Heuristic binary detection.

    Returns True if content looks binary (high NUL / control char ratio).
    Accepts both bytes and str inputs.
    """
    if isinstance(data, str):
        # Check for NUL chars in text — strong binary signal
        sample = data[:BINARY_DETECTION_BYTES]
        if "\x00" in sample:
            return True
        # Count suspicious control characters (excluding common whitespace)
        suspicious = sum(
            1 for c in sample
            if ord(c) < 32 and c not in "\t\n\r\f\b"
        )
        ratio = suspicious / max(1, len(sample))
        return ratio > BINARY_THRESHOLD
    else:
        # bytes input
        sample = data[:BINARY_DETECTION_BYTES]
        if b"\x00" in sample:
            return True
        suspicious = sum(1 for b in sample if b < 32 and b not in (9, 10, 13, 12, 8))
        ratio = suspicious / max(1, len(sample))
        return ratio > BINARY_THRESHOLD


def _safe_decode(data: bytes, source_file: str = "unknown") -> str | None:
    """Decode bytes to text with robust encoding fallback.

    Tries: utf-8 → utf-8-sig → latin-1 → cp1252
    Returns None if content appears binary or decoding fails.

    Binary blobs are rejected early to avoid feeding garbage into parsers.
    """
    # Binary check first
    if _is_binary_content(data):
        return None

    # Size check
    if len(data) > MAX_CITATION_FILE_SIZE:
        # Truncate to limit rather than rejecting outright —
        # citations are usually in the header/front matter
        data = data[:MAX_CITATION_FILE_SIZE]

    for encoding in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
        try:
            text = data.decode(encoding)
            # Post-decode binary check
            if _is_binary_content(text):
                continue
            return text
        except (UnicodeDecodeError, LookupError):
            continue

    # Last resort: utf-8 with replacement characters
    try:
        text = data.decode("utf-8", errors="replace")
        if _is_binary_content(text):
            return None
        return text
    except Exception:
        return None


def _safe_regex_finditer(
    pattern: re.Pattern[str], text: str, max_matches: int = MAX_REGEX_MATCHES
) -> list[re.Match[str]]:
    """Finditer with match count bound to prevent ReDoS / runaway matching.

    Stops after max_matches to prevent catastrophic backtracking or
    excessive memory usage on pathological inputs.
    """
    matches: list[re.Match[str]] = []
    try:
        for i, m in enumerate(pattern.finditer(text)):
            if i >= max_matches:
                break
            matches.append(m)
    except (re.error, RuntimeError, RecursionError, MemoryError):
        # Regex engine error / stack overflow / OOM — return what we have
        pass
    return matches


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


# ----------------------------------------------------------------------
# Structured citation file parsers (Phase 5)
# ----------------------------------------------------------------------


def _parse_citation_cff(text: str, source_file: str) -> list[PaperReference]:
    """Parse CITATION.cff (YAML) for DOIs, URLs with arXiv/DOI.

    CFF schema: https://citation-file-format.github.io/
    We extract:
    - identifiers[].type == "doi" → value
    - url / repository-code / identifiers with arXiv links
    - preferred-citation.doi

    File size limit: 2 MB (larger inputs are truncated).
    Binary content is rejected.
    Falls back to regex scan if PyYAML is unavailable or parsing fails.
    Never raises — always returns a list (possibly empty).
    """
    # File size / binary guards
    if not isinstance(text, str):
        return []
    if len(text) > MAX_CITATION_FILE_SIZE:
        text = text[:MAX_CITATION_FILE_SIZE]
    if _is_binary_content(text):
        return []

    refs: list[PaperReference] = []
    seen: set[tuple[str, str]] = set()

    def add(pid: str, id_type: str) -> None:
        # Defensive: ensure pid is a non-empty string
        if not isinstance(pid, str) or not pid:
            return
        try:
            key = (id_type, pid.lower())
            if key in seen:
                return
            seen.add(key)
            refs.append(PaperReference(
                paper_id=pid,
                id_type=id_type,
                source_file=source_file,
                context_snippet="CITATION.cff",
            ))
        except Exception:
            # Never let a bad add() crash the parser
            pass

    def _safe_regex_fallback() -> None:
        """Regex scan the raw CFF text — never raises."""
        try:
            for m in _safe_regex_finditer(DOI_RE, text):
                try:
                    add(m.group(0).lower().rstrip(".,;)]}"), "doi")
                except Exception:
                    continue
            for m in _safe_regex_finditer(ARXIV_RE, text):
                try:
                    arxiv_id = m.group(1)
                    version = m.group(2) or ""
                    add(f"{arxiv_id}{version}".lower(), "arxiv")
                except Exception:
                    continue
        except Exception:
            # re.error or other regex failure — return what we have
            pass

    # Try YAML parse first
    yaml_data_parsed = False
    try:
        import yaml  # type: ignore
    except ImportError:
        # PyYAML unavailable — fall back to regex immediately
        _safe_regex_fallback()
        return refs

    # --- YAML loading: trap scanner / parser errors explicitly ---
    try:
        data = yaml.safe_load(text)
    except Exception as e:
        # Catch all YAML errors explicitly:
        # yaml.YAMLError, yaml.scanner.ScannerError,
        # yaml.parser.ParserError, yaml.composer.ComposerError,
        # yaml.constructor.ConstructorError, etc.
        # Fall back to regex scan
        _safe_regex_fallback()
        return refs

    # --- Validate top-level type ---
    # CFF files must be a mapping at the top level.
    # If we got a list / scalar / None, treat as malformed and fall back.
    if not isinstance(data, dict):
        _safe_regex_fallback()
        return refs

    # --- Structured extraction with per-field guards ---
    try:
        # Top-level DOI
        try:
            doi = data.get("doi")
            if isinstance(doi, str):
                m = DOI_RE.search(doi)
                if m:
                    add(m.group(0).lower().rstrip(".,;)]}"), "doi")
        except Exception:
            pass

        # identifiers list
        try:
            identifiers = data.get("identifiers", [])
            if isinstance(identifiers, list):
                for ident in identifiers:
                    try:
                        if not isinstance(ident, dict):
                            continue
                        itype_raw = ident.get("type", "")
                        ival_raw = ident.get("value", "")
                        itype = str(itype_raw).lower() if itype_raw is not None else ""
                        ival = str(ival_raw) if ival_raw is not None else ""
                        if itype == "doi" and ival:
                            m = DOI_RE.search(ival)
                            if m:
                                add(m.group(0).lower().rstrip(".,;)]}"), "doi")
                        elif itype in ("arxiv", "other") and ival:
                            m = ARXIV_RE.search(ival)
                            if m:
                                arxiv_id = m.group(1)
                                version = m.group(2) or ""
                                add(f"{arxiv_id}{version}".lower(), "arxiv")
                    except Exception:
                        continue
        except Exception:
            pass

        # preferred-citation
        try:
            pc = data.get("preferred-citation")
            if isinstance(pc, dict):
                pc_doi = pc.get("doi")
                if isinstance(pc_doi, str):
                    m = DOI_RE.search(pc_doi)
                    if m:
                        add(m.group(0).lower().rstrip(".,;)]}"), "doi")
        except Exception:
            pass

        # Scan all string values for DOI/arXiv as fallback
        def scan_obj(obj: Any, depth: int = 0) -> None:
            if depth > 8:  # prevent runaway recursion
                return
            try:
                if isinstance(obj, str):
                    # Limit string length to prevent ReDoS on huge strings
                    obj_scan = obj[:65536] if len(obj) > 65536 else obj
                    for m in _safe_regex_finditer(DOI_RE, obj_scan):
                        try:
                            add(m.group(0).lower().rstrip(".,;)]}"), "doi")
                        except Exception:
                            continue
                    for m in _safe_regex_finditer(ARXIV_RE, obj_scan):
                        try:
                            arxiv_id = m.group(1)
                            version = m.group(2) or ""
                            add(f"{arxiv_id}{version}".lower(), "arxiv")
                        except Exception:
                            continue
                elif isinstance(obj, dict):
                    for v in obj.values():
                        scan_obj(v, depth + 1)
                elif isinstance(obj, list):
                    for v in obj:
                        scan_obj(v, depth + 1)
            except Exception:
                # Never let scan_obj crash the parser
                pass

        scan_obj(data)
        yaml_data_parsed = True
    except Exception:
        # Any unexpected error during structured extraction —
        # fall back to regex
        pass

    # If YAML parsing succeeded but found nothing, or if it failed
    # partway, always run the regex fallback to catch anything missed
    if not yaml_data_parsed or not refs:
        _safe_regex_fallback()

    return refs


def _parse_citation_bib(text: str, source_file: str) -> list[PaperReference]:
    """Parse BibTeX (.bib) for DOI / eprint (arXiv) / URL fields.

    Supports common entry types: @article, @inproceedings, @misc, etc.
    Extracts:
    - doi = {...}
    - eprint = {...}  (often arXiv ID)
    - archivePrefix = "arXiv"
    - url with doi.org / arxiv.org

    File size limit: 2 MB (larger inputs are truncated).
    Binary content is rejected.
    Lightweight regex parser — no external bibtex dependency.
    Never raises — always returns a list (possibly empty).
    """
    # File size / binary guards
    if not isinstance(text, str):
        return []
    if len(text) > MAX_CITATION_FILE_SIZE:
        text = text[:MAX_CITATION_FILE_SIZE]
    if _is_binary_content(text):
        return []

    refs: list[PaperReference] = []
    seen: set[tuple[str, str]] = set()

    def add(pid: str, id_type: str) -> None:
        if not isinstance(pid, str) or not pid:
            return
        try:
            key = (id_type, pid.lower())
            if key in seen:
                return
            seen.add(key)
            refs.append(PaperReference(
                paper_id=pid,
                id_type=id_type,
                source_file=source_file,
                context_snippet="CITATION.bib",
            ))
        except Exception:
            pass

    def _safe_regex_fallback() -> None:
        """Full-text regex scan — never raises."""
        try:
            for m in _safe_regex_finditer(DOI_RE, text):
                try:
                    add(m.group(0).lower().rstrip(".,;)]}"), "doi")
                except Exception:
                    continue
            for m in _safe_regex_finditer(ARXIV_RE, text):
                try:
                    arxiv_id = m.group(1)
                    version = m.group(2) or ""
                    add(f"{arxiv_id}{version}".lower(), "arxiv")
                except Exception:
                    continue
        except Exception:
            pass

    # --- Per-entry parsing with isolated error handling ---
    try:
        entries = re.split(r"@\w+\s*\{", text)
    except re.error:
        # Regex split failed — fall back to full-text scan
        _safe_regex_fallback()
        return refs

    for entry in entries[1:]:  # skip preamble
        try:
            # Extract doi field
            try:
                for m in re.finditer(
                    r"doi\s*=\s*[\"\{]\s*([^\"\},]+)\s*[\"\}]",
                    entry,
                    re.IGNORECASE,
                ):
                    try:
                        doi_val = m.group(1).strip()
                        dm = DOI_RE.search(doi_val)
                        if dm:
                            add(dm.group(0).lower().rstrip(".,;)]}"), "doi")
                    except Exception:
                        continue
            except re.error:
                pass

            # Extract eprint / archivePrefix (arXiv)
            eprint_m = None
            archive_m = None
            try:
                eprint_m = re.search(
                    r"eprint\s*=\s*[\"\{]\s*([^\"\},]+)\s*[\"\}]",
                    entry,
                    re.IGNORECASE,
                )
                archive_m = re.search(
                    r"archiveprefix\s*=\s*[\"\{]\s*([^\"\},]+)\s*[\"\}]",
                    entry,
                    re.IGNORECASE,
                )
            except re.error:
                pass

            if eprint_m:
                try:
                    eprint_val = eprint_m.group(1).strip()
                    is_arxiv = False
                    try:
                        is_arxiv = bool(
                            archive_m and "arxiv" in archive_m.group(1).lower()
                        )
                    except Exception:
                        pass

                    am = None
                    try:
                        am = ARXIV_RE.search(eprint_val)
                    except Exception:
                        pass

                    if am or is_arxiv:
                        if am:
                            try:
                                arxiv_id = am.group(1)
                                version = am.group(2) or ""
                                add(f"{arxiv_id}{version}".lower(), "arxiv")
                            except Exception:
                                pass
                        else:
                            # Bare arXiv ID in eprint field
                            try:
                                ev = eprint_val.strip()
                                if re.match(
                                    r"^\d{4}\.\d{4,5}(v\d+)?$", ev
                                ) or re.match(
                                    r"^[a-z\-]+(?:\.[a-z\-]+)?/\d{7}(v\d+)?$",
                                    ev,
                                    re.I,
                                ):
                                    add(ev.lower(), "arxiv")
                            except re.error:
                                pass
                except Exception:
                    pass

            # Extract URL field – may contain doi.org / arxiv.org links
            try:
                for m in re.finditer(
                    r"url\s*=\s*[\"\{]\s*([^\"\}]+)\s*[\"\}]",
                    entry,
                    re.IGNORECASE,
                ):
                    try:
                        url_val = m.group(1)
                        dm = DOI_RE.search(url_val)
                        if dm:
                            add(dm.group(0).lower().rstrip(".,;)]}"), "doi")
                        am = ARXIV_RE.search(url_val)
                        if am:
                            arxiv_id = am.group(1)
                            version = am.group(2) or ""
                            add(f"{arxiv_id}{version}".lower(), "arxiv")
                    except Exception:
                        continue
            except re.error:
                pass
        except Exception:
            # One malformed BibTeX entry must never kill the whole parse
            continue

    # Fallback: full-text regex scan for any missed DOIs/arXiv IDs
    _safe_regex_fallback()

    return refs


def _extract_citations_from_markdown(
    text: str, source_file: str
) -> list[PaperReference]:
    """Extract citations from Markdown with ReDoS protection.

    Strips code blocks / inline code to reduce false positives and
    ReDoS attack surface. Processes large files in bounded chunks
    to prevent catastrophic backtracking.

    Returns list[PaperReference] — never raises.
    """
    refs: list[PaperReference] = []
    seen: set[tuple[str, str]] = set()

    def add_ref(pid: str, id_type: str, start: int, end: int, chunk_offset: int = 0) -> None:
        try:
            # Normalize (same as extract_paper_references)
            if id_type == "doi":
                pid_norm = pid.lower().rstrip(".,;)]}")
            elif id_type == "arxiv":
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

            dedup_key = (
                re.sub(r"v\d+$", "", pid_norm) if id_type == "arxiv" else pid_norm
            )
            key = (id_type, dedup_key)
            if key in seen:
                return
            seen.add(key)

            # Context snippet (adjust for chunk offset)
            abs_start = start + chunk_offset
            abs_end = end + chunk_offset
            ctx = _context(text, abs_start, abs_end)
            refs.append(PaperReference(
                paper_id=pid_norm,
                id_type=id_type,
                source_file=source_file,
                context_snippet=ctx,
            ))
        except Exception:
            pass

    # --- Strip markdown code blocks to reduce ReDoS surface ---
    # Remove fenced code blocks ```...``` and ~~~...~~~
    try:
        # Limit input size to prevent memory exhaustion
        if len(text) > MAX_CITATION_FILE_SIZE:
            text = text[:MAX_CITATION_FILE_SIZE]

        # Strip fenced code blocks (non-greedy, DOTALL)
        # Guard against catastrophic backtracking with size limits
        stripped = text
        if len(stripped) < 512 * 1024:  # Only strip code blocks for reasonably sized files
            try:
                stripped = re.sub(r"```.*?```", " ", stripped, flags=re.DOTALL)
                stripped = re.sub(r"~~~.*?~~~", " ", stripped, flags=re.DOTALL)
                # Strip inline code `...`
                stripped = re.sub(r"`[^`\n]{0,500}`", " ", stripped)
            except (re.error, RecursionError, MemoryError):
                # If stripping fails, fall back to raw text
                stripped = text
        else:
            # Large file — skip expensive code-block stripping
            stripped = text
    except Exception:
        stripped = text[:MAX_CITATION_FILE_SIZE] if len(text) > MAX_CITATION_FILE_SIZE else text

    # --- Chunked processing for large markdown files ---
    # Prevents ReDoS on huge inputs by bounding regex scan windows
    text_len = len(stripped)
    if text_len <= MARKDOWN_CHUNK_SIZE:
        chunks = [(stripped, 0)]
    else:
        chunks = []
        pos = 0
        while pos < text_len:
            end = min(pos + MARKDOWN_CHUNK_SIZE, text_len)
            chunk = stripped[pos:end]
            chunks.append((chunk, pos))
            if end >= text_len:
                break
            # Overlap to avoid splitting IDs across chunk boundaries
            pos = end - MARKDOWN_CHUNK_OVERLAP

    # --- Regex scanning with match count bounds ---
    patterns = [
        (DOI_RE, "doi", lambda m: (m.group(0), m.start(), m.end())),
        (ARXIV_RE, "arxiv", lambda m: (f"{m.group(1)}{m.group(2) or ''}", m.start(), m.end())),
        (PMID_RE, "pmid", lambda m: (m.group(1), m.start(), m.end())),
        (PMCID_RE, "pmcid", lambda m: (m.group(0), m.start(), m.end())),
        (S2_CORPUS_RE, "s2_corpus", lambda m: (m.group(0), m.start(), m.end())),
        (ACL_RE, "acl", lambda m: (m.group(1), m.start(), m.end())),
    ]

    for chunk_text, chunk_offset in chunks:
        for pattern, id_type, extractor in patterns:
            try:
                matches = _safe_regex_finditer(pattern, chunk_text)
                for m in matches:
                    try:
                        pid, start, end = extractor(m)
                        # ACL heuristic: require "acl" nearby or letter prefix
                        if id_type == "acl":
                            ctx_check = chunk_text[max(0, start - 30): end + 30].lower()
                            if "acl" not in ctx_check and not re.match(r"^[a-z]", pid, re.I):
                                continue
                        # ArXiv: skip DOI-like false positives
                        if id_type == "arxiv":
                            full = m.group(0)
                            arxiv_id = m.group(1) if m.lastindex and m.lastindex >= 1 else ""
                            if "10." in full and "/" in full and len(arxiv_id) > 15:
                                continue
                        add_ref(pid, id_type, start, end, chunk_offset)
                    except Exception:
                        continue
            except Exception:
                continue

        # Early exit if we've found a lot of refs — prevents runaway work
        if len(refs) >= MAX_REGEX_MATCHES:
            break

    return refs


def extract_paper_references(
    text: str, source_file: str = "unknown"
) -> list[PaperReference]:
    """Extract all paper references from a text blob.

    For structured citation files, dispatches to specialized parsers:
    - CITATION.cff → YAML CFF parser
    - *.bib → BibTeX parser
    - *.md / *.markdown → Markdown citation extractor (ReDoS-hardened)

    Otherwise falls back to regex scanning for DOI / ArXiv / PMID / etc.

    File size limit: 2 MB (larger inputs are truncated).
    All regex matching is bounded to prevent ReDoS.

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
    # --- File size guard ---
    if not isinstance(text, str):
        return []
    if len(text) > MAX_CITATION_FILE_SIZE:
        text = text[:MAX_CITATION_FILE_SIZE]

    # Binary content guard
    if _is_binary_content(text):
        return []

    # Phase 5: structured citation file parsing —
    # Never let a parser crash propagate to collection.
    fname_lower = source_file.lower()
    if fname_lower.endswith(".cff") or "citation.cff" in fname_lower:
        try:
            return _parse_citation_cff(text, source_file)
        except Exception:
            # Hardened parsers should never raise, but belt-and-suspenders:
            # if _parse_citation_cff crashes, return empty refs rather
            # than killing repo collection.
            return []
    if fname_lower.endswith(".bib"):
        try:
            return _parse_citation_bib(text, source_file)
        except Exception:
            return []

    # Markdown files: use ReDoS-hardened markdown extractor
    if fname_lower.endswith((".md", ".markdown", ".mdown", ".mkd")):
        try:
            return _extract_citations_from_markdown(text, source_file)
        except Exception:
            # Fall through to generic regex scan
            pass

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

    # --- Regex scanning with match count bounds (ReDoS protection) ---
    # DOI — scan first (most specific)
    for m in _safe_regex_finditer(DOI_RE, text):
        add_ref(m.group(0), "doi", m.start(), m.end())

    # ArXiv
    for m in _safe_regex_finditer(ARXIV_RE, text):
        full_match = m.group(0)
        arxiv_id = m.group(1)
        version = m.group(2) or ""
        # Skip if this looks like it was already captured as part of a DOI
        if "10." in full_match and "/" in full_match and len(arxiv_id) > 15:
            continue
        pid = f"{arxiv_id}{version}"
        add_ref(pid, "arxiv", m.start(), m.end())

    # S2 CorpusId (40-char hex)
    for m in _safe_regex_finditer(S2_CORPUS_RE, text):
        add_ref(m.group(0), "s2_corpus", m.start(), m.end())

    # PMID
    for m in _safe_regex_finditer(PMID_RE, text):
        add_ref(m.group(1), "pmid", m.start(), m.end())

    # PubMed Central
    for m in _safe_regex_finditer(PMCID_RE, text):
        add_ref(m.group(0), "pmcid", m.start(), m.end())

    # ACL Anthology — run last (most likely to false-positive)
    for m in _safe_regex_finditer(ACL_RE, text):
        acl_id = m.group(1)
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

    # --- Phase 2: Enhanced impact metrics ---

    @property
    def influential_ratio(self) -> float:
        """Ratio of influential citations to total citations (0.0–1.0).

        Influential citations are those S2 has classified as significantly
        influencing the citing paper (not just a passing mention).
        """
        total = self.total_citations
        if total == 0:
            return 0.0
        return self.total_influential_citations / total

    def _paper_age_years(self, paper: S2Paper, current_year: int | None = None) -> int:
        """Age of a paper in years, minimum 1."""
        if current_year is None:
            current_year = datetime.datetime.now().year
        if paper.year is None:
            return 1
        age = max(1, current_year - paper.year + 1)
        return age

    @property
    def citation_velocity_per_year(self) -> float:
        """Average citations per paper per year (age-normalized impact).

        Computes total_citations / sum(paper_age_years) across all resolved papers.
        This prevents old papers from dominating purely on cumulative citations.
        """
        resolved = [p.s2 for p in self.papers_referenced if p.s2]
        if not resolved:
            return 0.0
        current_year = datetime.datetime.now().year
        total_age_years = sum(
            self._paper_age_years(p, current_year) for p in resolved
        )
        if total_age_years == 0:
            return 0.0
        return self.total_citations / total_age_years

    @property
    def avg_citation_velocity(self) -> float:
        """Mean per-paper citation velocity (citations/year)."""
        resolved = [p.s2 for p in self.papers_referenced if p.s2]
        if not resolved:
            return 0.0
        current_year = datetime.datetime.now().year
        velocities = [
            p.citation_count / self._paper_age_years(p, current_year)
            for p in resolved
        ]
        return sum(velocities) / len(velocities) if velocities else 0.0

    @property
    def h_index(self) -> int:
        """h-index across all referenced papers.

        The h-index is the largest h such that h papers have at least h citations.
        Standard scholarly impact metric.
        """
        citations = sorted(
            (p.s2.citation_count for p in self.papers_referenced if p.s2),
            reverse=True,
        )
        h = 0
        for i, c in enumerate(citations, start=1):
            if c >= i:
                h = i
            else:
                break
        return h

    def citation_velocity_distribution(self) -> list[float]:
        """Per-paper citation velocity list, sorted descending."""
        resolved = [p.s2 for p in self.papers_referenced if p.s2]
        current_year = datetime.datetime.now().year
        velocities = [
            p.citation_count / self._paper_age_years(p, current_year)
            for p in resolved
        ]
        return sorted(velocities, reverse=True)

    # --- Existing metrics (unchanged) ---

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
            current_year = datetime.datetime.now().year
        cutoff = current_year - years
        return sum(
            1
            for p in self.papers_referenced
            if p.s2 and p.s2.year is not None and p.s2.year >= cutoff
        )

    # --- Phase 2: Additional aggregated signals ---

    @property
    def venue_prestige_score(self) -> float:
        """Average venue quality score across resolved papers (0.0–1.0).

        Weights publicationTypes:
        - JournalArticle / Review / CaseReport → 1.0
        - Conference → 0.7
        - Dataset / Editorial / Letter → 0.4
        - Preprint / unknown → 0.2
        If journal_name is present, boost slightly.
        """
        resolved = [p.s2 for p in self.papers_referenced if p.s2]
        if not resolved:
            return 0.0

        scores: list[float] = []
        for p in resolved:
            pub_types = [t.lower() for t in (p.publication_types or [])]
            score = 0.2  # default / preprint
            if any(x in pub_types for x in ("journalarticle", "review", "casereport")):
                score = 1.0
            elif "conference" in pub_types:
                score = 0.7
            elif any(x in pub_types for x in ("dataset", "editorial", "letter")):
                score = 0.4
            # Boost if journal is named
            if p.journal_name:
                score = min(1.0, score + 0.1)
            scores.append(score)

        return sum(scores) / len(scores) if scores else 0.0

    @property
    def recency_weighted_citations(self) -> float:
        """Total citations weighted by recency decay.

        Weight = 1 / (1 + 0.15 × age_years)
        Recent highly-cited papers contribute more than old ones.
        """
        resolved = [p.s2 for p in self.papers_referenced if p.s2]
        if not resolved:
            return 0.0
        current_year = datetime.datetime.now().year
        total = 0.0
        for p in resolved:
            age = self._paper_age_years(p, current_year) - 1
            weight = 1.0 / (1.0 + 0.15 * age)
            total += p.citation_count * weight
        return total

    @property
    def impact_tier(self) -> str:
        """Qualitative impact tier.

        Tiers based on h-index and avg citation velocity:
        - exceptional: h >= 5 and velocity >= 150
        - high:        h >= 3 and velocity >= 50
        - moderate:    h >= 1 and velocity >= 10
        - low:         any resolved papers
        - none:        no papers
        """
        if self.resolved_count == 0:
            return "none"
        h = self.h_index
        vel = self.avg_citation_velocity
        if h >= 5 and vel >= 150:
            return "exceptional"
        if h >= 3 and vel >= 50:
            return "high"
        if h >= 1 and vel >= 10:
            return "moderate"
        return "low"


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

    # Penalties / recommendations
    if resolved < n:
        unresolved = n - resolved
        penalties.append(
            f"{unresolved} referenced paper(s) could not be resolved via Semantic Scholar"
        )

    if impact.open_access_ratio < 0.5 and resolved >= 2:
        recommendations.append(
            "Consider referencing open-access versions of papers where available"
        )

    if impact.recent_papers_count() == 0 and resolved > 0:
        recommendations.append(
            "Referenced papers are all older than 3 years — "
            "check if newer related work exists"
        )

    return round(score, 2), penalties, recommendations
