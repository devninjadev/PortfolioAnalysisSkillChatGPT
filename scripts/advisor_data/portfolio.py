"""Constrained portfolio candidates from a validated return matrix."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from . import DataGateError


def _portfolio_metrics(
    weights: np.ndarray,
    symbols: list[str],
    annualized_mean: np.ndarray,
    annualized_covariance: np.ndarray,
    role: str,
) -> dict[str, Any]:
    variance = float(weights @ annualized_covariance @ weights)
    if not np.isfinite(variance) or variance <= 0:
        raise DataGateError("degenerate_covariance", "Portfolio variance is not positive and finite.")
    volatility = float(np.sqrt(variance))
    asset_volatility = np.sqrt(np.diag(annualized_covariance))
    weighted_asset_volatility = float(weights @ asset_volatility)
    return {
        "role": role,
        "weights": {symbol: float(weight) for symbol, weight in zip(symbols, weights)},
        "historical_annualized_mean_return": float(weights @ annualized_mean),
        "annualized_volatility": volatility,
        "diversification_ratio": float(weighted_asset_volatility / volatility),
    }


def build_portfolio_candidates(
    returns: pd.DataFrame,
    max_weight: float,
    periods_per_year: int,
) -> dict[str, Any]:
    """Return equal-weight comparison and long-only minimum-variance candidate."""

    if returns is None or returns.empty or len(returns.columns) < 2:
        raise DataGateError("insufficient_assets", "MPT requires at least two assets with return history.")
    if len(returns.index) < 2:
        raise DataGateError("insufficient_history", "At least two return observations are required.")
    if periods_per_year <= 0:
        raise DataGateError("invalid_periods_per_year", "Periods per year must be positive.")
    values = returns.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise DataGateError("non_finite_returns", "Return matrix contains non-finite values.")

    asset_count = len(returns.columns)
    if not 0 < max_weight <= 1:
        raise DataGateError("invalid_max_weight", "Maximum weight must be in (0, 1].")
    if asset_count * max_weight < 1 - 1e-12:
        raise DataGateError(
            "infeasible_constraints",
            f"{asset_count} assets cannot sum to 100% with max_weight={max_weight}.",
        )

    annualized_mean = returns.mean().to_numpy(dtype=float) * periods_per_year
    annualized_covariance = returns.cov().to_numpy(dtype=float) * periods_per_year
    if not np.isfinite(annualized_covariance).all():
        raise DataGateError("non_finite_covariance", "Covariance matrix contains non-finite values.")
    if np.allclose(annualized_covariance, 0.0):
        raise DataGateError("degenerate_covariance", "All assets have zero estimated covariance.")

    equal_weights = np.full(asset_count, 1.0 / asset_count, dtype=float)

    def variance(weights: np.ndarray) -> float:
        return float(weights @ annualized_covariance @ weights)

    optimization = minimize(
        variance,
        equal_weights,
        method="SLSQP",
        bounds=[(0.0, max_weight)] * asset_count,
        constraints=[{"type": "eq", "fun": lambda weights: float(np.sum(weights) - 1.0)}],
        options={"ftol": 1e-12, "maxiter": 1000},
    )
    if not optimization.success:
        raise DataGateError(
            "optimization_failed",
            "Minimum-variance optimization did not converge.",
            {"optimizer_message": str(optimization.message)},
        )
    optimized = np.asarray(optimization.x, dtype=float)
    if (
        not np.isfinite(optimized).all()
        or abs(float(optimized.sum()) - 1.0) > 1e-7
        or float(optimized.min()) < -1e-8
        or float(optimized.max()) > max_weight + 1e-8
    ):
        raise DataGateError(
            "optimization_failed",
            "Optimizer returned weights outside the requested constraints.",
        )

    symbols = [str(column) for column in returns.columns]
    return {
        "method": "historical_long_only_candidates",
        "observation_count": int(len(returns.index)),
        "periods_per_year": periods_per_year,
        "max_weight": max_weight,
        "equal_weight": _portfolio_metrics(
            equal_weights,
            symbols,
            annualized_mean,
            annualized_covariance,
            role="comparison_only",
        ),
        "minimum_variance": _portfolio_metrics(
            optimized,
            symbols,
            annualized_mean,
            annualized_covariance,
            role="portfolio_candidate_not_order_instruction",
        ),
        "correlation": {
            row: {column: float(value) for column, value in returns.corr().loc[row].items()}
            for row in symbols
        },
    }


__all__ = ["build_portfolio_candidates"]
