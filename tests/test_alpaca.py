from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from advisor_data import DataGateError  # noqa: E402
from advisor_data.alpaca import normalize_alpaca_envelope  # noqa: E402


def bar(symbol: str, timestamp: str, close: float) -> dict[str, object]:
    return {
        "symbol": symbol,
        "timestamp": timestamp,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 10.0,
        "trade_count": 5,
        "vwap": close,
    }


def stock_envelope(
    *,
    symbol: str = "AAPL",
    provider_symbol: str | None = None,
    bars: list[dict[str, object]],
    actions: dict[str, object],
) -> dict[str, object]:
    provider_symbol = provider_symbol or symbol
    asset = {
        "id": "asset-id",
        "asset_class": "us_equity",
        "exchange": "NASDAQ",
        "symbol": provider_symbol,
        "name": "Fixture Equity",
        "status": "active",
        "tradable": True,
    }
    return {
        "schema_version": 1,
        "symbol": symbol,
        "provider_symbol": provider_symbol,
        "fallback_class": "us_equity",
        "classification_evidence": {
            "quote_type": "EQUITY",
            "exchange": "NMS",
            "currency": "USD",
        },
        "primary_failure": {
            "code": "price_history_unavailable",
            "message": "Yahoo returned no usable price history.",
            "details": {},
        },
        "asset_response": {"result": json.dumps(asset)},
        "bars_response": {
            "tool": "get_stock_bars",
            "request": {
                "symbols": [provider_symbol],
                "timeframe": "1Week",
                "feed": "iex",
            },
            "bars": {provider_symbol: bars},
        },
        "corporate_actions_response": {"result": json.dumps(actions)},
    }


def crypto_envelope(
    *,
    symbol: str = "BTC-USD",
    provider_symbol: str = "BTC/USD",
    bars: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "symbol": symbol,
        "provider_symbol": provider_symbol,
        "fallback_class": "crypto",
        "classification_evidence": {
            "quote_type": "CRYPTOCURRENCY",
            "currency": "USD",
        },
        "primary_failure": {
            "code": "price_history_unavailable",
            "message": "Yahoo returned no usable price history.",
            "details": {},
        },
        "bars_response": {
            "tool": "get_crypto_bars",
            "request": {
                "symbols": [provider_symbol],
                "timeframe": "1Week",
                "feed": "us",
            },
            "bars": {provider_symbol: bars},
        },
    }


class AlpacaEnvelopeTests(unittest.TestCase):
    def test_us_equity_requires_exact_active_asset_and_bar_symbol(self) -> None:
        result = normalize_alpaca_envelope(
            stock_envelope(
                bars=[
                    bar("AAPL", "2026-01-05T05:00:00+00:00", 100.0),
                    bar("AAPL", "2026-01-12T05:00:00+00:00", 101.0),
                ],
                actions={"announcements": {}},
            ),
            start="2026-01-01",
            end="2026-01-20",
        )

        self.assertEqual(result.currency, "USD")
        self.assertEqual(result.series.name, "AAPL")
        self.assertEqual(result.series.tolist(), [100.0, 101.0])
        self.assertEqual(result.receipt["provider"], "alpaca")
        self.assertEqual(result.receipt["provider_symbol"], "AAPL")
        self.assertEqual(result.receipt["alpaca_feed"], "iex")

    def test_crypto_accepts_verified_provider_symbol_mapping(self) -> None:
        result = normalize_alpaca_envelope(
            crypto_envelope(
                bars=[
                    bar("BTC/USD", "2026-01-05T00:00:00+00:00", 90000.0),
                    bar("BTC/USD", "2026-01-12T00:00:00+00:00", 91000.0),
                ],
            ),
            start="2026-01-01",
            end="2026-01-20",
        )

        self.assertEqual(result.series.name, "BTC-USD")
        self.assertEqual(result.receipt["provider_symbol"], "BTC/USD")
        self.assertEqual(result.receipt["fallback_class"], "crypto")
        self.assertEqual(result.receipt["alpaca_feed"], "us")

    def test_unsupported_market_fails_before_reading_bars(self) -> None:
        envelope = stock_envelope(bars=[], actions={"announcements": {}})
        envelope["fallback_class"] = "unsupported_market"

        with self.assertRaisesRegex(DataGateError, "fallback_not_supported"):
            normalize_alpaca_envelope(envelope, "2026-01-01", None)

    def test_ambiguous_classification_has_distinct_error(self) -> None:
        envelope = stock_envelope(bars=[], actions={"announcements": {}})
        envelope["fallback_class"] = "ambiguous"

        with self.assertRaisesRegex(DataGateError, "fallback_class_ambiguous"):
            normalize_alpaca_envelope(envelope, "2026-01-01", None)

    def test_wrong_provider_symbol_is_rejected(self) -> None:
        with self.assertRaisesRegex(DataGateError, "alpaca_schema_error"):
            normalize_alpaca_envelope(
                crypto_envelope(
                    bars=[
                        bar("ETH/USD", "2026-01-05T00:00:00+00:00", 3000.0),
                        bar("ETH/USD", "2026-01-12T00:00:00+00:00", 3100.0),
                    ]
                ),
                "2026-01-01",
                None,
            )

    def test_inactive_stock_asset_is_rejected(self) -> None:
        envelope = stock_envelope(
            bars=[
                bar("AAPL", "2026-01-05T00:00:00+00:00", 100.0),
                bar("AAPL", "2026-01-12T00:00:00+00:00", 101.0),
            ],
            actions={"announcements": {}},
        )
        asset = json.loads(envelope["asset_response"]["result"])
        asset["status"] = "inactive"
        envelope["asset_response"]["result"] = json.dumps(asset)

        with self.assertRaisesRegex(DataGateError, "alpaca_asset_not_found"):
            normalize_alpaca_envelope(envelope, "2026-01-01", None)


if __name__ == "__main__":
    unittest.main()
