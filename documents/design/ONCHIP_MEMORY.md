# 온칩 메모리 구성

이 문서는 32 lane 연산기에 가중치와 막전위를 공급하는 BRAM 구성을 정리한다. 계산 코드는 [bram_plan.py](../../software/analysis_develop/bram_plan.py), 결과는 [bram_plan.md](../../software/analysis_develop/p3_meas/bram_plan.md)다.

## 1. 결론

| 항목 | 구성 | BRAM |
|---|---|---:|
| 모델 entry | 4,096 × 256 bit, Simple Dual Port | 28.5 tile |
| slice double buffer | 512 × 256 bit × 2 | 7.5 tile |
| 512트랙 막전위 | layer별 16 bit bank | 176.5 tile |
| XDMA | 구현 report 실측 | 20.5 tile |
| MIG | 구현 report 실측 | 0 tile |

전체 모델 5개 cache는 구성 D에서만 가능하다. 구성 D는 slice double buffer, entry별 β·vth, distributed RAM queue를 쓴다. MIG·XDMA와 함께 배치한 결과 352 tile에서 100 MHz timing을 통과했다.

## 2. Port와 dataflow

### 2.1 요구량

| 대상 | 요구량 | 구성 |
|---|---:|---|
| 가중치 read | 32 B/cycle | 256 bit read port |
| 가중치 write | 최대 32 B/cycle | MIG AXI 256 bit write port |
| 막전위 | 최대 0.8뉴런/cycle | 16 bit read-modify-write |
| β·vth | 막전위와 같은 속도 | 16 bit/뉴런 |

가중치 RAM은 Simple Dual Port로 만든다. 연산기는 read port, DMA는 write port를 쓴다.

### 2.2 기준 dataflow

출력 뉴런 32개를 lane에 고정하는 output-stationary 방식을 기준으로 한다.

| Layer | word 수 | byte |
|---|---:|---:|
| L1 | 12그룹 × 40입력 = 480 | 15,360 |
| L2 | 8 × 384 = 3,072 | 98,304 |
| L3 | 2 × 256 = 512 | 16,384 |
| L4 | 4 | 128 |
| 합계 | 4,068 | 130,176 |

L4는 `입력 16개 × 출력 2개`를 한 word에 넣는다. 4 cycle이면 끝난다.

DDR3의 현재 `[out, in]` 형식은 lane-interleaved 형식으로 바꿔야 한다. 최종 format은 P3.9에서 정한다.

80개 golden vector에서 zero spike를 건너뛰면 요청당 계산은 평균 1,385 cycle이었다. dense 기준은 4,068 cycle이다. 이 값은 계산만 줄인다. 다음 spike를 미리 모르므로 weight DRAM byte는 줄지 않는다.

## 3. 모델 entry와 slice buffer

### 3.1 모델 entry

```text
4,068 word × 32 B = 130,176 B
entry depth = 4,096 word
```

Vivado는 256 bit word를 9 bit 열로 나눈다. parity bit도 data로 써서 entry 하나가 28.5 tile이 된다. 16 bit 막전위는 parity bit를 못 써서 tile당 32 Kibit만 쓴다.

여러 entry의 output은 pipelined mux로 고른다. 이 경로는 fit 실험에서 100 MHz를 통과했다.

### 3.2 Slice buffer

뉴런 그룹 하나를 slice로 잡으면 크기는 다음과 같다.

| Layer | 최대 slice |
|---|---:|
| L1 | 1,280 B |
| L2 | 12,288 B |
| L3 | 8,192 B |
| L4 | 128 B |

16 KiB buffer 2개는 7.5 tile이다. 한 buffer를 계산하는 동안 다음 slice를 다른 buffer에 받는다.

P3.1 실측식:

```text
t(S) = 0.244 µs + S / 3.015 GB/s
```

L2 slice 전송은 약 4.32 µs다. 한 트랙의 L2 연산은 3.84 µs다. 두 트랙 이상이면 연산 중 전송을 숨길 수 있다는 계산이 나온다. 실제 overlap은 simulation과 RTL에서 확인한다.

## 4. 막전위 bank

| Layer | 깊이 | 폭 | BRAM tile |
|---|---:|---:|---:|
| L1 | `512 × 384` | 16 bit | 96 |
| L2 | `512 × 256` | 16 bit | 64 |
| L3 | `512 × 64` | 16 bit | 16 |
| L4 | `512 × 2` | 16 bit | 0.5 |
| 합계 | 706 KiB data | | 176.5 |

주소는 `track × N_layer + neuron`이다. 한 port로 읽고 다른 port로 같은 주소에 쓴다.

막전위를 DDR3로 옮기면 요청마다 1,412 B read와 1,412 B write가 생긴다. 512트랙에서는 45.18 MB/s다. 대신 model entry를 최대 11개까지 늘릴 수 있다. 이 선택은 상태 전송 비용을 포함해 비교한다.

## 5. 기타 메모리

| 대상 | BRAM | 대안 |
|---|---:|---|
| β·vth 40모델 | 14 tile | entry마다 0.5 tile |
| 요청 queue `512 × 64 B` | 7.5 tile | distributed RAM |
| track metadata | 1 tile | distributed RAM |

## 6. BRAM 예산

### 6.1 기본 계산

```text
전체                   365.0 tile
- XDMA                  20.5
- MIG                    0.0
- 512트랙 막전위       176.5
- model prefetch 1개     28.5
= weight 공간          139.5 tile = 627.75 KiB
```

기존 709.375 KiB 계산과 다른 이유는 16 bit 막전위가 parity bit를 쓰지 못하기 때문이다.

### 6.2 구성 비교

| 구성 | 주요 조건 | model entry | 남는 tile |
|---|---|---:|---:|
| A | prefetch 1개, β·vth 전체, queue BRAM | 4 | 3 |
| B | slice buffer, β·vth 전체, queue BRAM | 4 | 24 |
| C | 별도 buffer 없음, β·vth 전체 | 5 | 3 |
| **D** | slice buffer, entry별 β·vth, queue distributed RAM | **5** | **15** |
| E | 별도 buffer 없음, entry별 β·vth, queue distributed RAM | 5 | 23 |

첫 layer 40개는 142.5 tile이다. 구성 D에는 들어가지만 B에는 4.5 tile이 부족하다.

## 7. Fit 결과

`build_p3.tcl -fit`으로 MIG, XDMA, memory skeleton을 함께 배치했다.

| 구성 | 계산 / 구현 BRAM | LUT | WNS @ 100 MHz | 결과 |
|---|---:|---:|---:|---|
| B, entry 4개 | 344 / 344 tile | 30,850 | +0.093 ns | 통과 |
| D, entry 5개 | 352 / 352 tile | 37,941 | +0.073 ns | 통과 |

구성 D의 요청 queue는 LUTRAM 약 5,500개를 쓴다. 두 설계 모두 Critical Warning이 없었다. 이 결과는 memory 배치 가능성을 확인한 것이다. 전체 가속기 timing 결과는 아니다.

## 8. 남은 결정

| 항목 | 현재안 | 결정 시점 |
|---|---|---|
| 5-entry 기준 | 구성 D | 완료 |
| dataflow | output-stationary 권고 | P3.9 |
| DDR3 format | lane-interleaved v2 권고 | P3.9 |
| slice 크기 | 뉴런 그룹 단위 | P3.8·P3.9 |
| β·vth 위치 | 전체 상주 또는 entry별 | P3.9 |
| 막전위 위치 | 온칩 기준, DDR3 대안 비교 | P3.8·P3.9 |

관련 결과는 [P3.1~P3.4 보고서](<../reports/P3.1~3.4 Research Report.md>)에 있다.
