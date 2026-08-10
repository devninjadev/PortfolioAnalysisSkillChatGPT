# 데이터 계약과 클라우드 실행 조건

## 런타임 요구사항

- Python 3.11 이상.
- `requirements.txt`의 `yfinance`, `pandas`, `numpy`, `scipy`.
- Yahoo Finance 및 뉴스 원문 도메인으로의 HTTPS 접근.
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

## 가격·환율 계약

자산 다운로드는 일간, `auto_adjust=true`, `actions=true`, `repair=true`, `keepna=true`를 먼저 요청한다. yfinance/pandas 조합에서 수리 경로가 실패하면 `repair=false`로 한 번 재시도하고, 실제 사용 여부와 첫 오류 유형을 영수증에 기록한다. 영수증에는 티커, 시작·종료일, 기준 통화, 조정·수리 옵션, 수리 행 수, 조회시각을 기록한다.

- 자산·기준 통화: Yahoo가 유효한 3자리 통화 코드와 가격·환율 이력을 반환하는 통화를 런타임에 시도한다.
- 우선 환율 심볼: `통화USD=X`(통화 1단위당 USD). 실패하면 `통화=X`를 조회해 역수로 사용한다.
- 임의의 자산 통화를 기준 통화로 바꿀 때는 `자산가격 × 자산통화의 USD가치 ÷ 기준통화의 USD가치`를 사용한다.
- `GBp`/`GBX`, `ZAc`, `ILA`처럼 Yahoo가 소단위로 표기하는 가격은 GBP, ZAR, ILS의 1/100로 정규화한다.
- 자산 가격 누락은 전진 채우지 않는다.
- 환율은 달력 차이를 위해 최대 3일만 전진 채운다.

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

의존성 오류 코드는 `requirements_missing`, `dependency_install_failed`, `dependency_import_failed`다. 주요 데이터 오류 코드는 `candidate_not_returned`, `price_history_unavailable`, `fundamentals_unavailable`, `news_unavailable`, `currency_unavailable`, `fx_history_unavailable`, `insufficient_assets`, `insufficient_history`, `unsupported_currency`, `non_finite_returns`, `degenerate_covariance`, `infeasible_constraints`, `optimization_failed`, `network_error`다.

오류가 난 분석 부분만 중단한다. 단, 티커 검증 실패는 그 티커에 의존하는 가격·재무·뉴스·포트폴리오 분석 전체를 막는다.
