"""Tests for code_churn metric."""

import pytest

from src.metrics.code_churn import calculate_churn


def test_calculate_churn_not_implemented() -> None:
    """Stub test - churn implementation pending (issue #3)."""
    with pytest.raises(NotImplementedError):
        calculate_churn("/tmp/fake-repo", window_days=90)


# TODO: Add once calculate_churn is implemented:
# - test_calculate_churn_basic()
#   - synthetic git repo with known churn
#   - assert churn_score in 0-100 range
#   - assert hot_files list populated correctly
# - test_calculate_churn_trend()
#   - rising / stable / falling detection
# - test_calculate_churn_empty_repo()
#   - empty repo returns score 0
# - test_churn_git_log_parsing()
#   - correctly parses git log --numstat output
