# Alpaca and Web-Evidence Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an evidence-preserving Yahoo-first fallback that accepts Alpaca plugin histories for U.S. equities and cryptocurrencies and routes failed Yahoo fundamentals/news work to verified web sources.

**Architecture:** ChatGPT remains the orchestrator because Alpaca is a plugin tool rather than a Python dependency. New pure Python adapters validate exact Alpaca tool envelopes, adjust raw stock histories for corporate actions, and merge them with per-symbol Yahoo evidence stored in a schema-versioned workspace before the existing return-matrix and optimizer run.

**Tech Stack:** Python 3.11+, unittest, pandas, numpy, scipy, yfinance, ChatGPT skills, Alpaca plugin structured results.

## Global Constraints

- Yahoo remains the primary provider for every existing evidence lane.
- Alpaca history fallback is allowed only for the structured classes `us_equity` and `crypto`.
- Korean and all other unsupported markets fail closed when Yahoo history is unavailable.
- FX and ticker candidate discovery have no fallback.
- Fundamentals and news may fall back to web search, but search snippets are discovery-only and source pages must be opened.
- No Alpaca REST client, Alpaca credential, guessed MCP URL, ticker alias parser, suffix parser, or country allowlist may be added.
- If an eligible Alpaca fallback is needed and the plugin is unavailable, recommend connecting it and state that no separate signup is required.
- Missing assets, FX, corporate actions, or source evidence never produce portfolio weights.
- Existing `portfolio` CLI behavior remains backward compatible.
- Every production behavior is introduced by a failing test and verified green before the next behavior.

---

## File Structure

- Create `scripts/advisor_data/alpaca.py`: parse plugin wrappers, validate provider symbols/classes, normalize bars, apply corporate actions, and emit series receipts.
- Create `scripts/advisor_data/evidence_workspace.py`: serialize per-symbol Yahoo evidence, preserve failures, read/write schema-versioned workspace files, merge validated Alpaca evidence.
- Modify `scripts/advisor_data/market_data.py`: expose one reusable FX-bridge downloader while preserving existing download and return-matrix behavior.
- Modify `scripts/advisor_data_cli.py`: add `alpaca-validate`, `prepare-portfolio`, and `complete-portfolio`.
- Create `tests/test_alpaca.py`: adapter and corporate-action behavior.
- Create `tests/test_evidence_workspace.py`: preparation, persistence, mixed-provider merge, unsupported markets, and FX gates.
- Modify `tests/test_cli.py`: end-to-end CLI contracts.
- Modify `SKILL.md`, `agents/openai.yaml`, `references/data-contract.md`, `references/methodology.md`, and `references/market-coverage.md`: user-visible workflow contract.

---

### Task 1: Parse and validate Alpaca plugin envelopes

**Files:**
- Create: `tests/test_alpaca.py`
- Create: `scripts/advisor_data/alpaca.py`

**Interfaces:**
- Produces: `AlpacaHistory(series: pd.Series, currency: str, receipt: dict[str, Any])`.
- Produces: `normalize_alpaca_envelope(envelope: Mapping[str, Any], start: str, end: str | None) -> AlpacaHistory`.
- Consumes: a fallback envelope containing canonical `symbol`, verified `provider_symbol`, `fallback_class`, classification evidence, and exact plugin responses.

- [ ] **Step 1: Write failing tests for valid stock and crypto envelopes**

```python
class AlpacaEnvelopeTests(unittest.TestCase):
    def test_us_equity_requires_exact_active_asset_and_bar_symbol(self) -> None:
        result = normalize_alpaca_envelope(
            stock_envelope(
                bars=[
                    bar("AAPL", "2026-01-05T05:00:00+00:00", 100.0),
                    bar("AAPL", "2026-01-12T05:00:00+00:00", 101.0),
                ],
                actions={"announcements": {}},
            ),
            start="2026-01-01",
            end="2026-01-20",
        )
        self.assertEqual(result.currency, "USD")
        self.assertEqual(result.series.name, "AAPL")
        self.assertEqual(result.receipt["provider"], "alpaca")
        self.assertEqual(result.receipt["provider_symbol"], "AAPL")

    def test_crypto_accepts_verified_provider_symbol_mapping(self) -> None:
        result = normalize_alpaca_envelope(
            crypto_envelope(
                symbol="BTC-USD",
                provider_symbol="BTC/USD",
                bars=[
                    bar("BTC/USD", "2026-01-05T00:00:00+00:00", 90000.0),
                    bar("BTC/USD", "2026-01-12T00:00:00+00:00", 91000.0),
                ],
            ),
            start="2026-01-01",
            end="2026-01-20",
        )
        self.assertEqual(result.series.name, "BTC-USD")
        self.assertEqual(result.receipt["provider_symbol"], "BTC/USD")
        self.assertEqual(result.receipt["fallback_class"], "crypto")
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `python3 -m unittest tests.test_alpaca.AlpacaEnvelopeTests -v`

Expected: FAIL because `advisor_data.alpaca` does not exist.

- [ ] **Step 3: Implement the envelope dataclass and strict wrapper parser**

```python
@dataclass(frozen=True)
class AlpacaHistory:
    series: pd.Series
    currency: str
    receipt: dict[str, Any]


def _decoded(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise DataGateError(
                "alpaca_schema_error",
                "Alpaca returned a non-JSON result wrapper.",
                {"error_type": exc.__class__.__name__},
            ) from exc
    return value
```

Implement `normalize_alpaca_envelope` so `us_equity` requires a decoded active asset with exact `symbol` and `asset_class == "us_equity"`; `crypto` requires exact bar records under the declared `provider_symbol`. Convert timestamps to a UTC `DatetimeIndex`, close values with `pd.to_numeric`, and reject empty, non-finite, non-positive, wrong-symbol, or conflicting duplicate observations with `alpaca_schema_error` or `alpaca_history_unavailable`.

- [ ] **Step 4: Add failing rejection tests**

```python
def test_unsupported_market_fails_before_reading_bars(self) -> None:
    envelope = stock_envelope(bars=[], actions={"announcements": {}})
    envelope["fallback_class"] = "unsupported_market"
    with self.assertRaisesRegex(DataGateError, "fallback_not_supported"):
        normalize_alpaca_envelope(envelope, "2026-01-01", None)

def test_wrong_provider_symbol_is_rejected(self) -> None:
    with self.assertRaisesRegex(DataGateError, "alpaca_schema_error"):
        normalize_alpaca_envelope(
            crypto_envelope(
                symbol="BTC-USD",
                provider_symbol="BTC/USD",
                bars=[bar("ETH/USD", "2026-01-05T00:00:00+00:00", 3000.0)],
            ),
            "2026-01-01",
            None,
        )
```

- [ ] **Step 5: Run the focused test file and verify GREEN**

Run: `python3 -m unittest tests.test_alpaca -v`

Expected: all envelope tests PASS.

- [ ] **Step 6: Commit the adapter boundary**

```bash
git add tests/test_alpaca.py scripts/advisor_data/alpaca.py
git commit -m "Add strict Alpaca evidence adapter"
```

---

### Task 2: Adjust stock histories and verify coverage

**Files:**
- Modify: `tests/test_alpaca.py`
- Modify: `scripts/advisor_data/alpaca.py`

**Interfaces:**
- Produces: `adjust_stock_close(series: pd.Series, announcements: Mapping[str, Any], timeframe: str) -> tuple[pd.Series, list[dict[str, Any]]]`.
- Extends: `normalize_alpaca_envelope` receipts with raw count, normalized count, observed range, price basis, and applied corporate actions.

- [ ] **Step 1: Write the failing AAPL split regression test**

```python
def test_four_for_one_split_removes_false_seventy_five_percent_return(self) -> None:
    envelope = stock_envelope(
        bars=[
            bar("AAPL", "2020-08-24T04:00:00+00:00", 499.345),
            bar("AAPL", "2020-08-31T04:00:00+00:00", 121.11),
        ],
        actions={
            "announcements": {
                "forward_splits": [{
                    "symbol": "AAPL",
                    "old_rate": 1.0,
                    "new_rate": 4.0,
                    "ex_date": "2020-08-31",
                }]
            }
        },
    )
    result = normalize_alpaca_envelope(envelope, "2020-08-01", "2020-09-10")
    split_return = result.series.pct_change().dropna().iloc[0]
    self.assertGreater(split_return, -0.10)
    self.assertEqual(
        result.receipt["corporate_actions_applied"][0]["factor"],
        0.25,
    )
```

- [ ] **Step 2: Run the regression test and verify RED**

Run: `python3 -m unittest tests.test_alpaca.AlpacaEnvelopeTests.test_four_for_one_split_removes_false_seventy_five_percent_return -v`

Expected: FAIL because the raw return is approximately -0.757.

- [ ] **Step 3: Implement backward split adjustment**

Process actions in ascending ex-date order. For a forward split, multiply observations strictly before the ex-date bar by `old_rate / new_rate`; for a reverse split, use the same declared old/new ratio. Validate positive finite rates and the exact provider symbol. Record `type`, `ex_date`, `factor`, and `status: "applied"`.

- [ ] **Step 4: Write the failing cash-dividend test**

```python
def test_cash_dividend_adjusts_prior_bar_with_declared_factor(self) -> None:
    envelope = stock_envelope(
        bars=[
            bar("AAPL", "2026-01-05T05:00:00+00:00", 100.0),
            bar("AAPL", "2026-01-12T05:00:00+00:00", 100.0),
        ],
        actions={
            "announcements": {
                "cash_dividends": [{
                    "symbol": "AAPL",
                    "rate": 1.0,
                    "ex_date": "2026-01-12",
                }]
            }
        },
    )
    result = normalize_alpaca_envelope(envelope, "2026-01-01", "2026-01-20")
    self.assertAlmostEqual(result.series.iloc[0], 99.0)
    self.assertAlmostEqual(result.series.iloc[1], 100.0)
```

- [ ] **Step 5: Implement cash-distribution adjustment and failure gates**

For each cash dividend, find the last full pre-ex-date bar; for `1Week`, exclude the bar whose Monday-started week contains the ex-date. Compute `factor = (pre_close - rate) / pre_close`, require `0 < factor <= 1`, and multiply earlier prices. Raise `corporate_action_adjustment_failed` when no reference bar exists or a factor is invalid. Require a decodable corporate-action response for every U.S. stock fallback; absence raises `corporate_actions_unavailable`.

- [ ] **Step 6: Add coverage and duplicate tests**

Test that identical duplicate bars collapse to one observation, conflicting duplicates fail, a history with first observation after the requested start records `coverage_status: "clipped"`, and fewer than two observations raises `alpaca_history_incomplete`.

- [ ] **Step 7: Run adapter tests and commit**

Run: `python3 -m unittest tests.test_alpaca -v`

Expected: all tests PASS.

```bash
git add tests/test_alpaca.py scripts/advisor_data/alpaca.py
git commit -m "Adjust Alpaca histories for corporate actions"
```

---

### Task 3: Prepare and merge the evidence workspace

**Files:**
- Create: `tests/test_evidence_workspace.py`
- Create: `scripts/advisor_data/evidence_workspace.py`
- Modify: `scripts/advisor_data/market_data.py`

**Interfaces:**
- Produces: `prepare_yahoo_workspace(symbols: list[str], start: str, end: str | None, base_currency: str, market_loader: Callable[..., MarketBundle], base_fx_loader: Callable[..., tuple[pd.Series, dict[str, str]]]) -> dict[str, Any]`.
- Produces: `write_workspace(path: Path, workspace: Mapping[str, Any]) -> None`.
- Produces: `read_workspace(path: Path) -> dict[str, Any]`.
- Produces: `complete_market_bundle(workspace: Mapping[str, Any], envelopes: Sequence[Mapping[str, Any]]) -> MarketBundle`.
- Produces: `download_currency_bridge(currency: str, start: str, end: str | None, downloader: Any = yf.download) -> tuple[pd.Series, dict[str, str]]`.

- [ ] **Step 1: Write a failing per-symbol preparation test**

```python
def test_prepare_preserves_yahoo_success_and_records_failure(self) -> None:
    def loader(*, symbols, **kwargs):
        if symbols == ["AAPL"]:
            return yahoo_bundle("AAPL", [100.0, 101.0], currency="USD")
        raise DataGateError(
            "price_history_unavailable",
            "Yahoo returned no usable price history for 005930.KS.",
        )

    workspace = prepare_yahoo_workspace(
        ["AAPL", "005930.KS"],
        "2026-01-01",
        None,
        "USD",
        market_loader=loader,
    )
    self.assertIn("AAPL", workspace["assets"])
    self.assertEqual(
        workspace["failures"]["005930.KS"]["code"],
        "price_history_unavailable",
    )
```

- [ ] **Step 2: Run the workspace test and verify RED**

Run: `python3 -m unittest tests.test_evidence_workspace -v`

Expected: FAIL because `advisor_data.evidence_workspace` does not exist.

- [ ] **Step 3: Implement schema-versioned pandas serialization**

Serialize every series as:

```json
{
  "name": "AAPL",
  "observations": [
    {"timestamp": "2026-01-02T00:00:00+00:00", "value": 100.0}
  ]
}
```

Reject NaN, infinity, duplicate timestamps, non-object roots, or schema versions other than `1`. Write with `json.dump(workspace, handle, ensure_ascii=False, indent=2, allow_nan=False)` and an atomic same-directory temporary file followed by `Path.replace`.

- [ ] **Step 4: Implement per-symbol preparation and independent FX bridge**

Call `market_loader(symbols=[symbol], start=start, end=end, base_currency=base_currency)` once per canonical symbol. Store successful prices, currency, FX series, and receipt. Convert `DataGateError` to a preserved `code/message/details` failure. Promote a public `download_currency_bridge` wrapper around the existing direct-then-inverse Yahoo FX logic so the requested non-USD base can be attempted even when every asset history failed.

- [ ] **Step 5: Write failing mixed-provider and unsupported-market tests**

```python
def test_complete_merges_yahoo_and_alpaca_without_dropping_symbols(self) -> None:
    bundle = complete_market_bundle(
        workspace_with_yahoo_aapl_and_failed_btc(),
        [crypto_envelope(symbol="BTC-USD", provider_symbol="BTC/USD", bars=BTC_BARS)],
    )
    self.assertEqual(list(bundle.prices.columns), ["AAPL", "BTC-USD"])
    self.assertEqual(bundle.receipt["providers"], {
        "AAPL": "yahoo",
        "BTC-USD": "alpaca",
    })

def test_unsupported_korean_failure_never_accepts_alpaca(self) -> None:
    envelope = stock_envelope(symbol="005930.KS", bars=[])
    envelope["fallback_class"] = "unsupported_market"
    with self.assertRaisesRegex(DataGateError, "fallback_not_supported"):
        complete_market_bundle(workspace_with_failed_korean_asset(), [envelope])
```

- [ ] **Step 6: Implement merge and completeness gates**

Match envelopes by canonical `symbol`; reject extras and duplicates. Require one eligible envelope for every failed asset. Merge on outer dates without filling asset prices. Preserve primary Yahoo failures in the final receipt. Determine required FX currencies from all resolved asset currencies and the base; if a required bridge is absent, raise `fx_history_unavailable` before returning a bundle.

- [ ] **Step 7: Run focused tests and commit**

Run: `python3 -m unittest tests.test_market_data tests.test_evidence_workspace -v`

Expected: all tests PASS.

```bash
git add tests/test_evidence_workspace.py scripts/advisor_data/evidence_workspace.py scripts/advisor_data/market_data.py
git commit -m "Add mixed-provider evidence workspace"
```

---

### Task 4: Expose deterministic CLI bridge commands

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `scripts/advisor_data_cli.py`

**Interfaces:**
- Adds: `alpaca-validate --input PATH --start DATE [--end DATE]`.
- Adds: `prepare-portfolio --symbols AAPL MSFT --start DATE [--end DATE] --base-currency ISO --workspace PATH`.
- Adds: repeatable `complete-portfolio --workspace PATH --alpaca-input PATH --alpaca-input PATH --frequency {weekly,daily} --min-observations N --max-weight W`.
- Extends: `main(argv=None, gateway=None, market_loader=None, workspace_preparer=None, workspace_completer=None, alpaca_normalizer=None)` for test injection without mocking internal implementation.

- [ ] **Step 1: Write failing parser and validation-command tests**

```python
def test_alpaca_validate_emits_normalized_receipt(self) -> None:
    input_path = self.write_json(crypto_envelope(
        symbol="BTC-USD",
        provider_symbol="BTC/USD",
        bars=[
            bar("BTC/USD", "2026-01-05T00:00:00+00:00", 90000.0),
            bar("BTC/USD", "2026-01-12T00:00:00+00:00", 91000.0),
        ],
    ))
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        code = main([
            "alpaca-validate", "--input", str(input_path),
            "--start", "2026-01-01", "--end", "2026-02-01",
        ])
    payload = json.loads(stdout.getvalue())
    self.assertEqual(code, 0)
    self.assertEqual(payload["validation"]["provider"], "alpaca")
```

- [ ] **Step 2: Run the new CLI test and verify RED**

Run: `python3 -m unittest tests.test_cli.CliTests.test_alpaca_validate_emits_normalized_receipt -v`

Expected: parser exits because `alpaca-validate` is not a recognized command.

- [ ] **Step 3: Add CLI arguments and `alpaca-validate`**

Load the exact JSON envelope, call `normalize_alpaca_envelope`, and emit its receipt plus first/last normalized observations. Use existing `DataGateError` handling and exit code 2.

- [ ] **Step 4: Write failing prepare/complete CLI tests**

Test that prepare writes a workspace and emits only its compact summary. Test that complete reads two Alpaca input paths, calls the existing `build_return_matrix` and `build_portfolio_candidates`, and emits `download_receipt`, `return_receipt`, and `portfolio_candidates`. Test that one missing required fallback input returns exit code 2 and no weights.

- [ ] **Step 5: Implement prepare/complete commands**

Keep the existing `portfolio` branch unchanged. Validate at least two symbols during prepare and complete. Let injected preparer/completer functions support unit tests; production defaults import from `evidence_workspace`.

- [ ] **Step 6: Run CLI and regression tests**

Run: `python3 -m unittest tests.test_cli tests.test_portfolio -v`

Expected: all tests PASS, including the original Yahoo-only portfolio test.

- [ ] **Step 7: Commit the bridge**

```bash
git add tests/test_cli.py scripts/advisor_data_cli.py
git commit -m "Expose Alpaca fallback CLI workflow"
```

---

### Task 5: Update the skill workflow and web-evidence contract

**Files:**
- Modify: `SKILL.md`
- Modify: `agents/openai.yaml`
- Modify: `references/data-contract.md`
- Modify: `references/methodology.md`
- Modify: `references/market-coverage.md`

**Interfaces:**
- Produces: explicit model instructions for Alpaca tool calls and exact fallback envelopes.
- Produces: source roles `discovery_only`, `publisher_verified`, and `primary_verified`.
- Produces: a clear missing-plugin stop condition without an invented tool response.

- [ ] **Step 1: Record the baseline workflow failure**

Run the existing Yahoo-only skill instructions against these written scenarios and record the unsupported outcome before editing:

- Yahoo stock history fails for a resolved AAPL candidate.
- Yahoo crypto history fails for a resolved BTC-USD candidate.
- Yahoo history fails for a resolved 005930.KS candidate.
- Yahoo fundamentals and news fail after runtime bootstrap.

Expected baseline: the current skill stops every affected lane because it has no Alpaca or verified web-search fallback workflow. This is the process-documentation RED condition; do not add source-text assertions to the unit suite.

- [ ] **Step 2: Update `SKILL.md` with exact orchestration**

Add the ordered workflow:

1. Run Yahoo.
2. Inspect the structured failure code.
3. Use LLM semantic classification.
4. For `us_equity`, call exact Alpaca asset, stock bars, and corporate actions; for `crypto`, call crypto bars.
5. Save the structured envelope and run the validation or prepare/complete CLI.
6. If Alpaca is unavailable, unsupported, ambiguous, or incomplete, stop the affected analysis.
7. For fundamentals/news failure, search and open source documents; never rely on snippets.

For an unavailable Alpaca tool, use this Korean user-facing meaning without claiming that a call occurred: `미국 주식·크립토 가격의 대안 출처로 Alpaca 플러그인을 사용할 수 있습니다. 별도 회원가입은 필요 없고, 플러그인을 연결하기만 하면 됩니다.` Emit `alpaca_plugin_unavailable` in the structured limitation receipt.

- [ ] **Step 3: Update references and metadata**

Document payload schemas, adjustment basis, errors, receipt fields, web source hierarchy, and the dated AAPL/BTC/005930.KS live evidence. In `agents/openai.yaml`, mention Alpaca as an optional installed fallback capability in user-facing metadata only if the schema supports it. Do not add a fabricated `dependencies.tools` URL.

- [ ] **Step 4: Exercise the documented scenarios against executable gates**

Run the new `alpaca-validate` CLI with valid AAPL and BTC/USD fixture envelopes and an unsupported 005930.KS envelope. Confirm the first two return provider receipts and the Korean envelope returns `fallback_not_supported`. Run a malformed or missing Alpaca input and confirm no price claim or weights are emitted.

Review the web-fallback instructions against the Yahoo fundamentals/news failure scenarios and confirm the required output shape includes source URL, retrieval time, source role, period/as-of date where applicable, and unresolved `null` fields. Because prose instructions are not executable production code, validate their structure with the available OpenAI skill validator rather than a source-text unit test.

Review the missing-plugin scenario separately: the recommendation appears for an eligible U.S. equity or crypto fallback, does not appear for a Korean or ambiguous asset, says no separate signup is required, and does not claim that Alpaca data was retrieved.

Run: `python3 -m unittest discover -s tests -v`

Expected: zero failures and zero errors.

- [ ] **Step 5: Commit the skill contract**

```bash
git add SKILL.md agents/openai.yaml references
git commit -m "Document Alpaca and web evidence fallbacks"
```

---

### Task 6: Validate packaging and live provider boundaries

**Files:**
- Modify only if validation reveals a defect in files already listed above.
- Create local artifact outside Git tracking: `dist/evidence-first-portfolio-advisor-alpaca-fallback.zip`.

**Interfaces:**
- Consumes: the complete repository tree and live Alpaca plugin.
- Produces: test, ZIP-root, metadata, and live-canary receipts.

- [ ] **Step 1: Run the full suite fresh**

Run: `python3 -m unittest discover -s tests -v`

Expected: every discovered test passes.

- [ ] **Step 2: Locate and run the available skill validator**

Search the local Codex skill tooling for a validator that accepts a skill root. Run it against the repository root. If no validator exists, record that boundary and perform the structural checks in Step 3.

- [ ] **Step 3: Build and inspect the release-ready ZIP**

```bash
python3 - <<'PY'
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

output = Path("dist/evidence-first-portfolio-advisor-alpaca-fallback.zip")
output.parent.mkdir(exist_ok=True)
roots = [
    Path("SKILL.md"), Path("agents"), Path("assets"),
    Path("references"), Path("requirements.txt"), Path("scripts"),
    Path("tests"),
]
files = []
for root in roots:
    files.extend([root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()])
with ZipFile(output, "w", ZIP_DEFLATED) as archive:
    for path in sorted(files):
        archive.write(path, path.as_posix())
PY
unzip -l dist/evidence-first-portfolio-advisor-alpaca-fallback.zip
```

Verify `SKILL.md` is at ZIP root and no `.advisor-runtime`, `__pycache__`, `.DS_Store`, test cache, or temporary evidence file is included.

- [ ] **Step 4: Run live Alpaca canaries**

Call the installed Alpaca plugin for:

- AAPL weekly stock bars.
- AAPL corporate actions covering the 2020 split.
- BTC/USD weekly crypto bars.
- 005930.KS exact asset lookup.

Save the compact request/record-count/provider-class/error receipts. Confirm U.S. stock and crypto succeed and the Korean asset remains unsupported. Do not treat live canaries as deterministic unit-test evidence.

- [ ] **Step 5: Review the final diff and repository state**

Run:

```bash
git diff --check origin/main...HEAD
git status --short --branch
git log --oneline --decorate origin/main..HEAD
```

Expected: no whitespace errors; only planned source, tests, docs, and local ignored artifact changes; no runtime caches.

- [ ] **Step 6: Commit any validation-only correction and report**

If Steps 1-5 required a planned-file correction, rerun the affected focused test and the full suite, then commit only that correction. Do not publish, tag, or push a release without separate release authorization.
