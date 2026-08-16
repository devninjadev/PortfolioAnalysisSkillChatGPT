from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from advisor_data import DataGateError  # noqa: E402
from advisor_data.wolfram_fx import normalize_wolfram_fx_envelope  # noqa: E402


def fx_observation(timestamp: str, value: float) -> dict[str, object]:
    return {"timestamp": timestamp, "value": value}


def wolfram_fx_envelope(
    *,
    currency: str = "KRW",
    base_currency: str = "KRW",
    quote_currency: str = "USD",
    symbol: str = "KRW/USD",
    unit_numerator: str = "USD",
    unit_denominator: str = "KRW",
    observations: list[dict[str, object]] | None = None,
    start: str = "2026-08-03",
    end: str | None = "2026-08-14",
) -> dict[str, object]:
    if observations is None:
        observations = [
            fx_observation("2026-08-03T00:00:00+00:00", 0.000700),
            fx_observation("2026-08-14T00:00:00+00:00", 0.000705),
        ]
    return {
        "schema_version": 1,
        "provider": "wolfram",
        "evidence_kind": "fx_history",
        "currency": currency,
        "request": {
            "start": start,
            "end": end,
            "base_currency": base_currency,
            "quote_currency": quote_currency,
        },
        "primary_failure": {
            "provider": "yahoo",
            "code": "fx_history_unavailable",
            "message": f"Yahoo returned no usable USD conversion pair for {currency}.",
            "details": {"stage": "fx_history", "currency": currency},
        },
        "result": {
            "entity_type": "FinancialData",
            "symbol": symbol,
            "base_currency": base_currency,
            "quote_currency": quote_currency,
            "unit": {
                "quantity_kind": "exchange_rate",
                "numerator_currency": unit_numerator,
                "denominator_currency": unit_denominator,
            },
            "observations": observations,
        },
        "sources": [
            {
                "name": "Wolfram FinancialData",
                "role": "official_plugin_tool",
                "underlying_source_annotation": None,
                "source_annotation_status": "unavailable",
            }
        ],
        "retrieved_at": "2026-08-17T00:00:00+00:00",
    }


class WolframFxEnvelopeTests(unittest.TestCase):
    def test_direct_pair_returns_usd_per_currency_without_inversion(self) -> None:
        result = normalize_wolfram_fx_envelope(
            wolfram_fx_envelope(),
            start="2026-08-03",
            end="2026-08-14",
        )

        self.assertEqual(result.currency, "KRW")
        self.assertEqual(result.series.name, "KRW/USD")
        self.assertAlmostEqual(float(result.series.iloc[0]), 0.000700)
        self.assertFalse(result.receipt["inversion_applied"])
        self.assertEqual(result.receipt["conversion_rule"], "observed_USD_per_currency_unit")
        self.assertEqual(result.receipt["provider"], "wolfram")
        self.assertEqual(result.receipt["source_annotation_status"], "unavailable")

    def test_inverse_pair_is_inverted_once_into_usd_per_currency(self) -> None:
        result = normalize_wolfram_fx_envelope(
            wolfram_fx_envelope(
                base_currency="USD",
                quote_currency="KRW",
                symbol="USD/KRW",
                unit_numerator="KRW",
                unit_denominator="USD",
                observations=[
                    fx_observation("2026-08-03T00:00:00+00:00", 1400.0),
                    fx_observation("2026-08-14T00:00:00+00:00", 1420.0),
                ],
            ),
            start="2026-08-03",
            end="2026-08-14",
        )

        self.assertEqual(result.currency, "KRW")
        self.assertEqual(result.series.name, "USD/KRW")
        self.assertAlmostEqual(float(result.series.iloc[0]), 1.0 / 1400.0)
        self.assertTrue(result.receipt["inversion_applied"])
        self.assertEqual(result.receipt["conversion_rule"], "inverse_currency_units_per_USD")

    def test_open_ended_history_requires_an_observation_on_or_after_start(self) -> None:
        envelope = wolfram_fx_envelope(
            observations=[fx_observation("2026-08-01T00:00:00+00:00", 0.000700)],
            start="2026-08-03",
            end=None,
        )

        with self.assertRaisesRegex(DataGateError, "wolfram_fx_history_incomplete"):
            normalize_wolfram_fx_envelope(envelope, start="2026-08-03", end=None)

    def test_rejects_pair_that_does_not_bind_required_currency_to_usd(self) -> None:
        envelope = wolfram_fx_envelope(
            base_currency="KRW",
            quote_currency="EUR",
            symbol="KRW/EUR",
            unit_numerator="EUR",
            unit_denominator="KRW",
        )

        with self.assertRaisesRegex(DataGateError, "wolfram_fx_pair_mismatch"):
            normalize_wolfram_fx_envelope(envelope, start="2026-08-03", end="2026-08-14")

    def test_rejects_unit_that_conflicts_with_pair_orientation(self) -> None:
        envelope = wolfram_fx_envelope(unit_numerator="KRW", unit_denominator="USD")

        with self.assertRaisesRegex(DataGateError, "wolfram_fx_unit_mismatch"):
            normalize_wolfram_fx_envelope(envelope, start="2026-08-03", end="2026-08-14")

    def test_rejects_conflicting_duplicate_observations(self) -> None:
        envelope = wolfram_fx_envelope(
            observations=[
                fx_observation("2026-08-03T00:00:00+00:00", 0.000700),
                fx_observation("2026-08-03T00:00:00+00:00", 0.000701),
            ]
        )

        with self.assertRaisesRegex(DataGateError, "wolfram_fx_schema_error"):
            normalize_wolfram_fx_envelope(envelope, start="2026-08-03", end="2026-08-14")

    def test_identical_duplicate_observations_collapse(self) -> None:
        envelope = wolfram_fx_envelope(
            observations=[
                fx_observation("2026-08-03T00:00:00+00:00", 0.000700),
                fx_observation("2026-08-03T00:00:00+00:00", 0.000700),
                fx_observation("2026-08-14T00:00:00+00:00", 0.000705),
            ]
        )

        result = normalize_wolfram_fx_envelope(
            envelope, start="2026-08-03", end="2026-08-14"
        )

        self.assertEqual(len(result.series), 2)

    def test_rejects_non_positive_non_finite_and_non_numeric_values(self) -> None:
        for value in (0.0, -1.0, float("nan"), float("inf"), "0.0007", True):
            with self.subTest(value=value):
                envelope = wolfram_fx_envelope(
                    observations=[fx_observation("2026-08-03", value)]
                )
                with self.assertRaisesRegex(DataGateError, "wolfram_fx_schema_error"):
                    normalize_wolfram_fx_envelope(
                        envelope, start="2026-08-03", end="2026-08-14"
                    )

    def test_rejects_empty_history(self) -> None:
        envelope = wolfram_fx_envelope(observations=[])

        with self.assertRaisesRegex(DataGateError, "wolfram_fx_history_unavailable"):
            normalize_wolfram_fx_envelope(envelope, start="2026-08-03", end="2026-08-14")

    def test_rejects_range_mismatch_and_clipped_endpoint(self) -> None:
        mismatch = wolfram_fx_envelope(start="2026-08-04")
        with self.assertRaisesRegex(DataGateError, "wolfram_fx_schema_error"):
            normalize_wolfram_fx_envelope(mismatch, start="2026-08-03", end="2026-08-14")

        clipped = wolfram_fx_envelope(
            observations=[
                fx_observation("2026-08-03", 0.000700),
                fx_observation("2026-08-05", 0.000701),
            ]
        )
        with self.assertRaisesRegex(DataGateError, "wolfram_fx_history_incomplete"):
            normalize_wolfram_fx_envelope(clipped, start="2026-08-03", end="2026-08-14")

    def test_rejects_missing_or_fabricated_source_provenance(self) -> None:
        missing = wolfram_fx_envelope()
        missing["sources"] = []
        with self.assertRaisesRegex(DataGateError, "wolfram_fx_source_unavailable"):
            normalize_wolfram_fx_envelope(missing, start="2026-08-03", end="2026-08-14")

        fabricated = wolfram_fx_envelope()
        fabricated["sources"][0]["underlying_source_annotation"] = "Imagined Vendor"
        with self.assertRaisesRegex(DataGateError, "wolfram_fx_source_unavailable"):
            normalize_wolfram_fx_envelope(fabricated, start="2026-08-03", end="2026-08-14")

    def test_rejects_mismatched_primary_yahoo_failure(self) -> None:
        envelope = wolfram_fx_envelope()
        envelope["primary_failure"]["details"]["currency"] = "EUR"

        with self.assertRaisesRegex(DataGateError, "wolfram_fx_schema_error"):
            normalize_wolfram_fx_envelope(envelope, start="2026-08-03", end="2026-08-14")


if __name__ == "__main__":
    unittest.main()
