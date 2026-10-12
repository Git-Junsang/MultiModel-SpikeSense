# A18: 대규모 SNN FPGA accelerator

원문: `A18_LargeScaleSNN_FPGA_ICANN2012.pdf`
Cheung, Schultz, Luk, ICANN 2012

## 1. 문제

큰 SNN은 state와 synapse weight가 많다. A18은 자주 갱신하는 state를 BRAM에 두고, 큰 synapse data는 DDR3에서 읽는다.

## 2. 구조

한 timestep의 흐름:

1. neuron state update
2. fired neuron ID 전달
3. 해당 synapse weight를 DRAM에서 read
4. target current를 BRAM에 누적
5. 다음 timestep에서 사용

Weight는 source neuron이 fire할 때만 읽는다. 여러 update가 같은 BRAM bank에 몰리지 않도록 DRAM packet을 배치한다.

## 3. 결과

| 항목 | 논문 값 |
|---|---:|
| FPGA | Virtex-6 SX475T |
| Clock | 100 MHz |
| DRAM bandwidth | 38.4 GB/s |
| Branch | 48 |
| LUT / FF / BRAM / DSP | 80,212 / 90,669 / 268 / 20 |
| 64K neuron 추정 속도 | real-time의 2.5배 |

성능은 논문의 추정값이다. Memory bandwidth가 bottleneck이라 clock만 높여도 이득이 작다고 설명한다.

## 4. 우리 연구에 쓰는 범위

공통점:

- 자주 바뀌는 state는 on-chip
- 큰 weight는 off-chip
- BRAM bank conflict를 줄이는 layout 필요

차이:

- A18은 단일 network simulation이다.
- model cache 교체와 request deadline이 없다.
- A18의 on-chip state는 누적 synaptic current다. 우리 state는 track별 membrane이다.

On-chip state와 off-chip weight 구성은 기존 기법이다. 우리 연구는 여러 model의 cache와 여러 track의 실행 순서를 다룬다.

MIG와 memory interface resource도 실제 구현에서 측정해야 한다는 근거로 쓴다.

원문 확인: 구조 §3, platform §4, resource·성능 §5.
