"""Tests for the Financial Impact scorer."""

import pytest

from src.metrics.financial import (
    FinancialMetrics,
    TickerQuote,
    YahooFinanceError,
    collect_financial_metrics,
    fetch_quote,
    get_quotes,
    resolve_backer_tickers,
    score_financial,
)


def test_resolve_backer_tickers_default() -> None:
    tickers = resolve_backer_tickers("unknown/repo")
    assert "MSFT" in tickers
    assert "GOOGL" in tickers
    assert "AAPL" in tickers


def test_resolve_backer_tickers_nvidia() -> None:
    # metrics.yaml doesn't map nvidia by default in the test checkout,
    # but resolve_backer_tickers falls back to default
    tickers = resolve_backer_tickers("nvidia/cuda-samples")
    assert isinstance(tickers, list)
    assert len(tickers) >= 1


def test_fetch_quote_cached_msft() -> None:
    q = fetch_quote("MSFT", live=False)
    assert q.symbol == "MSFT"
    assert q.source == "cache"
    assert q.price > 0
    assert q.change_pct_90d != 0  # cached data has real change_pct


def test_fetch_quote_cached_googl() -> None:
    q = fetch_quote("GOOGL", live=False)
    assert q.symbol == "GOOGL"
    assert q.market_cap_billions > 100


def test_fetch_quote_cached_aapl() -> None:
    q = fetch_quote("AAPL", live=False)
    assert q.symbol == "AAPL"


def test_fetch_quote_unknown_raises() -> None:
    with pytest.raises(YahooFinanceError):
        fetch_quote("FAKETICKERZZZ", live=False)


def test_fetch_quote_live_fallback_to_cache() -> None:
    # live=True should fall back to cache when Yahoo is blocked (451)
    # This test passes in both online and offline environments
    q = fetch_quote("MSFT", live=True)
    assert q.symbol == "MSFT"
    # source may be "cache" (offline) or "live" (if network works)
    assert q.source in ("cache", "live")


def test_get_quotes_multiple() -> None:
    quotes = get_quotes(["MSFT", "GOOGL", "AAPL"], live=False)
    assert len(quotes) == 3
    symbols = {q.symbol for q in quotes}
    assert symbols == {"MSFT", "GOOGL", "AAPL"}


def test_get_quotes_skips_invalid() -> None:
    quotes = get_quotes(["MSFT", "NOTAREALTICKER", "AAPL"], live=False)
    # invalid ticker is skipped, 2 valid quotes returned
    assert len(quotes) == 2


def test_collect_financial_metrics_default() -> None:
    fm = collect_financial_metrics("someuser/somerepo", live=False)
    assert fm is not None
    assert fm.backer_count >= 1
    assert len(fm.quotes) == fm.backer_count
    assert isinstance(fm.composite_change_pct_90d, float)
    assert isinstance(fm.composite_volatility, float)


def test_score_financial_strong_backer() -> None:
    # NVDA in cache: +18.9% 90d, 42.6% vol, $3115B mcap
    # Price: 12 pts, Vol: 1 pt, Mcap: 3 pts = 16/20 raw
    fm = collect_financial_metrics("nvidia/test", live=False)
    # Force NVDA-only if default backers resolved
    if fm and "NVDA" not in fm.tickers:
        from src.metrics.financial import get_quotes as gq
        quotes = gq(["NVDA"], live=False)
        fm = FinancialMetrics(
            tickers=["NVDA"],
            quotes=quotes,
            composite_change_pct_90d=quotes[0].change_pct_90d,
            composite_volatility=quotes[0].volatility_annualized,
            backer_count=1,
        )
    assert fm is not None
    score = score_financial("nvidia/test", fm)
    assert score.name == "Financial"
    assert score.max_score == 20.0
    # NVDA strong gain → high score
    assert score.score >= 15.0


def test_score_financial_default_backers() -> None:
    # Default: MSFT (+8.4%), GOOGL (+4.2%), AAPL (+2.1%)
    # Composite ~ +4.9% → price_score 5, vol ~24.5 → vol_score 3, mcap bonus 3
    # Total raw ~11/20 → scaled score ~11
    score = score_financial("unknown/repo", live=False)
    assert score.name == "Financial"
    assert 8.0 <= score.score <= 16.0


def test_score_financial_decline_penalty() -> None:
    # Construct a declining backer scenario
    declining_quote = TickerQuote(
        symbol="FAKE",
        short_name="Fake Corp",
        price=100.0,
        change_pct_90d=-20.0,
        volatility_annualized=25.0,
        market_cap_billions=150.0,
        currency="USD",
        source="cache",
    )
    fm = FinancialMetrics(
        tickers=["FAKE"],
        quotes=[declining_quote],
        composite_change_pct_90d=-20.0,
        composite_volatility=25.0,
        backer_count=1,
    )
    score = score_financial("fake/repo", fm)
    assert score.score < 10.0  # low score for steep decline
    assert any("down" in p.lower() for p in score.penalties)
    assert any("decline" in p.lower() for p in score.penalties)


def test_score_financial_no_data_neutral() -> None:
    # Repo with no backer mapping and no cache hit — but our
    # resolve_backer_tickers always returns default, so force fm=None
    # by passing an empty financial_metrics and mocking collect to fail.
    # Simpler: pass financial_metrics=None for a repo that resolves to
    # tickers not in cache, and patch get_quotes.
    from unittest.mock import patch
    with patch("src.metrics.financial.get_quotes", return_value=[]):
        with patch("src.metrics.financial.resolve_backer_tickers", return_value=["ZZZZ"]):
            score = score_financial("zzzz/repo", financial_metrics=None, live=False)
            # Falls back to neutral 10/20
            assert abs(score.score - 10.0) < 0.01
            assert any("no" in p.lower() and "financial" in p.lower() for p in score.penalties)


def test_score_financial_ignores() -> None:
    # Test ignore_rules suppress penalties
    declining_quote = TickerQuote(
        symbol="FAKE",
        short_name="Fake",
        price=100,
        change_pct_90d=-30.0,
        volatility_annualized=60.0,
        market_cap_billions=10.0,
        currency="USD",
    )
    fm = FinancialMetrics(
        tickers=["FAKE"],
        quotes=[declining_quote],
        composite_change_pct_90d=-30.0,
        composite_volatility=60.0,
        backer_count=1,
    )

    class FakeConfig:
        def weight_for(self, cat: str) -> float:
            return 20.0
        def is_ignored(self, rule: str) -> bool:
            return rule in {"backer_stock_decline", "high_backer_volatility"}

    score = score_financial("fake/repo", fm, config=FakeConfig())
    # Penalties should be suppressed
    assert not any("down" in p.lower() for p in score.penalties)
    assert not any("volatility" in p.lower() for p in score.penalties)
