"""Validate and normalize historical evidence returned by the Alpaca plugin."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from typing import Any, Mapping

import pandas as pd

from . import DataGateError


SUPPORTED_FALLBACK_CLASSES = {"us_equity", "crypto"}


@dataclass(frozen=True)
class AlpacaHistory:
    series: pd.Series
    currency: str
    receipt: dict[str, Any]


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DataGateError(
            "alpaca_schema_error",
            f"Alpaca {label} must be a JSON object.",
            {"received_type": value.__class__.__name__},
        )
    return value


def _decoded(value: Any, label: str) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise DataGateError(
                "alpaca_schema_error",
                f"Alpaca {label} contained a non-JSON result wrapper.",
                {"error_type": exc.__class__.__name__},
            ) from exc
    return value


def _plugin_payload(value: Any, label: str) -> Mapping[str, Any]:
    payload = _mapping(_decoded(value, label), label)
    if "structuredContent" in payload:
        payload = _mapping(_decoded(payload["structuredContent"], label), label)
    if set(payload) == {"result"}:
        payload = _mapping(_decoded(payload["result"], label), label)
    return payload


def _required_text(source: Mapping[str, Any], key: str) -> str:
    value = str(source.get(key) or "").strip()
    if not value:
        raise DataGateError(
            "alpaca_schema_error",
            f"Alpaca fallback envelope is missing {key}.",
        )
    return value


def _validate_class(envelope: Mapping[str, Any]) -> str:
    fallback_class = _required_text(envelope, "fallback_class")
    if fallback_class == "ambiguous":
        raise DataGateError(
            "fallback_class_ambiguous",
            "Alpaca fallback eligibility is ambiguous.",
        )
    if fallback_class not in SUPPORTED_FALLBACK_CLASSES:
        raise DataGateError(
            "fallback_not_supported",
            f"Alpaca fallback does not support {fallback_class}.",
            {"fallback_class": fallback_class},
        )
    return fallback_class


def _validate_stock_asset(value: Any, provider_symbol: str) -> Mapping[str, Any]:
    asset = _plugin_payload(value, "asset response")
    if (
        str(asset.get("symbol") or "") != provider_symbol
        or str(asset.get("asset_class") or "") != "us_equity"
        or str(asset.get("status") or "") != "active"
    ):
        raise DataGateError(
            "alpaca_asset_not_found",
            f"Alpaca did not confirm an active U.S. equity for {provider_symbol}.",
            {
                "returned_symbol": asset.get("symbol"),
                "asset_class": asset.get("asset_class"),
                "status": asset.get("status"),
            },
        )
    return asset


def _parse_bars(
    value: Any,
    *,
    provider_symbol: str,
    expected_tool: str,
) -> tuple[pd.Series, Mapping[str, Any]]:
    payload = _plugin_payload(value, "bars response")
    if str(payload.get("tool") or "") != expected_tool:
        raise DataGateError(
            "alpaca_schema_error",
            f"Expected Alpaca {expected_tool} evidence.",
            {"returned_tool": payload.get("tool")},
        )
    request = _mapping(payload.get("request"), "bars request")
    requested_symbols = request.get("symbols")
    if not isinstance(requested_symbols, list) or provider_symbol not in {
        str(symbol) for symbol in requested_symbols
    }:
        raise DataGateError(
            "alpaca_schema_error",
            "Alpaca bars request does not contain the declared provider symbol.",
            {"provider_symbol": provider_symbol},
        )
    bars_by_symbol = _mapping(payload.get("bars"), "bars")
    raw_bars = bars_by_symbol.get(provider_symbol)
    if not isinstance(raw_bars, list) or not raw_bars:
        raise DataGateError(
            "alpaca_history_unavailable",
            f"Alpaca returned no bars for {provider_symbol}.",
        )

    observations: dict[pd.Timestamp, float] = {}
    for position, raw_bar in enumerate(raw_bars):
        item = _mapping(raw_bar, f"bar {position}")
        if str(item.get("symbol") or "") != provider_symbol:
            raise DataGateError(
                "alpaca_schema_error",
                "Alpaca returned a bar for an unrequested symbol.",
                {
                    "provider_symbol": provider_symbol,
                    "returned_symbol": item.get("symbol"),
                    "position": position,
                },
            )
        try:
            timestamp = pd.Timestamp(item.get("timestamp"))
            if timestamp.tzinfo is None:
                timestamp = timestamp.tz_localize("UTC")
            else:
                timestamp = timestamp.tz_convert("UTC")
        except Exception as exc:
            raise DataGateError(
                "alpaca_schema_error",
                "Alpaca returned an invalid bar timestamp.",
                {"position": position, "error_type": exc.__class__.__name__},
            ) from exc
        try:
            close = float(item.get("close"))
        except (TypeError, ValueError) as exc:
            raise DataGateError(
                "alpaca_schema_error",
                "Alpaca returned a non-numeric close.",
                {"position": position},
            ) from exc
        if not math.isfinite(close) or close <= 0:
            raise DataGateError(
                "alpaca_schema_error",
                "Alpaca returned a non-positive or non-finite close.",
                {"position": position, "close": item.get("close")},
            )
        if timestamp in observations and observations[timestamp] != close:
            raise DataGateError(
                "alpaca_schema_error",
                "Alpaca returned conflicting bars at the same timestamp.",
                {"timestamp": timestamp.isoformat()},
            )
        observations[timestamp] = close

    series = pd.Series(observations, dtype=float).sort_index()
    series.index = pd.DatetimeIndex(series.index)
    return series, request


def normalize_alpaca_envelope(
    envelope: Mapping[str, Any],
    start: str,
    end: str | None,
) -> AlpacaHistory:
    """Return an evidence-gated USD close series from exact Alpaca tool results."""

    source = _mapping(envelope, "fallback envelope")
    if source.get("schema_version") != 1:
        raise DataGateError(
            "alpaca_schema_error",
            "Unsupported Alpaca fallback envelope schema.",
            {"schema_version": source.get("schema_version")},
        )
    symbol = _required_text(source, "symbol")
    provider_symbol = _required_text(source, "provider_symbol")
    fallback_class = _validate_class(source)

    expected_tool = "get_crypto_bars"
    asset_receipt: dict[str, Any] | None = None
    if fallback_class == "us_equity":
        asset = _validate_stock_asset(source.get("asset_response"), provider_symbol)
        asset_receipt = {
            "asset_class": asset.get("asset_class"),
            "exchange": asset.get("exchange"),
            "status": asset.get("status"),
        }
        expected_tool = "get_stock_bars"
        if "corporate_actions_response" not in source:
            raise DataGateError(
                "corporate_actions_unavailable",
                f"Alpaca corporate actions are required for {provider_symbol}.",
            )
        _plugin_payload(source["corporate_actions_response"], "corporate actions response")

    series, request = _parse_bars(
        source.get("bars_response"),
        provider_symbol=provider_symbol,
        expected_tool=expected_tool,
    )
    series.name = symbol
    retrieved_at = datetime.now(timezone.utc).isoformat()
    receipt: dict[str, Any] = {
        "provider": "alpaca",
        "symbol": symbol,
        "provider_symbol": provider_symbol,
        "fallback_class": fallback_class,
        "classification_evidence": dict(
            _mapping(source.get("classification_evidence", {}), "classification evidence")
        ),
        "primary_failure": source.get("primary_failure"),
        "alpaca_tool": expected_tool,
        "alpaca_feed": request.get("feed"),
        "bar_timeframe": request.get("timeframe"),
        "currency": "USD",
        "price_basis": "raw_crypto_close" if fallback_class == "crypto" else "raw_stock_close",
        "raw_observation_count": len(series),
        "normalized_observation_count": len(series),
        "first_at": series.index.min().isoformat(),
        "last_at": series.index.max().isoformat(),
        "requested_start": start,
        "requested_end": end,
        "retrieved_at": retrieved_at,
    }
    if asset_receipt is not None:
        receipt["asset"] = asset_receipt
    return AlpacaHistory(series=series, currency="USD", receipt=receipt)


__all__ = ["AlpacaHistory", "normalize_alpaca_envelope"]
