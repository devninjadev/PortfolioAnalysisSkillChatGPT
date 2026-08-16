# Wolfram FX Fallback and Tiered Treasury Evidence Design

## Status

Approved by the user on 2026-08-17. This design extends the existing official-Wolfram-plugin integration without adding web scraping, direct Wolfram HTTP/API access, or a second ungoverned data path.

## Context

Yahoo remains the primary provider for ticker resolution, adjusted asset prices, currency metadata, and FX histories. The existing mixed-provider workspace can preserve Yahoo asset successes and replace an asset-price failure with one validated Alpaca or Wolfram history. It currently blocks the portfolio when any required Yahoo FX bridge fails.

Official-plugin probes show that Wolfram `FinancialData` can return dated histories for currency pairs such as `KRW/USD` and `EUR/USD`. Those observations have a clear pair orientation and unit, but the probed time series did not expose a separate underlying-vendor source annotation. The integration must therefore identify the official plugin and `Wolfram FinancialData` as the evidence channel while preserving the underlying-source annotation as unavailable rather than inventing one.

Exact structured Wolfram Treasury qualifier queries can return `Missing[NotAvailable]` even when the official plugin displays a labeled current U.S. Treasury curve or interprets a maturity-specific request and returns dated percentage observations. The existing exact validator must remain strict. A second, visibly lower-confidence evidence tier may accept official-plugin labeled or semantically interpreted results when the maturity, date, unit, and value remain explicit.

## Goals

1. Use Wolfram only for a required currency whose Yahoo FX history failed.
2. Preserve Yahoo currency metadata as the authority for each asset's quote currency.
3. Preserve the internal convention of USD value per one unit of currency.
4. Keep every currency history single-provider; never splice Yahoo and Wolfram observations within one FX series.
5. Keep the existing exact Treasury evidence tier unchanged.
6. Add a lower-confidence Treasury tier that is usable in curves, spreads, risk-free conversion, backtests, and scenarios while preserving its limitations in every dependent receipt.
7. Keep all plugin calls in the ChatGPT orchestration layer and all validation deterministic in bundled Python.
8. Keep LLM semantic classification behind structured envelopes and deterministic validation; add no Korean substring parser, maturity regex parser, or guessed source metadata.

## Non-goals

- Do not make Wolfram the primary FX provider.
- Do not call Wolfram directly from Python, scrape Wolfram pages, or parse chart pixels/OCR.
- Do not replace Yahoo asset currency metadata with Wolfram metadata.
- Do not merge two providers into one asset or FX series.
- Do not turn a lower-confidence Treasury result into `provider_confirmed`.
- Do not accept an unlabeled number that lacks an explicit maturity, observation date, or percentage unit.
- Do not substitute a nearby Treasury maturity.
- Do not let an investment-expert persona override provenance, missingness, or evidence-tier gates.
- Do not push, tag, or publish a release in this change.

## Architecture

```text
Yahoo asset prices and currency metadata
            |
            v
Determine required USD-per-currency FX legs
            |
            +-- Yahoo FX success --------> keep Yahoo series
            |
            +-- Yahoo FX failure
                    |
                    v
          official Wolfram plugin
                    |
                    v
          wolfram-fx-validate
                    |
                    v
        one validated Wolfram series

Treasury request
      |
      +-- exact qualifiers and typed provider maturity agree
      |         --> provider_confirmed
      |
      +-- exact query unavailable, but official plugin result explicitly
                binds maturity + date + Percent observations
                --> provider_labeled_inferred (lower confidence)
```

The preparation workspace records successful Yahoo FX legs and failed Yahoo FX legs independently. Completion accepts asset fallback envelopes separately from FX fallback envelopes. An FX envelope is eligible only for a currency listed in the workspace's unresolved required FX failures.

## Wolfram FX Envelope

The new `fx_history` schema-version-1 envelope contains:

- `provider: "wolfram"` and `evidence_kind: "fx_history"`;
- the requested currency whose USD value the portfolio needs;
- `request.start`, `request.end`, and a requested base/quote pair;
- a provider-returned `FinancialData` symbol and explicit base/quote orientation;
- a structured exchange-rate unit naming numerator and denominator currencies;
- dated, positive, finite observations;
- official-plugin provenance and an explicit unavailable underlying-source annotation;
- retrieval time and the original Yahoo FX failure receipt.

Only two orientations are permitted for a non-USD currency `CCY`:

- direct `CCY/USD`: observations already mean USD per one CCY;
- inverse `USD/CCY`: observations mean CCY per one USD and are inverted once.

The normalizer returns a series keyed by `CCY`, always expressed as USD per one CCY. It rejects an unrelated pair, mixed orientation, non-positive/non-finite values, conflicting duplicate timestamps, an empty series, a request-range mismatch, or insufficient endpoint coverage. Identical duplicates may collapse deterministically.

The FX receipt preserves the requested and observed pairs, whether inversion occurred, the exact conversion rule, observation count, requested and observed ranges, coverage status, official-plugin provenance, source-annotation limitation, retrieval time, and the Yahoo failure that triggered fallback.

## Workspace and Portfolio Completion

Preparation must not discard asset evidence merely because an FX bridge failed. It records:

- `fx_prices`: Yahoo-successful currency histories;
- `fx_receipts`: successful Yahoo receipts;
- `fx_failures`: required currencies whose Yahoo bridge failed;
- `fallback_required_fx`: the unresolved required currencies.

Completion receives asset fallbacks through existing inputs and FX fallbacks through a separate repeatable `--wolfram-fx-input`. It rejects:

- an FX input for a currency that Yahoo already satisfied;
- duplicate FX inputs for one currency;
- an input for a currency not required by the workspace;
- a missing input for any unresolved required currency;
- a pair or normalized currency that conflicts with the workspace requirement;
- a provider other than the validated Wolfram FX adapter.

Successful completion records a provider per asset and a provider per FX currency. Yahoo and Wolfram may coexist across different currency legs, but each leg has one provider from end to end. Existing three-calendar-day FX forward-fill and return-matrix gates remain unchanged.

## Treasury Evidence Tiers

### `provider_confirmed`

This is the existing strict path. Requested qualifiers, provider-observed qualifiers, classifier-typed requested maturity, provider-typed observed maturity, numeric maturity years, unit, entity, property, and sources must agree. Exact `Missing` remains a failure.

### `provider_labeled_inferred`

This tier is accepted only from the official plugin when exact qualifier evidence was attempted and preserved as unavailable. The structured envelope must include:

- `evidence_tier: "provider_labeled_inferred"`;
- an exact-qualifier failure receipt with status `unavailable` and the original `Missing` or tool result;
- classifier-typed requested maturity and complete requested qualifiers;
- official-plugin binding evidence with the original query, input interpretation or displayed label, observation channel, and an explicit maturity binding;
- a structured LLM decision that binds the displayed/interpreted maturity to the requested typed maturity and reports no conflicts;
- `Percent` as the unit;
- one dated observation for current evidence or at least two dated observations for history;
- official-plugin source/provenance metadata.

The deterministic validator does not parse the natural-language label. It validates that the structured decision and binding evidence are complete, internally consistent, tied to the requested numeric maturity, and conflict-free. This is an LLM classification harness, not a text-matching parser.

Every normalized lower-tier receipt includes:

- `evidence_tier: "provider_labeled_inferred"`;
- `evidence_confidence: "lower"`;
- `maturity_binding: "provider_labeled_or_semantically_inferred"`;
- `exact_qualifier_status: "unavailable"`;
- the exact-qualifier failure and binding evidence;
- a warning that downstream calculations inherit the lower-confidence rate input.

An unlabeled number, a label without a date, a non-Percent value, a maturity conflict, or a missing exact-query failure receipt is rejected.

## Downstream Treasury Calculations

Yield-curve observations preserve the evidence tier for every maturity. Curve-level receipts summarize all upstream tiers and set overall confidence to `lower` if any point is lower-tier. Interpolated values remain explicitly calculated and inherit the weakest supporting evidence tier.

Historical curve receipts preserve per-maturity tiers. Risk-free alignment preserves the upstream tier, confidence, binding mode, and exact-qualifier status. Any dependent Sharpe, Sortino, alpha, backtest, or scenario output that consumes the rate must disclose that its rate input is lower confidence. The numeric formula does not change merely because the tier is lower.

## CLI and Orchestration

- `wolfram-fx-validate --input ... --start ... --end ...` validates one structured FX history.
- `complete-portfolio --wolfram-fx-input ...` accepts one repeatable envelope per failed currency.
- `treasury-validate` accepts both Treasury tiers and emits the normalized tier/confidence receipt.

ChatGPT calls the official Wolfram context/tool first, structures the returned evidence, and writes the envelope. The CLI never calls Wolfram or the public web. For lower-tier Treasury evidence, the orchestration layer must retain both the failed exact query and the labeled/interpreted result.

## Error Contract

New FX errors are explicit and fail closed: `wolfram_fx_schema_error`, `wolfram_fx_pair_mismatch`, `wolfram_fx_unit_mismatch`, `wolfram_fx_history_unavailable`, `wolfram_fx_history_incomplete`, and `wolfram_fx_source_unavailable`.

Lower-tier Treasury uses existing schema/entity/unit/maturity errors where applicable and adds `treasury_binding_unavailable` for incomplete or conflicting labeled/semantic binding evidence.

## Verification

Implementation follows RED-GREEN-REFACTOR for every behavior. Verification includes focused adapter, workspace, CLI, Treasury, and documentation-contract tests; the full unit suite; skill validation; a clean package inspection; and official-plugin canaries for direct FX, inverse FX, labeled current Treasury curves, and a historical lower-tier Treasury request when the plugin returns dated evidence. Live provider absence is reported separately from deterministic correctness.

After all gates pass, the feature branch is merged into local `main` and the full suite is rerun on `main`. No remote push or release is included.

## 2026-08-17 Canonical Treasury Query Amendment

Later official-plugin verification corrected the earlier operational diagnosis. The `Missing[NotAvailable]` exact probes had used a generic typed-year qualifier shape that Wolfram did not resolve as the canonical Treasury maturity token. User-provided WolframAlpha interpretation URLs exposed canonical `ClashPrefs` values such as `3Month`, `1Year`, `2Year`, `5Year`, `10Year`, and `30Year`, but the URLs themselves remain outside the data path.

The approved plugin-only route now compiles structured LLM intent into a fixed `EntityProperty["Country", "Treasury", ...]` expression using those canonical strings and the semantically classified `Bill`, `Note`, or `Bond` security type. `\[FreeformPrompt]["United States", "Country"]` resolves the country entity, `TimeSeriesWindow` selects the requested range, and the source property is queried separately. No direct HTTP, public-page scraping, URL execution, OCR, or arbitrary Wolfram Language generation is introduced.

Official-plugin canaries returned nine dated Percent observations from 2026-08-03 through 2026-08-13 for all six requested nominal maturities. Exact canonical evaluation plus matching qualifier, typed maturity, unit, date, and source receipts is eligible for `provider_confirmed`. The existing `provider_labeled_inferred` tier remains as a disclosed fallback only when exact canonical evaluation is unavailable but the official plugin still supplies adequate labeled maturity/date/unit evidence.
