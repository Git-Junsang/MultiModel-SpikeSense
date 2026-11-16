# 01. 개요와 기준 수치

이 폴더의 문서는 설계 정본이다. 현재 확정한 값을 기록하고, 값이 바뀌면 해당 내용을 고친다. 변경 이력과 근거는 [보고서](../reports/)에 남긴다. 별도 표시가 없는 수치는 simulation 결과다.

## 1. 요약

FPGA 하나로 SNN 모델 40개와 mic 트랙 1,024개를 처리하는 가속기다. 각 트랙은 32 ms마다 추론 요청을 하나 만든다. Host는 frame의 마지막 샘플이 Host에 도착한 시각부터 32 ms 안에 결과를 받아야 한다. 같은 모델을 쓰는 트랙도 membrane potential은 따로 둔다.

병목은 weight 전송이다. 모델 40개의 weight는 4.97 MiB로, 약 1.6 MiB인 BRAM에 모두 들어가지 않는다. Weight를 재사용하지 않으면 DDR3 읽기에 4.17 GB/s가 필요하다. 이는 보드에서 측정한 읽기 bandwidth 3.015 GB/s를 넘는다.

다음 네 기법을 결합해 weight를 재사용하고 BRAM을 나눠 쓴다.

| 기법                            | 위치 | 하는 일                                                                                                         |
| ------------------------------- | ---- | --------------------------------------------------------------------------------------------------------------- |
| Model-Grouped Offset Assignment | Host | 같은 모델을 쓰는 트랙에 같은 offset을 주어 nominal frame 끝 시각을 맞춘다 |
| Grouping                        | FPGA | 이미 도착한 같은 모델 추론 요청을 batch로 묶는다. 추가 추론 요청을 기다리지 않는다                              |
| Predicted-Next-Use (PNU) Weight Cache | FPGA | queue, Host 처리 지연 분포, 예상 추론 요청 수로 다음 사용 시각을 예측한다. 가장 늦게 쓸 모델을 내보낸다(PNU-Count) |
| 12 bit Membrane Storage         | FPGA | membrane potential을 16 bit로 계산하고 12 bit로 저장한다. Weight cache를 배치하고 남는 BRAM에 일부 트랙의 state를 둔다 |

Xeon Host(CPU 고정·부하 없음)에서 측정한 모델 그룹 지연에 추론 요청별 지연 j ~ Uniform(0, 0.8 ms)를 더해 simulation했다. 제안 기법의 DDR3 traffic은 6.38 KiB/추론으로, Dysta Method보다 88.7% 적다. Host 처리 지연을 포함한 response time의 관측 최대는 9.58 ms로 9.4% 짧다. 준비 완료 뒤 response time의 관측 최대는 1.42 ms로 79.5% 짧다. Deadline miss와 drop은 없다.

추론 요청별 지연을 Uniform(0, 3.2 ms)로 늘리면 DDR3 traffic은 12.37 KiB/추론이 된다. Dysta Method 대비 감소 폭은 78.9%다([08_EVALUATION.md](08_EVALUATION.md) §4).

FPGA의 모든 block을 RTL로 구현했다. MIG와 Ethernet을 포함한 전체 설계는 100 MHz에서 배치·배선 timing을 만족한다. 보드에 Xeon Host를 Ethernet으로 직결해 1,024트랙 실시간 입력을 처리했다. FPGA 출력은 INT8 software reference와 bit 단위로 같았고, 받은 결과 중 32 ms를 넘은 것은 없었다([P5.3 보고서](<../reports/P5.3 Research Report.md>)). 최종 Host인 라즈베리파이 5(8 GiB)와 Ethernet 링크 지연은 아직 측정하지 않았다. 32 ms hard deadline 보장은 주장하지 않는다([05_SCHEDULING.md](05_SCHEDULING.md) §6).

## 2. 기준 수치

| 항목 | 값 | 근거 | 상태 |
|---|---|---|---|
| 모델 수 | 40. DCASE 2020 Task 2의 6종 장비 41개 ID에서 fan_id00을 뺐다 | P2.2, [02_MODEL.md](02_MODEL.md) §3 | 확정 |
| 트랙 수 | 1,024 | P3.9 | 확정 |
| 추론 요청 주기 | 트랙마다 32 ms (hop 512샘플 @ 16 kHz) | 특징 추출 규칙 | 확정 |
| deadline | frame 마지막 샘플의 Host 도착 + 32 ms. Host 결과 수신 기준 | P3.25 | 확정 |
| 모델 | L `40→384→256→64→2`, PLIF SNN, INT8 weight 130,176 B, 뉴런 706개, bias 없음 | P3.6 | 확정 |
| compute array | 64 lane, output-stationary, 100 MHz | P4.1 RTL | 전체 설계 배치·배선 100 MHz 만족(P4.10) |
| 연산 | layer 2·3에서 spike 0 건너뛰기, cycle마다 spike input 2개, control overhead 67 cycle | P4.1 RTL | RTL simulation, 보드 확인 |
| Host | Model-Grouped Offset Assignment(`O_m = m × 0.8 ms`), 즉시 송신 | P3.13, P3.25 | 라즈베리파이 5 Host 처리 지연 실측(P3.16, [06_HOST_INTERFACE.md](06_HOST_INTERFACE.md) §9.2) |
| scheduler | Grouping. 기다리지 않고 선점하지 않는다 | P3.13, P3.26 | 확정, RTL 확인(P4.5) |
| weight cache | PNU-Count, entry 4개 | P3.25, P3.26, P3.17 | 확정, RTL 확인(P4.3). 라즈베리파이 5 측정값으로 entry 2–10 모두 miss 0. Entry 2가 DDR3 traffic 2.1% 적지만 지금 bitstream의 4개를 유지한다(P3.17) |
| entry 크기 | 28.5 tile (RAMB36 28개 + RAMB18 1개) | P4.1 합성 | 확정 |
| membrane potential | 16 bit 포화 연산, 12 bit 저장. Entry 4이면 768트랙 on-chip(187 tile), 256트랙 DDR3 | P3.13, P3.25, P4.2 RTL | RTL simulation, 보드 확인. On-chip 트랙 수는 entry 수를 따른다 |
| BRAM 예약 | 링크·request table·준비 buffer 50 tile, predictor 0.5 tile | P3.25 | Simulation 예산. 배치·배선에서는 15.5 tile, predictor 1 tile(P4.10) |
| Host 링크 | Gigabit Ethernet (RGMII), UDP | 사용자 결정 | RTL·보드 동작 확인(P4.7, P5.2). 라즈베리파이 5 직결 지연 실측: 입력 p50 22 µs, 결과 p50 38 µs·최대 126 µs(P3.16) |
| 최종 Host | 라즈베리파이 5 (8 GiB) | 사용자 결정 | 1,024트랙 실시간 처리 확인(P3.16). USB mic 2개 입력으로 보드 end-to-end 확인(P5.4) |
| 보드 | ALINX AX7A200B, XC7A200T-2FBG484I, BRAM 365 tile, DDR3 1 GiB 800 MT/s | 보드 시험 | 확정 |
| DDR3 | 순차 읽기 3.015 GB/s, 쓰기 2.768 GB/s | P3.1 보드 실측 | 확정 |

센서를 FPGA에 직접 연결하는 입력, online 학습, 실행 중 모델 교체, 이상 점수에 따른 우선순위는 필수 범위에 포함하지 않는다.

## 3. 용어

용어의 뜻과 표기 규칙은 [TERMS.md](../TERMS.md)에 있다.

## 4. 시간 기준

```text
t_host   frame 마지막 샘플이 Host에 들어온 시각
t_ready  Host가 특징 추출을 마쳐 추론 요청을 보낼 준비가 된 시각
t_send   Host가 추론 요청을 보낸 시각. 즉시 송신이면 t_ready
t_arr    추론 요청이 FPGA에 도착한 시각
t_done   FPGA 연산 완료
t_recv   Host가 결과를 받은 시각

deadline          = t_host + 32 ms
response time     = t_recv − t_host
Host 처리 지연    = t_ready − t_host = G(m(i), k) + j(i, k)
```

- Mic–Host 지연은 response time과 deadline에 넣지 않는다. 따로 재서 보고한다.
- 48 kHz mic 입력은 Host가 16 kHz로 resampling한다. Resampler는 지난 샘플만 쓰므로 계산 시간만 Host 처리 지연에 들어간다. Filter group delay(0.625 ms)는 frame이 그만큼 앞선 소리를 담게 할 뿐이므로 mic–Host 지연 쪽에 넣어 따로 보고한다([06_HOST_INTERFACE.md](06_HOST_INTERFACE.md) §2).
- Offset Assignment는 frame을 자르는 위치만 정한다. 어떤 offset을 받아도 deadline은 `t_host + 32 ms`다.
- 같은 트랙에서 뒤 주기 추론 요청이 먼저 준비되면, 그 준비 시각을 앞 주기의 준비 시각보다 이르지 않게 조정한다.
- Host는 frame 경계를 FPGA 주기에 맞춘다([06_HOST_INTERFACE.md](06_HOST_INTERFACE.md) §5). 오디오 장치의 sample clock drift도 Host가 보정한다.

Host와 FPGA의 시각 맞추기는 [06_HOST_INTERFACE.md](06_HOST_INTERFACE.md) §5에 있다.

## 5. 용량과 처리량

### 5.1 크기

```text
weight 1벌            = 15,360 + 98,304 + 16,384 + 128 = 130,176 B
weight 40벌           = 4.97 MiB
누설 계수·threshold   = 706 × 2 B = 1,412 B
모델 1개 DMA 적재량   = 131,648 B (parameter와 32 B 정렬 포함, DMA 한 번)
membrane potential    = 706 × 12 bit = 1,059 B/트랙 (계산은 16 bit, 1,412 B). DDR3 전송은 32 B beat 34개 = 1,088 B
weight cache entry    = 28.5 tile, entry 4개 = 114 tile
```

### 5.2 DDR3 전송

```text
T_read                = 0.244 µs + B ÷ 3.015 GB/s
T_write               = B ÷ 2.768 GB/s
재사용 없음           = 1,024 × 31.25 × 130,176 B/s = 4.17 GB/s  > 3.015 GB/s
주기마다 모델당 1번   = 40 × 31.25 × 130,176 B/s = 162.7 MB/s
weight 적재 1번       = 0.244 µs + 131,648 B ÷ 3.015 GB/s = 43.91 µs
membrane potential    = 1,088 B 읽기 + 쓰기 = 1.24 µs/추론 (DDR3 트랙만)
```

B는 전송할 byte 수다. 0.244 µs는 DDR3 read 한 번을 시작할 때 드는 고정 지연이다.

### 5.3 연산

```text
추론 1번 = 240 + 4⌈n1/2⌉ + ⌈n2/2⌉ + 2 + 67 cycle
```

n1·n2는 layer 1·2에서 spike가 난 뉴런 수다. 67은 control overhead다. 100 MHz에서 실데이터 평균은 535.9 cycle(5.36 µs), 모든 spike가 발생하면 1,205 cycle(12.05 µs)이다. 세부는 [03_ARCHITECTURE.md](03_ARCHITECTURE.md) §4.2에 있다.

### 5.4 FPGA 작업량

아래 식은 모든 입력 spike가 발생하고, 모델·주기마다 weight를 한 번씩만 적재할 때의 FPGA 작업량이다. Entry 4개, on-chip 768트랙, DDR3 256트랙 조건에서 적재 시간과 연산 시간을 겹치지 않고 더했다.

```text
R_single = N·C_dense + M·L_weight + N_DDR·C_state
         = 1,024 × 12.05 µs + 40 × 43.91 µs + 256 × 1.24 µs ≈ 14.41 ms
```

N은 전체 트랙 수, N_DDR은 membrane potential을 DDR3에 두는 트랙 수다. C_dense는 control overhead를 포함한 1,205 cycle, L_weight는 모델 하나의 적재 시간, C_state는 트랙 하나의 membrane potential 읽기·쓰기 시간이다. 이 값을 쓴 조건부 response time과 그 한계는 [05_SCHEDULING.md](05_SCHEDULING.md) §6에 있다.

## 6. 미정 사항

| 항목 | 정할 방법 | 문서 |
|---|---|---|
| entry 수와 on-chip 트랙 수 | 목표 Host의 Host 처리 지연을 재서 재실험. 배치·배선에서 남은 BRAM 47.5 tile의 쓰임도 함께 정한다 | [04_MEMORY.md](04_MEMORY.md) §2, §4 |
| Host 처리 지연 상한과 Host 규칙 | 목표 Host 측정 | [06_HOST_INTERFACE.md](06_HOST_INTERFACE.md) §9 |
| Ethernet 지연·packet 간격 | 측정 | [06_HOST_INTERFACE.md](06_HOST_INTERFACE.md) §8 |
| 결과 손실 | 라즈베리파이 5에서 같은 입력으로 측정 | [06_HOST_INTERFACE.md](06_HOST_INTERFACE.md) §8 |
| hard deadline 분석 | Host·링크 지연 상한, packet 분할 뒤 적재, 주기 사이 잔여 작업을 제한하는 운용 규칙 | [05_SCHEDULING.md](05_SCHEDULING.md) §6 |
| mic–Host 지연, sample clock drift | 측정 | [06_HOST_INTERFACE.md](06_HOST_INTERFACE.md) §9 |
| 실시간 특징 정규화의 mic 확인 | mic별 하한 정하기, mic를 붙인 긴 stream | [02_MODEL.md](02_MODEL.md) §5 |
| 신규성 확인 | IEEE Xplore 검색, 원문 확인 | [TASKS.md](../TASKS.md) P3.18 |
| 전력 측정 방법 | 보드 계측 방법 결정 | [08_EVALUATION.md](08_EVALUATION.md) §5 |

## 7. 문서

| 문서                                        | 내용                                                        |
| ------------------------------------------- | ----------------------------------------------------------- |
| [02_MODEL.md](02_MODEL.md)                   | 모델, 학습, 정수 규칙, export 형식, 판정                    |
| [03_ARCHITECTURE.md](03_ARCHITECTURE.md)     | 가속기 구조, 처리 순서, 연산, RTL 완료 기준                 |
| [04_MEMORY.md](04_MEMORY.md)                 | BRAM 배분, weight cache와 교체, Membrane Storage, DDR3 주소 |
| [05_SCHEDULING.md](05_SCHEDULING.md)         | Model-Grouped Offset Assignment, Grouping, deadline 분석    |
| [06_HOST_INTERFACE.md](06_HOST_INTERFACE.md) | Host 역할, Ethernet, packet, 시각, register, 측정 계획      |
| [07_SIMULATION.md](07_SIMULATION.md)         | 비용 모델, Host 처리 지연 모델, workload, simulator         |
| [08_EVALUATION.md](08_EVALUATION.md)         | 지표, 비교 방법, 실험 목록                                  |
| [09_RELATED_WORK.md](09_RELATED_WORK.md)     | 선행연구와 신규성 경계                                      |

진행 상황은 [TASKS.md](../TASKS.md), 실험 결과는 [보고서](../reports/)에 있다.
