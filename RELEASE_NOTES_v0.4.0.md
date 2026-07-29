# Release Notes — repo-health-analyzer v0.4.0

**Release date:** 2026-07-29

## 📚 Academic Impact Scoring with Semantic Scholar

This release adds full academic impact analysis to repo-health-analyzer. The tool now scans repository documentation for academic paper references (DOI, ArXiv, Semantic Scholar CorpusId, PMID, ACL Anthology, PubMed Central), resolves them via the Semantic Scholar API, and surfaces rich citation metadata in all export formats.

### What’s New

**Paper Reference Collection**
- Auto-discovers paper IDs in README, `docs/`, `CITATION.cff`, and `CITATION.bib` files
- Supports DOI, ArXiv, S2 CorpusId, PMID, ACL Anthology, and PubMed Central identifiers
- Cross-ID deduplication (e.g., `ArXiv:1706.03762` and `DOI:10.xxx` resolving to the same paper)

**Semantic Scholar API Client**
- Batch paper resolution with rate-limit aware backoff
- 30-day TTL response cache (`.repo_health_s2_cache.json`)
- Free API key support: set `S2_API_KEY` or pass `--s2-api-key`

**Impact Metrics**
- Total citations, avg citations/paper, **citation velocity** (cites/yr)
- **h-index** across referenced papers
- **Venue prestige score** (weighted by publication venue tier)
- **Impact tier**: exceptional / high / moderate / low / none
- Influential citation count & ratio, open-access ratio, recency-weighted citations
- Fields of study aggregation

**Exporter Improvements**
- **JSON**: Full `academic_impact` object with all computed scores + per-paper S2 metadata (`tldr`, `publication_types`, `arxiv_url`, `doi_url`, `citation_velocity`)
- **Markdown**: Dedicated "📚 Academic Impact" section with impact tier, velocity, venue prestige; collapsible paper list with TLDRs and arXiv/DOI links
- **HTML**: Full academic impact card with styled paper list
- **Terminal**: Rich academic snapshot with top 3 papers and TLDRs

**CLI Controls**
```bash
# Limit papers in export
--academic-max-papers 5

# Exclude TLDRs
--academic-no-tldr

# Include unresolved references
--academic-include-unresolved

# Skip academic scanning entirely
--skip-academic
```

### Scoring Impact

The total health score weight increases from 100 to **110 pts**, with the new `academic_impact` category contributing 10 pts:

| Category | Max Score |
|---|---|
| Documentation | 20 |
| Maintenance | 25 |
| CI/CD | 25 |
| Governance | 20 |
| **Academic Impact** | **10** |

Paper reference bonus (Documentation category):
- 1–2 papers → 2 pts
- 3–5 papers → 3.5 pts
- 6+ papers → 5 pts

High-impact papers (≥100 avg citations) and recent papers (<3 years) receive additional weighting.

### Breaking Changes

- Health score total increases from 100 to 110. Update quality gates accordingly (e.g., `--min-score 70` now evaluates against 110 pts).
- JSON export schema: new top-level `academic_impact` object in `metrics`. Existing fields unchanged.

### Upgrade Notes

- No S2 API key required for basic operation, but **recommended** for reliable lookups (unauthenticated requests share a global rate limit)
- Get a free key at https://www.semanticscholar.org/product/api#api-key-form
- To disable academic scanning in CI/offline environments: `--skip-academic` or `REPO_HEALTH_SKIP_ACADEMIC=1`

### Test Coverage

- 240 tests passing (18 exporter tests, 20 academic impact tests)
- End-to-end S2 lookup verified against real papers (e.g., `ArXiv:1706.03762` — "Attention is All you Need")
- Export formatting validated for JSON + Markdown (paper titles, arXiv/DOI links, citation counts, TLDRs)

---

**Full Changelog:** https://github.com/olusegunakinbo167-cell/repo-health-analyzer/compare/v0.2.1...v0.4.0
