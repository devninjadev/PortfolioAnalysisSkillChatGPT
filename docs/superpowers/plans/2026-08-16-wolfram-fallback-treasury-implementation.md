# Wolfram Price Fallback and U.S. Treasury Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the official ChatGPT Wolfram plugin as an evidence-gated financial-history fallback and as the structured source for U.S. Treasury histories, yield curves, and historical risk-free-rate inputs.

**Architecture:** ChatGPT remains the remote orchestrator because Wolfram is a plugin tool rather than a Python dependency. New pure Python adapters validate normalized Wolfram evidence envelopes, a provider-neutral workspace merges Yahoo, Alpaca, and Wolfram asset histories without mixing rows, and a separate Treasury module validates yields, assembles same-date curves, and converts annual percentage yields into aligned periodic risk-free returns.

**Tech Stack:** Python 3.11+, `unittest`, pandas, numpy, scipy, yfinance, ChatGPT skills, the official Wolfram plugin, Wolfram structured financial and country-entity results.

## Global Constraints

- Work only from the canonical `PortfolioAnalysisSkillChatGPT` checkout after `git fetch origin --tags --prune` and a clean comparison with `origin/main`.
- Preserve the existing untracked `.DS_Store`; do not add, delete, or modify it.
- Yahoo remains the primary ticker-resolution and price provider.
- A successful Yahoo result is not duplicated unless the user explicitly requests cross-source verification.
- Existing Alpaca behavior remains first fallback for semantically verified U.S. equities and cryptocurrencies.
- Wolfram follows Alpaca for those classes and is the direct fallback when Alpaca is semantically ineligible.
- Use only the official Wolfram plugin tools exposed inside ChatGPT; add no direct HTTP client, Python SDK, API key, guessed MCP URL, web scraper, or scheduled collector.
- Use an LLM structured classifier for user intent and provider eligibility; add no ticker-suffix parser, Korean text matcher, regex classifier, alias table, or country allowlist.
- Provider-specific symbols and entities proposed by the model must be confirmed by the provider response.
- Portfolio returns, MPT, and cumulative-total-return backtests accept only Wolfram `AdjustedClose` histories.
- Never combine rows from two providers into one asset series.
- Wolfram Treasury support is capability-driven: accept every semantically requested qualifier combination that validates, but never bulk-call a Cartesian product or substitute a nearby maturity.
- Treasury yields may be negative but must be finite and expressed in a recognized percentage unit.
- A missing Treasury maturity remains missing; observed and interpolated curve points stay separate.
- The default backtest proxy is the historical U.S. 3-month Treasury-bill constant-maturity daily series unless the user supplies another verified rate.
- Yahoo currency metadata and required Yahoo FX histories remain mandatory for mixed-currency portfolio calculations.
- Every production behavior begins with a failing test, turns green with the smallest implementation, and ends with a focused commit.
- Do not publish, push, tag, or create a release without separate authorization.
- Baseline receipt on 2026-08-16: `python3 -m unittest discover -s tests -v` ran 56 tests with zero failures.

## Final-review hardening amendment (2026-08-16)

The final review tightened several gates after the initial task snippets below were written. The shipped implementation and current fixtures supersede any older illustrative snippet in this plan:

- Only a Yahoo `asset_price`-stage failure is fallback-eligible. `price_history_unavailable` is inherently price-specific; production `network_error` additionally requires `details.stage == "asset_price"`. Currency metadata, FX, generic network, and other stages remain blocking. Prepare independently persists Yahoo currency evidence and required asset/base Yahoo FX for an eligible failed-price symbol. Fallback normalized currency must equal Yahoo, and Yahoo's original currency unit remains calculation authority.
- Wolfram classification evidence contains complete structured `yahoo_candidate` and `wolfram_observed` identities. Symbol/provider entity, exchange, issuer/company, security type, share class/instrument subtype, and currency are compared deterministically. Bare `identity_decision=match` is invalid.
- Financial `unit` is a structured monetary object with `name`, `canonical_currency`, and `quantity_kind`. The deterministic observed-unit mapping includes `USDollars → USD` and `Euros → EUR`.
- Envelope request ranges must match CLI/workspace ranges. `AdjustedClose` uses a seven-calendar-day market-calendar endpoint tolerance and otherwise raises `wolfram_history_incomplete`; open-ended histories require at least one observation on or after the requested start, and recent price uses a separate seven-day freshness policy.
- Successful Treasury evidence requires complete exact `requested_qualifiers` and provider `observed_qualifiers`, plus typed numeric `requested_maturity` and provider-derived `observed_maturity` that agree with `maturity_years`. Exact `Missing[NotAvailable]` remains authoritative even when the provider cannot emit observed echoes.
- Risk-free aligned rows include raw annual percent and periodic rate; receipts also preserve unit, retrieval time, requested/observed range, evidence kind, missing markers, and upstream provenance.
- The later 2026-08-16 release-verification pass returned `Missing[NotAvailable]` for all exact-maturity curve, 10-year nominal, TIPS, AuctionAverage, and SecondaryMarket Treasury canaries. Earlier successes are historical query-shape receipts, not current operational evidence.

---

## File Structure

- Create `scripts/advisor_data/wolfram.py`: validate Wolfram financial envelopes, confirm declared identity fields, normalize current or adjusted histories, and emit receipts.
- Create `scripts/advisor_data/treasury.py`: validate Treasury qualifiers and histories, assemble same-date curves, interpolate only requested interior points, and align periodic risk-free rates.
- Modify `scripts/advisor_data/evidence_workspace.py`: dispatch provider-neutral fallback envelopes and merge one final provider per failed asset.
- Modify `scripts/advisor_data_cli.py`: add `wolfram-validate`, `treasury-validate`, and repeatable `--wolfram-input` support.
- Create `tests/test_wolfram.py`: deterministic Wolfram financial fixtures and adapter tests.
- Create `tests/test_treasury.py`: Treasury series, curve, and risk-free conversion tests.
- Modify `tests/test_evidence_workspace.py`: Yahoo/Alpaca/Wolfram merge and provider-dispatch tests.
- Modify `tests/test_cli.py`: standalone Wolfram/Treasury commands and mixed-provider CLI tests.
- Create `tests/test_skill_contract.py`: assert the user-visible provider order, plugin-only boundary, Treasury coverage, and failure language.
- Modify `SKILL.md`: add the official plugin workflow, financial fallback rules, Treasury request contract, and risk-free default.
- Modify `references/data-contract.md`: add both Wolfram envelopes, qualifier gates, receipts, errors, and workspace behavior.
- Modify `references/methodology.md`: add provider routing, Treasury evidence roles, curve semantics, and risk-free conversion.
- Modify `references/market-coverage.md`: record dated Wolfram canaries as evidence rather than an allowlist.
- Modify `agents/openai.yaml`: mention eligible Wolfram price and Treasury evidence in the product prompt.

---

### Task 1: Validate Wolfram financial evidence

**Files:**
- Create: `tests/test_wolfram.py`
- Create: `scripts/advisor_data/wolfram.py`

**Interfaces:**
- Produces: `WolframHistory(series: pd.Series, currency: str, receipt: dict[str, Any])`.
- Produces: `normalize_wolfram_envelope(envelope: Mapping[str, Any], start: str, end: str | None) -> WolframHistory`.
- Consumes: a schema-versioned `financial_history` envelope created from official Wolfram plugin output.
- Guarantees: exact provider entity, declared financial identity, price property, currency, source metadata, and observation coverage are validated before a series is returned.

- [ ] **Step 1: Add deterministic fixture builders and valid-history tests**

Create `tests/test_wolfram.py` with these builders and initial tests:

```python
from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from advisor_data import DataGateError  # noqa: E402
from advisor_data.wolfram import normalize_wolfram_envelope  # noqa: E402


def observation(timestamp: str, value: float) -> dict[str, object]:
    return {"timestamp": timestamp, "value": value}


def financial_envelope(
    *,
    symbol: str = "AAPL",
    provider_entity: str = "NASDAQ:AAPL",
    property_name: str = "AdjustedClose",
    required_price_basis: str = "adjusted_total_return",
    currency: str = "USD",
    observations: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "provider": "wolfram",
        "evidence_kind": "financial_history",
        "symbol": symbol,
        "provider_entity": provider_entity,
        "requested_property": property_name,
        "required_price_basis": required_price_basis,
        "classification_evidence": {
            "yahoo_candidate": {
                "symbol": symbol,
                "exchange": "NASDAQ",
                "issuer": "Apple Inc.",
                "security_type": "Equity",
                "share_class": "CommonStock",
                "currency": currency,
            },
            "wolfram_observed": {
                "provider_entity": provider_entity,
                "symbol": symbol,
                "exchange": "NASDAQ",
                "issuer": "Apple Inc.",
                "security_type": "Equity",
                "share_class": "CommonStock",
                "currency": currency,
            },
        },
        "primary_failure": {
            "provider": "yahoo",
            "code": "price_history_unavailable",
            "message": "Yahoo returned no usable price history.",
        },
        "request": {"start": "2026-01-01", "end": "2026-01-13"},
        "result": {
            "entity_type": "Financial",
            "entity": provider_entity,
            "symbol": symbol,
            "exchange": "NASDAQ",
            "issuer": "Apple Inc.",
            "security_type": "Equity",
            "share_class": "CommonStock",
            "currency": currency,
            "property": property_name,
            "unit": {
                "name": "USDollars",
                "canonical_currency": currency,
                "quantity_kind": "monetary",
            },
            "observations": observations,
        },
        "sources": [
            {"name": "Fixture Financial Source", "url": "https://example.invalid/source"}
        ],
        "retrieved_at": "2026-08-16T00:00:00+00:00",
    }


class WolframEnvelopeTests(unittest.TestCase):
    def test_adjusted_history_returns_named_currency_series(self) -> None:
        result = normalize_wolfram_envelope(
            financial_envelope(
                observations=[
                    observation("2026-01-05T00:00:00+00:00", 100.0),
                    observation("2026-01-12T00:00:00+00:00", 101.0),
                ]
            ),
            start="2026-01-01",
            end="2026-01-13",
        )

        self.assertEqual(result.series.name, "AAPL")
        self.assertEqual(result.currency, "USD")
        self.assertEqual(result.receipt["provider"], "wolfram")
        self.assertEqual(result.receipt["provider_entity"], "NASDAQ:AAPL")
        self.assertEqual(result.receipt["price_basis"], "provider_adjusted_total_return_close")
        self.assertEqual(result.receipt["observation_count"], 2)

    def test_recent_price_allows_one_latest_trade_observation(self) -> None:
        result = normalize_wolfram_envelope(
            financial_envelope(
                property_name="LatestTrade",
                required_price_basis="recent_price",
                observations=[observation("2026-01-12T20:00:00+00:00", 101.0)],
            ),
            start="2026-01-01",
            end="2026-01-13",
        )

        self.assertEqual(result.receipt["price_basis"], "latest_trade")
        self.assertEqual(len(result.series), 1)
```

- [ ] **Step 2: Run the new test module and verify RED**

Run:

```bash
python3 -m unittest tests.test_wolfram.WolframEnvelopeTests -v
```

Expected: import failure because `advisor_data.wolfram` does not exist.

- [ ] **Step 3: Implement the dataclass, mapping gates, observation parser, and coverage receipt**

Create `scripts/advisor_data/wolfram.py` with this public structure:

```python
"""Validate structured financial evidence returned by the Wolfram plugin."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
import math

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
```

Implement `normalize_wolfram_envelope` with these exact gates:

1. Require `schema_version == 1`, `provider == "wolfram"`, and `evidence_kind == "financial_history"`.
2. Require complete structured `classification_evidence.yahoo_candidate` and `classification_evidence.wolfram_observed` objects; compare symbol/provider entity, exchange, issuer/company, security type, share class/instrument subtype, and currency deterministically against `result`. A bare model decision is never sufficient.
3. Require `result.entity_type == "Financial"`, exact provider entity/symbol identity, and no missing required identity fields.
4. Require a structured monetary `result.unit` with a deterministically mapped `name`, `canonical_currency` equal to `result.currency`, and `quantity_kind == "monetary"`; also require `retrieved_at` and at least one source with a non-empty `name`.
5. Require `result.property == requested_property`.
6. For `required_price_basis == "adjusted_total_return"`, require `AdjustedClose` and at least two observations.
7. For `required_price_basis == "recent_price"`, allow `Price`, `LatestTrade`, or `Close` and at least one observation.
8. Parse timestamps to UTC and values to finite positive floats. Collapse identical duplicates and reject conflicting duplicates.
9. Require the envelope request range to match the caller range. Sort the series without forward-filling; allow at most seven calendar days of endpoint tolerance for ordinary market weekends/holidays, otherwise raise `wolfram_history_incomplete`. Apply a separate seven-day freshness gate to recent-price evidence.
10. Return a receipt containing provider, symbol, provider entity, property, price basis, currency, unit, source list, observation count, requested range, observed range, coverage status, retrieval time, classification evidence, and primary failure.

Use this price-basis mapping:

```python
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
```

- [ ] **Step 4: Add identity, property, source, and unsafe-observation rejection tests**

Add these tests to `tests/test_wolfram.py`:

```python
def test_total_return_rejects_unadjusted_close(self) -> None:
    with self.assertRaisesRegex(DataGateError, "wolfram_property_unavailable"):
        normalize_wolfram_envelope(
            financial_envelope(
                property_name="Close",
                observations=[
                    observation("2026-01-05T00:00:00+00:00", 100.0),
                    observation("2026-01-12T00:00:00+00:00", 101.0),
                ],
            ),
            "2026-01-01",
            "2026-01-13",
        )

def test_provider_entity_conflict_fails_closed(self) -> None:
    envelope = financial_envelope(
        observations=[
            observation("2026-01-05T00:00:00+00:00", 100.0),
            observation("2026-01-12T00:00:00+00:00", 101.0),
        ]
    )
    envelope["result"]["entity"] = "NASDAQ:MSFT"
    with self.assertRaisesRegex(DataGateError, "wolfram_entity_mismatch"):
        normalize_wolfram_envelope(envelope, "2026-01-01", "2026-01-13")

def test_declared_identity_conflict_fails_closed(self) -> None:
    envelope = financial_envelope(
        observations=[
            observation("2026-01-05T00:00:00+00:00", 100.0),
            observation("2026-01-12T00:00:00+00:00", 101.0),
        ]
    )
    envelope["classification_evidence"]["yahoo_candidate"]["currency"] = "EUR"
    with self.assertRaisesRegex(DataGateError, "wolfram_entity_mismatch"):
        normalize_wolfram_envelope(envelope, "2026-01-01", "2026-01-13")

def test_provider_currency_conflict_fails_closed(self) -> None:
    envelope = financial_envelope(
        observations=[
            observation("2026-01-05T00:00:00+00:00", 100.0),
            observation("2026-01-12T00:00:00+00:00", 101.0),
        ]
    )
    envelope["result"]["currency"] = "EUR"
    with self.assertRaisesRegex(DataGateError, "wolfram_entity_mismatch"):
        normalize_wolfram_envelope(envelope, "2026-01-01", "2026-01-13")

def test_missing_source_metadata_is_rejected(self) -> None:
    envelope = financial_envelope(
        observations=[
            observation("2026-01-05T00:00:00+00:00", 100.0),
            observation("2026-01-12T00:00:00+00:00", 101.0),
        ]
    )
    envelope["sources"] = []
    with self.assertRaisesRegex(DataGateError, "wolfram_source_unavailable"):
        normalize_wolfram_envelope(envelope, "2026-01-01", "2026-01-13")

def test_conflicting_duplicate_observation_is_rejected(self) -> None:
    with self.assertRaisesRegex(DataGateError, "wolfram_schema_error"):
        normalize_wolfram_envelope(
            financial_envelope(
                observations=[
                    observation("2026-01-05T00:00:00+00:00", 100.0),
                    observation("2026-01-05T00:00:00+00:00", 101.0),
                ]
            ),
            "2026-01-01",
            None,
        )
```

Also test zero, negative, non-finite, malformed timestamps, empty histories, single-observation total-return histories, wrong provider, wrong evidence kind, wrong symbol, and a late first observation that records clipped coverage.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run:

```bash
python3 -m unittest tests.test_wolfram -v
```

Expected: every Wolfram financial adapter test passes.

- [ ] **Step 6: Commit the financial adapter**

```bash
git add tests/test_wolfram.py scripts/advisor_data/wolfram.py
git commit -m "Add Wolfram financial evidence adapter"
```

---

### Task 2: Validate Wolfram Treasury series and qualifier capabilities

**Files:**
- Create: `tests/test_treasury.py`
- Create: `scripts/advisor_data/treasury.py`

**Interfaces:**
- Produces: `TreasurySeries(series: pd.Series, maturity_years: float, receipt: dict[str, Any])`.
- Produces: `normalize_treasury_envelope(envelope: Mapping[str, Any]) -> TreasurySeries`.
- Consumes: official-plugin envelopes for one current or historical U.S. Treasury property.
- Guarantees: the country entity, qualifiers, numeric maturity, unit, observations, source, and missingness are preserved without nearby-series substitution.

- [ ] **Step 1: Add Treasury fixture builders and valid nominal/TIPS tests**

Create `tests/test_treasury.py` with:

```python
from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from advisor_data import DataGateError  # noqa: E402
from advisor_data.treasury import normalize_treasury_envelope  # noqa: E402


def treasury_observation(timestamp: str, value: float) -> dict[str, object]:
    return {"timestamp": timestamp, "value": value}


def treasury_envelope(
    *,
    evidence_kind: str = "us_treasury_history",
    security_type: str = "Note",
    maturity_duration: str = "10Year",
    maturity_years: float = 10.0,
    market: str | None = None,
    due_date: str | None = "ConstantMaturity",
    frequency: str = "Daily",
    time_series_operator: str | None = None,
    observations: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "provider": "wolfram",
        "evidence_kind": evidence_kind,
        "country_entity": "UnitedStates",
        "qualifiers": {
            "security_type": security_type,
            "maturity_duration": maturity_duration,
            "market": market,
            "due_date": due_date,
            "frequency": frequency,
            "time_series_operator": time_series_operator,
            "coupon_rate": None,
        },
        "request": {"start": "2025-01-01", "end": "2026-08-13"},
        "result": {
            "property": "Treasury",
            "maturity_years": maturity_years,
            "unit": "Percent",
            "observations": observations,
            "missing": [],
        },
        "sources": [
            {
                "name": "FRED (Federal Reserve Economic Data)",
                "organization": "Federal Reserve Bank of St. Louis",
                "url": "https://fred.stlouisfed.org/",
            }
        ],
        "retrieved_at": "2026-08-16T00:00:00+00:00",
    }


class TreasuryEnvelopeTests(unittest.TestCase):
    def test_nominal_constant_maturity_history_preserves_qualifiers(self) -> None:
        result = normalize_treasury_envelope(
            treasury_envelope(
                observations=[
                    treasury_observation("2026-08-12T00:00:00+00:00", 4.55),
                    treasury_observation("2026-08-13T00:00:00+00:00", 4.63),
                ]
            )
        )

        self.assertEqual(result.maturity_years, 10.0)
        self.assertEqual(result.series.tolist(), [4.55, 4.63])
        self.assertEqual(result.receipt["unit"], "Percent")
        self.assertEqual(result.receipt["qualifiers"]["security_type"], "Note")
        self.assertEqual(result.receipt["source_names"], ["FRED (Federal Reserve Economic Data)"])

    def test_tips_and_negative_yields_are_valid(self) -> None:
        result = normalize_treasury_envelope(
            treasury_envelope(
                security_type="TIPS",
                maturity_duration="5Year",
                maturity_years=5.0,
                observations=[
                    treasury_observation("2020-01-02T00:00:00+00:00", -0.10),
                    treasury_observation("2020-01-03T00:00:00+00:00", -0.08),
                ],
            )
        )

        self.assertEqual(result.series.iloc[0], -0.10)
        self.assertEqual(result.receipt["qualifiers"]["security_type"], "TIPS")
```

- [ ] **Step 2: Run the Treasury tests and verify RED**

Run:

```bash
python3 -m unittest tests.test_treasury.TreasuryEnvelopeTests -v
```

Expected: import failure because `advisor_data.treasury` does not exist.

- [ ] **Step 3: Implement qualifier constants, dataclass, and strict series normalization**

Create the module with these public constants and type:

```python
"""Validate U.S. Treasury evidence and derive disclosed calculations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence
import math

import numpy as np
import pandas as pd

from . import DataGateError


SUPPORTED_SECURITY_TYPES = frozenset({"Bill", "Note", "Bond", "TIPS"})
SUPPORTED_MARKETS = frozenset({"AuctionAverage", "SecondaryMarket"})
SUPPORTED_DUE_DATES = frozenset({"ConstantMaturity"})
SUPPORTED_FREQUENCIES = frozenset(
    {"Daily", "Weekly", "BiWeekly", "Monthly", "Quarterly", "Annual"}
)
SUPPORTED_OPERATORS = frozenset(
    {
        "Change",
        "ChangeRate",
        "AnnualChange",
        "AnnualizedChangeRate",
        "YearOverYearChangeRate",
    }
)
SUPPORTED_EVIDENCE_KINDS = frozenset(
    {"us_treasury_current", "us_treasury_history"}
)


@dataclass(frozen=True)
class TreasurySeries:
    series: pd.Series
    maturity_years: float
    receipt: dict[str, Any]
```

Implement `normalize_treasury_envelope` with these gates:

1. Require schema 1, provider `wolfram`, a supported evidence kind, and country `UnitedStates`.
2. Require `result.property == "Treasury"`, `result.unit == "Percent"`, a positive finite `maturity_years`, a non-empty semantic `maturity_duration`, and a source name.
3. Validate non-null qualifier values against the constant sets. `market`, `due_date`, and `time_series_operator` remain optional because different Wolfram Treasury modes use different qualifiers. `coupon_rate` must be null or a finite numeric percentage; the adapter never parses coupon text.
4. Accept one observation for `us_treasury_current`; require two or more for `us_treasury_history`.
5. Parse timestamps in UTC, preserve finite negative or positive yields, collapse identical duplicates, and reject conflicting duplicates.
6. Preserve `result.missing` as a list in the receipt. Do not fill or substitute it. An empty result whose missing marker names the requested maturity raises `treasury_maturity_unavailable`; another empty result raises `treasury_series_unavailable`.
7. Emit requested/observed ranges, observation count, qualifiers, numeric maturity, unit, sources, retrieval time, and missing markers.

- [ ] **Step 4: Add qualifier, unit, missing, and duplicate failure tests**

Add:

```python
def test_auction_and_secondary_market_qualifiers_are_accepted(self) -> None:
    for market in ("AuctionAverage", "SecondaryMarket"):
        with self.subTest(market=market):
            result = normalize_treasury_envelope(
                treasury_envelope(
                    security_type="Bill",
                    maturity_duration="3Month",
                    maturity_years=0.25,
                    market=market,
                    due_date=None,
                    frequency="Weekly" if market == "AuctionAverage" else "Daily",
                    observations=[
                        treasury_observation("2026-08-06T00:00:00+00:00", 3.70),
                        treasury_observation("2026-08-13T00:00:00+00:00", 3.71),
                    ],
                )
            )
            self.assertEqual(result.receipt["qualifiers"]["market"], market)

def test_unavailable_series_stays_unavailable(self) -> None:
    envelope = treasury_envelope(observations=[])
    envelope["result"]["missing"] = [
        {"reason": "NotAvailable", "maturity_duration": "2Month"}
    ]
    with self.assertRaisesRegex(DataGateError, "treasury_maturity_unavailable"):
        normalize_treasury_envelope(envelope)

def test_non_percent_unit_is_rejected(self) -> None:
    envelope = treasury_envelope(
        observations=[
            treasury_observation("2026-08-12T00:00:00+00:00", 4.55),
            treasury_observation("2026-08-13T00:00:00+00:00", 4.63),
        ]
    )
    envelope["result"]["unit"] = "BasisPoints"
    with self.assertRaisesRegex(DataGateError, "wolfram_unit_mismatch"):
        normalize_treasury_envelope(envelope)

def test_conflicting_duplicate_yields_are_rejected(self) -> None:
    with self.assertRaisesRegex(DataGateError, "wolfram_schema_error"):
        normalize_treasury_envelope(
            treasury_envelope(
                observations=[
                    treasury_observation("2026-08-13T00:00:00+00:00", 4.60),
                    treasury_observation("2026-08-13T00:00:00+00:00", 4.63),
                ]
            )
        )
```

Add subtests for all four security types, all six frequencies, all five time-series operators, an arbitrary positive numeric maturity such as `1.5`, a finite numeric coupon rate, a non-finite coupon rate, an unknown security type, an unknown market, an unknown frequency, a non-finite yield, malformed timestamps, missing sources, and a non-U.S. country entity.

- [ ] **Step 5: Run focused Treasury series tests and verify GREEN**

Run:

```bash
python3 -m unittest tests.test_treasury.TreasuryEnvelopeTests -v
```

Expected: every Treasury envelope test passes.

- [ ] **Step 6: Commit the Treasury series adapter**

```bash
git add tests/test_treasury.py scripts/advisor_data/treasury.py
git commit -m "Add Wolfram Treasury evidence adapter"
```

---

### Task 3: Assemble yield curves and align historical risk-free rates

**Files:**
- Modify: `tests/test_treasury.py`
- Modify: `scripts/advisor_data/treasury.py`

**Interfaces:**
- Produces: `YieldCurveResult(observed: list[dict[str, Any]], missing: list[dict[str, Any]], calculated: list[dict[str, Any]], receipt: dict[str, Any])`.
- Produces: `build_yield_curve(series_by_maturity: Mapping[float, TreasurySeries], observation_date: str, requested_maturities: Sequence[float], interpolate: bool = False) -> YieldCurveResult`.
- Produces: `HistoricalYieldCurveResult(frame: pd.DataFrame, receipt: dict[str, Any])`.
- Produces: `build_historical_yield_curve(series_by_maturity: Mapping[float, TreasurySeries]) -> HistoricalYieldCurveResult`.
- Produces: `RiskFreeResult(series: pd.Series, receipt: dict[str, Any])`.
- Produces: `align_periodic_risk_free(annual_percent: TreasurySeries, return_index: pd.DatetimeIndex, periods_per_year: int, max_fill_days: int = 3) -> RiskFreeResult`.

- [ ] **Step 1: Add a failing same-date curve test**

Extend `tests/test_treasury.py`:

```python
import pandas as pd

from advisor_data.treasury import (  # noqa: E402
    align_periodic_risk_free,
    build_historical_yield_curve,
    build_yield_curve,
    normalize_treasury_envelope,
)


def treasury_series_for_curve(maturity_years: float, value: float):
    security_type = "Bill" if maturity_years < 1.0 else "Note"
    maturity_duration = "3Month" if maturity_years == 0.25 else f"{int(maturity_years)}Year"
    return normalize_treasury_envelope(
        treasury_envelope(
            security_type=security_type,
            maturity_duration=maturity_duration,
            maturity_years=maturity_years,
            observations=[treasury_observation("2026-08-13T00:00:00+00:00", value)],
            evidence_kind="us_treasury_current",
        )
    )


class YieldCurveTests(unittest.TestCase):
    def test_curve_separates_observed_and_missing_points(self) -> None:
        result = build_yield_curve(
            {
                0.25: treasury_series_for_curve(0.25, 3.87),
                2.0: treasury_series_for_curve(2.0, 4.15),
                10.0: treasury_series_for_curve(10.0, 4.63),
            },
            observation_date="2026-08-13",
            requested_maturities=[0.25, 1.0, 2.0, 10.0],
        )

        self.assertEqual([point["maturity_years"] for point in result.observed], [0.25, 2.0, 10.0])
        self.assertEqual(result.missing, [{"maturity_years": 1.0, "reason": "not_observed"}])
        self.assertEqual(result.calculated, [])
        self.assertEqual(result.receipt["observation_date"], "2026-08-13T00:00:00+00:00")
```

The fixture helper may format a label for synthetic test readability; production code must never parse that label to obtain the numeric maturity.

- [ ] **Step 2: Run the curve test and verify RED**

Run:

```bash
python3 -m unittest tests.test_treasury.YieldCurveTests.test_curve_separates_observed_and_missing_points -v
```

Expected: import failure because `build_yield_curve` does not exist.

- [ ] **Step 3: Implement observed, missing, and optional interior interpolation output**

Add:

```python
@dataclass(frozen=True)
class YieldCurveResult:
    observed: list[dict[str, Any]]
    missing: list[dict[str, Any]]
    calculated: list[dict[str, Any]]
    receipt: dict[str, Any]


@dataclass(frozen=True)
class HistoricalYieldCurveResult:
    frame: pd.DataFrame
    receipt: dict[str, Any]
```

`build_yield_curve` must:

1. Parse `observation_date` as a UTC midnight timestamp.
2. Validate that each mapping key equals the evidence's numeric `maturity_years`.
3. Read only exact same-date observations.
4. Sort observed points by numeric maturity.
5. Emit every unobserved requested maturity in `missing`.
6. When `interpolate=False`, emit no calculated points.
7. When `interpolate=True`, linearly interpolate only a missing maturity strictly between two observed maturities and put the result in `calculated` with `role: "calculation"`, `method: "linear_maturity_interpolation"`, and both bounding maturities.
8. Never extrapolate below the shortest or above the longest observed maturity.
9. Preserve the source names and input qualifier summaries in the receipt.

`build_historical_yield_curve` must validate every numeric mapping key, sort maturities, concatenate the named yield series with `join="inner"`, reject an empty common-date frame with `treasury_alignment_failed`, and return a receipt containing `alignment: "exact_common_dates"`, maturities, common observation count, first/last dates, qualifiers, and source names. It must not forward-fill any maturity.

Use this interpolation body:

```python
value = left_value + (
    (target_years - left_years)
    / (right_years - left_years)
    * (right_value - left_value)
)
```

- [ ] **Step 4: Add interpolation and cross-date rejection tests**

```python
def test_curve_interpolation_is_calculation_and_never_extrapolates(self) -> None:
    result = build_yield_curve(
        {
            2.0: treasury_series_for_curve(2.0, 4.0),
            10.0: treasury_series_for_curve(10.0, 5.0),
        },
        observation_date="2026-08-13",
        requested_maturities=[1.0, 5.0, 20.0],
        interpolate=True,
    )

    self.assertEqual(result.calculated[0]["maturity_years"], 5.0)
    self.assertEqual(result.calculated[0]["role"], "calculation")
    self.assertAlmostEqual(result.calculated[0]["value"], 4.375)
    self.assertEqual(
        [item["maturity_years"] for item in result.missing],
        [1.0, 20.0],
    )

def test_curve_does_not_carry_a_prior_date_forward(self) -> None:
    evidence = normalize_treasury_envelope(
        treasury_envelope(
            evidence_kind="us_treasury_current",
            observations=[treasury_observation("2026-08-12T00:00:00+00:00", 4.63)],
        )
    )
    result = build_yield_curve(
        {10.0: evidence},
        observation_date="2026-08-13",
        requested_maturities=[10.0],
    )
    self.assertEqual(result.observed, [])
    self.assertEqual(result.missing[0]["reason"], "not_observed")

def test_historical_curve_uses_only_exact_common_dates(self) -> None:
    two_year = normalize_treasury_envelope(
        treasury_envelope(
            maturity_duration="2Year",
            maturity_years=2.0,
            observations=[
                treasury_observation("2026-08-12T00:00:00+00:00", 4.10),
                treasury_observation("2026-08-13T00:00:00+00:00", 4.15),
            ],
        )
    )
    ten_year = normalize_treasury_envelope(
        treasury_envelope(
            maturity_duration="10Year",
            maturity_years=10.0,
            observations=[
                treasury_observation("2026-08-13T00:00:00+00:00", 4.63),
                treasury_observation("2026-08-14T00:00:00+00:00", 4.64),
            ],
        )
    )

    result = build_historical_yield_curve({2.0: two_year, 10.0: ten_year})

    self.assertEqual(list(result.frame.columns), [2.0, 10.0])
    self.assertEqual(len(result.frame), 1)
    self.assertEqual(result.frame.index[0].isoformat(), "2026-08-13T00:00:00+00:00")
    self.assertEqual(result.receipt["alignment"], "exact_common_dates")
```

- [ ] **Step 5: Add failing risk-free conversion and alignment tests**

```python
class RiskFreeRateTests(unittest.TestCase):
    def test_annual_percent_converts_to_weekly_periodic_rate(self) -> None:
        treasury = normalize_treasury_envelope(
            treasury_envelope(
                security_type="Bill",
                maturity_duration="3Month",
                maturity_years=0.25,
                observations=[
                    treasury_observation("2026-01-02T00:00:00+00:00", 5.0),
                    treasury_observation("2026-01-09T00:00:00+00:00", 5.2),
                ],
            )
        )
        result = align_periodic_risk_free(
            treasury,
            pd.to_datetime(["2026-01-02T00:00:00+00:00", "2026-01-09T00:00:00+00:00"]),
            periods_per_year=52,
        )

        self.assertAlmostEqual(result.series.iloc[0], (1.05 ** (1.0 / 52.0)) - 1.0)
        self.assertEqual(result.receipt["conversion"], "effective_annual_to_periodic")
        self.assertEqual(result.receipt["max_fill_days"], 3)

    def test_negative_yield_above_minus_one_hundred_percent_is_supported(self) -> None:
        treasury = normalize_treasury_envelope(
            treasury_envelope(
                observations=[
                    treasury_observation("2026-01-02T00:00:00+00:00", -0.50),
                    treasury_observation("2026-01-09T00:00:00+00:00", -0.40),
                ]
            )
        )
        result = align_periodic_risk_free(
            treasury,
            pd.to_datetime(["2026-01-02T00:00:00+00:00"]),
            periods_per_year=252,
        )
        self.assertLess(result.series.iloc[0], 0.0)

    def test_alignment_carries_at_most_three_calendar_days(self) -> None:
        treasury = normalize_treasury_envelope(
            treasury_envelope(
                observations=[
                    treasury_observation("2026-01-02T00:00:00+00:00", 5.0),
                    treasury_observation("2026-01-09T00:00:00+00:00", 5.2),
                ]
            )
        )
        result = align_periodic_risk_free(
            treasury,
            pd.to_datetime(["2026-01-05T00:00:00+00:00"]),
            periods_per_year=252,
        )
        self.assertEqual(result.receipt["filled_observation_count"], 1)

        with self.assertRaisesRegex(DataGateError, "treasury_alignment_failed"):
            align_periodic_risk_free(
                treasury,
                pd.to_datetime(["2026-01-06T00:00:00+00:00"]),
                periods_per_year=252,
            )
```

- [ ] **Step 6: Run risk-free tests and verify RED**

Run:

```bash
python3 -m unittest tests.test_treasury.RiskFreeRateTests -v
```

Expected: import failure because `align_periodic_risk_free` does not exist.

- [ ] **Step 7: Implement conversion, source-age tracking, and disclosed receipts**

Add:

```python
@dataclass(frozen=True)
class RiskFreeResult:
    series: pd.Series
    receipt: dict[str, Any]
```

`align_periodic_risk_free` must require a positive integer `periods_per_year`, a non-empty `DatetimeIndex`, and `max_fill_days` between zero and three. It must reject Treasury evidence with a non-null `time_series_operator`, because a change series is not a yield level. It must sort and UTC-normalize both indexes, track the source date used for every aligned return date, reject source ages above the limit, reject annual percentages at or below `-100`, and calculate:

```python
annual_decimal = aligned_annual_percent.astype(float) / 100.0
periodic = np.power(1.0 + annual_decimal, 1.0 / periods_per_year) - 1.0
```

The receipt must contain `conversion: "effective_annual_to_periodic"`, `periods_per_year`, `max_fill_days`, aligned first/last dates, direct and filled observation counts, Treasury qualifiers, source names, and a note that the conversion is a disclosed analysis convention applied to the provider's annual percentage yield.

- [ ] **Step 8: Run the complete Treasury module and commit**

Run:

```bash
python3 -m unittest tests.test_treasury -v
```

Expected: all Treasury, curve, interpolation, and risk-free tests pass.

```bash
git add tests/test_treasury.py scripts/advisor_data/treasury.py
git commit -m "Add Treasury curves and risk free alignment"
```

---

### Task 4: Generalize the mixed-provider evidence workspace

**Files:**
- Modify: `tests/test_evidence_workspace.py`
- Modify: `scripts/advisor_data/evidence_workspace.py:1-398`

**Interfaces:**
- Extends: `complete_market_bundle(workspace: Mapping[str, Any], envelopes: Sequence[Mapping[str, Any]], normalizers: Mapping[str, Callable[..., Any]] | None = None) -> MarketBundle`.
- Consumes: legacy Alpaca envelopes without a top-level `provider` and new Wolfram envelopes with `provider == "wolfram"`.
- Produces: one final provider and one receipt per asset while preserving Yahoo FX requirements.

- [ ] **Step 1: Add a failing Yahoo/Wolfram merge test**

Import `financial_envelope` and `observation` from `tests.test_wolfram`, then add:

```python
def test_complete_merges_yahoo_and_wolfram_without_dropping_symbols(self) -> None:
    def loader(*, symbols: list[str], **_: object) -> MarketBundle:
        if symbols == ["AAPL"]:
            return yahoo_bundle("AAPL", [100.0, 101.0])
        raise DataGateError(
            "price_history_unavailable",
            "Yahoo returned no usable history for SAP.DE.",
        )

    workspace = prepare_yahoo_workspace(
        ["AAPL", "SAP.DE"],
        "2026-01-01",
        "2026-02-01",
        "USD",
        market_loader=loader,
    )
    envelope = financial_envelope(
        symbol="SAP.DE",
        provider_entity="XETR:SAP",
        currency="EUR",
        observations=[
            observation("2026-01-05T00:00:00+00:00", 200.0),
            observation("2026-01-12T00:00:00+00:00", 202.0),
        ],
    )
    envelope["result"]["symbol"] = "SAP.DE"
    envelope["result"]["exchange"] = "XETRA"
    workspace["fx_prices"]["EUR"] = {
        "name": "EURUSD=X",
        "observations": [
            {"timestamp": "2026-01-05T00:00:00+00:00", "value": 1.15},
            {"timestamp": "2026-01-12T00:00:00+00:00", "value": 1.16},
        ],
    }

    bundle = complete_market_bundle(workspace, [envelope])

    self.assertEqual(list(bundle.prices.columns), ["AAPL", "SAP.DE"])
    self.assertEqual(
        bundle.receipt["providers"],
        {"AAPL": "yahoo", "SAP.DE": "wolfram"},
    )
    self.assertEqual(bundle.currencies["SAP.DE"], "EUR")
```

- [ ] **Step 2: Run the new workspace test and verify RED**

Run:

```bash
python3 -m unittest tests.test_evidence_workspace.EvidenceWorkspaceTests.test_complete_merges_yahoo_and_wolfram_without_dropping_symbols -v
```

Expected: failure because the workspace always dispatches fallback envelopes to Alpaca.

- [ ] **Step 3: Implement provider-neutral envelope indexing and normalizer dispatch**

Modify imports and the function signature:

```python
from .wolfram import normalize_wolfram_envelope


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
    normalizers: Mapping[str, Callable[..., Any]] | None = None,
) -> MarketBundle:
    active_normalizers = dict(
        normalizers
        or {
            "alpaca": normalize_alpaca_envelope,
            "wolfram": normalize_wolfram_envelope,
        }
    )
```

Index one envelope per failed symbol. Reject unrequested symbols, duplicates across providers, and unknown providers before calculating. Normalize with `start` and `end`, read the actual final provider from `history.receipt["provider"]`, and preserve the original Yahoo failure:

```python
provider = _envelope_provider(envelope)
normalizer = active_normalizers.get(provider)
if normalizer is None:
    raise DataGateError(
        "fallback_not_supported",
        f"No validated fallback adapter is available for {provider}.",
        {"provider": provider, "symbol": symbol},
    )
history = normalizer(
    envelope,
    start=str(workspace.get("start")),
    end=workspace.get("end"),
)
providers[symbol] = str(history.receipt["provider"])
receipts[symbol] = {**history.receipt, "primary_failure": failures[symbol]}
```

Do not change `_required_fx`, `_deserialize_series`, `build_return_matrix`, or asset price forward-fill behavior.

- [ ] **Step 4: Add backward-compatibility and rejection tests**

Add tests that:

- the existing Alpaca envelope without `provider` still maps to `alpaca`;
- one Yahoo, one Alpaca, and one Wolfram asset produce three distinct provider receipts;
- duplicate Alpaca and Wolfram envelopes for the same failed symbol are rejected;
- a Wolfram envelope for a Yahoo-successful symbol is rejected as unrequested;
- an unknown provider is rejected before normalization;
- missing EUR or KRW FX still raises `fx_history_unavailable`;
- a required failed symbol with no envelope still raises `fallback_not_supported`.

Use this three-provider assertion:

```python
self.assertEqual(
    bundle.receipt["providers"],
    {"AAPL": "yahoo", "BTC-USD": "alpaca", "SAP.DE": "wolfram"},
)
```

- [ ] **Step 5: Run workspace and existing Alpaca tests and verify GREEN**

Run:

```bash
python3 -m unittest tests.test_evidence_workspace tests.test_alpaca tests.test_wolfram -v
```

Expected: all tests pass, including existing Alpaca compatibility.

- [ ] **Step 6: Commit the provider-neutral workspace**

```bash
git add tests/test_evidence_workspace.py scripts/advisor_data/evidence_workspace.py
git commit -m "Merge Wolfram histories in evidence workspace"
```

---

### Task 5: Expose Wolfram and Treasury CLI validation

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `scripts/advisor_data_cli.py:38-324`

**Interfaces:**
- Adds command: `wolfram-validate --input PATH --start DATE [--end DATE]`.
- Adds command: `treasury-validate --input PATH`.
- Extends command: `complete-portfolio --wolfram-input PATH` as a repeatable option.
- Extends `main` dependency injection with `wolfram_normalizer` and `treasury_normalizer`.

- [ ] **Step 1: Add failing standalone CLI tests**

Import the fixture builders and add:

```python
from tests.test_treasury import treasury_envelope, treasury_observation  # noqa: E402
from tests.test_wolfram import financial_envelope, observation  # noqa: E402


def test_wolfram_validate_emits_normalized_receipt(self) -> None:
    envelope = financial_envelope(
        observations=[
            observation("2026-01-05T00:00:00+00:00", 100.0),
            observation("2026-01-12T00:00:00+00:00", 101.0),
        ]
    )
    with tempfile.TemporaryDirectory() as tmp:
        input_path = self._write_json(tmp, "aapl-wolfram.json", envelope)
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = main(
                [
                    "wolfram-validate",
                    "--input",
                    str(input_path),
                    "--start",
                    "2026-01-01",
                    "--end",
                    "2026-02-01",
                ]
            )

    payload = json.loads(stdout.getvalue())
    self.assertEqual(code, 0)
    self.assertEqual(payload["validation"]["provider"], "wolfram")
    self.assertEqual(payload["normalized"]["observation_count"], 2)

def test_treasury_validate_emits_qualifiers_and_range(self) -> None:
    envelope = treasury_envelope(
        observations=[
            treasury_observation("2026-08-12T00:00:00+00:00", 4.55),
            treasury_observation("2026-08-13T00:00:00+00:00", 4.63),
        ]
    )
    with tempfile.TemporaryDirectory() as tmp:
        input_path = self._write_json(tmp, "us10y-wolfram.json", envelope)
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = main(["treasury-validate", "--input", str(input_path)])

    payload = json.loads(stdout.getvalue())
    self.assertEqual(code, 0)
    self.assertEqual(payload["validation"]["qualifiers"]["maturity_duration"], "10Year")
    self.assertEqual(payload["normalized"]["observation_count"], 2)
```

- [ ] **Step 2: Run standalone CLI tests and verify RED**

Run:

```bash
python3 -m unittest \
  tests.test_cli.CliTests.test_wolfram_validate_emits_normalized_receipt \
  tests.test_cli.CliTests.test_treasury_validate_emits_qualifiers_and_range -v
```

Expected: argument-parser errors because both commands are absent.

- [ ] **Step 3: Add parser entries and dependency injection**

Add parser definitions before `portfolio`:

```python
wolfram_validate = subparsers.add_parser(
    "wolfram-validate",
    help="Validate a structured Wolfram financial fallback envelope",
)
wolfram_validate.add_argument("--input", required=True)
wolfram_validate.add_argument("--start", required=True)
wolfram_validate.add_argument("--end")

treasury_validate = subparsers.add_parser(
    "treasury-validate",
    help="Validate a structured Wolfram U.S. Treasury envelope",
)
treasury_validate.add_argument("--input", required=True)
```

Add:

```python
complete.add_argument("--wolfram-input", action="append", default=[])
```

Extend `main`:

```python
def main(
    argv: Sequence[str] | None = None,
    gateway: Any = None,
    market_loader: Callable[..., Any] | None = None,
    workspace_preparer: Callable[..., Any] | None = None,
    workspace_completer: Callable[..., Any] | None = None,
    alpaca_normalizer: Callable[..., Any] | None = None,
    wolfram_normalizer: Callable[..., Any] | None = None,
    treasury_normalizer: Callable[..., Any] | None = None,
) -> int:
```

Import and activate `normalize_wolfram_envelope` and `normalize_treasury_envelope` inside the dependency-bootstrap success path.

- [ ] **Step 4: Implement both validation command outputs**

Use the same JSON shape as `alpaca-validate`:

```python
if args.command == "wolfram-validate":
    history = active_wolfram_normalizer(
        _read_json(args.input),
        start=args.start,
        end=args.end,
    )
    _emit(
        {
            "status": "ok",
            "runtime_receipt": runtime_receipt,
            "validation": history.receipt,
            "normalized": {
                "observation_count": len(history.series),
                "first_at": history.series.index.min().isoformat(),
                "last_at": history.series.index.max().isoformat(),
            },
        },
        sys.stdout,
    )
    return 0

if args.command == "treasury-validate":
    treasury = active_treasury_normalizer(_read_json(args.input))
    _emit(
        {
            "status": "ok",
            "runtime_receipt": runtime_receipt,
            "validation": treasury.receipt,
            "normalized": {
                "observation_count": len(treasury.series),
                "first_at": treasury.series.index.min().isoformat(),
                "last_at": treasury.series.index.max().isoformat(),
                "maturity_years": treasury.maturity_years,
            },
        },
        sys.stdout,
    )
    return 0
```

- [ ] **Step 5: Add a failing mixed-provider complete CLI test**

Construct a two-asset workspace with one Yahoo success and one Yahoo failure, save a valid Wolfram envelope, and run:

```python
complete_code = main(
    [
        "complete-portfolio",
        "--workspace",
        str(workspace_path),
        "--wolfram-input",
        str(wolfram_path),
        "--frequency",
        "weekly",
        "--min-observations",
        "3",
        "--max-weight",
        "1.0",
    ]
)
```

Use four weekly fixture observations and assert:

```python
self.assertEqual(complete_code, 0)
self.assertEqual(
    complete_payload["download_receipt"]["providers"],
    {"AAPL": "yahoo", "MSFT": "wolfram"},
)
self.assertEqual(complete_payload["return_receipt"]["observation_count"], 3)
```

- [ ] **Step 6: Merge Alpaca and Wolfram input lists and preserve error JSON**

Change complete-envelope loading to:

```python
envelopes = [
    *(_read_json(path) for path in args.alpaca_input),
    *(_read_json(path) for path in args.wolfram_input),
]
```

Do not change the existing exit-code contract: `DataGateError` remains JSON on stderr with exit 2, and unexpected errors remain exit 3.

- [ ] **Step 7: Run CLI and workspace tests and commit**

Run:

```bash
python3 -m unittest tests.test_cli tests.test_evidence_workspace -v
```

Expected: all existing and new CLI/workspace tests pass.

```bash
git add tests/test_cli.py scripts/advisor_data_cli.py
git commit -m "Expose Wolfram and Treasury validation commands"
```

---

### Task 6: Align the skill contract, methodology, metadata, and dated canaries

**Files:**
- Create: `tests/test_skill_contract.py`
- Modify: `SKILL.md:1-171`
- Modify: `references/data-contract.md:1-147`
- Modify: `references/methodology.md:1-113`
- Modify: `references/market-coverage.md:1-47`
- Modify: `agents/openai.yaml:1-10`

**Interfaces:**
- Produces: the exact ChatGPT orchestration contract that tells the model when and how to invoke the official Wolfram plugin.
- Produces: deterministic assertions that provider order, plugin boundaries, adjusted-price rules, Treasury coverage, and unavailable-series behavior cannot drift from implementation.

- [ ] **Step 1: Add failing skill-contract tests**

Create `tests/test_skill_contract.py`:

```python
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
```

- [ ] **Step 2: Run contract tests and verify RED**

Run:

```bash
python3 -m unittest tests.test_skill_contract -v
```

Expected: failures because the existing documentation names only Yahoo and Alpaca.

- [ ] **Step 3: Update `SKILL.md` with the exact orchestration order**

Preserve all existing ticker, bootstrap, fundamentals, news, portfolio, and backtest rules. Replace the price-fallback section with explicit rules containing these exact requirements:

```text
Yahoo remains the primary provider. After a Yahoo price data-source failure, classify fallback eligibility semantically from the complete user request and structured Yahoo candidate metadata. Existing eligible U.S. equity and crypto paths try Alpaca first. If Alpaca is ineligible, unavailable, incomplete, or fails its evidence gates, use the official Wolfram plugin when it is connected and an exact Financial entity can be confirmed.

For cumulative-total-return backtests, MPT, or any other return calculation, Wolfram must return AdjustedClose. Price, LatestTrade, Close, and RawClose cannot substitute for AdjustedClose in a total-return calculation.

Do not call Wolfram through direct HTTP, a Python SDK, a separately configured MCP server, or a public webpage. Do not scrape Wolfram result pages or images. Do not request a Wolfram API key. The bundled CLI validates plugin evidence but never calls Wolfram itself.
```

Add exact command examples for `wolfram-validate`, `treasury-validate`, and `complete-portfolio --wolfram-input`. State that numeric calculations use structured Wolfram Language results and source annotations, not rendered images.

Add a Treasury section that instructs the LLM to emit the structured qualifier schema from the design, validate qualifier values with the deterministic harness, preserve `Missing`, and never substitute a nearby maturity. Document the 3-month constant-maturity daily historical default for backtest risk-free rates and the `null` behavior when unavailable.

- [ ] **Step 4: Update the data contract and methodology**

In `references/data-contract.md`, add:

- the complete financial and Treasury envelope examples from the design;
- the known qualifier families and optionality rules;
- `AdjustedClose` versus recent-price property roles;
- one final provider per asset;
- the Wolfram and Treasury error-code lists;
- structured-value and source-annotation requirements;
- plugin-unavailable behavior;
- no direct API, SDK, or scraping route.

In `references/methodology.md`, update the price and portfolio sections so final providers may be `yahoo`, `alpaca`, or `wolfram`. Add a Treasury section with:

```text
Default risk-free proxy: United States 3-month Treasury bill, ConstantMaturity, Daily, historical series covering the backtest window.
Conversion label: effective_annual_to_periodic.
Formula: (1 + annual_percent / 100)^(1 / periods_per_year) - 1.
Alignment: last verified Treasury observation may carry across at most three calendar days.
Failure: dependent Sharpe, Sortino, and alpha fields remain null with risk_free_rate_unavailable.
```

State that this conversion is a disclosed analysis convention rather than a new provider fact.

- [ ] **Step 5: Record the dated Wolfram canaries without creating an allowlist**

Add a `2026-08-16 Wolfram 대안 경로 검증` section to `references/market-coverage.md` with these verified observations:

- AAPL resolved as `Entity["Financial", "NASDAQ:AAPL"]` and returned a dated USD `AdjustedClose` series.
- Wolfram source annotations for the AAPL adjusted series named Finnhub Stock API and Nasdaq Data Link.
- Nominal U.S. Treasury daily constant-maturity histories returned 404 observations from 2025-01-02 through 2026-08-13 for 1-month, 3-month, 6-month, 1-year, 2-year, 3-year, 5-year, 7-year, 10-year, 20-year, and 30-year maturities.
- Current 5-year and 10-year TIPS, 3-month AuctionAverage bill, and 3-month SecondaryMarket bill values returned.
- The Treasury property source annotation named FRED at the Federal Reserve Bank of St. Louis.
- 2-month and 4-month constant-maturity probes returned `Missing` and remain unavailable.

Label every entry as a dated canary, not a permanent availability promise.

- [ ] **Step 6: Update agent metadata**

Set the description and default prompt so they explicitly mention Yahoo-first evidence, eligible Alpaca and Wolfram fallbacks, and Wolfram Treasury evidence. Keep `products: ["chatgpt"]` and `allow_implicit_invocation: true` unchanged.

Use:

```yaml
interface:
  display_name: "증거 기반 포트폴리오 상담가"
  short_description: "Yahoo 우선 검증과 Alpaca·Wolfram 대안, 미 국채 근거로 투자 분석"
  default_prompt: "Use $evidence-first-portfolio-advisor in ChatGPT Work Cloud mode to verify with Yahoo first, use eligible Alpaca or official Wolfram plugin fallbacks when needed, retrieve structured Wolfram U.S. Treasury evidence for requested rates or historical risk-free inputs, preserve every evidence gate, and render explicitly requested backtests with ChatGPT's built-in interactive chart and required evaluation table."
  icon_small: "./assets/icon.svg"
  icon_large: "./assets/icon.svg"
policy:
  products:
  - "chatgpt"
  allow_implicit_invocation: true
```

- [ ] **Step 7: Run contract and focused workflow tests and commit**

Run:

```bash
python3 -m unittest \
  tests.test_skill_contract \
  tests.test_wolfram \
  tests.test_treasury \
  tests.test_evidence_workspace \
  tests.test_cli -v
```

Expected: all contract and workflow tests pass.

```bash
git add \
  tests/test_skill_contract.py \
  SKILL.md \
  references/data-contract.md \
  references/methodology.md \
  references/market-coverage.md \
  agents/openai.yaml
git commit -m "Document Wolfram and Treasury evidence workflow"
```

---

### Task 7: Verify the complete skill and build a local installation artifact

**Files:**
- Verify only: all files changed in Tasks 1-6.
- Create outside Git: a temporary local ZIP under a `mktemp -d` directory.

**Interfaces:**
- Consumes: the complete implementation and documentation commits.
- Produces: deterministic test receipts, optional local validator receipt, local archive-root inspection, live-plugin canary receipts, and a final clean-scope Git review.

- [ ] **Step 1: Run the complete deterministic unit suite**

Run:

```bash
python3 -m unittest discover -s tests -v
```

Expected: every test passes with zero failures and zero errors. Record the actual test count rather than assuming 56 remains current.

- [ ] **Step 2: Run static patch and repository-scope checks**

Run:

```bash
git diff --check origin/main...HEAD
git status --short --branch
git diff --stat origin/main...HEAD
git diff --name-status origin/main...HEAD
```

Expected: no whitespace errors; only the approved implementation, tests, documentation, design, and plan files differ. `.DS_Store` remains untracked and untouched.

- [ ] **Step 3: Run the local skill validator when present**

Locate an available validator without modifying the repository and execute it only when the result is unambiguous:

```bash
advisor_validator_list=$(mktemp)
find "${CODEX_HOME:-$HOME/.codex}" -path '*/scripts/quick_validate.py' -type f -print > "$advisor_validator_list"
advisor_validator_count=$(wc -l < "$advisor_validator_list" | tr -d ' ')
if [ "$advisor_validator_count" = "1" ]; then
  advisor_validator_path=$(sed -n '1p' "$advisor_validator_list")
  python3 "$advisor_validator_path" .
else
  sed -n '1,20p' "$advisor_validator_list"
  test "$advisor_validator_count" = "0"
fi
```

Expected: one located validator exits successfully. A zero-result exit records validator unavailability. More than one result causes the final `test` to fail and must be reported as ambiguity rather than choosing a path.

- [ ] **Step 4: Build and inspect a temporary local ZIP**

Create a temporary directory and run this from the repository root:

```bash
advisor_package_dir=$(mktemp -d)
export ADVISOR_PACKAGE_ZIP="$advisor_package_dir/evidence-first-portfolio-advisor-local.zip"
python3 - <<'PY'
import os
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

output = Path(os.environ["ADVISOR_PACKAGE_ZIP"])
roots = [
    Path("SKILL.md"),
    Path("agents"),
    Path("assets"),
    Path("references"),
    Path("requirements.txt"),
    Path("scripts"),
    Path("tests"),
]
files = []
for root in roots:
    if root.is_file():
        files.append(root)
    else:
        files.extend(path for path in root.rglob("*") if path.is_file())
with ZipFile(output, "w", ZIP_DEFLATED) as archive:
    for path in sorted(files):
        archive.write(path, path.as_posix())
print(output)
PY
unzip -l "$ADVISOR_PACKAGE_ZIP"
unzip -p "$ADVISOR_PACKAGE_ZIP" SKILL.md | sed -n '1,12p'
```

Expected: `SKILL.md` is at the ZIP root; required `agents`, `assets`, `references`, `requirements.txt`, `scripts`, and `tests` entries are present; `.advisor-runtime`, `__pycache__`, `.DS_Store`, live evidence, temporary envelopes, and Git metadata are absent.

- [ ] **Step 5: Run official-plugin live canaries**

Through the official Wolfram plugin in ChatGPT, run fresh structured checks for:

1. AAPL exact financial entity, currency, exchange, `AdjustedClose`, requested date range, and source annotations.
2. One exact non-U.S. financial entity independently matched to a Yahoo candidate.
3. The nominal U.S. Treasury constant-maturity curve over the currently verified 11 maturities on one date.
4. One historical 10-year nominal series.
5. One historical TIPS series.
6. One auction-average bill series.
7. One secondary-market bill series.
8. One unavailable maturity that returns `Missing`.
9. Treasury source annotations.

For each canary, save only the temporary envelope needed to run the new validator, execute `wolfram-validate` or `treasury-validate`, record the output, and remove the temporary envelope afterward. Do not add live provider payloads to Git.

- [ ] **Step 6: Re-run the full suite after live-envelope validation**

Run:

```bash
python3 -m unittest discover -s tests -v
```

Expected: every deterministic test still passes after live validation.

- [ ] **Step 7: Review every commit and report the actual state**

Run:

```bash
git log --oneline --decorate origin/main..HEAD
git status --short --branch
```

Expected: frequent focused commits for financial validation, Treasury validation, curves/risk-free alignment, workspace integration, CLI integration, and documentation. Report test count, validator result, live canary results, ZIP root inspection, remaining untracked user files, and the fact that no push or release occurred.

Do not create a final implementation commit in this step unless verification reveals a required tracked fix. If a fix is needed, add a focused failing regression test, implement the fix, rerun all verification, and commit only that fix with a descriptive message.
