"""Yahoo Finance boundary with normalized, evidence-preserving outputs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Iterable

import yfinance as yf

from . import DataGateError


FUNDAMENTAL_FIELDS = {
    "market_cap": "marketCap",
    "trailing_pe": "trailingPE",
    "forward_pe": "forwardPE",
    "price_to_book": "priceToBook",
    "enterprise_to_ebitda": "enterpriseToEbitda",
    "operating_margin": "operatingMargins",
    "free_cash_flow": "freeCashflow",
    "total_cash": "totalCash",
    "total_debt": "totalDebt",
    "dividend_yield": "dividendYield",
}


def _default_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _published_at(value: Any) -> str | None:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
    if isinstance(value, str) and value:
        return value
    return None


def _nested(mapping: dict[str, Any], *path: str) -> Any:
    current: Any = mapping
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


class YahooGateway:
    """Return Yahoo candidates and snapshots without making semantic selections."""

    def __init__(
        self,
        search_factory: Callable[..., Any] | None = None,
        ticker_factory: Callable[[str], Any] | None = None,
        now: Callable[[], str] | None = None,
    ) -> None:
        self._search_factory = search_factory or self._search
        self._ticker_factory = ticker_factory or yf.Ticker
        self._now = now or _default_now

    @staticmethod
    def _search(query: str, max_results: int = 10) -> Any:
        return yf.Search(query, max_results=max_results, news_count=0, include_research=False)

    def search(self, query: str, instrument_type: str = "all", max_results: int = 10) -> list[dict[str, Any]]:
        if not query.strip():
            raise DataGateError("empty_query", "A security name or ticker is required.")
        allowed_types = {
            "all": None,
            "stock": {"EQUITY"},
            "equity": {"EQUITY"},
            "etf": {"ETF"},
        }
        if instrument_type not in allowed_types:
            raise DataGateError(
                "unsupported_instrument_type",
                f"Unsupported instrument type: {instrument_type}",
            )
        try:
            search = self._search_factory(query, max_results=max_results)
        except Exception as exc:
            error_type = exc.__class__.__name__
            raise DataGateError(
                "network_error",
                "Yahoo security search failed.",
                {
                    "error_type": error_type,
                    "rate_limited": error_type == "YFRateLimitError",
                },
            ) from exc
        quotes = getattr(search, "quotes", None) or []
        candidates: list[dict[str, Any]] = []
        for quote in quotes:
            if not isinstance(quote, dict) or not quote.get("symbol"):
                continue
            quote_type = str(quote.get("quoteType") or quote.get("typeDisp") or "").upper()
            allowed = allowed_types[instrument_type]
            if allowed is not None and quote_type not in allowed:
                continue
            candidates.append(
                {
                    "symbol": str(quote["symbol"]),
                    "short_name": quote.get("shortname") or quote.get("shortName"),
                    "long_name": quote.get("longname") or quote.get("longName"),
                    "exchange": quote.get("exchange"),
                    "exchange_display": quote.get("exchDisp") or quote.get("exchangeDisplay"),
                    "quote_type": quote_type or None,
                    "type_display": quote.get("typeDisp"),
                    "yahoo_score": quote.get("score"),
                }
            )
        return candidates

    def validate_candidate(self, symbol: str, candidates: Iterable[dict[str, Any]]) -> dict[str, Any]:
        candidate_by_symbol = {
            str(candidate.get("symbol", "")).upper(): candidate
            for candidate in candidates
            if candidate.get("symbol")
        }
        normalized_symbol = symbol.upper()
        if normalized_symbol not in candidate_by_symbol:
            raise DataGateError(
                "candidate_not_returned",
                "The selected symbol was not present in Yahoo's candidate set.",
                {"symbol": symbol, "allowed_symbols": sorted(candidate_by_symbol)},
            )

        ticker = self._ticker_factory(symbol)
        history_options = {
            "period": "5d",
            "interval": "1d",
            "auto_adjust": True,
            "actions": True,
            "raise_errors": True,
        }
        repair_used = True
        repair_fallback_error_type: str | None = None
        try:
            history = ticker.history(**history_options, repair=True)
        except Exception as repair_exc:
            repair_used = False
            repair_fallback_error_type = repair_exc.__class__.__name__
            try:
                history = ticker.history(**history_options, repair=False)
            except Exception as fallback_exc:
                raise DataGateError(
                    "price_history_unavailable",
                    f"Yahoo price validation failed for {symbol} with and without repair.",
                    {
                        "repair_error_type": repair_exc.__class__.__name__,
                        "fallback_error_type": fallback_exc.__class__.__name__,
                    },
                ) from fallback_exc
        if history is None or history.empty:
            raise DataGateError(
                "price_history_unavailable",
                f"Yahoo returned no usable price history for {symbol}.",
            )
        metadata = getattr(ticker, "history_metadata", None) or {}
        candidate = candidate_by_symbol[normalized_symbol]
        return {
            "status": "validated",
            "symbol": symbol,
            "exchange": metadata.get("exchangeName") or candidate.get("exchange"),
            "quote_type": metadata.get("instrumentType") or candidate.get("quote_type"),
            "currency": metadata.get("currency"),
            "timezone": metadata.get("timezone") or metadata.get("exchangeTimezoneName"),
            "history_rows": int(len(history.index)),
            "repair_requested": True,
            "repair_used": repair_used,
            "repair_fallback_error_type": repair_fallback_error_type,
            "first_price_at": history.index.min().isoformat(),
            "last_price_at": history.index.max().isoformat(),
            "validated_at": self._now(),
        }

    def fundamentals(self, symbol: str) -> dict[str, Any]:
        ticker = self._ticker_factory(symbol)
        try:
            info = getattr(ticker, "info", None) or {}
        except Exception as exc:
            raise DataGateError(
                "fundamentals_unavailable",
                f"Yahoo fundamentals failed for {symbol}.",
                {"error_type": exc.__class__.__name__},
            ) from exc
        values = {output: info.get(source) for output, source in FUNDAMENTAL_FIELDS.items()}
        return {
            "status": "ok",
            "symbol": symbol,
            "currency": info.get("financialCurrency") or info.get("currency"),
            "values": values,
            "missing_fields": [field for field, value in values.items() if value is None],
            "retrieved_at": self._now(),
            "source": "Yahoo Finance via yfinance",
        }

    def news(self, symbol: str, count: int = 10) -> list[dict[str, Any]]:
        ticker = self._ticker_factory(symbol)
        try:
            raw_items = ticker.get_news(count=count, tab="news")
        except Exception as exc:
            raise DataGateError(
                "news_unavailable",
                f"Yahoo news discovery failed for {symbol}.",
                {"error_type": exc.__class__.__name__},
            ) from exc
        normalized: list[dict[str, Any]] = []
        for raw in raw_items or []:
            if not isinstance(raw, dict):
                continue
            content = raw.get("content") if isinstance(raw.get("content"), dict) else raw
            provider = content.get("publisher") or _nested(content, "provider", "displayName")
            link = content.get("link") or _nested(content, "canonicalUrl", "url") or _nested(
                content, "clickThroughUrl", "url"
            )
            published = content.get("providerPublishTime") or content.get("pubDate")
            normalized.append(
                {
                    "title": content.get("title"),
                    "publisher": provider,
                    "url": link,
                    "published_at": _published_at(published),
                    "source_role": "discovery_only",
                    "retrieved_at": self._now(),
                }
            )
        return normalized
