# C12: Serverless in the Wild

원문: `C12_ServerlessInTheWild_ATC2020.pdf`
Mohammad Shahrad, Rodrigo Fonseca, Íñigo Goiri, Gohar Chaudhry, Paul Batum, Jason Cooke, Eduardo Laureano, Colby Tresness, Mark Russinovich, Ricardo Bianchini, USENIX ATC 2020, pp. 205–218, DOI 없음(USENIX 공개본. ISBN 978-1-939133-14-4)
읽은 범위: 원문 전체

## 한 줄 요약

Azure Functions 전체의 invocation 기록을 분석하고 application마다 idle time 분포로 pre-warming window와 keep-alive window를 정하는 hybrid histogram policy를 제안했다. Simulation에서 10분 고정 keep-alive는 같은 메모리를 쓰는 hybrid policy보다 cold start가 약 2.5배 많았다(75번째 백분위 application, histogram 범위 4시간).

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | 고정 keep-alive(AWS 10분, Azure 20분)는 application마다 다른 invocation 간격을 보지 않아 cold start가 많고 메모리도 낭비한다(§1, §2) |
| 방법 | 실행이 끝나면 application을 내리고 pre-warming window가 지나면 다시 올려 keep-alive window 동안 둔다. Pre-warming window가 0이면 내리지 않는다(§4, Fig. 9) |
| 방법 | application마다 idle time(실행이 끝나고 다음 invocation까지)의 histogram을 1분 bin으로 둔다. 범위(예: 4시간)를 넘는 값은 범위 밖(OOB)으로 센다. 5번째 백분위로 pre-warming window를, 99번째 백분위로 keep-alive window를 정하고 10% margin을 둔다(§4.2, Fig. 11) |
| 방법 | bin count의 CV가 2보다 작거나 idle time 표본이 적으면 고정 keep-alive(pre-warming 0, keep-alive = histogram 범위)로 돌아간다. OOB가 많은 application은 ARIMA로 다음 idle time을 예측하고 15% margin을 둔다(§4.2, Fig. 10) |
| 가정·조건 | 2019년 7월 15–28일 Azure Functions 전체의 function별 invocation 수(1분 bin). 결정 단위는 application이다. 메모리 한도 없이 application마다 따로 정하고 deadline이 없다(§3.1, §4.2, §7) |

## 결론

- Simulation(trace 첫 1주): 10분 고정 keep-alive는 같은 메모리를 쓰는 hybrid policy(범위 4시간)보다 75번째 백분위 application의 cold start가 약 2.5배 많았다. 2시간 고정 keep-alive는 cold start가 비슷했고 메모리를 약 50% 더 썼다(§5.2, Fig. 15)
- 5·99번째 백분위 cutoff는 cutoff가 없을 때보다 낭비 메모리 시간을 15% 줄였고 cold start는 눈에 띄게 늘지 않았다. ARIMA를 더하면 cold start 비율이 100%인 application이 전체의 10.5%에서 5.2%로 줄었다(§5.2, Fig. 16·19)
- OpenWhisk 실측(VM 19대, application 68개, 8시간): 10분 고정 keep-alive보다 worker container 메모리가 평균 15.6% 적었다. Policy가 더한 지연은 평균 835.7 µs였다(§5.3)
- 평가 방식: Azure trace로 돌린 simulation과 OpenWhisk 실측

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| 관측한 시간 분포로 다음 사용 시각을 예측한다 | hybrid policy는 idle time 분포의 백분위로 분 단위 window 두 개를 정한다. PNU-Count는 nominal offset이 지난 뒤 경과 시간에 맞춰 모델 그룹 지연 분포에서 남은 지연을 구하고 추론 요청별 지연은 Uniform(0, J)로 본다 | [구조] Host가 모델마다 offset을 정하므로(Model-Grouped Offset Assignment) 다음 사용 시각의 기준이 정해져 있다. 분포는 그 기준보다 늦어지는 폭만 맡는다. Host가 추론 요청 packet에 n_expect를 실어 FPGA가 남은 추론 요청 수를 센다 |
| 다시 쓰일 때까지 메모리에 둘지 다음 사용 예측으로 정한다 | hybrid policy는 자리가 필요 없어도 미리 내리고 application마다 따로 정한다(§7). PNU-Count는 entry 4개가 모자랄 때 후보끼리 다음 사용 예측을 비교해 가장 늦은 모델 하나를 내보낸다 | 없음. 목표가 다르다. Hybrid policy는 cold start와 낭비 메모리 시간을 줄이고 이 연구는 BRAM이 정해진 상태에서 DDR3 traffic을 줄인다 |

## 인용할 때

- Shahrad 등이 먼저 했다: 대상마다 idle time 분포로 미리 올릴 시점(pre-warming)과 둘 시간(keep-alive)을 정하는 정책. 분포로 다음 사용을 예측해 미리 적재하는 것은 신규성으로 주장하지 않는다. Prefetch와 다음 사용 시점 교체 원리 자체도 주장하지 않는 범위다(09 §3)
- 근거 위치: window 정의 §4 첫머리와 Fig. 9, histogram·백분위·margin §4.2 "Range-limited histogram"과 Fig. 11, CV 판정과 ARIMA §4.2, cache와 다른 점 §4.2 "Justification"과 §7 "Cache management", 결과 §5.2 Fig. 14–19와 §5.3 Fig. 20
- 주의: cold start 수치는 application별 cold start 비율의 75번째 백분위다(§5.2). Simulation은 낭비 메모리 시간을 크게 잡으려고 실행 시간을 0으로 두고 application 메모리를 모두 같게 둔다(§5.1)
- 주의: 15.6%는 trace 전체가 아니라 OpenWhisk의 application 68개, 8시간 값이다. 같은 실험의 실행 시간 감소(평균 32.5%, 99번째 백분위 82.4%)는 warm container에서 언어 runtime 기동이 빠지는 OpenWhisk의 부수 효과다(§5.3)
- 주의: Azure Functions 구현은 HTTP trigger application부터 단계적으로 배포한다고만 적었다. Production 결과는 없다(§6)
- 비교군: 옮기지 않았다. 지금 cache 비교(LRU, offset-only, PNU-Count, Oracle MIN)에는 없다
