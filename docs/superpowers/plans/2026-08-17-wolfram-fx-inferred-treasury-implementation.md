# Wolfram FX Fallback and Tiered Treasury Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Every behavior follows `superpowers:test-driven-development`.

**Goal:** Let failed Yahoo FX legs fall back to validated official-plugin Wolfram histories and let explicitly labeled/interpreted official-plugin Treasury evidence enter calculations at a permanently visible lower-confidence tier.

**Architecture:** A new pure-Python Wolfram FX normalizer converts only `CCY/USD` or `USD/CCY` evidence into the workspace's USD-per-currency convention. The evidence workspace tracks Yahoo FX success and failure per currency and accepts a separate FX envelope stream at completion. The existing Treasury normalizer gains a second branch for official-plugin labeled/semantic binding evidence, and every downstream calculation propagates the weakest upstream evidence tier.

**Tech Stack:** Python 3.11+, `unittest`, pandas, numpy, yfinance, JSON CLI envelopes, ChatGPT official Wolfram plugin orchestration.

## Global Constraints

- Work in the canonical checkout and preserve untracked `.DS_Store`.
- Yahoo remains primary for instrument resolution, asset prices, asset currency metadata, and FX.
- Use Wolfram FX only for a currency with a preserved Yahoo `fx_history` failure.
- One provider owns one complete asset or FX series; never splice provider rows.
- Keep asset `--wolfram-input` and FX `--wolfram-fx-input` separate.
- The CLI never calls Wolfram, a public webpage, or a direct API.
- Do not invent an underlying FX vendor when Wolfram exposes none.
- Keep the strict Treasury path unchanged and independently tested.
- Lower-tier Treasury evidence requires explicit official-plugin maturity/date/unit binding and the preserved exact-query failure.
- Do not parse Treasury labels with string matching or regular expressions; validate a structured LLM classification decision.
- Propagate lower confidence to every curve, interpolation, historical alignment, and risk-free receipt that depends on it.
- Every production change begins with a focused failing test whose failure demonstrates the missing behavior.
- Run the full suite after each coherent task and before integration.
- Do not push, tag, publish, or release. Merge locally into `main` only after all gates pass.

## Task 1: Add the Wolfram FX envelope normalizer

**Files:**

- Create: `tests/test_wolfram_fx.py`
- Create: `scripts/advisor_data/wolfram_fx.py`

**Public interface:**

```python
@dataclass(frozen=True)
class WolframFxHistory:
    series: pd.Series
    currency: str
    receipt: dict[str, Any]

def normalize_wolfram_fx_envelope(
    envelope: Mapping[str, Any],
    start: str,
    end: str | None,
) -> WolframFxHistory:
    ...
```

- [ ] Write valid direct `KRW/USD` and inverse `USD/KRW` tests. Assert both normalize to USD per KRW and the inverse receipt discloses inversion.
- [ ] Run `python3 -m unittest tests.test_wolfram_fx -v` and confirm RED because the module is absent.
- [ ] Implement the minimum schema, pair, structured-unit, observation, request-range, endpoint-coverage, provenance, and primary-Yahoo-failure gates.
- [ ] Add RED tests for unrelated pairs, conflicting pair metadata, non-positive/non-finite values, conflicting duplicate dates, missing official-plugin provenance, fabricated non-null underlying-source annotations, empty history, request mismatch, and clipped endpoints.
- [ ] Implement only enough to turn each case green. Identical duplicate timestamps may collapse; conflicting duplicates fail.
- [ ] Run the focused module, `git diff --check`, and commit.

## Task 2: Preserve Yahoo FX failures as fallback requirements

**Files:**

- Modify: `tests/test_evidence_workspace.py`
- Modify: `scripts/advisor_data/evidence_workspace.py`

**Workspace additions:**

```json
{
  "fx_failures": {"KRW": {"code": "fx_history_unavailable", "details": {"stage": "fx_history"}}},
  "fallback_required_fx": ["KRW"]
}
```

- [ ] Add a RED test where asset prices and currency metadata succeed, one Yahoo FX bridge fails, and preparation still returns a usable workspace with that currency in `fallback_required_fx`.
- [ ] Add a RED test proving Yahoo-successful FX legs remain in `fx_prices` and are absent from `fallback_required_fx`.
- [ ] Make preparation independently collect required FX legs and preserve failures instead of aborting the workspace. Keep non-FX and currency-metadata failures blocking.
- [ ] Add workspace read/summary schema tests for the new field while retaining compatibility with schema-version-1 workspaces that derive it from `fx_failures`.
- [ ] Run the focused workspace tests and commit.

## Task 3: Complete a portfolio with one Wolfram FX envelope per failed currency

**Files:**

- Modify: `tests/test_evidence_workspace.py`
- Modify: `scripts/advisor_data/evidence_workspace.py`

**Interface change:**

```python
def complete_market_bundle(
    workspace: Mapping[str, Any],
    envelopes: Sequence[Mapping[str, Any]],
    fx_envelopes: Sequence[Mapping[str, Any]] = (),
    normalizers: Mapping[str, Callable[..., Any]] | None = None,
    fx_normalizer: Callable[..., Any] | None = None,
) -> MarketBundle:
    ...
```

- [ ] Add a RED test completing an otherwise valid mixed-currency portfolio after a KRW Yahoo FX failure with a validated Wolfram direct pair.
- [ ] Add RED tests for inverse-pair success, duplicate FX inputs, unrequested inputs, input for a Yahoo-successful currency, missing required input, currency mismatch, and unknown provider.
- [ ] Index FX envelopes by requested currency, validate only unresolved requirements, and merge a whole normalized series per currency.
- [ ] Record `fx_providers` and per-currency receipts, including the original Yahoo failure, in `MarketBundle.receipt`.
- [ ] Prove no row-level Yahoo/Wolfram combination occurs for a single currency.
- [ ] Run focused workspace and return-matrix tests and commit.

## Task 4: Expose separate FX validation and completion CLI inputs

**Files:**

- Modify: `tests/test_cli.py`
- Modify: `scripts/advisor_data_cli.py`

- [ ] Add RED parser/command tests for `wolfram-fx-validate --input --start --end` and repeatable `complete-portfolio --wolfram-fx-input`.
- [ ] Add injectable `wolfram_fx_normalizer` support to `main` for deterministic tests.
- [ ] Emit normalized currency, requested/observed pair, inversion, date range, observation count, and provenance in validation output.
- [ ] Pass FX envelopes separately to `complete_market_bundle`; never mix them with asset envelopes.
- [ ] Add an end-to-end CLI fixture where Yahoo FX failed and Wolfram FX completes portfolio calculation.
- [ ] Run focused CLI tests and commit.

## Task 5: Add lower-confidence Treasury binding evidence

**Files:**

- Modify: `tests/test_treasury.py`
- Modify: `scripts/advisor_data/treasury.py`
- Modify: `tests/test_cli.py`

**Envelope branch:**

```json
{
  "evidence_tier": "provider_labeled_inferred",
  "exact_qualifier_failure": {
    "status": "unavailable",
    "missing": ["Missing[NotAvailable]"]
  },
  "binding_evidence": {
    "channel": "official_plugin_labeled_result",
    "query": "current U.S. Treasury yield curve",
    "input_interpretation": "U.S. Treasury 10-year note yield",
    "displayed_label": "10-year note",
    "observation_date": "2026-08-13"
  },
  "binding_decision": {
    "requested_maturity_years": 10.0,
    "bound_maturity_years": 10.0,
    "maturity_match": true,
    "conflicts": []
  }
}
```

- [ ] Add a RED current-result test and a RED historical-result test that omit provider-observed exact qualifier echoes but contain complete official-plugin binding evidence.
- [ ] Assert normalized receipts contain `evidence_confidence=lower`, `maturity_binding=provider_labeled_or_semantically_inferred`, and `exact_qualifier_status=unavailable`.
- [ ] Add RED rejection tests for missing exact failure, missing displayed/interpreted maturity, missing observation date, non-Percent unit, maturity mismatch, conflicts, unsupported channel, and an unlabeled numeric result.
- [ ] Refactor the normalizer into explicit strict and inferred branches sharing only observation, unit, request-range, entity, source, and numeric gates.
- [ ] Make the strict branch emit `evidence_tier=provider_confirmed` and `evidence_confidence=high` without weakening any existing exact checks.
- [ ] Extend `treasury-validate` tests to prove both tiers are visible.
- [ ] Run Treasury and CLI tests and commit.

## Task 6: Propagate Treasury confidence through calculations

**Files:**

- Modify: `tests/test_treasury.py`
- Modify: `scripts/advisor_data/treasury.py`

- [ ] Add RED tests for mixed-tier current curves, lower-tier historical curves, lower-tier risk-free alignment, and interpolation supported by at least one lower-tier point.
- [ ] Add per-point tier/confidence to observed curve values and the weakest-upstream tier/confidence to curve receipts.
- [ ] Preserve per-maturity tier metadata in historical curve receipts.
- [ ] Add lower-confidence provenance and a dependency warning to risk-free receipts and every aligned-row receipt or upstream block needed by downstream metrics.
- [ ] Keep the annual-percent-to-periodic formula and maximum three-day no-look-ahead alignment unchanged.
- [ ] Run the Treasury suite and commit.

## Task 7: Synchronize product contracts and examples

**Files:**

- Modify: `tests/test_skill_contract.py`
- Modify: `SKILL.md`
- Modify: `references/data-contract.md`
- Modify: `references/methodology.md`
- Modify: `references/market-coverage.md`
- Modify: `agents/openai.yaml`

- [ ] Add RED contract tests requiring Yahoo-primary/Wolfram-FX-fallback wording, single-provider-per-FX behavior, separate CLI flags, lower-confidence Treasury usage, no scraping/direct API, and downstream confidence disclosure.
- [ ] Document official-plugin orchestration and the missing underlying FX source annotation honestly.
- [ ] Replace statements that all Yahoo FX histories are mandatory with the new validated-fallback rule.
- [ ] Document both Treasury tiers, the semantic binding harness, the minimum maturity/date/unit floor, and the persona boundary.
- [ ] Record dated FX and Treasury canaries as validation history, not an allowlist or availability promise.
- [ ] Run contract tests and commit.

## Task 8: Final deterministic and live verification

**Files:**

- Modify only if a real verification defect requires a new RED test and implementation fix.

- [ ] Run `python3 -m unittest discover -s tests -v` from a fresh process.
- [ ] Run `git diff --check` and verify `.DS_Store` remains untracked and untouched.
- [ ] Run the available skill validator against `SKILL.md` and package structure.
- [ ] Build a temporary release-shaped ZIP; verify `SKILL.md` is at root and caches, `.git`, `.DS_Store`, runtime data, and temporary evidence are absent; then delete the temporary ZIP.
- [ ] Through the official Wolfram plugin, run direct `KRW/USD` and `EUR/USD` history canaries and validate their envelopes with `wolfram-fx-validate`.
- [ ] Validate an inverse-pair fixture/canary so the conversion receipt proves one inversion.
- [ ] Validate the official labeled current Treasury curve at the lower tier, retaining the exact-qualifier failure.
- [ ] Attempt a maturity-specific historical lower-tier canary; if the plugin returns no dated evidence, record live unavailability without weakening deterministic tests.
- [ ] Inspect final branch diff and recent commits.

## Task 9: Integrate into local main and reverify

- [ ] Confirm the feature branch is green and the only unrelated worktree item is the preserved `.DS_Store`.
- [ ] Update local `main` from `origin/main` with a non-destructive fast-forward if needed.
- [ ] Merge `codex/wolfram-fallback-treasury` into local `main` without pushing.
- [ ] Rerun the full unit suite, `git diff --check`, skill validation, and status checks on `main`.
- [ ] Report the local main commit, test count, live canary results, known lower-confidence limitations, and the explicit fact that nothing was pushed or released.

## Amendment: exact canonical-string Treasury route

- [x] Add RED documentation-contract tests for the official-plugin `\[FreeformPrompt]` plus fixed `EntityProperty`/`TimeSeriesWindow` route.
- [x] Preserve the 2026-08-16 `Missing[NotAvailable]` run as a historical query-shape receipt rather than a present availability claim.
- [x] Verify `3Month` Bill, `1Year` Bill, `2Year` Note, `5Year` Note, `10Year` Note, and `30Year` Bond histories through the official plugin.
- [x] Document `FREDII` source annotation and the six 2026-08-13 curve points.
- [x] Keep `provider_labeled_inferred` available only when exact canonical evaluation still fails.
- [ ] Validate strict live envelopes, rerun all deterministic/package gates, and merge the finished branch into local `main`.
