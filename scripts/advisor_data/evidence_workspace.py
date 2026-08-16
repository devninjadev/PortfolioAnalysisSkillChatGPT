"""Persist Yahoo evidence and merge validated model-supplied provider fallbacks."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path
import tempfile
from typing import Any, Callable, Mapping, Sequence

import pandas as pd
import yfinance as yf

from . import DataGateError
from .alpaca import normalize_alpaca_envelope
from .market_data import (
    MarketBundle,
    YAHOO_STAGE_ASSET_PRICE,
    YAHOO_STAGE_CURRENCY_METADATA,
    YAHOO_STAGE_FX_HISTORY,
    _currency_spec,
    download_currency_bridge,
    download_market_bundle,
)
from .wolfram import normalize_wolfram_envelope
from .wolfram_fx import normalize_wolfram_fx_envelope


WORKSPACE_SCHEMA_VERSION = 1
FALLBACK_ELIGIBLE_PRICE_CODES = frozenset(
    {"price_history_unavailable", "network_error"}
)


def _is_fallback_eligible_yahoo_failure(exc: DataGateError) -> bool:
    """Admit only failures proven to originate in Yahoo asset-price retrieval."""

    stage = exc.details.get("stage")
    if stage is not None:
        return (
            stage == YAHOO_STAGE_ASSET_PRICE
            and exc.code in FALLBACK_ELIGIBLE_PRICE_CODES
        )
    return exc.code == "price_history_unavailable"


def _error_payload(exc: DataGateError) -> dict[str, Any]:
    return {"code": exc.code, "message": exc.message, "details": exc.details}


def _serialize_series(series: pd.Series, name: str) -> dict[str, Any]:
    if not isinstance(series.index, pd.DatetimeIndex):
        raise DataGateError(
            "evidence_workspace_invalid",
            f"Evidence series {name} must use a DatetimeIndex.",
        )
    numeric = pd.to_numeric(series, errors="coerce")
    observations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for timestamp, raw_value in numeric.sort_index().items():
        stamp = pd.Timestamp(timestamp)
        if stamp.tzinfo is None:
            stamp = stamp.tz_localize("UTC")
        else:
            stamp = stamp.tz_convert("UTC")
        stamp_text = stamp.isoformat()
        value = float(raw_value)
        if stamp_text in seen or not math.isfinite(value) or value <= 0:
            raise DataGateError(
                "evidence_workspace_invalid",
                f"Evidence series {name} contains an invalid observation.",
                {"timestamp": stamp_text, "value": raw_value},
            )
        seen.add(stamp_text)
        observations.append({"timestamp": stamp_text, "value": value})
    if not observations:
        raise DataGateError(
            "evidence_workspace_invalid",
            f"Evidence series {name} is empty.",
        )
    return {"name": name, "observations": observations}


def _deserialize_series(payload: Any, expected_name: str) -> pd.Series:
    if not isinstance(payload, Mapping):
        raise DataGateError(
            "evidence_workspace_invalid",
            f"Evidence series {expected_name} must be an object.",
        )
    observations = payload.get("observations")
    if not isinstance(observations, list) or not observations:
        raise DataGateError(
            "evidence_workspace_invalid",
            f"Evidence series {expected_name} has no observations.",
        )
    values: dict[pd.Timestamp, float] = {}
    for position, observation in enumerate(observations):
        if not isinstance(observation, Mapping):
            raise DataGateError(
                "evidence_workspace_invalid",
                f"Evidence observation {position} for {expected_name} is malformed.",
            )
        try:
            timestamp = pd.Timestamp(observation.get("timestamp"))
            if timestamp.tzinfo is None:
                timestamp = timestamp.tz_localize("UTC")
            else:
                timestamp = timestamp.tz_convert("UTC")
            value = float(observation.get("value"))
        except Exception as exc:
            raise DataGateError(
                "evidence_workspace_invalid",
                f"Evidence observation {position} for {expected_name} is invalid.",
                {"error_type": exc.__class__.__name__},
            ) from exc
        if timestamp in values or not math.isfinite(value) or value <= 0:
            raise DataGateError(
                "evidence_workspace_invalid",
                f"Evidence observation {position} for {expected_name} is unsafe.",
            )
        values[timestamp] = value
    result = pd.Series(values, dtype=float).sort_index()
    result.index = pd.DatetimeIndex(result.index)
    result.name = expected_name
    return result


def _merge_fx(
    destination: dict[str, pd.Series],
    currency: str,
    incoming: pd.Series,
) -> None:
    if currency not in destination:
        destination[currency] = incoming.astype(float).copy()
        return
    existing = destination[currency]
    overlap = existing.dropna().index.intersection(incoming.dropna().index)
    if any(
        not math.isclose(float(existing.loc[index]), float(incoming.loc[index]), rel_tol=1e-10)
        for index in overlap
    ):
        raise DataGateError(
            "evidence_workspace_invalid",
            f"Yahoo returned conflicting FX observations for {currency}.",
        )
    destination[currency] = existing.combine_first(incoming).sort_index()


def _download_yahoo_currency_metadata(symbol: str) -> tuple[str, dict[str, Any]]:
    """Retrieve Yahoo currency metadata independently of asset price history."""

    try:
        metadata = yf.Ticker(symbol).get_history_metadata() or {}
    except Exception as exc:
        raise DataGateError(
            "currency_unavailable",
            f"Yahoo currency metadata failed for {symbol}.",
            {
                "stage": YAHOO_STAGE_CURRENCY_METADATA,
                "error_type": exc.__class__.__name__,
            },
        ) from exc
    raw_currency = str(metadata.get("currency") or "").strip()
    try:
        normalized_currency, _, source_unit = _currency_spec(raw_currency)
    except DataGateError as exc:
        raise DataGateError(
            "currency_unavailable",
            f"Yahoo currency metadata is unusable for {symbol}: {raw_currency or 'missing'}",
            {"stage": YAHOO_STAGE_CURRENCY_METADATA},
        ) from exc
    return raw_currency, {
        "source": "Yahoo Finance via yfinance",
        "evidence_kind": "asset_currency_metadata",
        "symbol": symbol,
        "currency": raw_currency,
        "normalized_currency": normalized_currency,
        "source_currency_unit": source_unit,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }


def _validated_currency_evidence(
    symbol: str,
    value: Any,
) -> tuple[str, dict[str, Any]]:
    if not isinstance(value, tuple) or len(value) != 2:
        raise DataGateError(
            "currency_unavailable",
            f"Yahoo currency loader returned malformed evidence for {symbol}.",
            {"stage": YAHOO_STAGE_CURRENCY_METADATA},
        )
    raw_currency, raw_receipt = value
    try:
        normalized_currency, _, source_unit = _currency_spec(raw_currency)
    except DataGateError as exc:
        raise DataGateError(
            "currency_unavailable",
            f"Yahoo currency metadata is unusable for {symbol}: {raw_currency or 'missing'}",
            {"stage": YAHOO_STAGE_CURRENCY_METADATA},
        ) from exc
    if not isinstance(raw_receipt, Mapping):
        raise DataGateError(
            "currency_unavailable",
            f"Yahoo currency receipt is malformed for {symbol}.",
            {"stage": YAHOO_STAGE_CURRENCY_METADATA},
        )
    receipt = dict(raw_receipt)
    receipt.update(
        {
            "evidence_kind": "asset_currency_metadata",
            "symbol": symbol,
            "currency": str(raw_currency),
            "normalized_currency": normalized_currency,
            "source_currency_unit": source_unit,
        }
    )
    return str(raw_currency), receipt


def prepare_yahoo_workspace(
    symbols: list[str],
    start: str,
    end: str | None,
    base_currency: str,
    market_loader: Callable[..., MarketBundle] | None = None,
    base_fx_loader: Callable[..., tuple[pd.Series, dict[str, str]]] | None = None,
    currency_loader: Callable[..., tuple[str, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Collect Yahoo successes per symbol without losing them to another symbol's failure."""

    ordered_symbols = list(dict.fromkeys(str(symbol).strip() for symbol in symbols if str(symbol).strip()))
    if not ordered_symbols:
        raise DataGateError("insufficient_assets", "At least one symbol is required.")
    active_market_loader = market_loader or download_market_bundle
    active_base_fx_loader = base_fx_loader or download_currency_bridge
    active_currency_loader = currency_loader or _download_yahoo_currency_metadata
    base, base_scale, _ = _currency_spec(base_currency)
    if base_scale != 1.0:
        raise DataGateError("unsupported_currency", "Base currency must be a major currency unit.")

    assets: dict[str, dict[str, Any]] = {}
    failures: dict[str, dict[str, Any]] = {}
    fx_series: dict[str, pd.Series] = {}
    fx_receipts: dict[str, dict[str, Any]] = {}
    fx_failures: dict[str, dict[str, Any]] = {}
    yahoo_currency_evidence: dict[str, dict[str, Any]] = {}
    for symbol in ordered_symbols:
        try:
            bundle = active_market_loader(
                symbols=[symbol],
                start=start,
                end=end,
                base_currency=base,
            )
            if symbol not in bundle.prices or symbol not in bundle.currencies:
                raise DataGateError(
                    "price_history_unavailable",
                    f"Yahoo per-symbol bundle omitted {symbol}.",
                    {"stage": YAHOO_STAGE_ASSET_PRICE},
                )
            assets[symbol] = {
                "currency": bundle.currencies[symbol],
                "prices": _serialize_series(bundle.prices[symbol], symbol),
                "receipt": bundle.receipt,
            }
            normalized_currency, _, source_unit = _currency_spec(bundle.currencies[symbol])
            yahoo_currency_evidence[symbol] = {
                "source": "Yahoo Finance via yfinance",
                "evidence_kind": "asset_currency_metadata",
                "symbol": symbol,
                "currency": bundle.currencies[symbol],
                "normalized_currency": normalized_currency,
                "source_currency_unit": source_unit,
                "retrieved_at": bundle.receipt.get("retrieved_at"),
            }
            for currency, series in bundle.fx_prices.items():
                _merge_fx(fx_series, str(currency).upper(), series)
            for currency, receipt in bundle.receipt.get("fx_pairs", {}).items():
                fx_receipts[str(currency).upper()] = dict(receipt)
            for currency, failure in bundle.receipt.get("fx_failures", {}).items():
                if isinstance(failure, Mapping):
                    fx_failures[str(currency).upper()] = dict(failure)
        except DataGateError as exc:
            if not _is_fallback_eligible_yahoo_failure(exc):
                raise
            failures[symbol] = _error_payload(exc)
            try:
                raw_currency, receipt = _validated_currency_evidence(
                    symbol,
                    active_currency_loader(symbol=symbol),
                )
            except DataGateError:
                failures.pop(symbol, None)
                raise
            except Exception as currency_exc:
                failures.pop(symbol, None)
                raise DataGateError(
                    "currency_unavailable",
                    f"Yahoo currency metadata failed for {symbol}.",
                    {
                        "stage": YAHOO_STAGE_CURRENCY_METADATA,
                        "error_type": currency_exc.__class__.__name__,
                    },
                ) from currency_exc
            yahoo_currency_evidence[symbol] = {"currency": raw_currency, **receipt}
        except Exception as exc:
            raise DataGateError(
                "network_error",
                f"Yahoo per-symbol retrieval failed for {symbol}.",
                {"stage": "market_bundle", "error_type": exc.__class__.__name__},
            ) from exc

    currency_by_symbol = {
        symbol: str(evidence.get("currency") or "")
        for symbol, evidence in yahoo_currency_evidence.items()
    }
    required_fx = _required_fx(currency_by_symbol, base)
    for required_currency in sorted(required_fx - set(fx_series)):
        try:
            series, receipt = active_base_fx_loader(
                currency=required_currency,
                start=start,
                end=end,
            )
            _merge_fx(fx_series, required_currency, series)
            fx_receipts[required_currency] = dict(receipt)
            fx_failures.pop(required_currency, None)
        except DataGateError as exc:
            fx_failures[required_currency] = _error_payload(exc)
        except Exception as exc:
            fx_failures[required_currency] = {
                "code": "fx_history_unavailable",
                "message": f"Yahoo FX retrieval failed for {required_currency}.",
                "details": {
                    "stage": YAHOO_STAGE_FX_HISTORY,
                    "error_type": exc.__class__.__name__,
                },
            }

    retrieved_at = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": WORKSPACE_SCHEMA_VERSION,
        "symbols": ordered_symbols,
        "start": start,
        "end": end,
        "base_currency": base,
        "assets": assets,
        "failures": failures,
        "yahoo_currency_evidence": yahoo_currency_evidence,
        "fx_prices": {
            currency: _serialize_series(series, str(series.name or currency))
            for currency, series in sorted(fx_series.items())
        },
        "fx_receipts": fx_receipts,
        "fx_failures": fx_failures,
        "fallback_required_fx": sorted(required_fx - set(fx_series)),
        "retrieved_at": retrieved_at,
    }


def write_workspace(path: Path, workspace: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(workspace, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
        temporary.replace(target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def read_workspace(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataGateError(
            "evidence_workspace_invalid",
            "The evidence workspace could not be read.",
            {"error_type": exc.__class__.__name__},
        ) from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != WORKSPACE_SCHEMA_VERSION:
        raise DataGateError(
            "evidence_workspace_invalid",
            "The evidence workspace schema is unsupported.",
            {"schema_version": payload.get("schema_version") if isinstance(payload, dict) else None},
        )
    for key in ("symbols", "assets", "failures", "fx_prices", "base_currency", "start"):
        if key not in payload:
            raise DataGateError(
                "evidence_workspace_invalid",
                f"The evidence workspace is missing {key}.",
            )
    return payload


def _required_fx(currencies: Mapping[str, str], base_currency: str) -> set[str]:
    base, _, _ = _currency_spec(base_currency)
    required: set[str] = set()
    for raw_currency in currencies.values():
        currency, _, _ = _currency_spec(raw_currency)
        if currency == base:
            continue
        if currency != "USD":
            required.add(currency)
        if base != "USD":
            required.add(base)
    return required


def _envelope_provider(envelope: Mapping[str, Any]) -> str:
    declared = str(envelope.get("provider") or "").strip().lower()
    if declared:
        return declared
    if "fallback_class" in envelope:
        return "alpaca"
    raise DataGateError(
        "evidence_workspace_invalid",
        "Fallback evidence does not declare a provider.",
    )


def complete_market_bundle(
    workspace: Mapping[str, Any],
    envelopes: Sequence[Mapping[str, Any]],
    fx_envelopes: Sequence[Mapping[str, Any]] = (),
    normalizers: Mapping[str, Callable[..., Any]] | None = None,
    fx_normalizer: Callable[..., Any] | None = None,
) -> MarketBundle:
    """Merge Yahoo evidence with one validated provider fallback per failed symbol."""

    if workspace.get("schema_version") != WORKSPACE_SCHEMA_VERSION:
        raise DataGateError("evidence_workspace_invalid", "Unsupported evidence workspace schema.")
    symbols = [str(symbol) for symbol in workspace.get("symbols", [])]
    assets = workspace.get("assets", {})
    failures = workspace.get("failures", {})
    yahoo_currency_evidence = workspace.get("yahoo_currency_evidence", {})
    if (
        not isinstance(assets, Mapping)
        or not isinstance(failures, Mapping)
        or not isinstance(yahoo_currency_evidence, Mapping)
    ):
        raise DataGateError("evidence_workspace_invalid", "Workspace assets and failures must be objects.")

    active_normalizers = dict(
        normalizers
        or {
            "alpaca": normalize_alpaca_envelope,
            "wolfram": normalize_wolfram_envelope,
        }
    )
    envelopes_by_symbol: dict[str, tuple[str, Mapping[str, Any]]] = {}
    for envelope in envelopes:
        if not isinstance(envelope, Mapping):
            raise DataGateError("alpaca_schema_error", "Alpaca input must be an object.")
        symbol = str(envelope.get("symbol") or "")
        if symbol not in failures:
            raise DataGateError(
                "evidence_workspace_invalid",
                f"Fallback input for unrequested symbol {symbol or 'missing'} was supplied.",
            )
        provider = _envelope_provider(envelope)
        if provider not in active_normalizers:
            raise DataGateError(
                "fallback_not_supported",
                f"No validated fallback adapter is available for {provider}.",
                {"provider": provider, "symbol": symbol},
            )
        if symbol in envelopes_by_symbol:
            raise DataGateError(
                "evidence_workspace_invalid",
                f"Duplicate fallback inputs were supplied for {symbol}.",
            )
        envelopes_by_symbol[symbol] = (provider, envelope)

    price_series: dict[str, pd.Series] = {}
    currencies: dict[str, str] = {}
    providers: dict[str, str] = {}
    receipts: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        if symbol in assets:
            asset = assets[symbol]
            if not isinstance(asset, Mapping):
                raise DataGateError("evidence_workspace_invalid", f"Workspace asset {symbol} is malformed.")
            price_series[symbol] = _deserialize_series(asset.get("prices"), symbol)
            currencies[symbol] = str(asset.get("currency") or "")
            providers[symbol] = "yahoo"
            receipts[symbol] = dict(asset.get("receipt") or {})
            continue
        if symbol not in failures:
            raise DataGateError(
                "evidence_workspace_invalid",
                f"Workspace has neither evidence nor failure for {symbol}.",
            )
        indexed_envelope = envelopes_by_symbol.get(symbol)
        if indexed_envelope is None:
            raise DataGateError(
                "fallback_not_supported",
                f"No validated fallback input was supplied for {symbol}.",
                {"symbol": symbol, "primary_failure": failures[symbol]},
            )
        provider, envelope = indexed_envelope
        history = active_normalizers[provider](
            envelope,
            start=str(workspace.get("start")),
            end=workspace.get("end"),
        )
        currency_evidence = yahoo_currency_evidence.get(symbol)
        if not isinstance(currency_evidence, Mapping):
            raise DataGateError(
                "currency_unavailable",
                f"Independent Yahoo currency evidence is unavailable for {symbol}.",
                {"symbol": symbol},
            )
        yahoo_currency = str(currency_evidence.get("currency") or "")
        try:
            normalized_yahoo_currency, _, _ = _currency_spec(yahoo_currency)
            normalized_fallback_currency, _, _ = _currency_spec(history.currency)
        except DataGateError as exc:
            raise DataGateError(
                "fallback_currency_mismatch",
                f"Fallback or Yahoo currency evidence is invalid for {symbol}.",
                {
                    "yahoo_currency": yahoo_currency,
                    "fallback_currency": history.currency,
                },
            ) from exc
        if normalized_fallback_currency != normalized_yahoo_currency:
            raise DataGateError(
                "fallback_currency_mismatch",
                f"Fallback currency does not match Yahoo currency evidence for {symbol}.",
                {
                    "yahoo_currency": yahoo_currency,
                    "normalized_yahoo_currency": normalized_yahoo_currency,
                    "fallback_currency": history.currency,
                    "normalized_fallback_currency": normalized_fallback_currency,
                },
            )
        price_series[symbol] = history.series
        currencies[symbol] = yahoo_currency
        providers[symbol] = str(history.receipt["provider"])
        receipts[symbol] = {
            **history.receipt,
            "currency": yahoo_currency,
            "yahoo_currency_evidence": dict(currency_evidence),
            "primary_failure": failures[symbol],
        }

    fx_prices = {
        str(currency).upper(): _deserialize_series(payload, str(currency).upper())
        for currency, payload in workspace.get("fx_prices", {}).items()
    }
    required_fx = _required_fx(currencies, str(workspace.get("base_currency")))
    unresolved_fx = required_fx - set(fx_prices)
    active_fx_normalizer = fx_normalizer or normalize_wolfram_fx_envelope
    fx_inputs_by_currency: dict[str, Mapping[str, Any]] = {}
    for envelope in fx_envelopes:
        if not isinstance(envelope, Mapping):
            raise DataGateError(
                "wolfram_fx_schema_error",
                "Wolfram FX input must be an object.",
            )
        provider = str(envelope.get("provider") or "").strip().lower()
        if provider != "wolfram" or envelope.get("evidence_kind") != "fx_history":
            raise DataGateError(
                "fallback_not_supported",
                "Only validated Wolfram FX evidence can complete a Yahoo FX failure.",
                {"provider": provider or None},
            )
        try:
            currency, scale, _ = _currency_spec(envelope.get("currency"))
        except DataGateError as exc:
            raise DataGateError(
                "wolfram_fx_schema_error",
                "Wolfram FX input declares an invalid currency.",
            ) from exc
        if scale != 1.0 or currency not in unresolved_fx:
            raise DataGateError(
                "evidence_workspace_invalid",
                f"Wolfram FX input for unrequested currency {currency} was supplied.",
                {
                    "currency": currency,
                    "required_unresolved_currencies": sorted(unresolved_fx),
                },
            )
        if currency in fx_inputs_by_currency:
            raise DataGateError(
                "evidence_workspace_invalid",
                f"Duplicate Wolfram FX inputs were supplied for {currency}.",
            )
        fx_inputs_by_currency[currency] = envelope

    fx_receipts = {
        str(currency).upper(): dict(receipt)
        for currency, receipt in workspace.get("fx_receipts", {}).items()
        if isinstance(receipt, Mapping)
    }
    fx_providers = {currency: "yahoo" for currency in required_fx & set(fx_prices)}
    fx_failures = workspace.get("fx_failures", {})
    for currency, envelope in fx_inputs_by_currency.items():
        history = active_fx_normalizer(
            envelope,
            start=str(workspace.get("start")),
            end=workspace.get("end"),
        )
        if history.currency != currency:
            raise DataGateError(
                "wolfram_fx_pair_mismatch",
                "Normalized Wolfram FX currency conflicts with the workspace requirement.",
                {"workspace_currency": currency, "normalized_currency": history.currency},
            )
        failure = fx_failures.get(currency) if isinstance(fx_failures, Mapping) else None
        if not isinstance(failure, Mapping) or (
            history.receipt["primary_failure"].get("code") != failure.get("code")
            or history.receipt["primary_failure"].get("details") != failure.get("details")
        ):
            raise DataGateError(
                "evidence_workspace_invalid",
                "Wolfram FX input does not preserve the workspace Yahoo failure.",
                {"currency": currency},
            )
        fx_prices[currency] = history.series
        fx_receipts[currency] = dict(history.receipt)
        fx_providers[currency] = "wolfram"

    missing_fx = sorted(required_fx - set(fx_prices))
    if missing_fx:
        raise DataGateError(
            "fx_history_unavailable",
            "Required FX histories are unavailable for the mixed-provider bundle.",
            {
                "missing_currencies": missing_fx,
                "fx_failures": fx_failures,
            },
        )

    prices = pd.concat([price_series[symbol].rename(symbol) for symbol in symbols], axis=1)
    return MarketBundle(
        prices=prices,
        currencies=currencies,
        fx_prices=fx_prices,
        receipt={
            "source": "mixed evidence workspace",
            "providers": providers,
            "asset_receipts": receipts,
            "fx_providers": dict(sorted(fx_providers.items())),
            "fx_receipts": dict(sorted(fx_receipts.items())),
            "start": workspace.get("start"),
            "end": workspace.get("end"),
            "base_currency": workspace.get("base_currency"),
            "workspace_retrieved_at": workspace.get("retrieved_at"),
        },
    )


def workspace_summary(workspace: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": workspace.get("schema_version"),
        "workspace_symbols": workspace.get("symbols", []),
        "yahoo_completed_symbols": list(workspace.get("assets", {})),
        "fallback_required_symbols": list(workspace.get("failures", {})),
        "fallback_required_fx": list(
            workspace.get("fallback_required_fx", workspace.get("fx_failures", {}))
        ),
        "fx_failures": workspace.get("fx_failures", {}),
    }


__all__ = [
    "WORKSPACE_SCHEMA_VERSION",
    "complete_market_bundle",
    "prepare_yahoo_workspace",
    "read_workspace",
    "workspace_summary",
    "write_workspace",
]
