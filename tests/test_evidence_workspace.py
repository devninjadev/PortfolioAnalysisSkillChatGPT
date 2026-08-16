from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from advisor_data import DataGateError  # noqa: E402
from advisor_data.evidence_workspace import (  # noqa: E402
    complete_market_bundle,
    prepare_yahoo_workspace,
    read_workspace,
    write_workspace,
)
from advisor_data.market_data import MarketBundle  # noqa: E402
from tests.test_alpaca import bar, crypto_envelope, stock_envelope  # noqa: E402
from tests.test_wolfram import financial_envelope, observation  # noqa: E402


INDEX = pd.to_datetime(
    ["2026-01-05T00:00:00+00:00", "2026-01-12T00:00:00+00:00"]
)


def yahoo_bundle(
    symbol: str,
    values: list[float],
    *,
    currency: str = "USD",
    fx_prices: dict[str, pd.Series] | None = None,
) -> MarketBundle:
    return MarketBundle(
        prices=pd.DataFrame({symbol: values}, index=INDEX),
        currencies={symbol: currency},
        fx_prices=fx_prices or {},
        receipt={"source": "Yahoo fixture", "symbols": [symbol]},
    )


def yahoo_currency(
    symbol: str,
    currency: str = "USD",
) -> tuple[str, dict[str, object]]:
    return currency, {
        "source": "Yahoo Finance via yfinance",
        "symbol": symbol,
        "currency": currency,
        "retrieved_at": "2026-08-16T00:00:00+00:00",
    }


def yahoo_fx(currency: str, **_: object) -> tuple[pd.Series, dict[str, str]]:
    values = [1.15, 1.16] if currency == "EUR" else [0.00075, 0.00076]
    return (
        pd.Series(values, index=INDEX, name=f"{currency}USD=X"),
        {"symbol": f"{currency}USD=X", "orientation": "USD_per_currency_unit"},
    )


class EvidenceWorkspaceTests(unittest.TestCase):
    def test_non_price_yahoo_failure_is_not_marked_fallback_required(self) -> None:
        with self.assertRaisesRegex(DataGateError, "currency_unavailable"):
            prepare_yahoo_workspace(
                ["SAP.DE"],
                "2026-01-01",
                "2026-02-01",
                "USD",
                market_loader=lambda **_: (_ for _ in ()).throw(
                    DataGateError(
                        "currency_unavailable",
                        "Yahoo currency metadata failed for SAP.DE.",
                    )
                ),
                currency_loader=lambda **_: self.fail(
                    "A non-price failure must not enter fallback preparation."
                ),
            )

    def test_price_failure_persists_yahoo_currency_and_downloads_asset_fx(self) -> None:
        currency_calls: list[str] = []
        fx_calls: list[str] = []

        def currency_loader(*, symbol: str) -> tuple[str, dict[str, object]]:
            currency_calls.append(symbol)
            return yahoo_currency(symbol, "EUR")

        def fx_loader(*, currency: str, **kwargs: object):
            fx_calls.append(currency)
            return yahoo_fx(currency, **kwargs)

        workspace = prepare_yahoo_workspace(
            ["SAP.DE"],
            "2026-01-01",
            "2026-02-01",
            "USD",
            market_loader=lambda **_: (_ for _ in ()).throw(
                DataGateError("price_history_unavailable", "Yahoo price history failed.")
            ),
            currency_loader=currency_loader,
            base_fx_loader=fx_loader,
        )
        envelope = financial_envelope(
            symbol="SAP.DE",
            provider_entity="XETR:SAP",
            currency="EUR",
            exchange="XETRA",
            issuer="SAP SE",
            observations=[
                observation("2026-01-05T00:00:00+00:00", 200.0),
                observation("2026-01-30T00:00:00+00:00", 202.0),
            ],
        )

        bundle = complete_market_bundle(workspace, [envelope])

        self.assertEqual(currency_calls, ["SAP.DE"])
        self.assertEqual(fx_calls, ["EUR"])
        self.assertEqual(
            workspace["yahoo_currency_evidence"]["SAP.DE"]["currency"], "EUR"
        )
        self.assertIn("EUR", workspace["fx_prices"])
        self.assertEqual(bundle.currencies["SAP.DE"], "EUR")
        self.assertEqual(bundle.receipt["providers"], {"SAP.DE": "wolfram"})

    def test_fallback_currency_must_match_stored_yahoo_currency(self) -> None:
        workspace = prepare_yahoo_workspace(
            ["SAP.DE"],
            "2026-01-01",
            "2026-02-01",
            "USD",
            market_loader=lambda **_: (_ for _ in ()).throw(
                DataGateError("price_history_unavailable", "Yahoo price history failed.")
            ),
            currency_loader=lambda **_: yahoo_currency("SAP.DE", "EUR"),
            base_fx_loader=yahoo_fx,
        )
        envelope = financial_envelope(
            symbol="SAP.DE",
            provider_entity="XETR:SAP",
            currency="USD",
            exchange="XETRA",
            issuer="SAP SE",
            observations=[
                observation("2026-01-05T00:00:00+00:00", 200.0),
                observation("2026-01-30T00:00:00+00:00", 202.0),
            ],
        )

        with self.assertRaisesRegex(DataGateError, "fallback_currency_mismatch"):
            complete_market_bundle(workspace, [envelope])

    def test_prepare_preserves_yahoo_success_and_records_failure(self) -> None:
        calls: list[str] = []

        def loader(*, symbols: list[str], **_: object) -> MarketBundle:
            symbol = symbols[0]
            calls.append(symbol)
            if symbol == "AAPL":
                return yahoo_bundle("AAPL", [100.0, 101.0])
            raise DataGateError(
                "price_history_unavailable",
                "Yahoo returned no usable price history for 005930.KS.",
            )

        workspace = prepare_yahoo_workspace(
            ["AAPL", "005930.KS"],
            "2026-01-01",
            None,
            "USD",
            market_loader=loader,
            currency_loader=lambda *, symbol: yahoo_currency(symbol, "KRW"),
            base_fx_loader=yahoo_fx,
        )

        self.assertEqual(calls, ["AAPL", "005930.KS"])
        self.assertIn("AAPL", workspace["assets"])
        self.assertEqual(
            workspace["failures"]["005930.KS"]["code"],
            "price_history_unavailable",
        )
        self.assertEqual(
            workspace["assets"]["AAPL"]["prices"]["observations"][0],
            {
                "timestamp": "2026-01-05T00:00:00+00:00",
                "value": 100.0,
            },
        )

    def test_workspace_round_trip_preserves_schema_and_values(self) -> None:
        workspace = prepare_yahoo_workspace(
            ["AAPL"],
            "2026-01-01",
            "2026-02-01",
            "USD",
            market_loader=lambda **_: yahoo_bundle("AAPL", [100.0, 101.0]),
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "evidence.json"
            write_workspace(path, workspace)
            loaded = read_workspace(path)

        self.assertEqual(loaded, workspace)
        self.assertEqual(loaded["schema_version"], 1)

    def test_complete_merges_yahoo_and_alpaca_without_dropping_symbols(self) -> None:
        def loader(*, symbols: list[str], **_: object) -> MarketBundle:
            if symbols == ["AAPL"]:
                return yahoo_bundle("AAPL", [100.0, 101.0])
            raise DataGateError(
                "price_history_unavailable",
                "Yahoo returned no usable price history.",
            )

        workspace = prepare_yahoo_workspace(
            ["AAPL", "BTC-USD"],
            "2026-01-01",
            "2026-02-01",
            "USD",
            market_loader=loader,
            currency_loader=lambda *, symbol: yahoo_currency(symbol, "USD"),
        )
        bundle = complete_market_bundle(
            workspace,
            [
                crypto_envelope(
                    symbol="BTC-USD",
                    provider_symbol="BTC/USD",
                    bars=[
                        bar("BTC/USD", "2026-01-05T00:00:00+00:00", 90000.0),
                        bar("BTC/USD", "2026-01-12T00:00:00+00:00", 91000.0),
                    ],
                )
            ],
        )

        self.assertEqual(list(bundle.prices.columns), ["AAPL", "BTC-USD"])
        self.assertEqual(
            bundle.receipt["providers"],
            {"AAPL": "yahoo", "BTC-USD": "alpaca"},
        )
        self.assertEqual(bundle.currencies, {"AAPL": "USD", "BTC-USD": "USD"})
        self.assertEqual(
            bundle.receipt["asset_receipts"]["BTC-USD"]["primary_failure"]["code"],
            "price_history_unavailable",
        )

    def test_complete_merges_yahoo_and_wolfram_without_dropping_symbols(self) -> None:
        def loader(*, symbols: list[str], **_: object) -> MarketBundle:
            if symbols == ["AAPL"]:
                return yahoo_bundle("AAPL", [100.0, 101.0])
            raise DataGateError(
                "price_history_unavailable",
                "Yahoo returned no usable history for SAP.DE.",
            )

        workspace = prepare_yahoo_workspace(
            ["AAPL", "SAP.DE"],
            "2026-01-01",
            "2026-02-01",
            "USD",
            market_loader=loader,
            currency_loader=lambda *, symbol: yahoo_currency(symbol, "EUR"),
            base_fx_loader=yahoo_fx,
        )
        envelope = financial_envelope(
            symbol="SAP.DE",
            provider_entity="XETR:SAP",
            currency="EUR",
            exchange="XETRA",
            issuer="SAP SE",
            observations=[
                observation("2026-01-05T00:00:00+00:00", 200.0),
                observation("2026-01-30T00:00:00+00:00", 202.0),
            ],
        )
        bundle = complete_market_bundle(workspace, [envelope])

        self.assertEqual(list(bundle.prices.columns), ["AAPL", "SAP.DE"])
        self.assertEqual(
            bundle.receipt["providers"],
            {"AAPL": "yahoo", "SAP.DE": "wolfram"},
        )
        self.assertEqual(bundle.currencies["SAP.DE"], "EUR")

    def test_legacy_alpaca_envelope_without_provider_uses_alpaca(self) -> None:
        workspace = prepare_yahoo_workspace(
            ["BTC-USD"],
            "2026-01-01",
            "2026-02-01",
            "USD",
            market_loader=lambda **_: (_ for _ in ()).throw(
                DataGateError("price_history_unavailable", "Yahoo failed.")
            ),
            currency_loader=lambda *, symbol: yahoo_currency(symbol, "USD"),
        )
        envelope = crypto_envelope(
            bars=[
                bar("BTC/USD", "2026-01-05T00:00:00+00:00", 90000.0),
                bar("BTC/USD", "2026-01-12T00:00:00+00:00", 91000.0),
            ]
        )

        bundle = complete_market_bundle(workspace, [envelope])

        self.assertNotIn("provider", envelope)
        self.assertEqual(bundle.receipt["providers"], {"BTC-USD": "alpaca"})

    def test_complete_preserves_one_receipt_for_each_distinct_provider(self) -> None:
        def loader(*, symbols: list[str], **_: object) -> MarketBundle:
            if symbols == ["AAPL"]:
                return yahoo_bundle("AAPL", [100.0, 101.0])
            raise DataGateError("price_history_unavailable", "Yahoo failed.")

        workspace = prepare_yahoo_workspace(
            ["AAPL", "BTC-USD", "SAP.DE"],
            "2026-01-01",
            "2026-02-01",
            "USD",
            market_loader=loader,
            currency_loader=lambda *, symbol: yahoo_currency(
                symbol, "EUR" if symbol == "SAP.DE" else "USD"
            ),
            base_fx_loader=yahoo_fx,
        )
        wolfram = financial_envelope(
            symbol="SAP.DE",
            provider_entity="XETR:SAP",
            currency="EUR",
            exchange="XETRA",
            issuer="SAP SE",
            observations=[
                observation("2026-01-05T00:00:00+00:00", 200.0),
                observation("2026-01-30T00:00:00+00:00", 202.0),
            ],
        )

        bundle = complete_market_bundle(
            workspace,
            [
                crypto_envelope(
                    bars=[
                        bar("BTC/USD", "2026-01-05T00:00:00+00:00", 90000.0),
                        bar("BTC/USD", "2026-01-12T00:00:00+00:00", 91000.0),
                    ]
                ),
                wolfram,
            ],
        )

        self.assertEqual(
            bundle.receipt["providers"],
            {"AAPL": "yahoo", "BTC-USD": "alpaca", "SAP.DE": "wolfram"},
        )
        self.assertEqual(
            bundle.receipt["asset_receipts"]["BTC-USD"]["primary_failure"],
            workspace["failures"]["BTC-USD"],
        )
        self.assertEqual(
            bundle.receipt["asset_receipts"]["SAP.DE"]["primary_failure"],
            workspace["failures"]["SAP.DE"],
        )

    def test_duplicate_alpaca_and_wolfram_envelopes_for_failed_symbol_are_rejected(self) -> None:
        workspace = prepare_yahoo_workspace(
            ["SAP.DE"],
            "2026-01-01",
            "2026-02-01",
            "USD",
            market_loader=lambda **_: (_ for _ in ()).throw(
                DataGateError("price_history_unavailable", "Yahoo failed.")
            ),
            currency_loader=lambda *, symbol: yahoo_currency(symbol, "EUR"),
            base_fx_loader=yahoo_fx,
        )
        alpaca = crypto_envelope(
            symbol="SAP.DE",
            bars=[
                bar("BTC/USD", "2026-01-05T00:00:00+00:00", 90000.0),
                bar("BTC/USD", "2026-01-12T00:00:00+00:00", 91000.0),
            ],
        )
        wolfram = financial_envelope(
            symbol="SAP.DE",
            provider_entity="XETR:SAP",
            currency="EUR",
            exchange="XETRA",
            issuer="SAP SE",
            observations=[
                observation("2026-01-05T00:00:00+00:00", 200.0),
                observation("2026-01-30T00:00:00+00:00", 202.0),
            ],
        )

        with self.assertRaisesRegex(DataGateError, "Duplicate fallback inputs"):
            complete_market_bundle(workspace, [alpaca, wolfram])

    def test_wolfram_envelope_for_yahoo_success_is_rejected_as_unrequested(self) -> None:
        workspace = prepare_yahoo_workspace(
            ["AAPL"],
            "2026-01-01",
            "2026-02-01",
            "USD",
            market_loader=lambda **_: yahoo_bundle("AAPL", [100.0, 101.0]),
        )
        envelope = financial_envelope(
            observations=[
                observation("2026-01-05T00:00:00+00:00", 100.0),
                observation("2026-01-12T00:00:00+00:00", 101.0),
            ]
        )

        with self.assertRaisesRegex(DataGateError, "unrequested symbol AAPL"):
            complete_market_bundle(workspace, [envelope])

    def test_unknown_provider_is_rejected_before_normalization(self) -> None:
        workspace = prepare_yahoo_workspace(
            ["SAP.DE"],
            "2026-01-01",
            "2026-02-01",
            "USD",
            market_loader=lambda **_: (_ for _ in ()).throw(
                DataGateError("price_history_unavailable", "Yahoo failed.")
            ),
            currency_loader=lambda *, symbol: yahoo_currency(symbol, "EUR"),
            base_fx_loader=yahoo_fx,
        )
        envelope = {"provider": "unvalidated", "symbol": "SAP.DE"}

        with self.assertRaisesRegex(DataGateError, "No validated fallback adapter"):
            complete_market_bundle(workspace, [envelope])

    def test_missing_eur_yahoo_fx_blocks_wolfram_bundle(self) -> None:
        workspace = prepare_yahoo_workspace(
            ["SAP.DE"],
            "2026-01-01",
            "2026-02-01",
            "USD",
            market_loader=lambda **_: (_ for _ in ()).throw(
                DataGateError("price_history_unavailable", "Yahoo failed.")
            ),
            currency_loader=lambda *, symbol: yahoo_currency(symbol, "EUR"),
            base_fx_loader=lambda **_: (_ for _ in ()).throw(
                DataGateError("fx_history_unavailable", "EUR FX failed.")
            ),
        )
        envelope = financial_envelope(
            symbol="SAP.DE",
            provider_entity="XETR:SAP",
            currency="EUR",
            exchange="XETRA",
            issuer="SAP SE",
            observations=[
                observation("2026-01-05T00:00:00+00:00", 200.0),
                observation("2026-01-30T00:00:00+00:00", 202.0),
            ],
        )

        with self.assertRaisesRegex(DataGateError, "fx_history_unavailable"):
            complete_market_bundle(workspace, [envelope])

    def test_unsupported_korean_failure_never_accepts_alpaca(self) -> None:
        def failed_loader(**_: object) -> MarketBundle:
            raise DataGateError(
                "price_history_unavailable",
                "Yahoo returned no usable price history for 005930.KS.",
            )

        workspace = prepare_yahoo_workspace(
            ["005930.KS"],
            "2026-01-01",
            None,
            "KRW",
            market_loader=failed_loader,
            currency_loader=lambda *, symbol: yahoo_currency(symbol, "KRW"),
            base_fx_loader=lambda **_: (
                pd.Series([0.00075, 0.00076], index=INDEX, name="KRWUSD=X"),
                {"symbol": "KRWUSD=X"},
            ),
        )
        envelope = stock_envelope(
            symbol="005930.KS",
            bars=[],
            actions={"announcements": {}},
        )
        envelope["fallback_class"] = "unsupported_market"

        with self.assertRaisesRegex(DataGateError, "fallback_not_supported"):
            complete_market_bundle(workspace, [envelope])

    def test_missing_required_fallback_input_blocks_bundle(self) -> None:
        workspace = prepare_yahoo_workspace(
            ["BTC-USD"],
            "2026-01-01",
            None,
            "USD",
            market_loader=lambda **_: (_ for _ in ()).throw(
                DataGateError("price_history_unavailable", "Yahoo failed.")
            ),
            currency_loader=lambda *, symbol: yahoo_currency(symbol, "USD"),
        )

        with self.assertRaisesRegex(DataGateError, "fallback_not_supported"):
            complete_market_bundle(workspace, [])

    def test_missing_base_fx_blocks_cross_currency_bundle(self) -> None:
        workspace = prepare_yahoo_workspace(
            ["BTC-USD"],
            "2026-01-01",
            None,
            "KRW",
            market_loader=lambda **_: (_ for _ in ()).throw(
                DataGateError("price_history_unavailable", "Yahoo failed.")
            ),
            currency_loader=lambda *, symbol: yahoo_currency(symbol, "USD"),
            base_fx_loader=lambda **_: (_ for _ in ()).throw(
                DataGateError("fx_history_unavailable", "KRW FX failed.")
            ),
        )
        envelope = crypto_envelope(
            bars=[
                bar("BTC/USD", "2026-01-05T00:00:00+00:00", 90000.0),
                bar("BTC/USD", "2026-01-12T00:00:00+00:00", 91000.0),
            ]
        )

        with self.assertRaisesRegex(DataGateError, "fx_history_unavailable"):
            complete_market_bundle(workspace, [envelope])

    def test_extra_alpaca_envelope_is_rejected(self) -> None:
        workspace = prepare_yahoo_workspace(
            ["AAPL"],
            "2026-01-01",
            None,
            "USD",
            market_loader=lambda **_: yahoo_bundle("AAPL", [100.0, 101.0]),
        )
        envelope = crypto_envelope(
            bars=[
                bar("BTC/USD", "2026-01-05T00:00:00+00:00", 90000.0),
                bar("BTC/USD", "2026-01-12T00:00:00+00:00", 91000.0),
            ]
        )

        with self.assertRaisesRegex(DataGateError, "unrequested"):
            complete_market_bundle(workspace, [envelope])


if __name__ == "__main__":
    unittest.main()
