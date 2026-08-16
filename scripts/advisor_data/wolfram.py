"""Validate structured financial evidence returned by the Wolfram plugin."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping

import pandas as pd

from . import DataGateError


RECENT_PRICE_PROPERTIES = {"Price", "LatestTrade", "Close"}
TOTAL_RETURN_PROPERTY = "AdjustedClose"


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


def _coverage_status(
    series: pd.Series,
    *,
    start: str,
    end: str | None,
) -> str:
    requested_start = _utc_timestamp(start, "requested start")
    requested_end = _utc_timestamp(end, "requested end") if end is not None else None
    if requested_end is not None and requested_end < requested_start:
        raise DataGateError(
            "wolfram_schema_error",
            "Wolfram requested range ends before it starts.",
            {"start": start, "end": end},
        )

    clipped_start = series.index.min() > requested_start
    clipped_end = requested_end is not None and series.index.max() < requested_end
    if clipped_start and clipped_end:
        return "clipped_both"
    if clipped_start:
        return "clipped_start"
    if clipped_end:
        return "clipped_end"
    return "complete"


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

    if classification.get("identity_decision") != "match":
        raise DataGateError(
            "wolfram_entity_mismatch",
            "Wolfram classification evidence did not confirm identity.",
            {"identity_decision": classification.get("identity_decision")},
        )
    conflicts = classification.get("conflicts")
    if not isinstance(conflicts, list) or conflicts:
        raise DataGateError(
            "wolfram_entity_mismatch",
            "Wolfram classification evidence contains identity conflicts.",
            {"conflicts": conflicts},
        )

    result_currency = _required_text(result, "currency")
    if (
        str(classification.get("yahoo_symbol") or "") != symbol
        or str(classification.get("expected_provider_currency") or "") != result_currency
    ):
        raise DataGateError(
            "wolfram_entity_mismatch",
            "Wolfram classification evidence conflicts with the declared financial result.",
            {
                "symbol": symbol,
                "yahoo_symbol": classification.get("yahoo_symbol"),
                "expected_provider_currency": classification.get("expected_provider_currency"),
                "result_currency": result_currency,
            },
        )

    if result.get("entity_type") != "Financial":
        raise DataGateError(
            "wolfram_entity_mismatch",
            "Wolfram result is not a Financial entity.",
            {"entity_type": result.get("entity_type")},
        )
    if result.get("entity") != provider_entity:
        raise DataGateError(
            "wolfram_entity_mismatch",
            "Wolfram returned a different provider entity.",
            {"provider_entity": provider_entity, "returned_entity": result.get("entity")},
        )
    if result.get("symbol") != symbol:
        raise DataGateError(
            "wolfram_entity_mismatch",
            "Wolfram returned a different financial symbol.",
            {"symbol": symbol, "returned_symbol": result.get("symbol")},
        )

    exchange = _required_text(result, "exchange")
    security_type = _required_text(result, "security_type")
    currency = result_currency
    unit = _required_text(result, "unit")
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

    coverage_status = _coverage_status(series, start=start, end=end)
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
        "exchange": exchange,
        "security_type": security_type,
        "sources": sources,
        "observation_count": len(series),
        "requested_range": {"start": start, "end": end},
        "observed_range": {
            "start": series.index.min().isoformat(),
            "end": series.index.max().isoformat(),
        },
        "coverage_status": coverage_status,
        "retrieved_at": retrieved_at,
        "classification_evidence": dict(classification),
        "primary_failure": source.get("primary_failure"),
    }
    return WolframHistory(series=series, currency=currency, receipt=receipt)


__all__ = ["WolframHistory", "normalize_wolfram_envelope"]
