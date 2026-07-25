# repo-health-analyzer

GitHub repository health analysis tool.

Analyzes repositories across 4 categories — Documentation, Maintenance, **CI/CD & Code Quality**, and Governance — with optional code complexity (radon/cyclomatic), code churn hotspot detection, and academic impact scoring that surfaces research paper references and citation metrics.

## Install

```bash
pip install -e ".[dev]"
```

## Usage

```bash
# Repository health analysis
repo-health-analyzer analyze owner/repo [options]
# (Backwards compat: `repo-health-analyzer owner/repo [...]` also works)

# Movie showtimes / theater listings (dev downtime 🎬)
repo-health-analyzer movies <command> [options]
```

### Analyze options

| Flag | Description |
|---|---|
| `--token TOKEN` | GitHub personal access token (default: `GITHUB_TOKEN` env var) |
| `--s2-api-key KEY` | Semantic Scholar API key for academic impact metrics (default: `S2_API_KEY` / `SEMANTIC_SCHOLAR_API_KEY` env var) |
| `--skip-academic` | Skip academic impact / paper reference scanning (faster, no S2 API calls) |
| `--local-path PATH` | Path to a local checkout — enables code complexity and churn analysis (requires `radon`, `gitpython`). Auto-detected if the repository argument is a local directory. |
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

### Scoring categories

#### Documentation (25 pts)
- README — 10 pts
- LICENSE — 5 pts
- CONTRIBUTING.md — 5 pts
- CODE_OF_CONDUCT.md — 5 pts
- Academic impact bonus — up to +5 pts (capped at 25), for research paper references in docs

#### Maintenance (25 pts)
- Commit velocity — 10 pts (with churn data) / 15 pts (legacy, no churn)
  - ≥20 commits/90d → 10/15 pts
  - ≥10 commits/90d → 8/12 pts
  - ≥5 commits/90d → 5/8 pts
  - ≥1 commits/90d → 2/4 pts
- Issue close ratio — 10 pts
  - ≥80% → 10 pts, ≥60% → 7 pts, ≥40% → 4 pts, <40% → 1 pt
- Code churn — 0–5 pts (requires `--local-path` / local directory)
  - Churn score ≤25 → 5 pts, ≤50 → 3 pts, ≤75 → 1 pt, >75 → 0 pts
  - Trend adjustment: falling +1 pt, rising −1 pt
  - High-churn hotspot files are flagged in recommendations
- Bus factor penalty — up to −5 pts if top author owns >70% of commits

#### CI/CD & Code Quality (25 pts)
- Workflow count — 0–20 pts
  - 3+ workflows → 20 pts, 2 → 15 pts, 1 → 10 pts
- Code complexity — 0–5 pts (requires `--local-path` / local directory)
  - Cyclomatic complexity via `radon`, SonarQube-aligned A–E rating
  - Rating A/B → 5 pts, C → 3 pts, D → 1 pt, E → 0 pts
  - High-risk functions (CC > 10) are flagged with file/line
  - If complexity data is unavailable, workflow score scales to 25 pts (no penalty)

#### Governance (25 pts)
- LICENSE file presence — 10 pts
- Stale PR ratio — 15 pts
  - 0 stale PRs → 15 pts, ≤10% stale → 10 pts, ≤25% stale → 5 pts, >25% → 0 pts

### Code quality analysis (complexity & churn)

Code complexity and churn metrics require a local checkout of the repository:

```bash
# Auto-detect: pass a local directory as the repository argument
repo-health-analyzer analyze ./myrepo --skip-academic

# Explicit override
repo-health-analyzer analyze myorg/myrepo --local-path ./myrepo
```

- **Complexity** — Cyclomatic complexity per function via [`radon`](https://radon.readthedocs.io/), mapped to SonarQube A–E ratings. Install with `pip install radon>=6.0`
- **Churn** — Git history analysis (insertions/deletions per file, 90-day window), hotspot detection, trend tracking. Install with `pip install gitpython>=3.1`

Both are optional dependencies — if missing, the analyzer fails open with no penalty to the score.

### Examples

```bash
# Basic analysis (GitHub API only)
repo-health-analyzer octocat/Hello-World

# Analyze a local checkout — auto-enables complexity + churn
repo-health-analyzer ./myrepo --skip-academic

# Remote repo with local checkout override (for CI)
repo-health-analyzer myorg/myrepo --local-path ./myrepo

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

### Movies subcommand (dev downtime 🎬)

`repo-health-analyzer movies` wraps the [OpenClaw Fandango CLI](https://github.com/openclaw/openclaw) for checking movie showtimes, theater schedules, and seat availability — a fun easter egg for dev downtime, not part of repo health scoring.

Requires Node.js and the Fandango CLI installed at `~/.openclaw/extensions/fandango/fandango.js` (override with `FANDANGO_CLI=/path/to/fandango.js`). All commands are read-only.

```bash
# Search for movies
repo-health-analyzer movies search "odyssey"

# Showtimes for a movie near a ZIP code
repo-health-analyzer movies showtimes --movie-id 241283 --date 2026-07-25 --zip 78701

# All movies at a theater
repo-health-analyzer movies theater --theater-id aawjb --date 2026-07-25

# Available dates for a theater
repo-health-analyzer movies calendar --theater-id aawjb

# Seat availability (get showtimeHashCode from showtimes output)
repo-health-analyzer movies seats v2-d6971c7a5447715c79f18ac5c95ddca946140ce13d2b8286f4a8b86b4fc33c94 --render
```

All movie commands support `--json` for scripting. Movie/theater IDs come from Fandango URLs, e.g. `/the-odyssey-2026-241283/movie-overview` → movie ID `241283`.

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
