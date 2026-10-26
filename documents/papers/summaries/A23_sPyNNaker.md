# A23: sPyNNaker

원문: `A23_sPyNNaker_FrontNeurosci2018.pdf`
Oliver Rhodes, Petruț A. Bogdan, Christian Brenninkmeijer, Simon Davidson, Donal Fellows, Andrew Gait, David R. Lester, Mantas Mikaitis, Luis A. Plana, Andrew G. D. Rowley, Alan B. Stokes, Steve B. Furber, Frontiers in Neuroscience 12:816, 2018, DOI 10.3389/fnins.2018.00816
읽은 범위: 원문 전체(Supplementary Material 제외)

## 한 줄 요약

SpiNNaker의 ARM core에서 PyNN으로 정의한 SNN을 realtime으로 돌리는 software package다. Neuron state는 DTCM에 두고 synapse row는 spike가 올 때만 SDRAM에서 DMA로 가져와 fully-connected network에서 core 하나가 1 ms에 synaptic event 5,000개 이상을 처리했다.

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | 범용 ARM core로 큰 SNN을 생물학적 realtime(1 ms timestep을 1 ms 안에)으로 simulation한다 |
| 방법 | neuron 갱신은 timer마다 하는 time-driven, synapse 처리는 spike가 올 때 하는 event-driven이다(§3.2, Figure 4) |
| 방법 | neuron state와 model parameter는 core의 DTCM(64 kB)에 둔다. Fan-in이 커서 synapse 데이터는 DTCM에 두지 못하고 칩 공유 SDRAM(128 MB)에 둔다(§3.1, §3.2) |
| 방법 | spike가 오면 source neuron ID로 master population table과 address list를 찾고 synaptic matrix의 그 row를 DMA로 DTCM에 복사한다. Row word는 32 bit이고 위 16 bit가 weight다. DMA 시간은 다른 callback 처리 뒤에 숨긴다(§3.2.4–3.2.6, Figure 7–9) |
| 가정·조건 | SpiNNaker 칩(ARM968 core 18개, 200 MHz). Core당 neuron 기본값 255개. Network 하나를 여러 core에 나눈다. 추론 요청이나 deadline 개념이 없다 |

## 결론

- Random balanced network(excitatory 500·inhibitory 125 neuron, core 5개)를 5 s 동안 realtime으로 돌렸고 모든 spike를 전달·처리했다(§4.1, Figure 10)
- Cost model(식 (8), Table 2)이 측정과 맞았다. Core당 neuron 128개, 연결 확률 1에서 timer event 사이에 synaptic event를 최대 5,922개 처리했다(§4.2, Figure 11)
- Core당 neuron 255개인 fully-connected network에서 ms당 synaptic event 5,000개 이상을 처리했다. 설계 목표(core당 ms당 10,000개)의 절반 이상이다(§5)
- 평가 방식: SpiNNaker 실측과 cost model 예측

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| 자주 쓰는 state는 on-chip에, 큰 weight는 off-chip(SDRAM, DDR3)에 둔다 | sPyNNaker는 spike마다 그 source neuron의 row만 DMA로 읽고 network 하나를 다룬다. 이 연구는 모델 40개를 다룬다 | [구조] weight를 모델 단위 entry 4개에 cache하고 PNU-Count로 가장 늦게 쓸 모델을 내보낸다. Grouping이 같은 모델 추론 요청을 batch로 묶는다 |
| state를 연산 장치 안 메모리에 둔다 | sPyNNaker는 core당 neuron 255개의 state를 DTCM 64 kB에 둔다. 이 연구는 트랙마다 membrane potential을 따로 둔다 | [구조] 12 bit Membrane Storage로 남는 BRAM에 768트랙의 state를 둔다 |

## 인용할 때

- sPyNNaker가 먼저 했다: neuron state는 core 안 메모리(DTCM)에, synapse 데이터는 off-chip SDRAM에 두고 spike마다 row를 DMA로 가져오는 배치. On-chip state와 off-chip weight 배치 자체는 신규성으로 주장하지 않는다(09 §3)
- 근거 위치: 메모리 계층 §2.1과 Figure 1, state 위치 §3.1·§3.2, row DMA §3.2.4와 Figure 7, row 구조 §3.2.5와 Figure 8, DTCM 사용량 §4.2와 Figure 12
- 주의: realtime은 생물학적 시간 기준이다(1 ms timestep을 1 ms 안에, §3.2.2). 추론 요청별 deadline과 다르다. 자주 spike를 보내는 source의 synaptic matrix는 DTCM에 둘 수도 있다(§3.4.1)
- 비교군: P3.11 §3.2는 sPyNNaker를 '참고'로만 두고 비교군으로 옮기지 않았다. 거기 적힌 'state 위치가 반대'는 membrane potential을 DDR3에 둔 당시 조건(P3.11 §1.1) 기준이다. 지금은 768트랙의 state를 BRAM에 둔다
