# A25: TSCA

원문: `A25_TSCA_TVLSI2026.pdf`
Musheer Abdullah, De Xu, Muddassar Hussain, Chen Zhao, Wu Gao, IEEE TVLSI 2026(accepted 판, 쪽 번호 미정, 14쪽), DOI 10.1109/TVLSI.2026.3736398
읽은 범위: 원문 전체

## 한 줄 요약

Zynq UltraScale+ FPGA에서 SCNN을 단계마다 다른 정밀도로 돌리는 가속기다(첫 layer ternary weight, 중간 layer 8 bit weight, 분류기 binary weight). 중간 layer 뉴런은 5 bit QIF(quantized integrate-and-fire)로 갱신·저장해 state 저장량을 20 bit IF보다 75% 줄였고 정확도는 최대 0.66%p 떨어졌다.

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | SCNN은 단계마다 계산 성격이 다르다(입력 pixel, 중간 spike convolution, 분류). 같은 engine으로 돌리면 timestep 반복, 분류기의 뉴런 갱신, membrane state 저장이 낭비된다(§I, Table I) |
| 방법 | QIF: 부분합은 full precision으로 누산한다. 그 뒤 QIF 회로가 [0, λ]를 간격 ∆λ(∆ = 0.1, 11단계)로 나눈 index로 바꾸고 부호 bit를 붙여 5 bit로 만든다(§IV-B, §V-D, Fig. 10) |
| 방법 | membrane 누산, threshold 비교, reset-by-subtraction을 모두 5 bit index로 한다. Threshold는 index 10이다. 계산과 저장이 함께 5 bit이고 부분합 누산만 넓다(§IV-B 식 (14)–(16), §V-D) |
| 방법 | TCE는 첫 layer를 ternary weight로 계산하고 threshold LUT로 T timestep의 spike를 한 번에 만든다. DBC는 binary spike와 binary weight를 AND·popcount로 더하고 pooling을 weight 재사용으로 흡수한다(§IV-A, §IV-C, §V-B, §V-F) |
| 방법 | STCE(cluster 16개)는 중간 layer weight를 PS-DDR4에서 AXI-HP port 4개로 받아 ping-pong buffer에 두고 연산과 겹친다. TCE·DBC weight는 on-chip에 둔다(§V-A, §V-C) |
| 가정·조건 | Network 하나(SCNN-5·7·11)를 MNIST·CIFAR-10·CIFAR-100에 쓴다. State는 한 입력의 T = 1–4 timestep 사이에서 이어진다. 입력 사이 state 유지, 여러 모델 전환, 주기 deadline은 원문에 나오지 않는다 |

## 결론

- QIF(∆ = 0.1, 5 bit signed state)는 20 bit IF보다 state 저장을 75% 줄인다. 32 × 32 CIFAR-10/100 입력, cluster 16개에서 327.68 kbit가 81.92 kbit가 된다. BRAM은 RAMB36E2 환산 24개(17.3%), FF는 2K(8.0%) 줄고 LUT는 최대 5K(6.0%) 는다(§VI-C, Table V)
- 정확도 손실은 ∆ = 0.1에서 최대 0.66%p다(CIFAR-100, T = 4: 70.45% → 69.79%). ∆ = 0.05(6 bit)는 1.60%p, ∆ = 0.2(4 bit)는 7.04%p였다. ∆에 따라 단조롭게 변하지 않는다(§VI-C, Table V)
- XCZU7EV 250 MHz에서 LUT 72k–83k, FF 23k–25k, DSP 0, BRAM 114(STCE 66), 전력 4.8–4.9 W(PS 포함)다. CIFAR-10은 91.23%, latency 324 µs, 3.09 kFPS, 629.8 FPS/W다. 가장 깊은 512 × 4 × 4 layer는 연산 2.36 µs가 weight 적재 5.31 µs를 다 가리지 못한다(§VI-D–F, Table IV·VI·VII)
- 평가 방식: Vivado 배치·배선 뒤 timing·전력 보고. Latency·FPS를 보드에서 쟀는지는 원문에 나오지 않는다

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| membrane potential 저장 폭을 줄여 BRAM을 아낀다 | TSCA는 뉴런 갱신도 5 bit index로 하고 값 간격을 ∆λ로 넓힌다. 이 연구는 16 bit로 계산하고 저장할 때만 12 bit로 포화한다. 저장 폭 감소는 TSCA 75%, 이 연구 25%다 | 없음. 저장 폭은 TSCA가 더 좁다 |
| state를 on-chip에 둔다 | TSCA는 아낀 BRAM을 자원 감소로 보고한다. State는 한 입력의 timestep 사이에서만 쓴다. 이 연구는 state가 32 ms 추론 요청 사이에 트랙마다 이어진다 | [구조] 12 bit Membrane Storage로 아낀 BRAM에 768트랙의 state를 둔다 |
| 큰 weight를 off-chip에 두고 연산과 겹쳐 적재한다 | TSCA는 network 하나를 돌린다. 모델 전환, 모델 단위 weight 재사용, 주기 deadline이 없다 | [구조] 모델 40개(weight 4.97 MiB)를 entry 4개에 두고 PNU-Count로 교체한다. Grouping이 같은 모델 추론 요청을 batch로 묶는다 |

## 인용할 때

- Abdullah 등이 먼저 했다: SCNN 가속기에서 membrane state를 5 bit index로 양자화해 갱신·저장하고 state 저장을 75% 줄였다. 원문은 이것을 "to the best of our knowledge, the first low-bit QIF neurons in an SCNN accelerator"라고 쓴다(§II 기여 2). Membrane potential을 좁은 폭으로 저장해 on-chip 메모리를 아끼는 것 자체는 신규성으로 주장하지 않는다. 09 §3 주장 2는 12 bit Membrane Storage를 Grouping·PNU Cache와 결합한 구조다
- 근거 위치: QIF 식 §IV-B 식 (8)–(16), QIF 회로 §V-D·Fig. 10, ∆ 민감도 §VI-C·Table V, 자원 Table IV·VI, 성능 Table VII, weight streaming §V-C·§VI-F·Fig. 9
- 주의: 75%는 20 bit IF state 대비다(Table V). 16 bit 대비 12 bit(25%)와 같은 기준이 아니다. BRAM 24개·FF 2K는 CIFAR-10/100 구성의 "최대" 절감값이다
- 주의: 저 bit인 것은 뉴런 갱신과 state다. 부분합 누산은 full precision이다(§V-D)
- 주의: 전력은 Vivado 보고값이고 PS 전력을 포함한다. PS가 dynamic 전력의 약 52%다(§VI-A, §VI-D, Fig. 13)
