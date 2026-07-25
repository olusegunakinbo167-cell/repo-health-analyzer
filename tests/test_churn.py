"""Tests for code churn metric."""

import tempfile
from pathlib import Path


def test_churn_missing_gitpython_dependency(monkeypatch) -> None:
    """calculate_churn fails open with available=False when GitPython is missing."""
    import src.metrics.code_churn as churn_mod

    # Simulate GitPython not being installed
    monkeypatch.setattr(churn_mod, "Repo", None, raising=False)

    result = churn_mod.calculate_churn("/tmp/doesnt_matter")

    assert result["available"] is False
    assert result["churn_score"] == 0
    assert result["trend"] == "stable"
    assert result["hot_files"] == []
    assert result["total_insertions"] == 0
    assert result["total_deletions"] == 0
    assert result["files_changed"] == 0


def test_churn_non_git_directory() -> None:
    """Non-git directory returns available=True with zeroed metrics (graceful)."""
    from src.metrics.code_churn import calculate_churn

    with tempfile.TemporaryDirectory() as tmpdir:
        result = calculate_churn(tmpdir)

        # Should fail open gracefully — not crash
        assert result["available"] is True
        assert result["churn_score"] == 0
        assert result["hot_files"] == []
        assert result["trend"] == "stable"


def test_churn_basic_git_repo() -> None:
    """Churn analysis works against a real git repo with commits."""
    import os
    import subprocess

    from src.metrics.code_churn import calculate_churn

    with tempfile.TemporaryDirectory() as tmpdir:
        # Init a git repo with a couple of commits
        def git(*args):
            subprocess.run(
                ["git"] + list(args),
                cwd=tmpdir,
                check=True,
                capture_output=True,
            )

        git("init")
        git("config", "user.email", "test@example.com")
        git("config", "user.name", "Test User")

        # First commit
        test_file = Path(tmpdir) / "test.py"
        test_file.write_text("x = 1\n")
        git("add", "test.py")
        git("commit", "-m", "initial")

        # Second commit — modify file
        test_file.write_text("x = 1\ny = 2\nz = 3\n")
        git("add", "test.py")
        git("commit", "-m", "second")

        result = calculate_churn(tmpdir, window_days=90)

        assert result["available"] is True
        # Should have detected churn
        assert result["total_insertions"] > 0
        assert result["files_changed"] >= 1
        assert result["trend"] in ("rising", "stable", "falling")
        # hot_files should include test.py
        hot_names = {f["file"] for f in result["hot_files"]}
        assert "test.py" in hot_names or any("test.py" in f for f in hot_names)
