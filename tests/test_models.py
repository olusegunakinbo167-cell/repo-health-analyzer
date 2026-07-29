"""Tests for models.BaselineDiff.compare() — baseline comparison with schema evolution."""
from unittest.mock import patch
from src.models import BaselineDiff, CategoryScore, HealthScore

def test_baseline_compare_same_weights():
    """Baseline comparison with matching category weights."""
    baseline = HealthScore(total_score=70.0, documentation=CategoryScore('Documentation', score=18.0, max_score=20.0), maintenance=CategoryScore('Maintenance', score=16.0, max_score=20.0), ci_cd=CategoryScore('CI/CD', score=18.0, max_score=20.0), governance=CategoryScore('Governance', score=18.0, max_score=20.0), academic_impact=CategoryScore('Academic Impact', 0.0, max_score=10.0))
    current = HealthScore(total_score=68.0, documentation=CategoryScore('Documentation', score=20.0, max_score=20.0), maintenance=CategoryScore('Maintenance', score=15.0, max_score=20.0), ci_cd=CategoryScore('CI/CD', score=17.0, max_score=20.0), governance=CategoryScore('Governance', score=16.0, max_score=20.0), academic_impact=CategoryScore('Academic Impact', 0.0, max_score=10.0))
    diff = BaselineDiff.compare(current, baseline)
    assert len(diff.categories) == 5
    assert diff.baseline_score == 70.0
    assert diff.current_score == 68.0
    assert diff.delta == -2.0
    cd = diff.categories['documentation']
    assert cd.baseline == 18.0
    assert cd.current == 20.0
    assert cd.delta == 2.0
    assert cd.percentage_delta == 10.0
    assert cd.max_score == 20.0
    assert cd.baseline_max_score == 20.0

def test_baseline_compare_missing_category():
    """Missing category in baseline is marked None and excluded from overall delta.

    Simulates schema evolution: current has a new category that baseline lacks.
    We monkey-patch HealthScore.categories() to inject a fake extra category.
    """
    baseline = HealthScore(total_score=72.5, documentation=CategoryScore('Documentation', score=20.0, max_score=25.0), maintenance=CategoryScore('Maintenance', score=18.5, max_score=25.0), ci_cd=CategoryScore('CI/CD', score=15.0, max_score=25.0), governance=CategoryScore('Governance', score=19.0, max_score=25.0), academic_impact=CategoryScore('Academic Impact', 0.0, max_score=10.0))
    current = HealthScore(total_score=68.0, documentation=CategoryScore('Documentation', score=16.0, max_score=20.0), maintenance=CategoryScore('Maintenance', score=14.0, max_score=20.0), ci_cd=CategoryScore('CI/CD', score=12.0, max_score=20.0), governance=CategoryScore('Governance', score=15.0, max_score=20.0), academic_impact=CategoryScore('Academic Impact', 0.0, max_score=10.0))
    orig_categories = HealthScore.categories

    def patched_categories(self):
        cats = orig_categories(self)
        if self is current:
            cats = dict(cats)
            cats['financial'] = CategoryScore('Financial', score=11.0, max_score=20.0)
        return cats
    with patch.object(HealthScore, 'categories', patched_categories):
        diff = BaselineDiff.compare(current, baseline)
        cd_fin = diff.categories['financial']
        assert cd_fin.baseline is None
        assert cd_fin.delta is None
        assert cd_fin.percentage_delta is None
        assert cd_fin.current == 11.0
        assert cd_fin.max_score == 20.0
        assert cd_fin.baseline_max_score is None
        assert diff.baseline_score == 72.5
        assert diff.current_score == 57.0
        assert diff.delta == -15.5
        assert cd_fin.sign == '?'
        assert cd_fin.trend == '?'

def test_baseline_compare_mixed_max_scores():
    """Category weight rebalancing — percentage_delta normalizes across different max_scores."""
    baseline = HealthScore(total_score=75.0, documentation=CategoryScore('Documentation', score=20.0, max_score=25.0), maintenance=CategoryScore('Maintenance', score=15.0, max_score=25.0), ci_cd=CategoryScore('CI/CD', score=15.0, max_score=25.0), governance=CategoryScore('Governance', score=25.0, max_score=25.0), academic_impact=CategoryScore('Academic Impact', 0.0, max_score=10.0))
    current = HealthScore(total_score=60.0, documentation=CategoryScore('Documentation', score=16.0, max_score=20.0), maintenance=CategoryScore('Maintenance', score=14.0, max_score=20.0), ci_cd=CategoryScore('CI/CD', score=12.0, max_score=20.0), governance=CategoryScore('Governance', score=18.0, max_score=20.0), academic_impact=CategoryScore('Academic Impact', 0.0, max_score=10.0))
    diff = BaselineDiff.compare(current, baseline)
    cd = diff.categories['documentation']
    assert cd.baseline == 20.0
    assert cd.current == 16.0
    assert cd.delta == -4.0
    assert cd.percentage_delta == 0.0
    assert cd.max_score == 20.0
    assert cd.baseline_max_score == 25.0
    cd = diff.categories['maintenance']
    assert cd.baseline == 15.0
    assert cd.current == 14.0
    assert cd.delta == -1.0
    assert cd.percentage_delta == 10.0
    cd = diff.categories['ci_cd']
    assert cd.baseline == 15.0
    assert cd.current == 12.0
    assert cd.delta == -3.0
    assert cd.percentage_delta == 0.0
    cd = diff.categories['governance']
    assert cd.baseline == 25.0
    assert cd.current == 18.0
    assert cd.delta == -7.0
    assert cd.percentage_delta == -10.0

def test_baseline_compare_sign_trend_none():
    """sign/trend properties handle None delta gracefully."""
    baseline = HealthScore(total_score=50.0, documentation=CategoryScore('Documentation', score=15.0, max_score=25.0), maintenance=CategoryScore('Maintenance', score=15.0, max_score=25.0), ci_cd=CategoryScore('CI/CD', score=10.0, max_score=25.0), governance=CategoryScore('Governance', score=10.0, max_score=25.0), academic_impact=CategoryScore('Academic Impact', 0.0, max_score=10.0))
    current = HealthScore(total_score=50.0, documentation=CategoryScore('Documentation', score=15.0, max_score=20.0), maintenance=CategoryScore('Maintenance', score=15.0, max_score=20.0), ci_cd=CategoryScore('CI/CD', score=10.0, max_score=20.0), governance=CategoryScore('Governance', score=10.0, max_score=20.0), academic_impact=CategoryScore('Academic Impact', 0.0, max_score=10.0))
    orig_categories = HealthScore.categories

    def patched_categories(self):
        cats = orig_categories(self)
        if self is current:
            cats = dict(cats)
            cats['extra'] = CategoryScore('Extra', score=10.0, max_score=20.0)
        return cats
    with patch.object(HealthScore, 'categories', patched_categories):
        diff = BaselineDiff.compare(current, baseline)
        cd = diff.categories['extra']
        assert cd.delta is None
        assert cd.sign == '?'
        assert cd.trend == '?'
    baseline2 = HealthScore(total_score=40.0, documentation=CategoryScore('Documentation', score=10.0, max_score=20.0), maintenance=CategoryScore('Maintenance', score=10.0, max_score=20.0), ci_cd=CategoryScore('CI/CD', score=10.0, max_score=20.0), governance=CategoryScore('Governance', score=10.0, max_score=20.0), academic_impact=CategoryScore('Academic Impact', 0.0, max_score=10.0))
    current2 = HealthScore(total_score=40.1, documentation=CategoryScore('Documentation', score=10.04, max_score=20.0), maintenance=CategoryScore('Maintenance', score=10.6, max_score=20.0), ci_cd=CategoryScore('CI/CD', score=9.4, max_score=20.0), governance=CategoryScore('Governance', score=10.06, max_score=20.0), academic_impact=CategoryScore('Academic Impact', 0.0, max_score=10.0))
    diff2 = BaselineDiff.compare(current2, baseline2)
    assert diff2.categories['documentation'].sign == '±'
    assert diff2.categories['maintenance'].sign == '+'
    assert diff2.categories['documentation'].trend == '■'
    assert diff2.categories['maintenance'].trend == '▲'
    assert diff2.categories['ci_cd'].trend == '▼'