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

# National Weather Service forecasts / alerts (dev downtime 🌤️)
repo-health-analyzer weather <command> [options]
```

### Analyze options

| Flag | Description |
|---|---|
| `--output PATH, -o PATH` | Write health report to PATH (format auto-detected from extension) |
| `--format {json,markdown,auto}` | Output format for `--output` (default: auto) |
| `--token TOKEN` | GitHub personal access token (default: `GITHUB_TOKEN` env var) |
| `--s2-api-key KEY` | Semantic Scholar API key for academic impact metrics (default: `S2_API_KEY` / `SEMANTIC_SCHOLAR_API_KEY` env var) |
| `--skip-academic` | Skip academic impact / paper reference scanning (faster, no S2 API calls) |
| `--min-score N` | Quality gate threshold — exit with code 1 if health score is below N (default: 70.0) |
| `--config PATH` | Path to local `.repo-health.yml` config file (default: auto-fetch from target repo root) |
| `--baseline PATH` | Path to a prior artifact JSON to compare against — category score deltas are shown in terminal and Markdown output |
| `--weather-location LAT,LONG` | Latitude,longitude for environment weather context (default: `37.7749,-122.4194` — San Francisco, CA). Set to empty string to skip. |
| `--no-color` | Disable Rich color output in terminal |
| `--json` | *(deprecated)* Output results as JSON to stdout — use `-o report.json` instead |
| `--markdown PATH` | *(deprecated)* Write Markdown report to PATH — use `-o report.md` instead |
| `--save-artifact PATH` | *(deprecated)* Save run metadata to JSON — use `-o artifact.json` instead |

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

# Export to JSON (includes plugin statuses)
repo-health-analyzer myorg/myrepo -o health-report.json

# Export to Markdown (suitable for $GITHUB_STEP_SUMMARY or PR comments)
repo-health-analyzer myorg/myrepo -o health-report.md

# With academic impact (S2 API key from env)
export S2_API_KEY=your_key_here
repo-health-analyzer myorg/myrepo -o report.json

# Skip academic scanning (faster)
repo-health-analyzer myorg/myrepo --skip-academic -o report.md

# CI pipeline with quality gate
repo-health-analyzer myorg/myrepo \
  -o health-report.md \
  --min-score 75 \
  --baseline ./previous-run.json
```

### Baseline Comparison

Pass `--baseline PATH` with a prior `analyze` JSON artifact to compare the current run against a baseline commit. Category score deltas appear in terminal output and in exported Markdown/HTML/JSON reports.

**Schema drift handling:** When a category exists in the current run but was not present in the baseline file (e.g., new scoring categories added in a tool upgrade), the category is rendered as **new** rather than defaulting its baseline score to `0.0`. Missing categories are excluded from the overall score delta sum, so they can't mask real regressions in comparable categories.

**Weight rebalancing:** When a category's `max_score` differs between baseline and current runs, the delta is normalized to percentage points and displayed as `±X.Xpp` instead of raw point values. For example, Documentation scoring 20/25 (80%) → 16/20 (80%) is a **0.0pp** change, not −4.0 pts.

In JSON exports, missing baseline categories are `null`:

```json
"financial": {
  "name": "Financial",
  "current": 11.0,
  "baseline": null,
  "delta": null,
  "percentage_delta": null
}
```

Terminal and HTML/Markdown reporters display `new` / `— new` badges for missing-baseline categories, and `±X.Xpp` when category weights have changed.

The Python API is `BaselineDiff.compare(current: HealthScore, baseline: HealthScore) -> BaselineDiff` in `src/models.py`.

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

### Weather subcommand (dev downtime 🌤️)

`repo-health-analyzer weather` wraps the [OpenClaw Weather Service CLI](https://github.com/openclaw/openclaw) for National Weather Service forecasts, observations, and alerts — useful for logging local environment context alongside repo health runs.

Requires Python 3 and the Weather Service CLI installed at `~/.openclaw/extensions/weather-service/weather-service` (also found at `/usr/lib/node_modules/openclaw/dist/extensions/weather-service/skills/weather-service/weather-service` in OpenClaw installs; override with `WEATHER_SERVICE_CLI=/path/to/weather-service`). All commands are read-only, no API key required.

Environment context (forecast + alerts + observation) is **automatically collected during `repo-health-analyzer analyze` runs** and included in the exported report (`environment_context` field in JSON / Environment Context section in Markdown). Default location: San Francisco, CA (`37.7749,-122.4194`). Override with `--weather-location LAT,LONG`, or set to empty string to skip weather collection.

```bash
# Get forecast (default: San Francisco)
repo-health-analyzer weather forecast
repo-health-analyzer weather forecast --location "40.7128,-74.0060"

# Hourly forecast
repo-health-analyzer weather hourly --location "37.7749,-122.4194"

# Active weather alerts
repo-health-analyzer weather alerts --area CA
repo-health-analyzer weather alerts --location "37.7749,-122.4194"

# Find nearby observation stations
repo-health-analyzer weather stations --location "37.7749,-122.4194"

# Get station observation
repo-health-analyzer weather observation --station-id KSFO

# Full environment context (forecast + alerts + observation)
repo-health-analyzer weather context --location "37.7749,-122.4194"
```

All weather commands support `--json` for scripting.

Analyze with custom weather location:

```bash
repo-health-analyzer analyze owner/repo \
  -o run_summary.json \
  --weather-location "40.7128,-74.0060"
```

The exported `run_summary.json` includes both the GitHub health score and the weather payload under `environment_context`.

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
