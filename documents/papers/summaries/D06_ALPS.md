# D06: ALPS

원문: `D06_ALPS_AIM2026.pdf`
Filippo Aisa, Umberto Albertin, Mauro Martini, Vittorio Fra, Gianvito Urgese, Marcello Chiaberge(Politecnico di Torino), "Ultra-low-power Anomaly Detection at the Edge with Spiking Neural Networks", IEEE/ASME AIM 2026, 6쪽, DOI 10.1109/AIM65483.2026.11658148
읽은 범위: 원문 전체(6쪽)

## 한 줄 요약

왕복식 공기 압축기 소리를 16채널 대역 필터와 spike encoder로 바꾸고 LIF 128개 hidden layer 하나인 SNN으로 상태 8종을 분류했다. 7 bit로 양자화해 SynSense Xylo Audio 3에 올려 macro F1 0.93, 3.4 mW를 냈다(초록, Table II).

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | 전력이 작은 산업 장치에서 이상 탐지를 상시 돌려야 한다. 소리 기반 SNN 이상 탐지 연구는 진동 신호보다 적다(§I, §II) |
| 방법 | 입력: raw 음성을 16채널 대역 필터(Fig. 2 기준 105 Hz–16.8 kHz)로 나누고 채널마다 spike train으로 바꾼다. Encoder는 Xylo Audio 3에 든 analog front-end의 software 사본(AFESimExternal)이다(§III, §III-B) |
| 방법 | 모델: 16 → LIF 128(hidden 1층) → LIF 8, feed-forward CuBa-LIF. 출력 synaptic current의 시간 평균이 가장 큰 클래스를 고른다. τ는 Xylo의 정수 shift(dash) 값에 맞는 격자에서만 고른다(§III-A, Eq. 2–9) |
| 방법 | 학습: cross entropy와 발화율 penalty, Adam, 최대 500 epoch. Optuna(TPE) 1,000회로 hidden 크기, 층 수, τ, threshold를 골랐다(§III-B, Table I) |
| 방법 | 배치: 학습 뒤 양자화(PTQ)로 weight를 7 bit로 줄인다. 16 bit synaptic current 누산기가 넘치지 않게 8 bit 대신 7 bit를 골랐다(§IV-A) |
| 가정·조건 | 지도학습이다. 클래스 8개(정상 1, 고장 7)를 학습과 시험에서 모두 아는 closed-set 분류이고 처음 보는 고장 탐지는 범위 밖이다(§III). 데이터는 Verma 등의 공기 압축기 녹음, 클래스마다 wav 225개, 70/15/15% 분할(§III-B). 장치는 단일 채널 하나, 모델 하나다. 지연과 deadline은 원문에 없다 |

## 결론

- Xylo Audio 3의 ALPS Quantized: accuracy 0.93, macro F1 0.93, 3.4 mW. 부동소수점 ALPS는 라즈베리파이 4에서 F1 0.97, 2.6 W였다(Table II)
- 비교군 1D-CNN(라즈베리파이 4): FP32 F1 0.99·3.5 W, INT16 F1 0.99·3.4 W. 원문은 Xylo가 전력을 약 세 자릿수 줄였다고 쓴다(§IV-B)
- 오분류는 주로 Bearing과 LOV 클래스 사이다(Fig. 3). 공장 잡음을 더하면 SNR 18 dB까지 F1이 급락 없이 줄었다(§IV-C, §V)
- 평가 방식: Xylo Audio 3 보드와 라즈베리파이 4 실측. 시험 표본은 280개다(§IV-B)

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| SNN으로 장비 소리의 이상을 판정하고 이상 데이터를 학습에 쓰는 지도학습이다(이 연구는 02 §3) | Aisa 등은 압축기 한 대의 상태 8종을 분류한다. 이 연구는 DCASE 2020 Task 2의 장비 ID마다 정상·이상 2클래스 모델을 하나씩 둔다 | [구조] 장비 ID별 모델 40개를 FPGA 하나가 나눠 쓴다 |
| 정수 weight로 줄여 전용 hardware에 올린다 | Aisa 등은 모델 하나를 Xylo에 상주시키고 stream 하나를 처리한다. 이 연구는 weight 4.97 MiB를 DDR3에 두고 entry 4개에 적재하며 mic 트랙 1,024개를 32 ms 주기로 처리한다 | [구조] Offset Assignment와 Grouping으로 같은 모델 추론 요청을 batch로 묶어 weight 적재를 줄이고 트랙마다 membrane potential을 따로 둔다 |
| | Aisa 등은 3.4 mW를 보였다 | 없음. 이 연구는 전력을 재지 않았다 |

## 인용할 때

- Aisa 등이 먼저 했다: 공기 압축기 소리의 고장 분류 SNN을 neuromorphic chip(Xylo Audio 3)에 올려 mW 수준 전력을 보였다. 09 §3의 주장 범위와 겹치는 기법은 없다
- 근거 위치: pipeline Fig. 2, neuron 식 Eq. 3–7, 탐색 공간 Table I, 양자화 §IV-A, 결과 Table II, 잡음 시험 Fig. 4
- 주의: 제목은 anomaly detection이지만 실제로는 알려진 고장 8종의 closed-set 분류다. 원문도 처음 보는 고장 탐지는 앞으로 할 일이라고 쓴다(§III, §V)
- 주의: 3.4 mW를 §IV-B는 보드 단위 전력(board-level), §V는 on-chip 추론 전력이라고 쓴다. 측정 방법은 원문에 없다. 시험 280개는 1,800개의 15%(270개)와 맞지 않는다
- 주의: 정확도는 데이터셋과 과제가 달라 우리 AUC와 비교하지 않는다
- 비교군: 옮기지 않았다
