"""Tests for Embark Dog DNA wrapper."""

import json
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from src.metrics import embark
from src.metrics._external_cli import (
    CLIInvalidJSONError,
    CLITimeoutError,
    CLIWAFBlockError,
    ExternalCLIError,
)


# ── CLI discovery ──

def test_find_embark_cli_env_override(tmp_path, monkeypatch):
    fake_cli = tmp_path / "embark.js"
    fake_cli.write_text("#!/usr/bin/env node\n")
    monkeypatch.setenv("EMBARK_CLI", str(fake_cli))
    # Clear cached path
    embark._EMBARK_CLI._cached_cli_path = None
    try:
        result = embark.find_embark_cli()
        assert result == fake_cli
    finally:
        embark._EMBARK_CLI._cached_cli_path = None


def test_find_embark_cli_not_found(monkeypatch):
    monkeypatch.delenv("EMBARK_CLI", raising=False)
    from src.metrics import embark as embark_mod

    with patch.object(embark_mod._EMBARK_CLI, "candidates", []):
        embark_mod._EMBARK_CLI._cached_cli_path = None
        with patch("shutil.which", return_value=None):
            with pytest.raises(FileNotFoundError, match="embark.*CLI.*not found"):
                embark.find_embark_cli()


# ── search_breeds ──

def test_search_breeds_success(monkeypatch):
    fake_output = [
        {"name": "Golden Retriever", "slug": "golden-retriever", "url": "https://embarkvet.com/resources/dog-breeds/golden-retriever/"},
        {"name": "Labrador Retriever", "slug": "labrador-retriever", "url": "https://embarkvet.com/resources/dog-breeds/labrador-retriever/"},
    ]
    mock_proc = Mock()
    mock_proc.returncode = 0
    mock_proc.stdout = json.dumps(fake_output)
    mock_proc.stderr = ""

    with patch("subprocess.run", return_value=mock_proc) as mock_run:
        with patch.object(embark, "find_embark_cli", return_value=Path("/fake/embark.js")):
            result = embark.search_breeds("retriever", live=False)

    assert len(result) == 2
    assert result[0]["slug"] == "golden-retriever"
    # Verify subprocess was called correctly
    args = mock_run.call_args[0][0]
    assert args[0] == "node"
    assert "search-breeds" in args
    assert "--query" in args
    assert "retriever" in args
    # embark.js outputs JSON by default, no --json flag
    assert "--json" not in args


def test_search_breeds_live_flag(monkeypatch):
    mock_proc = Mock(returncode=0, stdout="[]", stderr="")
    with patch("subprocess.run", return_value=mock_proc) as mock_run:
        with patch.object(embark, "find_embark_cli", return_value=Path("/fake/embark.js")):
            embark.search_breeds("poodle", live=True)
    args = mock_run.call_args[0][0]
    assert "--live" in args


def test_search_breeds_no_query(monkeypatch):
    """search_breeds with no query should return all breeds."""
    mock_proc = Mock(returncode=0, stdout="[]", stderr="")
    with patch("subprocess.run", return_value=mock_proc) as mock_run:
        with patch.object(embark, "find_embark_cli", return_value=Path("/fake/embark.js")):
            embark.search_breeds()
    args = mock_run.call_args[0][0]
    # --query should NOT be in args when query is None
    assert "--query" not in args


# ── get_breed ──

def test_get_breed_success(monkeypatch):
    fake_output = {
        "slug": "golden-retriever",
        "name": "Golden Retriever",
        "description": "Friendly family dog",
        "fun_fact": "Holds 6 tennis balls",
        "url": "https://embarkvet.com/resources/dog-breeds/golden-retriever/",
    }
    mock_proc = Mock(returncode=0, stdout=json.dumps(fake_output), stderr="")
    with patch("subprocess.run", return_value=mock_proc) as mock_run:
        with patch.object(embark, "find_embark_cli", return_value=Path("/fake/embark.js")):
            result = embark.get_breed("golden-retriever")

    assert result["slug"] == "golden-retriever"
    assert result["name"] == "Golden Retriever"
    args = mock_run.call_args[0][0]
    assert "get-breed" in args
    assert "--breed-slug" in args
    assert "golden-retriever" in args


def test_get_breed_missing_slug():
    with pytest.raises(ValueError, match="breed_slug is required"):
        embark.get_breed("")


# ── search_health ──

def test_search_health_success(monkeypatch):
    fake_output = [
        {"name": "MDR1 Drug Sensitivity", "slug": "mdr1-drug-sensitivity", "category": "Clinical", "gene": "ABCB1"},
    ]
    mock_proc = Mock(returncode=0, stdout=json.dumps(fake_output), stderr="")
    with patch("subprocess.run", return_value=mock_proc):
        with patch.object(embark, "find_embark_cli", return_value=Path("/fake/embark.js")):
            result = embark.search_health("mdr1")

    assert len(result) == 1
    assert result[0]["slug"] == "mdr1-drug-sensitivity"
    assert result[0]["gene"] == "ABCB1"


# ── get_health ──

def test_get_health_success(monkeypatch):
    fake_output = {
        "slug": "mdr1-drug-sensitivity",
        "name": "MDR1 Drug Sensitivity",
        "gene_names": "ABCB1",
        "inheritance_type": "Autosomal recessive",
        "affected_breeds": [{"name": "Collie", "slug": "collie"}],
        "url": "https://embarkvet.com/products/dog-health/health-conditions/mdr1-drug-sensitivity/",
    }
    mock_proc = Mock(returncode=0, stdout=json.dumps(fake_output), stderr="")
    with patch("subprocess.run", return_value=mock_proc):
        with patch.object(embark, "find_embark_cli", return_value=Path("/fake/embark.js")):
            result = embark.get_health("mdr1-drug-sensitivity")

    assert result["slug"] == "mdr1-drug-sensitivity"
    assert result["gene_names"] == "ABCB1"


def test_get_health_missing_slug():
    with pytest.raises(ValueError, match="condition_slug is required"):
        embark.get_health("")


# ── list_traits ──

def test_list_traits_success(monkeypatch):
    fake_output = [
        {"name": "Coat Length", "gene": "FGF5", "category": "Other Coat Traits"},
        {"name": "Coat Texture", "gene": "KRT71", "category": "Other Coat Traits"},
    ]
    mock_proc = Mock(returncode=0, stdout=json.dumps(fake_output), stderr="")
    with patch("subprocess.run", return_value=mock_proc) as mock_run:
        with patch.object(embark, "find_embark_cli", return_value=Path("/fake/embark.js")):
            result = embark.list_traits("coat", live=False)

    assert len(result) == 2
    assert result[0]["gene"] == "FGF5"
    args = mock_run.call_args[0][0]
    assert "list-traits" in args
    assert "--query" in args
    assert "coat" in args


def test_list_traits_live_flag(monkeypatch):
    mock_proc = Mock(returncode=0, stdout="[]", stderr="")
    with patch("subprocess.run", return_value=mock_proc) as mock_run:
        with patch.object(embark, "find_embark_cli", return_value=Path("/fake/embark.js")):
            embark.list_traits(live=True)
    args = mock_run.call_args[0][0]
    assert "--live" in args


# ── error handling ──

def test_embark_waf_block_detection(monkeypatch):
    """CLI reports cf_waf_block in stderr JSON."""
    mock_proc = Mock()
    mock_proc.returncode = 1
    mock_proc.stdout = ""
    mock_proc.stderr = json.dumps({
        "error": "cf_waf_block",
        "message": "Embark is behind Cloudflare Bot Management"
    })

    with patch("subprocess.run", return_value=mock_proc):
        with patch.object(embark, "find_embark_cli", return_value=Path("/fake/embark.js")):
            with pytest.raises(CLIWAFBlockError, match="Cloudflare.*WAF"):
                embark.search_breeds("test")


def test_embark_cli_failure(monkeypatch):
    """CLI returns non-zero with structured error JSON."""
    mock_proc = Mock()
    mock_proc.returncode = 1
    mock_proc.stdout = ""
    mock_proc.stderr = json.dumps({"error": "breed not found"})

    with patch("subprocess.run", return_value=mock_proc):
        with patch.object(embark, "find_embark_cli", return_value=Path("/fake/embark.js")):
            with pytest.raises(ExternalCLIError, match="breed not found"):
                embark.get_breed("nonexistent")


def test_embark_cli_failure_plain_text(monkeypatch):
    """CLI returns non-zero with plain text error."""
    mock_proc = Mock(returncode=1, stdout="", stderr="something went wrong")
    with patch("subprocess.run", return_value=mock_proc):
        with patch.object(embark, "find_embark_cli", return_value=Path("/fake/embark.js")):
            with pytest.raises(ExternalCLIError, match="something went wrong"):
                embark.search_breeds("test")


def test_embark_invalid_json(monkeypatch):
    """CLI returns invalid JSON."""
    mock_proc = Mock(returncode=0, stdout="not json {{{", stderr="")
    with patch("subprocess.run", return_value=mock_proc):
        with patch.object(embark, "find_embark_cli", return_value=Path("/fake/embark.js")):
            with pytest.raises(CLIInvalidJSONError, match="returned invalid JSON"):
                embark.search_breeds("test")


def test_embark_timeout(monkeypatch):
    """CLI times out."""
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="node", timeout=20.0)):
        with patch.object(embark, "find_embark_cli", return_value=Path("/fake/embark.js")):
            with pytest.raises(CLITimeoutError, match="timed out"):
                embark.search_breeds("test")
