# repo-health-analyzer

GitHub repository health analysis tool.

## Install

```bash
pip install -e ".[dev]"
```

## Usage

```bash
repo-health-analyzer owner/repo [--token TOKEN] [--json]
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
