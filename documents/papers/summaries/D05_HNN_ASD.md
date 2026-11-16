# D05: HNN Processor for Anomalous Sound Detection

원문: `D05_HNN_ASD_VLSITSA2026.pdf`
Li-Yuan Chang, Ren-Hao Chiou, Heng-Siang Gao, Chia-Hsiang Yang(National Taiwan University), "An 88.1TOPS/W Hidden-Neural-Network Processor for Anomalous Sound Detection", VLSI-TSA 2026, 2쪽, DOI 10.1109/VLSITSA69131.2026.11527739
읽은 범위: 원문 전체(2쪽, Fig. 4 비교표 포함)

## 한 줄 요약

Weight를 외부 메모리에서 읽지 않고 chip 안의 난수 생성기로 만들고 mask만 on-chip에 두는 hidden neural network(HNN) 방식으로 이상음 탐지 ASIC을 만들었다. 40 nm CMOS chip이 MIMII에서 AUC 78.3–93.3%, 최대 88.1 TOPS/W를 냈다(초록, §IV).

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | Edge 장치가 여러 소리 탐지 task를 적은 에너지로 처리해야 한다. Weight를 외부 메모리에서 읽는 비용(EMA)을 줄여야 한다(§I) |
| 방법 | HNN: 같은 seed로 같은 난수 weight를 다시 만들 수 있어 weight를 chip 안에서 생성한다. 소리 종류가 달라도 난수 weight는 같고 mask만 바꾼다(§I) |
| 방법 | Weight generation unit: 8 bit 균등분포 난수 생성기 64개가 binary weight를 만들고 균등 perturbation으로 multi-bit weight를 만든다. Stream interface가 생성된 weight를 미리 받아 tensor engine의 데이터 접근 시간을 50% 줄인다(§III, Fig. 2) |
| 방법 | 연산 줄이기: 여러 겹 mask(multicoated mask)로 weight 52.6%·mask 29.8% 감소, column-wise bitmap encoding(CBE)으로 mask 메모리 43% 감소와 0 건너뛰기, ReLU 출력이 0이 될 부분합을 미리 끊는 space-time speculation. 합쳐서 연산량 최대 88.9% 감소(§II) |
| 방법 | Tensor engine: output-stationary 64-PE array, coat를 하나씩 처리해 PE array 전력 18.2% 감소. 음수 쪽 bit를 줄이는 비대칭 bitwidth로 activation 메모리 33.3% 감소(§III, Fig. 3) |
| 가정·조건 | 모델은 interpolation autoencoder(Suefusa 등, 재구성 오차로 판정)이고 데이터는 MIMII다(§I, §IV). Fig. 1의 on-chip 메모리는 mask 128 KB, index 4 KB, weight 4 KB 두 개, activation 0.5 KB다. 소리 stream 수, 주기, deadline은 원문에 없다 |

## 결론

- Chip: 40 nm CMOS, 1.69M gate, core 1.85 mm²(die 3.76 mm²), 0.65–0.9 V, 20–200 MHz, 5.6–45.7 mW(§IV, Fig. 4)
- 20 MHz에서 이상 판정 0.59 ms, MIMII AUC 78.3–93.3%(원문은 DNN 구현과 비슷하다고 쓴다). 최대 88.1 TOPS/W로 Hiddenite(ISSCC 2022, 2.94 TOPS/W)의 30배다. 면적 효율 1.25 TOPS/mm²(§IV, Fig. 4)
- 비교표에서 외부 mask 접근이 Hiddenite는 "Required", 이 chip은 "Not Required"다(Fig. 4)
- 평가 방식: 제작한 chip 실측. TOPS/W의 전력은 core 전력에 외부 메모리 접근 추정 전력을 더한 값이다(Fig. 4 각주)

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| 이상음 탐지 가속기에서 weight를 외부 메모리에서 읽는 양을 줄이려 한다 | Chang 등은 난수 weight를 chip 안에서 만들고 mask만 on-chip에 둔다. 모델을 HNN으로 학습해야 한다. 이 연구는 학습한 INT8 weight를 DDR3에 두고 Offset Assignment, Grouping, PNU Cache로 같은 weight의 재사용을 늘린다 | [구조] 일반 학습으로 만든 weight를 그대로 쓴다. 장비 ID마다 따로 학습한 모델 40개(4.97 MiB)를 바꾸지 않고 올린다 |
| 소리 종류(장비)마다 다른 모델을 쓴다 | Chang 등은 소리 종류마다 mask만 바꾼다고 쓰지만 여러 소리 stream을 동시에 처리하는 구조와 평가는 없다. 이 연구는 트랙 1,024개가 32 ms마다 추론 요청을 낸다 | [구조] 트랙마다 membrane potential을 따로 두고 12 bit Membrane Storage로 768트랙의 state를 BRAM에 둔다 |
| | Chang 등은 40 nm ASIC이고 DNN(autoencoder)이다. 이 연구는 Artix 7 FPGA의 SNN이다 | 없음. 이 연구는 전력과 에너지 효율을 재지 않았다 |

## 인용할 때

- Chang 등이 먼저 했다: 이상음 탐지 전용 chip에서 weight를 on-chip에서 생성해 외부 메모리 접근을 줄였다. HNN 자체와 on-chip weight 생성은 Hiddenite(원문 [3])가 먼저다. 09 §3의 주장 범위와 겹치는 기법은 없다
- 근거 위치: HNN과 mask 교체 §I, 연산 감소 수치 §II, 구조 Fig. 1–3, chip 수치와 비교표 §IV·Fig. 4
- 주의: 88.1 TOPS/W는 최대값이고 어느 전압·주파수에서 낸 값인지 원문에 없다. 건너뛴 연산을 TOPS에 넣었는지도 적혀 있지 않다. 30배의 기준인 Hiddenite 2.94 TOPS/W도 외부 메모리 접근 추정 전력을 더한 값이다. Hiddenite 원 논문 제목의 34.8–16.0 TOPS/W와 다르다(원문 [3], Fig. 4)
- 주의: AUC 78.3–93.3%가 장비 종류별 범위인지, 여러 mask를 chip에 함께 두고 쟀는지 원문에 없다. MIMII와 DCASE 2020 Task 2는 조건이 달라 우리 AUC와 비교하지 않는다
- 비교군: 옮기지 않았다
