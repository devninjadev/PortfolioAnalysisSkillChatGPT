"""Validate structured FX evidence returned by the official Wolfram plugin."""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real
from typing import Any, Mapping

import pandas as pd

from . import DataGateError


ENDPOINT_TOLERANCE_DAYS = 7


@dataclass(frozen=True)
class WolframFxHistory:
    series: pd.Series
    currency: str
    receipt: dict[str, Any]


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DataGateError(
            "wolfram_fx_schema_error",
            f"Wolfram FX {label} must be a JSON object.",
            {"received_type": value.__class__.__name__},
        )
    return value


def _currency(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value.strip()) != 3 or not value.strip().isalpha():
        raise DataGateError(
            "wolfram_fx_schema_error",
            f"Wolfram FX {label} must be a three-letter currency code.",
            {label: value},
        )
    return value.strip().upper()


def _timestamp(value: Any, label: str) -> pd.Timestamp:
    if value is None or isinstance(value, bool):
        raise DataGateError("wolfram_fx_schema_error", f"Wolfram FX {label} is invalid.")
    try:
        timestamp = pd.Timestamp(value)
        if pd.isna(timestamp):
            raise ValueError("NaT")
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize("UTC")
        else:
            timestamp = timestamp.tz_convert("UTC")
        return timestamp
    except Exception as exc:
        raise DataGateError(
            "wolfram_fx_schema_error",
            f"Wolfram FX {label} must be a valid timestamp.",
            {"value": value, "error_type": exc.__class__.__name__},
        ) from exc


def _requested_range(request: Mapping[str, Any], start: str, end: str | None) -> dict[str, str | None]:
    requested_start = _timestamp(request.get("start"), "requested start")
    requested_end = _timestamp(request.get("end"), "requested end") if request.get("end") is not None else None
    cli_start = _timestamp(start, "CLI start")
    cli_end = _timestamp(end, "CLI end") if end is not None else None
    if requested_start != cli_start or requested_end != cli_end:
        raise DataGateError(
            "wolfram_fx_schema_error",
            "Wolfram FX envelope range does not match the validation request.",
            {
                "envelope_start": requested_start.isoformat(),
                "envelope_end": requested_end.isoformat() if requested_end is not None else None,
                "validation_start": cli_start.isoformat(),
                "validation_end": cli_end.isoformat() if cli_end is not None else None,
            },
        )
    if requested_end is not None and requested_end < requested_start:
        raise DataGateError("wolfram_fx_schema_error", "Wolfram FX requested range ends before it starts.")
    return {
        "start": requested_start.isoformat(),
        "end": requested_end.isoformat() if requested_end is not None else None,
    }


def _observations(value: Any) -> pd.Series:
    if not isinstance(value, list) or not value:
        raise DataGateError(
            "wolfram_fx_history_unavailable",
            "Wolfram FinancialData returned no FX observations.",
        )
    observations: dict[pd.Timestamp, float] = {}
    for position, raw in enumerate(value):
        item = _mapping(raw, f"observation {position}")
        timestamp = _timestamp(item.get("timestamp"), f"observation {position} timestamp")
        raw_value = item.get("value")
        if isinstance(raw_value, bool) or not isinstance(raw_value, Real):
            raise DataGateError(
                "wolfram_fx_schema_error",
                "Wolfram FX observations must contain numeric values.",
                {"position": position, "value": raw_value},
            )
        numeric = float(raw_value)
        if not math.isfinite(numeric) or numeric <= 0:
            raise DataGateError(
                "wolfram_fx_schema_error",
                "Wolfram FX observations must be positive and finite.",
                {"position": position, "value": raw_value},
            )
        if timestamp in observations and observations[timestamp] != numeric:
            raise DataGateError(
                "wolfram_fx_schema_error",
                "Wolfram FX returned conflicting observations at the same timestamp.",
                {"timestamp": timestamp.isoformat()},
            )
        observations[timestamp] = numeric
    series = pd.Series(observations, dtype=float).sort_index()
    series.index = pd.DatetimeIndex(series.index, tz="UTC")
    return series


def _sources(value: Any) -> tuple[list[dict[str, Any]], str]:
    if not isinstance(value, list) or not value:
        raise DataGateError(
            "wolfram_fx_source_unavailable",
            "Wolfram FX evidence has no official-plugin provenance.",
        )
    sources: list[dict[str, Any]] = []
    for raw in value:
        source = _mapping(raw, "source")
        if source.get("name") != "Wolfram FinancialData" or source.get("role") != "official_plugin_tool":
            raise DataGateError(
                "wolfram_fx_source_unavailable",
                "Wolfram FX evidence must identify Wolfram FinancialData from the official plugin.",
            )
        if source.get("underlying_source_annotation") is not None:
            raise DataGateError(
                "wolfram_fx_source_unavailable",
                "Wolfram FX underlying source metadata cannot be invented when unavailable.",
            )
        if source.get("source_annotation_status") != "unavailable":
            raise DataGateError(
                "wolfram_fx_source_unavailable",
                "Wolfram FX source annotation status must preserve unavailability.",
            )
        sources.append(dict(source))
    return sources, "unavailable"


def _primary_failure(value: Any, currency: str) -> dict[str, Any]:
    failure = _mapping(value, "primary Yahoo failure")
    details = _mapping(failure.get("details"), "primary Yahoo failure details")
    if (
        failure.get("provider") != "yahoo"
        or failure.get("code") != "fx_history_unavailable"
        or details.get("stage") != "fx_history"
        or _currency(details.get("currency"), "primary failure currency") != currency
    ):
        raise DataGateError(
            "wolfram_fx_schema_error",
            "Wolfram FX fallback requires the matching Yahoo FX failure receipt.",
        )
    return dict(failure)


def normalize_wolfram_fx_envelope(
    envelope: Mapping[str, Any],
    start: str,
    end: str | None,
) -> WolframFxHistory:
    """Normalize direct or inverse official-plugin FX evidence to USD per currency unit."""

    source = _mapping(envelope, "envelope")
    if source.get("schema_version") != 1 or source.get("provider") != "wolfram":
        raise DataGateError("wolfram_fx_schema_error", "Unsupported Wolfram FX evidence envelope.")
    if source.get("evidence_kind") != "fx_history":
        raise DataGateError("wolfram_fx_schema_error", "Wolfram FX evidence kind must be fx_history.")
    currency = _currency(source.get("currency"), "currency")
    if currency == "USD":
        raise DataGateError("wolfram_fx_pair_mismatch", "USD does not require a Wolfram FX bridge.")
    request = _mapping(source.get("request"), "request")
    requested_range = _requested_range(request, start, end)
    requested_base = _currency(request.get("base_currency"), "requested base_currency")
    requested_quote = _currency(request.get("quote_currency"), "requested quote_currency")
    result = _mapping(source.get("result"), "result")
    if result.get("entity_type") != "FinancialData":
        raise DataGateError("wolfram_fx_schema_error", "Wolfram FX result must come from FinancialData.")
    observed_base = _currency(result.get("base_currency"), "observed base_currency")
    observed_quote = _currency(result.get("quote_currency"), "observed quote_currency")
    if (observed_base, observed_quote) != (requested_base, requested_quote):
        raise DataGateError("wolfram_fx_pair_mismatch", "Requested and observed Wolfram FX pairs disagree.")

    direct = (currency, "USD")
    inverse = ("USD", currency)
    pair = (observed_base, observed_quote)
    if pair not in {direct, inverse}:
        raise DataGateError(
            "wolfram_fx_pair_mismatch",
            "Wolfram FX pair does not resolve the required currency against USD.",
            {"currency": currency, "pair": f"{observed_base}/{observed_quote}"},
        )
    expected_symbol = f"{observed_base}/{observed_quote}"
    if result.get("symbol") != expected_symbol:
        raise DataGateError("wolfram_fx_pair_mismatch", "Wolfram FinancialData symbol conflicts with pair metadata.")

    unit = _mapping(result.get("unit"), "unit")
    expected_numerator, expected_denominator = (
        ("USD", currency) if pair == direct else (currency, "USD")
    )
    if (
        unit.get("quantity_kind") != "exchange_rate"
        or _currency(unit.get("numerator_currency"), "unit numerator_currency") != expected_numerator
        or _currency(unit.get("denominator_currency"), "unit denominator_currency") != expected_denominator
    ):
        raise DataGateError(
            "wolfram_fx_unit_mismatch",
            "Wolfram FX unit does not match the declared pair orientation.",
        )

    observations = _observations(result.get("observations"))
    requested_start = pd.Timestamp(requested_range["start"])
    requested_end = pd.Timestamp(requested_range["end"]) if requested_range["end"] else None
    start_gap = (observations.index.min().normalize() - requested_start.normalize()).days
    end_gap = (
        (requested_end.normalize() - observations.index.max().normalize()).days
        if requested_end is not None
        else 0
    )
    open_ended_missing_start = (
        requested_end is None and observations.index.max() < requested_start
    )
    if (
        start_gap > ENDPOINT_TOLERANCE_DAYS
        or end_gap > ENDPOINT_TOLERANCE_DAYS
        or open_ended_missing_start
    ):
        raise DataGateError(
            "wolfram_fx_history_incomplete",
            "Wolfram FX history does not cover the requested endpoints.",
            {"start_gap_days": start_gap, "end_gap_days": end_gap},
        )

    inversion_applied = pair == inverse
    normalized = (1.0 / observations) if inversion_applied else observations.copy()
    normalized.name = expected_symbol
    sources, source_annotation_status = _sources(source.get("sources"))
    primary_failure = _primary_failure(source.get("primary_failure"), currency)
    retrieved_at = _timestamp(source.get("retrieved_at"), "retrieved_at").isoformat()
    observed_range = {
        "start": observations.index.min().isoformat(),
        "end": observations.index.max().isoformat(),
    }
    return WolframFxHistory(
        series=normalized,
        currency=currency,
        receipt={
            "provider": "wolfram",
            "evidence_kind": "fx_history",
            "currency": currency,
            "requested_pair": f"{requested_base}/{requested_quote}",
            "observed_pair": expected_symbol,
            "inversion_applied": inversion_applied,
            "conversion_rule": (
                "inverse_currency_units_per_USD"
                if inversion_applied
                else "observed_USD_per_currency_unit"
            ),
            "normalized_unit": f"USD_per_{currency}",
            "observation_count": len(normalized),
            "requested_range": requested_range,
            "observed_range": observed_range,
            "coverage_status": "complete",
            "sources": sources,
            "source_names": [item["name"] for item in sources],
            "source_annotation_status": source_annotation_status,
            "underlying_source_annotation": None,
            "primary_failure": primary_failure,
            "retrieved_at": retrieved_at,
        },
    )


__all__ = ["WolframFxHistory", "normalize_wolfram_fx_envelope"]
