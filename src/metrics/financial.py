"""Financial Impact Scorer — corporate backer stock performance vs repo vitality.

Offline-first: cached ticker data is used by default. Live Yahoo Finance
lookups are opt-in (live=True) and gracefully fall back to cache on any
network error, including 451 / WAF blocks.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


# ----------------------------------------------------------------------
# Data models
# ----------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class TickerQuote:
    """Normalized stock quote for financial scoring."""

    symbol: str
    short_name: str
    price: float
    change_pct_90d: float
    volatility_annualized: float
    market_cap_billions: float
    currency: str = "USD"
    source: str = "cache"  # "cache" | "live"


@dataclass(slots=True)
class FinancialMetrics:
    """Financial impact metrics attached to a RepoMetrics object."""

    tickers: list[str]
    quotes: list[TickerQuote]
    composite_change_pct_90d: float
    composite_volatility: float
    backer_count: int


# ----------------------------------------------------------------------
# Cache loading
# ----------------------------------------------------------------------


def _load_metrics_yaml() -> dict[str, Any]:
    """Load metrics.yaml from repo root or package directory."""
    candidates = [
        Path.cwd() / "metrics.yaml",
        Path(__file__).parents[3] / "metrics.yaml",
        Path(__file__).parent.parent / "metrics.yaml",
    ]
    for p in candidates:
        if p.exists() and yaml is not None:
            try:
                data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
                return data
            except Exception:
                continue
    return {}


def _get_cached_quote(symbol: str) -> TickerQuote | None:
    """Look up a ticker in the metrics.yaml cache."""
    cfg = _load_metrics_yaml()
    cache = cfg.get("financial", {}).get("cache", {})
    entry = cache.get(symbol.upper())
    if not entry:
        return None
    try:
        return TickerQuote(
            symbol=entry.get("symbol", symbol.upper()),
            short_name=entry.get("short_name", symbol.upper()),
            price=float(entry.get("price", 0.0)),
            change_pct_90d=float(entry.get("change_pct_90d", 0.0)),
            volatility_annualized=float(entry.get("volatility_annualized", 30.0)),
            market_cap_billions=float(entry.get("market_cap_billions", 0.0)),
            currency=entry.get("currency", "USD"),
            source="cache",
        )
    except Exception:
        return None


# ----------------------------------------------------------------------
# Live Yahoo Finance lookup (opt-in, best-effort)
# ----------------------------------------------------------------------


class YahooFinanceError(RuntimeError):
    """Yahoo Finance lookup failed (network, 451, parse error)."""


def _find_yahoo_cli() -> str | None:
    """Locate the bundled OpenClaw yahoo_finance CLI, if available."""
    candidates = [
        Path.home() / ".openclaw/extensions/yahoo-finance/skills/yahoo-finance/yahoo_finance",
        Path("/usr/lib/node_modules/openclaw/dist/extensions/yahoo-finance/skills/yahoo-finance/yahoo_finance"),
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return None


def fetch_quote_live(symbol: str, timeout: float = 5.0) -> TickerQuote:
    """Fetch a live quote via the OpenClaw Yahoo Finance CLI.

    Raises:
        YahooFinanceError: on any network, subprocess, or parse failure.
    """
    cli = _find_yahoo_cli()
    if not cli:
        raise YahooFinanceError("yahoo_finance CLI not found")

    try:
        proc = subprocess.run(
            [sys.executable, cli, "quote", "--symbol", symbol.upper()],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise YahooFinanceError(f"Yahoo Finance timeout for {symbol}: {e}") from e
    except Exception as e:
        raise YahooFinanceError(f"Yahoo Finance subprocess error: {e}") from e

    if proc.returncode != 0:
        # Capture 451 / WAF / network errors cleanly
        err = (proc.stderr or proc.stdout or "").strip()[:200]
        raise YahooFinanceError(f"Yahoo Finance lookup failed for {symbol}: {err or 'non-zero exit'}")

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise YahooFinanceError(f"Invalid JSON from yahoo_finance for {symbol}: {e}") from e

    # Yahoo Finance quote payload is heterogeneous — extract with fallbacks
    try:
        price = float(
            data.get("regularMarketPrice")
            or data.get("price")
            or data.get("currentPrice")
            or 0.0
        )
        # Yahoo doesn't give us 90d change directly in quote — use 0 and rely on cache
        # for the composite signal unless caller does history aggregation
        return TickerQuote(
            symbol=symbol.upper(),
            short_name=str(data.get("shortName") or data.get("longName") or symbol.upper()),
            price=price,
            change_pct_90d=0.0,
            volatility_annualized=30.0,
            market_cap_billions=float(data.get("marketCap", 0)) / 1e9 if data.get("marketCap") else 0.0,
            currency=str(data.get("currency", "USD")),
            source="live",
        )
    except Exception as e:
        raise YahooFinanceError(f"Failed to parse Yahoo Finance response for {symbol}: {e}") from e


def fetch_quote(symbol: str, *, live: bool = False, timeout: float = 5.0) -> TickerQuote:
    """Get a quote for a single ticker.

    Offline-first: returns cached data unless live=True.
    On any live lookup failure (network / 451 / parse), falls back to cache.

    Args:
        symbol: Ticker symbol (e.g. "MSFT").
        live: If True, attempt a live Yahoo Finance lookup first.
        timeout: Subprocess timeout for live lookups.

    Raises:
        YahooFinanceError: only if live=True AND cache miss AND live lookup fails,
            or if live=False and symbol is not in cache.
    """
    symbol = symbol.upper()

    if live:
        try:
            live_quote = fetch_quote_live(symbol, timeout=timeout)
            # Merge in cached 90d / volatility fields if live quote is missing them
            cached = _get_cached_quote(symbol)
            if cached and live_quote.change_pct_90d == 0.0:
                return TickerQuote(
                    symbol=live_quote.symbol,
                    short_name=live_quote.short_name,
                    price=live_quote.price,
                    change_pct_90d=cached.change_pct_90d,
                    volatility_annualized=cached.volatility_annualized,
                    market_cap_billions=live_quote.market_cap_billions or cached.market_cap_billions,
                    currency=live_quote.currency,
                    source="live",
                )
            return live_quote
        except YahooFinanceError:
            # Fall through to cache
            pass

    cached = _get_cached_quote(symbol)
    if cached:
        return cached

    if live:
        # We already tried live and failed, and cache missed
        raise YahooFinanceError(f"No cached data for {symbol} and live lookup failed")
    raise YahooFinanceError(f"No cached data for {symbol} (offline mode)")


def get_quotes(tickers: list[str], *, live: bool = False) -> list[TickerQuote]:
    """Fetch quotes for multiple tickers. Skips symbols that fail entirely."""
    quotes: list[TickerQuote] = []
    for t in tickers:
        try:
            quotes.append(fetch_quote(t, live=live))
        except YahooFinanceError:
            continue
    return quotes


# ----------------------------------------------------------------------
# Backer resolution
# ----------------------------------------------------------------------


def resolve_backer_tickers(repo_full_name: str) -> list[str]:
    """Map a repo full_name (owner/repo) to corporate backer tickers.

    Looks up the owner in metrics.yaml financial.backers.
    Falls back to the "default" ticker list.
    """
    cfg = _load_metrics_yaml()
    backers = cfg.get("financial", {}).get("backers", {})
    owner = repo_full_name.split("/", 1)[0].lower() if "/" in repo_full_name else ""
    tickers = backers.get(owner) or backers.get("default") or ["MSFT", "GOOGL", "AAPL"]
    return [str(t).upper() for t in tickers]


def collect_financial_metrics(repo_full_name: str, *, live: bool = False) -> FinancialMetrics | None:
    """Collect financial impact metrics for a repository.

    Returns None if no backer tickers resolve or no quotes could be fetched.
    """
    tickers = resolve_backer_tickers(repo_full_name)
    if not tickers:
        return None

    quotes = get_quotes(tickers, live=live)
    if not quotes:
        return None

    # Composite signals — simple equal-weight mean
    composite_change = sum(q.change_pct_90d for q in quotes) / len(quotes)
    composite_vol = sum(q.volatility_annualized for q in quotes) / len(quotes)

    return FinancialMetrics(
        tickers=[q.symbol for q in quotes],
        quotes=quotes,
        composite_change_pct_90d=composite_change,
        composite_volatility=composite_vol,
        backer_count=len(quotes),
    )


# ----------------------------------------------------------------------
# Scoring
# ----------------------------------------------------------------------


def score_financial(
    repo_full_name: str = "unknown/unknown",
    financial_metrics: FinancialMetrics | None = None,
    *,
    live: bool = False,
    config: Any | None = None,
) -> Any:
    """Score Financial Impact (corporate backer stock performance).

    Raw scoring (0–20 pts, scaled to category weight):
    - Price change 90d: 0–12 pts
        ≥ +15% → 12 pts
        ≥ +5%  →  8 pts
        ≥ -5%  →  5 pts
        ≥ -15% →  2 pts
        < -15% →  0 pts
    - Volatility (annualized): 0–5 pts (lower is better)
        ≤ 20% → 5 pts
        ≤ 35% → 3 pts
        ≤ 50% → 1 pt
        > 50% → 0 pts
    - Market cap bonus: 0–3 pts
        avg market cap ≥ $100B → +3 pts

    Returns a CategoryScore-compatible object. If financial data cannot be
    collected, returns a neutral score (10/20) with an informational penalty.

    Args:
        repo_full_name: "owner/repo" string for backer ticker resolution.
        financial_metrics: Pre-collected FinancialMetrics, or None to collect
            automatically (offline-first, cache-backed).
        live: Attempt live Yahoo Finance lookups (falls back to cache on error).
        config: RepoConfig-like object with weight_for() and is_ignored().
    """
    # Lazy import to avoid circular dependency
    from ..scorer import CategoryScore  # type: ignore

    # Config shim
    if config is None:
        weight = 20.0
        def is_ignored(_: str) -> bool: return False
    else:
        weight_for = getattr(config, "weight_for", lambda x: 20.0)
        weight = float(weight_for("financial"))
        is_ignored = getattr(config, "is_ignored", lambda x: False)

    penalties: list[str] = []
    recommendations: list[str] = []

    # Collect financial metrics if not provided
    fm = financial_metrics
    if fm is None:
        try:
            fm = collect_financial_metrics(repo_full_name, live=live)
        except Exception:
            fm = None

    if fm is None or not fm.quotes:
        # No financial data available — neutral score, informational note
        raw_score = 10.0
        if not is_ignored("no_financial_data"):
            penalties.append("No corporate backer financial data available — using neutral baseline")
            recommendations.append(
                "Add a backer ticker mapping in metrics.yaml financial.backers "
                f"for owner '{repo_full_name.split('/')[0] if '/' in repo_full_name else 'unknown'}'"
            )
        score = (raw_score / 20.0) * weight
        return CategoryScore(
            name="Financial",
            score=score,
            max_score=weight,
            penalties=penalties,
            recommendations=recommendations,
        )

    change_pct = fm.composite_change_pct_90d
    volatility = fm.composite_volatility

    # --- Price change component (0–12 pts) ---
    if change_pct >= 15.0:
        price_score = 12.0
    elif change_pct >= 5.0:
        price_score = 8.0
    elif change_pct >= -5.0:
        price_score = 5.0
    elif change_pct >= -15.0:
        price_score = 2.0
        if not is_ignored("backer_stock_decline"):
            penalties.append(
                f"Backer stock down {change_pct:.1f}% over 90 days "
                f"({', '.join(fm.tickers)})"
            )
            recommendations.append(
                "Monitor corporate backer financial health — "
                "sustained declines may affect long-term project sponsorship"
            )
    else:
        price_score = 0.0
        if not is_ignored("backer_stock_decline"):
            penalties.append(
                f"Backer stock down {change_pct:.1f}% over 90 days — significant decline "
                f"({', '.join(fm.tickers)})"
            )
            recommendations.append(
                "Significant backer stock decline detected — "
                "assess project funding continuity risk"
            )

    # --- Volatility component (0–5 pts) ---
    if volatility <= 20.0:
        vol_score = 5.0
    elif volatility <= 35.0:
        vol_score = 3.0
    elif volatility <= 50.0:
        vol_score = 1.0
        if not is_ignored("high_backer_volatility"):
            penalties.append(f"High backer stock volatility: {volatility:.1f}% annualized")
    else:
        vol_score = 0.0
        if not is_ignored("high_backer_volatility"):
            penalties.append(f"Extreme backer stock volatility: {volatility:.1f}% annualized")

    # --- Market cap bonus (0–3 pts) ---
    avg_market_cap = sum(q.market_cap_billions for q in fm.quotes) / len(fm.quotes)
    market_cap_score = 3.0 if avg_market_cap >= 100.0 else 0.0

    raw_score = price_score + vol_score + market_cap_score

    # Informational notes for strong performance
    if change_pct >= 15.0:
        recommendations.append(
            f"Strong backer financial performance: {change_pct:.1f}% gain over 90 days "
            f"({', '.join(fm.tickers)})"
        )

    score = (raw_score / 20.0) * weight

    return CategoryScore(
        name="Financial",
        score=score,
        max_score=weight,
        penalties=penalties,
        recommendations=recommendations,
    )


__all__ = [
    "TickerQuote",
    "FinancialMetrics",
    "YahooFinanceError",
    "fetch_quote",
    "fetch_quote_live",
    "get_quotes",
    "resolve_backer_tickers",
    "collect_financial_metrics",
    "score_financial",
]
