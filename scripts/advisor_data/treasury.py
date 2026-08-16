"""Validate U.S. Treasury evidence and derive disclosed calculations."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping, Sequence

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


@dataclass(frozen=True)
class TreasurySeries:
    series: pd.Series
    maturity_years: float
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
    if isinstance(value, bool):
        raise DataGateError(
            "wolfram_schema_error",
            f"Wolfram {label} must be a finite numeric value.",
            {"value": value},
        )
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise DataGateError(
            "wolfram_schema_error",
            f"Wolfram {label} must be a finite numeric value.",
            {"value": value},
        ) from exc
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
    allowed = {
        "security_type",
        "maturity_duration",
        "market",
        "due_date",
        "frequency",
        "time_series_operator",
        "coupon_rate",
    }
    preserved = dict(qualifiers)
    for key in qualifiers:
        if key not in allowed:
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


def _qualifier_agreement(
    declared: Mapping[str, Any], request: Mapping[str, Any], result: Mapping[str, Any]
) -> None:
    nested: list[tuple[str, Mapping[str, Any]]] = []
    for label, value in (("request", request), ("result", result)):
        for key in ("qualifiers", "requested_qualifiers", "observed_qualifiers"):
            if key in value:
                nested.append((f"{label}.{key}", _mapping(value[key], f"{label} {key}")))
    for label, qualifiers in nested:
        for key, value in qualifiers.items():
            if key not in declared or value != declared[key]:
                raise DataGateError(
                    "wolfram_qualifier_mismatch",
                    "Wolfram Treasury requested and observed qualifiers disagree.",
                    {"qualifier": key, "declared": declared.get(key), label: value},
                )
    for label, value in (("request", request), ("result", result)):
        for key in declared:
            if key in value and value[key] != declared[key]:
                raise DataGateError(
                    "wolfram_qualifier_mismatch",
                    "Wolfram Treasury requested and observed qualifiers disagree.",
                    {"qualifier": key, "declared": declared[key], label: value[key]},
                )
    result_maturity = result.get("maturity_duration")
    if result_maturity is not None and result_maturity != declared.get("maturity_duration"):
        raise DataGateError(
            "wolfram_qualifier_mismatch",
            "Wolfram Treasury result maturity differs from the requested maturity.",
            {"requested": declared.get("maturity_duration"), "observed": result_maturity},
        )


def _missing_names_requested(missing: Sequence[Any], requested: str) -> bool:
    """Treat an explicit maturity miss as a hard maturity-unavailable gate.

    The marker's value is retained verbatim; a different maturity is never
    silently substituted for the requested series.
    """
    for item in missing:
        if isinstance(item, Mapping) and "maturity_duration" in item:
            return True
        if isinstance(item, str) and item == requested:
            return True
    return False


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
    if source.get("country_entity") != "UnitedStates":
        raise DataGateError(
            "wolfram_entity_mismatch",
            "Wolfram Treasury evidence is not for UnitedStates.",
            {"country_entity": source.get("country_entity")},
        )

    qualifiers = _validate_qualifiers(_mapping(source.get("qualifiers"), "Treasury qualifiers"))
    request = _mapping(source.get("request"), "Treasury request")
    result = _mapping(source.get("result"), "Treasury result")
    _qualifier_agreement(qualifiers, request, result)
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
    maturity_years = _finite_number(
        result.get("maturity_years"), "Treasury maturity_years", positive=True
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
        "sources": sources,
        "source_names": [str(item["name"]) for item in sources],
        "observation_count": len(series),
        "requested_range": requested_range,
        "observed_range": observed_range,
        "coverage_status": _coverage_status(series, requested_range),
        "missing": list(missing),
        "retrieved_at": retrieved_at,
    }
    return TreasurySeries(series=series, maturity_years=maturity_years, receipt=receipt)


__all__ = [
    "SUPPORTED_DUE_DATES",
    "SUPPORTED_EVIDENCE_KINDS",
    "SUPPORTED_FREQUENCIES",
    "SUPPORTED_MARKETS",
    "SUPPORTED_OPERATORS",
    "SUPPORTED_SECURITY_TYPES",
    "TreasurySeries",
    "normalize_treasury_envelope",
]
