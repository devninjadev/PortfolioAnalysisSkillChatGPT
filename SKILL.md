---
name: evidence-first-portfolio-advisor
description: Use in ChatGPT Work Cloud mode when analyzing listed equities, ETFs, or cryptoassets; resolving a security name to a Yahoo ticker; verifying prices, fundamentals, valuation, or news; constructing evidence-backed multi-asset portfolio candidates; or fulfilling an explicit backtest request.
---

# Evidence-First Portfolio Advisor

Give conditional investment counseling from retrieved evidence. Never turn missing data into a confident opinion, weight, price claim, or trade instruction.

This skill runs only in ChatGPT Work Cloud mode.

## Follow the evidence gates

1. Classify the request semantically with an LLM into:
   - instruments mentioned by the user;
   - requested analyses: price, fundamentals, news, portfolio, backtest;
   - decision constraints actually supplied by the user;
   - unresolved ambiguities.
2. Resolve every name to a Yahoo candidate set. Do not invent ticker suffixes or select a symbol absent from the returned set. Validate the selected candidate with price history. Ask the user only when two or more plausible candidates remain.
3. Fetch the required data before making factual claims. Use Yahoo first. If Yahoo price evidence fails, follow the explicit Alpaca/Wolfram price fallback below; fundamentals and news retain their opened-web-source fallback. If fields remain missing, state the gap and stop only the affected analysis.
4. Separate `fact`, `calculation`, `interpretation`, and `scenario` in the answer. Preserve the retrieval date, market/currency basis, observation window, and missing fields.
5. Treat all portfolio weights as research candidates, never orders. Do not prescribe allocation or timing unless the user supplied horizon, risk/loss tolerance, liquidity needs, existing holdings, and major constraints.

Read [references/methodology.md](references/methodology.md) before giving counseling. Read [references/data-contract.md](references/data-contract.md) before running scripts or interpreting an error. Consult [references/market-coverage.md](references/market-coverage.md) for dated verification examples/receipts; treat it as evidence, not an allowlist.

## Bootstrap runtime dependencies

Run the bundled CLI directly. It first imports `yfinance`, `pandas`, `numpy`, and `scipy`; when any are missing, it must install `requirements.txt` with the active Python interpreter into an isolated runtime directory, add that directory to the import path, and recheck every dependency before continuing. A missing import is an installation trigger, not an analysis error.

Do not report `cloud_runtime_unavailable` or replace the requested calculation merely because the first import failed. Stop script-based calculations only if the automatic installation command fails, no writable isolated directory exists, or the installed modules still cannot be imported. Treat Yahoo HTTP errors, rate limits, empty histories, and schema failures as data-source errors after dependency bootstrap, not as dependency failures. Fundamentals and news may still use the opened-web-source fallback when the Yahoo runtime is unavailable. The CLI returns a `runtime_receipt` on successful commands.

## Resolve instruments

Use structured LLM judgment, not Korean substring rules, to rank Yahoo candidates by the user's full context: legal/brand name, country, exchange, security type, and requested instrument class.

```bash
python scripts/advisor_data_cli.py search \
  --query '삼성전자' \
  --query-variant 'Samsung Electronics' \
  --query-variant '005930' \
  --instrument-type equity
python scripts/advisor_data_cli.py validate --symbol 005930.KS --candidate-symbols 005930.KS 005935.KS
```

Generate query variants semantically from known official/local names, romanization, country, exchange, and user-supplied codes. Do not use a fixed alias parser. The chosen symbol must appear verbatim in `candidates`. If validation fails, do not continue with that ticker.

## Retrieve evidence

```bash
python scripts/advisor_data_cli.py fundamentals --symbol 005930.KS
python scripts/advisor_data_cli.py news --symbol AAPL --count 10
```

Yahoo news is discovery-only. Open the linked publisher or official filing before asserting what happened or that news caused a price move. Never infer an event from a chart alone. Treat missing valuation fields as unknown, not zero.

## Use Yahoo first, then eligible fallbacks

Yahoo remains the primary provider. After a Yahoo price data-source failure, classify fallback eligibility semantically from the complete user request and structured Yahoo candidate metadata. Existing eligible U.S. equity and crypto paths try Alpaca first. If Alpaca is ineligible, unavailable, incomplete, or fails its evidence gates, use the official Wolfram plugin when it is connected and an exact Financial entity can be confirmed.

Do not call Alpaca, Wolfram, or web search merely to duplicate a successful Yahoo result. Only a failure proven to originate in Yahoo's asset-price stage enters the asset fallback lane: the price-specific `price_history_unavailable` code is eligible, and a production `network_error` is eligible only when its structured receipt says `stage: asset_price`. Generic or unscoped network errors, `currency_unavailable`, schema, and other non-price failures remain blocking. Yahoo remains mandatory for asset currency metadata and is the currency authority even when a final asset price provider is Alpaca or Wolfram. Required FX is tried through Yahoo first; only failed Yahoo FX legs may enter the separate official-Wolfram-plugin FX fallback below. The asset fallback's normalized currency must match Yahoo, while calculations retain Yahoo's original currency unit. Select exactly one final validated price provider per asset and one provider per FX currency; do not splice providers within either series.

### Alpaca fallback for eligible historical prices

Use the installed Alpaca plugin only after a resolved symbol's Yahoo recent or historical price retrieval fails. Classify eligibility semantically with an LLM from the full user context and structured Yahoo candidate metadata:

```json
{
  "symbol": "BTC-USD",
  "provider_symbol": "BTC/USD",
  "fallback_class": "crypto",
  "evidence": {
    "quote_type": "CRYPTOCURRENCY",
    "currency": "USD"
  }
}
```

The only eligible classes are `us_equity` and `crypto`. `unsupported_market` and `ambiguous` fail closed. Do not classify with suffixes, delimiters, regexes, alias tables, or country allowlists. A model-proposed provider symbol must be confirmed by the Alpaca response.

- For `us_equity`, call Alpaca's exact asset lookup, stock bars, and corporate actions for the requested range. Save the structured responses in the envelope defined by [references/data-contract.md](references/data-contract.md). Raw stock bars cannot enter returns before split and cash-distribution adjustment.
- For `crypto`, call Alpaca crypto bars and preserve the exact slash-delimited provider symbol. Crypto requires no corporate-action response.
- For a Korean equity or any other unsupported market, do not call Alpaca and do not remove or replace the failed asset.
- Alpaca does not replace Yahoo currency metadata. Required FX uses Yahoo first and may use the separately validated Wolfram FX fallback only after Yahoo fails.

For a single recent-price validation, save the envelope and run:

```bash
python scripts/advisor_data_cli.py alpaca-validate \
  --input /tmp/AAPL-alpaca.json \
  --start 2026-07-01 \
  --end 2026-08-15
```

If an eligible fallback is needed but the Alpaca tools are not installed or callable, report `alpaca_plugin_unavailable`, do not claim that an Alpaca fallback ran, and continue to the official Wolfram plugin decision below. Show this recommendation:

> 미국 주식·크립토 가격의 대안 출처로 Alpaca 플러그인을 사용할 수 있습니다. 별도 회원가입은 필요 없고, 플러그인을 연결하기만 하면 됩니다.

Do not show that recommendation for Korean equities, unsupported markets, ambiguous instruments, successful Yahoo retrievals, or unrelated analyses.

### Wolfram fallback for exact financial evidence

Use the official Wolfram plugin only after Yahoo price evidence fails and Alpaca is semantically ineligible, unavailable, incomplete, or rejected by its evidence gates. Resolve a Wolfram `Financial` entity from the complete request, Yahoo candidate metadata, selected Yahoo symbol, instrument type, exchange, and expected currency with structured LLM judgment. The envelope must carry separate structured `yahoo_candidate` and `wolfram_observed` identities. Deterministic validation compares symbol/provider entity, exchange, issuer/company, security type, share class/instrument subtype, and currency against the provider result; never accept a bare model-authored `identity_decision=match`. Invoke Wolfram only when that identity is exact; preserve the complete structured Wolfram Language result, source annotations, declared entity, requested property, observations, currency, structured monetary unit/canonical currency, and retrieval time in the evidence envelope. Numeric calculations use structured Wolfram Language results and source annotations, never rendered images.

For cumulative-total-return backtests, MPT, or any other return calculation, Wolfram must return `AdjustedClose`. `Price`, `LatestTrade`, `Close`, and `RawClose` cannot substitute for `AdjustedClose` in a total-return calculation. The envelope request range must exactly match the CLI/workspace range. `AdjustedClose` endpoint differences up to seven calendar days are tolerated for ordinary market weekends and adjacent holidays; larger clipping is `wolfram_history_incomplete`. Every history, including an open-ended request, must contain at least one observation on or after the requested start; pre-window observations cannot satisfy start coverage. A recent-price-only check may use the validated recent-price property under its separate seven-day freshness policy, but it cannot become a return series.

Do not call Wolfram through direct HTTP, a Python SDK, a separately configured MCP server, or a public webpage. Do not scrape Wolfram result pages or images. Do not request a Wolfram API key. The bundled CLI validates plugin evidence but never calls Wolfram itself.

Validate an exact Wolfram financial envelope before it can complete a price history:

```bash
python scripts/advisor_data_cli.py wolfram-validate \
  --input /tmp/AAPL-wolfram.json \
  --start 2021-01-01 \
  --end 2026-08-15
```

If the official Wolfram plugin is not connected or no exact Financial entity, `AdjustedClose`, source annotation, or requested coverage can be confirmed, report `wolfram_plugin_unavailable`, `wolfram_entity_mismatch`, `wolfram_property_unavailable`, `wolfram_source_unavailable`, or the returned data-gate error as applicable. Do not claim that Wolfram ran and do not replace the failed asset.

### Wolfram FX fallback after Yahoo FX failure

Yahoo remains the primary FX provider. For each currency in `fallback_required_fx`, use the official Wolfram plugin to request a dated `FinancialData` pair only after preserving the matching Yahoo `fx_history_unavailable` receipt. Accept `CCY/USD` directly or `USD/CCY` with one disclosed inversion. The structured unit must agree with the pair and the normalized result must always mean USD per one unit of `CCY`. Do not combine Yahoo and Wolfram rows inside one currency series: one provider per FX currency is mandatory.

The probed Wolfram FX time series identifies `Wolfram FinancialData` and the official plugin channel, but its underlying source annotation is unavailable. Preserve that exact limitation as `underlying source annotation is unavailable`; never invent an underlying vendor. Validate before completion:

```bash
python scripts/advisor_data_cli.py wolfram-fx-validate \
  --input /tmp/KRW-wolfram-fx.json \
  --start 2021-01-01 \
  --end 2026-08-15
```

Reject unrelated pairs, conflicting orientation/unit metadata, non-positive or non-finite values, conflicting duplicate timestamps, range mismatch, incomplete coverage, missing official-plugin provenance, or an FX envelope that does not preserve the workspace's Yahoo failure. The CLI validates official-plugin evidence but never calls Wolfram, HTTP, a public webpage, or a Python SDK.

### U.S. Treasury evidence through the official Wolfram plugin

For requested U.S. Treasury levels, histories, curves, or backtest risk-free inputs, have the LLM emit the structured Treasury envelope in [references/data-contract.md](references/data-contract.md). It must state `UnitedStates`, a complete `requested_qualifiers` echo, typed numeric `requested_maturity`, exact requested range, and structured observations or `Missing`. Prefer `provider_confirmed`: a successful exact result independently returns a complete `observed_qualifiers` echo and provider-derived typed numeric `observed_maturity`, plus unit, source annotations, and retrieval time. All qualifier and numeric maturity evidence must agree exactly; never derive maturity years by parsing `10Year` text.

If the exact structured query is unavailable but the official plugin explicitly displays or interprets the requested maturity and returns dated `Percent` observations, a structured LLM semantic binding may emit `provider_labeled_inferred`. It must preserve the exact-query `Missing` receipt, explicit label or input interpretation, observation date/range, typed requested and bound maturity, and an empty conflict list. The deterministic validator does not parse prose. This tier is usable for curves, spreads, historical risk-free conversion, backtests, and scenarios, but every dependent receipt must retain `evidence_confidence: lower`, `exact_qualifier_status: unavailable`, and the lower-confidence dependency warning. An unlabeled number, missing date, maturity conflict, non-Percent unit, scraped webpage, rendered image, or OCR result remains unusable. Run the deterministic validator before either tier is used:

```bash
python scripts/advisor_data_cli.py treasury-validate \
  --input /tmp/us-3-month-treasury.json
```

The validator preserves `Missing`; never substitute a nearby maturity. Keep observed yields and optional interpolated curve calculations separate: an interpolation is a labelled calculation, never an observed Treasury fact. For historical backtest risk-free rates, the default request is the 3-month constant-maturity daily U.S. Treasury proxy. Use a validated exact or explicitly lower-confidence historical series and disclose its tier. If neither tier has adequate maturity/date/unit binding or timely alignment, retain `null` and `risk_free_rate_unavailable` for dependent metrics instead of selecting another rate.

### Web fallback for fundamentals, valuation, and news

If Yahoo fundamentals, valuation fields, or news discovery fail, use web search for discovery. Open the source page before using it. Prefer company IR and official earnings materials, regulatory filings, exchange filings, and audited reports. Use reputable publisher articles or secondary financial sources only when primary evidence is unavailable.

A search-result title or snippet is `discovery_only`; it does not establish a number or event. An opened publisher page may be `publisher_verified`; an opened company, regulator, or exchange source may be `primary_verified`. Preserve URL, retrieval time, period or as-of date, currency, unit, and whether each datum is reported or calculated. Unresolved values remain `null` and stay in `missing_fields`. Never infer news causality from timing or a chart.

## Build portfolio candidates

Run the original Yahoo-only command when Yahoo histories succeed for every symbol:

```bash
python scripts/advisor_data_cli.py portfolio \
  --symbols AAPL 005930.KS 7203.T SAP.DE \
  --start 2021-01-01 \
  --base-currency KRW \
  --frequency weekly \
  --min-observations 104 \
  --max-weight 0.70
```

Require at least two assets, aligned adjusted histories, dynamically resolved currency metadata and FX history, enough common observations, and feasible constraints. Any Yahoo-listed market may be attempted. Add a market to the verified list only after search, recent-price validation, currency resolution, and a return-matrix smoke test succeed. If any gate fails, do not fabricate MPT, correlations, equal-weight fallbacks, or substitute tickers. Historical annualized mean is descriptive, not a forecast.

When one or more Yahoo histories fail, preserve successes per symbol:

```bash
python scripts/advisor_data_cli.py prepare-portfolio \
  --symbols AAPL BTC-USD \
  --start 2021-01-01 \
  --base-currency KRW \
  --workspace /tmp/advisor-evidence.json
```

For every symbol in `fallback_required_symbols`, use structured LLM eligibility judgment. Try Alpaca first only for eligible U.S. equity or crypto symbols; otherwise, or if its plugin/evidence gate fails, use the official Wolfram plugin only when an exact `Financial` entity and the required property can be verified. Save exactly one validated final-provider envelope per failed symbol and complete:

```bash
python scripts/advisor_data_cli.py complete-portfolio \
  --workspace /tmp/advisor-evidence.json \
  --wolfram-input /tmp/AAPL-wolfram.json \
  --wolfram-fx-input /tmp/KRW-wolfram-fx.json \
  --frequency weekly \
  --min-observations 104 \
  --max-weight 0.70
```

The completion command accepts asset inputs through `--alpaca-input` and `--wolfram-input`, and FX inputs separately through repeatable `--wolfram-fx-input`. Exactly one final provider is allowed for each asset and one provider per FX currency. It may mix providers across different assets or currency legs, never within one series. It must receive evidence for every required asset and every unresolved FX leg; it never silently drops a failed asset or currency. If any gate fails, do not fabricate MPT, correlations, equal-weight fallbacks, or substitute tickers.

## Render requested backtests by default

When the user explicitly requests a `backtest` or `백테스트`, the default answer includes both of these adjacent outputs before the narrative interpretation:

1. A ChatGPT built-in interactive cumulative-total-return line chart.
2. A portfolio evaluation table immediately below the chart.

Use the ChatGPT Work Cloud-mode built-in chart capability only. Do not search for, install, recommend, or generate Plotly, TradingView, ECharts, an external chart service, custom HTML, a separate chart application, or a fallback for another product.

The chart follows the visual structure of a portfolio-versus-benchmarks performance chart: a descriptive backtest title, portfolio and benchmark names, exact start and end dates, cumulative total return on the vertical axis, dates on the horizontal axis, a visible legend, and hoverable series. Normalize every displayed series to `0%` at one shared first valid observation. Use only a validated adjusted total-return price series for cumulative-total-return backtests, MPT, and any return calculation; specifically, a Wolfram series must be `AdjustedClose`, never `Price`, `LatestTrade`, `Close`, or `RawClose`. Disclose the actual treatment, base currency, rebalance rule, observation frequency, and sample window. Weekly last observations may be used for display readability, but summary metrics must be calculated from the stated validated return series rather than from pixels or a visually downsampled chart.

Include the tested portfolio and every user-named benchmark. If the user names no benchmark, use LLM semantic judgment over the portfolio's primary market, asset class, and base currency to select and clearly label up to two relevant investable broad-market benchmarks; do not use ticker suffixes, regexes, or a fixed country lookup table. Resolve and validate benchmark symbols through the same evidence gates as portfolio assets. If no benchmark is validated, show the portfolio-only chart and mark benchmark-relative table cells `null` with the reason instead of silently substituting a ticker.

The evaluation table uses one column per displayed portfolio or benchmark and these rows in this order: cumulative return, annualized return, annualized volatility, Sharpe ratio, Sortino ratio, maximum drawdown (MDD), primary-benchmark beta, primary-benchmark correlation, and annualized alpha. Identify the primary benchmark in the table heading or note. State the risk-free-rate value, source, as-of date, and calculation convention used for Sharpe, Sortino, and alpha. Missing inputs stay `null`; do not invent a risk-free rate or a benchmark-relative statistic.

A requested backtest is a historical-performance presentation, not an MPT optimization. It may use a shorter user-requested window such as one year even when that window cannot satisfy the default 104-week MPT gate. In that case, provide the validated backtest chart and evaluation table, but do not produce optimization weights unless the independent MPT gates pass. Do not imply suitability or future returns from the backtest.

## Report in this order

1. Scope, assumptions, unresolved limits.
2. Instrument-resolution table and validation receipts.
3. Verified facts with date, source role, currency, and missing data.
4. When requested, the built-in interactive backtest chart and its immediately following evaluation table.
5. Calculations and methodology.
6. Interpretation, counterevidence, and thesis-breaking conditions.
7. Conditional portfolio candidates, sensitivity, and concentration risks.
8. What additional user constraints or primary sources are still needed.

Do not collapse company quality, current valuation, and portfolio fit into one universal score. Do not imply suitability from a backtest alone. Identify the final provider for each price series and each FX currency, plus every Treasury evidence tier used. Mention that Yahoo Finance/yfinance, Alpaca market data, and official Wolfram plugin evidence are for research and may require licensing review for redistribution or commercial use.
