# B03: Sparse-DySta

원문: `B03_SparseDySta_multiDNN.pdf`
Fan 등, MICRO 2023

## 1. 문제

Multi-DNN accelerator에서 짧은 작업 우선과 deadline 우선은 같은 순서를 만들지 않는다. Sparse model은 input마다 실제 처리 시간도 달라진다.

Sparse-DySta는 평균 시간으로 시작하고, 실행 중 sparsity를 관측해 남은 시간을 다시 예측한다.

## 2. 방법

초기 score는 예상 처리 시간과 deadline slack을 함께 쓴다. Layer가 끝나면 최근 sparsity로 remaining time을 갱신한다.

Score 요소:

- 예상 remaining time
- 현재 deadline slack
- 잦은 preemption을 막는 항

논문의 SLO는 standalone latency에 배수를 곱한 soft target이다.

## 3. 결과

Multi-attention workload의 표 5:

| 정책 | ANTT | SLO miss |
|---|---:|---:|
| FCFS | 18.9 | 55.1 % |
| SJF | 5.0 | 15.2 % |
| PREMA | 5.4 | 15.3 % |
| Planaria | 16.0 | 6.8 % |
| Dysta | 4.7 | 5.1 % |

Dysta scheduler resource는 LUT 553, DSP 3, on-chip RAM 0.5 KB였다. 우리 구조에서도 같은 값이라는 뜻은 아니다.

## 4. 우리 연구에 쓰는 범위

Dysta의 sparsity 대신 다음 정보를 쓴다.

- 모델 cache hit
- 남은 weight byte
- 진행 중인 prefetch
- 트랙 compute와 state DMA
- Deadline slack

이미 completion time에 넣은 transfer를 별도 penalty로 다시 더하면 안 된다.

차이:

- Dysta는 ANN과 soft SLO를 다룬다.
- 우리는 periodic 32 ms hard deadline을 다룬다.
- Dysta는 모델 weight fetch를 scheduling cost로 보지 않는다.

P3.8 비교에서는 Dysta Method 순서가 평균 response time을 조금 줄였지만 off-chip byte는 줄이지 못했다. 느린 DDR3 조건에서는 miss가 났다.

원문 확인: algorithm 1–3, 결과 표 5·그림 12, resource 표 6.
