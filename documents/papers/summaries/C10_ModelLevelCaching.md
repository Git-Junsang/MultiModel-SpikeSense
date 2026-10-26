# C10: Model-Level Caching

원문: `C10_ModelLevelCaching_ACSOS2021.pdf`
Samuel S. Ogden, Guin R. Gilman, Robert J. Walls, Tian Guo, ACSOS 2021, DOI 10.1109/ACSOS52086.2021.00027(INDEX 기준. 받은 PDF는 저자 사본이라 DOI가 없다)
읽은 범위: 원문 전체

## 한 줄 요약

Edge의 많은 DL 모델을 CPU 메모리에 두는 문제를 모델 단위 cache 교체 문제로 보고 적재 비용·크기·다음 사용까지 거리를 함께 보는 교체 정책 CremeBrulee를 제안했다. CPU testbed에서 메모리를 절반으로 줄였을 때 response time은 1.92배였고 simulation에서 model load delay가 popularity 정책보다 최대 16.62% 작았다.

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | 인기가 크게 다른 많은 DL 모델을 한정된 메모리로 serving할 때 어느 모델을 내보낼지 정한다 |
| 방법 | utility를 penalty ÷ (모델 크기 × B(m))로 구하고 utility가 가장 작은 모델부터 내보낸다. Penalty는 적재 시간, B(m)은 모델 m이 다시 쓰일 때까지 들어오는 추론 요청 수다(§V-A 식 (1)) |
| 방법 | 미래를 모르므로 B(m)을 모델별 평균 추론 요청률 λ_m의 역수로 추정한다(Poisson 가정). 미래를 아는 CremeBrulee-oracle은 상한 비교용이다(§V-A) |
| 방법 | 자리가 날 때까지 utility가 작은 모델을 모으고 그중 큰 모델부터 내보낸다(§V-B) |
| 가정·조건 | CPU 서버(AWS m5), TensorFlow Serving, CNN 모델 26개, Azure FaaS trace로 만든 workload. Deadline이 없고 prefetch를 다루지 않는다(§IV) |

## 결론

- Testbed(AWS m5.2xlarge, 모델 26개, 1시간에 추론 요청 1,000개): 필요 메모리를 절반으로 줄였을 때 response time이 1.92배였다(§I, §VI-B)
- Simulation(모델 2,408개, 추론 요청 16,765개, quantiles-r): CremeBrulee의 model load delay는 모든 cache 크기에서 popularity보다 작다. 128 GB에서 16.62%, 평균 7.6% 작고 random보다 최대 36.34% 작다(§VI-C, Fig. 8(a))
- 미래를 알면 CremeBrulee-oracle이 BeladyMIN보다 128 GB에서 12.15%, 평균 6.19% 작다(§VI-C, Fig. 8(b))
- 평가 방식: testbed 실측(CPU 서버 AWS m5.2xlarge)과 trace 기반 event simulation

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| 모델 하나를 cache 단위로 보고 다음 사용이 먼 모델을 내보낸다 | CremeBrulee의 B(m) 추정(1/λ_m)은 평균 추론 요청률만 본다. 이 연구의 PNU-Count는 queue, 모델 그룹 지연 분포, 추론 요청별 지연 분포, n_expect로 다음 사용 시각을 예측한다 | [구조] 32 ms 주기 안에서 다음 사용 시각을 이번 주기 도착 상태로 갱신한다 |
| 적재 비용을 줄이는 것이 목표다 | Ogden 등은 크기와 적재 시간이 다른 모델을 식 (1)로 다룬다. CPU edge이고 deadline이 없다 | 없음. PNU-Count는 다음 사용 시각만으로 내보낸다 |

## 인용할 때

- Ogden 등이 먼저 했다: DL 모델을 cache 객체로 보는 모델 단위 cache, 적재 비용·크기·다음 사용 거리를 함께 쓰는 교체. 모델 단위 cache와 다음 사용 시점 교체 원리 자체는 신규성으로 주장하지 않는다(09 §3)
- 근거 위치: 문제 정의 §IV, utility 식 §V-A 식 (1), B(m) 추정 §V-A 끝, eviction set §V-B, 결과 §VI-B Fig. 5–7과 §VI-C Fig. 8
- 주의: 결론(§IX)은 36.34%를 "non-penalty aware" 정책 대비라고 적었지만 §VI-C 본문에서는 random 대비 값이다. Popularity 대비는 128 GB에서 16.62%다
- 주의: §I은 testbed 결과(메모리 절반, response time 1.92배)를 CremeBrulee의 것으로 적었지만 §VI-B의 testbed 그림(Fig. 5·6)은 CremeBrulee-oracle로 쟀다
- 주의: 크기와 적재 시간이 모두 같으면 식 (1)은 1/B(m)만 남는다. 여기에 1/λ_m 추정을 쓰면 인기 순서가 된다. 원문에서 이 순서는 제안이 아니라 비교군 popularity다(§VI-A)
- 비교군: P3.11 §3.2에서 E.인기고정(Ogden Method)으로 옮겼다. 크기와 적재 시간이 같으면 인기 순이라는 판단이다. 지금 cache 비교(LRU, offset-only, PNU-Count, Oracle MIN)에는 없다
