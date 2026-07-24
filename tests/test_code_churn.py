"""Tests for code_churn metric."""

import tempfile
from pathlib import Path

import pytest

from src.metrics.code_churn import calculate_churn

try:
    from git import Repo
    GIT_AVAILABLE = True
except ImportError:
    GIT_AVAILABLE = False


@pytest.mark.skipif(not GIT_AVAILABLE, reason="GitPython not installed")
def test_calculate_churn_empty_repo() -> None:
    """Non-git directory returns score 0 with stable trend."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = calculate_churn(tmpdir, window_days=90)
        assert result["churn_score"] == 0
        assert result["hot_files"] == []
        assert result["trend"] == "stable"
        assert result["total_insertions"] == 0
        assert result["total_deletions"] == 0


@pytest.mark.skipif(not GIT_AVAILABLE, reason="GitPython not installed")
def test_calculate_churn_basic() -> None:
    """Synthetic git repo with known churn - score in 0-100, hot_files populated."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Repo.init(tmpdir)
        repo.config_writer().set_value("user", "name", "Test").release()
        repo.config_writer().set_value("user", "email", "test@example.com").release()

        # Commit 1: add hot.py with 20 lines
        hot_file = Path(tmpdir) / "hot.py"
        hot_file.write_text("\n".join(f"line {i}" for i in range(20)) + "\n")
        repo.index.add(["hot.py"])
        repo.index.commit("initial")

        # Commit 2: modify hot.py (+5 lines)
        hot_file.write_text(hot_file.read_text() + "\n".join(f"extra {i}" for i in range(5)) + "\n")
        repo.index.add(["hot.py"])
        repo.index.commit("churn hot.py")

        # Commit 3: add cold.py (1 line, low churn)
        cold_file = Path(tmpdir) / "cold.py"
        cold_file.write_text("x = 1\n")
        repo.index.add(["cold.py"])
        repo.index.commit("add cold.py")

        result = calculate_churn(tmpdir, window_days=90)

        assert 0 <= result["churn_score"] <= 100
        assert result["total_insertions"] > 0
        assert result["files_changed"] >= 1
        assert len(result["hot_files"]) >= 1
        # hot.py should be top churn file
        assert result["hot_files"][0]["file"] == "hot.py"
        assert result["hot_files"][0]["churn"] > 0
        assert result["trend"] in ("rising", "stable", "falling")


@pytest.mark.skipif(not GIT_AVAILABLE, reason="GitPython not installed")
def test_calculate_churn_trend_detection() -> None:
    """Trend field returns one of rising/stable/falling."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Repo.init(tmpdir)
        repo.config_writer().set_value("user", "name", "Test").release()
        repo.config_writer().set_value("user", "email", "test@example.com").release()

        f = Path(tmpdir) / "a.py"
        f.write_text("x=1\n")
        repo.index.add(["a.py"])
        repo.index.commit("c1")

        result = calculate_churn(tmpdir, window_days=90)
        # Single commit in second half → rising or stable depending on timing
        assert result["trend"] in ("rising", "stable", "falling")
