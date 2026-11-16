# D09: Fit for the Edge

원문: `D09_FitForTheEdge_ARC2026.pdf`
Dragos Lazea, Tudor Ticudean, Tudor Coroian, Anca Hangan, Zsolt István, "Fit for the Edge: Resource and Power-Efficient Multi-stream Anomaly Detection on FPGAs", ARC 2026, LNCS 16514, Springer, pp. 3–15, DOI 10.1007/978-3-032-29365-7_1
읽은 범위: 원문 전체(13쪽)

## 한 줄 요약

센서 stream 여러 개의 이상 탐지를 FPGA 하나에서 처리하려고 연산 pipeline은 모든 stream이 시분할로 쓰고 stream별 state만 따로 두었다. 탐지기는 DNN이 아니라 CUSUM과 Z-Score 통계 방법이다. Stream마다 회로를 복제할 때보다 지원 stream 수가 2–10배 늘었다. 50 stream에서 CUSUM Int의 전력은 복제 방식의 약 1/50이었다(§3.2, §4).

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | 센서 수백 개가 20 Hz 이상으로 보내는 데이터를 Edge 노드가 모아 이상값을 거른 뒤 Cloud로 보낸다. Stream마다 회로를 복제하면 자원과 전력이 stream 수에 비례해 늘어난다(§1, §3) |
| 방법 | 탐지기: CUSUM은 같은 센서의 이웃 값 차이의 누적합이 threshold를 넘으면 이상으로 본다. Z-Score는 최근 N개 window의 평균·표준편차로 \|Z\| > 3이면 이상으로 본다(§3.1) |
| 방법 | 다중 stream CUSUM: 값마다 stream ID를 붙인다. Stream마다 register 3개(직전 값, 양·음 누적합)만 따로 두고 mux·demux로 ID에 맞는 register를 고른다. 산술 pipeline과 FIFO는 모든 stream이 함께 쓴다. Stream 값은 임의 순서로 섞여 들어와도 된다(§3.2, Fig. 2a) |
| 방법 | 다중 stream Z-Score: stream마다 window buffer와 running sum 회로를 복제한다. 나눗셈·제곱근 같은 부동소수점 회로는 공유하고 round-robin counter가 차례로 stream을 고른다(§3.2, Fig. 2b) |
| 가정·조건 | Stream별 모델이나 학습 weight가 없다. 모든 stream이 같은 알고리즘을 쓰고 stream마다 parameter를 다르게 준다는 서술은 없다. FPGA tiny는 Basys 3(Artix 7) 150 MHz, FPGA large는 ZCU104 300 MHz. 비교군은 stream마다 회로 복제(naive)와 MCU(RP2040 125 MHz, ESP32 240 MHz)다. 데이터는 무선 노드 20개의 link 품질 측정이고 노드 쌍 하나를 stream 하나로 본다(§4) |

## 결론

- 최대 stream 수(Fig. 3): CUSUM Int는 FPGA tiny 231(naive 24), FPGA large 1,268(naive 417)이고 둘 다 FF가 먼저 모자란다. CUSUM Float는 19(naive 9)·553(naive 188), Z-Score Float는 7(naive 3)·173(naive 46)이다
- Stream별 지연: CUSUM은 S개 stream에서 max{14, 2·S} cycle이고 처리량은 stream 7개에서 포화한다. Z-Score는 31 cycle마다 결과 하나, 8080 + 31·(S − 1) cycle이다. MCU는 CUSUM 201·S–582·S cycle이다(§4, Fig. 4)
- 전력(50 stream): CUSUM Int multi-stream은 FPGA tiny 약 0.48 W, FPGA large 1.02 W이고 naive는 약 50배다. Z-Score는 FPGA large 약 2.84 W, naive 약 58 W, ESP32 약 31 W다(§4, Fig. 5)
- 평가 방식: FPGA 자원은 구현 결과, FPGA 연산 전력은 Vivado post-implementation 추정, MCU 연산 전력과 Wi-Fi 송신 전력은 PPK2 실측이다. 처리량을 보드에서 쟀는지는 원문에 없다. 탐지 정확도 결과는 없다

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| FPGA 하나가 stream 여러 개를 처리한다. 연산 회로는 stream끼리 나눠 쓰고 stream별 state만 따로 둔다. 이 연구도 트랙 1,024개가 compute array 하나를 나눠 쓰고 트랙마다 membrane potential을 둔다. 둘 다 Artix 7을 쓴다 | Lazea 등은 학습 weight가 없는 통계 탐지기이고 모든 stream이 같은 계산을 한다. 이 연구는 장비 ID마다 weight가 다른 SNN 모델 40개(4.97 MiB)를 DDR3에 두고 entry 4개에 적재한다 | [구조] 모델 여러 개의 weight 적재를 다룬다. Offset Assignment와 Grouping으로 같은 모델 추론 요청을 batch로 묶고 PNU-Count로 entry를 교체한다 |
| Stream 값이 섞여 들어오는 순서를 받아들인다 | Lazea 등은 도착 순서를 그대로 처리하고 deadline이 없다. CUSUM의 stream별 state는 register 3개다. 이 연구의 state는 트랙마다 뉴런 706개다(02 §2) | [구조] 12 bit Membrane Storage로 768트랙의 state를 BRAM에 두고 나머지는 DDR3에 둔다. 32 ms deadline 기준 response time을 본다 |
| | Lazea 등은 stream 수에 따른 자원·전력을 naive 복제, MCU와 비교했다 | 없음. 이 연구는 전력을 재지 않았고 트랙 수에 따른 자원 증가를 보이지 않았다 |

## 인용할 때

- Lazea 등이 먼저 했다: 작은 FPGA(Artix 7)에서 연산 pipeline을 stream 수백–천여 개가 시분할로 쓰고 stream별 state만 두는 다중 stream 이상 탐지. 원문은 공유 pipeline을 여러 tenant가 쓰는 선행([9, 23])을 근거로 든다(§2). 트랙끼리 compute array를 나눠 쓰고 트랙마다 state를 두는 것 자체는 신규성으로 주장하지 않는다([09_RELATED_WORK §3](../../design_references/09_RELATED_WORK.md#3-신규성-경계)의 on-chip state 항목)
- 근거 위치: system model §3, 다중 stream 설계 §3.2와 Fig. 2, 최대 stream 수 Fig. 3, 지연 식 §4 Performance와 Fig. 4, 전력 식과 결과 §4 Power Consumption과 Fig. 5
- 주의: 탐지기는 CUSUM과 Z-Score다. HBOS나 DNN은 원문에 없다. 학습한 모델과 모델 교체가 없어 weight 적재 문제는 다루지 않는다
- 주의: Fig. 5 제목은 "Measured"지만 FPGA 연산 전력은 Vivado 추정값이다. 모든 구성에 ESP32 Wi-Fi 송신 전력 372.9 mW를 더했고 naive와 MCU는 그 값을 stream 수만큼 곱했다. 약 50배 차이에는 장치 수만큼 늘어난 송신 전력이 들어 있다
- 비교군: 옮기지 않았다
