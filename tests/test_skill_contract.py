from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SkillContractTests(unittest.TestCase):
    def test_skill_declares_yahoo_alpaca_wolfram_provider_order(self) -> None:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Yahoo remains the primary provider", text)
        self.assertIn("official Wolfram plugin", text)
        self.assertIn("AdjustedClose", text)
        self.assertIn("wolfram_plugin_unavailable", text)
        self.assertLess(text.index("Yahoo remains the primary provider"), text.index("official Wolfram plugin"))

    def test_skill_prohibits_direct_wolfram_network_fallbacks(self) -> None:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Do not call Wolfram through direct HTTP", text)
        self.assertIn("Do not scrape", text)
        self.assertIn("Do not request a Wolfram API key", text)

    def test_treasury_contract_names_full_qualifier_families(self) -> None:
        text = (ROOT / "references" / "data-contract.md").read_text(encoding="utf-8")
        for value in (
            "Bill",
            "Note",
            "Bond",
            "TIPS",
            "AuctionAverage",
            "SecondaryMarket",
            "ConstantMaturity",
            "BiWeekly",
        ):
            self.assertIn(value, text)
        self.assertIn("nearby maturity", text)

    def test_risk_free_default_and_null_behavior_are_documented(self) -> None:
        text = (ROOT / "references" / "methodology.md").read_text(encoding="utf-8")
        self.assertIn("3-month Treasury bill", text)
        self.assertIn("effective_annual_to_periodic", text)
        self.assertIn("risk_free_rate_unavailable", text)


if __name__ == "__main__":
    unittest.main()
