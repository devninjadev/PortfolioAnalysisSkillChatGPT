"""Currency-aware price normalization and return-matrix evidence gates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Mapping

import numpy as np
import pandas as pd
import yfinance as yf

from . import DataGateError


MINOR_CURRENCY_UNITS = {
    "GBp": ("GBP", 0.01),
    "GBX": ("GBP", 0.01),
    "ZAc": ("ZAR", 0.01),
    "ILA": ("ILS", 0.01),
}
ISO_CURRENCY_PATTERN = re.compile(r"^[A-Za-z]{3}$")
YAHOO_STAGE_ASSET_PRICE = "asset_price"
YAHOO_STAGE_CURRENCY_METADATA = "currency_metadata"
YAHOO_STAGE_FX_HISTORY = "fx_history"


@dataclass(frozen=True)
class ReturnMatrixResult:
    returns: pd.DataFrame
    normalized_prices: pd.DataFrame
    receipt: dict[str, Any]


@dataclass(frozen=True)
class MarketBundle:
    prices: pd.DataFrame
    currencies: dict[str, str]
    fx_prices: dict[str, pd.Series]
    receipt: dict[str, Any]


def _currency_spec(value: Any) -> tuple[str, float, str]:
    raw = str(value or "").strip()
    if raw in MINOR_CURRENCY_UNITS:
        major, scale = MINOR_CURRENCY_UNITS[raw]
        return major, scale, raw
    if not ISO_CURRENCY_PATTERN.fullmatch(raw):
        raise DataGateError(
            "unsupported_currency",
            f"Yahoo returned an invalid or missing currency unit: {raw or 'missing'}",
        )
    return raw.upper(), 1.0, raw.upper()


def _extract_field(raw: pd.DataFrame, field: str, symbols: list[str]) -> pd.DataFrame:
    if raw is None or raw.empty:
        raise DataGateError("price_history_unavailable", f"Yahoo returned no {field} data.")
    if isinstance(raw.columns, pd.MultiIndex):
        if field in raw.columns.get_level_values(0):
            extracted = raw[field]
        elif field in raw.columns.get_level_values(-1):
            extracted = raw.xs(field, axis=1, level=-1)
        else:
            raise DataGateError("price_history_unavailable", f"Yahoo output has no {field} field.")
    elif field in raw.columns:
        extracted = raw[[field]].copy()
        if len(symbols) != 1:
            raise DataGateError("price_history_unavailable", "Yahoo returned a single series for multiple symbols.")
        extracted.columns = symbols
    elif set(symbols).issubset(set(raw.columns)):
        extracted = raw[symbols].copy()
    else:
        raise DataGateError("price_history_unavailable", f"Yahoo output has no usable {field} field.")
    if isinstance(extracted, pd.Series):
        extracted = extracted.to_frame(name=symbols[0])
    missing_symbols = [symbol for symbol in symbols if symbol not in extracted.columns]
    if missing_symbols:
        raise DataGateError(
            "price_history_unavailable",
            "Yahoo omitted requested symbols from the price response.",
            {"missing_symbols": missing_symbols},
        )
    return extracted[symbols].copy()


def _valid_fx_series(raw: pd.DataFrame, symbol: str, inverted: bool) -> pd.Series:
    series = pd.to_numeric(_extract_field(raw, "Close", [symbol])[symbol], errors="coerce")
    if series.dropna().empty or (series.dropna() <= 0).any():
        raise DataGateError("fx_history_unavailable", f"Yahoo returned no valid FX values for {symbol}.")
    result = 1.0 / series if inverted else series
    result.name = symbol
    return result.astype(float)


def _download_usd_per_currency(
    currency: str,
    downloader: Any,
    options: dict[str, Any],
) -> tuple[pd.Series, dict[str, str]]:
    """Resolve one unit of currency into USD using direct, then inverse Yahoo pairs."""

    attempts = [(f"{currency}USD=X", False), (f"{currency}=X", True)]
    failures: list[dict[str, str]] = []
    for symbol, inverted in attempts:
        try:
            raw = downloader(tickers=symbol, **options)
            series = _valid_fx_series(raw, symbol, inverted)
            return series, {
                "symbol": symbol,
                "orientation": "currency_units_per_USD_inverted" if inverted else "USD_per_currency_unit",
            }
        except Exception as exc:
            failures.append({"symbol": symbol, "error_type": exc.__class__.__name__})
    raise DataGateError(
        "fx_history_unavailable",
        f"Yahoo returned no usable USD conversion pair for {currency}.",
        {
            "stage": YAHOO_STAGE_FX_HISTORY,
            "currency": currency,
            "attempts": failures,
        },
    )


def download_currency_bridge(
    currency: str,
    start: str,
    end: str | None,
    downloader: Any = yf.download,
) -> tuple[pd.Series, dict[str, str]]:
    """Download one non-USD currency's USD value independently of asset prices."""

    major, scale, _ = _currency_spec(currency)
    if scale != 1.0 or major == "USD":
        raise DataGateError(
            "unsupported_currency",
            "A Yahoo currency bridge requires a non-USD major currency.",
            {"currency": currency},
        )
    options = {
        "start": start,
        "end": end,
        "interval": "1d",
        "auto_adjust": False,
        "actions": False,
        "repair": False,
        "keepna": True,
        "progress": False,
        "threads": True,
        "group_by": "column",
        "multi_level_index": True,
    }
    return _download_usd_per_currency(major, downloader, options)


def download_market_bundle(
    symbols: list[str],
    start: str,
    end: str | None,
    base_currency: str,
    downloader: Any = yf.download,
    ticker_factory: Any = yf.Ticker,
    now: Any = None,
) -> MarketBundle:
    """Download adjusted prices and dynamically resolved USD FX legs."""

    if not symbols:
        raise DataGateError("insufficient_assets", "At least one symbol is required.")
    base, base_scale, _ = _currency_spec(base_currency)
    if base_scale != 1.0:
        raise DataGateError("unsupported_currency", "Base currency must be a major currency unit.")
    retrieved_at = (now or (lambda: datetime.now(timezone.utc).isoformat()))()
    options = {
        "start": start,
        "end": end,
        "interval": "1d",
        "auto_adjust": True,
        "actions": True,
        "repair": True,
        "keepna": True,
        "progress": False,
        "threads": True,
        "group_by": "column",
        "multi_level_index": True,
    }
    repair_used = True
    repair_fallback_error_type: str | None = None
    try:
        raw_prices = downloader(tickers=symbols, **options)
        prices = _extract_field(raw_prices, "Close", symbols)
    except Exception as repair_exc:
        repair_used = False
        repair_fallback_error_type = repair_exc.__class__.__name__
        fallback_options = dict(options)
        fallback_options["repair"] = False
        try:
            raw_prices = downloader(tickers=symbols, **fallback_options)
            prices = _extract_field(raw_prices, "Close", symbols)
        except Exception as fallback_exc:
            raise DataGateError(
                "network_error",
                "Yahoo asset price download failed with and without repair.",
                {
                    "stage": YAHOO_STAGE_ASSET_PRICE,
                    "repair_error_type": repair_exc.__class__.__name__,
                    "fallback_error_type": fallback_exc.__class__.__name__,
                },
            ) from fallback_exc

    currencies: dict[str, str] = {}
    currency_specs: dict[str, tuple[str, float, str]] = {}
    for symbol in symbols:
        ticker = ticker_factory(symbol)
        try:
            metadata = ticker.get_history_metadata() or {}
        except Exception as exc:
            raise DataGateError(
                "currency_unavailable",
                f"Yahoo currency metadata failed for {symbol}.",
                {
                    "stage": YAHOO_STAGE_CURRENCY_METADATA,
                    "error_type": exc.__class__.__name__,
                },
            ) from exc
        raw_currency = str(metadata.get("currency") or "")
        try:
            currency_specs[symbol] = _currency_spec(raw_currency)
        except DataGateError as exc:
            raise DataGateError(
                "currency_unavailable",
                f"Yahoo currency metadata is unusable for {symbol}: {raw_currency or 'missing'}",
                {"stage": YAHOO_STAGE_CURRENCY_METADATA},
            ) from exc
        currencies[symbol] = raw_currency

    required_fx: set[str] = set()
    for currency, _, _ in currency_specs.values():
        if currency == base:
            continue
        if currency != "USD":
            required_fx.add(currency)
        if base != "USD":
            required_fx.add(base)

    fx_prices: dict[str, pd.Series] = {}
    fx_pairs: dict[str, dict[str, str]] = {}
    fx_failures: dict[str, dict[str, Any]] = {}
    fx_options = dict(options)
    fx_options.update({"auto_adjust": False, "actions": False, "repair": False})
    for currency in sorted(required_fx):
        try:
            series, pair_receipt = _download_usd_per_currency(currency, downloader, fx_options)
            fx_prices[currency] = series
            fx_pairs[currency] = pair_receipt
        except DataGateError as exc:
            fx_failures[currency] = {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            }

    try:
        repaired = _extract_field(raw_prices, "Repaired?", symbols)
        repaired_counts = {
            symbol: int(repaired[symbol].fillna(False).astype(bool).sum()) for symbol in symbols
        }
    except DataGateError:
        repaired_counts = {symbol: 0 for symbol in symbols}

    return MarketBundle(
        prices=prices,
        currencies=currencies,
        fx_prices=fx_prices,
        receipt={
            "source": "Yahoo Finance via yfinance",
            "symbols": symbols,
            "start": start,
            "end": end,
            "base_currency": base,
            "asset_currency_units": {symbol: spec[2] for symbol, spec in currency_specs.items()},
            "normalized_asset_currencies": {symbol: spec[0] for symbol, spec in currency_specs.items()},
            "fx_pairs": fx_pairs,
            "fx_failures": fx_failures,
            "supported_by_runtime": sorted({base, *(spec[0] for spec in currency_specs.values())}),
            "auto_adjust": True,
            "actions": True,
            "repair_requested": True,
            "repair_used": repair_used,
            "repair_fallback_error_type": repair_fallback_error_type,
            "repaired_row_counts": repaired_counts,
            "retrieved_at": retrieved_at,
        },
    )


def _coerce_fx_mapping(fx_prices: Mapping[str, pd.Series] | pd.Series | None) -> dict[str, pd.Series]:
    if fx_prices is None:
        return {}
    if isinstance(fx_prices, pd.Series):
        name = str(fx_prices.name or "")
        direct = re.fullmatch(r"([A-Za-z]{3})USD=X", name)
        inverse = re.fullmatch(r"([A-Za-z]{3})=X", name)
        if direct:
            return {direct.group(1).upper(): fx_prices}
        if inverse:
            converted = 1.0 / fx_prices
            converted.name = name
            return {inverse.group(1).upper(): converted}
        raise DataGateError("fx_history_unavailable", "FX series name does not identify its currency.")
    return {str(currency).upper(): series for currency, series in fx_prices.items()}


def _align_fx(series: pd.Series | None, index: pd.DatetimeIndex, currency: str) -> pd.Series:
    if series is None or series.empty:
        raise DataGateError(
            "fx_history_unavailable",
            f"USD conversion history is required for {currency}.",
            {"currency": currency},
        )
    fx = pd.to_numeric(series, errors="coerce").sort_index().reindex(index).ffill(limit=3)
    if fx.isna().any() or (fx <= 0).any():
        raise DataGateError(
            "fx_history_unavailable",
            f"USD conversion history for {currency} could not be aligned to all asset dates.",
            {"currency": currency, "missing_fx_rows": int(fx.isna().sum())},
        )
    return fx.astype(float)


def build_return_matrix(
    prices: pd.DataFrame,
    currencies: dict[str, str],
    base_currency: str,
    fx_prices: Mapping[str, pd.Series] | pd.Series | None,
    frequency: str = "weekly",
    min_observations: int = 104,
) -> ReturnMatrixResult:
    """Convert arbitrary Yahoo currency units through USD and align returns."""

    if prices is None or prices.empty:
        raise DataGateError("price_history_unavailable", "No asset prices were supplied.")
    if not isinstance(prices.index, pd.DatetimeIndex):
        raise DataGateError("invalid_price_index", "Price history must use a DatetimeIndex.")
    if min_observations < 1:
        raise DataGateError("invalid_min_observations", "Minimum observations must be positive.")

    base, base_scale, _ = _currency_spec(base_currency)
    if base_scale != 1.0:
        raise DataGateError("unsupported_currency", "Base currency must be a major currency unit.")

    numeric = prices.copy().sort_index().apply(pd.to_numeric, errors="coerce")
    for symbol in numeric.columns:
        non_missing = numeric[symbol].dropna()
        if non_missing.empty:
            raise DataGateError("price_history_unavailable", f"No usable prices were supplied for {symbol}.")
        if (non_missing <= 0).any():
            raise DataGateError("invalid_price", f"Non-positive prices were supplied for {symbol}.")

    normalized_currencies: dict[str, str] = {}
    source_units: dict[str, str] = {}
    price_scales: dict[str, float] = {}
    for symbol in numeric.columns:
        currency, scale, source_unit = _currency_spec(currencies.get(str(symbol), ""))
        normalized_currencies[str(symbol)] = currency
        source_units[str(symbol)] = source_unit
        price_scales[str(symbol)] = scale

    required_fx: set[str] = set()
    for currency in normalized_currencies.values():
        if currency == base:
            continue
        if currency != "USD":
            required_fx.add(currency)
        if base != "USD":
            required_fx.add(base)

    fx_mapping = _coerce_fx_mapping(fx_prices)
    aligned_fx = {
        currency: _align_fx(fx_mapping.get(currency), numeric.index, currency)
        for currency in sorted(required_fx)
    }

    converted = pd.DataFrame(index=numeric.index)
    for symbol in numeric.columns:
        currency = normalized_currencies[str(symbol)]
        series = numeric[symbol].astype(float) * price_scales[str(symbol)]
        if currency == base:
            converted[symbol] = series
            continue
        asset_usd: float | pd.Series = 1.0 if currency == "USD" else aligned_fx[currency]
        base_usd: float | pd.Series = 1.0 if base == "USD" else aligned_fx[base]
        converted[symbol] = series * asset_usd / base_usd

    if frequency == "weekly":
        sampled = converted.resample("W-FRI").last()
        periods_per_year = 52
    elif frequency == "daily":
        sampled = converted
        periods_per_year = 252
    else:
        raise DataGateError("unsupported_frequency", f"Unsupported return frequency: {frequency}")

    returns = sampled.pct_change(fill_method=None).dropna(how="any")
    if not np.isfinite(returns.to_numpy(dtype=float)).all():
        raise DataGateError("non_finite_returns", "Return matrix contains non-finite values.")
    observation_count = int(len(returns.index))
    if observation_count < min_observations:
        raise DataGateError(
            "insufficient_history",
            f"Only {observation_count} common {frequency} returns are available; {min_observations} required.",
            {
                "observation_count": observation_count,
                "min_observations": min_observations,
                "frequency": frequency,
            },
        )

    receipt = {
        "symbols": [str(column) for column in returns.columns],
        "asset_currencies": normalized_currencies,
        "source_currency_units": source_units,
        "base_currency": base,
        "frequency": frequency,
        "periods_per_year": periods_per_year,
        "observation_count": observation_count,
        "first_return_at": returns.index.min().isoformat(),
        "last_return_at": returns.index.max().isoformat(),
        "source_missing_price_counts": {
            str(column): int(numeric[column].isna().sum()) for column in numeric.columns
        },
        "aligned_missing_price_counts": {
            str(column): int(sampled[column].isna().sum()) for column in sampled.columns
        },
        "fx_currencies": sorted(required_fx),
        "fx_symbols": {currency: str(fx_mapping[currency].name or "") for currency in sorted(required_fx)},
    }
    return ReturnMatrixResult(returns=returns, normalized_prices=sampled, receipt=receipt)


__all__ = [
    "MarketBundle",
    "ReturnMatrixResult",
    "build_return_matrix",
    "download_currency_bridge",
    "download_market_bundle",
]
