from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from advisor_data import DataGateError  # noqa: E402
from advisor_data.portfolio import build_portfolio_candidates  # noqa: E402


class PortfolioTests(unittest.TestCase):
    def setUp(self) -> None:
        self.returns = pd.DataFrame(
            {
                "AAPL": [0.02, -0.01, 0.03, 0.00, 0.01, -0.02, 0.025, 0.005],
                "005930.KS": [0.01, 0.00, -0.01, 0.02, -0.005, 0.015, 0.00, 0.01],
                "005380.KS": [-0.005, 0.02, 0.00, -0.01, 0.025, 0.005, -0.01, 0.015],
            },
            index=pd.date_range("2026-01-02", periods=8, freq="W-FRI"),
        )

    def test_minimum_variance_weights_respect_constraints(self) -> None:
        result = build_portfolio_candidates(self.returns, max_weight=0.7, periods_per_year=52)

        weights = result["minimum_variance"]["weights"]
        self.assertAlmostEqual(sum(weights.values()), 1.0, places=8)
        self.assertGreaterEqual(min(weights.values()), -1e-10)
        self.assertLessEqual(max(weights.values()), 0.7 + 1e-8)
        self.assertGreater(result["minimum_variance"]["annualized_volatility"], 0.0)

    def test_equal_weight_is_comparison_not_fallback_label(self) -> None:
        result = build_portfolio_candidates(self.returns, max_weight=0.7, periods_per_year=52)

        self.assertEqual(result["equal_weight"]["role"], "comparison_only")
        self.assertAlmostEqual(result["equal_weight"]["weights"]["AAPL"], 1 / 3, places=8)

    def test_infeasible_max_weight_is_rejected_before_optimization(self) -> None:
        with self.assertRaisesRegex(DataGateError, "infeasible_constraints"):
            build_portfolio_candidates(self.returns, max_weight=0.3, periods_per_year=52)

    def test_non_finite_returns_are_rejected(self) -> None:
        invalid = self.returns.copy()
        invalid.iloc[0, 0] = np.inf

        with self.assertRaisesRegex(DataGateError, "non_finite_returns"):
            build_portfolio_candidates(invalid, max_weight=0.7, periods_per_year=52)

    def test_single_asset_is_not_treated_as_mpt_portfolio(self) -> None:
        with self.assertRaisesRegex(DataGateError, "insufficient_assets"):
            build_portfolio_candidates(self.returns[["AAPL"]], max_weight=1.0, periods_per_year=52)


if __name__ == "__main__":
    unittest.main()
