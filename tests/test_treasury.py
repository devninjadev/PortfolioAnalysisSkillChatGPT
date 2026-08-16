from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

import pandas as pd


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from advisor_data import DataGateError  # noqa: E402
from advisor_data.treasury import (  # noqa: E402
    align_periodic_risk_free,
    build_historical_yield_curve,
    build_yield_curve,
    normalize_treasury_envelope,
)


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
    qualifiers = {
        "security_type": security_type,
        "maturity_duration": maturity_duration,
        "market": market,
        "due_date": due_date,
        "frequency": frequency,
        "time_series_operator": time_series_operator,
        "coupon_rate": coupon_rate,
    }
    return {
        "schema_version": 1,
        "provider": "wolfram",
        "evidence_kind": evidence_kind,
        "country_entity": "UnitedStates",
        "qualifiers": qualifiers,
        "request": {
            "start": "2025-01-01",
            "end": "2026-08-13",
            "requested_qualifiers": dict(qualifiers),
            "requested_maturity": {
                "duration": maturity_duration,
                "years": maturity_years,
                "unit": "years",
                "evidence_kind": "classifier_typed_request",
            },
        },
        "result": {
            "property": "Treasury",
            "maturity_years": maturity_years,
            "observed_qualifiers": dict(qualifiers),
            "observed_maturity": {
                "duration": maturity_duration,
                "years": maturity_years,
                "unit": "years",
                "evidence_kind": "provider_observed_typed",
            },
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


def treasury_series_for_curve(maturity_years: float, value: float):
    security_type = "Bill" if maturity_years < 1.0 else "Note"
    maturity_duration = "3Month" if maturity_years == 0.25 else f"{int(maturity_years)}Year"
    return normalize_treasury_envelope(
        treasury_envelope(
            security_type=security_type,
            maturity_duration=maturity_duration,
            maturity_years=maturity_years,
            observations=[treasury_observation("2026-08-13T00:00:00+00:00", value)],
            evidence_kind="us_treasury_current",
        )
    )


def inferred_treasury_envelope(
    *,
    evidence_kind: str = "us_treasury_history",
    maturity_duration: str = "10Year",
    maturity_years: float = 10.0,
    observations: list[dict[str, object]],
) -> dict[str, object]:
    envelope = treasury_envelope(
        evidence_kind=evidence_kind,
        maturity_duration=maturity_duration,
        maturity_years=maturity_years,
        observations=observations,
    )
    envelope["evidence_tier"] = "provider_labeled_inferred"
    envelope["result"].pop("observed_qualifiers")
    envelope["result"].pop("observed_maturity")
    envelope["result"].pop("maturity_years")
    envelope["exact_qualifier_failure"] = {
        "status": "unavailable",
        "query": f'exact Wolfram Treasury qualifiers for {maturity_duration}',
        "requested_maturity_years": maturity_years,
        "missing": [
            {
                "maturity_duration": maturity_duration,
                "value": "Missing[NotAvailable]",
            }
        ],
    }
    binding_evidence: dict[str, object] = {
        "channel": (
            "official_plugin_labeled_result"
            if evidence_kind == "us_treasury_current"
            else "official_plugin_input_interpretation"
        ),
        "query": f"U.S. Treasury {maturity_duration} yield",
        "input_interpretation": f"United States Treasury {maturity_duration} Note yield",
        "displayed_label": f"{maturity_duration} note",
    }
    if evidence_kind == "us_treasury_current":
        binding_evidence["observation_date"] = observations[0]["timestamp"]
    else:
        binding_evidence["observation_date_range"] = {
            "start": observations[0]["timestamp"],
            "end": observations[-1]["timestamp"],
        }
    envelope["binding_evidence"] = binding_evidence
    envelope["binding_decision"] = {
        "decision_kind": "structured_llm_semantic_binding",
        "requested_maturity_years": maturity_years,
        "bound_maturity_years": maturity_years,
        "maturity_match": True,
        "conflicts": [],
    }
    envelope["sources"] = [
        {
            "name": "Wolfram official plugin",
            "role": "official_plugin_tool",
            "underlying_source_annotation": None,
        }
    ]
    return envelope


def inferred_treasury_series_for_curve(maturity_years: float, value: float):
    maturity_duration = "3Month" if maturity_years == 0.25 else f"{int(maturity_years)}Year"
    return normalize_treasury_envelope(
        inferred_treasury_envelope(
            evidence_kind="us_treasury_current",
            maturity_duration=maturity_duration,
            maturity_years=maturity_years,
            observations=[treasury_observation("2026-08-13", value)],
        )
    )


class TreasuryEnvelopeTests(unittest.TestCase):
    def test_labeled_current_treasury_is_usable_at_lower_confidence(self) -> None:
        result = normalize_treasury_envelope(
            inferred_treasury_envelope(
                evidence_kind="us_treasury_current",
                observations=[treasury_observation("2026-08-13", 4.63)],
            )
        )

        self.assertEqual(result.maturity_years, 10.0)
        self.assertEqual(result.series.tolist(), [4.63])
        self.assertEqual(result.receipt["evidence_tier"], "provider_labeled_inferred")
        self.assertEqual(result.receipt["evidence_confidence"], "lower")
        self.assertEqual(
            result.receipt["maturity_binding"],
            "provider_labeled_or_semantically_inferred",
        )
        self.assertEqual(result.receipt["exact_qualifier_status"], "unavailable")

    def test_interpreted_historical_treasury_is_usable_at_lower_confidence(self) -> None:
        result = normalize_treasury_envelope(
            inferred_treasury_envelope(
                observations=[
                    treasury_observation("2026-08-12", 4.55),
                    treasury_observation("2026-08-13", 4.63),
                ]
            )
        )

        self.assertEqual(result.series.tolist(), [4.55, 4.63])
        self.assertEqual(result.receipt["evidence_confidence"], "lower")
        self.assertEqual(
            result.receipt["binding_evidence"]["channel"],
            "official_plugin_input_interpretation",
        )
        self.assertEqual(result.receipt["exact_qualifier_failure"]["status"], "unavailable")

    def test_lower_tier_rejects_missing_exact_failure_label_or_date_binding(self) -> None:
        mutations = (
            lambda envelope: envelope.pop("exact_qualifier_failure"),
            lambda envelope: (
                envelope["binding_evidence"].update({"displayed_label": None}),
                envelope["binding_evidence"].update({"input_interpretation": None}),
            ),
            lambda envelope: envelope["binding_evidence"].pop("observation_date"),
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                envelope = inferred_treasury_envelope(
                    evidence_kind="us_treasury_current",
                    observations=[treasury_observation("2026-08-13", 4.63)],
                )
                mutate(envelope)
                with self.assertRaisesRegex(DataGateError, "treasury_binding_unavailable"):
                    normalize_treasury_envelope(envelope)

    def test_lower_tier_rejects_maturity_conflict_and_unsupported_channel(self) -> None:
        conflict = inferred_treasury_envelope(
            observations=[
                treasury_observation("2026-08-12", 4.55),
                treasury_observation("2026-08-13", 4.63),
            ]
        )
        conflict["binding_decision"]["bound_maturity_years"] = 2.0
        conflict["binding_decision"]["maturity_match"] = False
        conflict["binding_decision"]["conflicts"] = ["displayed maturity is 2 years"]
        with self.assertRaisesRegex(DataGateError, "treasury_binding_unavailable"):
            normalize_treasury_envelope(conflict)

        unsupported = inferred_treasury_envelope(
            evidence_kind="us_treasury_current",
            observations=[treasury_observation("2026-08-13", 4.63)],
        )
        unsupported["binding_evidence"]["channel"] = "webpage_scrape"
        with self.assertRaisesRegex(DataGateError, "treasury_binding_unavailable"):
            normalize_treasury_envelope(unsupported)

    def test_lower_tier_rejects_exact_failure_for_a_different_maturity(self) -> None:
        envelope = inferred_treasury_envelope(
            evidence_kind="us_treasury_current",
            observations=[treasury_observation("2026-08-13", 4.63)],
        )
        envelope["exact_qualifier_failure"]["requested_maturity_years"] = 2.0

        with self.assertRaisesRegex(DataGateError, "treasury_binding_unavailable"):
            normalize_treasury_envelope(envelope)

    def test_lower_tier_rejects_non_percent_and_unlabeled_numeric_result(self) -> None:
        wrong_unit = inferred_treasury_envelope(
            evidence_kind="us_treasury_current",
            observations=[treasury_observation("2026-08-13", 4.63)],
        )
        wrong_unit["result"]["unit"] = "BasisPoints"
        with self.assertRaisesRegex(DataGateError, "wolfram_unit_mismatch"):
            normalize_treasury_envelope(wrong_unit)

        unlabeled = inferred_treasury_envelope(
            evidence_kind="us_treasury_current",
            observations=[treasury_observation("2026-08-13", 4.63)],
        )
        unlabeled["binding_evidence"]["displayed_label"] = None
        unlabeled["binding_evidence"]["input_interpretation"] = None
        with self.assertRaisesRegex(DataGateError, "treasury_binding_unavailable"):
            normalize_treasury_envelope(unlabeled)

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
        self.assertEqual(result.receipt["evidence_tier"], "provider_confirmed")
        self.assertEqual(result.receipt["evidence_confidence"], "high")

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
        envelope["result"]["observed_qualifiers"]["frequency"] = "Weekly"
        with self.assertRaisesRegex(DataGateError, "wolfram_qualifier_mismatch"):
            normalize_treasury_envelope(envelope)

    def test_success_requires_complete_requested_and_observed_qualifier_echoes(self) -> None:
        for location, key in (
            (("request",), "requested_qualifiers"),
            (("result",), "observed_qualifiers"),
        ):
            with self.subTest(key=key):
                envelope = treasury_envelope(
                    observations=[
                        treasury_observation("2026-08-12", 4.55),
                        treasury_observation("2026-08-13", 4.63),
                    ]
                )
                del envelope[location[0]][key]
                with self.assertRaisesRegex(DataGateError, "wolfram_qualifier_mismatch"):
                    normalize_treasury_envelope(envelope)

        envelope = treasury_envelope(
            observations=[
                treasury_observation("2026-08-12", 4.55),
                treasury_observation("2026-08-13", 4.63),
            ]
        )
        del envelope["result"]["observed_qualifiers"]["coupon_rate"]
        with self.assertRaisesRegex(DataGateError, "wolfram_qualifier_mismatch"):
            normalize_treasury_envelope(envelope)

    def test_success_requires_provider_typed_numeric_maturity_evidence(self) -> None:
        envelope = treasury_envelope(
            observations=[
                treasury_observation("2026-08-12", 4.55),
                treasury_observation("2026-08-13", 4.63),
            ]
        )
        del envelope["result"]["observed_maturity"]
        with self.assertRaisesRegex(DataGateError, "treasury_maturity_mismatch"):
            normalize_treasury_envelope(envelope)

    def test_typed_requested_and_observed_maturity_must_agree_numerically(self) -> None:
        envelope = treasury_envelope(
            observations=[
                treasury_observation("2026-08-12", 4.55),
                treasury_observation("2026-08-13", 4.63),
            ]
        )
        envelope["result"]["maturity_years"] = 2.0
        envelope["result"]["observed_maturity"]["years"] = 2.0
        with self.assertRaisesRegex(DataGateError, "treasury_maturity_mismatch"):
            normalize_treasury_envelope(envelope)

    def test_unavailable_missing_envelope_need_not_claim_observed_qualifiers(self) -> None:
        envelope = treasury_envelope(observations=[])
        envelope["result"]["missing"] = [
            {"reason": "NotAvailable", "maturity_duration": "10Year"}
        ]
        del envelope["result"]["observed_qualifiers"]
        del envelope["result"]["observed_maturity"]
        del envelope["result"]["maturity_years"]
        with self.assertRaisesRegex(DataGateError, "treasury_maturity_unavailable"):
            normalize_treasury_envelope(envelope)

    def test_unavailable_series_stays_unavailable(self) -> None:
        envelope = treasury_envelope(observations=[])
        envelope["result"]["missing"] = [
            {"reason": "NotAvailable", "maturity_duration": "2Month"}
        ]
        with self.assertRaisesRegex(DataGateError, "treasury_series_unavailable"):
            normalize_treasury_envelope(envelope)

    def test_requested_maturity_marker_is_maturity_unavailable(self) -> None:
        envelope = treasury_envelope(observations=[])
        envelope["result"]["missing"] = [
            {"reason": "NotAvailable", "maturity_duration": "10Year"}
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
            coupon_rate=2.875,
            observations=[
                treasury_observation("2026-08-12", 4.55),
                treasury_observation("2026-08-13", 4.63),
            ]
        )
        result = normalize_treasury_envelope(envelope)
        self.assertEqual(result.receipt["qualifiers"]["coupon_rate"], 2.875)

    def test_numeric_strings_are_rejected_for_maturity_yield_and_coupon(self) -> None:
        maturity_envelope = treasury_envelope(
            observations=[
                treasury_observation("2026-08-12", 4.55),
                treasury_observation("2026-08-13", 4.63),
            ]
        )
        maturity_envelope["result"]["maturity_years"] = "10.0"
        with self.assertRaisesRegex(DataGateError, "treasury_maturity_mismatch"):
            normalize_treasury_envelope(maturity_envelope)

        yield_envelope = treasury_envelope(
            observations=[
                treasury_observation("2026-08-12", "4.55"),
                treasury_observation("2026-08-13", 4.63),
            ]
        )
        with self.assertRaisesRegex(DataGateError, "wolfram_schema_error"):
            normalize_treasury_envelope(yield_envelope)

        coupon_envelope = treasury_envelope(
            coupon_rate="2.875",  # type: ignore[arg-type]
            observations=[
                treasury_observation("2026-08-12", 4.55),
                treasury_observation("2026-08-13", 4.63),
            ]
        )
        with self.assertRaisesRegex(DataGateError, "wolfram_schema_error"):
            normalize_treasury_envelope(coupon_envelope)

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


class YieldCurveTests(unittest.TestCase):
    def test_curve_and_interpolation_inherit_weakest_treasury_confidence(self) -> None:
        result = build_yield_curve(
            {
                2.0: treasury_series_for_curve(2.0, 4.0),
                10.0: inferred_treasury_series_for_curve(10.0, 5.0),
            },
            observation_date="2026-08-13",
            requested_maturities=[2.0, 5.0, 10.0],
            interpolate=True,
        )

        self.assertEqual(result.observed[0]["evidence_confidence"], "high")
        self.assertEqual(result.observed[1]["evidence_confidence"], "lower")
        self.assertEqual(result.calculated[0]["evidence_confidence"], "lower")
        self.assertEqual(
            result.calculated[0]["supporting_evidence_tiers"],
            ["provider_confirmed", "provider_labeled_inferred"],
        )
        self.assertEqual(result.receipt["evidence_confidence"], "lower")
        self.assertEqual(
            result.receipt["evidence_by_maturity"][10.0]["evidence_tier"],
            "provider_labeled_inferred",
        )

    def test_curve_separates_observed_and_missing_points(self) -> None:
        result = build_yield_curve(
            {
                0.25: treasury_series_for_curve(0.25, 3.87),
                2.0: treasury_series_for_curve(2.0, 4.15),
                10.0: treasury_series_for_curve(10.0, 4.63),
            },
            observation_date="2026-08-13",
            requested_maturities=[0.25, 1.0, 2.0, 10.0],
        )

        self.assertEqual(
            [point["maturity_years"] for point in result.observed], [0.25, 2.0, 10.0]
        )
        self.assertEqual(result.missing, [{"maturity_years": 1.0, "reason": "not_observed"}])
        self.assertEqual(result.calculated, [])
        self.assertEqual(result.receipt["observation_date"], "2026-08-13T00:00:00+00:00")

    def test_curve_observation_preserves_its_evidence_metadata(self) -> None:
        result = build_yield_curve(
            {0.25: treasury_series_for_curve(0.25, 3.87)},
            observation_date="2026-08-13",
            requested_maturities=[0.25],
        )

        point = result.observed[0]
        self.assertEqual(point["observation_date"], "2026-08-13T00:00:00+00:00")
        self.assertEqual(point["unit"], "Percent")
        self.assertEqual(point["qualifiers"]["maturity_duration"], "3Month")
        self.assertEqual(point["source_names"], ["FRED (Federal Reserve Economic Data)"])

    def test_curve_interpolation_is_calculation_and_never_extrapolates(self) -> None:
        result = build_yield_curve(
            {
                2.0: treasury_series_for_curve(2.0, 4.0),
                10.0: treasury_series_for_curve(10.0, 5.0),
            },
            observation_date="2026-08-13",
            requested_maturities=[1.0, 5.0, 20.0],
            interpolate=True,
        )

        self.assertEqual(result.calculated[0]["maturity_years"], 5.0)
        self.assertEqual(result.calculated[0]["role"], "calculation")
        self.assertAlmostEqual(result.calculated[0]["value"], 4.375)
        self.assertEqual(
            [item["maturity_years"] for item in result.missing],
            [1.0, 20.0],
        )

    def test_curve_does_not_carry_a_prior_date_forward(self) -> None:
        evidence = normalize_treasury_envelope(
            treasury_envelope(
                evidence_kind="us_treasury_current",
                observations=[treasury_observation("2026-08-12T00:00:00+00:00", 4.63)],
            )
        )
        result = build_yield_curve(
            {10.0: evidence},
            observation_date="2026-08-13",
            requested_maturities=[10.0],
        )
        self.assertEqual(result.observed, [])
        self.assertEqual(result.missing[0]["reason"], "not_observed")

    def test_historical_curve_uses_only_exact_common_dates(self) -> None:
        two_year = normalize_treasury_envelope(
            treasury_envelope(
                maturity_duration="2Year",
                maturity_years=2.0,
                observations=[
                    treasury_observation("2026-08-12T00:00:00+00:00", 4.10),
                    treasury_observation("2026-08-13T00:00:00+00:00", 4.15),
                ],
            )
        )
        ten_year = normalize_treasury_envelope(
            treasury_envelope(
                maturity_duration="10Year",
                maturity_years=10.0,
                observations=[
                    treasury_observation("2026-08-13T00:00:00+00:00", 4.63),
                    treasury_observation("2026-08-14T00:00:00+00:00", 4.64),
                ],
            )
        )

        result = build_historical_yield_curve({2.0: two_year, 10.0: ten_year})

        self.assertEqual(list(result.frame.columns), [2.0, 10.0])
        self.assertEqual(len(result.frame), 1)
        self.assertEqual(result.frame.index[0].isoformat(), "2026-08-13T00:00:00+00:00")
        self.assertEqual(result.receipt["alignment"], "exact_common_dates")

    def test_historical_curve_preserves_lower_confidence_by_maturity(self) -> None:
        lower = normalize_treasury_envelope(
            inferred_treasury_envelope(
                maturity_duration="2Year",
                maturity_years=2.0,
                observations=[
                    treasury_observation("2026-08-12", 4.10),
                    treasury_observation("2026-08-13", 4.15),
                ],
            )
        )
        high = normalize_treasury_envelope(
            treasury_envelope(
                observations=[
                    treasury_observation("2026-08-12", 4.60),
                    treasury_observation("2026-08-13", 4.63),
                ]
            )
        )

        result = build_historical_yield_curve({2.0: lower, 10.0: high})

        self.assertEqual(result.receipt["evidence_confidence"], "lower")
        self.assertEqual(
            result.receipt["evidence_by_maturity"][2.0]["evidence_tier"],
            "provider_labeled_inferred",
        )


class RiskFreeRateTests(unittest.TestCase):
    def test_lower_confidence_rate_is_usable_and_disclosed_downstream(self) -> None:
        treasury = normalize_treasury_envelope(
            inferred_treasury_envelope(
                maturity_duration="3Month",
                maturity_years=0.25,
                observations=[
                    treasury_observation("2026-01-02", 5.0),
                    treasury_observation("2026-01-09", 5.2),
                ],
            )
        )

        result = align_periodic_risk_free(
            treasury,
            pd.to_datetime(["2026-01-02T00:00:00+00:00", "2026-01-09T00:00:00+00:00"]),
            periods_per_year=52,
        )

        self.assertEqual(result.receipt["evidence_tier"], "provider_labeled_inferred")
        self.assertEqual(result.receipt["evidence_confidence"], "lower")
        self.assertEqual(result.receipt["exact_qualifier_status"], "unavailable")
        self.assertIn("lower-confidence", result.receipt["dependency_warning"])
        self.assertEqual(
            result.receipt["upstream_provenance"]["maturity_binding"],
            "provider_labeled_or_semantically_inferred",
        )
        self.assertEqual(
            result.receipt["aligned_observations"][0]["rate_input_confidence"],
            "lower",
        )

    def test_annual_percent_converts_to_weekly_periodic_rate(self) -> None:
        treasury = normalize_treasury_envelope(
            treasury_envelope(
                security_type="Bill",
                maturity_duration="3Month",
                maturity_years=0.25,
                observations=[
                    treasury_observation("2026-01-02T00:00:00+00:00", 5.0),
                    treasury_observation("2026-01-09T00:00:00+00:00", 5.2),
                ],
            )
        )
        result = align_periodic_risk_free(
            treasury,
            pd.to_datetime(["2026-01-02T00:00:00+00:00", "2026-01-09T00:00:00+00:00"]),
            periods_per_year=52,
        )

        self.assertAlmostEqual(result.series.iloc[0], (1.05 ** (1.0 / 52.0)) - 1.0)
        self.assertEqual(result.receipt["conversion"], "effective_annual_to_periodic")
        self.assertEqual(result.receipt["max_fill_days"], 3)
        aligned = result.receipt["aligned_observations"]
        self.assertEqual(aligned[0]["raw_annual_percent"], 5.0)
        self.assertAlmostEqual(
            aligned[0]["periodic_rate"], (1.05 ** (1.0 / 52.0)) - 1.0
        )
        self.assertEqual(result.receipt["unit"], "Percent")
        self.assertEqual(result.receipt["evidence_kind"], "us_treasury_history")
        self.assertEqual(result.receipt["retrieved_at"], "2026-08-16T00:00:00+00:00")
        self.assertEqual(
            result.receipt["requested_range"],
            {
                "start": "2025-01-01T00:00:00+00:00",
                "end": "2026-08-13T00:00:00+00:00",
            },
        )
        self.assertEqual(result.receipt["missing"], [])
        self.assertEqual(result.receipt["upstream_provenance"]["provider"], "wolfram")
        self.assertEqual(
            result.receipt["upstream_provenance"]["sources"][0]["organization"],
            "Federal Reserve Bank of St. Louis",
        )

    def test_negative_yield_above_minus_one_hundred_percent_is_supported(self) -> None:
        treasury = normalize_treasury_envelope(
            treasury_envelope(
                observations=[
                    treasury_observation("2026-01-02T00:00:00+00:00", -0.50),
                    treasury_observation("2026-01-09T00:00:00+00:00", -0.40),
                ]
            )
        )
        result = align_periodic_risk_free(
            treasury,
            pd.to_datetime(["2026-01-02T00:00:00+00:00"]),
            periods_per_year=252,
        )
        self.assertLess(result.series.iloc[0], 0.0)

    def test_alignment_carries_at_most_three_calendar_days(self) -> None:
        treasury = normalize_treasury_envelope(
            treasury_envelope(
                observations=[
                    treasury_observation("2026-01-02T00:00:00+00:00", 5.0),
                    treasury_observation("2026-01-09T00:00:00+00:00", 5.2),
                ]
            )
        )
        result = align_periodic_risk_free(
            treasury,
            pd.to_datetime(["2026-01-05T00:00:00+00:00"]),
            periods_per_year=252,
        )
        self.assertEqual(result.receipt["filled_observation_count"], 1)

        with self.assertRaisesRegex(DataGateError, "treasury_alignment_failed"):
            align_periodic_risk_free(
                treasury,
                pd.to_datetime(["2026-01-06T00:00:00+00:00"]),
                periods_per_year=252,
            )


if __name__ == "__main__":
    unittest.main()
