# Changelog

All notable changes to repo-health-analyzer are documented in this file.

## [0.4.0] - 2026-07-29

### Added

#### Academic Impact / Semantic Scholar Integration
- **S2 paper reference collector**: Scans README, `docs/`, and `CITATION.*` files for academic paper IDs (DOI, ArXiv, Semantic Scholar CorpusId, PMID, ACL Anthology, PubMed Central)
- **Semantic Scholar API client** (`src/semantic_scholar_client.py`): Resolves paper references with citation counts, TLDRs, venue metadata, publication types, arXiv/DOI links
  - Batch resolution with rate limit backoff (1 req/s unauth, 10 req/s with API key)
  - 30-day TTL response cache with cross-ID deduplication (`.repo_health_s2_cache.json`)
  - Supports `--s2-api-key` / `S2_API_KEY` / `SEMANTIC_SCHOLAR_API_KEY` env vars
- **CITATION.cff / CITATION.bib parser**: Extracts DOI/ArXiv identifiers from structured citation files
- **Academic impact scoring** (`src/metrics/academic_impact.py`):
  - Total citations, avg citations/paper, citation velocity (cites/yr)
  - h-index, venue prestige score, impact tier (exceptional/high/moderate/low/none)
  - Influential citation count / ratio, open-access ratio, recency-weighted citations
  - Fields of study aggregation
  - Documentation category bonus: 1–2 papers → 2 pts, 3–5 papers → 3.5 pts, 6+ papers → 5 pts

#### Exporter Enhancements
- **JSON exporter**: `academic_impact` object includes all computed scores (`citation_velocity_per_year`, `venue_prestige_score`, `impact_tier`, `h_index`, etc.) and per-paper S2 metadata (`tldr`, `publication_types`, `arxiv_url`, `doi_url`, `citation_velocity`)
- **Markdown exporter**: Dedicated "📚 Academic Impact" section with impact tier badge, citation velocity, h-index, venue prestige, influential citations. Collapsible "📖 Referenced Papers" list with title/year, authors, venue, citation velocity, arXiv/DOI/PDF links, and TLDR blockquotes. Academic impact (10 pts) included in category breakdown table.
- **HTML exporter**: Full academic impact card with paper list, TLDRs, arXiv/DOI links, venue prestige, citation velocity. Styled with dedicated CSS.
- **Rich terminal reporter**: Academic snapshot showing impact tier, citation velocity, h-index, venue prestige, and top 3 papers with TLDRs + arXiv/DOI links

#### CLI
- `--skip-academic`: Skip academic impact / paper reference scanning (faster, no S2 API calls)
- `--academic-max-papers N`: Max referenced papers to include in Markdown/HTML exports (default: 20, 0 = unlimited)
- `--academic-no-tldr`: Exclude paper TLDRs from exports
- `--academic-include-unresolved`: Include unresolved paper references in exports
- `REPO_HEALTH_SKIP_ACADEMIC=1` environment variable to disable academic scanning globally

### Changed
- Health score total weight increased from 100 to 110 pts (academic_impact: 10 pts, documentation: 20 pts, maintenance: 25 pts, ci_cd: 25 pts, governance: 20 pts)
- Exporter protocol (`src/exporters/base.py`) extended to accept `academic_max_papers`, `academic_include_tldr`, `academic_include_unresolved` kwargs
- `export_report()` forwards academic export options to all format exporters (JSON, Markdown, HTML)

### Fixed
- S2 client mock test (`test_s2_client_get_paper_mock`) – disable response cache during test to ensure mock is hit

## [0.2.1] - 2025-??-??

Prior release.
