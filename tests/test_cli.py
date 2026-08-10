from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pandas as pd


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from advisor_data.market_data import MarketBundle  # noqa: E402
from advisor_data_cli import main  # noqa: E402


class FakeGateway:
    def __init__(self) -> None:
        self.search_queries: list[str] = []

    def search(self, query: str, instrument_type: str, max_results: int) -> list[dict]:
        self.search_queries.append(query)
        if query == "삼성전자":
            return []
        return [
            {
                "symbol": "005930.KS",
                "short_name": "Samsung Electronics Co., Ltd.",
                "long_name": "Samsung Electronics Co., Ltd.",
                "exchange": "KSC",
                "exchange_display": "Korea Stock Exchange",
                "quote_type": "EQUITY",
                "type_display": "Equity",
                "yahoo_score": 20001.0,
            }
        ]


class CliTests(unittest.TestCase):
    def test_search_emits_normalized_json_candidates(self) -> None:
        gateway = FakeGateway()
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = main(
                [
                    "search",
                    "--query",
                    "삼성전자",
                    "--query-variant",
                    "Samsung Electronics",
                    "--instrument-type",
                    "stock",
                ],
                gateway=gateway,
            )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["candidates"][0]["symbol"], "005930.KS")
        self.assertEqual(payload["candidates"][0]["matched_queries"], ["Samsung Electronics"])
        self.assertEqual(payload["queries_attempted"], ["삼성전자", "Samsung Electronics"])
        self.assertEqual(gateway.search_queries, ["삼성전자", "Samsung Electronics"])

    def test_search_deduplicates_symbol_across_query_variants(self) -> None:
        gateway = FakeGateway()
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = main(
                [
                    "search",
                    "--query",
                    "Samsung Electronics",
                    "--query-variant",
                    "005930",
                ],
                gateway=gateway,
            )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(len(payload["candidates"]), 1)
        self.assertEqual(
            payload["candidates"][0]["matched_queries"],
            ["Samsung Electronics", "005930"],
        )

    def test_single_asset_portfolio_stops_before_network_access(self) -> None:
        def forbidden_loader(**_: object) -> MarketBundle:
            raise AssertionError("network loader should not run")

        stderr = io.StringIO()
        with redirect_stderr(stderr):
            code = main(
                ["portfolio", "--symbols", "AAPL", "--start", "2021-01-01"],
                gateway=FakeGateway(),
                market_loader=forbidden_loader,
            )

        payload = json.loads(stderr.getvalue())
        self.assertEqual(code, 2)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["error"]["code"], "insufficient_assets")

    def test_portfolio_emits_receipt_and_candidates(self) -> None:
        index = pd.to_datetime(["2026-01-02", "2026-01-09", "2026-01-16", "2026-01-23"])
        prices = pd.DataFrame(
            {"AAPL": [100.0, 102.0, 101.0, 104.0], "005930.KS": [70000.0, 71000.0, 70500.0, 72000.0]},
            index=index,
        )
        krw_per_usd = pd.Series([1300.0, 1310.0, 1290.0, 1305.0], index=index, name="KRW=X")

        def loader(**_: object) -> MarketBundle:
            return MarketBundle(
                prices=prices,
                currencies={"AAPL": "USD", "005930.KS": "KRW"},
                fx_prices={"KRW": 1.0 / krw_per_usd},
                receipt={"source": "fixture"},
            )

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = main(
                [
                    "portfolio",
                    "--symbols",
                    "AAPL",
                    "005930.KS",
                    "--start",
                    "2026-01-01",
                    "--min-observations",
                    "3",
                    "--max-weight",
                    "1.0",
                ],
                gateway=FakeGateway(),
                market_loader=loader,
            )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["download_receipt"]["source"], "fixture")
        self.assertEqual(payload["return_receipt"]["observation_count"], 3)
        self.assertIn("minimum_variance", payload["portfolio_candidates"])


if __name__ == "__main__":
    unittest.main()
