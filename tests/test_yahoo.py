from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd
from yfinance.exceptions import YFRateLimitError


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from advisor_data import DataGateError  # noqa: E402
from advisor_data.yahoo import YahooGateway  # noqa: E402


class FakeSearch:
    quotes = [
        {
            "symbol": "005930.KS",
            "shortname": "Samsung Electronics Co., Ltd.",
            "longname": "Samsung Electronics Co., Ltd.",
            "exchange": "KSC",
            "exchDisp": "Korea Stock Exchange",
            "quoteType": "EQUITY",
            "typeDisp": "Equity",
            "score": 20001.0,
        },
        {
            "symbol": "005935.KS",
            "shortname": "Samsung Electronics Co., Ltd. Pfd.",
            "exchange": "KSC",
            "quoteType": "EQUITY",
            "score": 19900.0,
        },
        {
            "symbol": "SAMSUNG-NEWS",
            "shortname": "Not a security",
            "quoteType": "NEWS",
        },
    ]


class FakeTicker:
    history_metadata = {
        "currency": "KRW",
        "exchangeName": "KSC",
        "instrumentType": "EQUITY",
        "timezone": "Asia/Seoul",
    }
    info = {
        "symbol": "005930.KS",
        "currency": "KRW",
        "marketCap": 400_000_000_000_000,
        "trailingPE": 18.5,
        "forwardPE": None,
        "priceToBook": 1.4,
        "enterpriseToEbitda": 7.2,
        "operatingMargins": 0.14,
        "freeCashflow": 18_000_000_000_000,
        "totalCash": 100_000_000_000_000,
        "totalDebt": 20_000_000_000_000,
        "dividendYield": 0.021,
    }

    def history(self, **_: object) -> pd.DataFrame:
        return pd.DataFrame(
            {"Close": [70000.0, 70500.0]},
            index=pd.to_datetime(["2026-08-06", "2026-08-07"]),
        )

    def get_news(self, count: int = 10, tab: str = "news") -> list[dict]:
        self.last_news_args = (count, tab)
        return [
            {
                "title": "Samsung Electronics announces results",
                "publisher": "Reuters",
                "link": "https://example.com/story",
                "providerPublishTime": 1_786_000_000,
            }
        ]


class YahooGatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gateway = YahooGateway(
            search_factory=lambda query, max_results=10: FakeSearch(),
            ticker_factory=lambda symbol: FakeTicker(),
            now=lambda: "2026-08-10T12:00:00+09:00",
        )

    def test_search_normalizes_candidates_without_semantic_selection(self) -> None:
        candidates = self.gateway.search("삼성전자", "stock", max_results=10)

        self.assertEqual([item["symbol"] for item in candidates], ["005930.KS", "005935.KS"])
        self.assertEqual(candidates[0]["quote_type"], "EQUITY")
        self.assertEqual(candidates[0]["exchange_display"], "Korea Stock Exchange")
        self.assertNotIn("selected", candidates[0])

    def test_search_classifies_yahoo_rate_limit_as_data_source_error(self) -> None:
        def rate_limited_search(query: str, max_results: int = 10) -> object:
            raise YFRateLimitError()

        gateway = YahooGateway(search_factory=rate_limited_search)

        with self.assertRaises(DataGateError) as raised:
            gateway.search("AAPL", "stock")

        self.assertEqual(raised.exception.code, "network_error")
        self.assertEqual(raised.exception.details["error_type"], "YFRateLimitError")
        self.assertTrue(raised.exception.details["rate_limited"])

    def test_validate_candidate_rejects_symbol_outside_returned_candidates(self) -> None:
        with self.assertRaisesRegex(DataGateError, "candidate_not_returned"):
            self.gateway.validate_candidate("AAPL", [{"symbol": "005930.KS"}])

    def test_validate_candidate_requires_usable_price_history(self) -> None:
        receipt = self.gateway.validate_candidate(
            "005930.KS",
            [{"symbol": "005930.KS", "quote_type": "EQUITY", "exchange": "KSC"}],
        )

        self.assertEqual(receipt["status"], "validated")
        self.assertEqual(receipt["currency"], "KRW")
        self.assertEqual(receipt["history_rows"], 2)
        self.assertTrue(receipt["repair_used"])
        self.assertEqual(receipt["validated_at"], "2026-08-10T12:00:00+09:00")

    def test_validate_candidate_records_repair_fallback(self) -> None:
        class RepairFallbackTicker(FakeTicker):
            def history(self, **kwargs: object) -> pd.DataFrame:
                if kwargs["repair"]:
                    raise ValueError("output array is read-only")
                return super().history(**kwargs)

        gateway = YahooGateway(
            ticker_factory=lambda symbol: RepairFallbackTicker(),
            now=lambda: "2026-08-10T12:00:00+09:00",
        )

        receipt = gateway.validate_candidate("7203.T", [{"symbol": "7203.T"}])

        self.assertFalse(receipt["repair_used"])
        self.assertEqual(receipt["repair_fallback_error_type"], "ValueError")

    def test_fundamentals_preserves_missing_fields(self) -> None:
        snapshot = self.gateway.fundamentals("005930.KS")

        self.assertEqual(snapshot["values"]["market_cap"], 400_000_000_000_000)
        self.assertIn("forward_pe", snapshot["missing_fields"])
        self.assertIsNone(snapshot["values"]["forward_pe"])

    def test_news_is_discovery_evidence_with_timestamp_and_source(self) -> None:
        items = self.gateway.news("005930.KS", count=3)

        self.assertEqual(items[0]["title"], "Samsung Electronics announces results")
        self.assertEqual(items[0]["publisher"], "Reuters")
        self.assertEqual(items[0]["source_role"], "discovery_only")
        self.assertEqual(items[0]["published_at"], "2026-08-06T07:06:40+00:00")


if __name__ == "__main__":
    unittest.main()
