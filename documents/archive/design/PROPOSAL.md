# 다중 모델·다중 트랙 실시간 SNN 추론 가속기

기준은 [2026-09-17 중간보고](<../presentation/다중 모델, 다중 트랙 실시간 SNN 추론 가속기_중간보고_26.09.17.pptx>)와 발표자 노트다. 별도 표시가 없으면 수치는 목표·가정·계산값이다. DDR3, PCIe, IP 자원만 P3.1~P3.4 보드·구현 실측값을 쓴다.

## 1. 요약

40개 SNN 모델로 512개 센서 트랙을 처리한다. 각 요청은 입력 생성 뒤 32 ms 안에 끝나야 한다.

같은 모델의 준비된 요청을 묶으면 가중치를 재사용할 수 있다. 너무 오래 묶으면 다른 요청이 deadline을 넘는다. 이 연구는 cache, 부분 상주, weight streaming, scheduler가 전송량과 지연에 주는 영향을 비교한다.

부분 상주가 가장 좋다는 결론은 아직 없다. P3.6~P3.8의 XL 모델·1,024트랙 안도 시뮬레이션 결과에 따른 제안이며, 이 문서의 확정 목표를 바꾸지 않는다.

## 2. 문제와 목표

### 2.1 용어

- 모델 `M`: 학습된 가중치 한 벌. 기본값은 40개다.
- 트랙 `N`: 센서 stream과 그 stream의 막전위·판정 상태. 기본값은 512개다.
- 요청: 한 트랙의 한 timestep 입력이다.
- Channel Window: 현재 준비된 같은 모델 요청을 연속 처리하는 묶음이다. 미래 timestep을 기다리는 offline batching이 아니다.

여러 트랙이 같은 모델을 써도 막전위, 입력 순서, 판정 상태는 따로 둔다.

### 2.2 기준 시스템

| 항목 | 기준 | 상태 |
|---|---|---|
| 보드 | ALINX AX7A200B, XC7A200T-2FBG484I | 확정 |
| DDR3 | 1 GiB, 32 bit, 800 MT/s | 순차 읽기 3.015 GB/s 실측 |
| Host | PCIe Gen2 ×2 | H2C 약 760 MB/s 실측 |
| 모델·트랙 | M=40, N=512 | 기본 목표 |
| 모델 | `40→384→256→64→2`, 706뉴런 | 기본 모델 |
| 정밀도 | INT8 가중치, 16 bit 막전위 | 기본 조건 |
| 출력 | 정상/이상 2개 | 확정 |
| deadline | 입력 생성 시각 + 32 ms | 통신 지연 포함 |
| 연산기 | 32 lane, 100 MHz | 검토안 |
| 입력 | USB 마이크 → Host 전처리 → PCIe → FPGA | 통합 경로 |

보드와 PCIe 표기는 매뉴얼과 보드 시험으로 고쳤다. 중간보고의 `AX7203B`, Gen2 ×4는 실제 보드와 다르다.

GigE 직접 입력, online 학습, model update, 이상 점수 기반 우선순위는 필수 범위가 아니다.

### 2.3 시간 기준

```text
deadline = t_gen + 32 ms
slack    = deadline - 현재 시각
latency  = t_complete - t_gen
```

`t_arrival + 32 ms`를 deadline으로 쓰면 Host·PCIe 지연이 빠진다. 센서, Host, FPGA의 시각 동기화와 완료 시점은 packet 규격을 정할 때 확정한다.

## 3. 용량과 처리량

### 3.1 모델과 상태 크기

```text
L1 = 40 × 384  =  15,360 B
L2 = 384 × 256 =  98,304 B
L3 = 256 × 64  =  16,384 B
L4 = 64 × 2    =     128 B
모델 1개       = 130,176 B = 127.125 KiB
모델 40개      = 5,207,040 B = 5,085 KiB
막전위         = 512 × 706 × 2 B = 706 KiB
```

β, 임계값, 주소표, padding은 별도다.

### 3.2 BRAM 예산

XC7A200T에는 RAMB36 365개가 있다. P3.2·P3.4 결과는 다음과 같다.

| 항목 | BRAM tile |
|---|---:|
| 전체 | 365 |
| 512트랙 막전위 | 176.5 |
| XDMA | 20.5 |
| MIG | 0 |
| 모델 entry 1개 | 28.5 |

model prefetch buffer 1개를 따로 두면 가중치 공간은 139.5 tile, 627.75 KiB다. 이 구성에는 전체 모델 4개가 들어간다.

전체 모델 5개는 [ONCHIP_MEMORY.md](ONCHIP_MEMORY.md)의 구성 D에서만 들어간다. 구성 D는 slice double buffer를 쓰고, β·임계값은 entry별로 둔다. queue와 track metadata는 distributed RAM으로 옮긴다.

첫 layer 40개는 `40 × 15 KiB = 600 KiB = 142.5 tile`이다. 모든 모델의 첫 layer를 두는 안은 가능하지만, 남은 layer를 매번 읽어야 한다.

### 3.3 가중치 전송량

트랙마다 초당 31.25개 요청이 생긴다.

```text
재사용 없음 = 512 × 31.25 × 130,176
             = 2,082,816,000 B/s = 2.082816 GB/s

완전 grouping = 40 × 31.25 × 130,176
              = 162,720,000 B/s = 162.72 MB/s
```

완전 grouping은 주기마다 모델별로 한 번만 읽는 이상적 비교값이다. 비동기 요청에서 항상 얻을 수 있는 하한이 아니다.

P3.1의 slice 전송 회귀식은 다음과 같다.

```text
전송 시간 = 0.244 µs + S / 3.015 GB/s
```

모델 전체 전송은 평균 43.43 µs였다. 기존 2.0 GB/s 가정값은 65.088 µs다.

### 3.4 연산량

```text
요청당 연산 = 130,176 / 32 = 4,068 cycle = 40.68 µs
512트랙 순수 연산 = 20.828 ms
32 lane × 100 MHz = 3.2 Gops/s
요구 연산량 = 2.082816 Gops/s
```

이 계산에는 control, state access, DMA wait, scheduler, 통신 비용이 없다. 따라서 20.828 ms를 실제 latency로 쓰지 않는다.

전송과 연산의 단순 비는 `65.088 / 40.68 = 1.6`이다. 전체 모델 전송을 다른 요청 연산 뒤에 숨기려면 약 2트랙이 필요하다는 뜻이다. cache hit와 slice streaming의 공통 하한은 아니다.

### 3.5 세 가지 경계

| 경계 | 계산값 | 뜻 |
|---|---:|---|
| 재사용 없는 DDR3 | 741트랙 | 3.015 GB/s를 모두 쓸 때 |
| 순수 연산 | 786트랙 | 32 lane, 100 MHz, overhead 제외 |
| 막전위 BRAM | 832트랙 | cache 1개와 prefetch 1개 조건 |

이 값은 서로 조건이 다르다. 어느 값도 달성 가능한 트랙 수를 뜻하지 않는다. 기본 목표는 512트랙이다.

## 4. 비교할 설계

### 4.1 저장 정책

| 정책 | 내용 | 확인할 것 |
|---|---|---|
| 전체 모델 cache | 모델 단위 LRU entry | hit, miss 전송, 교체 비용 |
| 부분 상주 | 모든 모델의 일부 layer 또는 slice 상주 | 첫 연산 시작, 남은 전송 |
| 혼합 | 부분 상주 + model cache | 같은 BRAM에서 latency와 전송량 |

막전위를 DDR3로 옮겨 cache를 늘리는 안도 비교할 수 있다. 이때 상태 read와 write를 모두 넣는다.

### 4.2 Weight streaming

DDR3에서 slice를 가져오고, 준비된 slice부터 계산한다. 계산 중에는 다음 slice를 prefetch한다.

결정할 값은 slice 크기, 전송 순서, buffer 수, 교체 단위다. 전송과 계산을 겹쳤다고 전송 byte가 줄어드는 것은 아니다.

### 4.3 Scheduler

scheduler는 처리할 모델과 Channel Window 길이를 정한다. 입력은 다음과 같다.

- deadline과 slack
- cache·부분 상주·prefetch 상태
- 남은 가중치 byte와 전송 시간
- 남은 연산과 state 처리 시간
- 다른 요청이 기다리는 시간

전송 시간을 완료 시간 예측에 넣었다면 같은 비용을 별도 penalty로 다시 더하지 않는다. 정확한 식, coefficient, update 시점, preemption 단위는 architecture 검증에서 정한다.

### 4.4 구조

```text
USB mic → Host preprocessing → PCIe → request queue
                                      │
                                      ▼
                                  scheduler
                           ┌──────────┴──────────┐
                           ▼                     ▼
                    compute array      cache / slice buffer
                           │                     ▲
                           ▼                     │
                    membrane bank          DMA / MIG ← DDR3
                           │
                           ▼
                       result → Host
```

계획 중인 역할 이름은 `track_scheduler`, `weight_store`, `model_prefetch`, `compute_array`, `membrane_bank`, `plift_core`, `anomaly_judge`다. 아직 RTL 파일이 있다는 뜻은 아니다.

## 5. 평가

### 5.1 핵심 지표

| 지표 | 정의 |
|---|---|
| deadline miss rate | `t_complete > t_gen + 32 ms` 비율 |
| weight DRAM byte | 추론 중 읽은 가중치 총량 |
| p99 latency | 입력 생성부터 완료까지 p99 |

worst-case latency와 보수적인 부하도 함께 본다. p99가 32 ms보다 작아도 deadline 보장은 아니다.

### 5.2 비교군

- FCFS
- EDF
- 모델별 Grouping
- 제안 scheduler

저장 정책과 실행 순서의 효과를 따로 본다. 같은 비교에서는 trace, 모델 매핑, BRAM 예산, clock, DDR 설정, cache 초기 상태를 맞춘다. 가능하면 같은 bitstream에서 runtime으로 정책을 바꾼다.

### 5.3 workload

기본 workload는 M=40, N=512다. 비동기 위상, 통신 jitter, 모델 편중을 포함한다. 동시 도착은 별도 비교 조건이다.

USB 마이크 demo는 통합 동작만 보여준다. 512트랙 성능은 별도 부하 실험으로 검증한다.

## 6. 검증할 가설

| 가설 | 검증 방법 |
|---|---|
| Channel Window가 가중치 재전송을 줄인다 | 같은 저장 정책에서 scheduler별 전송 byte 비교 |
| 부분 상주가 첫 연산을 앞당긴다 | 시작·대기·완료 시간 비교 |
| 혼합 방식이 latency와 재전송을 함께 줄인다 | 같은 BRAM에서 분할 비율 비교 |
| 제안 scheduler가 재사용과 deadline을 함께 개선한다 | 비동기·jitter·편중 조건 비교 |
| 모델을 공유해도 track state가 분리된다 | 독립 SW reference와 상태·출력 비교 |

## 7. 진행 순서

| 단계 | 작업 | 완료 기준 |
|---|---|---|
| 1. 모델 | 데이터, 학습, INT8 변환 | 정확도, 가중치, golden vector |
| 2. 설계 검증 | DDR3·PCIe 측정, simulation | 비용 모델과 정책 비교 |
| 3. RTL | DMA, buffer, scheduler, compute | module·통합 test |
| 4. 보드 | P&R, bitstream, Host 연동 | timing, resource, board 동작 |
| 5. 평가 | 정책·부하 비교, demo | 원자료, 지표, 논문 |

실제 일정은 정하지 않았다. 아키텍처를 고정하기 전에 bandwidth와 IP 자원부터 확인한다.

## 8. 미정 사항

- sensor·Host·FPGA 시간 동기화
- packet과 register map
- slice 크기와 buffer 수
- scheduler 식과 hardware cost
- 32 lane, 100 MHz 달성 여부
- 세부 N sweep과 demo 구성

P3.6~P3.8에서 XL 모델, 256 lane, 막전위 DDR3, 1,024트랙, SlackBatch가 제안됐다. 이 안은 [P3.6~P3.8 보고서](<../reports/P3.6~3.8 Research Report.md>)의 simulation 결과다. 목표와 모델 변경은 별도 확인 뒤 반영한다.

## 9. 관련 문서

- [중간보고](<../presentation/다중 모델, 다중 트랙 실시간 SNN 추론 가속기_중간보고_26.09.17.pptx>)
- [ONCHIP_MEMORY.md](ONCHIP_MEMORY.md)
- [SIM_PLAN.md](SIM_PLAN.md)
- [RELATED_WORK.md](RELATED_WORK.md)
- [P3.1~P3.4 보고서](<../reports/P3.1~3.4 Research Report.md>)
