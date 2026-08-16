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
    exchange: str = "NASDAQ",
    issuer: str = "Apple Inc.",
    security_type: str = "Equity",
    share_class: str = "CommonStock",
    unit_name: str | None = None,
    unit_currency: str | None = None,
    request_start: str = "2026-01-01",
    request_end: str | None = "2026-02-01",
    retrieved_at: str = "2026-08-16T00:00:00+00:00",
    observations: list[dict[str, object]],
) -> dict[str, object]:
    observed_identity = {
        "provider_entity": provider_entity,
        "symbol": symbol,
        "exchange": exchange,
        "issuer": issuer,
        "security_type": security_type,
        "share_class": share_class,
        "currency": currency,
    }
    return {
        "schema_version": 1,
        "provider": "wolfram",
        "evidence_kind": "financial_history",
        "symbol": symbol,
        "provider_entity": provider_entity,
        "requested_property": property_name,
        "required_price_basis": required_price_basis,
        "classification_evidence": {
            "yahoo_candidate": {
                "symbol": symbol,
                "exchange": exchange,
                "issuer": issuer,
                "security_type": security_type,
                "share_class": share_class,
                "currency": currency,
            },
            "wolfram_observed": observed_identity,
        },
        "primary_failure": {
            "provider": "yahoo",
            "code": "price_history_unavailable",
            "message": "Yahoo returned no usable price history.",
        },
        "request": {"start": request_start, "end": request_end},
        "result": {
            "entity_type": "Financial",
            "entity": provider_entity,
            "symbol": symbol,
            "exchange": exchange,
            "issuer": issuer,
            "security_type": security_type,
            "share_class": share_class,
            "currency": currency,
            "property": property_name,
            "unit": {
                "name": unit_name or ("Euros" if currency == "EUR" else "USDollars"),
                "canonical_currency": unit_currency or currency,
                "quantity_kind": "monetary",
            },
            "observations": observations,
        },
        "sources": [
            {"name": "Fixture Financial Source", "url": "https://example.invalid/source"}
        ],
        "retrieved_at": retrieved_at,
    }


class WolframEnvelopeTests(unittest.TestCase):
    def test_adjusted_history_returns_named_currency_series(self) -> None:
        result = normalize_wolfram_envelope(
            financial_envelope(
                request_end="2026-01-13",
                observations=[
                    observation("2026-01-05T00:00:00+00:00", 100.0),
                    observation("2026-01-12T00:00:00+00:00", 101.0),
                ]
            ),
            start="2026-01-01",
            end="2026-01-13",
        )

        self.assertEqual(result.series.name, "AAPL")
        self.assertEqual(result.currency, "USD")
        self.assertEqual(result.receipt["provider"], "wolfram")
        self.assertEqual(result.receipt["provider_entity"], "NASDAQ:AAPL")
        self.assertEqual(result.receipt["price_basis"], "provider_adjusted_total_return_close")
        self.assertEqual(result.receipt["unit"], "USDollars")
        self.assertEqual(result.receipt["observation_count"], 2)

    def test_recent_price_allows_one_latest_trade_observation(self) -> None:
        result = normalize_wolfram_envelope(
            financial_envelope(
                property_name="LatestTrade",
                required_price_basis="recent_price",
                request_end="2026-01-13",
                retrieved_at="2026-01-13T00:00:00+00:00",
                observations=[observation("2026-01-12T20:00:00+00:00", 101.0)],
            ),
            start="2026-01-01",
            end="2026-01-13",
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
            request_end=None,
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
            request_end=None,
            observations=[
                observation("2026-01-05T00:00:00+00:00", 100.0),
                observation("2026-01-12T00:00:00+00:00", 101.0),
            ]
        )
        envelope["classification_evidence"] = {"identity_decision": "match"}
        with self.assertRaisesRegex(DataGateError, "wolfram_entity_mismatch"):
            normalize_wolfram_envelope(envelope, "2026-01-01", None)

    def test_structured_identity_conflicts_fail_closed(self) -> None:
        for field, conflicting_value in (
            ("exchange", "NYSE"),
            ("issuer", "Microsoft Corporation"),
            ("security_type", "ETF"),
            ("share_class", "ADR"),
        ):
            with self.subTest(field=field):
                envelope = financial_envelope(
                    request_end=None,
                    observations=[
                        observation("2026-01-05T00:00:00+00:00", 100.0),
                        observation("2026-01-12T00:00:00+00:00", 101.0),
                    ],
                )
                envelope["classification_evidence"]["wolfram_observed"][field] = (  # type: ignore[index]
                    conflicting_value
                )
                envelope["result"][field] = conflicting_value  # type: ignore[index]
                with self.assertRaisesRegex(DataGateError, "wolfram_entity_mismatch"):
                    normalize_wolfram_envelope(envelope, "2026-01-01", None)

    def test_missing_required_structured_identity_is_rejected(self) -> None:
        envelope = financial_envelope(
            request_end=None,
            observations=[
                observation("2026-01-05T00:00:00+00:00", 100.0),
                observation("2026-01-12T00:00:00+00:00", 101.0),
            ],
        )
        del envelope["classification_evidence"]["yahoo_candidate"]["issuer"]  # type: ignore[index]
        with self.assertRaisesRegex(DataGateError, "wolfram_entity_mismatch"):
            normalize_wolfram_envelope(envelope, "2026-01-01", None)

    def test_provider_currency_conflict_fails_closed(self) -> None:
        envelope = financial_envelope(
            request_end=None,
            observations=[
                observation("2026-01-05T00:00:00+00:00", 100.0),
                observation("2026-01-12T00:00:00+00:00", 101.0),
            ]
        )
        envelope["result"]["currency"] = "EUR"  # type: ignore[index]
        with self.assertRaisesRegex(DataGateError, "wolfram_entity_mismatch"):
            normalize_wolfram_envelope(envelope, "2026-01-01", None)

    def test_unit_currency_conflict_and_malformed_units_are_rejected(self) -> None:
        conflict = financial_envelope(
            currency="USD",
            unit_name="Euros",
            unit_currency="EUR",
            request_end=None,
            observations=[
                observation("2026-01-05T00:00:00+00:00", 100.0),
                observation("2026-01-12T00:00:00+00:00", 101.0),
            ],
        )
        with self.assertRaisesRegex(DataGateError, "wolfram_unit_mismatch"):
            normalize_wolfram_envelope(conflict, "2026-01-01", None)

        malformed = financial_envelope(
            request_end=None,
            observations=[
                observation("2026-01-05T00:00:00+00:00", 100.0),
                observation("2026-01-12T00:00:00+00:00", 101.0),
            ],
        )
        malformed["result"]["unit"] = "USDollars"  # type: ignore[index]
        with self.assertRaisesRegex(DataGateError, "wolfram_unit_mismatch"):
            normalize_wolfram_envelope(malformed, "2026-01-01", None)

        unrecognized = financial_envelope(
            unit_name="Dollars",
            request_end=None,
            observations=[
                observation("2026-01-05T00:00:00+00:00", 100.0),
                observation("2026-01-12T00:00:00+00:00", 101.0),
            ],
        )
        with self.assertRaisesRegex(DataGateError, "wolfram_unit_mismatch"):
            normalize_wolfram_envelope(unrecognized, "2026-01-01", None)

    def test_missing_source_metadata_is_rejected(self) -> None:
        envelope = financial_envelope(
            request_end=None,
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
                    request_end=None,
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
                request_end=None,
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
                request_end=None,
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
                            request_end=None,
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
                    request_end=None,
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
                financial_envelope(request_end=None, observations=[]), "2026-01-01", None
            )

    def test_single_observation_total_return_is_rejected(self) -> None:
        with self.assertRaisesRegex(DataGateError, "wolfram_schema_error"):
            normalize_wolfram_envelope(
                financial_envelope(
                    request_end=None,
                    observations=[observation("2026-01-05T00:00:00+00:00", 100.0)]
                ),
                "2026-01-01",
                None,
            )

    def test_wrong_provider_is_rejected(self) -> None:
        envelope = financial_envelope(
            request_end=None,
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
            request_end=None,
            observations=[
                observation("2026-01-05T00:00:00+00:00", 100.0),
                observation("2026-01-12T00:00:00+00:00", 101.0),
            ]
        )
        envelope["result"]["symbol"] = "MSFT"  # type: ignore[index]
        with self.assertRaisesRegex(DataGateError, "wolfram_entity_mismatch"):
            normalize_wolfram_envelope(envelope, "2026-01-01", None)

    def test_envelope_request_range_must_match_cli_range(self) -> None:
        envelope = financial_envelope(
            request_start="2026-01-02",
            request_end="2026-01-13",
            observations=[
                observation("2026-01-05T00:00:00+00:00", 100.0),
                observation("2026-01-12T00:00:00+00:00", 101.0),
            ],
        )
        with self.assertRaisesRegex(DataGateError, "wolfram_request_mismatch"):
            normalize_wolfram_envelope(envelope, "2026-01-01", "2026-01-13")

    def test_materially_clipped_adjusted_history_is_rejected(self) -> None:
        envelope = financial_envelope(
            request_start="2026-01-01",
            request_end="2026-03-01",
            observations=[
                observation("2026-02-02T00:00:00+00:00", 100.0),
                observation("2026-02-20T00:00:00+00:00", 101.0),
            ],
        )
        with self.assertRaisesRegex(DataGateError, "wolfram_history_incomplete"):
            normalize_wolfram_envelope(envelope, "2026-01-01", "2026-03-01")

    def test_weekend_and_holiday_endpoint_tolerance_is_accepted(self) -> None:
        result = normalize_wolfram_envelope(
            financial_envelope(
                request_start="2026-01-03",
                request_end="2026-01-12",
                observations=[
                    observation("2026-01-05T00:00:00+00:00", 100.0),
                    observation("2026-01-09T00:00:00+00:00", 101.0),
                ],
            ),
            "2026-01-03",
            "2026-01-12",
        )
        self.assertEqual(result.receipt["coverage_status"], "endpoint_tolerated")
        self.assertEqual(result.receipt["endpoint_tolerance_days"], 7)

    def test_open_ended_adjusted_history_checks_only_start_endpoint(self) -> None:
        result = normalize_wolfram_envelope(
            financial_envelope(
                request_start="2026-01-03",
                request_end=None,
                observations=[
                    observation("2026-01-05T00:00:00+00:00", 100.0),
                    observation("2026-08-14T00:00:00+00:00", 151.0),
                ],
            ),
            "2026-01-03",
            None,
        )
        self.assertEqual(result.receipt["requested_range"]["end"], None)
        self.assertEqual(result.receipt["coverage_status"], "endpoint_tolerated")

    def test_open_ended_adjusted_history_rejects_only_pre_window_observations(
        self,
    ) -> None:
        envelope = financial_envelope(
            request_start="2026-01-03",
            request_end=None,
            observations=[
                observation("2025-12-22T00:00:00+00:00", 98.0),
                observation("2025-12-29T00:00:00+00:00", 99.0),
            ],
        )

        with self.assertRaisesRegex(DataGateError, "wolfram_history_incomplete"):
            normalize_wolfram_envelope(envelope, "2026-01-03", None)

    def test_recent_price_uses_separate_freshness_gate(self) -> None:
        stale = financial_envelope(
            property_name="LatestTrade",
            required_price_basis="recent_price",
            request_start="2026-01-01",
            request_end="2026-02-01",
            retrieved_at="2026-02-02T00:00:00+00:00",
            observations=[observation("2026-01-12T20:00:00+00:00", 101.0)],
        )
        with self.assertRaisesRegex(DataGateError, "wolfram_recent_price_stale"):
            normalize_wolfram_envelope(stale, "2026-01-01", "2026-02-01")

    def test_invalid_requested_range_is_rejected(self) -> None:
        with self.assertRaisesRegex(DataGateError, "wolfram_schema_error"):
            normalize_wolfram_envelope(
                financial_envelope(
                    request_start="2026-02-01",
                    request_end="2026-01-01",
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
