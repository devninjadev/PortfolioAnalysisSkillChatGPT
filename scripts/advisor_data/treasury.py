"""Validate U.S. Treasury evidence and derive disclosed calculations."""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from . import DataGateError


SUPPORTED_SECURITY_TYPES = frozenset({"Bill", "Note", "Bond", "TIPS"})
SUPPORTED_MARKETS = frozenset({"AuctionAverage", "SecondaryMarket"})
SUPPORTED_DUE_DATES = frozenset({"ConstantMaturity"})
SUPPORTED_FREQUENCIES = frozenset(
    {"Daily", "Weekly", "BiWeekly", "Monthly", "Quarterly", "Annual"}
)
SUPPORTED_OPERATORS = frozenset(
    {
        "Change",
        "ChangeRate",
        "AnnualChange",
        "AnnualizedChangeRate",
        "YearOverYearChangeRate",
    }
)
SUPPORTED_EVIDENCE_KINDS = frozenset(
    {"us_treasury_current", "us_treasury_history"}
)
SUPPORTED_EVIDENCE_TIERS = frozenset(
    {"provider_confirmed", "provider_labeled_inferred"}
)
INFERRED_BINDING_CHANNELS = frozenset(
    {"official_plugin_labeled_result", "official_plugin_input_interpretation"}
)
QUALIFIER_KEYS = (
    "security_type",
    "maturity_duration",
    "market",
    "due_date",
    "frequency",
    "time_series_operator",
    "coupon_rate",
)


@dataclass(frozen=True)
class TreasurySeries:
    series: pd.Series
    maturity_years: float
    receipt: dict[str, Any]


@dataclass(frozen=True)
class YieldCurveResult:
    observed: list[dict[str, Any]]
    missing: list[dict[str, Any]]
    calculated: list[dict[str, Any]]
    receipt: dict[str, Any]


@dataclass(frozen=True)
class HistoricalYieldCurveResult:
    frame: pd.DataFrame
    receipt: dict[str, Any]


@dataclass(frozen=True)
class RiskFreeResult:
    series: pd.Series
    receipt: dict[str, Any]


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DataGateError(
            "wolfram_schema_error",
            f"Wolfram {label} must be a JSON object.",
            {"received_type": value.__class__.__name__},
        )
    return value


def _utc_timestamp(value: Any, label: str) -> pd.Timestamp:
    if value is None or isinstance(value, bool):
        raise DataGateError(
            "wolfram_schema_error",
            f"Wolfram {label} must be a valid timestamp.",
            {"value": value},
        )
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
            "wolfram_schema_error",
            f"Wolfram {label} must be a valid timestamp.",
            {"value": value, "error_type": exc.__class__.__name__},
        ) from exc


def _required_text(source: Mapping[str, Any], key: str) -> str:
    value = source.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DataGateError(
            "wolfram_schema_error",
            f"Wolfram evidence is missing {key}.",
        )
    return value.strip()


def _sources(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise DataGateError(
            "wolfram_source_unavailable",
            "Wolfram Treasury evidence has no source metadata.",
        )
    sources: list[dict[str, Any]] = []
    for position, raw_source in enumerate(value):
        if not isinstance(raw_source, Mapping):
            raise DataGateError(
                "wolfram_source_unavailable",
                "Wolfram Treasury source metadata must contain JSON objects.",
                {"position": position},
            )
        if not isinstance(raw_source.get("name"), str) or not raw_source["name"].strip():
            raise DataGateError(
                "wolfram_source_unavailable",
                "Wolfram Treasury sources require a non-empty name.",
                {"position": position},
            )
        sources.append(dict(raw_source))
    return sources


def _finite_number(value: Any, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise DataGateError(
            "wolfram_schema_error",
            f"Wolfram {label} must be a finite numeric value.",
            {"value": value},
        )
    numeric = float(value)
    if not math.isfinite(numeric) or (positive and numeric <= 0):
        requirement = "positive finite" if positive else "finite"
        raise DataGateError(
            "wolfram_schema_error",
            f"Wolfram {label} must be a {requirement} numeric value.",
            {"value": value},
        )
    return numeric


def _parse_observations(value: Any) -> pd.Series:
    if not isinstance(value, list):
        raise DataGateError(
            "wolfram_schema_error",
            "Wolfram Treasury result observations must be a list.",
        )
    observations: dict[pd.Timestamp, float] = {}
    for position, raw_observation in enumerate(value):
        item = _mapping(raw_observation, f"observation {position}")
        timestamp = _utc_timestamp(item.get("timestamp"), f"observation {position} timestamp")
        numeric_value = _finite_number(item.get("value"), "Treasury observation yield")
        if timestamp in observations and observations[timestamp] != numeric_value:
            raise DataGateError(
                "wolfram_schema_error",
                "Wolfram returned conflicting Treasury observations at the same timestamp.",
                {"timestamp": timestamp.isoformat()},
            )
        observations[timestamp] = numeric_value

    series = pd.Series(observations, dtype=float).sort_index()
    if len(series):
        series.index = pd.DatetimeIndex(series.index, tz="UTC")
    series.name = "Treasury"
    return series


def _requested_range(request: Mapping[str, Any]) -> dict[str, str | None]:
    start = _utc_timestamp(request.get("start"), "requested start")
    raw_end = request.get("end")
    end = _utc_timestamp(raw_end, "requested end") if raw_end is not None else None
    if end is not None and end < start:
        raise DataGateError(
            "wolfram_schema_error",
            "Wolfram requested range ends before it starts.",
            {"start": request.get("start"), "end": raw_end},
        )
    return {"start": start.isoformat(), "end": end.isoformat() if end is not None else None}


def _coverage_status(series: pd.Series, requested: Mapping[str, str | None]) -> str:
    if series.empty:
        return "empty"
    requested_start = pd.Timestamp(requested["start"])
    requested_end = pd.Timestamp(requested["end"]) if requested.get("end") else None
    clipped_start = series.index.min() > requested_start
    clipped_end = requested_end is not None and series.index.max() < requested_end
    if clipped_start and clipped_end:
        return "clipped_both"
    if clipped_start:
        return "clipped_start"
    if clipped_end:
        return "clipped_end"
    return "complete"


def _validate_qualifiers(qualifiers: Mapping[str, Any]) -> dict[str, Any]:
    preserved = dict(qualifiers)
    for key in qualifiers:
        if key not in QUALIFIER_KEYS:
            raise DataGateError(
                "wolfram_schema_error",
                f"Wolfram Treasury qualifier {key} is not recognized.",
                {"qualifier": key},
            )

    security_type = qualifiers.get("security_type")
    if security_type not in SUPPORTED_SECURITY_TYPES:
        raise DataGateError(
            "wolfram_schema_error",
            "Wolfram Treasury security_type is unsupported.",
            {"security_type": security_type},
        )
    maturity_duration = qualifiers.get("maturity_duration")
    if not isinstance(maturity_duration, str) or not maturity_duration.strip():
        raise DataGateError(
            "wolfram_schema_error",
            "Wolfram Treasury maturity_duration must be non-empty semantic text.",
            {"maturity_duration": maturity_duration},
        )
    for key, supported in (
        ("market", SUPPORTED_MARKETS),
        ("due_date", SUPPORTED_DUE_DATES),
        ("frequency", SUPPORTED_FREQUENCIES),
        ("time_series_operator", SUPPORTED_OPERATORS),
    ):
        value = qualifiers.get(key)
        if value is not None and value not in supported:
            raise DataGateError(
                "wolfram_schema_error",
                f"Wolfram Treasury {key} is unsupported.",
                {key: value},
            )
    coupon_rate = qualifiers.get("coupon_rate")
    if coupon_rate is not None:
        preserved["coupon_rate"] = _finite_number(coupon_rate, "Treasury coupon_rate")
    return preserved


def _complete_qualifier_echo(
    container: Mapping[str, Any], key: str, label: str
) -> dict[str, Any]:
    if key not in container or not isinstance(container.get(key), Mapping):
        raise DataGateError(
            "wolfram_qualifier_mismatch",
            f"Wolfram Treasury evidence is missing complete {label} qualifiers.",
            {"missing_echo": key},
        )
    qualifiers = _mapping(container[key], f"Treasury {label} qualifiers")
    missing_keys = [name for name in QUALIFIER_KEYS if name not in qualifiers]
    extra_keys = [name for name in qualifiers if name not in QUALIFIER_KEYS]
    if missing_keys or extra_keys:
        raise DataGateError(
            "wolfram_qualifier_mismatch",
            f"Wolfram Treasury {label} qualifiers are incomplete.",
            {"missing_qualifiers": missing_keys, "extra_qualifiers": extra_keys},
        )
    return _validate_qualifiers(qualifiers)


def _qualifiers_must_match(
    declared: Mapping[str, Any], echoed: Mapping[str, Any], label: str
) -> None:
    for key in QUALIFIER_KEYS:
        if declared.get(key) != echoed.get(key):
            raise DataGateError(
                "wolfram_qualifier_mismatch",
                "Wolfram Treasury requested and observed qualifiers disagree.",
                {
                    "qualifier": key,
                    "declared": declared.get(key),
                    label: echoed.get(key),
                },
            )


def _typed_maturity(
    value: Any,
    label: str,
    *,
    expected_evidence_kind: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise DataGateError(
            "treasury_maturity_mismatch",
            f"Treasury {label} typed maturity evidence is required.",
        )
    duration = value.get("duration")
    unit = value.get("unit")
    evidence_kind = value.get("evidence_kind")
    try:
        years = _finite_number(value.get("years"), f"Treasury {label} maturity years", positive=True)
    except DataGateError as exc:
        raise DataGateError(
            "treasury_maturity_mismatch",
            f"Treasury {label} maturity requires provider-typed numeric years.",
            {"years": value.get("years")},
        ) from exc
    if (
        not isinstance(duration, str)
        or not duration.strip()
        or unit != "years"
        or evidence_kind != expected_evidence_kind
    ):
        raise DataGateError(
            "treasury_maturity_mismatch",
            f"Treasury {label} typed maturity evidence is malformed.",
            {"maturity": dict(value)},
        )
    return {
        "duration": duration.strip(),
        "years": years,
        "unit": "years",
        "evidence_kind": expected_evidence_kind,
    }


def _missing_names_requested(missing: Sequence[Any], requested: str) -> bool:
    """Treat an explicit maturity miss as a hard maturity-unavailable gate.

    The marker's value is retained verbatim; a different maturity is never
    silently substituted for the requested series.
    """
    for item in missing:
        if isinstance(item, Mapping) and item.get("maturity_duration") == requested:
            return True
        if isinstance(item, str) and item == requested:
            return True
    return False


def _validate_inferred_binding(
    source: Mapping[str, Any],
    requested_maturity: Mapping[str, Any],
    evidence_kind: str,
    series: pd.Series,
    sources: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], float]:
    if not isinstance(source.get("exact_qualifier_failure"), Mapping):
        raise DataGateError(
            "treasury_binding_unavailable",
            "Lower-confidence Treasury evidence is missing the exact-query failure receipt.",
        )
    exact_failure = _mapping(
        source.get("exact_qualifier_failure"), "Treasury exact qualifier failure"
    )
    exact_missing = exact_failure.get("missing")
    if exact_failure.get("status") != "unavailable" or not isinstance(exact_missing, list) or not exact_missing:
        raise DataGateError(
            "treasury_binding_unavailable",
            "Lower-confidence Treasury evidence must preserve the unavailable exact query.",
        )
    try:
        failed_query_maturity = _finite_number(
            exact_failure.get("requested_maturity_years"),
            "Treasury exact-query requested maturity years",
            positive=True,
        )
    except DataGateError as exc:
        raise DataGateError(
            "treasury_binding_unavailable",
            "The exact-query failure must identify its typed requested maturity.",
        ) from exc
    if failed_query_maturity != requested_maturity["years"]:
        raise DataGateError(
            "treasury_binding_unavailable",
            "The exact-query failure belongs to a different Treasury maturity.",
            {
                "failed_query_maturity_years": failed_query_maturity,
                "requested_maturity_years": requested_maturity["years"],
            },
        )

    binding = _mapping(source.get("binding_evidence"), "Treasury binding evidence")
    if binding.get("channel") not in INFERRED_BINDING_CHANNELS:
        raise DataGateError(
            "treasury_binding_unavailable",
            "Treasury binding evidence does not identify a supported official-plugin channel.",
            {"channel": binding.get("channel")},
        )
    _required_text(binding, "query")
    labels = (binding.get("displayed_label"), binding.get("input_interpretation"))
    if not any(isinstance(value, str) and value.strip() for value in labels):
        raise DataGateError(
            "treasury_binding_unavailable",
            "Treasury binding evidence needs an explicit displayed label or input interpretation.",
        )
    if not any(item.get("role") == "official_plugin_tool" for item in sources):
        raise DataGateError(
            "treasury_binding_unavailable",
            "Lower-confidence Treasury evidence must come from the official plugin.",
        )

    if evidence_kind == "us_treasury_current":
        if binding.get("observation_date") is None:
            raise DataGateError(
                "treasury_binding_unavailable",
                "Labeled Treasury evidence is missing its observation date.",
            )
        observation_date = _utc_timestamp(
            binding.get("observation_date"), "Treasury binding observation_date"
        )
        if observation_date not in series.index:
            raise DataGateError(
                "treasury_binding_unavailable",
                "The labeled Treasury observation date is not present in the result.",
            )
    else:
        if not isinstance(binding.get("observation_date_range"), Mapping):
            raise DataGateError(
                "treasury_binding_unavailable",
                "Interpreted Treasury history is missing its observation date range.",
            )
        date_range = _mapping(
            binding.get("observation_date_range"), "Treasury binding observation date range"
        )
        bound_start = _utc_timestamp(date_range.get("start"), "Treasury binding range start")
        bound_end = _utc_timestamp(date_range.get("end"), "Treasury binding range end")
        if bound_start != series.index.min() or bound_end != series.index.max():
            raise DataGateError(
                "treasury_binding_unavailable",
                "The interpreted Treasury date range does not match the returned observations.",
            )

    decision = _mapping(source.get("binding_decision"), "Treasury binding decision")
    if decision.get("decision_kind") != "structured_llm_semantic_binding":
        raise DataGateError(
            "treasury_binding_unavailable",
            "Treasury maturity binding must be a structured LLM semantic decision.",
        )
    requested_years = _finite_number(
        decision.get("requested_maturity_years"),
        "Treasury binding requested maturity years",
        positive=True,
    )
    bound_years = _finite_number(
        decision.get("bound_maturity_years"),
        "Treasury binding bound maturity years",
        positive=True,
    )
    conflicts = decision.get("conflicts")
    if (
        decision.get("maturity_match") is not True
        or not isinstance(conflicts, list)
        or conflicts
        or requested_years != requested_maturity["years"]
        or bound_years != requested_maturity["years"]
    ):
        raise DataGateError(
            "treasury_binding_unavailable",
            "Treasury labeled or interpreted maturity does not match the requested maturity.",
            {
                "requested_maturity_years": requested_maturity["years"],
                "decision": dict(decision),
            },
        )
    return dict(exact_failure), dict(binding), bound_years


def normalize_treasury_envelope(envelope: Mapping[str, Any]) -> TreasurySeries:
    """Return an exact, evidence-gated U.S. Treasury yield series."""

    source = _mapping(envelope, "Treasury envelope")
    if source.get("schema_version") != 1:
        raise DataGateError("wolfram_schema_error", "Unsupported Wolfram Treasury evidence schema.")
    if source.get("provider") != "wolfram":
        raise DataGateError("wolfram_schema_error", "Wolfram Treasury evidence has an unexpected provider.")
    if source.get("evidence_kind") not in SUPPORTED_EVIDENCE_KINDS:
        raise DataGateError(
            "wolfram_schema_error",
            "Wolfram Treasury evidence kind is unsupported.",
            {"evidence_kind": source.get("evidence_kind")},
        )
    evidence_tier = source.get("evidence_tier", "provider_confirmed")
    if evidence_tier not in SUPPORTED_EVIDENCE_TIERS:
        raise DataGateError(
            "wolfram_schema_error",
            "Wolfram Treasury evidence tier is unsupported.",
            {"evidence_tier": evidence_tier},
        )
    if source.get("country_entity") != "UnitedStates":
        raise DataGateError(
            "wolfram_entity_mismatch",
            "Wolfram Treasury evidence is not for UnitedStates.",
            {"country_entity": source.get("country_entity")},
        )

    qualifiers = _complete_qualifier_echo(source, "qualifiers", "declared")
    request = _mapping(source.get("request"), "Treasury request")
    result = _mapping(source.get("result"), "Treasury result")
    requested_qualifiers = _complete_qualifier_echo(
        request, "requested_qualifiers", "requested"
    )
    _qualifiers_must_match(qualifiers, requested_qualifiers, "requested")
    requested_maturity = _typed_maturity(
        request.get("requested_maturity"),
        "requested",
        expected_evidence_kind="classifier_typed_request",
    )
    if requested_maturity["duration"] != qualifiers["maturity_duration"]:
        raise DataGateError(
            "treasury_maturity_mismatch",
            "Treasury requested maturity duration conflicts with requested qualifiers.",
            {
                "qualifier_duration": qualifiers["maturity_duration"],
                "typed_duration": requested_maturity["duration"],
            },
        )
    requested_range = _requested_range(request)
    if result.get("property") != "Treasury":
        raise DataGateError(
            "wolfram_property_unavailable",
            "Wolfram result property is not Treasury.",
            {"property": result.get("property")},
        )
    if result.get("unit") != "Percent":
        raise DataGateError(
            "wolfram_unit_mismatch",
            "Wolfram Treasury yields must use the Percent unit.",
            {"unit": result.get("unit")},
        )
    _required_text(qualifiers, "maturity_duration")
    retrieved_at = _required_text(source, "retrieved_at")
    sources = _sources(source.get("sources"))
    missing = result.get("missing")
    if not isinstance(missing, list):
        raise DataGateError(
            "wolfram_schema_error",
            "Wolfram Treasury result missing must be a list.",
        )
    series = _parse_observations(result.get("observations"))
    evidence_kind = source.get("evidence_kind")
    if series.empty:
        code = (
            "treasury_maturity_unavailable"
            if _missing_names_requested(missing, qualifiers["maturity_duration"])
            else "treasury_series_unavailable"
        )
        raise DataGateError(
            code,
            "Wolfram Treasury returned no observations.",
            {"missing": list(missing)},
        )
    exact_qualifier_failure: dict[str, Any] | None = None
    binding_evidence: dict[str, Any] | None = None
    if evidence_tier == "provider_confirmed":
        observed_qualifiers = _complete_qualifier_echo(
            result, "observed_qualifiers", "provider-observed"
        )
        _qualifiers_must_match(qualifiers, observed_qualifiers, "provider_observed")
        observed_maturity = _typed_maturity(
            result.get("observed_maturity"),
            "provider-observed",
            expected_evidence_kind="provider_observed_typed",
        )
        try:
            maturity_years = _finite_number(
                result.get("maturity_years"), "Treasury maturity_years", positive=True
            )
        except DataGateError as exc:
            raise DataGateError(
                "treasury_maturity_mismatch",
                "Treasury result requires provider-derived typed numeric maturity years.",
                {"maturity_years": result.get("maturity_years")},
            ) from exc
        if (
            observed_maturity["duration"] != qualifiers["maturity_duration"]
            or observed_maturity["years"] != requested_maturity["years"]
            or maturity_years != observed_maturity["years"]
        ):
            raise DataGateError(
                "treasury_maturity_mismatch",
                "Treasury requested and provider-observed typed maturities disagree.",
                {
                    "requested_maturity": requested_maturity,
                    "observed_maturity": observed_maturity,
                    "maturity_years": maturity_years,
                },
            )
    else:
        observed_qualifiers = None
        observed_maturity = None
        exact_qualifier_failure, binding_evidence, maturity_years = _validate_inferred_binding(
            source,
            requested_maturity,
            evidence_kind,
            series,
            sources,
        )
    minimum = 1 if evidence_kind == "us_treasury_current" else 2
    if len(series) < minimum:
        raise DataGateError(
            "wolfram_schema_error",
            f"Wolfram {evidence_kind} requires at least {minimum} observation(s).",
            {"observation_count": len(series)},
        )

    observed_range = {
        "start": series.index.min().isoformat(),
        "end": series.index.max().isoformat(),
    }
    receipt: dict[str, Any] = {
        "provider": "wolfram",
        "country_entity": source["country_entity"],
        "evidence_kind": evidence_kind,
        "property": result["property"],
        "maturity_years": maturity_years,
        "unit": result["unit"],
        "qualifiers": qualifiers,
        "requested_qualifiers": requested_qualifiers,
        "observed_qualifiers": observed_qualifiers,
        "requested_maturity": requested_maturity,
        "observed_maturity": observed_maturity,
        "sources": sources,
        "source_names": [str(item["name"]) for item in sources],
        "observation_count": len(series),
        "requested_range": requested_range,
        "observed_range": observed_range,
        "coverage_status": _coverage_status(series, requested_range),
        "missing": list(missing),
        "retrieved_at": retrieved_at,
        "evidence_tier": evidence_tier,
        "evidence_confidence": "high" if evidence_tier == "provider_confirmed" else "lower",
        "maturity_binding": (
            "provider_typed_exact"
            if evidence_tier == "provider_confirmed"
            else "provider_labeled_or_semantically_inferred"
        ),
        "exact_qualifier_status": (
            "confirmed" if evidence_tier == "provider_confirmed" else "unavailable"
        ),
    }
    if exact_qualifier_failure is not None and binding_evidence is not None:
        receipt.update(
            {
                "exact_qualifier_failure": exact_qualifier_failure,
                "binding_evidence": binding_evidence,
                "dependency_warning": (
                    "Downstream calculations inherit a lower-confidence Treasury rate input."
                ),
            }
        )
    return TreasurySeries(series=series, maturity_years=maturity_years, receipt=receipt)


def _validated_treasury_series_by_maturity(
    series_by_maturity: Mapping[float, TreasurySeries],
) -> list[tuple[float, TreasurySeries]]:
    validated: list[tuple[float, TreasurySeries]] = []
    for mapping_maturity, treasury in series_by_maturity.items():
        if (
            isinstance(mapping_maturity, bool)
            or not isinstance(mapping_maturity, Real)
            or not math.isfinite(float(mapping_maturity))
            or float(mapping_maturity) <= 0
            or not isinstance(treasury, TreasurySeries)
            or float(mapping_maturity) != treasury.maturity_years
        ):
            raise DataGateError(
                "treasury_alignment_failed",
                "Treasury maturity mapping must match the evidence numeric maturity_years.",
                {
                    "mapping_maturity": mapping_maturity,
                    "evidence_maturity": (
                        treasury.maturity_years if isinstance(treasury, TreasurySeries) else None
                    ),
                },
            )
        validated.append((float(mapping_maturity), treasury))
    return sorted(validated, key=lambda item: item[0])


def _curve_receipt_series_metadata(
    validated: Sequence[tuple[float, TreasurySeries]],
) -> tuple[dict[float, list[str]], dict[float, dict[str, Any]]]:
    return (
        {maturity: list(treasury.receipt["source_names"]) for maturity, treasury in validated},
        {maturity: dict(treasury.receipt["qualifiers"]) for maturity, treasury in validated},
    )


def _evidence_by_maturity(
    validated: Sequence[tuple[float, TreasurySeries]],
) -> dict[float, dict[str, Any]]:
    return {
        maturity: {
            "evidence_tier": treasury.receipt["evidence_tier"],
            "evidence_confidence": treasury.receipt["evidence_confidence"],
            "maturity_binding": treasury.receipt["maturity_binding"],
            "exact_qualifier_status": treasury.receipt["exact_qualifier_status"],
        }
        for maturity, treasury in validated
    }


def _weakest_evidence_confidence(
    evidence: Sequence[Mapping[str, Any]],
) -> str:
    return "lower" if any(item.get("evidence_confidence") == "lower" for item in evidence) else "high"


def build_yield_curve(
    series_by_maturity: Mapping[float, TreasurySeries],
    observation_date: str,
    requested_maturities: Sequence[float],
    interpolate: bool = False,
) -> YieldCurveResult:
    """Assemble exact-date Treasury observations, with explicit optional calculations."""
    target_date = _utc_timestamp(observation_date, "yield curve observation_date").normalize()
    validated = _validated_treasury_series_by_maturity(series_by_maturity)
    source_names, qualifiers = _curve_receipt_series_metadata(validated)

    observed: list[dict[str, Any]] = []
    for maturity, treasury in validated:
        if target_date in treasury.series.index:
            observed.append(
                {
                    "maturity_years": maturity,
                    "value": float(treasury.series.loc[target_date]),
                    "role": "observation",
                    "observation_date": target_date.isoformat(),
                    "unit": treasury.receipt["unit"],
                    "qualifiers": dict(treasury.receipt["qualifiers"]),
                    "source_names": list(treasury.receipt["source_names"]),
                    "evidence_tier": treasury.receipt["evidence_tier"],
                    "evidence_confidence": treasury.receipt["evidence_confidence"],
                    "maturity_binding": treasury.receipt["maturity_binding"],
                    "exact_qualifier_status": treasury.receipt["exact_qualifier_status"],
                }
            )

    observed_by_maturity = {point["maturity_years"]: point["value"] for point in observed}
    missing: list[dict[str, Any]] = []
    calculated: list[dict[str, Any]] = []
    for requested_maturity in requested_maturities:
        if (
            isinstance(requested_maturity, bool)
            or not isinstance(requested_maturity, Real)
            or not math.isfinite(float(requested_maturity))
            or float(requested_maturity) <= 0
        ):
            raise DataGateError(
                "treasury_alignment_failed",
                "Requested Treasury maturities must be positive finite numeric years.",
                {"maturity_years": requested_maturity},
            )
        target_years = float(requested_maturity)
        if target_years in observed_by_maturity:
            continue

        if interpolate:
            left = next(
                (
                    point
                    for point in reversed(observed)
                    if float(point["maturity_years"]) < target_years
                ),
                None,
            )
            right = next(
                (
                    point
                    for point in observed
                    if float(point["maturity_years"]) > target_years
                ),
                None,
            )
            if left is not None and right is not None:
                left_years = float(left["maturity_years"])
                right_years = float(right["maturity_years"])
                left_value = float(left["value"])
                right_value = float(right["value"])
                value = left_value + (
                    (target_years - left_years)
                    / (right_years - left_years)
                    * (right_value - left_value)
                )
                calculated.append(
                    {
                        "maturity_years": target_years,
                        "value": value,
                        "role": "calculation",
                        "method": "linear_maturity_interpolation",
                        "bounding_maturities": [left_years, right_years],
                        "supporting_evidence_tiers": [
                            left["evidence_tier"],
                            right["evidence_tier"],
                        ],
                        "evidence_confidence": _weakest_evidence_confidence(
                            [left, right]
                        ),
                    }
                )
                continue
        missing.append({"maturity_years": target_years, "reason": "not_observed"})

    evidence_by_maturity = _evidence_by_maturity(validated)
    overall_confidence = _weakest_evidence_confidence(
        list(evidence_by_maturity.values())
    )
    return YieldCurveResult(
        observed=observed,
        missing=missing,
        calculated=calculated,
        receipt={
            "observation_date": target_date.isoformat(),
            "source_names": source_names,
            "qualifiers": qualifiers,
            "evidence_by_maturity": evidence_by_maturity,
            "evidence_confidence": overall_confidence,
            "dependency_warning": (
                "Curve calculations inherit a lower-confidence Treasury rate input."
                if overall_confidence == "lower"
                else None
            ),
        },
    )


def build_historical_yield_curve(
    series_by_maturity: Mapping[float, TreasurySeries],
) -> HistoricalYieldCurveResult:
    """Join Treasury yields only on dates observed by every requested maturity."""
    validated = _validated_treasury_series_by_maturity(series_by_maturity)
    if not validated:
        raise DataGateError(
            "treasury_alignment_failed",
            "A historical Treasury curve requires at least one maturity series.",
        )
    maturities = [maturity for maturity, _ in validated]
    frame = pd.concat(
        [treasury.series.rename(maturity) for maturity, treasury in validated],
        axis=1,
        join="inner",
    ).sort_index()
    if frame.empty:
        raise DataGateError(
            "treasury_alignment_failed",
            "Treasury maturities have no exact common observation dates.",
            {"maturities": maturities},
        )

    source_names, qualifiers = _curve_receipt_series_metadata(validated)
    evidence_by_maturity = _evidence_by_maturity(validated)
    overall_confidence = _weakest_evidence_confidence(
        list(evidence_by_maturity.values())
    )
    return HistoricalYieldCurveResult(
        frame=frame,
        receipt={
            "alignment": "exact_common_dates",
            "maturities": maturities,
            "common_observation_count": len(frame),
            "first_date": frame.index.min().isoformat(),
            "last_date": frame.index.max().isoformat(),
            "qualifiers": qualifiers,
            "source_names": source_names,
            "evidence_by_maturity": evidence_by_maturity,
            "evidence_confidence": overall_confidence,
            "dependency_warning": (
                "Historical curve calculations inherit a lower-confidence Treasury rate input."
                if overall_confidence == "lower"
                else None
            ),
        },
    )


def _utc_datetime_index(value: pd.DatetimeIndex, label: str) -> pd.DatetimeIndex:
    if not isinstance(value, pd.DatetimeIndex) or value.empty:
        raise DataGateError(
            "treasury_alignment_failed",
            f"{label} must be a non-empty DatetimeIndex.",
        )
    try:
        normalized = pd.to_datetime(value, utc=True)
    except Exception as exc:
        raise DataGateError(
            "treasury_alignment_failed",
            f"{label} must contain valid timestamps.",
            {"error_type": exc.__class__.__name__},
        ) from exc
    return pd.DatetimeIndex(normalized).sort_values()


def align_periodic_risk_free(
    annual_percent: TreasurySeries,
    return_index: pd.DatetimeIndex,
    periods_per_year: int,
    max_fill_days: int = 3,
) -> RiskFreeResult:
    """Align annual Treasury yields without look-ahead and convert to periodic rates."""
    if (
        isinstance(periods_per_year, bool)
        or not isinstance(periods_per_year, int)
        or periods_per_year <= 0
    ):
        raise DataGateError(
            "treasury_alignment_failed",
            "periods_per_year must be a positive integer.",
            {"periods_per_year": periods_per_year},
        )
    if (
        isinstance(max_fill_days, bool)
        or not isinstance(max_fill_days, int)
        or not 0 <= max_fill_days <= 3
    ):
        raise DataGateError(
            "treasury_alignment_failed",
            "max_fill_days must be an integer from zero through three.",
            {"max_fill_days": max_fill_days},
        )
    if not isinstance(annual_percent, TreasurySeries):
        raise DataGateError(
            "treasury_alignment_failed",
            "Risk-free alignment requires normalized Treasury yield evidence.",
        )

    qualifiers = dict(annual_percent.receipt["qualifiers"])
    if qualifiers.get("time_series_operator") is not None:
        raise DataGateError(
            "treasury_alignment_failed",
            "A Treasury change series cannot be used as a risk-free yield level.",
            {"time_series_operator": qualifiers["time_series_operator"]},
        )
    treasury_series = annual_percent.series.copy().sort_index()
    treasury_series.index = _utc_datetime_index(
        pd.DatetimeIndex(treasury_series.index), "Treasury observation index"
    )
    if (treasury_series <= -100.0).any():
        raise DataGateError(
            "treasury_alignment_failed",
            "Treasury annual percentage yields must be greater than -100.",
        )
    aligned_index = _utc_datetime_index(return_index, "return_index")
    source_index = pd.DatetimeIndex(treasury_series.index)
    positions = source_index.searchsorted(aligned_index, side="right") - 1
    if (positions < 0).any():
        first_missing = aligned_index[int(np.flatnonzero(positions < 0)[0])]
        raise DataGateError(
            "treasury_alignment_failed",
            "No Treasury observation exists on or before a return date.",
            {"return_date": first_missing.isoformat()},
        )

    source_dates = source_index.take(positions)
    source_ages = (aligned_index.normalize() - source_dates.normalize()).days
    if (source_ages > max_fill_days).any():
        first_expired = int(np.flatnonzero(source_ages > max_fill_days)[0])
        raise DataGateError(
            "treasury_alignment_failed",
            "Treasury yield forward fill exceeds the permitted calendar-day limit.",
            {
                "return_date": aligned_index[first_expired].isoformat(),
                "source_date": source_dates[first_expired].isoformat(),
                "source_age_days": int(source_ages[first_expired]),
                "max_fill_days": max_fill_days,
            },
        )

    aligned_annual_percent = pd.Series(
        treasury_series.iloc[positions].to_numpy(), index=aligned_index, dtype=float
    )
    annual_decimal = aligned_annual_percent.astype(float) / 100.0
    periodic = np.power(1.0 + annual_decimal, 1.0 / periods_per_year) - 1.0
    periodic.name = "risk_free_periodic"
    direct_observation_count = int((source_ages == 0).sum())
    aligned_observation_receipt = [
        {
            "return_date": return_date.isoformat(),
            "source_date": source_date.isoformat(),
            "source_age_days": int(source_age),
            "raw_annual_percent": float(raw_annual_percent),
            "periodic_rate": float(periodic_rate),
            "rate_input_confidence": annual_percent.receipt["evidence_confidence"],
        }
        for return_date, source_date, source_age, raw_annual_percent, periodic_rate in zip(
            aligned_index,
            source_dates,
            source_ages,
            aligned_annual_percent.to_numpy(),
            periodic.to_numpy(),
            strict=True,
        )
    ]
    upstream_provenance = {
        "provider": annual_percent.receipt["provider"],
        "country_entity": annual_percent.receipt["country_entity"],
        "property": annual_percent.receipt["property"],
        "maturity_years": annual_percent.maturity_years,
        "qualifiers": qualifiers,
        "sources": list(annual_percent.receipt["sources"]),
        "evidence_tier": annual_percent.receipt["evidence_tier"],
        "evidence_confidence": annual_percent.receipt["evidence_confidence"],
        "maturity_binding": annual_percent.receipt["maturity_binding"],
        "exact_qualifier_status": annual_percent.receipt["exact_qualifier_status"],
    }
    return RiskFreeResult(
        series=periodic,
        receipt={
            "conversion": "effective_annual_to_periodic",
            "periods_per_year": periods_per_year,
            "max_fill_days": max_fill_days,
            "aligned_first_date": aligned_index.min().isoformat(),
            "aligned_last_date": aligned_index.max().isoformat(),
            "direct_observation_count": direct_observation_count,
            "filled_observation_count": len(aligned_index) - direct_observation_count,
            "aligned_observations": aligned_observation_receipt,
            "source_dates": [
                {
                    "return_date": item["return_date"],
                    "source_date": item["source_date"],
                    "source_age_days": item["source_age_days"],
                }
                for item in aligned_observation_receipt
            ],
            "unit": annual_percent.receipt["unit"],
            "retrieved_at": annual_percent.receipt["retrieved_at"],
            "requested_range": dict(annual_percent.receipt["requested_range"]),
            "observed_range": dict(annual_percent.receipt["observed_range"]),
            "evidence_kind": annual_percent.receipt["evidence_kind"],
            "evidence_tier": annual_percent.receipt["evidence_tier"],
            "evidence_confidence": annual_percent.receipt["evidence_confidence"],
            "maturity_binding": annual_percent.receipt["maturity_binding"],
            "exact_qualifier_status": annual_percent.receipt["exact_qualifier_status"],
            "missing": list(annual_percent.receipt["missing"]),
            "upstream_provenance": upstream_provenance,
            "qualifiers": qualifiers,
            "source_names": list(annual_percent.receipt["source_names"]),
            "note": (
                "Effective annual-to-periodic conversion is a disclosed analysis convention "
                "applied to the provider's annual percentage yield."
            ),
            "dependency_warning": (
                "Dependent metrics inherit a lower-confidence Treasury rate input."
                if annual_percent.receipt["evidence_confidence"] == "lower"
                else None
            ),
        },
    )


__all__ = [
    "SUPPORTED_DUE_DATES",
    "SUPPORTED_EVIDENCE_KINDS",
    "SUPPORTED_FREQUENCIES",
    "SUPPORTED_MARKETS",
    "SUPPORTED_OPERATORS",
    "SUPPORTED_SECURITY_TYPES",
    "HistoricalYieldCurveResult",
    "RiskFreeResult",
    "TreasurySeries",
    "YieldCurveResult",
    "align_periodic_risk_free",
    "build_historical_yield_curve",
    "build_yield_curve",
    "normalize_treasury_envelope",
]
