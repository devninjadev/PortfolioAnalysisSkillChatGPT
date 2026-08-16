from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from advisor_data import DataGateError  # noqa: E402
from advisor_data.treasury import normalize_treasury_envelope  # noqa: E402


def treasury_observation(timestamp: str, value: float) -> dict[str, object]:
    return {"timestamp": timestamp, "value": value}


def treasury_envelope(
    *,
    evidence_kind: str = "us_treasury_history",
    security_type: str = "Note",
    maturity_duration: str = "10Year",
    maturity_years: float = 10.0,
    market: str | None = None,
    due_date: str | None = "ConstantMaturity",
    frequency: str = "Daily",
    time_series_operator: str | None = None,
    coupon_rate: float | None = None,
    observations: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "provider": "wolfram",
        "evidence_kind": evidence_kind,
        "country_entity": "UnitedStates",
        "qualifiers": {
            "security_type": security_type,
            "maturity_duration": maturity_duration,
            "market": market,
            "due_date": due_date,
            "frequency": frequency,
            "time_series_operator": time_series_operator,
            "coupon_rate": coupon_rate,
        },
        "request": {"start": "2025-01-01", "end": "2026-08-13"},
        "result": {
            "property": "Treasury",
            "maturity_years": maturity_years,
            "unit": "Percent",
            "observations": observations,
            "missing": [],
        },
        "sources": [
            {
                "name": "FRED (Federal Reserve Economic Data)",
                "organization": "Federal Reserve Bank of St. Louis",
                "url": "https://fred.stlouisfed.org/",
            }
        ],
        "retrieved_at": "2026-08-16T00:00:00+00:00",
    }


class TreasuryEnvelopeTests(unittest.TestCase):
    def test_nominal_constant_maturity_history_preserves_qualifiers(self) -> None:
        result = normalize_treasury_envelope(
            treasury_envelope(
                observations=[
                    treasury_observation("2026-08-12T00:00:00+00:00", 4.55),
                    treasury_observation("2026-08-13T00:00:00+00:00", 4.63),
                ]
            )
        )

        self.assertEqual(result.maturity_years, 10.0)
        self.assertEqual(result.series.tolist(), [4.55, 4.63])
        self.assertEqual(result.receipt["unit"], "Percent")
        self.assertEqual(result.receipt["qualifiers"]["security_type"], "Note")
        self.assertEqual(result.receipt["source_names"], ["FRED (Federal Reserve Economic Data)"])

    def test_tips_and_negative_yields_are_valid(self) -> None:
        result = normalize_treasury_envelope(
            treasury_envelope(
                security_type="TIPS",
                maturity_duration="5Year",
                maturity_years=5.0,
                observations=[
                    treasury_observation("2020-01-02T00:00:00+00:00", -0.10),
                    treasury_observation("2020-01-03T00:00:00+00:00", -0.08),
                ],
            )
        )

        self.assertEqual(result.series.iloc[0], -0.10)
        self.assertEqual(result.receipt["qualifiers"]["security_type"], "TIPS")

    def test_auction_and_secondary_market_qualifiers_are_accepted(self) -> None:
        for market in ("AuctionAverage", "SecondaryMarket"):
            with self.subTest(market=market):
                result = normalize_treasury_envelope(
                    treasury_envelope(
                        security_type="Bill",
                        maturity_duration="3Month",
                        maturity_years=0.25,
                        market=market,
                        due_date=None,
                        frequency="Weekly" if market == "AuctionAverage" else "Daily",
                        observations=[
                            treasury_observation("2026-08-06T00:00:00+00:00", 3.70),
                            treasury_observation("2026-08-13T00:00:00+00:00", 3.71),
                        ],
                    )
                )
                self.assertEqual(result.receipt["qualifiers"]["market"], market)

    def test_requested_and_observed_qualifiers_must_agree(self) -> None:
        envelope = treasury_envelope(
            observations=[
                treasury_observation("2026-08-12", 4.55),
                treasury_observation("2026-08-13", 4.63),
            ]
        )
        envelope["request"]["qualifiers"] = dict(envelope["qualifiers"])
        envelope["result"]["qualifiers"] = dict(envelope["qualifiers"])
        envelope["result"]["qualifiers"]["maturity_duration"] = "5Year"
        with self.assertRaisesRegex(DataGateError, "wolfram_qualifier_mismatch"):
            normalize_treasury_envelope(envelope)

    def test_unavailable_series_stays_unavailable(self) -> None:
        envelope = treasury_envelope(observations=[])
        envelope["result"]["missing"] = [
            {"reason": "NotAvailable", "maturity_duration": "2Month"}
        ]
        with self.assertRaisesRegex(DataGateError, "treasury_maturity_unavailable"):
            normalize_treasury_envelope(envelope)

    def test_empty_history_without_maturity_marker_is_unavailable(self) -> None:
        envelope = treasury_envelope(observations=[])
        envelope["result"]["missing"] = [{"reason": "NotAvailable"}]
        with self.assertRaisesRegex(DataGateError, "treasury_series_unavailable"):
            normalize_treasury_envelope(envelope)

    def test_non_percent_unit_is_rejected(self) -> None:
        envelope = treasury_envelope(
            observations=[
                treasury_observation("2026-08-12T00:00:00+00:00", 4.55),
                treasury_observation("2026-08-13T00:00:00+00:00", 4.63),
            ]
        )
        envelope["result"]["unit"] = "BasisPoints"
        with self.assertRaisesRegex(DataGateError, "wolfram_unit_mismatch"):
            normalize_treasury_envelope(envelope)

    def test_conflicting_duplicate_yields_are_rejected(self) -> None:
        with self.assertRaisesRegex(DataGateError, "wolfram_schema_error"):
            normalize_treasury_envelope(
                treasury_envelope(
                    observations=[
                        treasury_observation("2026-08-13T00:00:00+00:00", 4.60),
                        treasury_observation("2026-08-13T00:00:00+00:00", 4.63),
                    ]
                )
            )

    def test_identical_duplicate_yields_are_collapsed_and_timestamps_are_utc(self) -> None:
        result = normalize_treasury_envelope(
            treasury_envelope(
                observations=[
                    treasury_observation("2026-08-12T09:00:00+09:00", 4.55),
                    treasury_observation("2026-08-12T00:00:00Z", 4.55),
                    treasury_observation("2026-08-13", 4.63),
                ]
            )
        )
        self.assertEqual(len(result.series), 2)
        self.assertEqual(str(result.series.index.tz), "UTC")

    def test_current_series_accepts_one_observation(self) -> None:
        result = normalize_treasury_envelope(
            treasury_envelope(
                evidence_kind="us_treasury_current",
                observations=[treasury_observation("2026-08-13", 4.63)],
            )
        )
        self.assertEqual(len(result.series), 1)

    def test_supported_qualifier_values_and_arbitrary_maturity(self) -> None:
        for security_type in ("Bill", "Note", "Bond", "TIPS"):
            with self.subTest(security_type=security_type):
                result = normalize_treasury_envelope(
                    treasury_envelope(
                        security_type=security_type,
                        maturity_duration="Custom1.5Year",
                        maturity_years=1.5,
                        coupon_rate=0.5,
                        observations=[
                            treasury_observation("2026-08-12", 4.55),
                            treasury_observation("2026-08-13", 4.63),
                        ],
                    )
                )
                self.assertEqual(result.maturity_years, 1.5)

        for frequency in ("Daily", "Weekly", "BiWeekly", "Monthly", "Quarterly", "Annual"):
            with self.subTest(frequency=frequency):
                result = normalize_treasury_envelope(
                    treasury_envelope(
                        frequency=frequency,
                        observations=[
                            treasury_observation("2026-08-12", 4.55),
                            treasury_observation("2026-08-13", 4.63),
                        ],
                    )
                )
                self.assertEqual(result.receipt["qualifiers"]["frequency"], frequency)

        for operator in (
            "Change",
            "ChangeRate",
            "AnnualChange",
            "AnnualizedChangeRate",
            "YearOverYearChangeRate",
        ):
            with self.subTest(time_series_operator=operator):
                result = normalize_treasury_envelope(
                    treasury_envelope(
                        time_series_operator=operator,
                        observations=[
                            treasury_observation("2026-08-12", 4.55),
                            treasury_observation("2026-08-13", 4.63),
                        ],
                    )
                )
                self.assertEqual(
                    result.receipt["qualifiers"]["time_series_operator"], operator
                )

    def test_finite_coupon_rate_is_preserved(self) -> None:
        envelope = treasury_envelope(
            observations=[
                treasury_observation("2026-08-12", 4.55),
                treasury_observation("2026-08-13", 4.63),
            ]
        )
        envelope["qualifiers"]["coupon_rate"] = 2.875
        result = normalize_treasury_envelope(envelope)
        self.assertEqual(result.receipt["qualifiers"]["coupon_rate"], 2.875)

    def test_invalid_values_are_rejected(self) -> None:
        cases: list[tuple[str, object, str]] = [
            ("coupon_rate", math.inf, "wolfram_schema_error"),
            ("security_type", "ZeroCoupon", "wolfram_schema_error"),
            ("market", "PrimaryMarket", "wolfram_schema_error"),
            ("frequency", "Hourly", "wolfram_schema_error"),
        ]
        for field, value, code in cases:
            with self.subTest(field=field):
                envelope = treasury_envelope(
                    observations=[
                        treasury_observation("2026-08-12", 4.55),
                        treasury_observation("2026-08-13", 4.63),
                    ]
                )
                envelope["qualifiers"][field] = value
                with self.assertRaisesRegex(DataGateError, code):
                    normalize_treasury_envelope(envelope)

    def test_nonfinite_yield_malformed_timestamp_missing_source_and_country_fail(self) -> None:
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                with self.assertRaisesRegex(DataGateError, "wolfram_schema_error"):
                    normalize_treasury_envelope(
                        treasury_envelope(
                            observations=[
                                treasury_observation("2026-08-12", value),
                                treasury_observation("2026-08-13", 4.63),
                            ]
                        )
                    )

        with self.assertRaisesRegex(DataGateError, "wolfram_schema_error"):
            normalize_treasury_envelope(
                treasury_envelope(
                    observations=[
                        treasury_observation("not-a-date", 4.55),
                        treasury_observation("2026-08-13", 4.63),
                    ]
                )
            )

        envelope = treasury_envelope(
            observations=[
                treasury_observation("2026-08-12", 4.55),
                treasury_observation("2026-08-13", 4.63),
            ]
        )
        envelope["sources"] = []
        with self.assertRaisesRegex(DataGateError, "wolfram_source_unavailable"):
            normalize_treasury_envelope(envelope)

        envelope = treasury_envelope(
            observations=[
                treasury_observation("2026-08-12", 4.55),
                treasury_observation("2026-08-13", 4.63),
            ]
        )
        envelope["country_entity"] = "Canada"
        with self.assertRaisesRegex(DataGateError, "wolfram_entity_mismatch"):
            normalize_treasury_envelope(envelope)


if __name__ == "__main__":
    unittest.main()
