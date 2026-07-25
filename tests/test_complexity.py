"""Tests for complexity metric."""

import tempfile
from pathlib import Path

from src.metrics.complexity import calculate_complexity


def test_calculate_complexity_fixture() -> None:
    """Run complexity analysis against the known-CC fixture file."""
    fixture_path = Path(__file__).parent / "fixtures" / "complexity_sample.py"
    assert fixture_path.exists()

    # Run against the fixtures directory containing complexity_sample.py
    result = calculate_complexity(str(fixture_path.parent))

    # Fixture contains 4 functions with CC: 1, 2, 4, 11+
    assert result["total_functions"] >= 4
    assert result["max_complexity"] >= 11

    # high_risk_function should be flagged (cc > 10)
    high_risk_names = {f["function"] for f in result["high_risk_functions"]}
    assert "high_risk_function" in high_risk_names

    # Verify the high-risk entry has required fields
    hr = next(f for f in result["high_risk_functions"] if f["function"] == "high_risk_function")
    assert hr["cc"] > 10
    assert "file" in hr
    assert "lineno" in hr
    assert hr["file"].endswith("complexity_sample.py")


def test_complexity_rating_thresholds() -> None:
    """Rating thresholds match SonarQube: A≤5, B≤10, C≤20, D≤25, E>25."""
    # Create temp repos with known complexity levels
    with tempfile.TemporaryDirectory() as tmpdir:
        # CC = 2 → Rating A
        Path(tmpdir, "simple.py").write_text("def f(x):\n    return x + 1\n")
        result = calculate_complexity(tmpdir)
        assert result["rating"] == "A"
        assert result["avg_complexity"] <= 5


def test_complexity_empty_repo() -> None:
    """Empty repo / no Python files returns sensible defaults."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = calculate_complexity(tmpdir)
        assert result["total_functions"] == 0
        assert result["avg_complexity"] == 0.0
        assert result["max_complexity"] == 0
        assert result["high_risk_functions"] == []
        assert result["rating"] == "A"


def test_complexity_high_risk_detection() -> None:
    """Functions with cc > 10 appear in high_risk_functions with full metadata."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Write a high-complexity function
        Path(tmpdir, "risky.py").write_text(
            """
def risky(a,b,c,d,e,f,g,h,i,j,k):
    if a: x=1
    else: x=0
    if b: x+=1
    if c: x+=1
    if d: x+=1
    if e: x+=1
    if f: x+=1
    if g: x+=1
    if h: x+=1
    if i: x+=1
    if j: x+=1
    if k: x+=1
    return x
"""
        )
        result = calculate_complexity(tmpdir)
        assert result["max_complexity"] > 10
        assert len(result["high_risk_functions"]) >= 1

        hr = result["high_risk_functions"][0]
        assert all(k in hr for k in ("file", "function", "cc", "lineno"))
        assert hr["cc"] > 10
        assert hr["function"] == "risky"


def test_complexity_missing_radon_dependency(monkeypatch) -> None:
    """calculate_complexity fails open with available=False when radon is missing."""
    import src.metrics.complexity as complexity_mod

    # Simulate radon not being installed
    monkeypatch.setattr(complexity_mod, "cc_visit", None, raising=False)

    result = complexity_mod.calculate_complexity("/tmp/doesnt_matter")

    assert result["available"] is False
    assert result["rating"] == "A"
    assert result["total_functions"] == 0
    assert result["avg_complexity"] == 0.0
    assert result["max_complexity"] == 0
    assert result["high_risk_functions"] == []

