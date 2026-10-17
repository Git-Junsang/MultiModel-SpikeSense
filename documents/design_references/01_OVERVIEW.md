# 01. 개요와 기준 수치

이 폴더는 설계 정본이다. 확정한 값으로 쓰고 값이 바뀌면 고쳐 쓴다. 근거는 대부분 simulation이고 RTL과 보드로는 아직 확인하지 않았다. 이력과 근거는 [보고서](../reports/)에 있다.

## 1. 요약

FPGA 하나가 SNN 모델 40개로 마이크 트랙 1,024개를 처리한다. 트랙마다 32 ms에 추론 요청이 하나 생기고 Host는 frame의 마지막 샘플을 마이크가 수음한 시점부터 32 ms 안에 결과를 받아야 한다.

병목은 연산이 아니라 weight 전송이다. 모델 40개의 weight는 4.97 MiB라 BRAM(약 1.6 MiB)에 다 들어가지 않는다. weight를 재사용하지 않으면 DDR3에 4.17 GB/s가 필요해 보드의 읽기 대역폭 3.015 GB/s를 넘는다.

설계의 중심은 Model-Grouped Offset Assignment다. Host가 같은 모델을 쓰는 트랙에 같은 frame offset을 배정하면 같은 모델의 추론 요청이 FPGA에 함께 도착한다. FPGA는 추가 요청을 기다리지 않는 Grouping으로 batch를 만들어 한 번 읽은 weight로 여러 트랙을 처리한다. jitter 때문에 나뉘어 온 요청은 offset-order weight cache(entry 4개)가 받아 낸다. 남는 BRAM에는 membrane potential을 12 bit로 둔다.

외부 지연을 0으로 둔 simulation에서 이 구성은 1,024트랙, 시나리오 6개에서 deadline miss가 없었다. DDR3 전송량은 6.36 KiB/추론(169 MB/s), 평균 응답 시간은 0.18 ms다. 같은 BRAM에서 Dysta Method보다 두 값이 모두 89% 적다. DeepRT Method와 비교하면 DDR3 전송량은 44% 적고 평균 응답 시간은 약 44배 짧다([08_EVALUATION.md](08_EVALUATION.md) §4).

## 2. 기준 수치

| 항목 | 값 | 근거 | 상태 |
|---|---|---|---|
| 모델 수 | 40 (DCASE 2020 Task 2, 6종 장비의 40개 ID) | 중간보고 | 확정 |
| 트랙 수 | 1,024 | P3.9 simulation, 사용자 결정 | 확정 |
| 추론 요청 주기 | 트랙마다 32 ms (hop 512 샘플 @ 16 kHz) | 특징 추출 규칙 | 확정 |
| deadline | frame 마지막 샘플의 수음 시각 + 32 ms, Host 결과 수신 기준. 외부 지연 포함 | 사용자 결정(2026-10-16) | 확정 |
| 모델 | L `40→384→256→64→2`, PLIF SNN, INT8 weight 130,176 B, 뉴런 706개, bias 없음 | P3.6, 사용자 결정 | 확정. checkpoint는 `L_mixed_aug`로 바꿀 예정 |
| compute array | 64 lane, output-stationary, 100 MHz | P3.9 simulation | timing 미확인 |
| 연산 | layer 2·3에서 spike 0 건너뛰기, cycle마다 spike input 2개 | P3.12 simulation | 2개/cycle은 RTL 미확인 가정 |
| Host | Model-Grouped Offset Assignment, 즉시 입출력 | P3.12·P3.13 simulation | 확정. jitter 미측정 |
| scheduler | Grouping. 추가 요청을 기다리지 않고 선점하지 않는다 | P3.13 simulation | 확정 |
| weight cache | entry 4개, offset-order 교체 | P3.13·P3.21 simulation | entry 수는 Host jitter 측정 뒤 확정 |
| membrane potential | 16 bit 포화 연산, 12 bit로 저장. 768트랙 on-chip, 256트랙 DDR3 | P3.13 | 확정 |
| Host 링크 | Gigabit Ethernet (KSZ9031, RGMII), UDP | 사용자 결정(2026-10-13) | 지연·jitter 미측정 |
| 보드 | ALINX AX7A200B, XC7A200T-2FBG484I, BRAM 365 tile, DDR3 1 GiB 800 MT/s | 보드 시험 | 확정 |

같은 모델을 쓰는 트랙도 membrane potential, 입력 순서, 판정 상태는 트랙마다 따로 둔다.

필수 범위가 아닌 것: 센서를 FPGA에 직접 연결하는 입력, online 학습, 실행 중 모델 교체, 이상 점수에 따른 우선순위.

## 3. 용어

문서와 코드는 이 표의 표기만 쓴다. 영문 용어는 영문 그대로 쓴다.

| 용어 | 뜻 |
|---|---|
| 모델 | 학습된 weight 한 벌. 장비 ID 하나마다 하나 |
| 트랙 | 마이크 하나 = 기계 하나의 stream. 쓸 모델이 정해져 있고 membrane potential과 판정 상태를 따로 가진다 |
| frame | 추론 요청 하나를 만드는 음성 구간. 64 ms(1,024 샘플)에서 mel 40개를 구하고 32 ms씩 옮긴다 |
| 추론 요청 | frame 하나의 mel 40개를 Host가 FPGA로 보낸 것. frame 끝 시각에 생긴다 |
| offset | 모델 m의 추론 요청이 생기는 시각. `O_m = m × T/M = m × 0.8 ms` (T = 32 ms, M = 40) |
| Model-Grouped Offset Assignment | Host가 같은 모델을 쓰는 트랙에 같은 offset을 배정하는 기법. 배정하는 동작은 'offset 배정'이라 부른다 |
| batch | weight 적재 한 번으로 이어서 처리하는 같은 모델의 추론들. 이미 도착한 요청만 묶는다 |
| Grouping | queue에 먼저 들어온 순서대로 같은 모델 요청을 batch로 묶는 scheduler. 추가 요청을 기다리지 않는다 |
| jitter (J) | 같은 모델 요청의 도착 시각이 배정된 offset에서 달라지는 시간 폭 |
| entry | BRAM에서 weight 한 벌을 두는 자리(weight cache entry) |
| offset-order weight cache | entry가 차면 다음 사용 시점이 가장 먼 모델을 내보내는 weight cache. 다음 사용 순서를 offset에서 얻는다. 줄여서 offset-order cache |
| cache hit / miss | 처리할 모델이 entry에 있음 / 없어서 DDR3에서 적재함 |
| deadline miss | 응답 시간이 32 ms를 넘었거나 결과가 오지 않은 추론 요청. cache miss와 다르다 |
| 응답 시간 | 추론 요청 생성(frame 마지막 샘플 수음)부터 Host 결과 수신까지 |
| 외부 지연 | FPGA 밖에서 생기는 지연. 오디오 buffer, Host 전처리, Ethernet 링크 |
| DDR3 전송량 | 측정 구간의 DDR3 전송 byte(weight + membrane potential) ÷ 추론 수. 단위 KiB/추론 |
| DDR3 전송률 | 측정 구간의 DDR3 전송 byte ÷ 시간. 단위 MB/s |
| DDR3 대역폭 | DDR3가 낼 수 있는 전송률. 보드 실측 순차 읽기 3.015 GB/s |

DDR3 전송은 "요청"이라고 부르지 않는다. 요청은 Host가 보낸 추론 요청만 뜻한다.

## 4. 시간 기준

```text
deadline  = t_gen + 32 ms
응답 시간 = t_done_host − t_gen
```

`t_gen`은 frame 마지막 샘플을 마이크가 수음한 시각, 곧 frame 끝 시각이다. Host가 샘플 위치와 장치 clock으로 계산해 Host clock으로 나타낸다. `t_done_host`는 Host가 결과를 받은 시각이다. 그래서 응답 시간에는 외부 지연과 FPGA 처리가 모두 들어간다.

Host가 요청을 보낸 시각이나 FPGA 도착 시각을 기준으로 하면 앞쪽 지연이 빠진다. 소리가 늦게 들어와도 deadline miss로 잡히지 않으므로 쓰지 않는다. Host와 FPGA의 시각 맞추기는 [06_HOST_INTERFACE.md](06_HOST_INTERFACE.md) §5에 있다.

offset 배정은 frame을 자르는 위치만 정한다. 어떤 offset을 받아도 수음부터 32 ms라는 deadline은 같다.

## 5. 용량과 처리량

### 5.1 크기

```text
weight 1벌            = 15,360 + 98,304 + 16,384 + 128 = 130,176 B
누설 계수·threshold   = 706 × 2 B = 1,412 B
DDR3 slot             = 유효 131,648 B (32 B 정렬), 간격 256 KiB
membrane potential    = 706 × 12 bit = 1,059 B/트랙 (계산은 16 bit, 1,412 B)
weight cache entry    = 29 tile
```

### 5.2 DDR3 전송

```text
재사용 없음           = 1,024 × 31.25 × 130,176 B/s = 4.17 GB/s  > 3.015 GB/s
주기마다 모델당 1번   = 40 × 31.25 × 130,176 B/s = 162.72 MB/s
weight 적재 1번       = 0.244 µs + 131,648 B ÷ 3.015 GB/s = 43.9 µs
membrane potential    = 1,059 B 읽기 + 쓰기 ≈ 1.2 µs/추론 (DDR3 트랙만)
```

"주기마다 모델당 1번"은 이상적인 비교값이다. offset-order weight cache는 entry에 남은 모델을 다시 쓰므로 이보다 적을 수 있다.

### 5.3 연산

| 연산 | 추론 1번 | compute array만 따진 트랙 한계 |
|---|---:|---:|
| dense | 2,237 cycle = 22.4 µs | 약 1,430 |
| spike 0 건너뛰기, cycle마다 1개 | 903 cycle = 9.0 µs | 약 3,540 |
| spike 0 건너뛰기, cycle마다 2개 (설계값) | 676 cycle = 6.8 µs | 약 4,730 |

cycle 수는 test 입력 80개의 평균 spike 수로 셌고 제어 비용 203 cycle(가정)을 넣었다. 세부는 [03_ARCHITECTURE.md](03_ARCHITECTURE.md) §4에 있다.

### 5.4 deadline 보장

worst case는 1,024트랙의 요청이 한꺼번에 도착하고 spike 0을 하나도 건너뛰지 못하는 경우다. 이때 FPGA 내부 처리 시간은 다음을 넘지 않는다.

```text
R_FPGA ≤ N·C_dense + M·L_weight + N_DDR·C_state
       ≈ 1,024·22.4 µs + 40·43.9 µs + 256·1.2 µs ≈ 25 ms
```

N은 전체 트랙 수, N_DDR은 membrane potential을 DDR3에 두는 트랙 수다. compute array를 쉬게 하지 않는 scheduler면 성립한다. 32 ms 가운데 약 7 ms가 외부 지연에 남는다. 외부 지연이 이보다 크면 worst case 보장은 없고 실제 응답 시간에 기댄다([05_SCHEDULING.md](05_SCHEDULING.md) §6).

## 6. 미정 사항

| 항목 | 정할 방법 | 문서 |
|---|---|---|
| entry 수 최종값 | Host jitter 측정 | [04_MEMORY.md](04_MEMORY.md) §4 |
| on-chip membrane potential 트랙 배정과 12 bit 포장 | RTL 설계 | [04_MEMORY.md](04_MEMORY.md) §5 |
| Ethernet framing, 제어 경로, 모델 적재 경로 | Host interface 설계 | [06_HOST_INTERFACE.md](06_HOST_INTERFACE.md) §8 |
| Host jitter와 보내기 방식(즉시 / offset 단위 모아 보내기) | 측정 M1~M4 | [06_HOST_INTERFACE.md](06_HOST_INTERFACE.md) §9 |
| 외부 지연 | 측정 M1·M4 | [06_HOST_INTERFACE.md](06_HOST_INTERFACE.md) §9 |
| simulator 입력 | 측정한 jitter 분포, Ethernet 지연 표본 | [07_SIMULATION.md](07_SIMULATION.md) §6 |
| 신규성 확인 | IEEE Xplore 검색, 원문 확인 | [09_RELATED_WORK.md](09_RELATED_WORK.md) §5 |
| 전력 측정 방법 | 보드 계측 방법 결정 | [08_EVALUATION.md](08_EVALUATION.md) §5 |
| 64 lane @100 MHz, spike 2개/cycle, 제어 비용 | 합성과 RTL | [03_ARCHITECTURE.md](03_ARCHITECTURE.md) §6 |
| checkpoint 교체(`L_mixed_aug`) | export·golden 재생성 | [02_MODEL.md](02_MODEL.md) §3 |

## 7. 문서

| 문서 | 내용 |
|---|---|
| [02_MODEL.md](02_MODEL.md) | 모델, 학습, 정수 규칙, export 형식, 판정 |
| [03_ARCHITECTURE.md](03_ARCHITECTURE.md) | 가속기 구조, 처리 순서, 연산 |
| [04_MEMORY.md](04_MEMORY.md) | BRAM 배분, weight cache, membrane potential, DDR3 주소 |
| [05_SCHEDULING.md](05_SCHEDULING.md) | Model-Grouped Offset Assignment, scheduler, deadline |
| [06_HOST_INTERFACE.md](06_HOST_INTERFACE.md) | Host 역할, Ethernet, packet, 시각, register |
| [07_SIMULATION.md](07_SIMULATION.md) | 비용 모델, workload, simulator |
| [08_EVALUATION.md](08_EVALUATION.md) | 지표, 비교 방법, 실험 목록 |
| [09_RELATED_WORK.md](09_RELATED_WORK.md) | 선행연구와 신규성 경계 |

진행 상황은 [TASKS.md](../TASKS.md), 실험 결과는 [보고서](../reports/)에 있다.
