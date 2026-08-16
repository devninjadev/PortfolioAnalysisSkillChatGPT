# 시장 범위와 실데이터 검증 목록

## 지원 정책

이 목록은 허용 목록이 아니다. Yahoo 후보 검색, 최근 가격 검증, 통화 메타데이터, 필요한 FX 이력, 공통 수익률 행렬이 모두 성공하면 다른 거래소와 통화도 분석할 수 있다. 처음 보는 시장은 먼저 작은 스모크 테스트를 실행하고, 실패하면 가능한 이유와 실패 게이트를 그대로 보고한다.

## 2026-08-10 로컬 검증 완료

| 시장 | 예시 티커 | 거래소 | Yahoo 통화 단위 | 포트폴리오 환율 다리 |
|---|---|---|---|---|
| 미국 | `AAPL` | NASDAQ | USD | 불필요 또는 기준통화 FX |
| 한국 | `005930.KS` | KRX | KRW | `KRWUSD=X` |
| 일본 | `7203.T` | Tokyo | JPY | `JPYUSD=X` |
| 홍콩 | `0700.HK` | Hong Kong | HKD | `HKDUSD=X` |
| 중국 본토 | `600519.SS` | Shanghai | CNY | `CNYUSD=X` |
| 독일 | `SAP.DE` | Xetra | EUR | `EURUSD=X` |
| 영국 | `SHEL.L` | London | GBp → GBP | `GBPUSD=X` |
| 스위스 | `NESN.SW` | Swiss | CHF | `CHFUSD=X` |
| 캐나다 | `SHOP.TO` | Toronto | CAD | `CADUSD=X` |
| 호주 | `BHP.AX` | ASX | AUD | `AUDUSD=X` |
| 인도 | `RELIANCE.NS` | NSE | INR | `INRUSD=X` |
| 대만 | `2330.TW` | Taiwan | TWD | `TWDUSD=X` |
| 브라질 | `PETR4.SA` | São Paulo | BRL | `BRLUSD=X` |

첫 8개 시장은 2021-01-01 이후 KRW 기준 주간 공통 수익률 279개로 하나의 포트폴리오 계산을 완료했다. 캐나다·호주·인도·대만·브라질은 같은 시작일의 USD 기준 주간 공통 수익률 281개로 별도 계산을 완료했다. 이는 당시 데이터 경로의 작동 증거이지 향후 가용성 보장은 아니다.

## 새 시장 시도 절차

1. 사용자 표현과 LLM이 만든 공식명·현지명·로마자명·코드 변형을 `search`에 넣는다.
2. 후보의 이름, 국가, 거래소, 보통주/우선주/ADR/ETF 여부를 의미적으로 비교한다.
3. 선택한 심볼이 후보 집합에 있는지 확인하고 `validate`로 최근 가격·통화를 검증한다.
4. 두 종목 이상의 작은 포트폴리오로 자산 가격, FX 다리, 공통 관측치 계산을 확인한다.
5. 성공 영수증이 있을 때만 “검증 완료”로 표기한다. 일부 단계만 성공하면 “시도 가능, 미검증”으로 남긴다.

Yahoo 검색이 현지어를 받지 못할 수 있다. 예를 들어 `삼성전자` 단독 검색은 빈 결과였지만 `Samsung Electronics`와 `005930` 변형을 함께 사용하면 `005930.KS`가 후보로 반환됐다. 이는 하드코딩 별칭표가 아니라 LLM 기반 의미 변형을 쓰는 이유다.

## 2026-08-15 Alpaca 대안 경로 검증

이 표도 허용 목록이 아니라 실제 도구 응답으로 확인한 경로의 영수증이다. Yahoo 가격 실패가 먼저 있어야 하며, 실행 시점의 자산 상태·피드·보존 기간은 다시 확인한다.

| 의미 클래스 | Yahoo 심볼 | Alpaca 심볼 | 실검증 결과 | 적용 규칙 |
|---|---|---|---|---|
| 미국 주식 | `AAPL` | `AAPL` | 활성 `us_equity`, NASDAQ, IEX 주간 bar와 기업행동 조회 성공 | 원시 bar에 기업행동 조정 후 사용 |
| 크립토 | `BTC-USD` | `BTC/USD` | 미국 크립토 피드 주간 bar 조회 성공 | 정확한 슬래시 심볼을 응답에서 확인 |
| 한국 주식 | `005930.KS` | 없음 | Alpaca 자산 조회에서 찾을 수 없음 | Alpaca 호출 대상이 아니며 Yahoo 실패 유지 |

실제 AAPL 주간 원시 bar는 2020년 4대1 액면분할 경계에서 약 `499.345`에서 `121.11`로 불연속이었다. 따라서 미국 주식 폴백은 기업행동 응답 없이 절대 포트폴리오 수익률에 들어가지 않는다. BTC/USD는 기업행동 조정을 요구하지 않지만, Yahoo의 통화 메타데이터와 필요한 FX 이력은 계속 별도로 통과해야 한다.

## 2026-08-16 Wolfram 대안 경로 검증

아래는 영구 지원 목록이 아니라 2026-08-16에 official Wolfram plugin의 구조화 결과와 source annotation으로 확인한 **dated canary**다. 실제 분석에서는 Yahoo 실패·정확한 entity·property·기간·source annotation·Yahoo FX 게이트를 다시 검증하며, 이 표의 결과를 미래 가용성 약속이나 허용 목록으로 사용하지 않는다.

- **dated canary — 금융 adjusted history:** AAPL은 `Entity["Financial", "NASDAQ:AAPL"]`로 해석됐고, 날짜가 있는 USD `AdjustedClose` 시계열을 반환했다.
- **dated canary — 금융 source annotation:** 위 AAPL adjusted series의 Wolfram source annotation에는 Finnhub Stock API와 Nasdaq Data Link가 이름으로 남았다.
- **dated canary — 명목 미국 국채 constant-maturity history:** 1개월, 3개월, 6개월, 1년, 2년, 3년, 5년, 7년, 10년, 20년, 30년의 daily constant-maturity history가 2025-01-02부터 2026-08-13까지 404개 관측치로 반환됐다.
- **dated canary — 현재 미국 국채 수준:** 5년 및 10년 TIPS, 3개월 `AuctionAverage` bill, 3개월 `SecondaryMarket` bill 현재값이 반환됐다.
- **dated canary — Treasury source annotation:** Treasury property의 source annotation은 FRED at the Federal Reserve Bank of St. Louis를 이름으로 표시했다.
- **dated canary — unavailable maturity:** 2026-08-16 probe returned `Missing` for 2-month and 4-month constant-maturity maturities; later availability is unverified and must be rechecked. 요청 시 nearby maturity로 대체하지 않는다.

## 2026-08-16 later release verification — Treasury unavailable

이 절은 같은 날짜의 위 성공 canary보다 **명확히 나중에 수행한 release-verification pass**의 최신 상태다. 조회일은 2026-08-16이며, 앞선 성공 결과는 해당 시점과 해당 Wolfram property/qualifier query shape에서만 유효한 **historical evidence**다. earlier successful probes are historical only: 재현할 때는 원 요청의 entity, property, 전체 qualifier, 요청 범위, 실제 retrieval timestamp를 모두 새 영수증에 남겨야 하며 현재 가용성 근거로 승격하지 않는다.

최신 pass에서는 다음 exact query-shape canary를 다시 요청했다.

- same-date nominal **exact-maturity curve** points;
- **10-year nominal history**;
- exact-maturity **TIPS history**;
- 3-month **AuctionAverage bill** evidence;
- 3-month **SecondaryMarket bill** evidence.

These canaries all returned `Missing[NotAvailable]`. 따라서 **Treasury lane was not operational at release-verification time**. 곡선, 10년 명목, TIPS, 경매평균, 유통시장 중 어느 lane도 release 시점 작동으로 주장할 수 없고, 다른 maturity·market·security type으로 대체해서도 안 된다. 이후 실제 요청은 새 plugin 호출과 완전한 requested/provider-observed qualifier 영수증을 요구한다.

## 2026-08-17 Wolfram FX and canonical Treasury canaries

아래 역시 실행 시점 영수증인 **dated canary**이며 미래 가용성 약속이나 허용 목록이 아니다.

- Official Wolfram plugin의 `FinancialData["KRW/USD", …]`와 `FinancialData["EUR/USD", …]`는 2026-08-03부터 2026-08-14까지 각각 10개의 날짜별 환율 관측치를 반환했다. 값은 각 통화 1단위의 USD 가치로 해석되는 direct pair였다.
- 이 FX TimeSeries의 별도 원 공급자 source annotation과 `MetaInformation`은 제공되지 않았다. 따라서 영수증은 `Wolfram FinancialData`/official-plugin channel만 확인하고 underlying source annotation은 unavailable로 보존한다.
- 2026-08-16의 실패는 `MaturityDuration`을 잘못된 일반 수량 형태로 넣었던 query-shape에 한정된 historical receipt다. 2026-08-17 재검증에서는 `"3Month"`, `"1Year"`, `"2Year"`, `"5Year"`, `"10Year"`, `"30Year"` canonical strings와 각각 `Bill`, `Note`, `Bond`를 넣은 **structured canonical-string query**가 모두 성공했다. 따라서 앞선 “Treasury lane was not operational” 결론은 그 당시 query-shape에만 유효하며 현재 운영 판단을 지배하지 않는다.
- `\[FreeformPrompt]["United States", "Country"]`로 국가 entity를 확인하고, exact `EntityProperty["Country", "Treasury", ...]`를 평가한 뒤 `TimeSeriesWindow`로 2026-08-03~2026-08-14 요청 범위를 잘랐다. 반환된 마지막 날짜는 2026-08-13이었으며 여섯 만기 모두 날짜가 있는 Percent 관측치를 **각 9개** 반환했다.
- 2026-08-13 관측치는 3개월 3.87%, 1년 3.97%, 2년 4.15%, 5년 4.32%, 10년 4.63%, 30년 5.21%였다. 각 exact structured evaluation은 요청한 만기·증권종류와 일치하므로 완전한 envelope 검증을 거쳐 `provider_confirmed` 후보가 된다.
- 3개월과 10년 natural-language query는 canonical maturity를 정확히 해석했다. 1년·2년·5년·30년 natural-language query는 일반 `Quantity`로 모호하게 해석되어 `Missing`이었지만, 같은 의도를 canonical string으로 고정한 structured query는 정상 데이터를 반환했다. 따라서 자연어 실패를 데이터 부재로 오판하지 않고 exact structured template을 사용한다.
- Treasury property의 source annotation은 `FREDII`를 반환했다. 영수증에는 이 provider source entity를 그대로 보존하며, 화면 URL이나 `ClashPrefs`를 값의 출처로 쓰지 않는다.

이 성공 경로는 웹페이지 스크래핑, OCR, nearby maturity 대체가 아니다. 사용자가 제공한 URL의 `ClashPrefs`는 올바른 canonical interpretation을 확인하는 단서였을 뿐이며, 실제 값은 official plugin의 구조화 evaluator 결과에서 얻었다. 미래 호출에서 exact structured evaluation이 실패하고 labeled result만 남는 경우에는 기존 `provider_labeled_inferred` 하위 tier를 사용할 수 있지만, 그때는 모든 의존 계산에 lower confidence를 전파한다.
