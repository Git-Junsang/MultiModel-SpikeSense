# 01. 개요와 기준 수치

이 폴더는 설계 정본이다. 확정한 값으로 쓰고 값이 바뀌면 고쳐 쓴다. 이력과 근거는 [보고서](../reports/)에 있다. 수치는 따로 적지 않으면 simulation 결과다.

## 1. 요약

FPGA 하나가 SNN 모델 40개로 mic 트랙 1,024개를 처리한다. 트랙마다 32 ms에 추론 요청이 하나 생긴다. Host는 frame 마지막 샘플이 Host에 들어온 시각부터 32 ms 안에 결과를 받아야 한다. 같은 모델을 쓰는 트랙도 membrane potential은 따로 둔다.

병목은 연산이 아니라 weight 전송이다. 모델 40개의 weight는 4.97 MiB인데 BRAM은 약 1.6 MiB다. weight를 재사용하지 않으면 DDR3에 4.17 GB/s가 필요해 보드의 읽기 대역폭 3.015 GB/s를 넘는다.

설계는 네 가지를 묶는다.

| 기법 | 위치 | 하는 일 |
|---|---|---|
| Model-Grouped Offset Assignment | Host | 같은 모델을 쓰는 트랙에 같은 frame offset을 준다. 같은 모델 추론 요청의 nominal 생성 시각이 같아진다 |
| Grouping | FPGA | 이미 도착한 같은 모델 추론 요청을 batch로 묶는다. 추가 추론 요청을 기다리지 않는다 |
| predicted-next-use weight cache | FPGA | queue, Host 지연 분포, 예상 추론 요청 수로 다음 사용 시각을 예측해 가장 늦게 쓸 모델을 내보낸다(PNU-count) |
| 12 bit membrane storage | FPGA | membrane potential을 16 bit로 계산하고 12 bit로 저장한다. 남는 BRAM에 일부 트랙을 둔다 |

Xeon Host(CPU 고정·부하 없음)에서 잰 모델 묶음 지연에 추론 요청별 지연 j ~ Uniform(0, 0.8 ms)를 더한 simulation 결과는 다음과 같다. 제안은 DDR3 전송량이 6.38 KiB/추론으로 Dysta Method보다 88.7 % 적다. Host 처리 지연을 포함한 관측 최대 응답 시간은 9.58 ms로 9.4 % 짧고 준비 완료 뒤 관측 최대는 1.42 ms로 79.5 % 짧다. deadline miss와 drop은 없다. 추론 요청별 지연이 Uniform(0, 3.2 ms)이면 전송량은 12.37 KiB/추론으로 늘고 감소폭은 78.9 %다([08_EVALUATION.md](08_EVALUATION.md) §4).

RTL은 compute array와 membrane storage까지 있다. 최종 Host(라즈베리파이 5 8 GB)와 Ethernet 경로는 재지 않았다. 32 ms hard deadline 보장은 주장하지 않는다([05_SCHEDULING.md](05_SCHEDULING.md) §6).

## 2. 기준 수치

| 항목 | 값 | 근거 | 상태 |
|---|---|---|---|
| 모델 수 | 40. DCASE 2020 Task 2의 6종 장비 41개 ID에서 fan_id00을 뺐다 | P2.2, [02_MODEL.md](02_MODEL.md) §3 | 확정 |
| 트랙 수 | 1,024 | P3.9 | 확정 |
| 추론 요청 주기 | 트랙마다 32 ms (hop 512 샘플 @ 16 kHz) | 특징 추출 규칙 | 확정 |
| deadline | frame 마지막 샘플의 Host 도착 + 32 ms. Host 결과 수신 기준 | P3.25 | 확정 |
| 모델 | L `40→384→256→64→2`, PLIF SNN, INT8 weight 130,176 B, 뉴런 706개, bias 없음 | P3.6 | 확정 |
| compute array | 64 lane, output-stationary, 100 MHz | P4.1 RTL | 전체 설계 timing 미확인 |
| 연산 | layer 2·3에서 spike 0 건너뛰기, cycle마다 spike input 2개, control overhead 67 cycle | P4.1 RTL | RTL simulation 확인 |
| Host | Model-Grouped Offset Assignment(`O_m = m × 0.8 ms`), 즉시 송신 | P3.13, P3.25 | 최종 Host 지연 미측정 |
| scheduler | Grouping. 기다리지 않고 선점하지 않는다 | P3.13, P3.26 | 확정 |
| weight cache | PNU-count, entry 4개 | P3.25, P3.26 | 교체 정책은 PNU-count로 확정(2026-10-24). entry 4개는 비교 실험 구성이고 entry 수는 목표 Host 측정 뒤 |
| entry 크기 | 28.5 tile (RAMB36 28개 + RAMB18 1개) | P4.1 합성 | 확정 |
| membrane potential | 16 bit 포화 연산, 12 bit 저장. entry 4이면 768트랙 on-chip(187 tile), 256트랙 DDR3 | P3.13, P3.25, P4.2 RTL | RTL simulation 확인. on-chip 트랙 수는 entry 수를 따른다 |
| BRAM 예약 | 링크·request table·준비 buffer 50 tile, predictor 0.5 tile | P3.25 | 링크 예약은 PCIe 근거. Ethernet·predictor 합성 전 |
| Host 링크 | Gigabit Ethernet (KSZ9031, RGMII), UDP | 사용자 결정(2026-10-13) | 지연·jitter 미측정 |
| 최종 Host | 라즈베리파이 5 (8 GB) | 사용자 결정(2026-10-24) | 처리량·지연 미측정 |
| 보드 | ALINX AX7A200B, XC7A200T-2FBG484I, BRAM 365 tile, DDR3 1 GiB 800 MT/s | 보드 시험 | 확정 |
| DDR3 | 순차 읽기 3.015 GB/s, 쓰기 2.768 GB/s | P3.1 보드 실측 | 확정 |

같은 모델을 쓰는 트랙도 membrane potential, 입력 순서, 판정 상태는 트랙마다 따로 둔다.

필수 범위가 아닌 것: 센서를 FPGA에 직접 연결하는 입력, online 학습, 실행 중 모델 교체, 이상 점수에 따른 우선순위.

## 3. 용어

문서·코드·그림은 이 표의 표기만 쓴다. 영문 용어는 영문 그대로 쓴다. 그림 글자는 영문이고 한국어 용어의 그림 표기는 뜻 열에 적었다.

### 3.1 workload와 offset

| 용어 | 뜻 |
|---|---|
| 모델 | 학습된 weight 한 벌. 장비 ID 하나마다 하나 |
| 트랙 | mic 하나 = 기계 하나의 stream. 쓸 모델이 정해져 있고 membrane potential과 판정 상태를 따로 가진다 |
| frame | 추론 요청 하나를 만드는 음성 구간. 64 ms(1,024 샘플)에서 mel 40개를 구한다. 32 ms마다 하나씩 만든다 |
| frame 전송 | mic에서 Host로 frame의 샘플이 들어오는 것. 마지막 샘플이 Host에 도착한 시각이 `t_host`다 |
| 추론 요청 | frame 하나의 mel 40개를 Host가 FPGA로 보낸 것. mic→Host는 frame 전송이고 추론 요청이라 부르지 않는다 |
| 주기 (T) | 32 ms. 트랙마다 주기에 추론 요청 하나를 낸다. 그림에서는 period, 코드에서 주기 번호 k는 epoch |
| 판정 주기 | 이어진 frame 31개, 992 ms. 겹치지 않는다 |
| segment | 이어진 frame 31개의 음성 구간. 학습·평가 data의 단위다 |
| offset | 모델 m의 frame을 기준 모델보다 얼마나 뒤에 자르는지. `O_m = m × T/M = m × 0.8 ms` (M = 40) |
| nominal 생성 시각 | offset으로 정한 frame 끝 시각 `O_m + kT`. 실제 도착은 Host 처리 지연과 링크 지연만큼 늦다 |
| Model-Grouped Offset Assignment | 같은 모델을 쓰는 트랙에 같은 offset을 주는 Host 기법. 동작은 'offset 배정'이라 부른다 |
| Unaligned | offset 배정이 없는 비교 조건. 시나리오의 offset(트랙마다 무작위 또는 동시 시작)을 그대로 쓴다 |
| Global alignment | 모든 트랙에 같은 nominal offset을 주는 비교 조건. 제안 기법의 구성요소가 아니다 |

### 3.2 FPGA

| 용어 | 뜻 |
|---|---|
| batch | weight 적재 한 번으로 이어서 처리하는 같은 모델의 추론 요청들. 이미 도착한 추론 요청만 묶는다 |
| Grouping | 가장 오래 기다린 추론 요청의 모델을 고르고, 그때 queue에 있는 그 모델 추론 요청을 batch 하나로 묶는 scheduler |
| entry | BRAM에서 모델 한 벌의 weight와 누설 계수·threshold를 두는 자리 |
| prefetch | 연산하는 동안 다음 batch의 모델 전체를 빈 entry로 적재하는 것. layer나 slice로 나누지 않는다 |
| 적재 / 재적재 | 적재는 DDR3에서 모델 한 벌을 entry로 읽는 것. 재적재는 같은 모델·주기에서 첫 적재 뒤에 다시 읽은 것 |
| 단일 적재 | 모델·주기마다 한 번만 적재한다는 가정 |
| cache hit / miss | 처리할 모델이 entry에 있음 / 없어서 DDR3에서 적재함 |
| hit rate | batch 중 cache hit인 batch의 비율 |
| predicted-next-use weight cache | 다음 사용 예측이 가장 늦은 모델을 내보내는 weight cache. 줄여서 PNU cache |
| PNU-count | Host가 추론 요청 packet에 싣는 이번 주기 예상 추론 요청 수까지 쓰는 PNU. 제안 정책 |
| PNU-timeout | 예상 추론 요청 수 없이, timeout 안에서는 추론 요청이 남았다고 보는 PNU. 비교용 |
| offset-only | nominal offset과 지금 queue만 쓰는 교체 정책. 비교용 |
| Oracle MIN | 실제 미래 도착 시각을 아는 교체 정책. 구현할 수 없는 비교 기준 |
| Belady 하한 | 실행이 만든 고정 batch 순서에 offline Belady MIN을 적용한 적재 수 하한 |
| victim | 교체로 내보낼 entry의 모델 |
| membrane storage | membrane potential을 12 bit로 저장하는 방식. on-chip 트랙은 membrane bank, 나머지는 DDR3에 둔다 |
| membrane bank | on-chip 트랙의 membrane potential을 두는 BRAM |
| compute array | 64-lane output-stationary 연산 block |
| control overhead | 추론 하나에서 compute array가 weight word를 누산하지 않는 cycle. layer 경계에서 앞 layer의 PLIF를 기다리는 시간과 pipeline을 채우고 비우는 시간 |
| tile | BRAM 단위. RAMB36 하나가 1 tile, RAMB18 하나가 0.5 tile |

### 3.3 시간과 지연

| 용어 | 뜻 |
|---|---|
| 응답 시간 | `t_recv − t_host`. frame 마지막 샘플의 Host 도착부터 Host 결과 수신까지 |
| 준비 완료 뒤 시간 | `t_recv − t_ready`. 즉시 송신이면 입력 링크, FPGA 처리, 결과 링크 |
| 송신 뒤 시간 | `t_recv − t_send` |
| Host 처리 지연 | `t_ready − t_host`. 모델 묶음 지연과 추론 요청별 지연의 합. 줄여서 Host 지연 |
| 모델 묶음 | 같은 모델·같은 주기의 추론 요청들. Host가 함께 계산한다. batch와 다르다 |
| 모델 묶음 지연 (G) | 모델 묶음 전체에 공통인 Host 처리 지연. 주기마다 바뀐다. 줄여서 묶음 지연. 그림에서는 group delay |
| 추론 요청별 지연 (j) | 모델 묶음 안에서 추론 요청마다 다른 Host 처리 지연. simulation은 `Uniform(0, J)` |
| jitter (J) | 같은 모델·같은 주기 추론 요청의 Host 처리 완료 시각이 퍼지는 폭. simulation에서는 j의 상한. 묶음 지연은 jitter가 아니다 |
| 링크 지연 | Host와 FPGA 사이 전송 지연. 입력 `t_arr − t_send`, 결과 `t_recv − t_done` |
| mic–Host 지연 | frame 전송의 지연. mic에서 Host 도착까지. 응답 시간에 넣지 않고 따로 잰다 |
| 즉시 송신 | Host가 준비된 추론 요청을 바로 보낸다. 기본 구성 |
| 즉시 입출력 | 즉시 송신에 더해, FPGA도 연산이 끝나자마자 결과를 보내는 것 |
| 모아 보내기 | Host가 같은 모델·주기 추론 요청을 모았다가 한꺼번에 보낸다. 비교 구성 |
| deadline | `t_host + 32 ms` |
| deadline miss | 응답 시간이 32 ms를 넘었거나 결과가 없는 추론 요청. drop을 포함한다. cache miss와 다르다 |
| drop | 같은 트랙의 이전 추론 요청이 FPGA 연산을 마치기 전에 도착해 버린 추론 요청 |
| deadline 여유 | 32 ms − 응답 시간. 최솟값을 최소 deadline 여유라 부른다 |
| 관측 최대 | 결과가 나온 추론 요청에서 잰 최대. 보장된 상한이 아니다 |
| 조건부 응답 시간 (R_cond) | Host·링크 지연의 측정 최대와 단일 적재 가정으로 계산한 응답 시간 |
| hard worst case | 명시한 운용 제약 안에서 가능한 모든 입력과 도착 과정 중 가장 긴 응답 시간. 아직 구하지 않았다 |

### 3.4 지표

| 용어 | 뜻 |
|---|---|
| DDR3 전송량 | 측정 구간의 weight와 membrane potential 읽기·쓰기 byte ÷ 완료한 추론 수. KiB/추론 |
| DDR3 전송률 | 같은 byte ÷ 측정 구간 시간. MB/s |
| DDR3 대역폭 | DDR3가 낼 수 있는 전송률. 보드 실측 순차 읽기 3.015 GB/s |

frame 전송과 DDR3 전송은 추론 요청이라 부르지 않는다.

### 3.5 쓰지 않는 표기

| 쓰는 표기 | 쓰지 않는 표기 |
|---|---|
| offset, offset 배정 | slot(offset을 뜻할 때. DDR3의 모델 slot은 그대로), 정렬 slot, 위상 정렬 |
| membrane potential | 막전위 |
| deadline, deadline miss | 마감, 마감 위반 |
| batch | 묶음(batch를 뜻할 때) |
| 모델 묶음 지연 | 묶음 공통 지연, 모델·주기 묶음 공통 지연 |
| compute array | 연산기, 연산부 |
| Grouping | 그룹핑 |
| Dysta Method, DeepRT Method | Dysta식, DeepRT식 |
| 응답 시간 | latency(지표 이름) |
| worst case | 최악(응답 시간을 말할 때) |
| DDR3 | DRAM |
| deadline 여유 | slack |
| 주기 | epoch(한국어 문장에서 32 ms 주기를 뜻할 때. 코드 이름과 학습 epoch는 그대로) |
| 즉시 송신 | 즉시 보내기 |
| 준비 완료 뒤 시간 | Host 처리 지연을 뺀 시간 |
| 추론 요청 | 요청(단독으로 쓸 때. 요청서와 동사 '요청하다'는 그대로) |
| mic | 마이크 |

옛 보고서에만 나오는 이름:

| 이름 | 뜻 |
|---|---|
| offset-order weight cache | P3.13~P3.24의 교체 정책. 트랙마다 실제 지연을 알고 있어 미래 정보가 섞였다. P3.25에서 버렸다 |
| 외부 지연 | P3.22까지 쓴 시간 기준(mic 수음부터)에서 FPGA 밖 지연 전체. 지금은 mic–Host 지연, Host 처리 지연, 링크 지연으로 나눈다 |

## 4. 시간 기준

```text
t_host   frame 마지막 샘플이 Host에 들어온 시각
t_ready  Host가 특징 추출을 마쳐 추론 요청을 보낼 준비가 된 시각
t_send   Host가 추론 요청을 보낸 시각. 즉시 송신이면 t_ready
t_arr    추론 요청이 FPGA에 도착한 시각
t_done   FPGA 연산 완료
t_recv   Host가 결과를 받은 시각

deadline          = t_host + 32 ms
응답 시간         = t_recv − t_host
Host 처리 지연    = t_ready − t_host = G(m(i), k) + j(i, k)
```

- mic–Host 지연은 응답 시간과 deadline에 넣지 않는다. 따로 재서 보고한다.
- 최대는 추론 요청마다 시간 차이를 구한 뒤 계산한다. 응답 시간 최대에서 Host 지연 최대를 빼지 않는다.
- offset 배정은 frame을 자르는 위치만 정한다. 어떤 offset을 받아도 deadline은 `t_host + 32 ms`다.
- 같은 트랙의 준비 순서가 뒤집히면 앞 주기의 준비 시각보다 이르지 않게 맞춘다.
- frame 경계와 Host clock이 맞는다고 가정한다. 오디오 장치마다 다른 sample clock drift는 따로 검증한다.

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

B는 전송 byte, 0.244 µs는 DDR3 read 한 번을 시작할 때의 고정 지연이다.

### 5.3 연산

```text
추론 1번 = 240 + 4⌈n1/2⌉ + ⌈n2/2⌉ + 2 + 67 cycle
```

n1·n2는 layer 1·2에서 spike가 난 뉴런 수다. 67은 control overhead다.

| 입력 | cycle | 100 MHz에서 |
|---|---:|---:|
| 실데이터 2,480 추론 평균 | 535.9 | 5.36 µs |
| 실데이터 최대 | 621 | 6.21 µs |
| 모든 spike 발생(포화 입력) | 1,205 | 12.05 µs |

compute array RTL simulation 값이다. 보드 실측이 아니다. 세부는 [03_ARCHITECTURE.md](03_ARCHITECTURE.md) §4에 있다.

### 5.4 FPGA 작업량

모든 입력 spike가 나고 모델·주기마다 weight를 한 번씩만 적재하는 경우의 FPGA 작업량이다. entry 4, on-chip 768트랙, DDR3 256트랙에서 적재와 연산을 겹치지 않고 더했다.

```text
R_single = N·C_dense + M·L_weight + N_DDR·C_state
         = 1,024 × 12.05 µs + 40 × 43.91 µs + 256 × 1.24 µs ≈ 14.41 ms
```

N은 전체 트랙 수, N_DDR은 membrane potential을 DDR3에 두는 트랙 수다. C_dense는 control overhead를 포함한 1,205 cycle, L_weight는 모델 하나의 적재 시간, C_state는 트랙 하나의 membrane potential 읽기·쓰기 시간이다. 이 값을 쓴 조건부 응답 시간과 그 한계는 [05_SCHEDULING.md](05_SCHEDULING.md) §6에 있다.

## 6. 미정 사항

| 항목 | 정할 방법 | 문서 |
|---|---|---|
| entry 수 | 목표 Host의 Host 처리 지연을 재서 재실험 | [04_MEMORY.md](04_MEMORY.md) §4 |
| Host 처리 지연 상한과 Host 규칙 | 목표 Host 측정 | [06_HOST_INTERFACE.md](06_HOST_INTERFACE.md) §9 |
| Ethernet 지연·packet 간격, framing, 제어·적재 경로 | 측정, interface 설계 | [06_HOST_INTERFACE.md](06_HOST_INTERFACE.md) §8 |
| predictor 자원과 묶음 지연 예측 표 오차 | RTL, 합성 | [04_MEMORY.md](04_MEMORY.md) §3 |
| 통합 자원과 timing(MIG·Ethernet MAC·scheduler 포함) | 합성, P&R | [03_ARCHITECTURE.md](03_ARCHITECTURE.md) §6 |
| membrane storage 분할(on-chip 트랙 배정, 12 bit 포장) | 전체 합성 뒤 RTL | [04_MEMORY.md](04_MEMORY.md) §5 |
| hard deadline 분석 | Host·링크 지연 상한, packet 분할 뒤 적재, 주기 사이 잔여 작업을 제한하는 운용 규칙 | [05_SCHEDULING.md](05_SCHEDULING.md) §6 |
| mic–Host 지연, sample clock drift | 측정 | [06_HOST_INTERFACE.md](06_HOST_INTERFACE.md) §9 |
| 실시간 특징 정규화 | 평가와 재학습 | [02_MODEL.md](02_MODEL.md) §5 |
| 신규성 확인 | IEEE Xplore 검색, 원문 확인 | [09_RELATED_WORK.md](09_RELATED_WORK.md) §4 |
| 전력 측정 방법 | 보드 계측 방법 결정 | [08_EVALUATION.md](08_EVALUATION.md) §5 |

## 7. 문서

| 문서 | 내용 |
|---|---|
| [02_MODEL.md](02_MODEL.md) | 모델, 학습, 정수 규칙, export 형식, 판정 |
| [03_ARCHITECTURE.md](03_ARCHITECTURE.md) | 가속기 구조, 처리 순서, 연산, RTL 완료 기준 |
| [04_MEMORY.md](04_MEMORY.md) | BRAM 배분, weight cache와 교체, membrane storage, DDR3 주소 |
| [05_SCHEDULING.md](05_SCHEDULING.md) | Model-Grouped Offset Assignment, Grouping, deadline 분석 |
| [06_HOST_INTERFACE.md](06_HOST_INTERFACE.md) | Host 역할, Ethernet, packet, 시각, register, 측정 계획 |
| [07_SIMULATION.md](07_SIMULATION.md) | 비용 모델, Host 지연 모델, workload, simulator |
| [simulation_engine.md](simulation_engine.md) | simulator 코드 구조, 코드의 식, 환경 키, 결과 CSV 형식 |
| [08_EVALUATION.md](08_EVALUATION.md) | 지표, 비교 방법, 실험 목록 |
| [09_RELATED_WORK.md](09_RELATED_WORK.md) | 선행연구와 신규성 경계 |

진행 상황은 [TASKS.md](../TASKS.md), 실험 결과는 [보고서](../reports/)에 있다.
