# 데이터 계약과 클라우드 실행 조건

## 런타임 요구사항

- Python 3.11 이상.
- `requirements.txt`의 `yfinance`, `pandas`, `numpy`, `scipy`.
- Yahoo Finance 및 검증할 뉴스·공시 원문 도메인으로의 HTTPS 접근.
- 미국 주식·크립토 가격 폴백을 실제로 쓸 때는 연결된 Alpaca 플러그인. Python 패키지나 Alpaca 계정 자격증명은 요구하지 않는다.
- Yahoo 실패 가격 또는 미국 국채 증거를 실제로 쓸 때는 연결된 official Wolfram plugin. 별도 Wolfram HTTP 경로, SDK, MCP 서버, 공개 웹페이지, 스크래핑, API 키는 이 계약의 실행 경로가 아니다.
- 재현 가능한 분석을 위해 실행 시각, 인수, 오류 JSON을 보존할 수 있는 파일 공간.

CLI는 시작할 때 네 패키지의 import를 검사한다. 하나라도 없으면 같은 Python 인터프리터로 `requirements.txt`를 격리된 런타임 디렉터리에 자동 설치하고, 그 경로를 import 경로의 맨 앞에 추가한 뒤 네 패키지를 전부 다시 검사한다. 첫 `ModuleNotFoundError`는 오류가 아니라 설치 트리거다. 기존 패키지가 모두 import되면 설치를 생략한다.

기본 설치 위치는 현재 작업 디렉터리의 `.advisor-runtime/<python-version>-<requirements-hash>`이며, 그 위치가 쓰기 불가능하면 임시 격리 디렉터리를 시도한다. `EVIDENCE_ADVISOR_DEPS_DIR`가 설정되어 있으면 그 명시적 경로만 사용한다. 시스템 Python과 전역 site-packages는 변경하지 않는다.

첫 설치 명령이 실패하면 손상된 패키지 캐시를 배제하도록 `--no-cache-dir`로 한 번만 재시도한다. 두 설치 명령 실패, 격리 경로 쓰기 실패, 설치 후 재검증 실패일 때만 해당 데이터 도구 실행을 중단한다. Yahoo HTTP 429, 네트워크 오류, 빈 가격 이력은 설치 성공 이후의 별도 데이터 소스 오류다. 패키지 부재로 오인해 `cloud_runtime_unavailable`로 합치지 않는다. 모델 지식으로 가격·뉴스·포트폴리오 결과를 대체하지 않는다. 조직의 도메인 허용 목록에 Python 패키지 인덱스, Yahoo, 검증할 1차 출처가 포함되어야 할 수 있다.

## 후보 계약

`search`는 선택이 아니라 다음 후보 목록을 반환한다.

```json
{
  "symbol": "005930.KS",
  "short_name": "Samsung Electronics Co., Ltd.",
  "long_name": null,
  "exchange": "KSC",
  "exchange_display": "Korea Stock Exchange",
  "quote_type": "EQUITY",
  "type_display": "Equity",
  "yahoo_score": 1000010.0
}
```

LLM이 고른 `symbol`은 후보 집합에 정확히 존재해야 한다. `validate`는 최근 조정 가격 행, 거래소, 통화, 시간대, 검증시각이 있는 영수증을 반환해야 한다. 후보에 없거나 가격 이력이 없으면 해당 종목 분석은 중단한다.

## 재무·뉴스 계약

`fundamentals.values`의 필드는 숫자 또는 `null`이다. `null`은 0이 아니며 `missing_fields`에 기록한다. 값의 통화와 조회시각을 보존한다.

`news`의 모든 결과는 `source_role: discovery_only`다. 제목·발행자·URL·발행시각 중 누락된 항목을 LLM이 채우지 않는다. 사실 또는 인과 주장은 URL의 원문이나 공식 공시를 별도로 확인한 후에만 쓴다.

Yahoo 재무·밸류에이션 또는 뉴스 조회가 실패하면 웹 검색은 후보 발견에만 쓴다. 검색 결과의 제목·스니펫은 `discovery_only`이며 숫자나 사건을 확정하지 못한다. 실제 페이지를 열어 본 뒤 일반 언론·금융 출처는 `publisher_verified`, 회사 IR·규제기관·거래소 원문은 `primary_verified`로 기록한다. 각 재무 값에는 URL, 조회시각, 회계기간 또는 기준일, 통화, 단위, 보고값/계산값 구분을 붙인다. 해결되지 않은 값은 계속 `null`과 `missing_fields`로 남긴다.

## 가격·환율 계약

자산 다운로드는 일간, `auto_adjust=true`, `actions=true`, `repair=true`, `keepna=true`를 먼저 요청한다. yfinance/pandas 조합에서 수리 경로가 실패하면 `repair=false`로 한 번 재시도하고, 실제 사용 여부와 첫 오류 유형을 영수증에 기록한다. 영수증에는 티커, 시작·종료일, 기준 통화, 조정·수리 옵션, 수리 행 수, 조회시각을 기록한다.

- 자산·기준 통화: Yahoo가 유효한 3자리 통화 코드와 가격·환율 이력을 반환하는 통화를 런타임에 시도한다.
- 우선 환율 심볼: `통화USD=X`(통화 1단위당 USD). 실패하면 `통화=X`를 조회해 역수로 사용한다.
- 임의의 자산 통화를 기준 통화로 바꿀 때는 `자산가격 × 자산통화의 USD가치 ÷ 기준통화의 USD가치`를 사용한다.
- `GBp`/`GBX`, `ZAc`, `ILA`처럼 Yahoo가 소단위로 표기하는 가격은 GBP, ZAR, ILS의 1/100로 정규화한다.
- 자산 가격 누락은 전진 채우지 않는다.
- 환율은 달력 차이를 위해 최대 3일만 전진 채운다.

### 가격 공급자 라우팅

| 데이터 | 우선 출처 | 허용 대안 | 대안 없음 |
|---|---|---|---|
| 최근·과거 가격 | Yahoo 조정 가격 | Alpaca: 의미상 확인된 미국 주식 또는 크립토, 그 외 또는 Alpaca 실패 후 exact Financial entity의 Wolfram | 최종 검증 공급자를 정하지 못하면 해당 자산 중단 |
| 통화 메타데이터·FX | Yahoo | 없음 | 필수 환율이 없으면 계산 중단 |
| 재무·밸류에이션 | Yahoo | 검색 후 연 원문 | 확인하지 못한 필드는 `null` |
| 뉴스 | Yahoo 발견 후보 | 검색 후 연 원문 | 확인하지 못한 사건은 주장하지 않음 |

Yahoo 가격이 성공한 심볼은 Alpaca 또는 Wolfram으로 중복 조회하지 않는다. 가격 폴백 대상은 LLM이 사용자 전체 문맥과 구조화된 Yahoo 후보 메타데이터로 `us_equity`, `crypto`, `unsupported_market`, `ambiguous` 중 하나로 의미 분류한다. 접미사·구분자·정규식·고정 국가 목록으로 분류하지 않는다. `us_equity`와 `crypto`만 Alpaca를 먼저 시도하며, 결정론적 어댑터는 그 두 클래스만 받는다. Alpaca가 의미상 대상이 아니거나, 연결되지 않았거나, 불완전하거나, 증거 게이트에서 실패하면 exact Financial entity를 확인할 수 있는 경우에만 official Wolfram plugin을 다음 대안으로 쓴다. Yahoo 통화 메타데이터는 모든 자산에 계속 필수다. FX는 Yahoo가 우선이며 그 통화 다리가 실패한 경우에만 별도 official Wolfram FX 봉투를 허용한다.

### Alpaca 증거 봉투

Alpaca는 Python 라이브러리가 아니라 ChatGPT가 호출하는 플러그인이다. 도구 응답을 가공하거나 요약하지 말고 다음 스키마 버전 1 봉투에 그대로 보존한 뒤 `alpaca-validate` 또는 `complete-portfolio`로 검증한다.

```json
{
  "schema_version": 1,
  "symbol": "BTC-USD",
  "provider_symbol": "BTC/USD",
  "fallback_class": "crypto",
  "classification_evidence": {
    "quote_type": "CRYPTOCURRENCY",
    "currency": "USD"
  },
  "primary_failure": {
    "code": "price_history_unavailable"
  },
  "bars_response": {}
}
```

- 미국 주식은 정확한 `asset_response`, `get_stock_bars` 결과인 `bars_response`, 관측 기간을 덮는 `corporate_actions_response`가 모두 필요하다. 자산 응답은 동일 심볼, `us_equity`, `active`를 확인해야 한다. 기업행동 요청은 같은 단일 심볼을 모든 행동 유형에 대해 조회해야 하며, 응답의 시작·종료일이 실제 bar 범위를 덮어야 한다.
- 크립토는 정확한 슬래시 표기 심볼을 포함한 `get_crypto_bars` 결과가 필요하며 기업행동 응답은 쓰지 않는다.
- bars 응답의 `tool`, `request.symbols`, 개별 bar의 `symbol`, 타임스탬프, 양의 유한 종가를 검증한다. 서로 충돌하는 중복 시점은 거부하고 같은 값의 중복만 하나로 접는다.
- 미국 주식의 원시 종가는 수익률에 직접 넣지 않는다. 선·역분할은 권리락일 전 가격에 비율을 역적용하고, 현금배당은 이용 가능한 직전 종가로 총수익 가격 계수를 계산한다. 아직 어댑터가 지원하지 않는 비어 있지 않은 기업행동 그룹, 다음 페이지가 남은 응답, 필요한 기업행동 증거 누락, 안전하게 계산할 수 없는 조정은 모두 실패한다.
- 결과 영수증은 Yahoo의 최초 실패, 최종 공급자, 두 심볼, 분류 근거, Alpaca 도구·피드·주기, 요청/관측 범위, 원시/정규화 관측치 수, 가격 기준, 통화, 적용한 기업행동, 누락 또는 잘린 범위, 조회시각을 보존한다.

미국 주식·크립토 가격 폴백이 실제로 필요하지만 Alpaca 도구가 설치되어 있지 않거나 호출할 수 없으면 `alpaca_plugin_unavailable`을 보고하고 다음 문구를 그대로 보여 준다.

> 미국 주식·크립토 가격의 대안 출처로 Alpaca 플러그인을 사용할 수 있습니다. 별도 회원가입은 필요 없고, 플러그인을 연결하기만 하면 됩니다.

이 안내는 Yahoo 가격이 성공한 경우, 한국 주식, 지원하지 않는 시장, 종목이 모호한 경우, 가격과 무관한 요청에는 표시하지 않는다.

### Wolfram 금융 증거 봉투

Wolfram은 연결된 official Wolfram plugin이 반환한 구조화된 Wolfram Language 결과와 source annotation만으로 사용한다. ChatGPT가 다음 스키마 버전 1 봉투에 값을 보존하고 `wolfram-validate`로 검증한다. CLI는 봉투만 검증하며 Wolfram을 호출하지 않는다. 직접 HTTP, Python SDK, 별도 MCP, 공개 웹페이지, 스크래핑, 이미지 추출, API 키 요청은 금지다.

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
  "request": {"start": "2021-01-01", "end": "2026-08-15"},
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
    "observations": [
      {"timestamp": "2026-08-13T00:00:00+00:00", "value": 230.0},
      {"timestamp": "2026-08-14T00:00:00+00:00", "value": 231.0}
    ]
  },
  "sources": [{"name": "Named provider from Wolfram annotation", "url": "https://example.invalid/source"}],
  "retrieved_at": "2026-08-16T00:00:00+00:00"
}
```

`entity_type` must be `Financial`. `classification_evidence` must contain both structured `yahoo_candidate` and structured `wolfram_observed` identities. The validator deterministically compares symbol, provider entity, exchange, issuer/company, security type, `share_class` or `instrument_subtype`, and currency against the returned result; a bare model-authored `identity_decision: match` is never evidence. Every required field must be present and every available subtype field must agree.

`result.unit` is structured monetary evidence rather than prose. `name`, `canonical_currency`, and `quantity_kind: monetary` are mandatory. The conservative unit mapping currently recognizes the observed Wolfram identifiers `USDollars → USD` and `Euros → EUR`; adding another currency requires an explicit deterministic unit mapping, not a country allowlist or a model assertion. A USD result paired with `Euros`, an unrecognized unit name, a string-only unit, or a mismatched canonical currency raises `wolfram_unit_mismatch`.

The envelope `request.start` and `request.end` must equal the caller's `wolfram-validate` or workspace range after UTC normalization, including `null` for an open-ended request. A mismatch raises `wolfram_request_mismatch`. For `AdjustedClose`, both observed endpoints may differ from the requested endpoints by at most seven calendar days under the documented **market-calendar endpoint tolerance** for ordinary weekends and adjacent holidays. Start coverage is calculated from the first observation on or after the requested start, and every history—including an open-ended request—must contain such an observation. A pre-window-only series or a larger clipped interval raises the dedicated `wolfram_history_incomplete` gate. This endpoint rule does not forward-fill prices. `recent_price` is separate and uses a seven-calendar-day freshness policy against the requested end or retrieval time; stale evidence raises `wolfram_recent_price_stale`.

Observations must be finite positive dated structured values, and source annotations need a non-empty provider name. The returned property must equal `requested_property`. `Price`, `LatestTrade`, and `Close` may satisfy only `recent_price`; only `AdjustedClose` satisfies `adjusted_total_return`. Therefore every total-return backtest, MPT computation, and other return calculation using Wolfram requires `AdjustedClose`; recent-price properties and `RawClose` are never substitutes.

If the plugin is unavailable, identity is not exact, property/coverage/source evidence is missing, or structured output is unusable, preserve the error (`wolfram_plugin_unavailable`, `wolfram_entity_mismatch`, `wolfram_property_unavailable`, `wolfram_source_unavailable`, or `wolfram_schema_error`) and stop that affected asset. Do not convert rendered tables or images into numeric evidence.

### Wolfram FX fallback envelope

Yahoo is the primary FX provider. Only a currency recorded in `fallback_required_fx` after a Yahoo `fx_history_unavailable` failure may use this official-plugin envelope. Asset currency metadata remains Yahoo-authoritative.

```json
{
  "schema_version": 1,
  "provider": "wolfram",
  "evidence_kind": "fx_history",
  "currency": "KRW",
  "request": {
    "start": "2021-01-01",
    "end": "2026-08-15",
    "base_currency": "KRW",
    "quote_currency": "USD"
  },
  "primary_failure": {
    "provider": "yahoo",
    "code": "fx_history_unavailable",
    "message": "Yahoo returned no usable USD conversion pair for KRW.",
    "details": {"stage": "fx_history", "currency": "KRW"}
  },
  "result": {
    "entity_type": "FinancialData",
    "symbol": "KRW/USD",
    "base_currency": "KRW",
    "quote_currency": "USD",
    "unit": {
      "quantity_kind": "exchange_rate",
      "numerator_currency": "USD",
      "denominator_currency": "KRW"
    },
    "observations": [
      {"timestamp": "2026-08-13T00:00:00+00:00", "value": 0.000701},
      {"timestamp": "2026-08-14T00:00:00+00:00", "value": 0.000705}
    ]
  },
  "sources": [{
    "name": "Wolfram FinancialData",
    "role": "official_plugin_tool",
    "underlying_source_annotation": null,
    "source_annotation_status": "unavailable"
  }],
  "retrieved_at": "2026-08-17T00:00:00+00:00"
}
```

`CCY/USD` is already USD per one currency unit. `USD/CCY` is currency units per USD and is inverted exactly once. The pair, result symbol, and structured numerator/denominator unit must agree. Every normalized output is USD per one unit of `currency`; the receipt states the observed pair, `inversion_applied`, conversion rule, requested/observed ranges, observation count, and original Yahoo failure.

Official plugin probes exposed `Wolfram FinancialData` but no separate underlying vendor annotation, so the underlying source annotation is unavailable and remains `null`; it must not be guessed. Each required currency has one provider for its whole history. Yahoo and Wolfram may serve different currency legs, but their observations are never spliced within one leg. Validate a standalone envelope with `wolfram-fx-validate`; pass completed currency evidence separately with repeatable `--wolfram-fx-input`.

Errors are `wolfram_fx_schema_error`, `wolfram_fx_pair_mismatch`, `wolfram_fx_unit_mismatch`, `wolfram_fx_history_unavailable`, `wolfram_fx_history_incomplete`, and `wolfram_fx_source_unavailable`.

### U.S. Treasury Wolfram evidence envelope

U.S. Treasury evidence also comes only from the official Wolfram plugin. The LLM emits the requested structured qualifiers; the deterministic harness accepts the documented vocabulary but does not infer a qualifier from a text parser. A complete nominal 3-month daily constant-maturity history envelope is:

The preferred retrieval path compiles the LLM's structured Treasury intent into a fixed Wolfram Language property expression. It never executes WolframAlpha webpage parameters as code and never reads a rendered result page. The canonical nominal maturities verified on 2026-08-17 were `"3Month"`, `"1Year"`, `"2Year"`, `"5Year"`, `"10Year"`, and `"30Year"`; the associated security types were `"Bill"`, `"Note"`, and `"Bond"`. A 10-year example is:

```wl
property = EntityProperty["Country", "Treasury", {
  "Date" -> All,
  "DueDate" -> "ConstantMaturity",
  "Frequency" -> "Daily",
  "MaturityDuration" -> "10Year",
  "SecurityType" -> "Note"
}];
series = \[FreeformPrompt]["United States", "Country"][property];
Normal[TimeSeriesWindow[series, {start, end}]]
property["Source"]
```

The successful evaluator result must contain dated `Quantity[..., "Percent"]` values. The evaluated property expression is preserved as the provider-observed qualifier receipt, the classifier's typed maturity is preserved separately, and the source annotation is copied without rewriting it; the live probe identified `FREDII`. A natural-language `\[FreeformPrompt]` may be used as interpretation evidence, but if it turns a duration into an ambiguous generic `Quantity`, it does not override the structured intent. The fixed template is retried with the canonical string, and all requested/provider-observed qualifier and numeric maturity gates still apply. The query becomes `provider_confirmed` only after this exact structured evaluation succeeds; a labeled result without exact evaluation remains `provider_labeled_inferred`.

```json
{
  "schema_version": 1,
  "provider": "wolfram",
  "evidence_kind": "us_treasury_history",
  "country_entity": "UnitedStates",
  "qualifiers": {
    "security_type": "Bill",
    "maturity_duration": "3Month",
    "market": null,
    "due_date": "ConstantMaturity",
    "frequency": "Daily",
    "time_series_operator": null,
    "coupon_rate": null
  },
  "request": {
    "start": "2021-01-01",
    "end": "2026-08-15",
    "requested_qualifiers": {
      "security_type": "Bill",
      "maturity_duration": "3Month",
      "market": null,
      "due_date": "ConstantMaturity",
      "frequency": "Daily",
      "time_series_operator": null,
      "coupon_rate": null
    },
    "requested_maturity": {
      "duration": "3Month",
      "years": 0.25,
      "unit": "years",
      "evidence_kind": "classifier_typed_request"
    }
  },
  "result": {
    "property": "Treasury",
    "maturity_years": 0.25,
    "observed_qualifiers": {
      "security_type": "Bill",
      "maturity_duration": "3Month",
      "market": null,
      "due_date": "ConstantMaturity",
      "frequency": "Daily",
      "time_series_operator": null,
      "coupon_rate": null
    },
    "observed_maturity": {
      "duration": "3Month",
      "years": 0.25,
      "unit": "years",
      "evidence_kind": "provider_observed_typed"
    },
    "unit": "Percent",
    "observations": [
      {"timestamp": "2026-08-13T00:00:00+00:00", "value": 4.55},
      {"timestamp": "2026-08-14T00:00:00+00:00", "value": 4.54}
    ],
    "missing": []
  },
  "sources": [{"name": "FRED (Federal Reserve Economic Data)", "organization": "Federal Reserve Bank of St. Louis", "url": "https://fred.stlouisfed.org/"}],
  "retrieved_at": "2026-08-16T00:00:00+00:00"
}
```

`security_type` and non-empty semantic `maturity_duration` are required. Known `security_type` values are `Bill`, `Note`, `Bond`, and `TIPS`. `market` is optional and, when present, is `AuctionAverage` or `SecondaryMarket`; `due_date` is optional and, when present, is `ConstantMaturity`; `frequency` is optional and, when present, is one of `Daily`, `Weekly`, `BiWeekly`, `Monthly`, `Quarterly`, or `Annual`; `time_series_operator` is optional and, when present, is `Change`, `ChangeRate`, `AnnualChange`, `AnnualizedChangeRate`, or `YearOverYearChangeRate`; `coupon_rate` is optional and finite when present.

For every successful observation envelope, all seven qualifier keys must appear in top-level `qualifiers`, `request.requested_qualifiers`, and provider-returned `result.observed_qualifiers`; the three structures must agree exactly, including explicit `null` values. `request.requested_maturity` and provider-derived `result.observed_maturity` both carry typed numeric years. Their duration and numeric years must agree with one another and with `result.maturity_years`. The validator never parses `10Year` text into a number, so a request carrying typed `10.0` years cannot be satisfied by provider-observed `2.0` years even if a model labels it `10Year`; the conflict raises `treasury_maturity_mismatch`.

`evidence_kind` is `us_treasury_current` (at least one observation) or `us_treasury_history` (at least two observations); country is exactly `UnitedStates`, property is `Treasury`, and unit is `Percent`.

Preserve Wolfram `Missing` in `result.missing`. An empty result with the requested maturity marked unavailable is `treasury_maturity_unavailable`; another empty series is `treasury_series_unavailable`. A provider that returns `Missing[NotAvailable]` may be unable to emit `observed_qualifiers`, `observed_maturity`, or `maturity_years`; the validator checks the complete requested echo and then preserves the exact unavailable error rather than converting it to a schema success or substituting evidence. Never replace either result with a nearby maturity. A curve returns direct `observation` values separately from explicit `calculation` values: only an opt-in, bounded linear maturity interpolation may be labelled `linear_maturity_interpolation`, never represented as observed evidence.

Successful exact envelopes normalize to `evidence_tier: provider_confirmed`, `evidence_confidence: high`, `maturity_binding: provider_typed_exact`, and `exact_qualifier_status: confirmed`.

When exact qualifiers return unavailable but the official plugin still provides an explicitly labeled current result or a maturity-specific input interpretation with dated `Percent` observations, the orchestration layer may emit the lower tier:

```json
{
  "evidence_tier": "provider_labeled_inferred",
  "exact_qualifier_failure": {
    "status": "unavailable",
    "query": "exact Wolfram Treasury qualifiers for 10Year",
    "requested_maturity_years": 10.0,
    "missing": [{"maturity_duration": "10Year", "value": "Missing[NotAvailable]"}]
  },
  "binding_evidence": {
    "channel": "official_plugin_labeled_result",
    "query": "current U.S. Treasury 10-year yield",
    "input_interpretation": "United States Treasury 10Year Note yield",
    "displayed_label": "10-year note",
    "observation_date": "2026-08-13"
  },
  "binding_decision": {
    "decision_kind": "structured_llm_semantic_binding",
    "requested_maturity_years": 10.0,
    "bound_maturity_years": 10.0,
    "maturity_match": true,
    "conflicts": []
  }
}
```

Historical evidence uses `official_plugin_input_interpretation` and an `observation_date_range` matching the first and last structured observations. This is a structured LLM semantic binding harness: deterministic code validates the typed decision and never derives maturity with a substring or regex parser. Missing exact-query evidence, an absent label/interpretation, a missing or conflicting observation date/range, a maturity conflict, a nonempty conflict list, an unsupported channel such as webpage scraping, or an unlabeled number raises `treasury_binding_unavailable`.

Normalized lower-tier receipts always retain `"evidence_confidence": "lower"`, `maturity_binding: provider_labeled_or_semantically_inferred`, and `"exact_qualifier_status": "unavailable"`. Curves, interpolations, historical alignments, periodic risk-free conversions, and dependent metrics inherit the weakest upstream tier and the lower-confidence warning. Lower confidence does not change the numeric formula and never becomes provider-confirmed evidence.

### 혼합 공급자 워크스페이스

`prepare-portfolio`는 심볼별 Yahoo 성공 가격과 통화, Yahoo FX, 영수증, 실패를 스키마 버전 1 JSON에 원자적으로 저장한다. 따라서 한 종목의 실패가 다른 종목의 성공 증거를 지우지 않는다. 오직 Yahoo asset-price stage로 증명된 실패만 `fallback_required_symbols`가 된다. `price_history_unavailable`는 가격 전용 코드라 인정하고, production `network_error`는 `details.stage == "asset_price"`일 때만 인정한다. generic/unscoped network error, `currency_unavailable`, 스키마·기타 비가격 오류는 자산 폴백 요구로 변환하지 않는다. Currency metadata와 FX 오류 영수증은 각각 `currency_metadata`, `fx_history` stage를 보존한다. FX 실패는 자산 증거를 지우지 않고 `fx_failures`와 `fallback_required_fx`에 통화별로 남는다.

가격만 실패한 심볼은 Yahoo 통화 메타데이터를 가격과 독립적으로 다시 조회해 `yahoo_currency_evidence`에 저장하고, 그 Yahoo 통화 및 기준 통화에 필요한 FX를 함께 조회한다. 완료 단계는 폴백의 정규화 통화가 저장된 Yahoo 정규화 통화와 같은지 확인하지만 계산 통화 단위에는 Yahoo 원 표기(소단위 포함)를 권위로 사용한다. Yahoo FX 성공 통화는 그대로 보존한다. 실패 통화만 검증된 `--wolfram-fx-input`으로 채울 수 있으며, 요청하지 않은 통화, 중복 입력, Yahoo 성공 통화 입력, 잘못된 쌍, 미해결 필수 통화는 `fx_history_unavailable` 또는 해당 검증 오류로 전체 계산을 막는다.

`complete-portfolio`는 실패한 각 심볼에 정확히 하나의 검증된 Alpaca 또는 Wolfram 봉투를 요구하고, 실패한 각 필수 FX 통화에 정확히 하나의 검증된 Wolfram FX 봉투를 요구한다. 성공하면 자산 공급자를 `download_receipt.providers`, 통화별 공급자를 `download_receipt.fx_providers`에 기록하고 기존 최대 3일 FX 정렬·수익률·최적화 게이트를 그대로 실행한다.

## 수익률·포트폴리오 계약

수익률 행렬은 모든 종목이 같은 날짜에 존재하는 유한한 단순 수익률이어야 한다. 기본은 금요일 기준 주간 마지막 가격과 최소 104개 공통 관측치다. 영수증에는 종목별 통화, 기준 통화, 빈도, 연율화 계수, 공통 관측치, 첫·마지막 수익률 일자, 누락 수를 포함한다.

최소분산 후보는 다음 제약을 만족해야 한다.

- 종목 수 2개 이상.
- 비중 합 1.
- 종목별 비중 0 이상, `max_weight` 이하.
- 유한하고 퇴화하지 않은 공분산.
- SLSQP 수렴 및 사후 제약 검증.

동일가중은 `comparison_only`, 최소분산은 `portfolio_candidate_not_order_instruction` 역할을 가진다. 어느 게이트든 실패하면 결과 비중을 출력하지 않는다.

### 무위험수익률 계약

백테스트의 기본 위험무위험 요청은 historical window를 덮는 United States 3-month Treasury bill, `ConstantMaturity`, `Daily` Wolfram 역사 시계열이다. `provider_confirmed` 또는 완전한 semantic binding을 가진 `provider_labeled_inferred` 역사 증거를 사용할 수 있다. 연간 Percent 수익률은 `effective_annual_to_periodic`이라는 공개 분석 규칙으로 `periodic = (1 + annual_percent / 100)^(1 / periods_per_year) - 1`로 변환한다. 이 변환은 공급자 사실이 아니라 명시된 분석 관례다. 과거 관측치는 미래를 보지 않고 최대 3 calendar days만 전진 정렬할 수 있다. 어느 tier에서도 maturity/date/unit/source channel과 시의성 있는 관측치를 검증하지 못하면 샤프, 소르티노, 알파 같은 의존 필드는 `null`과 `risk_free_rate_unavailable`을 유지한다.

정렬 영수증은 각 반환 날짜를 `aligned_observations` 항목으로 기록한다. 각 항목에는 `return_date`, 실제 `source_date`, `source_age_days`, `raw_annual_percent`, 변환 후 `periodic_rate`, `rate_input_confidence`가 함께 있어야 한다. 최상위 영수증에는 `unit`, `retrieved_at`, `requested_range`, `observed_range`, `evidence_kind`, `evidence_tier`, `evidence_confidence`, `maturity_binding`, `exact_qualifier_status`, `missing`, 그리고 공급자·국가 entity·property·수치 maturity·qualifier·원 source annotation을 묶은 `upstream_provenance`를 보존한다.

```json
{
  "aligned_observations": [
    {
      "return_date": "2026-01-09T00:00:00+00:00",
      "source_date": "2026-01-09T00:00:00+00:00",
      "source_age_days": 0,
      "raw_annual_percent": 5.2,
      "periodic_rate": 0.000975
    }
  ],
  "unit": "Percent",
  "retrieved_at": "2026-08-16T00:00:00+00:00",
  "requested_range": {"start": "2025-01-01T00:00:00+00:00", "end": "2026-08-13T00:00:00+00:00"},
  "observed_range": {"start": "2026-01-02T00:00:00+00:00", "end": "2026-01-09T00:00:00+00:00"},
  "evidence_kind": "us_treasury_history",
  "missing": [],
  "upstream_provenance": {"provider": "wolfram", "property": "Treasury"}
}
```

## 백테스트 출력 계약

명시적인 백테스트 요청의 기본 UI 계약은 ChatGPT Work 클라우드 모드의 `ChatGPT 빌트인 인터랙티브 누적 총수익률 차트`와 그 바로 아래의 `포트폴리오 평가 테이블`이다. 외부 차트 플랫폼과 커스텀 HTML은 이 계약의 구현 수단이 아니며, 다른 제품이나 로컬 모드를 위한 대체 경로는 지원 범위가 아니다.

차트에 들어가는 모든 시계열은 하나의 공통 최초 유효 관측일을 가져야 하며 그 시점의 누적수익률은 정확히 `0%`다. 표시 열은 포트폴리오와 검증된 비교지수이고, 표의 필수 행은 `누적수익률`, `연환산 수익률`, `연환산 변동성`, `샤프지수`, `소르티노지수`, `최대낙폭(MDD)`, `주 비교지수 기준 베타`, `주 비교지수 상관계수`, `연환산 알파`다. 차트와 표는 같은 심볼, 기간, 통화 변환, 가격 조정, 배당 재투자, 리밸런싱 규칙을 사용해야 한다.

영수증 또는 출력 주석에는 다음을 보존한다.

- 차트 렌더러: `chatgpt_builtin_interactive`.
- 시작일·종료일, 표시 빈도, 지표 계산 빈도, 공통 관측치 수.
- 포트폴리오 구성·리밸런싱 규칙과 각 가격 시리즈 공급자.
- 가격 조정 및 배당 재투자 여부, 기준 통화와 FX 처리.
- 주 비교지수와 그 선택 근거.
- 무위험수익률 값·출처·기준일·계산 규칙.
- 계산할 수 없어 `null`이 된 지표와 사유.

사용자 요청 기간이 MPT의 기본 104개 주간 공통 수익률보다 짧다는 이유만으로 백테스트 표시를 실패시키지 않는다. 백테스트 계산에 필요한 가격 이력이 충분한지 별도로 판정한다. 반대로 백테스트 차트가 생성되었다는 사실은 MPT 비중 게이트 통과를 의미하지 않는다.

비교지수 검증 실패 시 포트폴리오 시계열은 유지하되 비교지수 의존 셀을 `null`로 두고 `benchmark_unavailable` 사유를 남긴다. 차트와 표의 데이터 범위·처리가 다르거나, 외부 차트 플랫폼 또는 다른 제품용 폴백을 사용하는 출력은 계약 위반이다.

## 오류 계약

CLI 성공은 표준출력 JSON과 종료코드 0이다. 데이터 게이트 실패는 표준에러 JSON과 종료코드 2, 예상하지 못한 실패는 종료코드 3이다.

의존성 오류 코드는 `requirements_missing`, `dependency_install_failed`, `dependency_import_failed`다. 주요 Yahoo·계산 오류 코드는 `candidate_not_returned`, `price_history_unavailable`, `fundamentals_unavailable`, `news_unavailable`, `currency_unavailable`, `fx_history_unavailable`, `insufficient_assets`, `insufficient_history`, `unsupported_currency`, `non_finite_returns`, `degenerate_covariance`, `infeasible_constraints`, `optimization_failed`, `network_error`다.

폴백·증거 오류 코드는 `fallback_not_supported`, `fallback_class_ambiguous`, `fallback_currency_mismatch`, `alpaca_plugin_unavailable`, `alpaca_asset_not_found`, `alpaca_history_unavailable`, `alpaca_history_incomplete`, `alpaca_schema_error`, `corporate_actions_unavailable`, `corporate_action_adjustment_failed`, `wolfram_plugin_unavailable`, `wolfram_entity_mismatch`, `wolfram_property_unavailable`, `wolfram_source_unavailable`, `wolfram_schema_error`, `wolfram_request_mismatch`, `wolfram_history_incomplete`, `wolfram_recent_price_stale`, `wolfram_qualifier_mismatch`, `wolfram_unit_mismatch`, `wolfram_fx_schema_error`, `wolfram_fx_pair_mismatch`, `wolfram_fx_unit_mismatch`, `wolfram_fx_history_unavailable`, `wolfram_fx_history_incomplete`, `wolfram_fx_source_unavailable`, `treasury_series_unavailable`, `treasury_maturity_unavailable`, `treasury_maturity_mismatch`, `treasury_binding_unavailable`, `treasury_alignment_failed`, `risk_free_rate_unavailable`, `evidence_workspace_invalid`, `web_evidence_unavailable`, `web_primary_source_unverified`다. `wolfram_plugin_unavailable`과 `risk_free_rate_unavailable`은 ChatGPT 오케스트레이션/출력 계약의 상태 코드이며, 나머지 Wolfram/Treasury 게이트는 CLI 검증 결과일 수 있다. 웹 관련 두 코드는 모델 오케스트레이션 계약이며 CLI가 검색을 직접 실행한다는 뜻이 아니다.

오류가 난 분석 부분만 중단한다. 단, 티커 검증 실패는 그 티커에 의존하는 가격·재무·뉴스·포트폴리오 분석 전체를 막는다.
