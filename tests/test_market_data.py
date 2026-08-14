from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from advisor_data import DataGateError  # noqa: E402
from advisor_data.market_data import (  # noqa: E402
    build_return_matrix,
    download_currency_bridge,
    download_market_bundle,
)


class MarketDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.index = pd.to_datetime(["2026-01-02", "2026-01-09", "2026-01-16", "2026-01-23"])
        self.prices = pd.DataFrame(
            {
                "AAPL": [100.0, 110.0, 121.0, 133.1],
                "005930.KS": [1000.0, 1000.0, 1000.0, 1000.0],
            },
            index=self.index,
        )
        self.krw_per_usd = pd.Series(
            [1000.0, 1100.0, 1000.0, 1000.0], index=self.index, name="KRW=X"
        )
        self.fx = {"KRW": 1.0 / self.krw_per_usd}

    def test_usd_prices_are_converted_to_krw_before_returns(self) -> None:
        result = build_return_matrix(
            self.prices,
            {"AAPL": "USD", "005930.KS": "KRW"},
            base_currency="KRW",
            fx_prices=self.fx,
            frequency="weekly",
            min_observations=3,
        )

        self.assertEqual(list(result.returns.columns), ["AAPL", "005930.KS"])
        self.assertAlmostEqual(result.returns.iloc[0]["AAPL"], 0.21, places=8)
        self.assertAlmostEqual(result.returns.iloc[1]["AAPL"], 0.0, places=8)
        self.assertEqual(result.receipt["observation_count"], 3)
        self.assertEqual(result.receipt["base_currency"], "KRW")

    def test_krw_prices_are_converted_to_usd_before_returns(self) -> None:
        result = build_return_matrix(
            self.prices[["005930.KS"]],
            {"005930.KS": "KRW"},
            base_currency="USD",
            fx_prices=self.fx,
            frequency="weekly",
            min_observations=3,
        )

        self.assertAlmostEqual(result.returns.iloc[0]["005930.KS"], -1 / 11, places=8)
        self.assertAlmostEqual(result.returns.iloc[1]["005930.KS"], 0.1, places=8)

    def test_insufficient_common_history_is_rejected(self) -> None:
        with self.assertRaisesRegex(DataGateError, "insufficient_history"):
            build_return_matrix(
                self.prices,
                {"AAPL": "USD", "005930.KS": "KRW"},
                base_currency="KRW",
                fx_prices=self.fx,
                frequency="weekly",
                min_observations=4,
            )

    def test_missing_asset_week_is_not_forward_filled(self) -> None:
        prices = self.prices.drop(index=self.index[1]).copy()
        prices.loc[self.index[2], "005930.KS"] = float("nan")

        with self.assertRaisesRegex(DataGateError, "insufficient_history"):
            build_return_matrix(
                prices,
                {"AAPL": "USD", "005930.KS": "KRW"},
                base_currency="KRW",
                fx_prices=self.fx,
                frequency="weekly",
                min_observations=2,
            )

    def test_missing_dynamic_fx_series_stops_calculation(self) -> None:
        with self.assertRaisesRegex(DataGateError, "fx_history_unavailable"):
            build_return_matrix(
                self.prices[["AAPL"]],
                {"AAPL": "JPY"},
                base_currency="KRW",
                fx_prices=self.fx,
                frequency="weekly",
                min_observations=3,
            )

    def test_japanese_and_euro_assets_convert_through_usd_to_krw(self) -> None:
        prices = pd.DataFrame(
            {
                "7203.T": [1000.0, 1000.0, 1000.0, 1000.0],
                "SAP.DE": [100.0, 100.0, 100.0, 100.0],
            },
            index=self.index,
        )
        fx_prices = {
            "JPY": pd.Series([0.01, 0.011, 0.01, 0.01], index=self.index, name="JPYUSD=X"),
            "EUR": pd.Series([1.0, 1.0, 1.1, 1.1], index=self.index, name="EURUSD=X"),
            "KRW": pd.Series([0.001, 0.001, 0.001, 0.001], index=self.index, name="KRWUSD=X"),
        }

        result = build_return_matrix(
            prices,
            {"7203.T": "JPY", "SAP.DE": "EUR"},
            base_currency="KRW",
            fx_prices=fx_prices,
            frequency="weekly",
            min_observations=3,
        )

        self.assertAlmostEqual(result.returns.iloc[0]["7203.T"], 0.1, places=8)
        self.assertAlmostEqual(result.returns.iloc[1]["SAP.DE"], 0.1, places=8)
        self.assertEqual(result.receipt["fx_currencies"], ["EUR", "JPY", "KRW"])

    def test_london_pence_currency_is_scaled_to_gbp(self) -> None:
        prices = pd.DataFrame({"SHEL.L": [2500.0, 2525.0, 2550.0, 2575.0]}, index=self.index)

        result = build_return_matrix(
            prices,
            {"SHEL.L": "GBp"},
            base_currency="GBP",
            fx_prices={},
            frequency="weekly",
            min_observations=3,
        )

        self.assertAlmostEqual(result.normalized_prices.iloc[0]["SHEL.L"], 25.0, places=8)
        self.assertEqual(result.receipt["asset_currencies"], {"SHEL.L": "GBP"})
        self.assertEqual(result.receipt["source_currency_units"], {"SHEL.L": "GBp"})

    def test_download_market_bundle_uses_explicit_adjustment_and_repair_options(self) -> None:
        calls: list[dict] = []

        def downloader(**kwargs: object) -> pd.DataFrame:
            calls.append(dict(kwargs))
            tickers = kwargs["tickers"]
            if tickers == "KRWUSD=X":
                return pd.DataFrame({"Close": [1 / 1300.0, 1 / 1310.0]}, index=self.index[:2])
            columns = pd.MultiIndex.from_product(
                [["Close"], ["AAPL", "005930.KS"]], names=["Price", "Ticker"]
            )
            return pd.DataFrame([[100.0, 70000.0], [101.0, 71000.0]], index=self.index[:2], columns=columns)

        class MetadataTicker:
            def __init__(self, symbol: str) -> None:
                self.symbol = symbol

            def get_history_metadata(self) -> dict[str, str]:
                return {"currency": "USD" if self.symbol == "AAPL" else "KRW"}

        bundle = download_market_bundle(
            ["AAPL", "005930.KS"],
            start="2026-01-01",
            end="2026-02-01",
            base_currency="KRW",
            downloader=downloader,
            ticker_factory=MetadataTicker,
            now=lambda: "2026-08-10T12:00:00+09:00",
        )

        self.assertEqual(list(bundle.prices.columns), ["AAPL", "005930.KS"])
        self.assertEqual(bundle.currencies, {"AAPL": "USD", "005930.KS": "KRW"})
        self.assertEqual(bundle.fx_prices["KRW"].name, "KRWUSD=X")
        self.assertTrue(calls[0]["auto_adjust"])
        self.assertTrue(calls[0]["actions"])
        self.assertTrue(calls[0]["repair"])
        self.assertEqual(bundle.receipt["fx_pairs"]["KRW"]["symbol"], "KRWUSD=X")
        self.assertEqual(bundle.receipt["retrieved_at"], "2026-08-10T12:00:00+09:00")

    def test_download_market_bundle_discovers_non_usd_fx_pairs_dynamically(self) -> None:
        calls: list[str | list[str]] = []

        def downloader(**kwargs: object) -> pd.DataFrame:
            tickers = kwargs["tickers"]
            calls.append(tickers)
            if tickers == "JPYUSD=X":
                return pd.DataFrame({"Close": [0.0065, 0.0066]}, index=self.index[:2])
            if tickers == "EURUSD=X":
                return pd.DataFrame({"Close": [1.10, 1.11]}, index=self.index[:2])
            columns = pd.MultiIndex.from_product(
                [["Close"], ["7203.T", "SAP.DE"]], names=["Price", "Ticker"]
            )
            return pd.DataFrame([[2800.0, 190.0], [2820.0, 192.0]], index=self.index[:2], columns=columns)

        class MetadataTicker:
            def __init__(self, symbol: str) -> None:
                self.symbol = symbol

            def get_history_metadata(self) -> dict[str, str]:
                return {"currency": "JPY" if self.symbol == "7203.T" else "EUR"}

        bundle = download_market_bundle(
            ["7203.T", "SAP.DE"],
            start="2026-01-01",
            end="2026-02-01",
            base_currency="EUR",
            downloader=downloader,
            ticker_factory=MetadataTicker,
        )

        self.assertIn("JPYUSD=X", calls)
        self.assertIn("EURUSD=X", calls)
        self.assertEqual(set(bundle.fx_prices), {"EUR", "JPY"})
        self.assertEqual(bundle.receipt["supported_by_runtime"], ["EUR", "JPY"])

    def test_asset_download_records_repair_fallback(self) -> None:
        calls: list[bool] = []

        def downloader(**kwargs: object) -> pd.DataFrame:
            calls.append(bool(kwargs["repair"]))
            if kwargs["repair"]:
                raise ValueError("output array is read-only")
            columns = pd.MultiIndex.from_product(
                [["Close"], ["SHEL.L", "SAP.DE"]], names=["Price", "Ticker"]
            )
            return pd.DataFrame([[25.0, 190.0], [25.5, 192.0]], index=self.index[:2], columns=columns)

        class MetadataTicker:
            def __init__(self, symbol: str) -> None:
                self.symbol = symbol

            def get_history_metadata(self) -> dict[str, str]:
                return {"currency": "EUR"}

        bundle = download_market_bundle(
            ["SHEL.L", "SAP.DE"],
            start="2026-01-01",
            end="2026-02-01",
            base_currency="EUR",
            downloader=downloader,
            ticker_factory=MetadataTicker,
        )

        self.assertEqual(calls, [True, False])
        self.assertFalse(bundle.receipt["repair_used"])
        self.assertEqual(bundle.receipt["repair_fallback_error_type"], "ValueError")

    def test_currency_bridge_uses_direct_yahoo_pair(self) -> None:
        calls: list[dict[str, object]] = []

        def downloader(**kwargs: object) -> pd.DataFrame:
            calls.append(dict(kwargs))
            return pd.DataFrame(
                {"Close": [0.00075, 0.00076]},
                index=self.index[:2],
            )

        series, receipt = download_currency_bridge(
            "KRW",
            start="2026-01-01",
            end="2026-02-01",
            downloader=downloader,
        )

        self.assertEqual(calls[0]["tickers"], "KRWUSD=X")
        self.assertFalse(calls[0]["auto_adjust"])
        self.assertFalse(calls[0]["actions"])
        self.assertEqual(series.name, "KRWUSD=X")
        self.assertEqual(receipt["orientation"], "USD_per_currency_unit")


if __name__ == "__main__":
    unittest.main()
