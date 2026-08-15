---
name: evidence-first-portfolio-advisor
description: Use when analyzing listed equities, ETFs, or cryptoassets; resolving a security name to a Yahoo ticker; verifying prices, fundamentals, valuation, or news; or constructing evidence-backed multi-asset portfolio candidates.
---

# Evidence-First Portfolio Advisor

Give conditional investment counseling from retrieved evidence. Never turn missing data into a confident opinion, weight, price claim, or trade instruction.

## Follow the evidence gates

1. Classify the request semantically with an LLM into:
   - instruments mentioned by the user;
   - requested analyses: price, fundamentals, news, portfolio;
   - decision constraints actually supplied by the user;
   - unresolved ambiguities.
2. Resolve every name to a Yahoo candidate set. Do not invent ticker suffixes or select a symbol absent from the returned set. Validate the selected candidate with price history. Ask the user only when two or more plausible candidates remain.
3. Fetch the required data before making factual claims. Use Yahoo first. If Yahoo fails, follow only the explicit Alpaca-history or opened-web-source fallback below. If fields remain missing, state the gap and stop only the affected analysis.
4. Separate `fact`, `calculation`, `interpretation`, and `scenario` in the answer. Preserve the retrieval date, market/currency basis, observation window, and missing fields.
5. Treat all portfolio weights as research candidates, never orders. Do not prescribe allocation or timing unless the user supplied horizon, risk/loss tolerance, liquidity needs, existing holdings, and major constraints.

Read [references/methodology.md](references/methodology.md) before giving counseling. Read [references/data-contract.md](references/data-contract.md) before running scripts or interpreting an error. Consult [references/market-coverage.md](references/market-coverage.md) for live-verified examples; treat it as evidence, not an allowlist.

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

Yahoo remains the primary provider. Do not call Alpaca or web search merely to duplicate a successful Yahoo result.

### Alpaca fallback for historical prices

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
- Alpaca does not replace Yahoo currency metadata or FX. Missing required FX still blocks cross-currency results.

For a single recent-price validation, save the envelope and run:

```bash
python scripts/advisor_data_cli.py alpaca-validate \
  --input /tmp/AAPL-alpaca.json \
  --start 2026-07-01 \
  --end 2026-08-15
```

If an eligible fallback is needed but the Alpaca tools are not installed or callable, report `alpaca_plugin_unavailable`, do not claim that a fallback ran, and show this recommendation:

> 미국 주식·크립토 가격의 대안 출처로 Alpaca 플러그인을 사용할 수 있습니다. 별도 회원가입은 필요 없고, 플러그인을 연결하기만 하면 됩니다.

Do not show that recommendation for Korean equities, unsupported markets, ambiguous instruments, successful Yahoo retrievals, or unrelated analyses.

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

Call Alpaca only for eligible symbols listed in `fallback_required_symbols`, save one validated envelope per symbol, and complete:

```bash
python scripts/advisor_data_cli.py complete-portfolio \
  --workspace /tmp/advisor-evidence.json \
  --alpaca-input /tmp/BTC-USD-alpaca.json \
  --frequency weekly \
  --min-observations 104 \
  --max-weight 0.70
```

The completion command must receive evidence for every required asset and every Yahoo FX leg. It may mix Yahoo and Alpaca asset histories, but it never silently drops a failed asset. If any gate fails, do not fabricate MPT, correlations, equal-weight fallbacks, or substitute tickers.

## Report in this order

1. Scope, assumptions, unresolved limits.
2. Instrument-resolution table and validation receipts.
3. Verified facts with date, source role, currency, and missing data.
4. Calculations and methodology.
5. Interpretation, counterevidence, and thesis-breaking conditions.
6. Conditional portfolio candidates, sensitivity, and concentration risks.
7. What additional user constraints or primary sources are still needed.

Do not collapse company quality, current valuation, and portfolio fit into one universal score. Do not imply suitability from a backtest alone. Identify the provider for each price series. Mention that Yahoo Finance/yfinance and Alpaca market data are for research and may require licensing review for redistribution or commercial use.
