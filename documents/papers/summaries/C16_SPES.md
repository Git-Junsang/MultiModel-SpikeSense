# C16: SPES

원문: `C16_SPES_ICDE2024.pdf`
Cheryl Lee, Zhouruixing Zhu, Tianyi Yang, Yintong Huo, Yuxin Su, Pinjia He, Michael R. Lyu, IEEE ICDE 2024, pp. 165–178, DOI 10.1109/ICDE60146.2024.00020(OpenAlex 기준. 받은 PDF는 arXiv 2403.17574v2라 DOI가 없다)
읽은 범위: 원문 전체

## 한 줄 요약

Serverless function을 호출 간격 수열에 따라 유형(always warm, regular, appro-regular, dense, successive와 보조 유형 셋)으로 나누고 유형마다 다른 규칙으로 instance를 미리 올리고 내리는 SPES를 제안했다. Azure trace simulation에서 75번째 백분위 cold start rate를 가장 좋은 비교 방식(Defuse)의 0.215에서 0.108로 49.77% 줄였다.

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | 고정 keep-alive나 호출 간격 histogram만 쓰는 방법은 trigger가 만드는 호출 유형을 보지 않는다. 그래서 드물게 호출되는 function의 cold start를 줄이지 못하고 메모리를 낭비한다(§I) |
| 방법 | 1분 slot마다 호출 수를 보고 호출이 없는 연속 slot 수(waiting time, WT)의 수열을 만든다. 쉬운 유형부터 정의에 맞춰 보고 처음 맞는 유형으로 나눈다(§IV, §IV-A, Table I) |
| 방법 | 주기 호출 유형: regular는 WT의 95번째와 5번째 백분위 차가 1 이하이거나 WT의 CV가 0.01 이하이고 예측값은 WT 중앙값이다. 맞지 않으면 첫·마지막 WT를 빼고 다시 본다. 그래도 아니면 mode에 가까운 WT 옆의 작은 WT들을 합친다. Appro-regular는 상위 n개 WT mode의 출현 수가 수열 길이의 90% 이상이고 예측값은 그 mode들이다(§IV-A2, §IV-A3) |
| 방법 | 예측 호출 시각은 마지막 호출 시각 + 예측값이다. 지금 시각 t에 예측 시각이 [t − θprewarm, t + θprewarm] 안이면 미리 올린다. 지금 WT가 θgivenup 이상이면 내린다. θprewarm = 2, θgivenup은 dense·pulsed가 5이고 나머지는 1이다. 예측값은 online으로 고친다. 정의에 맞지 않는 function은 같은 application·user의 function과 T-lagged co-occurrence rate(0.5 이상, T ≤ 10)로 잇는다(§IV-B–D, Algorithm 1, §V-A2) |
| 가정·조건 | Azure Functions 공개 trace(분 단위 호출 수 14일. 앞 12일로 유형을 정하고 뒤 2일로 simulation). 실행은 모두 1분 안에 끝나고 cold start 지연은 모두 같다고 둔다. Node 하나가 모든 instance를 담는다고 보아 메모리 한도가 없다. Deadline이 없다(§V-A, §VI-A) |

## 결론

- Simulation: 75번째 백분위 cold start rate가 Defuse의 0.215에서 0.108로 49.77% 줄었고 다른 비교 방식보다 64.06–89.20% 낮다. Cold start가 없는 function은 57.99%다(비교 방식은 25.61–52.59%)(§V-B, Fig. 8)
- 낭비 메모리 시간(WMT)은 비교 방식보다 10.89–63.50%, Defuse보다 57.06% 적다. 메모리 사용은 고정 keep-alive(10분)보다 8.08% 많고 다른 비교 방식보다 평균 36.07–55.55% 적다(§V-B, §V-C1, Fig. 9(a), Fig. 11(a))
- 데이터 분석: timer trigger function의 68.12%가 주기 또는 준주기로 호출된다(KS 검정, 호출 수가 모자란 6.65% 제외)(§III-B1)
- 평가 방식: Azure trace로 돌린 simulation(8-core Intel i5-3470S, 16 GB workstation)

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| 주기로 쓰이는 대상의 다음 사용 시각을 예측해 직전에 올린다 | SPES는 지난 WT의 중앙값이나 mode로 주기를 추정하고 1분 slot 단위로 판단한다. PNU-Count는 queue, 모델 그룹 지연 분포, 추론 요청별 지연 분포, n_expect로 32 ms 주기 안의 다음 사용 시각을 예측한다 | [구조] 주기(32 ms)와 모델별 offset(O_m = m × 0.8 ms)을 Host가 정하므로 지난 간격에서 주기를 추정하지 않는다. 분포는 nominal frame 끝 시각보다 늦어지는 폭만 맡는다. n_expect로 이번 주기에 남은 추론 요청 수를 안다 |
| 올리고 내리는 것을 다음 사용 예측으로 정한다 | SPES는 메모리 한도 없이 function마다 따로 정하고 θgivenup이 지나면 자리가 남아도 내린다. PNU-Count는 entry 4개가 모자랄 때 후보끼리 다음 사용 예측을 비교해 가장 늦게 쓸 모델 하나를 내보낸다 | 없음. 목표가 다르다. SPES는 cold start와 낭비 메모리 시간을 줄이고 이 연구는 BRAM이 정해진 상태에서 DDR3 traffic을 줄인다 |

## 인용할 때

- Lee 등이 먼저 했다: 호출 간격으로 function을 주기·준주기 등 유형으로 나누고 유형별 예측값(WT 중앙값, mode)으로 다음 호출 직전에 instance를 올리는 것. 주기 대상의 다음 사용을 예측해 미리 올리는 것은 신규성으로 주장하지 않는다. Prefetch와 다음 사용 시점 교체 원리 자체도 주장하지 않는 범위다(09 §3)
- 근거 위치: 주기 호출 관찰 §III-B1, 유형 정의 Table I와 §IV-A(regular §IV-A2, appro-regular §IV-A3), 보조 유형 §IV-B, 적응 §IV-C, 올리고 내리는 규칙 §IV-D와 Algorithm 1, 매개변수 §V-A2, 결과 §V-B Fig. 8–10과 §V-C Fig. 11·12, 가정 §V-A와 §VI-A
- 주의: 초록의 WMT 감소 56.43%와 §V-C의 Defuse 대비 57.06%가 다르다. §I의 13.51–64.58%와 §V-C의 10.89–63.50%도 다르다. 인용할 때는 §V 값과 비교 대상을 함께 적는다
- 주의: 비교 방식(FaaSCache, Defuse, Hybrid(C12), 고정 keep-alive)은 공개 code가 없다며 저자가 다시 구현했다. FaaSCache(C17)의 메모리 한도는 SPES가 simulation에서 쓴 최대 메모리로 두었다(§V-A1). C17 원문에는 code 공개 위치가 있다
- 주의: "the first differentiated scheduler"는 저자 주장이다(초록, §I)
- 비교군: 옮기지 않았다. 지금 cache 비교(LRU, offset-only, PNU-Count, Oracle MIN)에는 없다
