"""Validate and normalize historical evidence returned by the Alpaca plugin."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import math
from typing import Any, Mapping

import pandas as pd

from . import DataGateError


SUPPORTED_FALLBACK_CLASSES = {"us_equity", "crypto"}
SUPPORTED_CORPORATE_ACTION_GROUPS = {
    "cash_dividends",
    "forward_splits",
    "reverse_splits",
}


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
) -> tuple[pd.Series, Mapping[str, Any], int]:
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
    duplicate_count = 0
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
        if timestamp in observations:
            if observations[timestamp] != close:
                raise DataGateError(
                    "alpaca_schema_error",
                    "Alpaca returned conflicting bars at the same timestamp.",
                    {"timestamp": timestamp.isoformat()},
                )
            duplicate_count += 1
        observations[timestamp] = close

    series = pd.Series(observations, dtype=float).sort_index()
    series.index = pd.DatetimeIndex(series.index)
    if len(series) < 2:
        raise DataGateError(
            "alpaca_history_incomplete",
            f"Alpaca returned fewer than two observations for {provider_symbol}.",
            {"observation_count": len(series)},
        )
    return series, request, duplicate_count


def _utc_timestamp(value: Any, label: str) -> pd.Timestamp:
    try:
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is None:
            return timestamp.tz_localize("UTC")
        return timestamp.tz_convert("UTC")
    except Exception as exc:
        raise DataGateError(
            "corporate_action_adjustment_failed",
            f"Alpaca returned an invalid {label}.",
            {"value": value, "error_type": exc.__class__.__name__},
        ) from exc


def _action_items(
    announcements: Mapping[str, Any],
    key: str,
) -> list[Mapping[str, Any]]:
    value = announcements.get(key, [])
    if value is None:
        return []
    if not isinstance(value, list):
        raise DataGateError(
            "corporate_action_adjustment_failed",
            f"Alpaca {key} announcements must be a list.",
        )
    return [_mapping(item, f"{key} announcement") for item in value]


def _validate_corporate_actions_evidence(
    payload: Mapping[str, Any],
    provider_symbol: str,
    series: pd.Series,
) -> dict[str, Any]:
    request = _mapping(payload.get("request"), "corporate actions request")
    symbols = request.get("symbols")
    if (
        not isinstance(symbols, list)
        or {str(symbol) for symbol in symbols} != {provider_symbol}
    ):
        raise DataGateError(
            "corporate_action_adjustment_failed",
            "Alpaca corporate actions were not requested for exactly the declared asset.",
            {"provider_symbol": provider_symbol, "requested_symbols": symbols},
        )
    if "ca_types" not in request or request.get("ca_types") is not None:
        raise DataGateError(
            "corporate_action_adjustment_failed",
            "Alpaca corporate actions must be requested without a type filter.",
            {"ca_types": request.get("ca_types")},
        )
    raw_start = str(request.get("start") or "").strip()
    raw_end = str(request.get("end") or "").strip()
    if not raw_start or not raw_end:
        raise DataGateError(
            "corporate_action_adjustment_failed",
            "Alpaca corporate actions request must preserve start and end dates.",
        )
    request_start = _utc_timestamp(raw_start, "corporate actions request start")
    request_end = _utc_timestamp(raw_end, "corporate actions request end")
    observed_start = pd.Timestamp(series.index.min())
    observed_end = pd.Timestamp(series.index.max())
    if (
        request_start.date() > observed_start.date()
        or request_end.date() < observed_end.date()
    ):
        raise DataGateError(
            "corporate_action_adjustment_failed",
            "Alpaca corporate actions do not cover the observed stock history.",
            {
                "request_start": raw_start,
                "request_end": raw_end,
                "observed_start": observed_start.date().isoformat(),
                "observed_end": observed_end.date().isoformat(),
            },
        )
    if payload.get("next_page_token"):
        raise DataGateError(
            "corporate_action_adjustment_failed",
            "Alpaca corporate actions evidence is paginated and incomplete.",
        )

    announcements = _mapping(
        payload.get("announcements", {}),
        "corporate action announcements",
    )
    unsupported = sorted(
        key
        for key, value in announcements.items()
        if key not in SUPPORTED_CORPORATE_ACTION_GROUPS and value not in (None, [])
    )
    if unsupported:
        raise DataGateError(
            "corporate_action_adjustment_failed",
            "Alpaca returned corporate actions that the price adapter cannot safely adjust.",
            {"unsupported_action_groups": unsupported},
        )
    return {
        "symbols": [provider_symbol],
        "start": raw_start,
        "end": raw_end,
        "all_types_requested": True,
    }


def _adjust_stock_close(
    series: pd.Series,
    actions_payload: Mapping[str, Any],
    provider_symbol: str,
    timeframe: str,
) -> tuple[pd.Series, list[dict[str, Any]]]:
    announcements = _mapping(
        actions_payload.get("announcements", {}),
        "corporate action announcements",
    )
    actions: list[tuple[pd.Timestamp, str, Mapping[str, Any]]] = []
    for key in ("forward_splits", "reverse_splits"):
        for item in _action_items(announcements, key):
            actions.append((_utc_timestamp(item.get("ex_date"), "split ex-date"), key, item))
    for item in _action_items(announcements, "cash_dividends"):
        actions.append((_utc_timestamp(item.get("ex_date"), "dividend ex-date"), "cash_dividend", item))
    actions.sort(key=lambda action: action[0])

    adjusted = series.astype(float).copy()
    applied: list[dict[str, Any]] = []
    for ex_date, action_type, item in actions:
        if str(item.get("symbol") or "") != provider_symbol:
            raise DataGateError(
                "corporate_action_adjustment_failed",
                "Alpaca corporate action symbol does not match the requested asset.",
                {
                    "provider_symbol": provider_symbol,
                    "returned_symbol": item.get("symbol"),
                    "action_type": action_type,
                },
            )
        if action_type in {"forward_splits", "reverse_splits"}:
            try:
                old_rate = float(item.get("old_rate"))
                new_rate = float(item.get("new_rate"))
            except (TypeError, ValueError) as exc:
                raise DataGateError(
                    "corporate_action_adjustment_failed",
                    "Alpaca split rates must be numeric.",
                    {"ex_date": ex_date.date().isoformat()},
                ) from exc
            factor = old_rate / new_rate if new_rate else float("nan")
            if not math.isfinite(factor) or factor <= 0:
                raise DataGateError(
                    "corporate_action_adjustment_failed",
                    "Alpaca split rates produced an invalid adjustment factor.",
                    {
                        "old_rate": item.get("old_rate"),
                        "new_rate": item.get("new_rate"),
                        "ex_date": ex_date.date().isoformat(),
                    },
                )
            adjusted.loc[adjusted.index < ex_date] *= factor
        else:
            try:
                rate = float(item.get("rate"))
            except (TypeError, ValueError) as exc:
                raise DataGateError(
                    "corporate_action_adjustment_failed",
                    "Alpaca cash dividend rate must be numeric.",
                    {"ex_date": ex_date.date().isoformat()},
                ) from exc
            if not math.isfinite(rate) or rate < 0:
                raise DataGateError(
                    "corporate_action_adjustment_failed",
                    "Alpaca cash dividend rate is invalid.",
                    {"rate": item.get("rate"), "ex_date": ex_date.date().isoformat()},
                )
            boundary = ex_date
            if str(timeframe).lower() in {"1week", "1w"}:
                boundary = ex_date - pd.Timedelta(days=ex_date.weekday())
            prior = adjusted.loc[adjusted.index < boundary]
            if prior.empty:
                raise DataGateError(
                    "corporate_action_adjustment_failed",
                    "No complete pre-ex-date bar is available for a cash dividend.",
                    {"ex_date": ex_date.date().isoformat(), "timeframe": timeframe},
                )
            pre_close = float(prior.iloc[-1])
            factor = (pre_close - rate) / pre_close
            if not math.isfinite(factor) or factor <= 0 or factor > 1:
                raise DataGateError(
                    "corporate_action_adjustment_failed",
                    "Alpaca cash dividend produced an invalid adjustment factor.",
                    {
                        "rate": rate,
                        "pre_close": pre_close,
                        "ex_date": ex_date.date().isoformat(),
                    },
                )
            adjusted.loc[adjusted.index < boundary] *= factor
        applied.append(
            {
                "type": (
                    "cash_dividend"
                    if action_type == "cash_dividend"
                    else action_type.removesuffix("s")
                ),
                "ex_date": ex_date.date().isoformat(),
                "factor": factor,
                "status": "applied",
            }
        )
    return adjusted, applied


def _coverage_receipt(
    series: pd.Series,
    *,
    start: str,
    end: str | None,
    timeframe: str,
) -> tuple[str, list[str]]:
    requested_start = _utc_timestamp(start, "requested start")
    requested_end = _utc_timestamp(end, "requested end") if end else None
    tolerance = timedelta(days=8 if str(timeframe).lower() in {"1week", "1w"} else 2)
    gaps: list[str] = []
    if series.index.min().to_pydatetime() > (requested_start.to_pydatetime() + tolerance):
        gaps.append("starts_after_requested_start")
    if (
        requested_end is not None
        and series.index.max().to_pydatetime() < (requested_end.to_pydatetime() - tolerance)
    ):
        gaps.append("ends_before_requested_end")
    return ("clipped" if gaps else "complete"), gaps


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
    paper_receipts = None
    if source.get("connector_id") == "asdk_app_6a3cdf9e34b881918505f1cd5e06dbd8":
        from .paper_alpaca import adapt_paper_envelope
        source, paper_receipts = adapt_paper_envelope(source)
    elif "paper_calls" in source:
        raise DataGateError("alpaca_schema_error", "Unknown Paper connector identity.", {})
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
        actions_payload = _plugin_payload(
            source["corporate_actions_response"],
            "corporate actions response",
        )
    else:
        actions_payload = {}

    series, request, duplicate_count = _parse_bars(
        source.get("bars_response"),
        provider_symbol=provider_symbol,
        expected_tool=expected_tool,
    )
    applied_actions: list[dict[str, Any]] = []
    actions_request_receipt: dict[str, Any] | None = None
    if fallback_class == "us_equity":
        actions_request_receipt = _validate_corporate_actions_evidence(
            actions_payload,
            provider_symbol,
            series,
        )
        series, applied_actions = _adjust_stock_close(
            series,
            actions_payload,
            provider_symbol,
            str(request.get("timeframe") or ""),
        )
    series.name = symbol
    coverage_status, coverage_gaps = _coverage_receipt(
        series,
        start=start,
        end=end,
        timeframe=str(request.get("timeframe") or ""),
    )
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
        "price_basis": (
            "raw_crypto_close"
            if fallback_class == "crypto"
            else "corporate_action_adjusted_close"
        ),
        "raw_observation_count": len(series) + duplicate_count,
        "normalized_observation_count": len(series),
        "duplicate_observation_count": duplicate_count,
        "first_at": series.index.min().isoformat(),
        "last_at": series.index.max().isoformat(),
        "coverage_status": coverage_status,
        "coverage_gaps": coverage_gaps,
        "requested_start": start,
        "requested_end": end,
        "retrieved_at": retrieved_at,
    }
    if paper_receipts is not None:
        receipt["connector_id"] = source["connector_id"]
        receipt["connector_name"] = "Alpaca Paper Trading"
        receipt["connector_failure"] = source["connector_failure"]
        receipt["paper_calls"] = paper_receipts
    if asset_receipt is not None:
        receipt["asset"] = asset_receipt
        receipt["corporate_actions_request"] = actions_request_receipt
        receipt["corporate_actions_applied"] = applied_actions
    return AlpacaHistory(series=series, currency="USD", receipt=receipt)


__all__ = ["AlpacaHistory", "normalize_alpaca_envelope"]
