"""Tests for CLI argument parsing and entrypoint."""

import json
from pathlib import Path

from src import cli
from src.config import RepoConfig
from src.models import (
    CategoryScore,
    CiCdSetup,
    CommunityFiles,
    HealthScore,
    MaintenanceActivity,
    RepoMetrics,
)


def _make_objects(score: float = 75.0):
    metrics = RepoMetrics(
        full_name="o/r",
        description="Test",
        stars=5,
        language="Python",
        default_branch="main",
        commit_sha="abc123def456",
        community_files=CommunityFiles(
            readme=True, license=True, contributing=True, code_of_conduct=True
        ),
        ci_cd=CiCdSetup(workflow_files=["ci.yml"], workflow_count=1),
        maintenance=MaintenanceActivity(
            commits_last_90_days=10, open_issues=2, closed_issues=8, stale_prs=0
        ),
    )
    cat_score = score / 4
    health = HealthScore(
        total_score=score,
        documentation=CategoryScore("Documentation", cat_score, 25.0, [], []),
        maintenance=CategoryScore("Maintenance", cat_score, 25.0, [], []),
        ci_cd=CategoryScore("CI/CD", cat_score, 25.0, [], []),
        governance=CategoryScore(
            "Governance", score - cat_score * 3, 25.0, [], []
        ),
    )
    return metrics, health


def _fake_result(metrics, health, repo_extra=None, metrics_extra=None, hs_extra=None):
    repo = {
        "full_name": "o/r",
        "description": "Test",
        "stars": 5,
        "language": "Python",
        "default_branch": "main",
        "commit_sha": metrics.commit_sha,
    }
    if repo_extra:
        repo.update(repo_extra)
    return {
        "repository": repo,
        "metrics": metrics_extra or {},
        "health_score": hs_extra or {},
        "config": {"weights": {}, "ignore_rules": []},
        "rate_limit": {"limit": 5000, "remaining": 4999, "reset": 0, "used": 1},
        "_metrics_obj": metrics,
        "_health_obj": health,
        "_config_obj": RepoConfig(),
    }


def test_parse_args_repository() -> None:
    args = cli.parse_args(["octocat/Hello-World"])
    assert args.repository == "octocat/Hello-World"
    assert args.token is None
    assert args.json is False
    assert args.markdown is None


def test_parse_args_with_token() -> None:
    args = cli.parse_args(["octocat/Hello-World", "--token", "abc123"])
    assert args.token == "abc123"


def test_parse_args_json_flag() -> None:
    args = cli.parse_args(["octocat/Hello-World", "--json"])
    assert args.json is True


def test_parse_args_markdown() -> None:
    args = cli.parse_args(["o/r", "--markdown", "report.md"])
    assert args.markdown == Path("report.md")


def test_parse_args_baseline_and_config() -> None:
    args = cli.parse_args(
        ["o/r", "--baseline", "old.json", "--config", ".repo-health.yml"]
    )
    assert args.baseline == Path("old.json")
    assert args.config == Path(".repo-health.yml")


def test_main_invalid_repo_format(monkeypatch, capsys) -> None:
    async def fake_run(repository, token=None, config_path=None, **kwargs):
        raise ValueError("bad format")

    monkeypatch.setattr(cli, "run", fake_run)
    exit_code = cli.main(["not-a-valid-repo"])
    assert exit_code == 2
    assert "Error:" in capsys.readouterr().err


def test_main_json_output(monkeypatch, capsys) -> None:
    # JSONExporter now serializes the live HealthScore object (not result["health_score"] dict)
    # so health.total_score must match the expected JSON output
    metrics, health = _make_objects(score=55.0)
    # Patch the governance score to match the test's hs_extra fixture
    # (test data has governance=30.0 which exceeds max_score — preserving legacy test data)
    health.governance.score = 30.0
    health.total_score = 55.0

    async def fake_run(repository, token=None, config_path=None, **kwargs):
        d = _fake_result(
            metrics,
            health,
            metrics_extra={
                "full_name": "o/r",
                "description": "Test",
                "stars": 5,
                "language": "Python",
                "default_branch": "main",
                "community_files": {
                    "readme": True,
                    "license": True,
                    "contributing": False,
                    "code_of_conduct": False,
                },
                "ci_cd": {"workflow_files": [], "workflow_count": 0},
                "maintenance": {
                    "commits_last_90_days": 3,
                    "open_issues": 1,
                    "closed_issues": 2,
                    "stale_prs": 0,
                },
            },
            hs_extra={
                "total_score": 55.0,
                "documentation": {
                    "name": "Documentation",
                    "score": 15.0,
                    "max_score": 25.0,
                    "penalties": [],
                    "recommendations": [],
                },
                "maintenance": {
                    "name": "Maintenance",
                    "score": 10.0,
                    "max_score": 25.0,
                    "penalties": [],
                    "recommendations": [],
                },
                "ci_cd": {
                    "name": "CI/CD",
                    "score": 0.0,
                    "max_score": 25.0,
                    "penalties": [],
                    "recommendations": [],
                },
                "governance": {
                    "name": "Governance",
                    "score": 30.0,
                    "max_score": 25.0,
                    "penalties": [],
                    "recommendations": [],
                },
            },
        )
        return d

    monkeypatch.setattr(cli, "run", fake_run)
    exit_code = cli.main(["o/r", "--json", "--min-score", "0"])
    assert exit_code == 0
    data = json.loads(capsys.readouterr().out)
    assert "health_score" in data
    assert data["health_score"]["total_score"] == 55.0


def test_main_text_output(monkeypatch, capsys) -> None:
    metrics, health = _make_objects()

    async def fake_run(repository, token=None, config_path=None, **kwargs):
        return _fake_result(metrics, health)

    monkeypatch.setattr(cli, "run", fake_run)
    exit_code = cli.main(["o/r", "--no-color", "--min-score", "0"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Health Report for o/r" in out
    assert "Documentation" in out


def test_main_markdown_output(monkeypatch, capsys, tmp_path) -> None:
    metrics, health = _make_objects()
    out_path = tmp_path / "report.md"

    async def fake_run(repository, token=None, config_path=None, **kwargs):
        return _fake_result(metrics, health)

    monkeypatch.setattr(cli, "run", fake_run)
    exit_code = cli.main(
        ["o/r", "--markdown", str(out_path), "--no-color", "--min-score", "0"]
    )
    assert exit_code == 0
    content = out_path.read_text()
    assert "Health Report" in content
    assert "<details>" in content


def test_quality_gate_failure(monkeypatch, capsys) -> None:
    metrics, health = _make_objects(score=45.0)

    async def fake_run(repository, token=None, config_path=None, **kwargs):
        return _fake_result(metrics, health)

    monkeypatch.setattr(cli, "run", fake_run)
    exit_code = cli.main(["o/r", "--no-color"])
    assert exit_code == 1
    err = capsys.readouterr()
    assert "Quality gate FAILED" in (err.err + err.out)


def test_quality_gate_pass_explicit_threshold(monkeypatch, capsys) -> None:
    metrics, health = _make_objects(score=65.0)

    async def fake_run(repository, token=None, config_path=None, **kwargs):
        return _fake_result(metrics, health)

    monkeypatch.setattr(cli, "run", fake_run)
    exit_code = cli.main(["o/r", "--no-color", "--min-score", "60"])
    assert exit_code == 0


def test_save_artifact(monkeypatch, capsys, tmp_path) -> None:
    metrics, health = _make_objects(score=80.0)
    metrics.commit_sha = "deadbeef1234567890abcdef"

    async def fake_run(repository, token=None, config_path=None, **kwargs):
        return _fake_result(
            metrics,
            health,
            repo_extra={"commit_sha": "deadbeef1234567890abcdef"},
            hs_extra={"total_score": 80.0},
        )

    artifact_path = tmp_path / "run-artifact.json"
    monkeypatch.setattr(cli, "run", fake_run)
    exit_code = cli.main(
        ["o/r", "--no-color", "--min-score", "0", "--save-artifact", str(artifact_path)]
    )
    assert exit_code == 0
    data = json.loads(artifact_path.read_text())
    assert data["repository"]["commit_sha"] == "deadbeef1234567890abcdef"
    assert data["health_score"]["total_score"] == 80.0


def test_baseline_comparison(monkeypatch, capsys, tmp_path) -> None:
    metrics, health = _make_objects(score=85.0)

    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps(
            {
                "timestamp": "2025-01-01T00:00:00Z",
                "repository": {
                    "full_name": "o/r",
                    "commit_sha": "base123",
                    "default_branch": "main",
                },
                "health_score": {
                    "total_score": 70.0,
                    "documentation": {
                        "name": "Documentation",
                        "score": 15.0,
                        "max_score": 25.0,
                        "penalties": [],
                        "recommendations": [],
                    },
                    "maintenance": {
                        "name": "Maintenance",
                        "score": 20.0,
                        "max_score": 25.0,
                        "penalties": [],
                        "recommendations": [],
                    },
                    "ci_cd": {
                        "name": "CI/CD",
                        "score": 15.0,
                        "max_score": 25.0,
                        "penalties": [],
                        "recommendations": [],
                    },
                    "governance": {
                        "name": "Governance",
                        "score": 20.0,
                        "max_score": 25.0,
                        "penalties": [],
                        "recommendations": [],
                    },
                },
                "metrics": {},
            }
        ),
        encoding="utf-8",
    )

    async def fake_run(repository, token=None, config_path=None, **kwargs):
        return _fake_result(metrics, health)

    monkeypatch.setattr(cli, "run", fake_run)
    exit_code = cli.main(
        ["o/r", "--no-color", "--min-score", "0", "--baseline", str(baseline_path)]
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    # Baseline delta should appear (+15)
    assert "15" in out or "baseline" in out.lower()
