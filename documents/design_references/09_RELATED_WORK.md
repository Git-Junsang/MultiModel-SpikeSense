# 09. 선행연구와 신규성 경계

원문 목록은 [papers/references/INDEX.md](../papers/references/INDEX.md), 개별 해설은 [papers/summaries/](../papers/summaries/)에 있다. 비교군 정책을 옮긴 방법은 [P3.11 보고서](<../reports/P3.11 Research Report.md>)와 [08_EVALUATION.md](08_EVALUATION.md) §3에 있다.

## 1. 요약

같은 모델 요청을 묶는 것, weight를 함께 쓰는 것, 다음 사용 시점으로 cache를 교체하는 것, 주기 작업에 offset을 주는 것은 모두 기존 기법이다. 이 설계의 기여는 모델별 frame offset 배정과 FPGA의 Grouping·weight cache를 결합해 DDR3 전송량과 응답 시간을 함께 줄이는 데 있다. 각 요소의 효과는 ablation으로 나눠 보인다([05_SCHEDULING.md](05_SCHEDULING.md) §4.1). 지금까지 찾아본 범위에서 같은 결합은 보지 못했지만 체계적인 신규성 조사를 마친 것은 아니다.

## 2. 가장 가까운 연구

| 연구 | 하는 일 | 이 설계와 다른 점 |
|---|---|---|
| Sparse-DySta (MICRO'23) | 실행 중 관측한 sparsity로 남은 실행 시간을 갱신하고 deadline 여유를 반영해 요청 우선순위를 정한다 | 도착한 요청의 순서만 바꾼다. 비교군 Dysta Method로 옮겼다 |
| DeepRT (SEC'21) | 시간 window에 들어온 같은 처리 유형의 frame을 묶어 deadline 순서로 실행한다 | 기다린 만큼 응답 시간이 는다. 비교군 DeepRT Method로 옮겼다 |
| LazyBatching (HPCA'21) | 새 요청이 실행 중인 요청과 같은 layer까지 진행한 뒤 이후 layer를 함께 처리한다 | 요청 도착 시각은 바꾸지 않는다 |
| BATCH-DNN (Euro-Par 2025) | layer별 on-chip 메모리 여유에 맞춰 batch를 나누거나 합쳐 weight를 재사용한다 | 요청 생성 시각을 맞추지 않는다(공개 초록 기준) |
| RT-Swap (RTAS'24) | 주기 작업의 다음 release가 늦은 모델부터 GPU 메모리에서 내보낸다 | offset-order cache와 같은 교체 원리. 이 설계는 다음 사용 순서를 Host가 배정한 offset에서 얻는다 |
| CAN offset 배정 (Grenier 외, 2008) | 주기 message의 전송 시각에 간격을 두어 동시 전송과 worst case 응답 시간을 줄인다 | 모델을 보지 않는다. 이 설계는 같은 모델의 트랙에 같은 offset을 준다. 모델과 상관없이 offset을 고르게 나눠 주면 DDR3 전송량이 무작위 offset과 같았다 |
| Clockwork (OSDI'20) | GPU memory를 모델 cache로 쓰고 LRU로 내보낸다. 응답 시간을 예측 가능하게 만든다 | 기다리지 않는다. 요청 사이 state가 없고 도착 시각을 바꾸지 않는다 |
| Ogden 외 (ACSOS'21) | 모델 단위 cache를 인기·크기·적재 비용으로 교체한다 | CPU edge, deadline 없음 |
| Minitaur, Sharma 외 (ISLPED'22), Cheung 외 (ICANN'12), sPyNNaker | SNN weight·state 배치. membrane potential과 weight가 on-chip memory를 두고 다툰다 | network 하나. 모델 전환과 주기 deadline을 함께 다루지 않는다 |

SNAVA는 제목에 `real-time`, `multi-model`, `SNN`이 들어가지만 뜻이 다르다. multi-model은 neuron model 종류, real-time은 생물학적 1 ms timestep이다.

## 3. 신규성 경계

주장하는 범위:

1. 같은 모델을 쓰는 센서 stream에 같은 frame offset을 주어, FPGA에 도착한 순간부터 weight 재사용이 가능하게 만든다(Model-Grouped Offset Assignment). deadline과 계산량은 바뀌지 않는다.
2. 같은 모델 요청이 함께 도착하는 조건에서 가속기를 단순하게 만든다. 추가 요청을 기다리지 않는 Grouping, offset-order weight cache, 12 bit membrane storage를 결합한다.
3. 같은 BRAM과 trace에서 기존 scheduler의 DDR3 전송량-응답 시간 trade-off를 벗어남을 보이고 jitter, DDR3 대역폭, 트랙 수에 대한 민감도를 평가한다.

주장하지 않는 범위:

- 같은 모델 요청을 묶거나 weight를 함께 쓰는 것 자체 (DeepRT, LazyBatching, BATCH-DNN)
- 기다려 묶기 자체 (DeepRT, Symphony)
- 다음 사용 시점에 따른 cache 교체 자체 (RT-Swap)
- 주기 작업의 offset 배정 자체 (CAN offset 배정)
- 모델 단위 cache, off-chip weight와 on-chip cache 자체 (Clockwork, Minitaur)
- on-chip state와 off-chip weight 배치 자체, membrane potential의 memory 압박 관찰 (Sharma 외, Cheung 외, sPyNNaker)
- 부분 상주, prefetch, double buffer, SNN timestep 재사용 자체

"최초"나 "같은 연구가 없다"고 단정하지 않는다.

## 4. 남은 조사

| 항목 | 상태 |
|---|---|
| Model-Grouped Offset Assignment와 같은 기법 | 웹 검색·OpenAlex 결과 없음. IEEE Xplore API 승인 대기 |
| BATCH-DNN 전문 | 미확보. 공개 초록이 뒷받침하는 내용만 쓴다 |
| Nexus | 원문 확인 전 |
| CD-MSA (TPDS'23), AI-MT (ISCA'20) | 원문 미확보 |
| Symphony 게재 학회 | 확인 전 |
| 설비별 개인화 모델의 산업 적용 근거 | 확보 전 |

수집한 논문의 파일명과 출처는 [papers/references/INDEX.md](../papers/references/INDEX.md)에 있다.
