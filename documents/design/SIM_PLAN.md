# Architecture simulation 계획

P3.5 simulator는 저장 정책, scheduler, 연산 순서를 같은 비용 모델에서 비교한다. P3.8의 최신 결과는 [MODEL_SIZE_PLAN.md](MODEL_SIZE_PLAN.md)와 [P3.6~P3.8 보고서](<../reports/P3.6~3.8 Research Report.md>)를 따른다.

## 1. 기준 조건

### 1.1 Workload

- 40모델, 512트랙
- 트랙마다 32 ms 주기
- 트랙 위상은 random
- `model_id`는 uniform 또는 Zipf 분포
- 요청 입력 지연은 P3.3 PCIe sample 사용
- deadline은 입력 생성부터 결과 Host 도착까지 32 ms

미래 요청은 알 수 없다. scheduler는 현재 도착한 요청만 본다.

### 1.2 비용 모델

| 항목 | 값 | 근거 |
|---|---:|---|
| DDR3 read | `0.244 µs + S / 3.015 GB/s` | P3.1 실측 |
| 모델 유효 data | 131,588 B | weight + β·vth |
| 연산 | 4,068 cycle + overhead 10 % | P3.4 + 가정 |
| 요청당 연산 | 44.748 µs @ 100 MHz | 계산 |
| model switch | 추가 비용 없음 | P3.1 실측 |
| 가중치 관련 BRAM | 168 tile | P3.2·P3.4 |

DMA 하나와 compute array 하나가 동시에 동작한다고 가정한다.

### 1.3 Event 순서

1. scheduler가 다음 모델을 고른다.
2. 저장 정책이 필요한 DMA byte를 계산한다.
3. DMA와 compute start time을 계산한다.
4. 첫 group 연산 시작 시점에 Channel Window를 닫는다.
5. 다음 묶음의 weight는 현재 묶음 계산 중 prefetch한다.
6. 결과가 Host에 도착한 시각으로 deadline을 확인한다.

## 2. 비교 축

### 2.1 저장 정책

| 이름 | 내용 | BRAM |
|---|---|---:|
| A. 전체 cache | 5개 model entry, LRU | 145 tile |
| B. 부분 상주 | 40모델 L1 + β·vth | 156.5 tile + buffer |
| C. 혼합 | entry 3개 + 인기 21모델 L1 | 167 tile |

### 2.2 Scheduler

| 이름 | 선택 방식 |
|---|---|
| FCFS | 가장 먼저 온 요청 |
| EDF | deadline이 가장 이른 요청 |
| Grouping | 가장 오래 기다린 모델의 준비된 요청 전체 |
| Score 초안 | 긴급 요청 우선, 아니면 `n / (전송 + n × 연산)` 최대 |

Score 초안은 `T_urgent=4 ms`, 최대 묶음 16을 썼다. 이후 P3.8에서 이 고정값을 deadline guard로 바꿨다.

### 2.3 연산 순서

| 이름 | 시작 시점 |
|---|---|
| 한 번에 | 모델 전체가 준비된 뒤 시작 |
| 한 줄씩 | 뉴런 group이 준비되면 시작 |

B × 한 번에는 185 tile이 필요해 예산을 넘는다. B × 한 줄씩은 164 tile이다.

## 3. 지표와 판정

핵심 지표:

- deadline miss rate
- weight DRAM MB/s
- p99 latency
- worst latency

보조 지표는 평균 묶음, cache hit, DMA·compute utilization, BRAM tile이다.

기본 실행은 저장 3 × scheduler 4 × 연산 2 = 24조합, seed 5개다. BRAM을 넘거나 miss가 한 건이라도 있으면 제외한다.

## 4. Simulator 검증

```bash
python3 software/sim_develop/run_sim.py --selftest
```

| Test | 기대값 | 결과 |
|---|---:|---|
| 1트랙 cache miss, 한 번에 | 140.636 µs | 일치 |
| 1트랙 cache hit | 96.748 µs | 일치 |
| 512트랙 동시 도착, cache 5개 | 164.485 MB/s | 일치 |
| cache 40개 | warm-up 뒤 전송 0 | 일치 |
| 512트랙 compute utilization | 0.716 | 일치 |

코드:

| 파일 | 역할 |
|---|---|
| `sim_core.py` | workload, event, 비용, 지표 |
| `policies.py` | 저장, scheduler, 연산 정책 |
| `run_sim.py` | P3.5 24조합과 bandwidth sweep |
| `dse.py` | 최대 트랙 design-space search |
| `target_exp.py` | P3.8 최종 비교 |

## 5. P3.5 결과

### 5.1 실측 bandwidth

| 항목 | N=512 | N=640 |
|---|---:|---:|
| 예산 안 조합의 miss | 모두 0 | 모두 0 |
| p99 | 0.36~0.56 ms | 0.71~1.58 ms |
| worst | 0.44~0.97 ms | 0.82~3.10 ms |
| weight bandwidth | 1,771~1,862 MB/s | 2,093~2,292 MB/s |
| 평균 묶음 | 1.01~1.04 | 1.02~1.10 |

512·640트랙에서는 연산이 먼저 바빠졌다. Queue가 짧아 같은 모델 요청이 거의 쌓이지 않았다. 따라서 정책 차이가 작았다.

### 5.2 가상 bandwidth

512트랙에서 DDR3만 낮춘 결과다. 보드 실측이 아니다.

| DDR3 | miss 0 조합 | 결과 |
|---|---:|---|
| 3.015 GB/s | 20/20 | 모두 통과 |
| 2.0 GB/s | 18/20 | 일부 FCFS·EDF 실패 |
| 1.5 GB/s | 10/20 | FCFS·EDF 모두 실패 |

Grouping과 Score는 queue가 쌓일 때 같은 모델을 묶어 버텼다. storage와 compute 차이는 작았다.

### 5.3 64 lane·1,024트랙 가상안

이 조건은 확정 목표가 아니다.

- FCFS·EDF는 실측 DDR3 bandwidth에서도 miss 100 %였다.
- Grouping·Score는 miss 0이었다.
- 부분 상주보다 전체 cache의 요청당 weight byte가 20~30 % 적었다.
- 1,024트랙 막전위는 BRAM에 들어가지 않아 DDR3 state traffic을 가정했다.

이 결과를 보고 P3.6~P3.8에서 모델 크기와 최대 트랙 실험을 다시 설계했다.

## 6. 최신 P3.8 결과와 한계

P3.8은 XL 모델, 256 lane, 막전위 DDR3, 시나리오 6개, Host 1 ms batching을 넣었다. SlackBatch를 포함한 최종 비교는 [MODEL_SIZE_PLAN.md](MODEL_SIZE_PLAN.md) §5에 있다.

모든 latency와 energy 결과는 simulation 값이다. 256 lane RTL, scheduler cost, 실제 power는 아직 측정하지 않았다.

자동 생성 결과는 [sim_result/INDEX.md](../../software/sim_result/INDEX.md)에서 찾는다.
