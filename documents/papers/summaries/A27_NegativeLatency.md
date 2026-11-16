# A27: Negative Latency on SpiNNaker2

원문: `A27_NegativeLatency_GCWkshps2025.pdf`
Matthias Jobst, Jonas Schulz, Chen Liu, Mohamed Samaali, Matthias Lohrmann, Juan A. Cabrera, Christian Mayr, Frank H. P. Fitzek, IEEE Globecom Workshops 2025, pp. 757–762, DOI 10.1109/GCWkshps68340.2025.11591225
읽은 범위: 원문 전체

## 한 줄 요약

Data glove의 IMU stream으로 사용자가 잡을 물체를 미리 맞히는 CNN ensemble(모델 10개)을 SpiNNaker2 칩 하나에 올렸다. 모델은 SNN이 아니라 CNN이다. Stream마다 PE 10개를 따로 주어 stream 15개를 함께 처리했고 end-to-end latency는 stream 1개 11.4 ms, 15개 20.0 ms였다. Stream·추론당 에너지는 2.18 mJ에서 0.48 mJ로 줄었다.

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | Tactile Internet의 tactile 상호작용은 1 ms 미만의 지연을 요구하지만 haptic actuator 지연만 수십 ms다. 사용자 동작을 미리 예측하는 negative latency 추론을 edge에서 적은 에너지로 계속 돌려야 한다(§I, §II-A) |
| 방법 | VGG 계열 CNN(parameter 13,658개) 10개를 ensemble로 쓴다. microTVM으로 32 bit floating point code를 만든다. 입력은 IMU 6개의 quaternion 최근 10 sample(6 × 4 × 10)이다(§III-B1, §IV-A, Table I) |
| 방법 | 칩의 PE 152개 중 stream마다 PE 10개가 모델 하나씩 맡는다. 모델 10개는 같은 입력을 받고 Host PC가 softmax 출력을 평균한다. PE를 stream마다 따로 두므로 stream은 15개까지다(§III-B2, Fig. 1) |
| 방법 | latency 최적화: Data Mover PE 하나가 입력을 받아 worker PE에 나눈다. Stream마다 PE 하나가 ready flag를 모은다. Worker PE는 연산이 끝나면 바로 결과를 Host PC로 보낸다(Automatic Reply)(§III-B3) |
| 방법 | 쓰지 않는 PE와 외부 메모리 interface는 끄고 PE마다 DVFS로 쉬는 동안 clock과 전압을 낮춘다(§III-B4) |
| 가정·조건 | SpiNNaker2 칩 1개와 Host PC를 Ethernet으로 잇는다. 50 Hz 갱신(20 ms)을 실시간 기준으로 본다. 모든 stream이 같은 ensemble을 쓰고 weight는 PE 메모리에 상주한다. 모델 교체, weight 적재, deadline miss 집계는 원문에 나오지 않는다 |

## 결론

- End-to-end latency: stream 1개에서 처음 구현 17.3 ms, 최적화 뒤 11.4 ms다. Stream 15개에서는 98.4 ms와 20.0 ms다(4.92배). Latency는 stream 수에 비례해 늘고 Data Mover PE가 2배를 줄였다. 처리량은 ensemble 추론 초당 87.7회(1 stream)에서 750회(15 stream)다(§IV-B1, Fig. 2)
- 전력은 192 mW(1 stream)에서 353 mW(15 stream)다. Stream·추론당 에너지는 최적화 전 3.28 mJ, 최적화 뒤 2.18 mJ, 15 stream에서 0.48 mJ다. 약 8 stream까지는 칩 leakage를 나눠 줄고 그 뒤에는 stream 관리 부담으로 조금 는다(§IV-B2, Fig. 3)
- Coral Edge TPU(USB, INT8)는 1 stream 2.97 ms·9.2 mJ, 15 stream 순차 10.59 ms·32.82 mJ, TPU 15개 병렬(추정) 2.97 ms·138 mJ다. SpiNNaker2 15 stream은 20.0 ms·7.20 mJ다(§IV-C, Table II)
- 평가 방식: 실측(SpiNNaker2 칩 1개와 Host PC, Coral USB Accelerator와 shunt 저항 전력 측정). TPU 15개 병렬은 추정값이다

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| 장치 하나가 sensor stream 여러 개의 추론을 맡고 Host와 Ethernet으로 잇는다 | Jobst 등은 stream마다 PE 10개를 따로 주는 공간 분할이라 stream 수가 PE 수에 묶인다(15개). 이 연구는 트랙 1,024개가 compute array 하나를 시간으로 나눠 쓴다 | [구조] 트랙 수가 연산 유닛 수에 묶이지 않는다. Grouping이 같은 모델 추론 요청을 batch로 묶는다 |
| 모델 여러 개를 한 장치에서 돌린다 | Jobst 등은 같은 구조의 CNN 10개가 같은 입력을 받고 weight가 PE 메모리에 상주한다. 이 연구는 트랙마다 모델 40개 중 하나를 쓰는 SNN이고 weight 4.97 MiB가 BRAM보다 커서 entry 4개에 교체 적재한다 | [구조] PNU-Count가 entry에 둘 모델을 고르고 Offset Assignment가 같은 모델 추론 요청이 함께 생기게 한다 |
| 결과를 연산이 끝나자마자 Host로 보낸다(Automatic Reply) | Jobst 등은 offset, batch, deadline 여유를 다루지 않는다. Stream이 늘면 latency가 비례해 는다 | 없음. 결과를 바로 보내는 방식은 같다 |

## 인용할 때

- Jobst 등이 먼저 했다: neuromorphic 칩 하나가 여러 사용자의 sensor stream을 PE를 나눠 동시에 처리하고 stream 수에 따른 latency와 에너지를 쟀다. 09 §3 주장 범위와 겹치는 기법은 없다
- 근거 위치: PE 배정 §III-B2·Fig. 1, 최적화 §III-B3–4, 모델 §IV-A·Table I, latency Fig. 2, 에너지 Fig. 3, Coral 비교 §IV-C·Table II
- 주의: 모델은 CNN이고 32 bit floating point로 돌렸다. PE의 machine learning accelerator와 spiking model은 후속 과제다(§V). SNN 다중 트랙 처리의 근거로 쓰지 않는다
- 주의: 초록은 "temporal multiplexing"으로 stream 15개를 처리한다고 쓰지만 본문은 stream마다 PE를 따로 두는 방식만 설명한다(§III-B2). 시분할의 근거로 인용하지 않는다
- 주의: 초록의 "6.8× reduction over the single-stream case"는 최적화 전 1 stream(3.28 mJ) 대비다. 최적화 뒤 1 stream 대비는 4.5배다(§IV-B2)
- 주의: Edge TPU는 interpreter 호출 전후 시간만 쟀고 SpiNNaker2는 Host PC 기준 end-to-end다(§IV-B1, §IV-C1). Edge TPU 15 stream 순차 10.59 ms는 1 stream 2.97 ms의 15배보다 짧은데 원문은 이유를 적지 않는다
- 주의: 15 stream을 실제 glove 15개로 만들었는지는 원문에 나오지 않는다
