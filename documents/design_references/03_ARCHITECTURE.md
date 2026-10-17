# 03. 가속기 구조와 연산

## 1. 요약

시스템은 Host, Gigabit Ethernet, FPGA, DDR3로 이루어진다. Host는 특징 추출, offset 배정, 최종 판정을 맡는다. FPGA는 request table, Grouping scheduler, DMA, weight cache entry 4개, membrane bank, 64-lane compute array를 가진다. DDR3에는 모델 40개의 weight와 BRAM에 들어가지 않은 256트랙의 membrane potential을 둔다.

compute array 하나가 모든 트랙의 추론을 차례로 처리한다. 모델을 바꿀 때만 weight를 적재하고 결과는 연산이 끝나자마자 Host로 보낸다.

## 2. 전체 구조

```text
Host ── Gigabit Ethernet (RGMII) ── eth_mac ─┬─ udp_rx ──► ingest ──► req_table
                                              ├─ udp_tx ◄── result
                                              └─ ctrl ◄──► regs, offset_table
                                                                   │
                     dma ── AXI 256 bit ── MIG ── DDR3 (weight 40벌, DDR3 트랙 membrane potential)
                      │
                      ├──► weight_entry ×4 ──┐
                      └◄─► membrane_buf ◄────┤      membrane_bank (on-chip 트랙, 12 bit)
                                             ▼                 ▲
    track_scheduler ──► compute_array (64 lane) ──► plif_array (16) ──► result
```

| Block | 역할 | 상태 |
|---|---|---|
| `eth_mac`, `udp_rx`, `udp_tx` | Ethernet MAC과 UDP 받기·보내기 | IP와 framing 미정 |
| `ctrl`, `regs` | 상태·제어·counter 읽고 쓰기 | Ethernet 위 접근 방법 미정 |
| `offset_table` | 모델별 offset 번호 40개. Host가 시작할 때 쓴다 | 새로 추가 |
| `ingest` | 받은 추론 요청을 검사해 `req_table`과 모델별 list에 넣는다 | P3.9와 같음 |
| `req_table` | request table. 트랙마다 요청 1개(입력, `t_gen`, 도착 시각, 순번, flag) | P3.9와 같음 |
| `track_scheduler` | 다음 batch의 모델과 구성원을 고른다(Grouping) | [05_SCHEDULING.md](05_SCHEDULING.md) |
| `dma` | weight 적재, DDR3 membrane potential 읽기·쓰기. AXI4 master 256 bit | P3.9와 같음 |
| `weight_entry` | 모델 1벌의 weight와 누설 계수·threshold, 4개 | entry 수는 jitter로 확정 |
| `membrane_bank` | on-chip 트랙의 membrane potential(12 bit) | 새로 추가 |
| `membrane_buf` | DDR3 트랙 membrane potential의 준비·연산·되쓰기 buffer | P3.9와 같음 |
| `compute_array` | 64 lane MAC, spike 0 건너뛰기, layer 4 reduction | 2개/cycle 추가 |
| `plif_array` | 누설·적분·발화·soft reset, cycle마다 16뉴런 | P3.9와 같음 |
| `result` | 결과 packet을 연산이 끝나자마자 `udp_tx`로 보낸다 | Host가 읽어 가던 방식에서 바뀜 |

가속기는 MIG `ui_clk` 100 MHz에서 동작한다. Ethernet MAC은 RGMII 125 MHz 쪽에 있고 두 clock 사이는 비동기 FIFO로 넘긴다(구현 방법 미정).

## 3. 처리 순서

1. Host가 frame 끝마다 추론 요청을 바로 보낸다. 같은 모델의 요청은 그 모델의 offset 근처에 함께 온다.
2. `ingest`가 요청을 검사한다. 통과하면 `req_table[track_id]`에 넣고 모델 list 끝에 붙인다.
3. batch i의 연산이 시작되면 scheduler가 batch i+1의 모델을 고른다. 그 모델이 entry에 없으면 offset 순서로 내보낼 entry를 골라 적재(prefetch)를 시작한다. 연산 중인 entry는 내보내지 않는다.
4. 적재가 끝나고 compute array가 비면 batch i+1의 구성원을 확정한다. 그 시각까지 도착한 같은 모델 요청이 모두 들어간다. 연산이 시작된 뒤 도착한 요청은 다음 batch에서 처리한다.
5. 구성원을 `t_gen` 순서로 하나씩 처리한다. DDR3 트랙은 다음 트랙의 membrane potential을 미리 읽는다. on-chip 트랙은 `membrane_bank`에서 바로 읽는다.
6. 추론 하나가 끝나면 membrane potential을 12 bit로 저장한다. DDR3 트랙은 쓰기 응답을 받은 뒤 결과를 보낸다. 그다음 `req_table`의 그 트랙 칸을 비운다.

같은 트랙의 다음 요청은 칸이 빈 뒤에만 받는다. 그래서 membrane potential 읽기가 앞 요청의 쓰기보다 먼저 일어나지 않는다. 앞 요청이 deadline 안에 끝나면 다음 요청은 그 뒤에 생기므로, 이 규칙은 deadline miss 때만 걸린다.

3~4는 simulator의 "한 batch 앞 적재" 규칙과 같다([engine.py](../../simulation/engine/engine.py) §2 머리말).

## 4. 연산

### 4.1 Dataflow

64 lane이 출력 뉴런 64개를 하나씩 맡는다(output-stationary). 매 cycle input 하나와 그 input의 weight 64개(word 하나, 64 B)를 읽고 각 lane이 DSP48E1 하나로 누산한다.

| Layer | 출력 그룹 | input | dense word | spike 0 건너뛰기 |
|---|---:|---:|---:|---|
| 1 | 6 | mel 40 (8 bit 값) | 240 | 건너뛰지 않음 |
| 2 | 4 | layer 1 spike 384 | 1,536 | spike가 1인 input만 |
| 3 | 1 | layer 2 spike 256 | 256 | spike가 1인 input만 |
| 4 | 2 | layer 3 spike 64 | 2 | reduction |

layer 4 word k는 출력 k의 weight 64개다. lane j가 `W4[k][j] · s3[j]`를 만들고 64-input adder tree 하나로 더한다. 2 cycle에 출력 2개가 나온다.

### 4.2 spike 0 건너뛰기

layer 2·3은 spike가 1인 input의 weight만 더한다. cycle마다 spike input 2개를 처리한다. entry BRAM의 두 번째 port로 weight word를 하나 더 읽고 DSP pre-adder로 두 값을 함께 더한다. RTL로 확인하지 않은 가정이다.

| 연산 | layer 1 | layer 2 | layer 3 | layer 4 | 제어(가정) | 합계 |
|---|---:|---:|---:|---:|---:|---:|
| dense | 240 | 1,536 | 256 | 2 | 203 | 2,237 cycle = 22.4 µs |
| 건너뛰기, 1개/cycle | 240 | 4 × n1 | n2 | 2 | 203 | 903 cycle = 9.0 µs |
| 건너뛰기, 2개/cycle | 240 | 4 × ⌈n1/2⌉ | ⌈n2/2⌉ | 2 | 203 | 676 cycle = 6.8 µs |

n1·n2는 layer 1·2에서 spike가 난 뉴런 수다. test 입력 80개 평균은 n1 85, n2 109다. 합계는 이 평균으로 셌다. 제어 비용 203 cycle은 dense 2,034 word의 10%로 둔 가정이다. 다음 spike를 미리 모르므로 weight는 모두 적재한다. spike 0 건너뛰기는 DDR3 전송량을 바꾸지 않고 연산 시간과 트랙 한계만 바꾼다.

### 4.3 PLIF

한 그룹의 누산이 끝나면 64개 결과를 `plif_array`로 넘긴다. `plif_array`는 cycle마다 16뉴런을 갱신해 4 cycle에 끝낸다. 그동안 `compute_array`는 다음 그룹을 누산한다. 누산 결과는 shadow register 한 벌에 잡아 둔다. layer 경계에서는 앞 layer의 PLIF가 끝나야 다음 layer를 시작한다. 이 대기는 제어 cycle에 넣었다.

출력은 layer 4 membrane potential 2개이고 soft reset 뒤 값이다. 정수 규칙은 [02_MODEL.md](02_MODEL.md) §4에 있다.

## 5. RTL 완료 기준

| 항목 | 기준 |
|---|---|
| 정수 연산 | `hardware/data/golden_l64/` 82개와 layer별 bit 일치 |
| 연산 cycle | 추론마다 `240 + 4⌈n1/2⌉ + ⌈n2/2⌉ + 2 + 제어`. dense에서도 2,237 cycle 이하 |
| 트랙 분리 | 같은 모델을 쓰는 트랙의 membrane potential이 섞이지 않음, `RESET_STATE` 동작 |
| cache | offset-order 교체, 연산 중 entry 보호 |
| DMA 대기 | 적재가 늦을 때 연산 정지와 정지 cycle counter |
| membrane potential 순서 | 쓰기 응답 전 같은 트랙 요청 거부 |
| timing | 64 lane @ 100 MHz |

## 6. 검증과 한계

| 항목 | 위험 | 확인 시점 |
|---|---|---|
| 64 lane @ 100 MHz | entry 출력 mux와 adder tree. entry가 10개에서 4개로 줄어 mux는 작아졌다 | P4.1 첫 합성 |
| spike 2개/cycle | BRAM 두 번째 port를 DMA 쓰기와 나눠 쓰는 방법, pre-adder 경로 | P4.1 |
| 제어 비용 | 203 cycle 가정. RTL 값에 따라 연산 시간과 트랙 한계가 바뀐다 | P4.1 |
| LUT·DSP | DSP 64개, adder tree, scheduler, Ethernet MAC | P4.1, P5.1 |
| Ethernet MAC | BRAM·LUT 사용량, clock 경계 | P4.7 |

## 7. 관련 문서

- [04_MEMORY.md](04_MEMORY.md): entry, membrane potential, DDR3 주소
- [05_SCHEDULING.md](05_SCHEDULING.md): scheduler와 cache 교체
- [P3.12 보고서](<../reports/P3.12 Latency Research Report.md>): spike 0 건너뛰기와 즉시 입출력의 효과
