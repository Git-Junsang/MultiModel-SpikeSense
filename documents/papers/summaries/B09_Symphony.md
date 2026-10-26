# B09: Symphony

원문: `B09_Symphony_deferred_batching.pdf`
Lequn Chen, Weixin Deng, Anirudh Canumalla, Yu Xin, Danyang Zhuo, Matthai Philipose, Arvind Krishnamurthy, arXiv:2308.07470v2(2024-02-28), 게재 학회 확인 못 함, DOI 확인 못 함
읽은 범위: 원문 전체(부록 A–D 포함)

## 한 줄 요약

추론 요청 하나를 더 넣으면 deadline을 넘기는 시각(frontrun)까지 batch 실행을 일부러 미뤄 batch를 키운다. GPU cluster에서 같은 GPU 수로 goodput이 최대 5배였고 같은 부하에서 GPU가 최대 60% 적게 들었다(§1, §8).

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | 기존 serving system은 GPU가 놀면 바로 batch를 보내(eager) batch가 작고 throughput이 낮다. 부하가 낮아도 GPU를 모두 써 auto-scaling이 어렵다(§2.2–2.3) |
| 방법 | batch 실행 시간을 `ℓ(b) = αb + β`로 둔다(§2.1). Batch 크기 b, deadline d일 때 frontrun `d − ℓ(b + 1)`부터 latest `d − ℓ(b)` 사이에만 batch를 보낸다. Frontrun 전에는 보내지 않는다(§3.1, Fig. 3) |
| 방법 | 모델마다 queue와 후보 batch(추론 요청 집합, 실행 시각, latest)를 둔다. GPU가 비면 latest가 가장 가까운 후보를 고른다. 번호가 작은 GPU부터 써서 남는 GPU를 비워 둔다(§3.2, Algorithm 1) |
| 방법 | deadline을 넘길 추론 요청은 버린다(부록 D, Fig. 18). 중앙 scheduler와 RDMA로 초당 수백만 추론 요청을 처리한다(§4.2–4.3) |
| 가정·조건 | GPU cluster. 모델 37개 mixed zoo, SLO 20–400 ms(§5.1). Sub-cluster의 GPU에는 그 sub-cluster의 모델을 모두 미리 올리고 몇 분마다 다시 나눈다(§4.1, §4.4). 도착은 따로 적지 않으면 Poisson이다(§5). Goodput은 모델마다 p99 latency가 SLO 안인 최대 throughput이다(§2.1) |

## 결론

- 모델 37개 mixed에서 Clockwork, Nexus, Shepherd의 2.0–2.4배 goodput을 냈다. Batching 효과가 큰 모델만 두면 1080Ti 3.5배, A100 5.7배였다. 효과가 작은 모델에서는 1080Ti 23%, A100 10% 높았다(Fig. 9, §5.1)
- 15k RPS를 처리하는 데 Nexus와 Shepherd는 Symphony보다 GPU가 166%, 90% 더 필요했다(mixed, emulated A100, Fig. 10, §5.2)
- Timeout 방식은 모델 하나일 때 가장 좋은 timeout으로 deferred batch scheduling과 같은 goodput을 냈다. 모델이 여럿이면 크게 낮았다(Fig. 6b, §3.4.1)
- 평가 방식: 실측 cluster(1080Ti 8대, 56 Gbps InfiniBand)와 GPU 실행을 지연으로 대신한 emulation(1080Ti·A100 profile, 최대 512 GPU, §5). §3.4는 scheduler simulation이다

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| 같은 모델 추론 요청을 batch로 묶어 batch를 키우려 한다 | Symphony는 추론 요청이 도착한 뒤 batch 실행을 frontrun까지 미룬다. 이 연구는 Host가 모델별 frame offset을 정해 같은 모델 추론 요청이 함께 도착하게 한다. Grouping은 기다리지 않는다 | [구조] 일부러 미루는 시간이 response time에 더해지지 않는다 |
| | Symphony는 GPU 여러 대에 모델을 미리 올려 둔다. 이 연구는 FPGA 하나이고 모델 40개 weight 4.97 MiB가 BRAM보다 커서 weight 전송이 병목이다 | [구조] PNU-Count가 다음 사용 시각을 예측해 가장 늦게 쓸 모델을 내보낸다 |

## 인용할 때

- 이 논문이 먼저 한 것: deadline을 지키는 범위에서 batch 실행 시각을 일부러 늦춰 batch를 키우는 것(deferred batch scheduling). 기다려 묶기 자체는 신규성으로 주장하지 않는다([09_RELATED_WORK §3](../../design_references/09_RELATED_WORK.md#3-신규성-경계))
- 근거 위치: schedulable window §3.1(Fig. 3), 알고리즘 §3.2(Algorithm 1), 예시 §3.3(Fig. 4–5), eager·timeout 비교 §3.4(Fig. 6–7), 모델 배치 §4.1·§4.4, 결과 §5.1–5.3(Fig. 9–10, Table 2), drop 부록 D(Fig. 18)
- 주의: 게재 학회는 원문에 없고 확인하지 못했다([09_RELATED_WORK §4](../../design_references/09_RELATED_WORK.md#4-남은-조사)). arXiv 번호로 인용한다
- 주의: 5배와 60%는 최댓값이다(§1 "up to"). 모델 37개 mixed에서는 2.0–2.4배다(Fig. 9). Fig. 4의 staggered execution은 GPU 여러 대가 batch를 서로 다른 시각에 실행하는 모양이다. Frame 생성 시각을 정하는 Model-Grouped Offset Assignment와 다르다
- 옮긴 방식: P3.11에서 Symphony Method(원문에 없는 고정 여유를 더하고 drop을 씀)로 비교했으나 2026-10-16에 비교군에서 뺐다([08_EVALUATION §3](../../design_references/08_EVALUATION.md#3-비교-규칙)). 지금 결과로 인용하지 않는다
