---
name: evidence-first-portfolio-advisor
description: Use when analyzing listed equities or ETFs across global markets, resolving a security name to a Yahoo ticker, verifying price or news history, reviewing valuation and fundamentals, or constructing evidence-backed multi-asset portfolio candidates.
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
3. Fetch the required data before making factual claims. If retrieval fails or fields are missing, state the gap and stop only the affected analysis.
4. Separate `fact`, `calculation`, `interpretation`, and `scenario` in the answer. Preserve the retrieval date, market/currency basis, observation window, and missing fields.
5. Treat all portfolio weights as research candidates, never orders. Do not prescribe allocation or timing unless the user supplied horizon, risk/loss tolerance, liquidity needs, existing holdings, and major constraints.

Read [references/methodology.md](references/methodology.md) before giving counseling. Read [references/data-contract.md](references/data-contract.md) before running scripts or interpreting an error. Consult [references/market-coverage.md](references/market-coverage.md) for live-verified examples; treat it as evidence, not an allowlist.

## Bootstrap runtime dependencies

Run the bundled CLI directly. It first imports `yfinance`, `pandas`, `numpy`, and `scipy`; when any are missing, it must install `requirements.txt` with the active Python interpreter into an isolated runtime directory, add that directory to the import path, and recheck every dependency before continuing. A missing import is an installation trigger, not an analysis error.

Do not report `cloud_runtime_unavailable` or replace the requested calculation merely because the first import failed. Stop only if the automatic installation command fails, no writable isolated directory exists, or the installed modules still cannot be imported. Treat Yahoo HTTP errors, rate limits, empty histories, and schema failures as data-source errors after dependency bootstrap, not as dependency failures. The CLI returns a `runtime_receipt` on successful commands.

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

## Build portfolio candidates

Run only after every symbol is resolved and validated:

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

## Report in this order

1. Scope, assumptions, unresolved limits.
2. Instrument-resolution table and validation receipts.
3. Verified facts with date, source role, currency, and missing data.
4. Calculations and methodology.
5. Interpretation, counterevidence, and thesis-breaking conditions.
6. Conditional portfolio candidates, sensitivity, and concentration risks.
7. What additional user constraints or primary sources are still needed.

Do not collapse company quality, current valuation, and portfolio fit into one universal score. Do not imply suitability from a backtest alone. Mention that Yahoo Finance/yfinance data is for research and may require licensing review for redistribution or commercial use.
