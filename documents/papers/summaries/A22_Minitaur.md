# A22: Minitaur

원문: `A22_Minitaur_TVLSI2014.pdf`
Daniel Neil, Shih-Chii Liu, IEEE TVLSI 22(12), pp. 2621–2628, 2014, DOI 10.1109/TVLSI.2013.2294916
읽은 범위: 원문 전체

## 한 줄 요약

Spartan-6 FPGA에 입력 spike가 올 때만 계산하는 event-driven SNN 가속기를 구현했다. Weight와 neuron state는 DDR2에 두고 core마다 BRAM cache를 두었으며 1.5 W에서 초당 PSC(postsynaptic current)를 최대 1,873만 개 처리했다.

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | 저전력 FPGA에서 spiking deep network를 돌릴 때 성능은 계산보다 메모리 bandwidth가 막는다(§III-B) |
| 방법 | neuron은 입력 spike가 올 때만 지난 갱신 뒤 흐른 시간만큼 decay하고 weight를 더한다. 계산량이 neuron 수가 아니라 network 활동(spike 수)에 비례한다(§III-A, Algorithm 2) |
| 방법 | neuron ID 아래 5 bit로 neuron을 core 32개에 나눈다. Core마다 state cache(2 kB BRAM, entry 256개)와 weight cache를 direct-mapped로 두고 연속 miss를 세는 reference bit로 교체한다(§IV-B, §IV-C) |
| 방법 | 연결은 layer 범위 규칙(16 B)으로 저장한다. Spike queue에는 보낸 neuron의 주소를 넣고 받는 neuron은 처리할 때 규칙으로 찾는다(§IV-B, §IV-C) |
| 가정·조건 | network 하나를 실행 중에 적재한다(neuron 최대 65,536개). 주기와 deadline이 없다. ZTEX 보드(Spartan-6 LX150, DDR2 128 MB)를 Host PC에 USB로 연결한다 |

## 결론

- 자원과 전력: logic slice 22k(LX150의 23%)와 전력 1.5 W(그중 400 mW는 FPGA 밖 회로)를 쓰고 BRAM 268개 중 200개를 cache로 쓴다. Clock은 logic 75 MHz, DDR2 132 MHz다(§V)
- 최대 585 kevts/s, 초당 PSC 1,873만 개를 처리한다. 모든 메모리 fetch가 local cache에서 나올 때의 값이다. MNIST 작업에서는 초당 488만 개다. 같은 작업을 CPU(Core 2 Duo P7350, 최대 20 W)의 MATLAB 구현은 초당 3,360만 개 처리했다. USB에서 USB까지 236 µs(10,000회 평균)가 걸린다(§V-B, Table II)
- MNIST 92%(784–500–500–10, image마다 입력 spike 1,000개, software에서는 94.2%), 20 newsgroups 71%(10,000–20)다(§V-A)
- 평가 방식: 보드 실측(Host PC Intel Core 2 Duo P7350, USB)

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| FPGA SNN 가속기다. 큰 weight를 off-chip 메모리에 두고 BRAM을 cache로 쓴다 | Minitaur는 network 하나를 다루고 neuron·synapse 단위 direct-mapped cache를 쓴다. 주기와 deadline이 없다 | [구조] 모델 40개(weight 4.97 MiB)를 다룬다. BRAM에는 모델 단위 entry 4개를 두고 PNU-Count로 가장 늦게 쓸 모델을 내보낸다 |
| neuron state를 BRAM에 둔다 | Minitaur는 state를 DDR2에 두고 BRAM에는 core마다 entry 256개의 cache만 둔다. State는 neuron마다 8 B(state 2 B, 마지막 갱신 시각 3 B, refractory 끝 시각 2 B, tag 등 1 B)다 | [구조] 트랙마다 membrane potential을 따로 두고 12 bit Membrane Storage로 남는 BRAM에 768트랙의 state를 둔다 |

## 인용할 때

- Minitaur가 먼저 했다: FPGA SNN 가속기에서 weight와 state를 off-chip DDR2에 두고 BRAM을 cache로 쓰는 구조. Off-chip weight와 on-chip cache 자체는 신규성으로 주장하지 않는다(09 §3)
- 근거 위치: 구조 §IV-B·§IV-C와 Fig. 1, cache 교체 §IV-C 끝, 자원·전력 §V, 처리량 §V-B와 Table II, 정확도 §V-A
- 주의: Fig. 1 설명은 core마다 state cache 2048 kB, weight cache 8192 kB라고 적었다. 본문은 state cache를 2 kB BRAM 하나(entry 256개)로 적었고 칩 전체 BRAM이 549 kB이므로(§IV-A) 본문 값을 쓴다
- 주의: cache 단위는 neuron state와 synapse weight다. 모델 단위 cache의 근거로는 Clockwork나 Ogden 등을 쓴다
