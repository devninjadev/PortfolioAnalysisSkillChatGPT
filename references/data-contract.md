# 데이터 계약과 클라우드 실행 조건

## 런타임 요구사항

- Python 3.11 이상.
- `requirements.txt`의 `yfinance`, `pandas`, `numpy`, `scipy`.
- Yahoo Finance 및 검증할 뉴스·공시 원문 도메인으로의 HTTPS 접근.
- 미국 주식·크립토 가격 폴백을 실제로 쓸 때는 연결된 Alpaca 플러그인. Python 패키지나 Alpaca 계정 자격증명은 요구하지 않는다.
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
| 최근·과거 가격 | Yahoo 조정 가격 | Alpaca: 의미상 확인된 미국 주식 또는 크립토 | 한국 주식과 그 밖의 시장 |
| 통화 메타데이터·FX | Yahoo | 없음 | 필수 환율이 없으면 계산 중단 |
| 재무·밸류에이션 | Yahoo | 검색 후 연 원문 | 확인하지 못한 필드는 `null` |
| 뉴스 | Yahoo 발견 후보 | 검색 후 연 원문 | 확인하지 못한 사건은 주장하지 않음 |

Yahoo 가격이 성공한 심볼은 Alpaca로 중복 조회하지 않는다. 가격 폴백 대상은 LLM이 사용자 전체 문맥과 구조화된 Yahoo 후보 메타데이터로 `us_equity`, `crypto`, `unsupported_market`, `ambiguous` 중 하나로 의미 분류한다. 접미사·구분자·정규식·고정 국가 목록으로 분류하지 않는다. 결정론적 어댑터는 앞의 두 클래스만 받으며, 제안된 Alpaca 심볼을 실제 도구 응답에서 다시 확인한다.

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

### 혼합 공급자 워크스페이스

`prepare-portfolio`는 심볼별 Yahoo 성공 가격과 통화, Yahoo FX, 영수증, 실패를 스키마 버전 1 JSON에 원자적으로 저장한다. 따라서 한 종목의 실패가 다른 종목의 성공 증거를 지우지 않는다. 출력의 `fallback_required_symbols`만 의미 분류 및 Alpaca 호출 대상으로 검토한다.

`complete-portfolio`는 실패한 각 심볼에 정확히 하나의 검증된 Alpaca 봉투를 요구한다. 요청하지 않은 봉투, 중복 봉투, 미해결 필수 종목, 빠진 Yahoo FX는 모두 전체 비중 계산을 막는다. 성공하면 각 자산의 공급자를 `download_receipt.providers`에 기록하고 기존 수익률·최적화 게이트를 그대로 실행한다.

## 수익률·포트폴리오 계약

수익률 행렬은 모든 종목이 같은 날짜에 존재하는 유한한 단순 수익률이어야 한다. 기본은 금요일 기준 주간 마지막 가격과 최소 104개 공통 관측치다. 영수증에는 종목별 통화, 기준 통화, 빈도, 연율화 계수, 공통 관측치, 첫·마지막 수익률 일자, 누락 수를 포함한다.

최소분산 후보는 다음 제약을 만족해야 한다.

- 종목 수 2개 이상.
- 비중 합 1.
- 종목별 비중 0 이상, `max_weight` 이하.
- 유한하고 퇴화하지 않은 공분산.
- SLSQP 수렴 및 사후 제약 검증.

동일가중은 `comparison_only`, 최소분산은 `portfolio_candidate_not_order_instruction` 역할을 가진다. 어느 게이트든 실패하면 결과 비중을 출력하지 않는다.

## 오류 계약

CLI 성공은 표준출력 JSON과 종료코드 0이다. 데이터 게이트 실패는 표준에러 JSON과 종료코드 2, 예상하지 못한 실패는 종료코드 3이다.

의존성 오류 코드는 `requirements_missing`, `dependency_install_failed`, `dependency_import_failed`다. 주요 Yahoo·계산 오류 코드는 `candidate_not_returned`, `price_history_unavailable`, `fundamentals_unavailable`, `news_unavailable`, `currency_unavailable`, `fx_history_unavailable`, `insufficient_assets`, `insufficient_history`, `unsupported_currency`, `non_finite_returns`, `degenerate_covariance`, `infeasible_constraints`, `optimization_failed`, `network_error`다.

폴백·증거 오류 코드는 `fallback_not_supported`, `fallback_class_ambiguous`, `alpaca_plugin_unavailable`, `alpaca_asset_not_found`, `alpaca_history_unavailable`, `alpaca_history_incomplete`, `alpaca_schema_error`, `corporate_actions_unavailable`, `corporate_action_adjustment_failed`, `evidence_workspace_invalid`, `web_evidence_unavailable`, `web_primary_source_unverified`다. 웹 관련 두 코드는 모델 오케스트레이션 계약이며 CLI가 검색을 직접 실행한다는 뜻이 아니다.

오류가 난 분석 부분만 중단한다. 단, 티커 검증 실패는 그 티커에 의존하는 가격·재무·뉴스·포트폴리오 분석 전체를 막는다.
