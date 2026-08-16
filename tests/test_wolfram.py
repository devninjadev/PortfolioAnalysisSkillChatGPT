from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from advisor_data import DataGateError  # noqa: E402
from advisor_data.wolfram import normalize_wolfram_envelope  # noqa: E402


def observation(timestamp: str, value: object) -> dict[str, object]:
    return {"timestamp": timestamp, "value": value}


def financial_envelope(
    *,
    symbol: str = "AAPL",
    provider_entity: str = "NASDAQ:AAPL",
    property_name: str = "AdjustedClose",
    required_price_basis: str = "adjusted_total_return",
    currency: str = "USD",
    observations: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "provider": "wolfram",
        "evidence_kind": "financial_history",
        "symbol": symbol,
        "provider_entity": provider_entity,
        "requested_property": property_name,
        "required_price_basis": required_price_basis,
        "classification_evidence": {
            "yahoo_symbol": symbol,
            "expected_provider_currency": currency,
            "identity_decision": "match",
            "matched_fields": ["symbol", "security_type", "currency"],
            "conflicts": [],
        },
        "primary_failure": {
            "provider": "yahoo",
            "code": "price_history_unavailable",
            "message": "Yahoo returned no usable price history.",
        },
        "request": {"start": "2026-01-01", "end": "2026-02-01"},
        "result": {
            "entity_type": "Financial",
            "entity": provider_entity,
            "symbol": symbol,
            "exchange": "NASDAQ",
            "security_type": "Equity",
            "currency": currency,
            "property": property_name,
            "unit": "USDollars",
            "observations": observations,
        },
        "sources": [
            {"name": "Fixture Financial Source", "url": "https://example.invalid/source"}
        ],
        "retrieved_at": "2026-08-16T00:00:00+00:00",
    }


class WolframEnvelopeTests(unittest.TestCase):
    def test_adjusted_history_returns_named_currency_series(self) -> None:
        result = normalize_wolfram_envelope(
            financial_envelope(
                observations=[
                    observation("2026-01-05T00:00:00+00:00", 100.0),
                    observation("2026-01-12T00:00:00+00:00", 101.0),
                ]
            ),
            start="2026-01-01",
            end="2026-02-01",
        )

        self.assertEqual(result.series.name, "AAPL")
        self.assertEqual(result.currency, "USD")
        self.assertEqual(result.receipt["provider"], "wolfram")
        self.assertEqual(result.receipt["provider_entity"], "NASDAQ:AAPL")
        self.assertEqual(result.receipt["price_basis"], "provider_adjusted_total_return_close")
        self.assertEqual(result.receipt["observation_count"], 2)

    def test_recent_price_allows_one_latest_trade_observation(self) -> None:
        result = normalize_wolfram_envelope(
            financial_envelope(
                property_name="LatestTrade",
                required_price_basis="recent_price",
                observations=[observation("2026-01-12T20:00:00+00:00", 101.0)],
            ),
            start="2026-01-01",
            end="2026-02-01",
        )

        self.assertEqual(result.receipt["price_basis"], "latest_trade")
        self.assertEqual(len(result.series), 1)

    def test_total_return_rejects_unadjusted_close(self) -> None:
        with self.assertRaisesRegex(DataGateError, "wolfram_property_unavailable"):
            normalize_wolfram_envelope(
                financial_envelope(
                    property_name="Close",
                    observations=[
                        observation("2026-01-05T00:00:00+00:00", 100.0),
                        observation("2026-01-12T00:00:00+00:00", 101.0),
                    ],
                ),
                "2026-01-01",
                "2026-02-01",
            )

    def test_provider_entity_conflict_fails_closed(self) -> None:
        envelope = financial_envelope(
            observations=[
                observation("2026-01-05T00:00:00+00:00", 100.0),
                observation("2026-01-12T00:00:00+00:00", 101.0),
            ]
        )
        envelope["result"]["entity"] = "NASDAQ:MSFT"  # type: ignore[index]
        with self.assertRaisesRegex(DataGateError, "wolfram_entity_mismatch"):
            normalize_wolfram_envelope(envelope, "2026-01-01", None)

    def test_declared_identity_conflict_fails_closed(self) -> None:
        envelope = financial_envelope(
            observations=[
                observation("2026-01-05T00:00:00+00:00", 100.0),
                observation("2026-01-12T00:00:00+00:00", 101.0),
            ]
        )
        envelope["classification_evidence"]["conflicts"] = ["currency"]  # type: ignore[index]
        with self.assertRaisesRegex(DataGateError, "wolfram_entity_mismatch"):
            normalize_wolfram_envelope(envelope, "2026-01-01", None)

    def test_provider_currency_conflict_fails_closed(self) -> None:
        envelope = financial_envelope(
            observations=[
                observation("2026-01-05T00:00:00+00:00", 100.0),
                observation("2026-01-12T00:00:00+00:00", 101.0),
            ]
        )
        envelope["result"]["currency"] = "EUR"  # type: ignore[index]
        with self.assertRaisesRegex(DataGateError, "wolfram_entity_mismatch"):
            normalize_wolfram_envelope(envelope, "2026-01-01", None)

    def test_missing_source_metadata_is_rejected(self) -> None:
        envelope = financial_envelope(
            observations=[
                observation("2026-01-05T00:00:00+00:00", 100.0),
                observation("2026-01-12T00:00:00+00:00", 101.0),
            ]
        )
        envelope["sources"] = []
        with self.assertRaisesRegex(DataGateError, "wolfram_source_unavailable"):
            normalize_wolfram_envelope(envelope, "2026-01-01", None)

    def test_conflicting_duplicate_observation_is_rejected(self) -> None:
        with self.assertRaisesRegex(DataGateError, "wolfram_schema_error"):
            normalize_wolfram_envelope(
                financial_envelope(
                    observations=[
                        observation("2026-01-05T00:00:00+00:00", 100.0),
                        observation("2026-01-05T00:00:00+00:00", 101.0),
                    ]
                ),
                "2026-01-01",
                None,
            )

    def test_identical_duplicate_observation_is_collapsed_and_sorted(self) -> None:
        result = normalize_wolfram_envelope(
            financial_envelope(
                observations=[
                    observation("2026-01-12T00:00:00+00:00", 101.0),
                    observation("2026-01-05T00:00:00+00:00", 100.0),
                    observation("2026-01-05T00:00:00+00:00", 100.0),
                ]
            ),
            "2026-01-01",
            None,
        )
        self.assertEqual(len(result.series), 2)
        self.assertTrue(result.series.index.is_monotonic_increasing)

    def test_observations_are_normalized_to_utc(self) -> None:
        result = normalize_wolfram_envelope(
            financial_envelope(
                observations=[
                    observation("2026-01-05T09:00:00-05:00", 100.0),
                    observation("2026-01-12", 101.0),
                ]
            ),
            "2026-01-01",
            None,
        )
        self.assertEqual(str(result.series.index.tz), "UTC")
        self.assertEqual(result.series.index[0], pd.Timestamp("2026-01-05T14:00:00Z"))

    def test_unsafe_values_are_rejected(self) -> None:
        for value in (0.0, -1.0, float("nan"), float("inf"), "bad"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(DataGateError, "wolfram_schema_error"):
                    normalize_wolfram_envelope(
                        financial_envelope(
                            observations=[
                                observation("2026-01-05T00:00:00+00:00", value),
                                observation("2026-01-12T00:00:00+00:00", 101.0),
                            ]
                        ),
                        "2026-01-01",
                        None,
                    )

    def test_malformed_timestamp_is_rejected(self) -> None:
        with self.assertRaisesRegex(DataGateError, "wolfram_schema_error"):
            normalize_wolfram_envelope(
                financial_envelope(
                    observations=[
                        observation("not-a-timestamp", 100.0),
                        observation("2026-01-12T00:00:00+00:00", 101.0),
                    ]
                ),
                "2026-01-01",
                None,
            )

    def test_empty_history_is_rejected(self) -> None:
        with self.assertRaisesRegex(DataGateError, "wolfram_schema_error"):
            normalize_wolfram_envelope(
                financial_envelope(observations=[]), "2026-01-01", None
            )

    def test_single_observation_total_return_is_rejected(self) -> None:
        with self.assertRaisesRegex(DataGateError, "wolfram_schema_error"):
            normalize_wolfram_envelope(
                financial_envelope(
                    observations=[observation("2026-01-05T00:00:00+00:00", 100.0)]
                ),
                "2026-01-01",
                None,
            )

    def test_wrong_provider_is_rejected(self) -> None:
        envelope = financial_envelope(
            observations=[
                observation("2026-01-05T00:00:00+00:00", 100.0),
                observation("2026-01-12T00:00:00+00:00", 101.0),
            ]
        )
        envelope["provider"] = "yahoo"
        with self.assertRaisesRegex(DataGateError, "wolfram_schema_error"):
            normalize_wolfram_envelope(envelope, "2026-01-01", None)

    def test_wrong_evidence_kind_is_rejected(self) -> None:
        envelope = financial_envelope(
            observations=[
                observation("2026-01-05T00:00:00+00:00", 100.0),
                observation("2026-01-12T00:00:00+00:00", 101.0),
            ]
        )
        envelope["evidence_kind"] = "quote"
        with self.assertRaisesRegex(DataGateError, "wolfram_schema_error"):
            normalize_wolfram_envelope(envelope, "2026-01-01", None)

    def test_wrong_symbol_is_rejected(self) -> None:
        envelope = financial_envelope(
            observations=[
                observation("2026-01-05T00:00:00+00:00", 100.0),
                observation("2026-01-12T00:00:00+00:00", 101.0),
            ]
        )
        envelope["result"]["symbol"] = "MSFT"  # type: ignore[index]
        with self.assertRaisesRegex(DataGateError, "wolfram_entity_mismatch"):
            normalize_wolfram_envelope(envelope, "2026-01-01", None)

    def test_late_first_observation_records_clipped_start(self) -> None:
        result = normalize_wolfram_envelope(
            financial_envelope(
                observations=[
                    observation("2026-01-05T00:00:00+00:00", 100.0),
                    observation("2026-01-12T00:00:00+00:00", 101.0),
                ]
            ),
            "2026-01-01",
            "2026-01-13",
        )
        self.assertEqual(result.receipt["coverage_status"], "clipped_both")
        self.assertEqual(result.receipt["requested_range"], {"start": "2026-01-01", "end": "2026-01-13"})
        self.assertEqual(result.receipt["observed_range"], {"start": "2026-01-05T00:00:00+00:00", "end": "2026-01-12T00:00:00+00:00"})

    def test_coverage_can_be_clipped_at_both_ends(self) -> None:
        result = normalize_wolfram_envelope(
            financial_envelope(
                observations=[
                    observation("2026-01-05T00:00:00+00:00", 100.0),
                    observation("2026-01-12T00:00:00+00:00", 101.0),
                ]
            ),
            "2026-01-01",
            "2026-02-01",
        )
        self.assertEqual(result.receipt["coverage_status"], "clipped_both")

    def test_coverage_can_be_clipped_at_end_only(self) -> None:
        result = normalize_wolfram_envelope(
            financial_envelope(
                observations=[
                    observation("2026-01-01T00:00:00+00:00", 100.0),
                    observation("2026-01-12T00:00:00+00:00", 101.0),
                ]
            ),
            "2026-01-01",
            "2026-02-01",
        )
        self.assertEqual(result.receipt["coverage_status"], "clipped_end")

    def test_invalid_requested_range_is_rejected(self) -> None:
        with self.assertRaisesRegex(DataGateError, "wolfram_schema_error"):
            normalize_wolfram_envelope(
                financial_envelope(
                    observations=[
                        observation("2026-01-05T00:00:00+00:00", 100.0),
                        observation("2026-01-12T00:00:00+00:00", 101.0),
                    ]
                ),
                "2026-02-01",
                "2026-01-01",
            )


if __name__ == "__main__":
    unittest.main()
