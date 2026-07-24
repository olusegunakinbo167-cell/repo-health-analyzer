"""Tests for complexity metric."""

import pytest

from src.metrics.complexity import calculate_complexity


def test_calculate_complexity_not_implemented() -> None:
    """Stub test - complexity implementation pending (issue #3)."""
    with pytest.raises(NotImplementedError):
        calculate_complexity("/tmp/fake-repo")


# TODO: Add once calculate_complexity is implemented:
# - test_calculate_complexity_fixture()
#   - run against tests/fixtures/complexity_sample.py
#   - assert simple_add CC == 1
#   - assert absolute CC == 2
#   - assert categorize_score CC == 4
#   - assert high_risk_function CC > 10 and is flagged
# - test_complexity_rating_thresholds()
#   - A: avg ≤ 5, B: ≤ 10, C: ≤ 20, D: ≤ 25, E: > 25
# - test_complexity_empty_repo()
#   - no Python files → sensible defaults
# - test_complexity_high_risk_detection()
#   - functions with cc > 10 appear in high_risk_functions list
#   - entries include file, function, cc, lineno
