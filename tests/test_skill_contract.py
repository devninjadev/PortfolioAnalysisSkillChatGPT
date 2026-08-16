from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SkillContractTests(unittest.TestCase):
    def assert_in_order(self, text: str, *clauses: str) -> None:
        positions = [text.index(clause) for clause in clauses]
        self.assertEqual(positions, sorted(positions), clauses)

    def test_price_fallback_order_is_yahoo_then_eligible_alpaca_then_wolfram(self) -> None:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assert_in_order(
            text,
            "Yahoo remains the primary provider",
            "Existing eligible U.S. equity and crypto paths try Alpaca first",
            "If Alpaca is ineligible, unavailable, incomplete, or fails its evidence gates",
            "use the official Wolfram plugin",
        )
        self.assertIn("structured LLM eligibility judgment", text)
        self.assertIn("Select exactly one final validated price provider per asset", text)
        self.assertIn("Yahoo remains mandatory for currency metadata and FX", text)

    def test_wolfram_is_only_an_official_plugin_evidence_path(self) -> None:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("official Wolfram plugin", text)
        self.assertIn("Do not call Wolfram through direct HTTP", text)
        self.assertIn("a Python SDK", text)
        self.assertIn("a separately configured MCP server", text)
        self.assertIn("a public webpage", text)
        self.assertIn("Do not scrape", text)
        self.assertIn("Do not request a Wolfram API key", text)
        self.assertIn("CLI validates plugin evidence but never calls Wolfram itself", text)

    def test_adjusted_close_is_exclusive_for_return_calculations(self) -> None:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("cumulative-total-return backtests, MPT, or any other return calculation", text)
        self.assertIn("Wolfram must return `AdjustedClose`", text)
        for property_name in ("`Price`", "`LatestTrade`", "`Close`", "`RawClose`"):
            self.assertIn(property_name, text)
        self.assertIn("cannot substitute for `AdjustedClose`", text)

    def test_treasury_contract_preserves_missing_and_qualifier_capabilities(self) -> None:
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
        self.assertIn("`security_type` and non-empty semantic `maturity_duration` are required", text)
        self.assertIn("`market` is optional", text)
        self.assertIn("`due_date` is optional", text)
        self.assertIn("`frequency` is optional", text)
        self.assertIn("`time_series_operator` is optional", text)
        self.assertIn("`coupon_rate` is optional", text)
        self.assertIn("Preserve Wolfram `Missing`", text)
        self.assertIn("nearby maturity", text)
        self.assertIn("direct `observation` values separately from explicit `calculation` values", text)
        self.assertIn("`linear_maturity_interpolation`", text)

    def test_risk_free_default_alignment_and_null_behavior_are_documented(self) -> None:
        text = (ROOT / "references" / "methodology.md").read_text(encoding="utf-8")
        self.assertIn("3-month Treasury bill", text)
        self.assertIn("ConstantMaturity", text)
        self.assertIn("Daily", text)
        self.assertIn("historical series covering the backtest window", text)
        self.assertIn("effective_annual_to_periodic", text)
        self.assertIn("at most three calendar days", text)
        self.assertIn("risk_free_rate_unavailable", text)
        self.assertIn("Sharpe, Sortino, and alpha fields remain `null`", text)

    def test_market_coverage_is_dated_canary_not_present_availability_claim(self) -> None:
        text = (ROOT / "references" / "market-coverage.md").read_text(encoding="utf-8")
        self.assertIn("**dated canary**", text)
        self.assertIn("미래 가용성 약속이나 허용 목록으로 사용하지 않는다", text)
        self.assertIn("2026-08-16 probe returned `Missing`", text)
        self.assertIn("later availability is unverified and must be rechecked", text)
        self.assertNotIn("계속 unavailable이다", text)
        self.assertIn("nearby maturity로 대체하지 않는다", text)

    def test_latest_release_verification_discloses_all_treasury_lanes_unavailable(self) -> None:
        text = (ROOT / "references" / "market-coverage.md").read_text(encoding="utf-8")
        latest_heading = "## 2026-08-16 later release verification — Treasury unavailable"
        self.assertIn(latest_heading, text)
        latest = text[text.index(latest_heading) :]
        for lane in (
            "exact-maturity curve",
            "10-year nominal history",
            "TIPS history",
            "AuctionAverage bill",
            "SecondaryMarket bill",
        ):
            self.assertIn(lane, latest)
        self.assertIn("all returned `Missing[NotAvailable]`", latest)
        self.assertIn("Treasury lane was not operational at release-verification time", latest)
        self.assertIn("earlier successful probes are historical only", latest)

    def test_envelope_contract_requires_structured_identity_units_and_provider_echoes(self) -> None:
        text = (ROOT / "references" / "data-contract.md").read_text(encoding="utf-8")
        for token in (
            '"yahoo_candidate"',
            '"wolfram_observed"',
            '"share_class"',
            '"canonical_currency"',
            '"requested_qualifiers"',
            '"observed_qualifiers"',
            '"requested_maturity"',
            '"observed_maturity"',
            "wolfram_history_incomplete",
            "market-calendar endpoint tolerance",
            '"aligned_observations"',
            '"raw_annual_percent"',
            '"periodic_rate"',
            '"upstream_provenance"',
        ):
            self.assertIn(token, text)

    def test_implementation_plan_does_not_endorse_superseded_wolfram_gates(self) -> None:
        text = (
            ROOT
            / "docs"
            / "superpowers"
            / "plans"
            / "2026-08-16-wolfram-fallback-treasury-implementation.md"
        ).read_text(encoding="utf-8")
        self.assertNotIn(
            'Require `classification_evidence.identity_decision == "match"`', text
        )
        self.assertNotIn(
            'mark `coverage_status` as `complete`, `clipped_start`, `clipped_end`, or `clipped_both`',
            text,
        )
        for token in (
            '"yahoo_candidate"',
            '"wolfram_observed"',
            '"canonical_currency"',
            "wolfram_history_incomplete",
        ):
            self.assertIn(token, text)

    def test_skill_cross_reference_and_agent_metadata_use_dated_evidence_contract(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        metadata = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn("dated verification examples/receipts", skill)
        self.assertIn("Yahoo 우선 검증과 Alpaca·Wolfram 대안, 미 국채 근거", metadata)
        self.assertIn("official Wolfram plugin fallbacks", metadata)
        self.assertIn("structured Wolfram U.S. Treasury evidence", metadata)


if __name__ == "__main__":
    unittest.main()
