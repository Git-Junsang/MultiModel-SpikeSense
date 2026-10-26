# 03. 가속기 구조와 연산

## 1. 요약

시스템은 Host, Gigabit Ethernet, FPGA, DDR3로 이루어진다. Host는 특징 추출, Offset Assignment, 최종 판정을 맡는다. FPGA는 request table, Grouping scheduler, DMA, weight cache(next-use predictor 포함), membrane bank, 64-lane compute array를 가진다. DDR3에는 모델 40개의 weight와, BRAM에 두지 못한 트랙의 membrane potential을 둔다.

Entry 4개와 on-chip 768트랙은 비교 실험에 쓴 구성이고 최종 자원 배분은 아니다. Entry 수는 목표 Host의 지연을 잰 뒤 정한다([04_MEMORY.md](04_MEMORY.md) §4).

RTL은 compute array(weight entry 포함, P4.1)와 Membrane Storage(P4.2)까지 있다. 나머지 block은 없다. Host program은 `software/host`에 있다([06_HOST_INTERFACE.md](06_HOST_INTERFACE.md) §2).

## 2. 전체 구조

![시스템 구조](../../analysis/figure/architecture/fig1_x-dataflow_y-block.png)

```text
Host ── Gigabit Ethernet (RGMII) ── eth_mac ─┬─ udp_rx ──► ingest ──► req_table ──► track_scheduler (Grouping)
                                              ├─ udp_tx ◄── result            │               │ 다음 모델
                                              └─ ctrl ◄──► regs              │ 도착 수·첫 도착 │
                                                   (offset table, 지연 예측 표) ▼               ▼
                                                                    next_use_predictor ──► weight_entry ×4
                     dma ── AXI 256 bit ── MIG ── DDR3                              (victim)        │
                      ├──► weight_entry (한 batch 앞 prefetch)                                       ▼
                      └◄─► membrane_buf ◄──► membrane_bank (on-chip 트랙, 12 bit) ◄──► compute_array (64 lane) ──► result
```

| Block                               | 역할                                                                                                           | 상태                                                                                 |
| ----------------------------------- | -------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| `eth_mac`, `udp_rx`, `udp_tx` | Ethernet MAC과 UDP 받기·보내기                                                                                | `verilog-ethernet` 사용, framing은 [06_HOST_INTERFACE.md](06_HOST_INTERFACE.md) §4 |
| `ctrl`, `regs`                  | 상태·제어·counter. 시작할 때 Host가 offset table, 지연 예측 표(모델 그룹 지연·jitter), 트랙·모델 수를 쓴다 | 주소 공간과 제어 packet은 [06_HOST_INTERFACE.md](06_HOST_INTERFACE.md) §7            |
| `ingest`                          | 받은 추론 요청을 검사해 `req_table`과 모델별 list에 넣는다. 모델·주기마다 도착 수와 첫 도착 시각을 센다     | 설계                                                                                 |
| `req_table`                       | 트랙마다 추론 요청 1개(입력, `t_host`, 도착 시각, 순번, flag)                                                | 설계                                                                                 |
| `track_scheduler`                 | 다음 batch의 모델과 구성원을 고른다(Grouping)                                                                  | [05_SCHEDULING.md](05_SCHEDULING.md) §3                                              |
| `next_use_predictor`              | 모델마다 다음 사용 시각을 예측해 victim을 고른다(PNU-Count)                                                    | 제안. RTL 없음                                                                       |
| `weight_entry`                    | 모델 1벌의 weight와 누설 계수·threshold. 4개, 하나에 28.5 tile                                                | RTL 있음(P4.1)                                                                       |
| `dma`                             | weight 적재(한 batch 앞 prefetch), DDR3 트랙의 membrane potential 읽기·쓰기. AXI4 master 256 bit              | 설계                                                                                 |
| `membrane_bank`                   | on-chip 트랙의 membrane potential(12 bit). 768트랙 187 tile                                                    | RTL 있음(P4.2)                                                                       |
| `membrane_buf`                    | DDR3 트랙 membrane potential의 준비·연산·되쓰기 buffer 2개                                                   | RTL 있음(P4.2)                                                                       |
| `compute_array`                   | 64-lane MAC, spike 0 건너뛰기(cycle마다 spike input 2개), layer 4 reduction                                    | RTL 있음(P4.1)                                                                       |
| `plif_array`                      | 누설·적분·발화·soft reset, cycle마다 16뉴런                                                                 | RTL 있음(P4.1)                                                                       |
| `result`                          | 결과 packet을 연산이 끝나자마자 `udp_tx`로 보낸다                                                            | 설계                                                                                 |

가속기는 MIG `ui_clk` 100 MHz에서 동작한다. Ethernet MAC은 RGMII 125 MHz 쪽에 있고 두 clock 사이는 `verilog-ethernet`의 비동기 FIFO로 넘긴다.

## 3. 처리 순서

1. Host는 추론 요청이 준비되면 바로 보낸다(즉시 송신). 추론 요청 packet에는 그 모델·주기의 예상 추론 요청 수를 싣는다(PNU-Count가 쓴다, [06_HOST_INTERFACE.md](06_HOST_INTERFACE.md) §4.1).
2. `ingest`가 추론 요청을 검사한다. 통과하면 `req_table[track_id]`에 넣고 모델 list 끝에 붙인다. 같은 트랙의 이전 추론 요청 결과를 아직 보내지 않았으면 새 추론 요청은 버린다(drop). 결과는 연산이 끝난 뒤, DDR3 트랙은 쓰기 응답 뒤에 나간다(6).
3. Batch i의 연산이 시작되면 scheduler가 batch i+1의 모델을 고른다. 그 모델이 entry에 없으면 predictor가 victim을 고르고 `dma`가 모델 전체를 그 entry로 적재한다. 연산 중인 entry와 적재 대상은 victim 후보에서 뺀다.
4. 적재가 끝나고 compute array가 비면 batch i+1의 구성원을 정한다. 그 시각까지 도착한 같은 모델 추론 요청이 모두 들어간다. 연산이 시작된 뒤 도착한 추론 요청은 다음 batch에서 처리한다.
5. 구성원을 하나씩 처리한다. DDR3 트랙은 다음 트랙의 membrane potential을 미리 읽는다. On-chip 트랙은 `membrane_bank`에서 바로 읽는다.
6. 추론이 끝나면 membrane potential을 12 bit로 저장한다. DDR3 트랙은 쓰기 응답을 받은 뒤 결과를 보낸다. 그다음 `req_table`의 그 트랙 칸을 비운다.

2의 drop 규칙 때문에 membrane potential 읽기가 같은 트랙 앞 추론 요청의 쓰기보다 먼저 일어나지 않는다. Drop이 나면 앞 추론 요청은 이미 deadline을 넘긴 것이다. 3–4는 simulator의 "한 batch 앞 적재" 규칙과 같다([simulation_engine.md](simulation_engine.md) §5).

## 4. 연산

### 4.1 Dataflow

64 lane이 출력 뉴런 64개를 하나씩 맡는다(output-stationary). 매 cycle input 하나와 그 input의 weight 64개(word 하나, 64 B)를 읽고 각 lane이 DSP48E1 하나로 누산한다.

| Layer | 출력 그룹 |             input | dense word | spike 0 건너뛰기    |
| ----- | --------: | ----------------: | ---------: | ------------------- |
| 1     |         6 | mel 40 (8 bit 값) |        240 | 건너뛰지 않음       |
| 2     |         4 | layer 1 spike 384 |      1,536 | spike가 1인 input만 |
| 3     |         1 | layer 2 spike 256 |        256 | spike가 1인 input만 |
| 4     |         2 |  layer 3 spike 64 |          2 | reduction           |

layer 4 word k는 출력 k의 weight 64개다. lane j가 `W4[k][j] · s3[j]`를 만들고 64-input adder tree 하나로 더한다. 2 cycle에 출력 2개가 나온다.

### 4.2 spike 0 건너뛰기

layer 2·3은 spike가 1인 input의 weight만 더한다. cycle마다 spike input 2개를 처리한다. Entry BRAM의 두 번째 port로 weight word를 하나 더 읽고 DSP pre-adder로 두 값을 함께 더한다. `dma`는 연산 중이 아닌 entry에만 쓰므로 연산 중인 entry의 두 번째 port는 비어 있다.

```text
추론 1번 = 240 + 4⌈n1/2⌉ + ⌈n2/2⌉ + 2 + 67 cycle
           L1    L2         L3        L4  control overhead
```

| 입력                                 |                            cycle | 100 MHz에서 |
| ------------------------------------ | -------------------------------: | ----------: |
| 실데이터 2,480 추론 평균             |                            535.9 |    5.36 µs |
| 실데이터 최대                        |                              621 |    6.21 µs |
| 모든 spike 발생 (n1 = 384, n2 = 256) | 240 + 768 + 128 + 2 + 67 = 1,205 |   12.05 µs |

n1·n2는 layer 1·2에서 spike가 난 뉴런 수다(실데이터 평균 n1 85.6, n2 108.9). 다음 spike를 미리 모르므로 weight는 모두 적재한다. spike 0 건너뛰기는 DDR3 traffic을 바꾸지 않고 연산 시간만 바꾼다.

### 4.3 PLIF와 control overhead

한 그룹의 누산이 끝나면 64개 결과를 shadow register에 잡고 `plif_array`로 넘긴다. `plif_array`는 cycle마다 16뉴런을 갱신해 4 cycle에 끝낸다. 그동안 `compute_array`는 다음 그룹을 누산한다. 누설 곱 뒤에는 timing을 맞추려고 register를 하나 넣었다.

layer 경계에서는 앞 layer의 PLIF가 끝나야 다음 layer를 시작한다. 다음 layer의 input 목록이 그때 완성되기 때문이다.

| 구간                             |    cycle |
| -------------------------------- | -------: |
| layer 1→2, 2→3, 3→4 경계      | 각 약 17 |
| layer 4 adder tree와 마지막 PLIF |    약 16 |
| 합계(RTL 측정)                   |       67 |

출력은 layer 4 membrane potential 2개이고 soft reset 뒤 값이다. 정수 규칙은 [02_MODEL.md](02_MODEL.md) §4에 있다.

### 4.4 RTL 확인 결과

| 항목             | 결과                                                                                                                                                                                                                                                      |
| ---------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| bit 일치         | `golden_l64`(16 bit 저장)와 `golden_l64_m12`(12 bit 저장) 각 82개, 추론 2,542개에서 layer별 값과 출력이 모두 일치(xsim, Verilator)                                                                                                                    |
| 연산 cycle       | §4.2 표. engine의 cycle 식과 실데이터 2,480 추론 모두 같다                                                                                                                                                                                               |
| timing           | compute array, entry 4개, 출력 mux, 1트랙 state RAM의 out-of-context 배치·배선에서 100 MHz, WNS +0.311 ns                                                                                                                                                |
| 자원             | `compute_array` LUT 5,027, FF 2,783, DSP 80. Entry 하나 28.5 tile                                                                                                                                                                                       |
| Membrane Storage | `golden_l64_m12` 82개를 트랙 82개(on-chip 60, DDR3 22)로 돌려 bit 일치, 같은 모델 트랙을 번갈아 처리해도 섞이지 않음, `RESET_STATE`면 DDR3를 읽지 않음(xsim, Verilator). Entry 4개와 768트랙 bank를 함께 배선해 100 MHz, WNS +0.348 ns, BRAM 301 tile |

bit 정확도와 cycle은 RTL simulation 결과이고 보드 실측이 아니다.

## 5. RTL 완료 기준

| 항목                    | 기준                                                                                                  | 상태                     |
| ----------------------- | ----------------------------------------------------------------------------------------------------- | ------------------------ |
| 정수 연산               | `golden_l64` 82개, `golden_l64_m12` 82개와 layer별 bit 일치                                       | compute array 완료(P4.1) |
| 연산 cycle              | 추론마다 `240 + 4⌈n1/2⌉ + ⌈n2/2⌉ + 2 + 67`. 모든 spike 발생에서 1,205 cycle                     | 완료(P4.1)               |
| 트랙 분리               | 같은 모델을 쓰는 트랙의 membrane potential이 섞이지 않음, `RESET_STATE` 동작                        | 완료(P4.2)               |
| cache                   | PNU-Count 교체. 연산 중 entry와 적재 대상 보호. 예측이 같으면 queue가 빈 모델, 그다음 오래 안 쓴 모델 | P4.3                     |
| DMA 대기                | 적재가 늦을 때 연산 정지와 정지 cycle counter                                                         | P4.4                     |
| membrane potential 순서 | 이전 추론 요청의 결과를 보내기 전에 온 같은 트랙 추론 요청을 버림(drop, `ERR_CODE` 5)               | 완료(P4.5·P4.6)         |
| timing                  | MIG·Ethernet MAC·scheduler를 포함한 전체 설계가 100 MHz                                             | P5.1                     |

## 6. 검증과 한계

| 항목            | 위험                                                                                                                                                                                                                                            | 확인 시점 |
| --------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------- |
| 전체 timing     | out-of-context 결과다. 가장 느린 경로는 register 하나가 BRAM 수백 개로 퍼지는 배선이다(entry 출력 register enable 여유 0.311 ns, bank 주소 0.348 ns). 배치가 달라지면 여기부터 실패할 수 있고, 그때는 이 신호를 entry나 sub 메모리마다 복제한다 | P5.1      |
| predictor 자원  | 모델별 첫 도착 시각(40 × 32 bit), 모델 그룹 지연 예측 표, 계수기. LUT·FF·BRAM과 예측 표 근사 오차를 확인하지 않았다. Simulation은 0.5 tile을 예약했다                                                                                        | P4.3      |
| controller 크기 | Grouping은 대기 시간이나 deadline 점수가 없어 제어가 단순하다. 줄어든 자원은 RTL로 확인하지 않았다                                                                                                                                              | P4.5      |
| Ethernet MAC    | BRAM·LUT 사용량, clock 경계                                                                                                                                                                                                                    | P4.7      |
| 없는 block      | cache controller, DMA, Ethernet 경로                                                                                                                                                                                                            | P4.3~P4.7 |

## 7. 관련 문서

- [04_MEMORY.md](04_MEMORY.md): entry, PNU 교체, Membrane Storage, DDR3 주소
- [05_SCHEDULING.md](05_SCHEDULING.md): Offset Assignment와 Grouping
- [P4.1 보고서](<../reports/P4.1 Research Report.md>): compute array RTL, cycle, timing
- [P4.2 보고서](<../reports/P4.2 Research Report.md>): Membrane Storage RTL, 트랙 분리, bank 합성
- [P3.12 보고서](<../reports/P3.12 Response Time Research Report.md>): spike 0 건너뛰기와 즉시 입출력의 효과
