# 09. 선행연구와 신규성 경계

선행연구의 원문 목록은 [papers/references/INDEX.md](../papers/references/INDEX.md), 논문별 해설은 [papers/summaries/](../papers/summaries/)에 있다. 원 논문의 정책을 비교군에 적용한 방법은 [P3.11 보고서](<../reports/P3.11 Research Report.md>)와 [08_EVALUATION.md](08_EVALUATION.md) §3에 정리했다.

## 1. 요약

같은 모델의 추론 요청을 묶거나 weight를 공유하는 것은 기존 기법이다. 다음 사용 시점에 따라 cache를 교체하는 것과 주기 작업의 생성 시각에 간격을 두는 것도 기존 기법이다.

이 설계의 기여는 Host의 Model-Grouped Offset Assignment와 FPGA의 Grouping·weight cache를 결합해 DDR3 traffic과 response time을 함께 줄이는 데 있다. 각 요소의 효과는 분리해 평가한다([05_SCHEDULING.md](05_SCHEDULING.md) §4, [04_MEMORY.md](04_MEMORY.md) §3.2). 지금까지 조사한 범위에서는 같은 결합을 찾지 못했다. 다만 체계적인 신규성 조사는 아직 끝내지 않았다. 남은 조사는 [TASKS.md](../TASKS.md) P3.18에 있다.

## 2. 가장 가까운 연구

| 연구 | 주요 기법 | 이 설계와의 관계 |
|---|---|---|
| Sparse-DySta (MICRO'23) | 실행 중 관측한 sparsity로 남은 실행 시간을 갱신하고 deadline 여유 등을 반영해 추론 요청 우선순위를 정한다 | 도착한 추론 요청의 실행 순서를 조정한다. 이 설계는 Host에서 모델별 frame 생성 시각을 정한다. 비교군 Dysta Method로 옮겼다 |
| DeepRT (SEC'21) | 시간 window에 들어온 같은 처리 유형의 frame을 묶어 deadline 순서로 실행한다 | 기다린 만큼 response time이 는다. 비교군 DeepRT Method로 옮겼다 |
| LazyBatching (HPCA'21) | 새 추론 요청이 실행 중인 추론 요청과 같은 layer까지 진행한 뒤 이후 layer를 함께 처리한다 | 추론 요청 도착 시각은 바꾸지 않는다 |
| BATCH-DNN (Euro-Par 2025) | layer별 on-chip 메모리 여유에 맞춰 batch를 나누거나 합쳐 weight를 재사용한다 | 추론 요청 생성 시각을 맞추지 않는다(공개 초록 기준) |
| RT-Swap (RTAS'24) | 주기 작업의 다음 release가 늦은 모델부터 GPU 메모리에서 내보낸다 | Predicted-Next-Use (PNU) Weight Cache와 교체 원리가 같다. 이 설계에서는 nominal offset만으로 다음 도착을 알 수 없으므로 queue, 모델 그룹 지연·추론 요청별 지연 분포, 예상 추론 요청 수로 다음 사용 시각을 예측한다 |
| CAN offset 배정 (Grenier 등, 2008) | 주기 message의 전송 시각에 간격을 두어 동시 전송과 worst case response time을 줄인다 | 이 설계도 모델 사이에 간격을 두지만, 같은 모델의 트랙에는 같은 offset을 줘 weight 재사용 기회를 만든다. offset 배정 자체보다 모델별 frame 생성 시각을 맞추는 효과를 평가한다 |
| Clockwork (OSDI'20) | GPU 메모리를 모델 cache로 쓰고 LRU로 내보낸다. Response time을 예측 가능하게 만든다 | 기다리지 않는다. 추론 요청 사이 state가 없고 도착 시각을 바꾸지 않는다 |
| Ogden 등 (ACSOS'21) | 모델 단위 cache를 인기도·크기·적재 비용으로 교체한다 | CPU edge 환경을 다루며 deadline은 고려하지 않는다 |
| Minitaur, Sharma 등 (ISLPED'22), Cheung 등 (ICANN'12), sPyNNaker | SNN의 weight·state를 배치한다. Membrane potential과 weight가 한정된 on-chip 메모리를 나눠 쓴다 | Network 하나를 대상으로 하며, 모델 전환과 주기 deadline을 함께 다루지 않는다 |

SNAVA의 제목에 쓰인 `real-time`과 `multi-model`은 이 설계와 의미가 다르다. Multi-model은 neuron model의 종류를, real-time은 생물학적 1 ms timestep을 뜻한다.

## 3. 신규성 경계

다음을 기여로 주장한다.

1. 같은 모델을 쓰는 소리 stream에 같은 offset을 주어 weight 재사용 기회를 만든다(Model-Grouped Offset Assignment). Deadline과 계산량은 바뀌지 않는다.
2. 추가 추론 요청을 기다리지 않는 Grouping, PNU Cache, 12 bit Membrane Storage를 결합한 가속기 구조를 제안한다.
3. 같은 BRAM 예산과 입력에서 Offset Assignment, scheduler, cache의 영향을 분리해 비교한다. 측정한 Host 처리 지연을 넣어 DDR3 traffic과 response time을 평가한다. 추론 요청별 지연과 entry 수에 따른 이득, deadline 분석의 한계도 확인한다.

다음은 기여로 주장하지 않는다.

- 같은 모델 추론 요청을 묶거나 weight를 함께 쓰는 것 자체 (DeepRT, LazyBatching, BATCH-DNN)
- 같은 모델의 추가 추론 요청을 기다려 batch를 키우는 것 자체 (DeepRT, Symphony)
- 다음 사용 시점에 따른 cache 교체 자체 (RT-Swap)
- 주기 작업의 생성 시각에 간격을 두는 것 자체 (CAN offset 배정)
- 모델 단위 cache, off-chip weight와 on-chip cache 자체 (Clockwork, Minitaur)
- On-chip state와 off-chip weight 배치 자체, membrane potential의 메모리 압박 관찰 (Sharma 등, Cheung 등, sPyNNaker)
- 부분 상주, prefetch, double buffer, SNN timestep 재사용 자체
- 32 ms hard deadline 보장

"최초"나 "같은 연구가 없다"고 단정하지 않는다.
