# C28: INFless

원문: `C28_INFless_ASPLOS2022.pdf`
Yanan Yang, Laiping Zhao, Yiming Li, Huanyu Zhang, Jie Li, Mingyang Zhao, Xingzhen Chen, Keqiu Li, ACM ASPLOS 2022, pp. 768–781, DOI 10.1145/3503222.3507709
읽은 범위: 원문 전체(부록 A 포함). 그림의 막대 값은 본문에 적힌 것만 옮겼다

## 한 줄 요약

추론용 serverless platform 안에 instance마다 batch queue를 두고 batch 크기와 CPU·GPU 할당을 함께 고른다. Pre-warm·keep-alive window는 짧은 기간(1시간)과 긴 기간(1일)의 idle time histogram을 섞은 LSTH로 정한다. GPU 서버 8대 실측에서 최대 RPS가 OpenFaaS+의 5.2배, BATCH의 2.6배였다(§5.2, Fig. 11).

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | 상용 serverless(AWS Lambda)는 가속기가 없고 request 하나에 instance 하나를 쓴다. Platform 위에 얹은 묶음 처리(OTP 설계, BATCH)는 platform 안의 scheduling 지연과 queue 시간을 모르고 자원 구성을 함께 고르지 못한다(§2.2, Observation 1–5) |
| 방법 | built-in non-uniform batching: instance마다 batch queue가 있고 request는 batch가 차거나 timeout이 될 때까지 기다린다. Latency l = t_cold + t_batch + t_exec가 SLO를 넘지 않도록 instance별 도착률을 [r_low, r_up] 안에 둔다. r_up = ⌊1/t_exec⌋ × b, r_low = ⌈1/(t_slo − t_exec)⌉ × b이고 t_exec ≤ t_slo/2여야 한다(§3.2, Eq. 1) |
| 방법 | operator profile을 합쳐(순차는 합, 병렬은 최댓값) batch·자원 구성별 실행 시간을 예측한다. 평균 오차는 10% 미만이고 예측값에 10%를 더해 쓴다(§3.3, Fig. 8). 자원 최소화 문제(Eq. 2–9)는 큰 batch 크기부터 시도하는 greedy 알고리즘으로 푼다(§3.4, Algorithm 1) |
| 방법 | LSTH: 함수마다 짧은 기간과 긴 기간의 idle time histogram을 둔다. 각각 5번째 백분위로 pre-warm window, 99번째 백분위로 keep-alive window를 구하고 가중합 γL + (1 − γ)S(기본 γ = 0.5)를 쓴다. 과거 최고 도착률을 넘는 급증에서는 cold start를 피하지 못한다(§3.5, Fig. 9) |
| 가정·조건 | OpenFaaS 위에 Golang 약 9,300줄로 구현했고 TensorFlow Serving과 CUDA MPS를 쓴다(§4). 시험 cluster는 서버 8대, RTX 2080Ti 16개다. 응용은 OSVT(SSD·MobileNet·ResNet-50, SLO 200 ms)와 Q&A robot(TextCNN-69·LSTM-2365·DSSM-2389, SLO 50 ms)이고 batch 크기는 32 이하, 도착은 Azure Functions trace(7일)다. 대규모 평가는 서버 2,000대 simulation이다(§5.1) |

## 결론

- 일정 부하에서 최대 RPS는 OpenFaaS+의 5.2배, BATCH의 2.6배였다. Azure trace 세 종류(sporadic, periodic, bursty)에서 자원당 처리량은 BATCH의 1.8–2.6배였다(§5.2, Fig. 11–12). Batch를 끄면(batch 크기 1) 처리량이 OSVT 45.6%, Q&A robot 60% 줄어 구성요소 가운데 영향이 가장 컸다(Fig. 11)
- SLO 위반율은 평균 3.1% 이하였고 batch queue 시간은 실행 시간과 비슷하게 유지됐다(§5.2, Fig. 15)
- LSTH(긴 기간 24시간, 짧은 기간 1시간)는 HHP(Shahrad 등의 hybrid histogram policy, C12)보다 cold start 비율이 21.9% 낮고 idle 자원 낭비가 24.3% 적었다(§5.2, Fig. 16)
- 평가 방식: GPU 서버 8대 cluster 실측과 서버 2,000대 simulation. Simulation은 호출을 실행하지 않고 scheduling 결정과 이론 처리량 상한만 센다(§5.1)

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| 같은 대상(함수, 모델)의 추론을 batch로 묶어 한 번 올린 자원과 weight로 처리한다 | INFless는 batch가 차거나 timeout이 될 때까지 기다리고 instance마다 batch 크기 b를 정한다. Scheduling 제약은 batch 대기 시간을 실행 시간 이상, t_slo − t_exec 이하로 둔다(Eq. 3–4). Grouping은 이미 도착한 같은 모델 추론 요청만 묶고 기다리지 않는다. 함께 도착하게 하는 일은 Host의 Offset Assignment가 맡는다 | [구조] batch를 채우려고 기다리는 시간이 response time에 들어가지 않는다 |
| 과거 도착 기록으로 다음 사용을 예측해 미리 올리거나 남겨 둔다 | LSTH는 함수별 idle time 분포의 백분위로 분 단위 window 두 개를 정하고 keep-alive window가 지나면 instance를 내린다. PNU-Count는 queue, 모델 그룹 지연 분포, 추론 요청별 지연 분포, `n_expect`로 ms 단위 다음 사용 시각을 예측하고 entry 4개가 모자랄 때 가장 늦게 쓸 모델 하나를 내보낸다(04 §3.1) | 없음. 시간 규모와 목표가 다르다. LSTH는 cold start와 idle 자원을 줄이고 이 연구는 정해진 BRAM에서 DDR3 traffic을 줄인다 |
| 묶음 처리와 예측 적재를 한 시스템에 둔다 | INFless에서 batch 크기·자원·도착률 배분은 auto-scaling engine이, pre-warm·keep-alive는 LSTH가 정한다. LSTH의 입력은 idle time이고 batch queue 상태를 쓴다는 서술은 없다(§3.1, §3.5). 이 연구는 Grouping이 쓰는 queue를 PNU-Count도 본다. Queue에 추론 요청이 있는 모델의 다음 사용은 지금이고 다음 batch의 모델은 연산 중에 prefetch한다(04 §3) | [구조] Offset Assignment가 정한 nominal 도착 시각을 batch 형성과 cache 예측이 함께 기준으로 쓴다. INFless는 도착 pattern을 바꾸지 않고 trace 그대로 받는다 |

## 인용할 때

- Yang 등이 먼저 했다: 추론 serverless platform 안에 batch queue를 넣고 batch 크기와 CPU·GPU 자원을 함께 고르는 것, 묶음 처리와 idle time histogram 기반 pre-warm·keep-alive를 한 시스템에 합친 것. 저자는 INFless를 첫 ML 전용 serverless platform이라고 적었다(초록, §1). 묶음 처리와 예측 적재를 한 시스템에 두는 것 자체는 신규성으로 주장하지 않는다. 같은 모델 추론 요청을 묶는 것과 기다려 묶기도 주장하지 않는 범위다(09 §3)
- 근거 위치: 상용 platform 관찰 §2.2(Fig. 2–3), 도착률 범위 §3.2(Eq. 1), operator profiling §3.3(Fig. 7–8), scheduling §3.4(Eq. 2–10, Algorithm 1), LSTH §3.5(Fig. 9), 구현 §4, 실험 §5(Fig. 11–18, Table 3–4)
- 주의: cold start 감소를 §5.2 소제목은 20%, 본문과 §1은 21.9%라고 적었다. 초록의 2–5배는 OpenFaaS+와 BATCH 비교를 합친 범위다
- 주의: 비교군은 저자가 OpenFaaS 위에 다시 만들었다. OpenFaaS+는 GPU를 더하고 keep-alive를 300초로 고정했고 BATCH는 CPU·GPU profile을 더했다(§5.1)
- 주의: LSTH는 Shahrad 등의 HHP(C12)와 같은 idle time histogram·백분위(5·99번째) 방식을 짧은 기간과 긴 기간에 따로 쓰고 가중합한다(§3.5)
- 비교군: 옮기지 않았다. 지금 scheduler 비교(Dysta Method, DeepRT Method)와 cache 비교(LRU, offset-only, PNU-Count, Oracle MIN)에는 없다
