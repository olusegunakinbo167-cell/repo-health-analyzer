"""Tests for GitHub Actions workflow files.

Validates that .github/workflows/*.yml files are well-formed and contain
expected triggers, jobs, and steps. Catches CI configuration regressions
at test time instead of at CI run time.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]


REPO_ROOT = Path(__file__).parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"


@pytest.mark.skipif(yaml is None, reason="PyYAML not installed")
def test_repo_health_workflow_exists():
    """repo-health.yml exists."""
    workflow_path = WORKFLOWS_DIR / "repo-health.yml"
    assert workflow_path.is_file(), f"{workflow_path} not found"


@pytest.mark.skipif(yaml is None, reason="PyYAML not installed")
def test_repo_health_workflow_valid_yaml():
    """repo-health.yml is valid YAML."""
    workflow_path = WORKFLOWS_DIR / "repo-health.yml"
    content = workflow_path.read_text(encoding="utf-8")
    data = yaml.safe_load(content)
    assert isinstance(data, dict)
    assert "name" in data
    assert data["name"] == "Repo Health"


@pytest.mark.skipif(yaml is None, reason="PyYAML not installed")
def test_repo_health_workflow_triggers():
    """repo-health.yml triggers on push/PR to main + workflow_dispatch."""
    workflow_path = WORKFLOWS_DIR / "repo-health.yml"
    data = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))

    on = data.get("on") or data.get(True)  # 'on' parses as True in YAML 1.1
    assert on is not None, "workflow missing 'on' triggers"

    # Check push trigger
    assert "push" in on, "missing push trigger"
    push_cfg = on["push"]
    assert "branches" in push_cfg
    assert "main" in push_cfg["branches"]

    # Check pull_request trigger
    assert "pull_request" in on, "missing pull_request trigger"
    pr_cfg = on["pull_request"]
    assert "branches" in pr_cfg
    assert "main" in pr_cfg["branches"]

    # Check workflow_dispatch
    assert "workflow_dispatch" in on, "missing workflow_dispatch trigger"


@pytest.mark.skipif(yaml is None, reason="PyYAML not installed")
def test_repo_health_workflow_has_analyze_job():
    """repo-health.yml has an 'analyze' job."""
    workflow_path = WORKFLOWS_DIR / "repo-health.yml"
    data = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))

    jobs = data.get("jobs", {})
    assert "analyze" in jobs, "missing 'analyze' job"

    analyze_job = jobs["analyze"]
    assert analyze_job.get("runs-on") == "ubuntu-latest"


@pytest.mark.skipif(yaml is None, reason="PyYAML not installed")
def test_repo_health_workflow_analyze_step():
    """analyze job runs repo-health-analyzer with HTML output."""
    workflow_path = WORKFLOWS_DIR / "repo-health.yml"
    data = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))

    steps = data["jobs"]["analyze"]["steps"]
    steps_text = yaml.safe_dump(steps)

    # Must install the analyzer
    assert "pip install" in steps_text
    assert "repo-health-analyzer" in steps_text or "repo_health_analyzer" in steps_text

    # Must generate HTML report
    assert "html" in steps_text.lower(), "workflow should generate HTML report"
    assert "health-report.html" in steps_text, "workflow should output health-report.html"


@pytest.mark.skipif(yaml is None, reason="PyYAML not installed")
def test_repo_health_workflow_uploads_artifact():
    """analyze job uploads HTML report as artifact."""
    workflow_path = WORKFLOWS_DIR / "repo-health.yml"
    data = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))

    steps = data["jobs"]["analyze"]["steps"]
    
    # Find upload-artifact step
    upload_steps = [
        s for s in steps
        if isinstance(s, dict) and "uses" in s and "upload-artifact" in str(s["uses"])
    ]
    assert len(upload_steps) >= 1, "workflow must upload artifacts via upload-artifact action"

    # Check that HTML report is in the upload path
    upload_step = upload_steps[0]
    with_block = str(upload_step.get("with", {}))
    assert "health-report.html" in with_block, "artifact upload must include health-report.html"
    assert "health-summary.json" in with_block or "json" in with_block.lower(), \
        "artifact upload should include JSON summary"


@pytest.mark.skipif(yaml is None, reason="PyYAML not installed")
def test_repo_health_workflow_permissions():
    """repo-health.yml has minimal required permissions."""
    workflow_path = WORKFLOWS_DIR / "repo-health.yml"
    data = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))

    permissions = data.get("permissions", {})
    # Should have contents: read at minimum
    assert permissions.get("contents") == "read", \
        "workflow should have contents: read permission"

    # Should NOT request overly broad permissions
    # (e.g., no write access to contents, issues, pull-requests)
    assert permissions.get("contents") != "write", \
        "workflow should not need contents: write"


@pytest.mark.skipif(yaml is None, reason="PyYAML not installed")
def test_all_workflows_valid_yaml():
    """All .github/workflows/*.yml files are valid YAML."""
    if not WORKFLOWS_DIR.is_dir():
        pytest.skip("no .github/workflows directory")

    workflow_files = list(WORKFLOWS_DIR.glob("*.yml")) + list(WORKFLOWS_DIR.glob("*.yaml"))
    assert len(workflow_files) >= 1, "no workflow files found"

    for wf_path in workflow_files:
        content = wf_path.read_text(encoding="utf-8")
        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError as exc:
            pytest.fail(f"{wf_path.name} is invalid YAML: {exc}")
        
        assert isinstance(data, dict), f"{wf_path.name}: top-level must be a mapping"
        assert "name" in data or "on" in data or True in data, \
            f"{wf_path.name}: missing 'name' or 'on' keys"
