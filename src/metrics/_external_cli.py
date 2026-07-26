# metrics/_external_cli.py
"""Shared runner for OpenClaw CLI extension subprocess invocations.

Provides a generic ExternalCLI class that handles CLI discovery, JSON parsing,
timeout management, and structured error taxonomy for all external extension
wrappers (Fandango, Embark, etc.).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


class ExternalCLIError(RuntimeError):
    """Base error for external CLI invocations."""


class CLINotFoundError(ExternalCLIError, FileNotFoundError):
    """The CLI executable was not found in any configured location."""


class CLITimeoutError(ExternalCLIError):
    """The CLI subprocess exceeded the configured timeout."""


class CLIWAFBlockError(ExternalCLIError):
    """The CLI was blocked by a Cloudflare / WAF challenge page.

    Raised when the CLI output contains cf_waf_block markers.
    Set an appropriate *_COOKIE / *_COOKIE_FILE env var to bypass,
    or run from a non-datacenter IP.
    """


class CLIInvalidJSONError(ExternalCLIError):
    """The CLI returned output that could not be parsed as JSON."""


class ExternalCLI:
    """Generic runner for OpenClaw CLI extension subprocess calls.

    Example
    -------
    >>> cli = ExternalCLI(
    ...     name="fandango",
    ...     cli_filename="fandango.js",
    ...     env_var="FANDANGO_CLI",
    ...     candidates=[Path.home() / ".openclaw/extensions/fandango/fandango.js"],
    ... )
    >>> result = cli.run_json(["search-movies", "--query", "odyssey"])
    """

    def __init__(
        self,
        name: str,
        cli_filename: str,
        env_var: str,
        candidates: list[Path] | None = None,
        *,
        json_flag: str = "--json",
        node_required: bool = True,
        python_required: bool = False,
    ):
        """Initialize an ExternalCLI runner.

        Parameters
        ----------
        name:
            Human-readable name for the CLI (used in error messages).
        cli_filename:
            Basename of the CLI file (e.g. "fandango.js", "embark.js").
        env_var:
            Environment variable name for CLI path override
            (e.g. "FANDANGO_CLI", "EMBARK_CLI").
        candidates:
            List of Path objects to check for the CLI, in order.
        json_flag:
            Flag to append to force JSON output. Default "--json".
            Set to "" to disable auto-appending.
        node_required:
            If True, invoke via ["node", <cli_path>, ...].
            If False, invoke <cli_path> directly.
        python_required:
            If True, invoke via ["python3", <cli_path>, ...].
            Takes precedence over node_required if both are True.
        """
        self.name = name
        self.cli_filename = cli_filename
        self.env_var = env_var
        self.candidates = candidates or []
        self.json_flag = json_flag
        self.node_required = node_required
        self.python_required = python_required
        self._cached_cli_path: Path | None = None

    def find_cli(self) -> Path:
        """Locate the CLI executable.

        Search order:
        1. Environment variable override (<env_var>)
        2. Candidate paths (in order)
        3. shutil.which() lookup by basename sans extension

        Returns
        -------
        Path to the CLI executable.

        Raises
        ------
        CLINotFoundError
            If the CLI was not found in any location.
        """
        if self._cached_cli_path and self._cached_cli_path.exists():
            return self._cached_cli_path

        # 1. Env override
        env_path = os.getenv(self.env_var)
        if env_path:
            p = Path(env_path)
            if p.exists():
                self._cached_cli_path = p
                return p

        # 2. Known install locations
        for candidate in self.candidates:
            if candidate.exists():
                self._cached_cli_path = candidate
                return candidate

        # 3. PATH lookup
        # Try basename without extension (e.g. "fandango" from "fandango.js")
        stem = Path(self.cli_filename).stem
        which = shutil.which(stem)
        if which:
            p = Path(which)
            self._cached_cli_path = p
            return p

        tried = ", ".join(str(c) for c in self.candidates) or "(no candidates configured)"
        raise CLINotFoundError(
            f"{self.name} CLI ({self.cli_filename}) not found. "
            f"Tried: {tried}. Set {self.env_var}=/path/to/{self.cli_filename} to override."
        )

    def run_json(
        self,
        args: list[str],
        timeout: float = 20.0,
        *,
        detect_waf_block: bool = True,
    ) -> Any:
        """Invoke the CLI with JSON output and parse the result.

        Parameters
        ----------
        args:
            Arguments to pass to the CLI (before --json).
        timeout:
            Subprocess timeout in seconds.
        detect_waf_block:
            If True, scan stdout/stderr for "cf_waf_block" markers
            and raise CLIWAFBlockError instead of a generic RuntimeError.

        Returns
        -------
        Parsed JSON output from the CLI.

        Raises
        ------
        CLINotFoundError
            CLI executable not found.
        CLITimeoutError
            Subprocess exceeded timeout.
        CLIWAFBlockError
            CLI reported a Cloudflare / WAF block.
        CLIInvalidJSONError
            CLI output could not be parsed as JSON.
        ExternalCLIError
            CLI exited with non-zero status (other errors).
        """
        cli_path = self.find_cli()

        cmd: list[str]
        # python_required takes precedence over node_required
        if self.python_required:
            cmd = ["python3", str(cli_path), *args]
        elif self.node_required:
            cmd = ["node", str(cli_path), *args]
        else:
            cmd = [str(cli_path), *args]

        if self.json_flag:
            cmd.append(self.json_flag)

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise CLITimeoutError(
                f"{self.name} CLI timed out after {timeout}s: {exc}"
            ) from exc

        stdout = proc.stdout or ""
        stderr = proc.stderr or ""

        # WAF / Cloudflare block detection — check before returncode
        # so callers can distinguish CF blocks from other failures
        if detect_waf_block and "cf_waf_block" in (stdout + stderr).lower():
            combined = (stderr.strip() or stdout.strip() or "WAF block detected")
            raise CLIWAFBlockError(
                f"{self.name} CLI blocked by Cloudflare / WAF: {combined}"
            )

        if proc.returncode != 0:
            err = stderr.strip() or stdout.strip() or "unknown error"
            raise ExternalCLIError(
                f"{self.name} CLI failed (exit {proc.returncode}): {err}"
            )

        try:
            return json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise CLIInvalidJSONError(
                f"{self.name} CLI returned invalid JSON: {exc}\n{stdout[:500]}"
            ) from exc
