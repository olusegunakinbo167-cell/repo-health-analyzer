"""Tests for CLI argument parsing and entrypoint."""

import json
from pathlib import Path

from src import cli
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
    # Distribute score roughly evenly across categories
    cat_score = score / 4
    health = HealthScore(
        total_score=score,
        documentation=CategoryScore(
            name="Documentation",
            score=cat_score,
            penalties=[],
            recommendations=[],
        ),
        maintenance=CategoryScore(
            name="Maintenance",
            score=cat_score,
            penalties=[],
            recommendations=[],
        ),
        ci_cd=CategoryScore(
            name="CI/CD",
            score=cat_score,
            penalties=[],
            recommendations=[],
        ),
        governance=CategoryScore(
            name="Governance",
            score=score - cat_score * 3,
            penalties=[],
            recommendations=[],
        ),
    )
    return metrics, health


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


def test_main_invalid_repo_format(monkeypatch, capsys) -> None:
    """Main should exit 2 on ValueError (bad repo format)."""

    async def fake_run(repository: str, token: str | None) -> dict:
        raise ValueError("bad format")

    monkeypatch.setattr(cli, "run", fake_run)
    exit_code = cli.main(["not-a-valid-repo"])
    assert exit_code == 2
    captured = capsys.readouterr()
    assert "Error:" in captured.err


def test_main_json_output(monkeypatch, capsys) -> None:
    """CLI --json emits full metrics + health_score payload."""
    metrics, health = _make_objects()

    async def fake_run(repository: str, token: str | None) -> dict:
        return {
            "repository": {
                "full_name": "o/r",
                "description": "Test",
                "stars": 5,
                "language": "Python",
                "default_branch": "main",
            },
            "metrics": {
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
            "health_score": {
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
            "rate_limit": {"limit": 5000, "remaining": 4999, "reset": 0, "used": 1},
            "_metrics_obj": metrics,
            "_health_obj": health,
        }

    monkeypatch.setattr(cli, "run", fake_run)
    exit_code = cli.main(["o/r", "--json", "--min-score", "0"])
    assert exit_code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "health_score" in data
    assert "metrics" in data
    assert data["health_score"]["total_score"] == 55.0
    # Live objects should be stripped from JSON output
    assert "_metrics_obj" not in data
    assert "_health_obj" not in data


def test_main_text_output(monkeypatch, capsys) -> None:
    """CLI text mode prints Rich health report with scores and recommendations."""
    metrics, health = _make_objects()

    async def fake_run(repository: str, token: str | None) -> dict:
        return {
            "repository": {
                "full_name": "o/r",
                "description": "Test",
                "stars": 5,
                "language": "Python",
                "default_branch": "main",
            },
            "metrics": {
                "full_name": "o/r",
                "description": "Test",
                "stars": 5,
                "language": "Python",
                "default_branch": "main",
                "community_files": {
                    "readme": True,
                    "license": False,
                    "contributing": False,
                    "code_of_conduct": False,
                },
                "ci_cd": {"workflow_files": ["ci.yml"], "workflow_count": 1},
                "maintenance": {
                    "commits_last_90_days": 0,
                    "open_issues": 0,
                    "closed_issues": 0,
                    "stale_prs": 0,
                },
            },
            "health_score": {
                "total_score": 42.5,
                "documentation": {
                    "name": "Documentation",
                    "score": 10.0,
                    "max_score": 25.0,
                    "penalties": ["Missing LICENSE file"],
                    "recommendations": ["Add a LICENSE file"],
                },
                "maintenance": {
                    "name": "Maintenance",
                    "score": 5.0,
                    "max_score": 25.0,
                    "penalties": ["No commits in the last 90 days"],
                    "recommendations": ["Resume active development"],
                },
                "ci_cd": {
                    "name": "CI/CD",
                    "score": 15.0,
                    "max_score": 25.0,
                    "penalties": [],
                    "recommendations": ["Add more CI/CD coverage"],
                },
                "governance": {
                    "name": "Governance",
                    "score": 15.0,
                    "max_score": 25.0,
                    "penalties": [],
                    "recommendations": [],
                },
            },
            "rate_limit": {"limit": 5000, "remaining": 4999, "reset": 0, "used": 1},
            "_metrics_obj": metrics,
            "_health_obj": health,
        }

    monkeypatch.setattr(cli, "run", fake_run)
    exit_code = cli.main(["o/r", "--no-color", "--min-score", "0"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Health Report for o/r" in out
    assert "Documentation" in out
    # Score comes from live HealthScore object (75.0 by default)


def test_main_markdown_output(monkeypatch, capsys, tmp_path) -> None:
    """CLI --markdown writes a Markdown report to disk."""
    metrics, health = _make_objects()
    out_path = tmp_path / "report.md"

    async def fake_run(repository: str, token: str | None) -> dict:
        return {
            "repository": {
                "full_name": "o/r",
                "description": "Test",
                "stars": 5,
                "language": "Python",
                "default_branch": "main",
            },
            "metrics": {},
            "health_score": {},
            "rate_limit": {"limit": 5000, "remaining": 4999, "reset": 0, "used": 1},
            "_metrics_obj": metrics,
            "_health_obj": health,
        }

    monkeypatch.setattr(cli, "run", fake_run)
    exit_code = cli.main(
        ["o/r", "--markdown", str(out_path), "--no-color", "--min-score", "0"]
    )
    assert exit_code == 0
    assert out_path.exists()
    content = out_path.read_text()
    assert "Health Report" in content
    assert "o/r" in content
    assert "<details>" in content  # Collapsible sections
    # Markdown mode still prints terminal output by default
    out = capsys.readouterr()
    assert "Health Report for o/r" in out.out


def test_quality_gate_failure(monkeypatch, capsys) -> None:
    """Exit code 1 when health_score < --min-score."""
    metrics, health = _make_objects(score=45.0)

    async def fake_run(repository: str, token: str | None) -> dict:
        return {
            "repository": {
                "full_name": "o/r",
                "description": "Test",
                "stars": 0,
                "language": None,
                "default_branch": "main",
            },
            "metrics": {},
            "health_score": {},
            "rate_limit": {"limit": 5000, "remaining": 4999, "reset": 0, "used": 1},
            "_metrics_obj": metrics,
            "_health_obj": health,
        }

    monkeypatch.setattr(cli, "run", fake_run)
    # Default min_score is 70, health is 45 → should fail
    exit_code = cli.main(["o/r", "--no-color"])
    assert exit_code == 1
    err = capsys.readouterr()
    # Gate failure message goes to stderr
    assert "Quality gate FAILED" in err.err or "Quality gate FAILED" in err.out
    assert "45" in err.err or "45" in err.out


def test_quality_gate_pass_explicit_threshold(monkeypatch, capsys) -> None:
    """Gate passes when score >= threshold."""
    metrics, health = _make_objects(score=65.0)

    async def fake_run(repository: str, token: str | None) -> dict:
        return {
            "repository": {
                "full_name": "o/r",
                "description": "Test",
                "stars": 0,
                "language": None,
                "default_branch": "main",
            },
            "metrics": {},
            "health_score": {},
            "rate_limit": {"limit": 5000, "remaining": 4999, "reset": 0, "used": 1},
            "_metrics_obj": metrics,
            "_health_obj": health,
        }

    monkeypatch.setattr(cli, "run", fake_run)
    exit_code = cli.main(["o/r", "--no-color", "--min-score", "60"])
    assert exit_code == 0


def test_save_artifact(monkeypatch, capsys, tmp_path) -> None:
    """--save-artifact writes run metadata JSON with timestamp and commit SHA."""
    metrics, health = _make_objects(score=80.0)
    # Set a specific commit SHA
    metrics.commit_sha = "deadbeef1234567890abcdef"

    async def fake_run(repository: str, token: str | None) -> dict:
        return {
            "repository": {
                "full_name": "o/r",
                "description": "Test",
                "stars": 5,
                "language": "Python",
                "default_branch": "main",
                "commit_sha": "deadbeef1234567890abcdef",
            },
            "metrics": {
                "full_name": "o/r",
                "commit_sha": "deadbeef1234567890abcdef",
            },
            "health_score": {"total_score": 80.0},
            "rate_limit": {"limit": 5000, "remaining": 4999, "reset": 0, "used": 1},
            "_metrics_obj": metrics,
            "_health_obj": health,
        }

    artifact_path = tmp_path / "run-artifact.json"
    monkeypatch.setattr(cli, "run", fake_run)
    exit_code = cli.main(
        ["o/r", "--no-color", "--min-score", "0", "--save-artifact", str(artifact_path)]
    )
    assert exit_code == 0
    assert artifact_path.exists()

    data = json.loads(artifact_path.read_text())
    assert "timestamp" in data
    assert data["repository"]["full_name"] == "o/r"
    assert data["repository"]["commit_sha"] == "deadbeef1234567890abcdef"
    assert "metrics" in data
    assert "health_score" in data
    assert data["health_score"]["total_score"] == 80.0
    assert "tool_version" in data

