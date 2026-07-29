# Changelog

All notable changes to repo-health-analyzer are documented in this file.

## [Unreleased]

### Security

- **Academic impact parser hardening (ReDoS protection)**
  - Bounded all regex quantifiers in citation extraction to prevent catastrophic backtracking:
    - `DOI_RE`: suffix quantifier bounded to `{1,256}` chars
    - `ARXIV_RE`: archive name segments capped to `{1,32}`, version to `{1,3}`
  - Added chunked regex scanning (500 KB chunks with 256 B overlap) to cap worst-case CPU on pathological Markdown inputs
  - All regex failures are caught and recorded in diagnostics instead of crashing extraction
  - Added 23 fuzz tests covering binary payloads, oversized inputs (>2 MB), pathological regex triggers, nested brackets, long single-line inputs, YAML bombs, and unclosed BibTeX braces

- **File-level safety guards**
  - Enforced 2 MB size limit across the entire citation extraction pipeline (`collector.py`, `github_client.py`, `academic_impact.py`)
  - Binary content detection (NUL byte / control-char heuristic) in all parsers (`.md`, `.cff`, `.bib`)
  - Robust encoding fallback chain: UTF-8 → UTF-8-SIG → Latin-1 → UTF-8/replace
  - Oversized files are truncated safely with warnings recorded in diagnostics
  - Binary blobs and malformed files are skipped cleanly without high memory usage
  - GitHub Contents API pre-filters oversized files via `size` field before base64 decode

### Added

- **Extraction diagnostics tracking** (`src/metrics/academic_impact.py`)
  - New `ExtractionDiagnostics` dataclass tracking: files_scanned, files_skipped_binary, files_skipped_oversize, files_truncated, files_failed, citations_found, bytes_processed, syntax_warnings[]
  - New `SyntaxWarning` type with source_file, warning_type, message, line
  - New `ExtractionError` exception for strict-mode fail-fast behavior
  - Diagnostics flow through the entire pipeline: `extract_paper_references()` → `extract_from_files()` → `resolve_paper_references()` → `AcademicImpact.extraction_diagnostics`
  - Parser functions (`_parse_citation_cff`, `_parse_citation_bib`, `_extract_citations_from_markdown`) all accept `diagnostics` + `strict` parameters

- **CLI: `--academic-strict` flag** (`src/cli.py`)
  - Raise exceptions on skipped citation files (binary, oversize, parse failures)
  - Default behavior: malformed files are skipped with warnings recorded in diagnostics
  - Configurable via `REPO_HEALTH_ACADEMIC_STRICT=1` environment variable
  - Threads through `run()` → `RepoCollector(academic_strict=...)` → `extract_from_files(strict=...)`

- **JSON exporter: extraction diagnostics block** (`src/exporters/json_exporter.py`)
  - `_serialize_academic_impact()` now includes `"extraction_diagnostics"` with full counts + syntax_warnings array
  - Schema-stable: empty diagnostics block provided when none available
  - Enables programmatic monitoring of parser health in CI

- **Markdown exporter: extraction summary rendering** (`src/exporters/markdown_exporter.py`)
  - Academic Impact section renders even with 0 papers when diagnostics exist
  - "Extraction summary" block shows files scanned, citations found, bytes processed, binary skipped, truncated, failed, syntax warnings
  - First 5 syntax warnings rendered inline with source_file + warning_type
  - 🔒 Strict mode indicator when `--academic-strict` is enabled

- **Test coverage**
  - `tests/test_fuzz_parsers.py` (new, 23 tests): binary payload handling, oversized input handling, pathological regex / ReDoS triggers, encoding robustness, Markdown edge cases, structured file fuzz
  - `tests/test_exporters.py`: added `test_exporters_render_diagnostics_gracefully()` verifying JSON/Markdown reports render correctly with malformed/truncated inputs

### Changed

- **Breaking: `extract_from_files()` signature**
  - Old: `extract_from_files(files: dict[str, str]) -> list[PaperReference]`
  - New: `extract_from_files(files: dict[str, str], *, strict: bool = False, diagnostics: ExtractionDiagnostics | None = None) -> tuple[list[PaperReference], ExtractionDiagnostics]`
  - Added `extract_from_files_legacy()` compatibility wrapper returning refs only
  - All internal callers updated (`collector.py`, test suite)

- **Breaking: `extract_paper_references()` signature**
  - Added optional `diagnostics: ExtractionDiagnostics | None = None, strict: bool = False` parameters
  - Backward compatible for callers not passing diagnostics (defaults to `None`)

- **`resolve_paper_references()` signature**
  - Added optional `diagnostics: ExtractionDiagnostics | None = None` parameter
  - Attaches diagnostics to returned `AcademicImpact` object

- **`AcademicImpact` model**
  - Added `extraction_diagnostics: ExtractionDiagnostics | None = None` field

- **`RepoCollector`**
  - Added `academic_strict: bool = False` parameter
  - Captures and preserves `ExtractionDiagnostics` end-to-end, even with 0 papers or S2 failures

### Fixed

- Prevent memory exhaustion from binary blobs or massive log files in citation extraction
- Prevent ReDoS (catastrophic backtracking) in DOI / ArXiv regex parsing
- Prevent unbounded context snippet growth in `_context()`
- Graceful degradation on malformed YAML in `CITATION.cff` parsing
- Graceful degradation on unclosed braces in BibTeX parsing
- Proper encoding fallback when GitHub file content is not valid UTF-8

---

## [0.2.1] - 2026-07-25

### Added
- Baseline comparison with schema drift handling
- Financial impact scoring
- Org-batch runner and exporters

### Fixed
- BaselineDiff nullable handling
- Academic impact loading in baseline deserializer
