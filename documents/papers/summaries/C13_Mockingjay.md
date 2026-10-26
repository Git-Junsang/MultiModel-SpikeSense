# C13: Mockingjay

원문: `C13_Mockingjay_HPCA2022.pdf`
Ishan Shah, Akanksha Jain, Calvin Lin, HPCA 2022, DOI 10.1109/HPCA53966.2022.00048(받은 PDF는 저자 최종 원고라 DOI와 쪽 번호가 없어 확인하지 못했다)
읽은 범위: 원문 전체

## 한 줄 요약

CPU last-level cache(LLC)에서 PC별 reuse distance를 학습해 line마다 다음 사용 예상 시각(ETA)을 두고 ETA가 가장 먼 line을 내보내 Belady MIN을 흉내 냈다. Single core·prefetcher 없음에서 LRU 대비 성능 향상이 5.7%로 MIN의 6.0%에 가까웠고 4 core에서는 15.2%로 Hawkeye의 12.9%보다 컸다.

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | 이전 ETA 기반 교체(KPK, IbRDP)는 ETA까지 남은 시간(ETR)과 age 중 큰 값으로 내보내고 reuse distance 예측도 부정확해 MIN처럼 내보내지 못한다(§I, §II-B, Fig. 1) |
| 방법 | Sampled cache가 표본 set 32개의 과거 접근을 cache 크기의 8배 길이로 기록한다. 여기서 관측한 reuse distance로 PC별 predictor(RDP)를 temporal difference learning으로 학습한다. 같은 PC라도 hit와 miss는 따로 배운다(§III-A·B) |
| 방법 | 삽입할 때 예측 reuse distance로 line의 ETR 계수기를 정하고 set 접근이 쌓이면 줄인다. 시간 단위는 set 접근 수다. 0을 지나도 계속 줄인다. 교체할 때는 ETR 절댓값이 가장 큰 line을 내보낸다. 가장 늦게 쓸 line이거나 ETA가 가장 오래 지난 line이다(§III-A) |
| 방법 | ETA가 set의 모든 line보다 먼 삽입은 bypass한다. Prefetch로 다시 들어올 구간은 reuse distance를 2배(4 core는 1.5배)로 학습해 Flex-MIN을 흉내 낸다(§III-A, §III-D) |
| 가정·조건 | ChampSim, core당 LLC 2 MB 16-way. SPEC CPU2006·2017과 GAP 중 LLC MPKI가 1보다 큰 33개, CVP 중 MPKI가 높은 25개, 4 core mix 100개. 비교 정책의 hardware 예산은 모두 32 KB다(Mockingjay 31.91 KB, §III-E, §IV-A, Table II) |

## 결론

- Single core, prefetcher 없음: LRU 대비 IPC 향상은 Mockingjay 5.7%, Hawkeye 4.4%(Table I은 4.5%), SHiP 3.4%, MIN 6.0%다(§IV-B, Table I). 1 MB Mockingjay가 2 MB LRU보다 성능이 높다(§I)
- 4 core mix 100개(weighted speedup): prefetcher가 없으면 15.2%로 SHiP 7.6%, Hawkeye 12.9%보다 높다. Prefetcher가 있으면 13.3%로 Harmony 11.1%보다 높다(§IV-B, Fig. 3)
- Reuse distance 예측 정확도는 85%로 IbRDP의 43%보다 높다(§II-B). MIN이 고를 victim과 비교한 순서 오차는 3.2로 LRU 8.2, Hawkeye 4.1보다 작다(§V-D, Fig. 21). DRAM traffic은 Hawkeye보다 9.8% 적다(§IV-B, Fig. 5)
- 평가 방식: ChampSim simulation. 실측과 합성 결과는 없다

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| 다음 사용 예상 시각이 가장 늦은 대상을 내보내 Belady MIN을 흉내 낸다. 이 연구도 미래를 아는 Oracle MIN을 비교 기준으로 둔다 | Mockingjay는 PC별 과거 reuse distance로 ETA를 학습하고 시간을 set 접근 수로 센다. PNU-Count는 nominal offset, queue, 모델 그룹 지연 분포, 추론 요청별 지연 분포, n_expect로 다음 사용 시각을 계산한다 | [구조] Host가 모델마다 offset을 정하므로(Model-Grouped Offset Assignment) 다음 사용 시각의 기준을 접근 이력으로 학습하지 않아도 된다 |
| 예측 시각이 지난 대상을 따로 다룬다 | Mockingjay는 ETA가 오래 지난 line일수록 먼저 내보낸다(§III-A). PNU-Count는 nominal offset이 지났어도 첫 추론 요청 전이면 모델 그룹 지연 분포로 곧 쓸 모델로 본다(04 §3.1) | [구조] 트랙마다 주기에 추론 요청이 하나씩 생기므로 nominal frame 끝 시각이 지나도 아직 오지 않은 추론 요청이 남는다. 이것을 n_expect와 모델 그룹 지연 분포로 예측식에 넣었다 |

## 인용할 때

- 먼저 한 것: reuse distance 예측을 ETA로 바꿔 가장 먼 대상을 내보내는 교체는 KPK(Keramidas 등)가 제안하고 IbRDP(Petoumenos 등)가 고쳤다. Mockingjay는 age를 reuse distance 정보가 없을 때만 쓰고 ETA 순서로 내보내 MIN에 더 가깝게 했다(§I, §II-B). 다음 사용 시점 교체 원리 자체는 신규성으로 주장하지 않는다(09 §3)
- 근거 위치: 구성 §III-A와 Fig. 2, ETR·교체 규칙 §III-A "ETA Counters"·"ETR Counters", 구현 §III-B, prefetch §III-D, hardware 예산 §III-E, 결과 §IV-B Fig. 3·Table I, KPK·IbRDP 분해 §IV-B Fig. 6, 순서 오차 §V-D Fig. 21
- 주의: 초록은 CVP·prefetcher 있음의 13.4%를 Hawkeye 값으로 적었지만 §I·§IV-B에서는 Harmony 값이다. Single core의 Hawkeye 값도 Table I(4.5%)과 §IV-B 본문(4.4%)이 다르다. Uncore energy 9.1% 감소의 비교 대상도 다르다(§I: Harmony, §IV-B·Fig. 5: Hawkeye)
- 주의: MIN은 multicore에서 잘 정의되지 않아 MIN 비교(6.0%)는 single core만 있다(각주 1). Prefetcher가 있으면 MIN이 최적이 아니어서 Flex-MIN을 흉내 낸다(§III-D). 이 연구의 Oracle MIN도 cache 결정에 따라 batch 구성이 바뀌어 전체 시스템의 최적은 아니다(04 §3.2)
- 비교군: 옮기지 않았다. 지금 cache 비교(LRU, offset-only, PNU-Count, Oracle MIN)에는 없다
