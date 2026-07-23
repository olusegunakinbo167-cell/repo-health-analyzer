# repo-health-analyzer

Analyzes a GitHub repo's health and generates a simple quality score.

## Overview

`repo-health-analyzer` scans a public GitHub repository using the GitHub API and produces a lightweight health report. It looks at signals that typically indicate whether a project is well-maintained, active, and easy for others to contribute to — similar in spirit to tools like CodeClimate, but intentionally simple and easy to read end-to-end.

This project applies an evaluation/scoring mindset — similar to rubric-based QA used for LLM responses in [llm-eval-toolkit](https://github.com/olusegunakinbo167-cell/llm-eval-toolkit) and [Evaluators](https://github.com/olusegunakinbo167-cell/Evaluators) — to software repositories instead.

## What It Checks

- **Commit activity** — frequency and recency of commits
- **README quality** — presence and basic length/structure check
- **Issue age** — how long open issues have been sitting unaddressed
- **Dependency freshness** — whether `requirements.txt` / `package.json` dependencies look outdated
- **License presence** — whether the repo has a license file

Each check contributes to an overall **health score** (0–100), with a short breakdown explaining the score.

## Project Structure

```
repo-health-analyzer/
├── README.md
├── requirements.txt
├── scripts/
│   └── analyze_repo.py   # main analysis script
├── results/                # saved reports
└── notes/                   # scoring rubric notes, ideas
```

## Usage

```bash
python scripts/analyze_repo.py owner/repo-name
```

Example:

```bash
python scripts/analyze_repo.py olusegunakinbo167-cell/llm-eval-toolkit
```

This will print a health report to the console, including the overall score and a breakdown per category.

## Setup

You'll need a GitHub personal access token to avoid API rate limits. Set it as an environment variable:

```bash
export GITHUB_TOKEN=your_token_here
```

## Status

 Early stage — starting with the core checks above. Planned additions: HTML report output, CLI flags for custom weighting, and CI integration.

## License

TBD
