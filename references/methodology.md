# 상담 방법론

## 목적과 원칙

이 스킬은 특정 종목의 매수·매도를 자동 결정하지 않는다. 확인 가능한 시장·재무·뉴스 데이터와 사용자의 실제 제약을 결합해 조건부 포트폴리오 후보를 만든다. 핵심 원칙은 다음과 같다.

- 회사의 질, 현재 가격·밸류에이션, 포트폴리오 적합성을 서로 다른 축으로 평가한다.
- 사실, 계산, 해석, 시나리오를 구분한다.
- 좋은 이야기보다 반증 자료와 투자 논리가 깨지는 조건을 먼저 확인한다.
- 고정된 만능 점수표로 서로 다른 기업·산업을 억지로 줄 세우지 않는다.
- 계산은 스크립트에 맡기고, LLM은 의미 분류·후보 판별·설명에 집중한다.

## 상담 흐름

### 1. 요청 구조화

LLM으로 다음 JSON 의미 구조를 만든다. 한국어 조사·띄어쓰기·별칭을 정규식만으로 분류하지 않는다.

```json
{
  "instruments": [{"user_text": "삼성전자", "type_hint": "equity", "country_hint": "KR"}],
  "analysis": ["price", "fundamentals", "news", "portfolio"],
  "constraints": {
    "horizon": null,
    "loss_tolerance": null,
    "liquidity_need": null,
    "existing_holdings": null,
    "tax_or_account": null,
    "currency": "KRW"
  },
  "ambiguities": []
}
```

사용자가 제공하지 않은 제약은 추정해서 채우지 않는다. 제약이 비어 있으면 분석 후보는 제시할 수 있지만 개인화된 실행 비중이나 매매 시점은 제시하지 않는다.

### 2. 이름에서 티커로

Yahoo 검색 결과의 후보만 사용한다. LLM은 사용자의 전체 문맥과 후보의 `symbol`, 이름, 거래소, 유형을 함께 보고 후보를 선택한다. 보통주는 우선주·ETF·ADR과 구별한다. 같은 이름의 복수 종목이 합리적으로 남으면 후보 표를 보여 주고 사용자에게 확인한다. 선택 뒤에는 최근 가격 이력으로 실제 거래 가능한 티커인지 검증한다.

Yahoo 가격 이력이 실패했다고 티커 검색 자체를 다른 공급자로 바꾸지는 않는다. 선택된 후보의 가격 폴백 가능성은 전체 문맥과 구조화된 후보 메타데이터를 이용해 LLM으로 `us_equity`, `crypto`, `unsupported_market`, `ambiguous` 중 하나로 분류한다. 정규식, 티커 접미사, 대시·슬래시 치환, 고정 국가 목록으로 분류하지 않는다. 미국 주식과 크립토만 Alpaca 후보이며, Alpaca 도구 응답이 제안된 공급자 심볼과 자산 종류를 다시 확인하지 못하면 실패한다. Alpaca가 의미상 대상이 아니거나, 연결되지 않았거나, 불완전하거나, 증거 게이트에 실패하면 LLM은 official Wolfram plugin에서 exact `Financial` entity를 구조적으로 확인할 수 있는지 판단한다. 확인된 경우에만 Wolfram을 다음 가격 대안으로 사용하고, 그렇지 않으면 Yahoo 실패를 보존한다.

### 3. 기업과 밸류에이션

기업 분석은 최소한 다음 세 묶음으로 나눈다.

1. 사업의 질: 수익 구조, 경쟁 우위, 재투자 기회, 재무 건전성.
2. 현재 가격: 시가총액, P/E, P/B, EV/EBITDA, 마진, 현금흐름, 현금·부채.
3. 포트폴리오 역할: 기존 보유분과의 중복, 통화, 국가·산업 집중, 변동성·상관관계.

Yahoo 값이 비어 있거나 조회가 실패하면 웹 검색으로 후보 출처를 찾되 검색 스니펫을 증거로 쓰지 않는다. 회사 IR·실적 자료, 규제기관 공시, 거래소 공시, 감사보고서를 우선 열고 확인한다. 그다음에만 신뢰할 만한 보도·2차 금융 출처를 쓴다. 값은 URL, 조회시각, 회계기간/기준일, 통화, 단위, 보고값/계산값 구분과 함께 보존한다. 확인하지 못한 필드는 `unknown` 또는 `null`로 유지한다. 회계 기준·통화·기준일이 다른 숫자를 직접 비교하지 않는다.

### 4. 가격과 뉴스

“실제로 주가가 어땠는가”는 Yahoo 조정 가격과 명시된 기간·통화 기준으로 먼저 계산한다. Yahoo가 실패하면 의미상 자격이 있는 미국 주식과 크립토에 한해 Alpaca를 먼저 호출한다. 미국 주식 원시 bar는 선·역분할 및 현금배당을 안전하게 조정한 뒤에만 수익률에 넣고, 크립토 bar는 공급자 심볼·기간·통화를 확인한다. Alpaca가 대상이 아니거나 검증에 실패하면 exact Financial identity가 확인된 경우에만 official Wolfram plugin 구조화 결과를 쓴다. Wolfram에서 최근 가격은 검증된 recent-price property를 쓸 수 있지만, 누적 총수익률·MPT·그 밖의 수익률 계산은 오직 `AdjustedClose`로만 한다. `Price`, `LatestTrade`, `Close`, `RawClose`, 렌더링 이미지, 직접 HTTP/SDK/MCP/스크래핑/API 키 경로는 그 대체가 될 수 없다. Alpaca와 Wolfram 자산 가격 폴백 모두 Yahoo의 통화 메타데이터를 대신하지 않는다. FX는 Yahoo를 먼저 쓰고 실패한 통화 다리만 official Wolfram `FinancialData`의 검증된 direct 또는 inverse pair로 대체한다.

“어떤 소식이 있었나”는 Yahoo를 후보 발견에만 사용하고, Yahoo 뉴스가 실패하면 웹 검색으로 후보를 찾는다. 어느 경로든 검색 결과나 제목에서 끝내지 않고 원문 기사, 거래소 공시, 회사 IR, 규제기관 문서를 연다. 열린 일반 출처는 `publisher_verified`, 열린 1차 출처는 `primary_verified`로 구분한다. 가격 변동과 사건의 시간적 근접성만으로 인과관계를 단정하지 않는다. 확인 가능한 시장 보도는 `동시에 보도됨`, 근거가 약한 설명은 `가능한 해석`으로 표현한다.

### 5. 포트폴리오 후보

기본 분석은 주간 수익률, 최소 104개의 공통 관측치, 사용자가 선택한 기준 통화를 사용한다. 서로 다른 통화의 자산을 섞으면 Yahoo가 제공하는 `통화USD=X` 환율 다리로 각 통화 1단위의 USD 가치를 구한 뒤 같은 기준 통화의 가격열을 만든다. 직접 환율이 없으면 `통화=X` 역수를 시도한다. 두 Yahoo 방향이 모두 실패하면 해당 통화만 official Wolfram plugin의 `CCY/USD`를 시도하고, 필요하면 `USD/CCY`를 한 번 역수화한다. Yahoo와 Wolfram 관측치를 한 통화 열 안에서 섞지 않으며 통화별 최종 공급자를 영수증에 남긴다. Wolfram이 별도 원 공급자 주석을 주지 않으면 그 상태를 unavailable로 보존한다. 자산 가격은 임의로 전진 채움하지 않는다. 환율은 공급자와 무관하게 거래일 불일치 보정을 위해 최대 3일까지만 전진 채운다.

여러 종목 중 일부 Yahoo **가격 이력만** 실패하면 성공분을 버리지 않는다. 실패는 stage-aware 영수증을 남기며, `network_error`는 `asset_price` stage로 확인된 경우에만 가격 폴백이다. generic network, `currency_metadata`, 다른 비가격 실패는 자산 대안 경로로 보내지 않는다. `fx_history` 실패는 별도 통화 폴백 요구로 보존한다. 가격 실패 심볼도 Yahoo currency metadata를 가격과 독립적으로 다시 확인하고 자산/기준 통화 FX를 먼저 시도한다. `prepare-portfolio` 워크스페이스에 종목별 Yahoo 가격·통화·FX·오류를 보존한 뒤, 실패 심볼은 의미상 자격이 있으면 Alpaca를 먼저, 그 외 또는 Alpaca 게이트 실패 뒤에는 exact Financial entity가 확인될 때만 Wolfram으로 채운다. 실패 FX 통화는 별도 Wolfram FX 봉투로 채워 `complete-portfolio`를 실행한다. 폴백 정규화 통화는 Yahoo 정규화 통화와 같아야 하며 계산은 Yahoo 원 통화 단위를 권위로 쓴다. 자산마다 최종 가격 공급자는 정확히 하나이고 통화마다 최종 FX 공급자도 정확히 하나다. 필수 종목이나 FX가 하나라도 해결되지 않으면 종목을 조용히 빼지 않고 모든 비중 출력을 막는다.

제시 가능한 결과는 다음 두 개다.

- 동일가중: 성능 비교용 기준선일 뿐, 권고 비중이 아니다.
- 롱온리 최소분산: 최대 종목 비중 제약을 적용한 연구 후보이며 주문 지시가 아니다.

기대수익률 최적화나 최대 샤프 비중은 표본 평균에 매우 민감하므로 기본 출력에 포함하지 않는다. 과거 연율 평균수익률은 예측치가 아니라 설명 통계로 표기한다.

### 5a. U.S. Treasury 무위험수익률 증거

Default risk-free proxy: United States 3-month Treasury bill, ConstantMaturity, Daily, historical series covering the backtest window.

Conversion label: `effective_annual_to_periodic`.

Formula: `(1 + annual_percent / 100)^(1 / periods_per_year) - 1`.

Alignment: 마지막으로 검증된 Treasury 관측치는 미래를 보지 않고 at most three calendar days만 다음 수익률 날짜로 이어질 수 있다.

Failure: 정확한 시리즈, source annotation, 또는 정렬이 없으면 의존 Sharpe, Sortino, and alpha fields remain `null` with `risk_free_rate_unavailable`.

Evidence tiers: exact provider qualifier and typed maturity echoes are `provider_confirmed`. If that query is unavailable but the official plugin explicitly labels or interprets the requested maturity and returns dated Percent observations, a structured LLM semantic binding may produce `provider_labeled_inferred`. Deterministic code uses no substring or regex maturity parser. A lower-confidence Treasury rate input may be used numerically, but curves, interpolation, aligned risk-free rows, Sharpe, Sortino, alpha, backtests, and scenarios must inherit and display `evidence_confidence: lower`, the exact-query failure, and the dependency warning.

Retrieval method: the LLM first classifies country, maturity, security type, due-date basis, frequency, and optional market semantics. ChatGPT then calls only the official Wolfram plugin and evaluates the fixed Treasury `EntityProperty` template with canonical strings such as `3Month`, `1Year`, `2Year`, `5Year`, `10Year`, or `30Year`; `TimeSeriesWindow` limits the requested historical range. A natural-language interpretation is checked, but an ambiguous generic year quantity is replaced by the already classified canonical provider value rather than accepted as an exact maturity. The resulting dated Percent observations, evaluated qualifiers, and source annotation must enter the deterministic envelope validator. WolframAlpha page URLs and `ClashPrefs` may help explain the intended interpretation but are never scraped or used as the numerical data channel.

각 정렬 행에는 공급자 원값 `raw_annual_percent`와 로컬 계산값 `periodic_rate`를 함께 남긴다. 영수증은 `unit`, `retrieved_at`, requested/observed range, `evidence_kind`, missing markers, 그리고 원 Treasury provider/entity/property/maturity/qualifier/source annotation을 담은 `upstream_provenance`를 보존한다. 이 두 값을 함께 남겨야 공급자 관측과 분석 변환을 사후에 분리 검증할 수 있다.

이 변환은 Wolfram 또는 Treasury 공급자가 새 사실을 제공한다는 뜻이 아니라, 공개된 effective annual-to-periodic 분석 관례다. LLM은 required qualifiers와 `Missing`을 구조화 봉투에 보존하고 `treasury-validate`로 검증한다. 요청한 만기가 없으면 nearby maturity로 바꾸지 않으며, 직접 관측 `observation`과 선택적 `linear_maturity_interpolation` 계산을 별개로 표시한다.

### 6. 민감도와 반증

표본 시작일, 일간/주간 빈도, 기준 통화, 최대 비중을 바꾸었을 때 결과가 크게 달라지는지 확인한다. 다음 항목을 명시한다.

- 단일 종목·국가·산업·통화 집중.
- 짧은 상장 이력 또는 공통 관측치 손실.
- 상관관계 급변 가능성.
- 재무지표 누락과 데이터 공급자 한계.
- 투자 논리를 무효화할 사업·재무·규제 조건.

### 7. 백테스트 기본 출력

사용자가 명시적으로 `백테스트`를 요청하면 서술만 반환하지 않는다. 검증된 가격 이력으로 다음 두 결과를 붙여서 기본 출력한다.

1. ChatGPT 기본 빌트인 인터랙티브 누적 총수익률 선형 차트.
2. 차트 바로 아래의 포트폴리오 평가 테이블.

이 스킬과 출력 계약은 ChatGPT Work 클라우드 모드에서만 작동한다. 외부 차트 플랫폼, Plotly, TradingView, ECharts, 별도 웹앱, 커스텀 HTML을 검색·설치·추천·생성하지 않으며 다른 실행 환경용 차트 대체 경로도 만들지 않는다.

차트에는 백테스트 제목, 포트폴리오와 비교지수 이름, 정확한 시작일·종료일, 날짜축, 누적 총수익률축, 범례, 호버 가능한 각 시계열을 표시한다. 모든 시계열은 하나의 공통 최초 유효 관측일에 `0%`로 시작한다. 누적 총수익률·MPT·그 밖의 수익률 계산에는 검증된 조정 총수익률 가격만 사용하며, Wolfram 공급자의 경우에는 반드시 `AdjustedClose`다. 실제 배당 재투자 처리·기준 통화·리밸런싱 규칙·관측 빈도·표본 기간을 차트 주변에 적는다. 화면 가독성을 위해 주간 마지막 관측치로 표시할 수 있지만, 평가 지표는 화면용 다운샘플이나 차트 픽셀이 아니라 명시된 검증 수익률 시계열로 계산한다.

사용자가 비교지수를 지정하면 모두 포함한다. 지정하지 않으면 LLM이 포트폴리오의 주 시장·자산 유형·기준 통화를 의미적으로 판단해 관련성이 높은 투자 가능한 광범위 시장 비교지수를 최대 두 개 선택하고, 그 선택을 가정으로 밝힌다. 국가 allowlist, 티커 접미사, 정규식, 고정 별칭 표로 비교지수를 선택하지 않는다. 비교지수도 다른 종목과 같은 티커 확인·가격·통화·FX 게이트를 통과해야 한다. 검증된 비교지수가 없으면 포트폴리오 단독 차트를 만들고 비교지수 의존 지표를 사유와 함께 `null`로 둔다.

평가 테이블은 행에 지표, 열에 차트에 표시된 포트폴리오와 비교지수를 놓고 다음 순서를 유지한다.

1. 누적수익률
2. 연환산 수익률
3. 연환산 변동성
4. 샤프지수
5. 소르티노지수
6. 최대낙폭(MDD)
7. 주 비교지수 기준 베타
8. 주 비교지수 상관계수
9. 연환산 알파

표 제목 또는 주석에서 주 비교지수를 식별한다. 샤프·소르티노·알파에는 기본 3-month Treasury bill `ConstantMaturity` `Daily` 역사 증거가 통과한 경우에만 위 `effective_annual_to_periodic` 변환을 사용하고, 값·출처·기준일·계산 규칙을 명시한다. 필요한 값이 없으면 임의의 무위험수익률이나 비교지수 통계를 만들지 않고 `null`과 `risk_free_rate_unavailable` 사유를 남긴다.

백테스트와 MPT 최적화의 데이터 게이트는 별개다. 사용자가 요청한 1년 같은 짧은 구간이 기본 104주 MPT 게이트에 못 미쳐도 가격 이력이 백테스트 계산에 충분하면 차트와 평가표를 출력할 수 있다. 다만 독립적인 MPT 게이트가 실패한 상태에서 최적화 비중을 출력하지 않는다. 백테스트 결과만으로 투자 적합성이나 미래 수익을 암시하지 않는다.

## 출력 규율

상담 결과에는 데이터 기준시각, 가격 공급자, 가격 조정 여부, 기준 통화, 표본 구간, 관측치 수, 누락 필드, 출처 역할을 적는다. 사용자의 실제 제약이 없는 경우 “가능한 연구 후보”까지만 말하고 “지금 몇 퍼센트를 사라”는 문장으로 넘어가지 않는다.
