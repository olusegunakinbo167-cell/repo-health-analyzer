# repo-health-analyzer

GitHub repository health analysis tool.

Analyzes repositories across 4 categories (Documentation, Maintenance, CI/CD, Governance) with an optional academic impact score that surfaces research paper references and citation metrics.

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

# Dog breed traits / genetic health info (dev downtime 🐕)
repo-health-analyzer embark <command> [options]
```

### Analyze options

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

### Embark subcommand (dev downtime 🐕)

`repo-health-analyzer embark` wraps the [OpenClaw Embark Dog DNA CLI](https://github.com/openclaw/openclaw) for looking up dog breeds, genetic traits, and health conditions — another fun easter egg for dev downtime, not part of repo health scoring.

Requires Node.js and the Embark CLI installed at `~/.openclaw/extensions/embark/embark.js` (override with `EMBARK_CLI=/path/to/embark.js`). All commands are read-only.

`breeds` and `traits` use offline cached data by default (~400 breeds, ~30 traits), avoiding Cloudflare WAF blocks. Use `--live` to force a fresh scrape from embarkvet.com.

`breed`, `health-search`, and `health` require live HTTP requests to embarkvet.com and may be blocked by Cloudflare Bot Management on AWS/datacenter IPs. Set `EMBARK_COOKIE` or `EMBARK_COOKIE_FILE` with a valid browser session cookie to bypass.

```bash
# Search dog breeds (offline cached, default)
repo-health-analyzer embark breeds --query retriever

# Search all breeds
repo-health-analyzer embark breeds

# Force live breed scrape (may trigger CF WAF)
repo-health-analyzer embark breeds --query poodle --live

# Get full breed profile (live, may need CF cookie)
repo-health-analyzer embark breed --breed-slug golden-retriever

# Search genetic health conditions (live)
repo-health-analyzer embark health-search --query mdr1

# Get health condition detail (live)
repo-health-analyzer embark health --condition-slug mdr1-drug-sensitivity

# List/search genetic traits (offline cached, default)
repo-health-analyzer embark traits --query coat

# Force live trait scrape
repo-health-analyzer embark traits --live
```

All Embark commands support `--json` for scripting.

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
