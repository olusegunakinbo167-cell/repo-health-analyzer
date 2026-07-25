# metrics/embark.py
"""Embark Dog DNA breed traits and genetic health information wrapper.

Calls the local OpenClaw Embark CLI at ~/.openclaw/extensions/embark/embark.js
via subprocess. All commands are read-only.

search-breeds and list-traits use offline cached data by default
(data/breeds.json, data/traits.json), avoiding Cloudflare WAF blocks.
Use live=True to force a fresh scrape (may trigger CF WAF on datacenter IPs).

get-breed, search-health, and get-health require live HTTP requests to
embarkvet.com and may be blocked by Cloudflare Bot Management on AWS/datacenter
IPs. Set EMBARK_COOKIE or EMBARK_COOKIE_FILE with a valid browser session cookie
to bypass, or run from a non-datacenter IP.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ._external_cli import (
    CLIWAFBlockError,
    ExternalCLI,
    ExternalCLIError,
)

_EMBARK_CLI = ExternalCLI(
    name="embark",
    cli_filename="embark.js",
    env_var="EMBARK_CLI",
    candidates=[
        Path.home() / ".openclaw" / "extensions" / "embark" / "embark.js",
    ],
    json_flag="",  # embark.js outputs JSON by default, no --json flag
    node_required=True,
)


def find_embark_cli() -> Path:
    """Locate the embark.js CLI."""
    return _EMBARK_CLI.find_cli()


def _run_embark(args: list[str], timeout: float = 20.0) -> Any:
    """Invoke embark.js and return parsed JSON output.

    The Embark CLI outputs JSON to stdout by default. On error it prints
    {"error": "..."} to stderr and exits non-zero. We parse stdout first;
    if that fails, check for structured error JSON in stderr.

    Raises
    ------
    CLIWAFBlockError
        Cloudflare / WAF block detected (cf_waf_block).
    ExternalCLIError
        Other CLI failures.
    """
    cli_path = _EMBARK_CLI.find_cli()
    import json
    import subprocess

    cmd = ["node", str(cli_path), *args]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        from ._external_cli import CLITimeoutError

        raise CLITimeoutError(f"embark CLI timed out after {timeout}s: {exc}") from exc

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""

    # WAF / Cloudflare block detection
    if "cf_waf_block" in (stdout + stderr).lower():
        combined = (stderr.strip() or stdout.strip() or "WAF block detected")
        raise CLIWAFBlockError(f"embark CLI blocked by Cloudflare / WAF: {combined}")

    # Try parsing stdout as JSON (normal success path)
    if proc.returncode == 0:
        try:
            return json.loads(stdout)
        except json.JSONDecodeError as exc:
            from ._external_cli import CLIInvalidJSONError

            raise CLIInvalidJSONError(
                f"embark CLI returned invalid JSON: {exc}\n{stdout[:500]}"
            ) from exc

    # Non-zero exit — try to parse structured error from stderr/stdout
    for output in (stderr, stdout):
        if not output.strip():
            continue
        try:
            err_data = json.loads(output)
            if isinstance(err_data, dict) and "error" in err_data:
                err_msg = err_data.get("error", "")
                err_detail = err_data.get("message", "")
                full_msg = f"{err_msg}: {err_detail}" if err_detail else err_msg
                # Re-check for WAF block in structured error
                if "cf_waf_block" in full_msg.lower() or "waf" in full_msg.lower():
                    raise CLIWAFBlockError(f"embark CLI blocked by Cloudflare / WAF: {full_msg}")
                raise ExternalCLIError(f"embark CLI failed: {full_msg}")
        except json.JSONDecodeError:
            pass

    # Fall back to raw error text
    err = stderr.strip() or stdout.strip() or "unknown error"
    raise ExternalCLIError(f"embark CLI failed (exit {proc.returncode}): {err}")


# ── Public API ──


def search_breeds(query: str | None = None, live: bool = False) -> list[dict[str, Any]]:
    """Search 400+ dog breeds tested by Embark.

    Parameters
    ----------
    query:
        Optional case-insensitive search term (matches breed name or slug).
        If None, returns all breeds.
    live:
        If True, force a fresh scrape from embarkvet.com/dog-breeds-list/.
        If False (default), use offline cached data (data/breeds.json).
        Live mode may trigger Cloudflare WAF blocks on datacenter IPs.

    Returns
    -------
    List of breeds: [{name, slug, url}, ...]
    """
    args = ["search-breeds"]
    if query:
        args += ["--query", query]
    if live:
        args += ["--live"]
    result = _run_embark(args)
    # CLI returns a bare list
    if isinstance(result, list):
        return result
    return result  # type: ignore[return-value]


def get_breed(breed_slug: str) -> dict[str, Any]:
    """Get full breed profile for a specific breed.

    Parameters
    ----------
    breed_slug:
        Breed slug (e.g. "golden-retriever", "labrador-retriever").
        Get slugs from search_breeds().

    Returns
    -------
    Breed detail dict with keys:
    slug, name, description, fun_fact, about, physical_characteristics,
    playtime, grooming, health_aging, size, weight_lbs,
    health_conditions_tested, url

    Notes
    -----
    Requires a live HTTP request to embarkvet.com and may be blocked by
    Cloudflare Bot Management on AWS/datacenter IPs. Set EMBARK_COOKIE or
    EMBARK_COOKIE_FILE to bypass.
    """
    if not breed_slug:
        raise ValueError("breed_slug is required")
    return _run_embark(["get-breed", "--breed-slug", breed_slug])


def search_health(query: str | None = None) -> list[dict[str, Any]]:
    """Search 270+ genetic health conditions tested by Embark.

    Parameters
    ----------
    query:
        Optional case-insensitive search term (matches condition name,
        gene, or slug). If None, returns all conditions.

    Returns
    -------
    List of health conditions: [{name, slug, category, gene}, ...]

    Notes
    -----
    Requires a live HTTP request to embarkvet.com/health-conditions-list/
    and may be blocked by Cloudflare Bot Management on AWS/datacenter IPs.
    Set EMBARK_COOKIE or EMBARK_COOKIE_FILE to bypass.
    """
    args = ["search-health"]
    if query:
        args += ["--query", query]
    result = _run_embark(args)
    if isinstance(result, list):
        return result
    return result  # type: ignore[return-value]


def get_health(condition_slug: str) -> dict[str, Any]:
    """Get full health condition detail.

    Parameters
    ----------
    condition_slug:
        Health condition slug (e.g. "mdr1-drug-sensitivity").
        Get slugs from search_health().

    Returns
    -------
    Health condition detail dict with keys:
    slug, name, description, gene_names, inheritance_type,
    signs_symptoms, diagnosis, treatment, affected_breeds, url

    Notes
    -----
    Requires a live HTTP request to embarkvet.com and may be blocked by
    Cloudflare Bot Management on AWS/datacenter IPs. Set EMBARK_COOKIE or
    EMBARK_COOKIE_FILE to bypass.
    """
    if not condition_slug:
        raise ValueError("condition_slug is required")
    return _run_embark(["get-health", "--condition-slug", condition_slug])


def list_traits(query: str | None = None, live: bool = False) -> list[dict[str, Any]]:
    """List/search genetic traits Embark tests for.

    Parameters
    ----------
    query:
        Optional case-insensitive search term (matches trait name or gene).
        If None, returns all traits.
    live:
        If True, force a fresh scrape from embarkvet.com/physical-traits-list/.
        If False (default), use offline cached data (data/traits.json).
        Live mode may trigger Cloudflare WAF blocks on datacenter IPs.

    Returns
    -------
    List of traits: [{name, gene, category?}, ...]
    """
    args = ["list-traits"]
    if query:
        args += ["--query", query]
    if live:
        args += ["--live"]
    result = _run_embark(args)
    if isinstance(result, list):
        return result
    return result  # type: ignore[return-value]
