# Wolfram Price Fallback and U.S. Treasury Evidence Design

## Status

Approved direction as of 2026-08-16. This document records the reviewed product and data-contract design before implementation planning and production-code changes.

## Context

The advisor currently resolves instruments through Yahoo Finance and uses Yahoo adjusted histories as its primary price source. When Yahoo price retrieval fails, the released `0.9.2` workflow can use the installed Alpaca plugin for semantically verified U.S. equities and cryptocurrencies. Alpaca remains intentionally unavailable for other markets, and raw U.S. stock bars cannot enter portfolio returns without complete corporate-action evidence and deterministic adjustment.

The user wants the official Wolfram plugin available inside ChatGPT to become an additional price fallback and the provider for U.S. Treasury yield data. This integration must use only the Wolfram plugin tools exposed to ChatGPT. It must not add a direct Wolfram HTTP client, scrape Wolfram web pages, require an API key, or turn the skill into a standing data collector.

Live probes through the Wolfram plugin established that:

- `Entity["Financial", "NASDAQ:AAPL"]` exposes `Price`, `LatestTrade`, `Close`, `RawClose`, `AdjustedClose`, `Currency`, `Exchange`, `Symbol`, dividends, and return properties.
- AAPL `AdjustedClose` returned a dated USD `TimeSeries` for a requested historical interval.
- Wolfram documents `AdjustedClose` as adjusted for ordinary dividends and corporate actions, while non-U.S. coverage may have different adjustment limits that must remain visible in receipts.
- `EntityProperty["Country", "Treasury"]` exposes qualifiers for coupon, date, due-date basis, frequency, market, maturity duration, security type, and time-series transformations.
- Treasury security types include `Bill`, `Note`, `Bond`, and `TIPS`.
- Treasury market qualifiers include `AuctionAverage` and `SecondaryMarket`.
- Treasury frequencies include `Daily`, `Weekly`, `BiWeekly`, `Monthly`, `Quarterly`, and `Annual`.
- The Treasury property unit is `Percent`, and source annotations identify FRED at the Federal Reserve Bank of St. Louis for the probed series.
- Daily nominal constant-maturity histories returned 404 observations from 2025-01-02 through 2026-08-13 for 1-month, 3-month, 6-month, 1-year, 2-year, 3-year, 5-year, 7-year, 10-year, 20-year, and 30-year maturities.
- Current 5-year and 10-year TIPS values, a 3-month auction-average bill value, and a 3-month secondary-market bill value also returned successfully.
- A 2-month or 4-month nominal constant-maturity query can return `Missing`; no nearby maturity may be silently substituted.

These probes are dated validation receipts, not a permanent allowlist or a guarantee that every qualifier combination is populated.

## Goals

1. Preserve Yahoo as the primary instrument-resolution and price provider.
2. Add the official Wolfram ChatGPT plugin as an evidence-gated fallback for financial histories when Yahoo fails.
3. Preserve Alpaca as an eligible fallback for U.S. equities and cryptocurrencies.
4. Route every requested instrument only to providers that are semantically eligible and independently confirm the instrument identity.
5. Support Wolfram U.S. Treasury evidence across every security type, market, frequency, maturity, and transformation that the plugin actually returns for a semantically valid request.
6. Provide current Treasury observations, historical Treasury series, same-date yield-curve snapshots, and historical risk-free-rate inputs for backtests.
7. Keep source identity, units, dates, missingness, transformations, and primary-provider failures in machine-verifiable receipts.
8. Preserve all current ticker, currency, FX, return-matrix, optimization, and backtest evidence gates.
9. Fail only the affected analysis when a provider or series is unavailable, while never fabricating a ticker, maturity, price, rate, correlation, metric, or portfolio weight.

## Non-goals

- Do not replace Yahoo as the primary provider.
- Do not remove or weaken the existing Alpaca fallback.
- Do not call Wolfram through direct HTTP, a Python SDK, an API key, or a separately configured MCP server.
- Do not scrape a Wolfram result page or parse rendered images as numerical data.
- Do not construct a persistent Wolfram market-data database or periodic collection service.
- Do not call every Cartesian product of Treasury qualifiers. Full support means accepting and validating every semantically requested combination that Wolfram returns, not bulk-extracting the domain.
- Do not infer Wolfram financial entities from ticker punctuation, exchange suffixes, regular expressions, alias tables, or country allowlists.
- Do not substitute one Treasury maturity, security type, market, frequency, or yield convention for another when the requested series is unavailable.
- Do not blend observations from multiple providers into one asset history.
- Do not use an unadjusted historical price series for total-return backtests, MPT, or other return calculations.
- Do not publish a release, replace a tag, or push to GitHub without separate release authorization.

## Chosen Architecture

Use capability-aware routing. Yahoo remains primary, Alpaca remains the first fallback for its existing eligible classes, and Wolfram expands the fallback pool and owns the Treasury evidence lane.

```text
Instrument request
    |
    v
Yahoo candidate discovery and exact candidate selection
    |
    v
Yahoo validation/history succeeds --------------------------> use Yahoo
    |
    | data-source failure
    v
Structured LLM fallback classification
    |
    +-- U.S. equity or crypto --> Alpaca --> if failed/incomplete --> Wolfram
    |
    +-- other exact financial entity --------------------------> Wolfram
    |
    +-- ambiguous or unconfirmed ------------------------------> fail closed

U.S. Treasury request or risk-free-rate requirement
    |
    v
Structured LLM Treasury intent --> Wolfram Treasury --> deterministic validation
```

Fallbacks are attempted only after a Yahoo data-source failure. A successful Yahoo result is not duplicated unless the user explicitly asks for cross-source verification. Alpaca and Wolfram are alternatives, not row-level co-providers.

## Semantic Classification Harness

All user intent and provider eligibility classification remains model-based. The model consumes the complete user request, the selected Yahoo candidate, structured Yahoo metadata, the primary error, and the calculation's required price basis.

### Financial fallback classification

The model emits a strict object such as:

```json
{
  "symbol": "AAPL",
  "instrument_type": "equity",
  "exchange": "NASDAQ",
  "currency": "USD",
  "required_price_basis": "adjusted_total_return",
  "provider_attempts": [
    {
      "provider": "alpaca",
      "provider_symbol": "AAPL",
      "eligibility_class": "us_equity"
    },
    {
      "provider": "wolfram",
      "entity_prompt": "AAPL stock",
      "eligibility_class": "financial_entity"
    }
  ],
  "classification_evidence": {
    "yahoo_candidate": {
      "symbol": "AAPL",
      "exchange": "NASDAQ",
      "issuer": "Apple Inc.",
      "security_type": "Equity",
      "share_class": "CommonStock",
      "currency": "USD"
    }
  }
}
```

The harness accepts only known provider identifiers and known eligibility classes. The model may propose a provider-specific symbol or entity prompt, but the provider response must independently confirm it. No deterministic code derives a provider symbol from suffixes or delimiters.

Provider order is stable:

1. Existing Alpaca-eligible U.S. equity or crypto paths remain first to preserve current behavior.
2. Wolfram follows when Alpaca is ineligible, unavailable, incomplete, or fails its evidence gates.
3. Markets outside Alpaca's scope may proceed directly to Wolfram.
4. Ambiguous classifications fail without calling a provider.

### Treasury intent classification

The model emits a strict object such as:

```json
{
  "country": "UnitedStates",
  "security_type": "TIPS",
  "maturity_duration": "10Year",
  "maturity_years": 10.0,
  "market": null,
  "due_date": "ConstantMaturity",
  "frequency": "Daily",
  "date_range": {
    "start": "2020-01-01",
    "end": "2026-08-13"
  },
  "time_series_operator": null,
  "coupon_rate": null,
  "intended_use": "historical_real_yield"
}
```

The harness validates security type, market, due-date basis, frequency, and transformation against qualifier metadata returned by Wolfram. `MaturityDuration`, `Date`, and `CouponRate` accept typed values rather than a fixed textual allowlist; the resulting property and output must still confirm the requested semantics.

The allowed intended-use classes are:

- `current_rate`
- `historical_rate`
- `yield_curve_snapshot`
- `historical_yield_curve`
- `risk_free_rate`
- `rate_change_analysis`

Text matching and Korean morphological parsing are prohibited. Classification failures remain explicit and do not trigger a guessed default except for the documented backtest risk-free-rate default.

## ChatGPT-to-CLI Boundary

The Wolfram plugin is a ChatGPT tool, not a bundled Python dependency. The CLI never attempts to authenticate to or call Wolfram.

ChatGPT performs the remote orchestration:

1. Confirm that the Wolfram plugin tools are callable.
2. Use Wolfram context when the plugin contract requires topic initialization.
3. Use natural-language interpretation to obtain typed entities and dates.
4. Use Wolfram Language evaluation for structured financial and Treasury values.
5. Request source annotations separately when they are not present in the value response.
6. Convert the tool result into an exact evidence envelope without summarizing away raw dates, values, units, entities, qualifiers, or source metadata.
7. Pass the envelope to bundled deterministic validation and calculation commands.

The Wolfram evaluator request uses a fixed code template. Only JSON-encoded values from the structured classifier may fill the template. The model does not generate arbitrary Wolfram Language programs for this workflow.

The preferred evaluator output is a JSON-compatible association containing:

- interpreted entity canonical name;
- interpreted property canonical name;
- exact qualifiers;
- dates as ISO 8601 strings;
- numeric magnitudes;
- unit name;
- source names, organizations, and URLs when returned;
- requested and observed ranges;
- missing-value markers;
- retrieval time supplied by the orchestration layer.

Rendered charts and images are presentation evidence only. Numerical calculations use structured values.

## Financial History Contract

### Identity validation

A Wolfram financial history is eligible only if the response identifies a `Financial` entity and provides enough metadata to match the selected Yahoo candidate. The validator compares all available fields:

- provider entity canonical name;
- symbol;
- exchange;
- official name or company;
- instrument type;
- quote currency.

The classification evidence carries two independent structured objects: the selected `yahoo_candidate` identity and provider-returned `wolfram_observed` identity. Required symbol, exchange, issuer/company, security type, currency, provider entity, and at least one share-class/instrument-subtype field must be present. The deterministic validator compares every required and available field against the returned result. A bare model-authored `identity_decision=match` is not evidence. Any omission or conflict in symbol/provider entity, exchange, issuer, share class/instrument subtype, security type, or currency rejects the envelope with `wolfram_entity_mismatch`.

ADR, ordinary share, preferred share, ETF, fund, index, currency pair, commodity, and cryptocurrency identities remain distinct. The validator never merges them merely because names are similar.

### Permitted price bases

| Use | Permitted Wolfram properties |
| --- | --- |
| Current or recent-price statement | `Price`, `LatestTrade`, or dated `Close` with an as-of timestamp |
| Historical chart without a total-return claim | `Close` only when the adjustment convention is disclosed |
| Portfolio returns, MPT, cumulative-total-return backtest | `AdjustedClose` |

`RawClose` is retained only as diagnostic evidence. It never enters total-return or MPT calculations.

The validator rejects:

- non-positive or non-finite prices;
- invalid or duplicate conflicting dates;
- an entity other than the declared one;
- a property other than the declared one;
- a currency conflict;
- an empty series;
- fewer than two observations for a historical request;
- a request range that differs from the CLI/workspace range;
- an `AdjustedClose` endpoint clipped by more than the seven-calendar-day market-calendar endpoint tolerance (ordinary weekend/holiday differences inside the tolerance remain valid);
- a total-return calculation backed by anything other than `AdjustedClose`.

Asset prices are not forward-filled. Sampling and common-date alignment remain the responsibility of the existing return-matrix code.

### Provider selection

If multiple fallbacks succeed during an explicitly requested cross-source verification, each series is validated separately. The workflow does not average values or splice observations. It compares:

- identity confidence;
- requested-range coverage;
- adjustment basis;
- currency confirmation;
- observation count and missingness;
- source metadata availability;
- retrieval timestamp.

The selected series and rejected alternatives are recorded. For ordinary fallback execution, the next provider is called only when the earlier eligible provider fails, so duplicate calls and token use are avoided.

## Wolfram Financial Evidence Envelope

```json
{
  "schema_version": 1,
  "provider": "wolfram",
  "evidence_kind": "financial_history",
  "symbol": "AAPL",
  "provider_entity": "NASDAQ:AAPL",
  "requested_property": "AdjustedClose",
  "required_price_basis": "adjusted_total_return",
  "classification_evidence": {
    "yahoo_candidate": {
      "symbol": "AAPL",
      "exchange": "NASDAQ",
      "issuer": "Apple Inc.",
      "security_type": "Equity",
      "share_class": "CommonStock",
      "currency": "USD"
    },
    "wolfram_observed": {
      "provider_entity": "NASDAQ:AAPL",
      "symbol": "AAPL",
      "exchange": "NASDAQ",
      "issuer": "Apple Inc.",
      "security_type": "Equity",
      "share_class": "CommonStock",
      "currency": "USD"
    }
  },
  "primary_failure": {
    "provider": "yahoo",
    "code": "price_history_unavailable",
    "message": "Yahoo returned no usable price history."
  },
  "request": {
    "start": "2021-01-01",
    "end": "2026-08-13"
  },
  "result": {
    "entity_type": "Financial",
    "entity": "NASDAQ:AAPL",
    "symbol": "AAPL",
    "exchange": "NASDAQ",
    "issuer": "Apple Inc.",
    "security_type": "Equity",
    "share_class": "CommonStock",
    "currency": "USD",
    "property": "AdjustedClose",
    "unit": {
      "name": "USDollars",
      "canonical_currency": "USD",
      "quantity_kind": "monetary"
    },
    "observations": []
  },
  "sources": [],
  "retrieved_at": "2026-08-16T00:00:00Z"
}
```

The exact tool response wrapper may also be retained when available, but the normalized association is mandatory. The validator does not depend on rendered prose or an image.

The monetary unit relationship is structured and deterministic. The initial verified mapping includes `USDollars → USD` and `Euros → EUR`; future unit names require an explicit mapping addition rather than a country allowlist or free-form model assertion. `AdjustedClose` uses a seven-calendar-day market-calendar endpoint tolerance. Start coverage is measured from the first observation on or after the requested start; an open-ended series containing only pre-window observations is incomplete. Recent-price properties do not use the historical coverage gate and instead use their separate seven-day freshness policy.

## Treasury Capability Contract

The Treasury adapter supports every semantically valid combination returned by Wolfram from the following known qualifier families:

- `SecurityType`: `Bill`, `Note`, `Bond`, `TIPS`
- `Market`: `AuctionAverage`, `SecondaryMarket`
- `DueDate`: `ConstantMaturity`
- `Frequency`: `Daily`, `Weekly`, `BiWeekly`, `Monthly`, `Quarterly`, `Annual`
- `TimeSeriesOperator`: `Change`, `ChangeRate`, `AnnualChange`, `AnnualizedChangeRate`, `YearOverYearChangeRate`
- typed `MaturityDuration`
- typed `CouponRate`
- typed `Date` or date interval

These metadata values are refreshed from the Wolfram property when the plugin can return them. The documented values are the validator baseline when the metadata call is unavailable, but a requested result must still confirm all relevant qualifiers.

Full support is capability-driven:

1. The classifier expresses the user's requested Treasury semantics.
2. The tool request preserves those semantics exactly.
3. A returned value or series is accepted only when its entity, qualifiers, unit, dates, and source metadata pass validation.
4. `Missing`, an incompatible unit, an empty history, or a conflicting interpretation fails the requested series.
5. The workflow never substitutes another maturity or convention.

## Treasury Evidence Modes

### Current rate

Return one current or last-known observation with:

- security type;
- maturity;
- market and due-date basis;
- value and `Percent` unit;
- observation date, which may differ from retrieval time;
- source annotation;
- retrieval time.

A current value without an observation date is usable only as a displayed current fact with an explicit date limitation. It is not accepted for a point-in-time backtest calculation.

### Historical rate

Return a dated series for one fully specified Treasury property. The validator checks ascending dates, numeric values, unit, duplicates, requested range, observed range, missingness, and minimum observations required by the downstream calculation.

Treasury yields may be negative; unlike asset prices, the validator does not require them to be positive. It requires finite magnitudes and a recognized percentage unit.

### Yield-curve snapshot

A yield-curve snapshot is a set of independently validated rates sharing one requested observation date. Each curve point preserves its security type, maturity, market, due-date basis, value, unit, and actual observation date.

Curve construction rules:

- Never silently carry a point from a different date into the observed curve.
- A missing maturity remains visibly missing.
- If interpolation is requested, keep observed points and calculated points in separate fields.
- Label interpolation as `calculation`, never `fact`.
- Record the interpolation method and prohibit extrapolation unless the user explicitly requests it.
- Do not describe an interpolated curve as the provider's raw curve.

### Historical yield curve

A historical curve panel is built from separately validated maturity series. The deterministic join retains only dates that satisfy the declared alignment policy. Default alignment requires the same observation date. Any looser alignment must be user-requested and disclosed.

### Rate transformations

When Wolfram directly returns one of its declared time-series operators, preserve that operator in the receipt. When the advisor calculates a change from validated raw yields, label it as a local `calculation` and retain the formula. Do not confuse basis-point changes with percent changes.

## Treasury Evidence Envelope

```json
{
  "schema_version": 1,
  "provider": "wolfram",
  "evidence_kind": "us_treasury_history",
  "country_entity": "UnitedStates",
  "qualifiers": {
    "security_type": "TIPS",
    "maturity_duration": "10Year",
    "market": null,
    "due_date": "ConstantMaturity",
    "frequency": "Daily",
    "time_series_operator": null,
    "coupon_rate": null
  },
  "request": {
    "start": "2020-01-01",
    "end": "2026-08-13",
    "requested_qualifiers": {
      "security_type": "TIPS",
      "maturity_duration": "10Year",
      "market": null,
      "due_date": "ConstantMaturity",
      "frequency": "Daily",
      "time_series_operator": null,
      "coupon_rate": null
    },
    "requested_maturity": {
      "duration": "10Year",
      "years": 10.0,
      "unit": "years",
      "evidence_kind": "classifier_typed_request"
    }
  },
  "result": {
    "property": "Treasury",
    "maturity_years": 10.0,
    "observed_qualifiers": {
      "security_type": "TIPS",
      "maturity_duration": "10Year",
      "market": null,
      "due_date": "ConstantMaturity",
      "frequency": "Daily",
      "time_series_operator": null,
      "coupon_rate": null
    },
    "observed_maturity": {
      "duration": "10Year",
      "years": 10.0,
      "unit": "years",
      "evidence_kind": "provider_observed_typed"
    },
    "unit": "Percent",
    "observations": [],
    "missing": []
  },
  "sources": [
    {
      "name": "FRED (Federal Reserve Economic Data)",
      "organization": "Federal Reserve Bank of St. Louis",
      "url": "http://research.stlouisfed.org/fred2/"
    }
  ],
  "retrieved_at": "2026-08-16T00:00:00Z"
}
```

The source list is evidence returned by Wolfram and may differ by series. The adapter does not hardcode FRED as the source for every Treasury result.

Successful Treasury envelopes require complete and exactly equal declared, requested, and provider-observed qualifier structures. Requested and provider-observed typed numeric maturity evidence must agree with `maturity_years`; no code parses a label such as `10Year` to invent that number. An unavailable `Missing[NotAvailable]` response may omit provider-observed qualifiers and maturity because the provider observed no series; the exact Missing gate still wins and no nearby series is substituted.

## Risk-Free-Rate Contract

When an explicit backtest requires Sharpe, Sortino, or alpha and the user supplies no risk-free-rate series, use this documented default:

- United States Treasury bill;
- 3-month maturity;
- constant-maturity basis;
- daily frequency;
- historical observations covering the backtest window;
- Wolfram as the immediate provider;
- the source annotation returned for that exact series.

The default is a modeling convention, not an assertion that one risk-free proxy is universally correct. A user-specified verified series overrides it.

Wolfram Treasury observations are annualized percentage yields. Convert each finite annual percentage magnitude `y` into a decimal and then into the analysis period return:

```text
annual_decimal = y / 100
periodic_rate = (1 + annual_decimal)^(1 / periods_per_year) - 1
```

The implementation must safely handle negative yields greater than `-100%`. The annualization count follows the actual return frequency used by the metric calculation. The rate series is aligned to portfolio returns under a declared rule, with no unlimited forward fill.

Default alignment permits carrying the last known Treasury observation across at most three calendar days to accommodate weekends and adjacent holidays. Any remaining missing risk-free observation blocks the dependent metric over that range unless the metric implementation explicitly supports and discloses a narrower common sample.

Receipts preserve:

- Treasury series qualifiers;
- raw annual percentages;
- conversion convention;
- return frequency and periods per year;
- alignment rule;
- first and last aligned dates;
- missing observations;
- source and retrieval time.

Every aligned receipt item preserves the raw annual percentage and resulting periodic rate. The receipt also carries unit, retrieval time, requested/observed range, evidence kind, missing markers, and an upstream provenance object containing the original Treasury entity, property, maturity, qualifiers, and source annotations.

If no verified risk-free-rate series is available, Sharpe, Sortino, and alpha remain `null` with `risk_free_rate_unavailable`. The workflow does not invent a constant rate.

## Mixed-Provider Workspace

Keep the existing schema-versioned prepare/complete architecture and extend it without breaking Alpaca callers.

### Prepare

`prepare-portfolio` continues to save successful Yahoo assets, currencies, FX legs, receipts, and per-symbol failures. Only failures proven to originate at the Yahoo `asset_price` stage become `fallback_required_symbols`: `price_history_unavailable` remains price-specific, while `network_error` requires an explicit `details.stage == "asset_price"`. Generic network errors and `currency_metadata`, `fx_history`, schema, or other non-price stages stop. For an asset-price-stage failure, prepare independently retrieves and stores Yahoo currency metadata for the failed symbol and every required Yahoo asset/base FX leg before emitting the workspace.

### Complete

Extend `complete-portfolio` with repeatable Wolfram input support:

```bash
python scripts/advisor_data_cli.py complete-portfolio \
  --workspace /tmp/advisor-evidence.json \
  --alpaca-input /tmp/AAPL-alpaca.json \
  --wolfram-input /tmp/SAP-wolfram.json \
  --frequency weekly \
  --min-observations 104 \
  --max-weight 0.70
```

Rules:

- Each failed required asset receives exactly one accepted final fallback envelope.
- Multiple attempted-provider envelopes for one symbol are allowed only in an explicit provider-verification workflow and must declare which one was selected.
- Extra, duplicate, or unrelated envelopes are rejected.
- A Wolfram asset history does not replace Yahoo currency metadata or required Yahoo FX legs unless a future separately approved design adds an equivalent currency/FX fallback. Its normalized currency must equal stored Yahoo currency, and calculations use the Yahoo original currency unit as authority.
- Missing required FX continues to block cross-currency calculations.
- The final download receipt records one provider per asset.
- No required asset is silently dropped.

Add standalone validation commands:

```bash
python scripts/advisor_data_cli.py wolfram-validate \
  --input /tmp/AAPL-wolfram.json \
  --start 2021-01-01 \
  --end 2026-08-13

python scripts/advisor_data_cli.py treasury-validate \
  --input /tmp/US10Y-wolfram.json
```

Add no command that directly invokes the Wolfram service.

## Error Contract

Add provider-specific errors:

- `wolfram_plugin_unavailable`
- `wolfram_interpretation_failed`
- `wolfram_entity_mismatch`
- `wolfram_property_unavailable`
- `wolfram_history_unavailable`
- `wolfram_history_incomplete`
- `wolfram_schema_error`
- `wolfram_unit_mismatch`
- `wolfram_source_unavailable`
- `treasury_series_unavailable`
- `treasury_maturity_unavailable`
- `treasury_alignment_failed`
- `risk_free_rate_unavailable`

The original Yahoo failure remains in the receipt after fallback success or failure. An Alpaca failure also remains visible when Wolfram is attempted afterward.

When the Wolfram plugin is required but unavailable, the affected analysis stops and the skill recommends connecting the official Wolfram plugin in ChatGPT. It does not request a separate Wolfram API key, install a Python package, call the public website, or claim that a fallback ran.

## Documentation and Agent Metadata

Update:

- `SKILL.md` with the provider router, Wolfram plugin-only workflow, Treasury intent contract, risk-free default, and stop conditions.
- `agents/openai.yaml` so the short description and default prompt mention eligible Alpaca and Wolfram fallbacks and Wolfram Treasury evidence.
- `references/data-contract.md` with both Wolfram envelopes, validation rules, workspace integration, and errors.
- `references/methodology.md` with provider hierarchy, Treasury evidence roles, yield-curve rules, and risk-free-rate calculations.
- `references/market-coverage.md` with dated Wolfram financial and Treasury canary results, clearly labeled as evidence rather than an allowlist.

If the current skill metadata cannot express a dependency on a separately installed curated plugin, document the runtime requirement and fail clearly when the tool is unavailable. Do not invent a plugin identifier, MCP URL, or authentication flow.

## File-Level Implementation

Expected production changes:

- `scripts/advisor_data/wolfram.py`: Wolfram financial envelope parsing, identity validation, history normalization, and receipts.
- `scripts/advisor_data/treasury.py`: Treasury qualifier validation, time-series normalization, yield-curve assembly, periodic risk-free conversion, and receipts.
- `scripts/advisor_data/evidence_workspace.py`: provider-neutral fallback dispatch and Wolfram merge support.
- `scripts/advisor_data_cli.py`: `wolfram-validate`, `treasury-validate`, and `--wolfram-input` support.
- `SKILL.md`, `agents/openai.yaml`, and the relevant references.
- New and updated deterministic tests.

No unrelated ticker resolver, optimizer, scoring system, fundamentals path, news path, chart platform, or runtime dependency changes are included.

## Test Strategy

All behavioral implementation follows red-green-refactor.

### Wolfram financial adapter tests

- Accept an exact financial entity with a valid adjusted USD history.
- Accept JSON-encoded plugin wrappers and normalized associations.
- Reject an entity type other than `Financial`.
- Reject conflicting symbol, exchange, issuer, share class, security type, or currency.
- Reject the wrong requested property.
- Reject empty, non-finite, non-positive, malformed, or conflicting duplicate observations.
- Reject a total-return or MPT request backed by `Close` or `RawClose`.
- Preserve source metadata, requested range, observed range, missingness, and the Yahoo primary failure.
- Keep current-price validation separate from historical total-return eligibility.

### Treasury adapter tests

- Accept `Bill`, `Note`, `Bond`, and `TIPS` envelopes.
- Accept `AuctionAverage`, `SecondaryMarket`, and constant-maturity semantics when returned.
- Accept all declared frequencies and time-series transformations.
- Accept typed maturities without a fixed maturity allowlist.
- Preserve negative finite yields.
- Reject a non-percent unit, conflicting qualifiers, malformed dates, conflicting duplicates, and empty histories.
- Preserve `Missing` values and fail only the requested unavailable series.
- Never substitute a nearby maturity.
- Assemble a same-date curve from independently validated points.
- Separate observed and interpolated curve points.
- Reject undisclosed cross-date curve mixing.

### Risk-free-rate tests

- Convert annual percentage yields into daily, weekly, and monthly periodic rates.
- Handle negative yields safely.
- Align through at most three calendar days.
- Reject remaining uncovered return dates.
- Keep dependent metrics `null` when the risk-free series is unavailable.
- Preserve the selected series, formula, frequency, dates, source, and missingness.

### Workflow tests

- Yahoo success never calls or requires a fallback.
- U.S. equity and crypto failures retain Alpaca as the first eligible fallback.
- Wolfram is attempted after an eligible Alpaca failure.
- Alpaca-ineligible but Wolfram-confirmed financial entities can recover.
- Ambiguous or mismatched entities fail closed.
- `complete-portfolio` merges Yahoo, Alpaca, and Wolfram histories without dropping symbols.
- Missing required Wolfram input or Yahoo FX blocks weights.
- Extra and duplicate envelopes are rejected.
- Existing `--alpaca-input` callers remain backward compatible.

### Skill-contract tests

- The instructions require the official ChatGPT Wolfram plugin and prohibit direct API, SDK, and web-scraping fallbacks.
- Yahoo remains primary.
- Alpaca remains eligible for U.S. equities and cryptocurrencies.
- Wolfram numeric calculations use structured values rather than rendered images.
- Treasury classification is LLM-structured and harness-validated.
- A missing Wolfram plugin produces a truthful connection recommendation.
- No result claims an unavailable maturity or fabricated risk-free rate.

### Live canaries

After deterministic tests pass, run plugin canaries separately from the unit suite:

- AAPL exact financial entity and adjusted history.
- One non-U.S. financial entity whose Yahoo identity can be independently confirmed.
- One cryptocurrency or another financial entity class if Wolfram returns an exact match.
- The nominal constant-maturity curve across the currently verified 11 maturities.
- At least one TIPS series.
- At least one auction-average bill series.
- At least one secondary-market bill series.
- One intentionally unavailable maturity to confirm `Missing` handling.
- Source annotation retrieval.

Canary results are dated receipts. A canary failure does not invalidate deterministic unit tests, but it blocks claiming that the affected live provider path is operational at release time.

## Verification

Run the complete unit suite from the canonical checkout:

```bash
python3 -m unittest discover -s tests -v
```

Then:

1. Run any locally available skill validator.
2. Build a local ZIP with `SKILL.md` at the ZIP root.
3. Inspect the archive root and exclude `.advisor-runtime`, caches, live evidence, temporary envelopes, and test artifacts.
4. Run the live Wolfram canaries through the official ChatGPT plugin.
5. Record deterministic and live results separately.

No release or remote publication occurs without explicit authorization.

## Acceptance Criteria

The implementation is accepted only when:

1. The complete existing and new unit suite passes.
2. Yahoo remains the primary provider and successful Yahoo histories are not duplicated.
3. Existing Alpaca fallback behavior and compatibility are preserved.
4. An exact Wolfram financial entity can recover from a simulated Yahoo history failure with `AdjustedClose` evidence.
5. A mismatched or ambiguous Wolfram entity cannot enter a price or return calculation.
6. A mixed Yahoo, Alpaca, and Wolfram portfolio preserves every required asset and one final provider per series.
7. Required Yahoo currency metadata and FX gates remain intact.
8. Current and historical Treasury evidence preserves security type, maturity, market, frequency, date, unit, source, and missingness.
9. Every Wolfram-returned valid Treasury qualifier combination can pass without adding a text parser or maturity allowlist.
10. An unavailable Treasury combination stays unavailable and is never replaced by a nearby maturity.
11. Yield-curve snapshots separate observed, missing, and calculated points.
12. Backtest risk-free rates use a validated historical series and disclosed periodic conversion.
13. Missing risk-free evidence produces `null` dependent metrics rather than an invented constant.
14. Plugin absence produces `wolfram_plugin_unavailable` and an official-plugin connection recommendation.
15. The implementation contains no direct Wolfram API, SDK, web scraping, or arbitrary Wolfram-code execution path.
16. Documentation, agent metadata, runtime errors, and tests describe the same provider and Treasury contracts.
17. The local package validates and contains no live or runtime-local evidence artifacts.
