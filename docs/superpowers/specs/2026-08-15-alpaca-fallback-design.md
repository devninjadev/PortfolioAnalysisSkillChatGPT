# Alpaca and Web-Evidence Fallback Design

## Status

Approved direction as of 2026-08-15. This document defines the implementation boundary that must be reviewed before production code changes begin.

## Context

The advisor currently relies on Yahoo Finance through `yfinance` for ticker discovery, price validation, fundamentals, news discovery, asset histories, currency metadata, and FX histories. In ChatGPT cloud, Yahoo access or `yfinance` execution can fail even after dependency bootstrap succeeds.

The installed Alpaca plugin exposes structured historical bars for U.S. equities and cryptocurrencies. Live probes confirmed:

- `AAPL` stock bars are available through the IEX feed.
- `BTC/USD` crypto bars are available through the U.S. crypto feed.
- `005930.KS` is not an Alpaca asset.
- Alpaca stock bars are raw around corporate actions. AAPL moved from a weekly close of `499.345` before its 2020 four-for-one split to `121.11` after the split, so raw bars cannot enter a return matrix without adjustment.

## Goals

1. Keep Yahoo as the primary provider.
2. When Yahoo historical-price retrieval fails, use the installed Alpaca plugin only for semantically classified U.S. equities and cryptocurrencies.
3. Leave Korean equities and other unsupported markets failed when Yahoo history is unavailable.
4. When Yahoo fundamentals or news retrieval fails, use web search for discovery and open authoritative source documents before reporting facts.
5. Preserve deterministic portfolio calculations, source receipts, missingness, and every existing evidence gate.
6. Support mixed-provider portfolios without silently dropping failed assets.

## Non-goals

- Do not call Alpaca's REST API directly or require Alpaca API credentials.
- Do not use Alpaca for Korean equities, arbitrary non-U.S. equities, FX histories, Yahoo ticker search, fundamentals, or news.
- Do not invent a ticker when Yahoo candidate discovery fails.
- Do not treat search-result snippets as verified evidence.
- Do not replace a failed required asset with another security or remove it to force a portfolio result.
- Do not publish a GitHub release or change a release tag without explicit release authorization. The implementation will be made release-ready and packaged locally.

## Provider Routing

| Evidence lane | Primary | Fallback | Unsupported outcome |
| --- | --- | --- | --- |
| Ticker candidate discovery | Yahoo search | None | Stop ticker-dependent analysis |
| Recent price validation | Yahoo adjusted history | Alpaca bars for U.S. equity or crypto | Stop ticker-dependent analysis |
| Historical asset prices | Yahoo adjusted history | Alpaca bars for U.S. equity or crypto | Stop affected price/portfolio analysis |
| Currency metadata and FX | Yahoo | None | Stop affected cross-currency calculation |
| Fundamentals and valuation inputs | Yahoo | Web search plus opened primary or authoritative sources | Preserve unresolved fields as `null` |
| News discovery | Yahoo | Web search | Open source before asserting facts or causality |

Only data-source failures are fallback-eligible. Dependency bootstrap failure, invalid user input, ambiguous ticker resolution, infeasible portfolio constraints, or calculation-gate failures do not trigger a provider fallback.

## Semantic Eligibility Classification

The model classifies fallback eligibility from the user's complete context and structured provider metadata. Korean suffix matching, regular expressions, fixed country allowlists, and symbol heuristics are prohibited.

The model must produce:

```json
{
  "symbol": "AAPL",
  "provider_symbol": "AAPL",
  "fallback_class": "us_equity",
  "evidence": {
    "quote_type": "EQUITY",
    "exchange": "NMS",
    "currency": "USD"
  }
}
```

Allowed `fallback_class` values are:

- `us_equity`
- `crypto`
- `unsupported_market`
- `ambiguous`

The deterministic input harness accepts Alpaca evidence only for `us_equity` and `crypto`. Ambiguous or unsupported classifications fail closed. For a U.S. equity, Alpaca's exact asset response must independently confirm the requested symbol and `us_equity` class. For crypto, the bars response must independently confirm the exact slash-delimited pair requested by the workflow.

Yahoo and Alpaca may represent the same instrument differently. The model may propose an explicit `provider_symbol` from the structured instrument context, such as Yahoo `BTC-USD` to Alpaca `BTC/USD`, but code must never derive that mapping with a suffix or delimiter parser. The Alpaca asset or bars response must confirm the proposed provider symbol, and receipts retain both symbols. An unconfirmed mapping fails closed.

## ChatGPT-to-CLI Bridge

The Alpaca plugin is a model tool, not a Python dependency. The CLI therefore does not attempt to invoke Alpaca itself. ChatGPT orchestrates provider calls while bundled scripts validate and compute.

### Prepare phase

Add a `prepare-portfolio` command:

```bash
python scripts/advisor_data_cli.py prepare-portfolio \
  --symbols AAPL MSFT BTC-USD \
  --start 2021-01-01 \
  --base-currency KRW \
  --workspace /tmp/advisor-evidence.json
```

The command:

1. Attempts Yahoo adjusted-price and currency retrieval per asset so one provider failure does not erase successful assets.
2. Attempts each required Yahoo FX leg independently.
3. Stores successful Yahoo series, currencies, FX series, retrieval receipts, and per-symbol failures in the workspace file.
4. Emits a compact JSON summary listing completed symbols, fallback-required symbols, unresolved FX, and blocking errors.
5. Does not classify markets and does not call Alpaca.

The workspace is schema-versioned and must not contain NaN or infinity.

### Complete phase

For each fallback-required symbol, ChatGPT uses semantic classification and calls the relevant Alpaca tools. It saves one exact, structured fallback envelope per symbol. The envelope distinguishes the canonical Yahoo-side `symbol` used by the portfolio from the independently verified Alpaca `provider_symbol`:

```json
{
  "schema_version": 1,
  "symbol": "BTC-USD",
  "provider_symbol": "BTC/USD",
  "fallback_class": "crypto",
  "classification_evidence": {},
  "asset_response": {},
  "bars_response": {},
  "corporate_actions_response": {}
}
```

Add a `complete-portfolio` command:

```bash
python scripts/advisor_data_cli.py complete-portfolio \
  --workspace /tmp/advisor-evidence.json \
  --alpaca-input /tmp/AAPL-alpaca.json \
  --alpaca-input /tmp/BTC-USD-alpaca.json \
  --frequency weekly \
  --min-observations 104 \
  --max-weight 0.70
```

The command validates every envelope, normalizes eligible Alpaca histories, merges them with the Yahoo series in the workspace, runs the existing return-matrix and portfolio gates, and emits the existing portfolio candidates plus provider receipts. A required unresolved asset or FX leg blocks all weights.

The existing `portfolio` command remains backward compatible and Yahoo-first. It may direct the caller to the prepare/complete workflow in its error details, but it must not silently change providers.

## Alpaca History Contract

### Tool selection

- U.S. equity validation: exact Alpaca asset lookup.
- U.S. equity history: stock bars.
- U.S. equity adjustments: corporate actions for forward splits, reverse splits, stock dividends where representable, and cash dividends.
- Cryptocurrency history: crypto bars.

Weekly portfolio analysis requests `1Week` bars to reduce tool payload size. Daily analysis divides long requests into bounded, non-overlapping date windows and merges them deterministically. Every window must use the same symbol, feed, currency basis, and timeframe.

### Parsing and validation

Add `scripts/advisor_data/alpaca.py` with pure, dependency-injected functions that:

1. Accept raw structured Alpaca result objects or the plugin's JSON-encoded `result` wrapper.
2. Verify the declared tool, symbol, asset class, feed, timeframe, and requested date range.
3. Parse timestamps as UTC and sort ascending.
4. Reject duplicate conflicting timestamps, non-finite values, non-positive closes, malformed records, wrong symbols, empty histories, and unrequested assets.
5. Merge chunked histories without forward-filling.
6. Record missing and clipped coverage rather than claiming complete coverage.

### Corporate-action adjustment

Raw U.S. stock bars never enter portfolio returns directly.

The adapter:

1. Parses corporate actions within the requested history plus the boundary required to adjust the first observation.
2. Applies split ratios backward to pre-ex-date prices.
3. Builds a total-return close series using cash distributions when the pre-ex-date reference price is available.
4. Rejects unknown or internally inconsistent actions that could materially change returns.
5. Records every applied and skipped action, its ex-date, type, and factor.

If the corporate-action response is unavailable, malformed, incomplete, or cannot support a safe adjustment, the U.S. equity fallback fails with no portfolio output. Crypto requires no corporate-action adjustment.

### Frequency alignment

The adapter produces dated price levels, not returns. The existing return-matrix code remains responsible for sampling and alignment. Crypto's seven-day market and U.S. equity bars are normalized onto the advisor's requested weekly basis before common observations are counted. Asset prices are never forward-filled.

## Fundamentals and Valuation Web Fallback

When Yahoo fundamentals fail or critical fields remain missing, the skill uses web search for discovery and opens source pages in this priority order:

1. Company investor relations and official earnings materials.
2. Regulatory filings such as SEC or DART.
3. Exchange filings.
4. Audited annual or interim reports.
5. Reputable secondary financial sources when primary material is unavailable.

Each extracted datum keeps:

- field name and value;
- currency and unit;
- fiscal period and as-of date;
- source URL and retrieval time;
- source role;
- whether it was reported directly or calculated.

Search snippets never satisfy the evidence gate. Valuation calculations must use compatible dates, currencies, units, share bases, and fiscal periods. Unresolved values stay `null` and remain in `missing_fields`.

## News Web Fallback

When Yahoo news discovery fails, web search produces discovery candidates. The workflow opens the publisher article, company release, regulatory filing, or other authoritative source before asserting the event.

Source roles are:

- `discovery_only`: search result found but source not opened;
- `publisher_verified`: publisher page opened and supports the claim;
- `primary_verified`: company, regulator, or exchange source opened and supports the claim.

Search snippets do not establish facts. Temporal proximity between a reported event and a price move does not establish causality.

## Receipts and Errors

Each final asset series records:

- primary provider and primary failure, if any;
- final provider;
- classification evidence;
- Alpaca tool/feed/timeframe;
- requested and observed date range;
- raw and normalized observation counts;
- price basis and currency;
- applied corporate actions;
- missing or clipped coverage;
- retrieval timestamp.

Add these data-gate errors:

- `fallback_not_supported`
- `fallback_class_ambiguous`
- `alpaca_asset_not_found`
- `alpaca_plugin_unavailable`
- `alpaca_history_unavailable`
- `alpaca_history_incomplete`
- `alpaca_schema_error`
- `corporate_actions_unavailable`
- `corporate_action_adjustment_failed`
- `web_evidence_unavailable`
- `web_primary_source_unverified`

The Yahoo failure is preserved alongside any Alpaca failure. Fallback success does not erase why the primary provider failed.

## Documentation and Agent Metadata

Update:

- `SKILL.md` with the exact provider order, tool workflow, stop conditions, and web verification boundary.
- `references/data-contract.md` with fallback schemas, adjustment rules, receipts, and errors.
- `references/methodology.md` with source hierarchy and mixed-provider methodology.
- `references/market-coverage.md` with verified Alpaca examples clearly labeled as dated evidence, not an allowlist.
- `agents/openai.yaml` to state that the installed Alpaca plugin is required for the fallback path, without embedding credentials or pretending the skill owns Alpaca's MCP server.

If the current OpenAI metadata schema cannot express a dependency on a separately installed curated plugin, document that Alpaca must be installed and fail clearly when its tools are unavailable. Do not invent an MCP URL.

When an eligible U.S. equity or crypto fallback is needed but the Alpaca tools are unavailable, stop only the affected analysis and recommend connecting the Alpaca plugin. The user-facing message must explain that no separate Alpaca signup is required and connecting the plugin is sufficient. Do not attempt installation or imply that a fallback was executed.

## Test Strategy

All behavioral implementation follows red-green-refactor.

### Unit tests

- Accept valid U.S. equity, crypto, and JSON-wrapped tool payloads.
- Reject wrong symbol, asset class, feed, malformed timestamps, invalid closes, conflicting duplicates, and empty bars.
- Merge chunks and report clipped coverage.
- Reproduce the raw AAPL split discontinuity, then prove split adjustment removes the false return.
- Apply a cash dividend with a known ex-date and reference price.
- Fail closed when corporate actions are missing or inconsistent.
- Ensure crypto bypasses corporate-action processing.

### Workflow tests

- Prepare preserves successful Yahoo symbols while recording failed symbols separately.
- Complete merges Yahoo and Alpaca series.
- Korean or ambiguous classifications never accept Alpaca evidence.
- Missing required fallback input blocks weights.
- Missing required FX blocks cross-currency weights.
- Mixed-provider receipts survive through final output.
- Existing `portfolio` behavior and output remain backward compatible.

### Skill-contract tests

- Provider order is Yahoo before Alpaca or web search.
- Alpaca scope is limited to U.S. equity and crypto history.
- Search snippets are discovery-only.
- Korean history failure has no fallback.
- An unavailable Alpaca plugin produces a clear, non-fabricated limitation.

### Verification

Run:

```bash
python3 -m unittest discover -s tests -v
```

Then run any locally available skill validator, build a ZIP with `SKILL.md` at the root, inspect its contents, and execute live canaries against Alpaca stock bars, corporate actions, crypto bars, and a Korean unsupported asset. Live provider behavior is reported separately from deterministic unit-test success.

## File-Level Implementation

Expected production changes:

- `scripts/advisor_data/alpaca.py`: Alpaca parsing, validation, adjustment, and receipts.
- `scripts/advisor_data/evidence_workspace.py`: schema-versioned Yahoo/Alpaca workspace serialization and merge.
- `scripts/advisor_data/market_data.py`: reusable per-symbol Yahoo and FX preparation without changing return-matrix gates.
- `scripts/advisor_data_cli.py`: `prepare-portfolio` and `complete-portfolio` commands.
- `SKILL.md`, `agents/openai.yaml`, and relevant references.
- New and updated tests.

No unrelated optimizer, scoring model, ticker resolver, or news-causality changes are included.

## Acceptance Criteria

The work is accepted only when:

1. Existing tests and all new tests pass.
2. An eligible U.S. equity can recover from a simulated Yahoo price failure using adjusted Alpaca evidence.
3. An eligible crypto asset can recover using Alpaca evidence.
4. A Korean equity Yahoo failure remains a failure and never calls or accepts Alpaca.
5. A split discontinuity cannot enter a return matrix unadjusted.
6. Yahoo fundamentals/news failures route to web discovery with opened-source verification requirements.
7. Every output preserves provider, time, coverage, adjustment, missingness, and primary-error receipts.
8. The release-ready ZIP has the correct root and contains no runtime caches or test artifacts.
9. A missing Alpaca plugin produces the no-signup connection recommendation only when an eligible fallback is actually needed.
