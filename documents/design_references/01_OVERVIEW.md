# 01. 개요와 기준 수치

이 폴더는 설계 정본이다. 확정한 값으로 쓰고 값이 바뀌면 고쳐 쓴다. 이력과 근거는 [보고서](../reports/)에 있다. 수치는 따로 적지 않으면 simulation 결과다.

## 1. 요약

FPGA 하나가 SNN 모델 40개로 mic 트랙 1,024개를 처리한다. 트랙마다 32 ms에 추론 요청이 하나 생긴다. Host는 frame 마지막 샘플이 Host에 들어온 시각부터 32 ms 안에 결과를 받아야 한다. 같은 모델을 쓰는 트랙도 membrane potential은 따로 둔다.

병목은 연산이 아니라 weight 전송이다. 모델 40개의 weight는 4.97 MiB인데 BRAM은 약 1.6 MiB다. weight를 재사용하지 않으면 DDR3에 4.17 GB/s가 필요해 보드의 읽기 bandwidth 3.015 GB/s를 넘는다.

설계는 네 가지를 묶는다.

| 기법 | 위치 | 하는 일 |
|---|---|---|
| Model-Grouped Offset Assignment | Host | 같은 모델을 쓰는 트랙에 같은 frame offset을 준다. 같은 모델 추론 요청의 nominal frame 끝 시각이 같아진다 |
| Grouping | FPGA | 이미 도착한 같은 모델 추론 요청을 batch로 묶는다. 추가 추론 요청을 기다리지 않는다 |
| Predicted-Next-Use Weight Cache | FPGA | queue, Host 처리 지연 분포, 예상 추론 요청 수로 다음 사용 시각을 예측해 가장 늦게 쓸 모델을 내보낸다(PNU-Count) |
| 12 bit Membrane Storage | FPGA | membrane potential을 16 bit로 계산하고 12 bit로 저장한다. 남는 BRAM에 일부 트랙을 둔다 |

Xeon Host(CPU 고정·부하 없음)에서 잰 모델 그룹 지연에 추론 요청별 지연 j ~ Uniform(0, 0.8 ms)를 더한 simulation 결과는 다음과 같다. 제안은 DDR3 traffic이 6.38 KiB/추론으로 Dysta Method보다 88.7% 적다. Host 처리 지연을 포함한 관측 최대 response time은 9.58 ms로 9.4% 짧고 준비 완료 뒤 관측 최대는 1.42 ms로 79.5% 짧다. Deadline miss와 drop은 없다. 추론 요청별 지연이 Uniform(0, 3.2 ms)이면 DDR3 traffic은 12.37 KiB/추론으로 늘고 감소폭은 78.9%다([08_EVALUATION.md](08_EVALUATION.md) §4).

RTL은 compute array와 Membrane Storage까지 있다. 최종 Host(라즈베리파이 5 8 GiB)와 Ethernet 경로는 재지 않았다. 32 ms hard deadline 보장은 주장하지 않는다([05_SCHEDULING.md](05_SCHEDULING.md) §6).

## 2. 기준 수치

| 항목 | 값 | 근거 | 상태 |
|---|---|---|---|
| 모델 수 | 40. DCASE 2020 Task 2의 6종 장비 41개 ID에서 fan_id00을 뺐다 | P2.2, [02_MODEL.md](02_MODEL.md) §3 | 확정 |
| 트랙 수 | 1,024 | P3.9 | 확정 |
| 추론 요청 주기 | 트랙마다 32 ms (hop 512샘플 @ 16 kHz) | 특징 추출 규칙 | 확정 |
| deadline | frame 마지막 샘플의 Host 도착 + 32 ms. Host 결과 수신 기준 | P3.25 | 확정 |
| 모델 | L `40→384→256→64→2`, PLIF SNN, INT8 weight 130,176 B, 뉴런 706개, bias 없음 | P3.6 | 확정 |
| compute array | 64 lane, output-stationary, 100 MHz | P4.1 RTL | 전체 설계 timing 미확인 |
| 연산 | layer 2·3에서 spike 0 건너뛰기, cycle마다 spike input 2개, control overhead 67 cycle | P4.1 RTL | RTL simulation 확인 |
| Host | Model-Grouped Offset Assignment(`O_m = m × 0.8 ms`), 즉시 송신 | P3.13, P3.25 | 최종 Host 처리 지연 미측정 |
| scheduler | Grouping. 기다리지 않고 선점하지 않는다 | P3.13, P3.26 | 확정 |
| weight cache | PNU-Count, entry 4개 | P3.25, P3.26 | 교체 정책은 PNU-Count로 확정(2026-10-24). Entry 4개는 비교 실험 구성이고 entry 수는 목표 Host 측정 뒤 |
| entry 크기 | 28.5 tile (RAMB36 28개 + RAMB18 1개) | P4.1 합성 | 확정 |
| membrane potential | 16 bit 포화 연산, 12 bit 저장. Entry 4이면 768트랙 on-chip(187 tile), 256트랙 DDR3 | P3.13, P3.25, P4.2 RTL | RTL simulation 확인. On-chip 트랙 수는 entry 수를 따른다 |
| BRAM 예약 | 링크·request table·준비 buffer 50 tile, predictor 0.5 tile | P3.25 | 링크 예약은 PCIe 근거. Ethernet·predictor 합성 전 |
| Host 링크 | Gigabit Ethernet (RGMII), UDP | 사용자 결정(2026-10-13) | 지연·jitter 미측정 |
| 최종 Host | 라즈베리파이 5 (8 GiB) | 사용자 결정(2026-10-24) | 처리량·지연 미측정 |
| 보드 | ALINX AX7A200B, XC7A200T-2FBG484I, BRAM 365 tile, DDR3 1 GiB 800 MT/s | 보드 시험 | 확정 |
| DDR3 | 순차 읽기 3.015 GB/s, 쓰기 2.768 GB/s | P3.1 보드 실측 | 확정 |

같은 모델을 쓰는 트랙도 membrane potential, 입력 순서, 판정 상태는 트랙마다 따로 둔다.

필수 범위가 아닌 것: 센서를 FPGA에 직접 연결하는 입력, online 학습, 실행 중 모델 교체, 이상 점수에 따른 우선순위.

## 3. 용어

문서·코드·그림은 이 표의 표기만 쓴다. 대소문자와 띄어쓰기까지 같게 쓰고, 영문 용어는 영문 그대로 쓴다.

- 제안 기법 이름(Model-Grouped Offset Assignment, Grouping, Predicted-Next-Use (PNU) Weight Cache, PNU-Count, Membrane Storage)은 단어 첫 글자를 대문자로 쓴다. 고유명사, 약어, 이름 붙은 비교군(Host, FPGA, DDR3, Ethernet, Dysta Method, DeepRT Method, LRU, Oracle MIN)도 대문자다. 나머지는 소문자다.
- Weight cache는 PNU와 함께 쓸 때만 대문자다(PNU Cache, Predicted-Next-Use Weight Cache).
- 소문자 용어도 문장, 제목, 목록, code 주석의 첫머리에서는 첫 글자를 대문자로 쓴다. 표 칸은 이 표의 표기 그대로 쓴다. 그림은 block 이름만 첫 글자를 대문자로 쓰고 화살표·범례 글자는 소문자로 쓴다.
- code 이름, 설정 키, CSV 열은 영문 용어를 snake_case로 쓴다(`period`, `on_chip`, `ddr3_traffic_kib`, `min_deadline_margin_ms`, `model_group_delay`).
- 숫자는 88.7%, 0–0.8 ms(범위는 en dash), J = 0.8 ms, 1,024샘플처럼 쓴다. 용량은 B·KiB·MiB·GiB, bandwidth는 MB/s·GB/s다.

### 3.1 Workload와 offset

| 용어 | 뜻 |
|---|---|
| 모델 | 학습된 weight 한 벌. 장비 ID 하나마다 하나 |
| 트랙 | mic 하나 = 장비 하나의 stream. 쓸 모델이 정해져 있고 membrane potential과 판정 상태를 따로 가진다. 영문 track |
| frame | 추론 요청 하나를 만드는 음성 구간. 1,024샘플(64 ms)에서 40차원 mel을 구한다 |
| hop | frame을 옮기는 간격. 512샘플(32 ms) |
| frame 전송 | mic에서 Host로 frame의 샘플이 들어오는 것. 마지막 샘플이 Host에 도착한 시각이 `t_host`다 |
| 추론 요청 | frame 하나의 mel을 Host가 FPGA로 보낸 것. Mic→Host는 frame 전송이고 추론 요청이라 부르지 않는다 |
| 주기 (T) | 32 ms. 트랙마다 주기에 추론 요청 하나를 낸다. 영문·code는 period(주기 번호 k) |
| 판정 주기 | 이어진 frame 31개, 992 ms. 겹치지 않는다 |
| segment | 이어진 frame 31개의 음성 구간. 학습·평가 데이터의 단위다 |
| offset | 모델 m의 frame을 기준 트랙보다 얼마나 뒤에 자르는지. `O_m = m × T/M = m × 0.8 ms` (M = 40) |
| nominal frame 끝 시각 | offset으로 정한 frame 끝 시각 `O_m + kT`. 실제 도착은 Host 처리 지연과 링크 지연만큼 늦다 |
| Model-Grouped Offset Assignment | 같은 모델을 쓰는 트랙에 같은 offset을 주는 Host 기법. 줄여서 Offset Assignment. code `offset_assignment` |
| offset 배정 | 제안이 아닌 일반 행위(무작위 offset 배정 등) |
| unaligned | Offset Assignment가 없는 비교 조건. 시나리오의 offset(트랙마다 무작위 또는 동시 시작)을 그대로 쓴다 |
| global alignment | 모든 트랙에 같은 nominal offset을 주는 비교 조건. 제안 기법의 구성요소가 아니다. code `global_alignment` |
| 시나리오 | uniform(균등 배정), skewed(편중 배정), synchronized(동시 시작), skewed_synchronized(동시 시작 + 편중 배정), intermittent(간헐적 추론 요청), fluctuating(운영 중 트랙 구성 변경) |

### 3.2 FPGA

| 용어 | 뜻 |
|---|---|
| batch | weight 적재 한 번으로 이어서 처리하는 같은 모델의 추론 요청들. 이미 도착한 추론 요청만 묶는다 |
| Grouping | 가장 오래 기다린 추론 요청의 모델을 고르고, 그때 queue에 있는 그 모델 추론 요청을 batch 하나로 묶는 scheduler. FPGA block 이름은 Grouping scheduler |
| entry | BRAM에서 모델 한 벌의 weight와 누설 계수·threshold를 두는 자리. 개수는 entry 수 |
| prefetch | 연산하는 동안 다음 batch의 모델 전체를 빈 entry로 적재하는 것. layer나 slice로 나누지 않는다 |
| 적재 / 재적재 | 적재는 DDR3에서 모델 한 벌을 entry로 읽는 것. 재적재는 같은 모델·주기에서 첫 적재 뒤에 다시 읽은 것. 여러 번이면 반복 적재 |
| 단일 적재 | 모델·주기마다 한 번만 적재한다는 가정 |
| cache hit / miss | 처리할 모델이 entry에 있음 / 없어서 DDR3에서 적재함 |
| hit rate | batch 중 cache hit인 batch의 비율 |
| weight cache | 모델 weight를 entry에 두고 교체하는 FPGA block |
| Predicted-Next-Use (PNU) Weight Cache | 다음 사용 예측이 가장 늦은 모델을 내보내는 weight cache. 약어는 처음 한 번 붙이고 뒤에는 PNU Cache라 쓴다. 절 제목은 Predicted-Next-Use Weight Cache |
| next-use predictor | PNU Cache에서 다음 사용 시각을 예측하는 block |
| PNU-Count | Host가 추론 요청 packet에 싣는 이번 주기 예상 추론 요청 수까지 쓰는 PNU. 제안 정책. code `pnu_count` |
| PNU-Timeout | 예상 추론 요청 수 없이, timeout 안에서는 추론 요청이 남았다고 보는 PNU. 비교용 |
| offset-only | nominal offset과 지금 queue만 쓰는 교체 정책. 비교용 |
| LRU | 가장 오래 쓰지 않은 모델을 내보내는 교체 정책. 비교용 |
| Oracle MIN | 실제 미래 도착 시각을 아는 교체 정책. 구현할 수 없는 비교 기준. 처음 소개할 때는 Oracle Belady MIN. code `oracle_min` |
| Belady 하한 | 실행이 만든 고정 batch 순서에 offline Belady MIN을 적용한 적재 수 하한 |
| victim | 교체로 내보낼 entry의 모델 |
| Membrane Storage | membrane potential을 16 bit로 연산하고 12 bit로 포화해 저장하는 방식(12 bit Membrane Storage). On-chip 트랙은 membrane bank, 나머지는 DDR3에 둔다 |
| membrane bank | on-chip 트랙의 membrane potential을 두는 BRAM |
| membrane potential | 트랙마다 이어지는 뉴런 값. 줄여 potential. Membrane potential을 뜻하는 상태는 state라 쓴다 |
| compute array | 64-lane output-stationary 연산 block |
| request table | 도착한 추론 요청을 모델별로 두는 표 |
| control overhead | 추론 하나에서 compute array가 weight word를 누산하지 않는 cycle. layer 경계에서 앞 layer의 PLIF를 기다리는 시간과 pipeline을 채우고 비우는 시간 |
| tile | BRAM 단위. RAMB36 하나가 1 tile, RAMB18 하나가 0.5 tile |

### 3.3 시간과 지연

| 용어 | 뜻 |
|---|---|
| response time | `t_recv − t_host`. Frame 마지막 샘플의 Host 도착부터 Host 결과 수신까지 |
| 준비 완료 뒤 response time | `t_recv − t_ready`. 즉시 송신이면 입력 링크, FPGA 처리, 결과 링크 |
| 송신 뒤 response time | `t_recv − t_send` |
| Host 처리 지연 | `t_ready − t_host`. 모델 그룹 지연과 추론 요청별 지연의 합. 영문 Host processing delay |
| 모델 그룹 | 같은 모델·같은 주기의 추론 요청들. Host가 함께 계산한다. Batch와 다르다 |
| 모델 그룹 지연 G(m, k) | 모델 그룹 전체에 공통인 Host 처리 지연. 주기마다 바뀐다. 줄여 쓰지 않는다. 영문·그림 model-group delay |
| 추론 요청별 지연 j(i, k) | 모델 그룹 안에서 추론 요청마다 다른 Host 처리 지연. Simulation은 `Uniform(0, J)`. 영문 per-request delay |
| jitter (J) | 같은 모델·같은 주기 추론 요청의 Host 처리 완료 시각이 퍼지는 폭. Simulation에서는 j(i, k)의 상한(지연 상한 J). 모델 그룹 지연은 jitter가 아니다 |
| 링크 지연 | Host와 FPGA 사이 전송 지연(Host-FPGA 통신). 입력 `t_arr − t_send`, 결과 `t_recv − t_done` |
| mic–Host 지연 | frame 전송의 지연. Mic에서 Host 도착까지. Response time에 넣지 않고 따로 잰다 |
| 즉시 송신 | Host가 준비된 추론 요청을 바로 보낸다. 기본 구성 |
| 즉시 입출력 | 즉시 송신에 더해, FPGA도 연산이 끝나자마자 결과를 보내는 것 |
| 모아 보내기 | Host가 같은 모델·주기 추론 요청을 모았다가 한꺼번에 보낸다. 비교 구성 |
| deadline | `t_host + 32 ms`. 모든 입력에서 지키는 것을 보장하는 기준은 hard deadline |
| deadline miss | response time이 32 ms를 넘었거나 결과가 없는 추론 요청. Drop을 포함한다. Cache miss와 다르다 |
| drop | 같은 트랙의 이전 추론 요청이 FPGA 연산을 마치기 전에 도착해 버린 추론 요청. 처음 설명할 때만 폐기(drop) |
| deadline 여유 | 32 ms − response time. 최솟값을 최소 deadline 여유라 부른다. code `min_deadline_margin_ms` |
| 관측 최대 | 결과가 나온 추론 요청에서 잰 최대. 보장된 상한이 아니다 |
| 조건부 response time (R_cond) | Host·링크 지연의 측정 최대와 단일 적재 가정으로 계산한 response time |
| hard worst case | 명시한 운용 제약 안에서 가능한 모든 입력과 도착 과정 중 가장 긴 response time(worst case response time). 아직 구하지 않았다 |

### 3.4 지표

| 용어 | 뜻 |
|---|---|
| DDR3 traffic | 측정 구간의 weight와 membrane potential 읽기·쓰기 byte ÷ 완료한 추론 수. KiB/추론. CSV `ddr3_traffic_kib` |
| DDR3 bandwidth | 시간당 DDR3 byte. MB/s·GB/s. 측정 구간에 쓴 양은 사용 bandwidth(`ddr3_used_bandwidth_mbps`), 낼 수 있는 상한은 DDR3 읽기 bandwidth(보드 실측 순차 읽기 3.015 GB/s, `ddr3_bandwidth_mbps`) |
| 파일 단위 평균 AUC | 모델마다 test 파일 단위로 구한 AUC의 평균 |

Frame 전송과 DDR3 전송은 추론 요청이라 부르지 않는다.

### 3.5 쓰지 않는 표기

| 쓰는 표기 | 쓰지 않는 표기 |
|---|---|
| response time | 응답 시간, 응답 지연, 지표 이름으로 쓴 latency |
| DDR3 traffic | DDR3 전송량, 트래픽, 읽기량, DDR traffic |
| bandwidth | 대역폭, 전송률 |
| DDR3 | DRAM, DDR 단독 |
| Model-Grouped Offset Assignment, Offset Assignment | Model-grouped, 제안을 뜻하는 offset 배정, slot(offset을 뜻할 때. DDR3의 모델 slot은 그대로), 정렬 slot, 위상 정렬 |
| Grouping | grouping, 그룹핑 |
| weight cache, PNU Cache | PNU 없이 쓴 Weight Cache, PNU cache, 캐시 |
| PNU-Count, PNU-Timeout | PNU-count, PNU-timeout |
| Membrane Storage | membrane storage |
| membrane potential | 막전위 |
| compute array | Compute-array, 연산기, 연산부 |
| 모델 그룹 지연 | 모델 묶음 지연, 묶음 지연, 그룹 지연, 묶음 공통 지연, group delay |
| 추론 요청별 지연 | 요청별 지연 |
| Host 처리 지연 | Host 지연 |
| 추론 요청 | 단독으로 쓴 요청(요청서, 동사 '요청하다', 제어 packet의 요청·응답은 그대로) |
| deadline, deadline miss, hard deadline | 마감, 마감 위반, 데드라인, 하드 데드라인 |
| deadline 여유 | slack(Vivado timing slack은 그대로) |
| batch | 묶음(batch를 뜻할 때) |
| Dysta Method, DeepRT Method | Dysta식, DeepRT식, 우리 비교군을 뜻하는 Dysta·DeepRT 단독 |
| worst case | 최악(response time을 말할 때) |
| 주기, period | epoch(32 ms 주기를 뜻할 때. 학습 epoch는 그대로) |
| 즉시 송신 | 즉시 보내기, 즉시 전송 |
| 준비 완료 뒤 response time | 준비 완료 뒤 시간, Host 처리 지연을 뺀 시간 |
| mic | 마이크 |
| on-chip | onchip, 온칩 |
| 장비 | 기계(장비 종류·ID를 뜻할 때) |
| 데이터, 메모리 | 한국어 문장의 data, memory |
| state | membrane potential을 뜻하는 상태 |
| 보드 | 한국어 문장의 board(폴더 이름 `board_test`는 그대로) |
| out-of-context, 배치·배선 | OOC, P&R |

옛 보고서에만 나오는 이름:

| 이름 | 뜻 |
|---|---|
| offset-order weight cache | P3.13~P3.24의 교체 정책. 트랙마다 실제 지연을 알고 있어 미래 정보가 섞였다. P3.25에서 버렸다 |
| 외부 지연 | P3.22까지 쓴 시간 기준(mic 수음부터)에서 FPGA 밖 지연 전체. 지금은 mic–Host 지연, Host 처리 지연, 링크 지연으로 나눈다 |
| 시나리오 키 U·K·S·SK·I·R | 2026-10-26 전 code·CSV의 시나리오 이름. uniform·skewed·synchronized·skewed_synchronized·intermittent·fluctuating으로 바꿨다 |

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

- Mic–Host 지연은 response time과 deadline에 넣지 않는다. 따로 재서 보고한다.
- 최대는 추론 요청마다 시간 차이를 구한 뒤 계산한다. Response time 최대에서 Host 처리 지연 최대를 빼지 않는다.
- Offset Assignment는 frame을 자르는 위치만 정한다. 어떤 offset을 받아도 deadline은 `t_host + 32 ms`다.
- 같은 트랙의 준비 순서가 뒤집히면 앞 주기의 준비 시각보다 이르지 않게 맞춘다.
- Frame 경계와 Host clock이 맞는다고 가정한다. 오디오 장치마다 다른 sample clock drift는 따로 검증한다.

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

Compute array RTL simulation 값이다. 보드 실측이 아니다. 세부는 [03_ARCHITECTURE.md](03_ARCHITECTURE.md) §4에 있다.

### 5.4 FPGA 작업량

모든 입력 spike가 나고 모델·주기마다 weight를 한 번씩만 적재하는 경우의 FPGA 작업량이다. Entry 4, on-chip 768트랙, DDR3 256트랙에서 적재와 연산을 겹치지 않고 더했다.

```text
R_single = N·C_dense + M·L_weight + N_DDR·C_state
         = 1,024 × 12.05 µs + 40 × 43.91 µs + 256 × 1.24 µs ≈ 14.41 ms
```

N은 전체 트랙 수, N_DDR은 membrane potential을 DDR3에 두는 트랙 수다. C_dense는 control overhead를 포함한 1,205 cycle, L_weight는 모델 하나의 적재 시간, C_state는 트랙 하나의 membrane potential 읽기·쓰기 시간이다. 이 값을 쓴 조건부 response time과 그 한계는 [05_SCHEDULING.md](05_SCHEDULING.md) §6에 있다.

## 6. 미정 사항

| 항목 | 정할 방법 | 문서 |
|---|---|---|
| entry 수 | 목표 Host의 Host 처리 지연을 재서 재실험 | [04_MEMORY.md](04_MEMORY.md) §4 |
| Host 처리 지연 상한과 Host 규칙 | 목표 Host 측정 | [06_HOST_INTERFACE.md](06_HOST_INTERFACE.md) §9 |
| Ethernet 지연·packet 간격, framing, 제어·적재 경로 | 측정, interface 설계 | [06_HOST_INTERFACE.md](06_HOST_INTERFACE.md) §8 |
| predictor 자원과 모델 그룹 지연 예측 표 오차 | RTL, 합성 | [04_MEMORY.md](04_MEMORY.md) §3 |
| 통합 자원과 timing(MIG·Ethernet MAC·scheduler 포함) | 합성, 배치·배선 | [03_ARCHITECTURE.md](03_ARCHITECTURE.md) §6 |
| Membrane Storage 분할(on-chip 트랙 배정, 12 bit 포장) | 전체 합성 뒤 RTL | [04_MEMORY.md](04_MEMORY.md) §5 |
| hard deadline 분석 | Host·링크 지연 상한, packet 분할 뒤 적재, 주기 사이 잔여 작업을 제한하는 운용 규칙 | [05_SCHEDULING.md](05_SCHEDULING.md) §6 |
| mic–Host 지연, sample clock drift | 측정 | [06_HOST_INTERFACE.md](06_HOST_INTERFACE.md) §9 |
| 실시간 특징 정규화의 mic 확인 | mic별 하한 정하기, mic를 붙인 긴 stream | [02_MODEL.md](02_MODEL.md) §5 |
| 신규성 확인 | IEEE Xplore 검색, 원문 확인 | [09_RELATED_WORK.md](09_RELATED_WORK.md) §4 |
| 전력 측정 방법 | 보드 계측 방법 결정 | [08_EVALUATION.md](08_EVALUATION.md) §5 |

## 7. 문서

| 문서 | 내용 |
|---|---|
| [02_MODEL.md](02_MODEL.md) | 모델, 학습, 정수 규칙, export 형식, 판정 |
| [03_ARCHITECTURE.md](03_ARCHITECTURE.md) | 가속기 구조, 처리 순서, 연산, RTL 완료 기준 |
| [04_MEMORY.md](04_MEMORY.md) | BRAM 배분, weight cache와 교체, Membrane Storage, DDR3 주소 |
| [05_SCHEDULING.md](05_SCHEDULING.md) | Model-Grouped Offset Assignment, Grouping, deadline 분석 |
| [06_HOST_INTERFACE.md](06_HOST_INTERFACE.md) | Host 역할, Ethernet, packet, 시각, register, 측정 계획 |
| [07_SIMULATION.md](07_SIMULATION.md) | 비용 모델, Host 처리 지연 모델, workload, simulator |
| [simulation_engine.md](simulation_engine.md) | simulator 코드 구조, 코드의 식, 환경 키, 결과 CSV 형식 |
| [08_EVALUATION.md](08_EVALUATION.md) | 지표, 비교 방법, 실험 목록 |
| [09_RELATED_WORK.md](09_RELATED_WORK.md) | 선행연구와 신규성 경계 |

진행 상황은 [TASKS.md](../TASKS.md), 실험 결과는 [보고서](../reports/)에 있다.
