# repo-health-analyzer

GitHub repository health analysis tool.

Analyzes repositories across 4 categories (Documentation, Maintenance, CI/CD, Governance) with an optional academic impact score that surfaces research paper references and citation metrics.

## Install

```bash
pip install -e ".[dev]"
```

## Usage

```bash
repo-health-analyzer owner/repo [options]
```

### Options

| Flag | Description |
|---|---|
| `--token TOKEN` | GitHub personal access token (default: `GITHUB_TOKEN` env var) |
| `--s2-api-key KEY` | Semantic Scholar API key for academic impact metrics (default: `S2_API_KEY` / `SEMANTIC_SCHOLAR_API_KEY` env var) |
| `--skip-academic` | Skip academic impact / paper reference scanning (faster, no S2 API calls) |
| `--json` | Output results as JSON |
| `--markdown PATH` | Write a GitHub-flavored Markdown report to PATH (suitable for `$GITHUB_STEP_SUMMARY` or PR comments) |
| `--min-score N` | Quality gate threshold — exit with code 1 if health score is below N (default: 70.0) |
| `--save-artifact PATH` | Save complete run metadata (metrics, health_score, timestamp, repo SHA) to a JSON file |
| `--config PATH` | Path to local `.repo-health.yml` config file (default: auto-fetch from target repo root) |
| `--baseline PATH` | Path to a prior artifact JSON to compare against — category score deltas are shown in terminal and Markdown output |
| `--no-color` | Disable Rich color output in terminal |

### Academic impact / paper references

`repo-health-analyzer` scans repository documentation (README, `docs/`, `CITATION.*` files) for academic paper references — DOI, ArXiv, Semantic Scholar CorpusId, PMID, ACL Anthology, and PubMed Central IDs — then resolves them via the [Semantic Scholar API](https://www.semanticscholar.org/product/api) to aggregate citation counts, influential citations, fields of study, and open-access status.

Referenced papers contribute a 0–5 pt bonus to the Documentation category score:
- 1–2 papers → 2 pts
- 3–5 papers → 3.5 pts
- 6+ papers → 5 pts

High-impact papers (≥100 avg citations) and recent papers (<3 years) receive additional weighting.

An S2 API key is recommended for reliable lookups — unauthenticated requests share a global rate limit and may be throttled. Get a free key at https://www.semanticscholar.org/product/api#api-key-form, then set `S2_API_KEY` or pass `--s2-api-key`.

To disable academic impact scanning entirely (offline / CI environments), use `--skip-academic` or set `REPO_HEALTH_SKIP_ACADEMIC=1`.

### Examples

```bash
# Basic analysis
repo-health-analyzer octocat/Hello-World

# With academic impact (S2 API key from env)
export S2_API_KEY=your_key_here
repo-health-analyzer myorg/myrepo

# Skip academic scanning (faster)
repo-health-analyzer myorg/myrepo --skip-academic

# JSON output + Markdown report for CI
repo-health-analyzer myorg/myrepo \
  --json \
  --markdown ./health-report.md \
  --min-score 75 \
  --save-artifact ./health-artifact.json
```

Or via module:

```bash
python -m src.cli owner/repo
```

Authentication: pass `--token` or set `GITHUB_TOKEN` env var.

## Development

```bash
ruff check .
pytest -q
```
