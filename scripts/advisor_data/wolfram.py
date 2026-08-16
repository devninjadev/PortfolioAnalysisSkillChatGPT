"""Validate structured financial evidence returned by the Wolfram plugin."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping

import pandas as pd

from . import DataGateError


RECENT_PRICE_PROPERTIES = {"Price", "LatestTrade", "Close"}
TOTAL_RETURN_PROPERTY = "AdjustedClose"
HISTORY_ENDPOINT_TOLERANCE_DAYS = 7
RECENT_PRICE_MAX_AGE_DAYS = 7
REQUIRED_IDENTITY_FIELDS = (
    "symbol",
    "exchange",
    "issuer",
    "security_type",
    "currency",
)
SUBTYPE_IDENTITY_FIELDS = ("share_class", "instrument_subtype")
MONETARY_UNIT_CURRENCIES = {
    "USDollars": "USD",
    "Euros": "EUR",
}


@dataclass(frozen=True)
class WolframHistory:
    series: pd.Series
    currency: str
    receipt: dict[str, Any]


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DataGateError(
            "wolfram_schema_error",
            f"Wolfram {label} must be a JSON object.",
            {"received_type": value.__class__.__name__},
        )
    return value


def _required_text(source: Mapping[str, Any], key: str) -> str:
    value = str(source.get(key) or "").strip()
    if not value:
        raise DataGateError(
            "wolfram_schema_error",
            f"Wolfram evidence is missing {key}.",
        )
    return value


def _price_basis(required: str, property_name: str) -> str:
    if required == "adjusted_total_return" and property_name == TOTAL_RETURN_PROPERTY:
        return "provider_adjusted_total_return_close"
    if required == "recent_price" and property_name == "LatestTrade":
        return "latest_trade"
    if required == "recent_price" and property_name in {"Price", "Close"}:
        return "recent_close"
    raise DataGateError(
        "wolfram_property_unavailable",
        f"Wolfram property {property_name} cannot satisfy {required}.",
        {"required_price_basis": required, "property": property_name},
    )


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


def _parse_observations(value: Any, property_name: str) -> pd.Series:
    if not isinstance(value, list) or not value:
        raise DataGateError(
            "wolfram_schema_error",
            "Wolfram result observations must be a non-empty list.",
        )

    observations: dict[pd.Timestamp, float] = {}
    for position, raw_observation in enumerate(value):
        item = _mapping(raw_observation, f"observation {position}")
        timestamp = _utc_timestamp(item.get("timestamp"), f"observation {position} timestamp")
        raw_value = item.get("value")
        if isinstance(raw_value, bool):
            raise DataGateError(
                "wolfram_schema_error",
                "Wolfram observation values must be finite positive numbers.",
                {"position": position, "value": raw_value},
            )
        try:
            numeric_value = float(raw_value)
        except (TypeError, ValueError) as exc:
            raise DataGateError(
                "wolfram_schema_error",
                "Wolfram observation values must be finite positive numbers.",
                {"position": position, "value": raw_value},
            ) from exc
        if not math.isfinite(numeric_value) or numeric_value <= 0:
            raise DataGateError(
                "wolfram_schema_error",
                "Wolfram observation values must be finite positive numbers.",
                {"position": position, "value": raw_value},
            )
        if timestamp in observations and observations[timestamp] != numeric_value:
            raise DataGateError(
                "wolfram_schema_error",
                "Wolfram returned conflicting observations at the same timestamp.",
                {"timestamp": timestamp.isoformat(), "property": property_name},
            )
        observations[timestamp] = numeric_value

    series = pd.Series(observations, dtype=float).sort_index()
    series.index = pd.DatetimeIndex(series.index, tz="UTC")
    return series


def _normalized_identity_value(field: str, value: str) -> str:
    normalized = " ".join(value.split())
    if field in {"symbol", "exchange", "currency", "provider_entity"}:
        return normalized.upper()
    return normalized.casefold()


def _identity_text(identity: Mapping[str, Any], field: str, label: str) -> str:
    value = identity.get(field)
    if not isinstance(value, str) or not value.strip():
        raise DataGateError(
            "wolfram_entity_mismatch",
            f"Wolfram {label} identity is missing {field}.",
            {"identity": label, "field": field},
        )
    return value.strip()


def _compare_identity_field(
    field: str,
    expected: Mapping[str, Any],
    observed: Mapping[str, Any],
    *,
    expected_label: str,
    observed_label: str,
) -> None:
    expected_value = _identity_text(expected, field, expected_label)
    observed_value = _identity_text(observed, field, observed_label)
    if _normalized_identity_value(field, expected_value) != _normalized_identity_value(
        field, observed_value
    ):
        raise DataGateError(
            "wolfram_entity_mismatch",
            f"Wolfram structured identity conflicts on {field}.",
            {
                "field": field,
                expected_label: expected_value,
                observed_label: observed_value,
            },
        )


def _validate_structured_identity(
    classification: Mapping[str, Any],
    result: Mapping[str, Any],
    *,
    symbol: str,
    provider_entity: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        yahoo_candidate = _mapping(
            classification.get("yahoo_candidate"), "Yahoo candidate identity"
        )
        wolfram_observed = _mapping(
            classification.get("wolfram_observed"), "Wolfram observed identity"
        )
    except DataGateError as exc:
        raise DataGateError(
            "wolfram_entity_mismatch",
            "Wolfram fallback requires structured Yahoo and Wolfram identities.",
        ) from exc

    result_identity = {
        "provider_entity": result.get("entity"),
        "symbol": result.get("symbol"),
        "exchange": result.get("exchange"),
        "issuer": result.get("issuer") or result.get("company"),
        "security_type": result.get("security_type"),
        "share_class": result.get("share_class"),
        "instrument_subtype": result.get("instrument_subtype"),
        "currency": result.get("currency"),
    }
    for field in REQUIRED_IDENTITY_FIELDS:
        _compare_identity_field(
            field,
            yahoo_candidate,
            wolfram_observed,
            expected_label="yahoo_candidate",
            observed_label="wolfram_observed",
        )
        _compare_identity_field(
            field,
            wolfram_observed,
            result_identity,
            expected_label="wolfram_observed",
            observed_label="result",
        )

    subtype_fields = {
        field
        for field in SUBTYPE_IDENTITY_FIELDS
        if any(
            isinstance(identity.get(field), str) and bool(identity.get(field).strip())
            for identity in (yahoo_candidate, wolfram_observed, result_identity)
        )
    }
    if not subtype_fields:
        raise DataGateError(
            "wolfram_entity_mismatch",
            "Wolfram fallback identity requires share class or instrument subtype evidence.",
        )
    for field in sorted(subtype_fields):
        _compare_identity_field(
            field,
            yahoo_candidate,
            wolfram_observed,
            expected_label="yahoo_candidate",
            observed_label="wolfram_observed",
        )
        _compare_identity_field(
            field,
            wolfram_observed,
            result_identity,
            expected_label="wolfram_observed",
            observed_label="result",
        )

    _compare_identity_field(
        "provider_entity",
        {"provider_entity": provider_entity},
        wolfram_observed,
        expected_label="declared",
        observed_label="wolfram_observed",
    )
    _compare_identity_field(
        "provider_entity",
        wolfram_observed,
        result_identity,
        expected_label="wolfram_observed",
        observed_label="result",
    )
    _compare_identity_field(
        "symbol",
        {"symbol": symbol},
        yahoo_candidate,
        expected_label="declared",
        observed_label="yahoo_candidate",
    )
    return dict(yahoo_candidate), dict(wolfram_observed)


def _monetary_unit(value: Any, currency: str) -> tuple[str, dict[str, str]]:
    if not isinstance(value, Mapping):
        raise DataGateError(
            "wolfram_unit_mismatch",
            "Wolfram monetary unit evidence must be a structured object.",
            {"received_type": value.__class__.__name__},
        )
    name = value.get("name")
    canonical_currency = value.get("canonical_currency")
    quantity_kind = value.get("quantity_kind")
    if (
        not isinstance(name, str)
        or not name.strip()
        or not isinstance(canonical_currency, str)
        or not canonical_currency.strip()
        or quantity_kind != "monetary"
    ):
        raise DataGateError(
            "wolfram_unit_mismatch",
            "Wolfram monetary unit evidence is malformed.",
            {"unit": dict(value)},
        )
    name = name.strip()
    canonical_currency = canonical_currency.strip().upper()
    mapped_currency = MONETARY_UNIT_CURRENCIES.get(name)
    if mapped_currency is None:
        raise DataGateError(
            "wolfram_unit_mismatch",
            "Wolfram monetary unit name is not recognized by the deterministic mapping.",
            {"unit_name": name, "canonical_currency": canonical_currency},
        )
    if mapped_currency != canonical_currency or canonical_currency != currency.upper():
        raise DataGateError(
            "wolfram_unit_mismatch",
            "Wolfram monetary unit and result currency disagree.",
            {
                "unit_name": name,
                "mapped_currency": mapped_currency,
                "canonical_currency": canonical_currency,
                "result_currency": currency,
            },
        )
    return name, {
        "name": name,
        "canonical_currency": canonical_currency,
        "quantity_kind": "monetary",
    }


def _validated_request_range(
    request: Mapping[str, Any], start: str, end: str | None
) -> tuple[pd.Timestamp, pd.Timestamp | None, dict[str, str | None]]:
    request_start = _utc_timestamp(request.get("start"), "envelope request start")
    request_end = (
        _utc_timestamp(request.get("end"), "envelope request end")
        if request.get("end") is not None
        else None
    )
    cli_start = _utc_timestamp(start, "requested start")
    cli_end = _utc_timestamp(end, "requested end") if end is not None else None
    if request_end is not None and request_end < request_start:
        raise DataGateError(
            "wolfram_schema_error",
            "Wolfram requested range ends before it starts.",
            {"start": request.get("start"), "end": request.get("end")},
        )
    if request_start != cli_start or request_end != cli_end:
        raise DataGateError(
            "wolfram_request_mismatch",
            "Wolfram envelope request range does not match the CLI or workspace range.",
            {
                "envelope": {
                    "start": request_start.isoformat(),
                    "end": request_end.isoformat() if request_end is not None else None,
                },
                "caller": {
                    "start": cli_start.isoformat(),
                    "end": cli_end.isoformat() if cli_end is not None else None,
                },
            },
        )
    return request_start, request_end, {
        "start": request_start.isoformat(),
        "end": request_end.isoformat() if request_end is not None else None,
    }


def _history_coverage_status(
    series: pd.Series,
    *,
    requested_start: pd.Timestamp,
    requested_end: pd.Timestamp | None,
) -> tuple[str, dict[str, int]]:
    on_or_after_start = series.index[series.index >= requested_start]
    if on_or_after_start.empty:
        raise DataGateError(
            "wolfram_history_incomplete",
            "Wolfram AdjustedClose history has no observation on or after the requested start.",
            {
                "requested_start": requested_start.isoformat(),
                "last_observation": series.index.max().isoformat(),
                "endpoint_tolerance_days": HISTORY_ENDPOINT_TOLERANCE_DAYS,
            },
        )
    first = on_or_after_start.min()
    last = series.index.max()
    start_gap = max(0, int((first.normalize() - requested_start.normalize()).days))
    end_gap = (
        max(0, int((requested_end.normalize() - last.normalize()).days))
        if requested_end is not None
        else 0
    )
    gaps = {"start_calendar_days": start_gap, "end_calendar_days": end_gap}
    if start_gap > HISTORY_ENDPOINT_TOLERANCE_DAYS or end_gap > HISTORY_ENDPOINT_TOLERANCE_DAYS:
        raise DataGateError(
            "wolfram_history_incomplete",
            "Wolfram AdjustedClose history is materially clipped at a requested endpoint.",
            {
                **gaps,
                "endpoint_tolerance_days": HISTORY_ENDPOINT_TOLERANCE_DAYS,
                "first_observation": first.isoformat(),
                "last_observation": last.isoformat(),
            },
        )
    return ("endpoint_tolerated" if start_gap or end_gap else "complete"), gaps


def _validate_recent_freshness(
    series: pd.Series,
    requested_end: pd.Timestamp | None,
    retrieved_at: str,
) -> dict[str, Any]:
    anchor = requested_end or _utc_timestamp(retrieved_at, "retrieved_at")
    age_days = int((anchor.normalize() - series.index.max().normalize()).days)
    if age_days < 0 or age_days > RECENT_PRICE_MAX_AGE_DAYS:
        raise DataGateError(
            "wolfram_recent_price_stale",
            "Wolfram recent-price observation is outside the freshness policy.",
            {
                "observation_at": series.index.max().isoformat(),
                "freshness_anchor": anchor.isoformat(),
                "age_calendar_days": age_days,
                "max_age_days": RECENT_PRICE_MAX_AGE_DAYS,
            },
        )
    return {
        "policy": "calendar_day_recent_price_freshness",
        "max_age_days": RECENT_PRICE_MAX_AGE_DAYS,
        "age_calendar_days": age_days,
        "anchor": anchor.isoformat(),
    }


def _sources(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise DataGateError(
            "wolfram_source_unavailable",
            "Wolfram financial evidence has no source metadata.",
        )
    sources: list[dict[str, Any]] = []
    for position, raw_source in enumerate(value):
        try:
            source = _mapping(raw_source, f"source {position}")
        except DataGateError as exc:
            raise DataGateError(
                "wolfram_source_unavailable",
                "Wolfram source metadata must contain JSON objects.",
                {"position": position},
            ) from exc
        if not str(source.get("name") or "").strip():
            raise DataGateError(
                "wolfram_source_unavailable",
                "Wolfram financial evidence sources require a non-empty name.",
                {"position": position},
            )
        sources.append(dict(source))
    return sources


def normalize_wolfram_envelope(
    envelope: Mapping[str, Any],
    start: str,
    end: str | None,
) -> WolframHistory:
    """Return an evidence-gated price series from exact Wolfram tool output."""

    source = _mapping(envelope, "financial envelope")
    if source.get("schema_version") != 1:
        raise DataGateError(
            "wolfram_schema_error",
            "Unsupported Wolfram financial evidence schema.",
            {"schema_version": source.get("schema_version")},
        )
    if source.get("provider") != "wolfram":
        raise DataGateError(
            "wolfram_schema_error",
            "Wolfram financial evidence has an unexpected provider.",
            {"provider": source.get("provider")},
        )
    if source.get("evidence_kind") != "financial_history":
        raise DataGateError(
            "wolfram_schema_error",
            "Wolfram evidence kind must be financial_history.",
            {"evidence_kind": source.get("evidence_kind")},
        )

    symbol = _required_text(source, "symbol")
    provider_entity = _required_text(source, "provider_entity")
    requested_property = _required_text(source, "requested_property")
    required_price_basis = _required_text(source, "required_price_basis")
    classification = _mapping(
        source.get("classification_evidence"), "classification evidence"
    )
    result = _mapping(source.get("result"), "financial result")
    request = _mapping(source.get("request"), "financial request")
    requested_start, requested_end, requested_range = _validated_request_range(
        request, start, end
    )

    if result.get("entity_type") != "Financial":
        raise DataGateError(
            "wolfram_entity_mismatch",
            "Wolfram result is not a Financial entity.",
            {"entity_type": result.get("entity_type")},
        )
    yahoo_candidate, wolfram_observed = _validate_structured_identity(
        classification,
        result,
        symbol=symbol,
        provider_entity=provider_entity,
    )
    result_currency = _required_text(result, "currency")
    exchange = _required_text(result, "exchange")
    security_type = _required_text(result, "security_type")
    currency = result_currency
    unit, unit_evidence = _monetary_unit(result.get("unit"), result_currency)
    retrieved_at = _required_text(source, "retrieved_at")
    sources = _sources(source.get("sources"))

    observed_property = _required_text(result, "property")
    if observed_property != requested_property:
        raise DataGateError(
            "wolfram_property_unavailable",
            "Wolfram returned a property different from the requested property.",
            {"requested_property": requested_property, "property": observed_property},
        )
    price_basis = _price_basis(required_price_basis, observed_property)
    series = _parse_observations(result.get("observations"), observed_property)
    if required_price_basis == "adjusted_total_return" and len(series) < 2:
        raise DataGateError(
            "wolfram_schema_error",
            "Wolfram adjusted total-return history requires at least two observations.",
            {"observation_count": len(series)},
        )
    if required_price_basis == "recent_price" and len(series) < 1:
        raise DataGateError(
            "wolfram_schema_error",
            "Wolfram recent-price evidence requires an observation.",
        )

    if required_price_basis == "adjusted_total_return":
        coverage_status, coverage_gaps = _history_coverage_status(
            series,
            requested_start=requested_start,
            requested_end=requested_end,
        )
        freshness_policy = None
    else:
        coverage_status = "recent_price_freshness_validated"
        coverage_gaps = None
        freshness_policy = _validate_recent_freshness(
            series, requested_end, retrieved_at
        )
    series.name = symbol
    receipt: dict[str, Any] = {
        "provider": "wolfram",
        "symbol": symbol,
        "provider_entity": provider_entity,
        "property": observed_property,
        "required_price_basis": required_price_basis,
        "price_basis": price_basis,
        "currency": currency,
        "unit": unit,
        "unit_evidence": unit_evidence,
        "exchange": exchange,
        "security_type": security_type,
        "sources": sources,
        "observation_count": len(series),
        "requested_range": requested_range,
        "observed_range": {
            "start": series.index.min().isoformat(),
            "end": series.index.max().isoformat(),
        },
        "coverage_status": coverage_status,
        "coverage_gaps": coverage_gaps,
        "coverage_policy": "market_calendar_endpoint_tolerance",
        "endpoint_tolerance_days": HISTORY_ENDPOINT_TOLERANCE_DAYS,
        "recent_price_freshness": freshness_policy,
        "retrieved_at": retrieved_at,
        "classification_evidence": {
            **dict(classification),
            "yahoo_candidate": yahoo_candidate,
            "wolfram_observed": wolfram_observed,
        },
        "primary_failure": source.get("primary_failure"),
    }
    return WolframHistory(series=series, currency=currency, receipt=receipt)


__all__ = ["WolframHistory", "normalize_wolfram_envelope"]
