# Simulation engine

## 1. 요약

Engine은 환경 파일 하나로 실험 하나를 실행하는 event simulator다. 이 문서는 코드 구조, 계산식, 환경 키, 결과 CSV 형식을 설명한다. 비용·지연 모델과 workload의 근거는 [07_SIMULATION.md](../design_references/07_SIMULATION.md), 지표의 정의는 [08_EVALUATION.md](../design_references/08_EVALUATION.md) §2에 있다.

```bash
python3 simulation/engine/engine.py simulation/environment/<환경>.toml --jobs 11
python3 simulation/engine/test_engine.py             # 모두
python3 simulation/engine/test_engine.py p326 env    # 고른 부만(core p325 p326 env csv)
```

## 2. 파일과 객체

코드는 모두 `simulation/engine/`에 있다. `engine.py`가 실행을 맡고, 부품은 기능별 `part_*.py`에 둔다.

| 파일 | 객체 | 하는 일 |
|---|---|---|
| `engine.py` | `Setup`, `load`·`points`·`check`, `Run`·`Search`·`Tune`·`Bound`·`Adversarial`, `main` | 환경 파일을 읽어 부품을 조립하고 mode대로 돌려 CSV를 쓴다 |
| `part_hardware.py` | `Hardware`, `Part`, `bram_tiles`, `golden_words` | hardware 조건과 부품 공통 class |
| `part_workload.py` | `Workload`, `SCENARIOS`, `link_samples` | 추론 요청열, 추론 요청 시나리오, 링크 지연 표본 |
| `part_jitter.py` | `Jitter`, 분포 class 8개, `JITTERS` | Host 처리 지연 분포 |
| `part_simulator.py` | `simulate`, `Queue`, `metrics`, `belady` | 시간 진행과 지표 |
| `part_cache.py` | `Cache`, `LRU`, `OffsetOnly`, `PNU`, `PNUTimeout`, `PNURTL`, `OracleMIN` | weight cache 교체 정책 |
| `part_scheduler.py` | `Scheduler`, `Grouping`, `Dysta`, `DeepRT` | 다음 batch의 모델과 구성원 선택 |
| `part_compute.py` | `Compute` | DMA와 compute array의 시각 |
| `part_deadline.py` | `bound`, `DelayPattern`, `model_group_delay_stats`, `host_max_us` | deadline 분석: 조건부 response time 계산과 adversarial search의 지연 패턴 |
| `part_result.py` | `read_csv`, `write_csv`, `summarize`, `seed_stats` | 결과 CSV와 실행 합산 |
| `test_engine.py` | | 손계산·결과 재현 시험 |

코드 규칙은 다음과 같다.

- 상태를 가진 것은 class로, 입력을 받아 값을 내는 계산(지표, Belady 하한, CSV)은 함수로 둔다.
- 부품(cache 정책·scheduler·연산)은 `Part(hw, **attrs)`로 만든다. 키워드 인자로는 class에 이미 있는 속성만 바꿀 수 있다. 환경의 `cache_attrs`·`scheduler_attrs`에도 같은 규칙을 적용한다.
- 각 부품은 실행을 시작할 때 `reset(wl)`로 초기화한다. 결정에 필요한 queue와 시각은 속성에 저장하지 않고 method의 인자로 넘긴다. 해당 method는 `scheduler.pick(queue, T, cache, busy_until)`, `cache.plan(m, queue, T)`, `compute.run(T, nbytes, members)`다. Cache 정책과 연산에 필요한 BRAM tile은 각각 `tiles()`로 구한다.
- 같은 종류의 부품은 공통 method를 제공한다. Cache 정책은 `peek`·`plan`·`predict`·`stats`, scheduler는 `pick`·`members`, Host 처리 지연 분포는 `draw`·`surv`·`delta`·`quantile`, mode는 `jobs`·`one`·`summary`·`job_rows`·`table`을 제공한다.
- 이름은 보고 뜻을 알 수 있게 짓고 단위를 붙인다(`PERIOD_US`, `dense_req_us`). 약어는 `CLK`처럼 널리 쓰는 것만 쓴다.
- 코드 안 문자열(부품 이름, 오류, 출력 표)은 영어로 쓰고 주석과 docstring은 한국어로 쓴다.

## 3. Hardware 조건

`Hardware`는 실행 하나에 적용할 가속기 조건을 담는다. 생성자 인자로 아래 값을 정하면 부품과 추론 요청열이 이를 참조한다.

| 인자 | 환경 키 | 뜻 |
|---|---|---|
| `lanes` | `compute_lanes` | compute array가 한 cycle에 계산하는 뉴런 수 |
| `tracks` | `track_count` | 트랙 수 |
| `membrane_place` | `membrane_place` | membrane potential 위치: `split`·`onchip`·`ddr` |
| `membrane_bits` | `membrane_bits` | membrane potential 저장 bit: 12·16 |
| `arch` | `model_size` | 모델 구조. L = 40-384-256-64-2, XL = 40-768-512-128-2 |
| `ctrl_scale` | `compute_ctrl_scale` | control overhead 67 cycle에 곱하는 배수 |
| `spikes_per_cycle` | `compute_spikes_per_cycle` | L2·L3에서 cycle마다 누산하는 spike 입력 수 |
| `models` | `model_count` | 모델 수 M |
| `ddr3_bandwidth_mbps` | `ddr3_bandwidth_mbps` | DDR3 유효 bandwidth |

은닉 layer의 뉴런은 lane 수만큼씩 그룹으로 나눈다. Layer마다 그룹 수는 ⌈뉴런 수 ÷ lane 수⌉다. 각 그룹은 해당 뉴런들의 입력 전체를 처리하며, cycle마다 weight word 하나를 읽는다. 출력 layer(2뉴런 × 64입력)의 weight는 word ⌈128 ÷ lane 수⌉개로 묶는다.

L·64 lane 구성의 word 수는 다음과 같다.

| layer | 그룹 수 | 그룹당 word 수 |
|---|---:|---:|
| 1 | 6 | 40 |
| 2 | 4 | 384 |
| 3 | 1 | 256 |
| 4 | 1 | 2 |

전체 weight는 2,034 word다.

| 값 | 식 | L·64-lane |
|---|---|---|
| `dense_req_us` | (L1·출력 layer word + 가운데 layer word ÷ spikes_per_cycle(올림) + 67 × ctrl_scale) × 0.01 µs | 1,205 cycle = 12.05 µs |
| `model_bytes` | weight + β·vth(뉴런 706개 × 2 B를 64 B 단위로 올림) | 130,176 + 1,472 = 131,648 B |
| `entry_tiles` | word RAM tile. β·vth는 LUTRAM이라 뺀다 | 28.5 tile |
| `membrane_bytes` | ⌈뉴런 수 × bit ÷ 8⌉, 추론 요청마다 읽기와 쓰기 한 번씩 | 12 bit 1,059 B, 16 bit 1,412 B |
| `membrane_buf_tiles` | `membrane_place`가 `split`·`ddr`일 때 두는 membrane potential 준비 buffer 등. `split`에서 모든 트랙이 on-chip이어도 유지(`MEMBRANE_PREP_TILES`, [04_MEMORY.md](../design_references/04_MEMORY.md) §2) | 4 tile |
| `tile_budget` | 365 − XDMA 20.5 − (on-chip이면 모든 트랙의 membrane potential tile) | 344.5 tile |

연산 cycle 식은 L·64 lane 구성에서 RTL과 대조했다(P4.1). 다른 lane 수와 XL에도 같은 식을 쓰지만, 이 경우는 RTL로 확인하지 않은 가정이다. `golden` 연산은 golden vector의 layer별 spike 수로 추론 요청마다 cycle을 정한다. 첫 timestep은 제외한다. Golden vector가 없는 41번째 모델에는 나머지 모델 40개의 구간을 모아 쓴다.

Membrane potential 위치에 따라 추론 요청당 DDR3 전송이 달라진다.

| `membrane_place` | 뜻 | 추론 요청당 DDR3 |
|---|---|---|
| `split` (제안) | 남는 BRAM에 들어가는 트랙의 state는 on-chip에, 나머지는 DDR3에 둔다. 배분은 `split_membrane`이 정한다(§7.1) | `membrane_bytes` × (1 − on-chip 트랙 ÷ 전체 트랙). 평균으로 계산한다 |
| `onchip` | 모든 트랙의 state를 BRAM에 둔다. 필요한 tile만큼 `tile_budget`을 줄인다 | 0 |
| `ddr` | 모든 트랙을 DDR3에 둔다 | `membrane_bytes` |

고정 상수는 `part_hardware.py` 첫머리에 있다.

| 이름 | 값 | 근거 |
|---|---|---|
| `PERIOD_US` | 32,000 µs (주기 = deadline 길이) | 설계 기준 |
| `DMA_SETUP_US` | 0.244 µs | P3.1 회귀 |
| `DDR3_READ_BANDWIDTH_MBPS`, `DDR3_WRITE_BANDWIDTH_MBPS` | 3,015, 2,768 | P3.1 실측 |
| `CTRL_OVERHEAD_CYC` | 67 cycle | P4.1 RTL |
| `BRAM_TILES`, `XDMA_TILES`, `MEMBRANE_PREP_TILES` | 365, 20.5, 4 | XC7A200T, P3.2, 04 §2 |

## 4. 추론 요청열

### 4.1 시각 열과 생성 순서

추론 요청마다 아래 시각을 둔다([01_OVERVIEW.md](../design_references/01_OVERVIEW.md) §4).

| 열 | 정하는 방법 |
|---|---|
| `t_host` | nominal offset + k × 주기. Deadline = `t_host` + 32 ms |
| `t_ready` | `t_host` + Host 처리 지연(모델 그룹 지연 G + 추론 요청별 지연 j) |
| `t_send` | 즉시 송신이면 `t_ready`, 모아 보내기면 모델 그룹을 보내는 시각 |
| `t_arr` | `t_send` + 입력 링크 지연. `host_link`가 `pcie`면 PCIe 64 B H2C 실측 표본(P3.3), `ethernet`이면 라즈베리파이 5–보드 직결 Ethernet 입력 표본(P3.16)이다 |
| 연산 완료 | `simulate`가 정한다 |
| `t_recv` | 연산 완료 + 결과 링크 지연(`pcie`는 64 B C2H, `ethernet`은 Ethernet 결과 실측 표본). `Workload.recv_time` |

`Setup.workload`는 다음 순서로 추론 요청열을 만든다. 1·2번은 `Setup`, 3–5번은 `Workload.make`, 6–8번은 `Workload`의 각 method가 수행한다.

1. 트랙의 모델과 offset을 시나리오에 따라 정한다. `uniform`은 균등 배정, `skewed`는 비율 ∝ 1/(k+1)의 편중 배정이다. `synchronized`·`skewed_synchronized`는 동시 시작, `intermittent`는 주기마다 추론 요청 확률 0.25, `fluctuating`은 주기마다 활성 트랙 비율 Uniform(0.25, 1)을 적용한다. Code의 시나리오 키(`part_workload.SCENARIOS`, 환경 키 `sim_scenarios`)도 이 이름을 그대로 쓴다.
2. `host_offset`이 `model`이면 모델 m의 트랙을 m × 32 ms ÷ M에 둔다. `global`이면 모든 트랙을 0에, `none`이면 시나리오 값 그대로 둔다.
3. (트랙, 주기)마다 `host_jitter_dist` 분포에서 추론 요청별 지연 j를 뽑는다. `host_model_group_delay_trace`가 있으면 (모델, 주기)별 모델 그룹 지연 G를 더한다. 같은 트랙의 준비 시각에는 누적 최댓값을 적용해 순서가 뒤집히지 않게 한다. Adversarial search처럼 (트랙, 주기)별 지연을 직접 전달한 경우에는 이를 전체 Host 처리 지연으로 쓰며 순서를 조정하지 않는다.
4. 링크 지연 표본과 추론 요청별 연산을 넣는다.
5. 간헐적 추론 요청과 운영 중 트랙 구성 변경 조건에 따라 추론 요청을 거른 뒤 FPGA 도착 순으로 정렬한다. 두 지연 분포는 PNU가 예측에 참조할 수 있도록 추론 요청열에 함께 둔다.
6. `host_gather_ms`가 0보다 크거나 `host_gather_to_max`가 참이면 `gather`로 모아 보내기를 적용한다. 모델·주기별 추론 요청이 모두 준비되거나 offset + D에 도달하면 모은 추론 요청을 한꺼번에 보낸다. `host_gather_to_max`가 참이면 D는 Host 처리 지연의 최댓값(모델 그룹 지연 표의 최대 + J)이다.
7. `host_packet_gap_us`가 0보다 크면 `packetize`가 같은 모델·주기·송신 시각의 추론 요청을 64 B 추론 요청 23개(MTU 1,500 B)씩 packet으로 나누고 j번째 packet을 j × 간격만큼 늦게 도착시킨다.
8. `delay`는 송신 전에 모든 추론 요청에 `host_fixed_delay_us`를 더한다. 이 고정 지연은 response time에 포함한다.

예열 주기(`sim_warmup_periods`)가 끝난 뒤 측정 주기(`sim_meas_periods`) 동안을 측정 구간으로 잡는다. 추론 요청 지표는 `t_host`가 측정 구간 안에 있는 추론 요청으로, DDR3 지표는 측정 구간에 연산을 시작한 batch로 센다.

### 4.2 Host 처리 지연 분포

각 지연 분포는 `Jitter`를 상속한 class로 구현한다. 분포 class는 표본 생성 방법(`_draw`)과 생존함수 S(x)(`_surv`)를 정의한다. 최댓값이 J와 다르면 `max_us`도 정의한다. `draw`·`surv`·`delta`·`quantile`은 공통 method다. 측정 기록을 입력으로 쓰는 `TraceJitter`는 `draw`와 분위수 계산을 직접 정의한다.

`Jitter.of(host_jitter_dist, J, trace)`는 환경 값에 맞는 분포를 만든다. 추론 요청열은 `draw`로 실제 지연을 뽑는다. PNU는 이 실제 지연을 읽지 않고 분포의 `delta`·`quantile`·`max_us`만 예측에 쓴다.

| `host_jitter_dist` | class | 추론 요청별 지연 j |
|---|---|---|
| `none` | `NoJitter` | 0 |
| `uniform` | `UniformJitter` | 추론 요청·주기마다 Uniform(0, J) |
| `tail` | `TailJitter` | 95% Uniform(0, b) + 5% Uniform(b, J), b = min(0.8 ms, J) |
| `tail1` | `Tail1Jitter` | `tail`과 같은 형태이며 긴 지연의 비율을 1%로 설정 |
| `burst` | `BurstJitter` | 주기마다 5% 확률로 모든 추론 요청에 공통 Uniform(0, J), 여기에 추론 요청마다 Uniform(0, b) |
| `cd` | `CommonDelayJitter` | 주기 공통 Uniform(0, J/2) + 추론 요청마다 Uniform(0, J/2) |
| `static` | `StaticJitter` | 트랙마다 Uniform(0, J) 하나를 모든 주기에 쓴다 |
| `trace` | `TraceJitter` | 측정 CSV(`host_jitter_trace`)의 지연 값 |

`delta(e, r)`는 남은 추론 요청 r개가 모두 경과 시간 e 이후에 도착한다는 조건에서, 첫 추론 요청이 도착할 때까지 남은 시간의 기대값이다.

```text
δ(e, r) = ∫_e^max (S(x) / S(e))^r dx        S(x) = P(지연 > x)
uniform·static: δ(e, r) = (J − e) / (r + 1)
```

`TraceJitter`는 입력 기록의 앞 절반 주기로 분포를 추정하고, 뒤 절반 주기의 값을 simulation에 넣는다. 모델 그룹 지연 표(`host_model_group_delay_trace`, 행 = 모델)도 `TraceJitter`로 읽는다. Seed s의 입력은 뒤 절반 구간의 s × (예열 + 측정 주기 수)번째 주기부터 시작한다. 같은 분포는 `Jitter.of`가 한 번만 만든다.

### 4.3 난수

결과가 seed로만 정해지도록 난수열을 나눠 쓴다.

| 생성기 seed | 쓰는 곳 |
|---|---|
| seed | 트랙 → 모델, 무작위 offset, 링크 지연 표본 |
| seed + 4545 | 추론 요청별 지연 j |
| seed + 5555 | golden 구간과 시작 위치 |
| seed + 7777 | 간헐적 추론 요청(intermittent) |
| seed + 8888 | 운영 중 트랙 구성 변경(fluctuating) |

`Workload.draw_tracks`는 `make`와 같은 순서로 같은 난수를 뽑는다. adversarial search처럼 추론 요청열 밖에서 트랙 배정이 필요할 때 쓴다.

## 5. Simulator

`simulate(wl, cache, scheduler, compute)`는 한 batch 앞의 모델을 미리 고르고 weight를 적재하며 시간을 진행한다.

1. 결정 시각 T까지 FPGA에 도착한 추론 요청을 `Queue`에 넣는다. Queue가 비어 있으면 다음 추론 요청의 도착 시각으로 이동한다.
2. `scheduler.pick(queue, T, cache, busy_until)`이 다음 모델을 고른다. busy_until은 compute array가 비는 시각이다. Scheduler가 기다리기로 하면 다시 고를 시각으로 넘어간다.
3. `cache.plan(m, queue, T)`이 적재할 byte 수를 정한다. Cache hit이면 0, cache miss이면 `model_bytes`다.
4. `compute.run(T, nbytes, members)`이 적재 완료 시각과 연산 시작 시각 s를 계산한다. Batch 구성원은 s에 확정하므로 T 이후 s까지 도착한 같은 모델의 추론 요청도 포함한다.
5. 다음 결정 시각은 s다. 그래서 batch i를 연산하는 동안 batch i+1의 weight를 적재한다(prefetch).

`fpga_drop_busy`가 참이면 같은 트랙의 이전 추론 요청이 연산을 마치기 전에 도착한 추론 요청은 queue에 넣지 않고 버린다. 버린 추론 요청은 response time을 2주기로 적어 deadline miss로 센다([06_HOST_INTERFACE.md](../design_references/06_HOST_INTERFACE.md) §4.3).

`belady`는 실행에서 생성된 batch 순서에 offline Belady MIN을 적용해 적재 수 하한을 구한다. 측정 구간이 시작할 때 entry에는 어떤 모델이든 있을 수 있다고 가정한다. 둘째 batch부터는 직전 batch의 모델을 교체 후보에서 제외한다.

`detail=True`이면 compute array의 cycle 합계(연산 + 정지 + 유휴 = 측정 구간)를 확인하고, response time을 입력 링크·FPGA 처리·결과 링크로 나눠 기록한다. 도착한 추론 요청이 남아 있는데 compute array가 쉬는 cycle은 정지로 센다. FPGA 안에 추론 요청이 없는 cycle은 유휴로 센다.

## 6. 부품

### 6.1 Cache 정책

모든 정책은 여러 entry에 모델 weight를 저장한다. `cache_entries = 0`이면 entry 수는 ⌊(예산 − 준비 buffer − 메타데이터) ÷ `entry_tiles`⌋로 정한다(예산은 §7.1). Entry가 2개보다 적은 구성은 배치할 수 없다.

Cache hit이면 해당 entry의 사용 순서를 가장 최근으로 갱신한다. Cache miss이고 entry가 모두 차 있으면, 연산 중인 entry(가장 최근)를 제외한 후보 중 `predict` 점수가 가장 큰 모델을 내보낸다. 점수가 같으면 queue가 빈 모델을, 그래도 같으면 가장 오래 쓰지 않은 모델을 고른다.

| `cache_policy` | class | `predict` |
|---|---|---|
| `lru` | `LRU` | 모두 0. 가장 오래 안 쓴 모델을 내보낸다 |
| `offset_only` | `OffsetOnly` | queue에 추론 요청이 있으면 지금, 없으면 다음 nominal offset |
| `pnu_count` (제안) | `PNU` | [04_MEMORY.md](../design_references/04_MEMORY.md) §3.1의 식 |
| `pnu_timeout` | `PNUTimeout` | 같은 식에서 예상 추론 요청 수를 모르고 r = 1 |
| `pnu_rtl` | `PNURTL` | `next_use_predictor.v`와 같은 정수 µs·표 계산 |
| `oracle_min` | `OracleMIN` | 실제 미래 도착 시각. 구현할 수 없는 비교 기준인 Oracle Belady MIN(이하 Oracle MIN) |

PNU 계열의 세부는 다음과 같다.

- 예측에 쓰는 모델 그룹의 키는 (모델, nominal offset)이다. Offset Assignment를 적용하면 모델마다 하나이고, 적용하지 않으면 트랙마다 하나다.
- 해당 주기의 예상 추론 요청 수는 첫 추론 요청이 도착할 때 알 수 있다. 그전에는 직전 주기의 값을 쓰고, 첫 주기에는 등록 트랙 수를 쓴다.
- τ는 분포의 `tau_q` 분위수다(기본 1.0 = 최대).
- `pred = "lut"`이면 δ를 경과 시간 `bin_us` 칸 × 남은 추론 요청 수 6칸 표에서 읽는다. 남은 수 칸은 1, 2, 3–4, 5–8, 9–16, 17 이상이다.
- `model_group_delay_aware = false`면 모델 그룹 지연 분포를 쓰지 않는다(P3.25 식).

모델 그룹 지연 분포가 없을 때는 아래 식을 쓴다. 분포가 있으면 [04_MEMORY.md](../design_references/04_MEMORY.md) §3.1의 식을 쓴다.

```text
kn = ⌊(now − O) / T⌋,  el = now − O − kn·T,  r = 예상 수 − 받은 수
r > 0 이고 el < τ:  t̂ = max(now, O + kn·T + el + δ(el, r))
그 밖:              t̂ = O + (kn + 1)·T + δ(0, n)
```

`PNURTL`은 시각을 정수 µs로 내림하고, δ를 256 µs 간격의 128칸 표에서 읽는다. 모델 그룹마다 가장 최근 주기 하나의 예상 추론 요청 수, 도착 수, 첫 도착 시각만 저장한다. 추론 요청의 주기는 RTL과 같이 도착 시각과 `t_host`로 판정한다. Predictor 메타데이터에는 0.5 tile을 추가로 쓴다.

각 정책은 측정 구간의 교체 결정을 실제 다음 사용 시각과 비교한다. 진단 값으로 교체 수, Oracle MIN과 다른 victim 수, 예측 오차(50 µs 간격 히스토그램)를 기록한다. 이 값은 교체 결정에 쓰지 않는다.

### 6.2 Scheduler

| `scheduler` | class | 규칙 |
|---|---|---|
| `grouping` (제안) | `Grouping` | 가장 오래 기다린 추론 요청의 모델을 고르고 그 모델의 준비된 추론 요청을 모두 묶는다 |
| `dysta_method` | `Dysta` | 점수 = batch 시간 ÷ n + η × (deadline − t0 − batch 시간 − margin)이 가장 작은 모델의 추론 요청 전부 |
| `deeprt_method` | `DeepRT` | 모델마다 길이 W의 window를 두되 모델 m의 시작을 m·W/M로 다르게 하고 window가 끝나면 그동안 온 추론 요청을 job 하나로 묶어 job deadline 순서로 처리한다 |

- Dysta Method의 batch 시간 = 남은 적재 + membrane potential DMA + n × `dense_req_us`다. t0은 결정 시각과 compute array가 비는 시각 중 늦은 쪽이다. η 기본값은 1e-4(p325_dysta_method_tune에서 고른 값)다. margin 기본값은 결과 링크 지연 표본 최대 + 20 µs이고 `Dysta`를 만들 때 정한다.
- DeepRT Method의 `window = [W µs, flush]`에서 flush가 참이면 compute array가 쉬고 있을 때 window 끝을 기다리지 않는다. 기본값은 `[14,900 µs, false]`이며, `p325_deeprt_method_tune`에서 선택했다.
- 비교 실험의 환경 파일은 이 값을 `scheduler_attrs`에 그대로 적는다. 결과 CSV의 `scheduler_attrs` 열이 쓴 값을 남긴다.
- 비교군을 이렇게 옮긴 근거는 [08_EVALUATION.md](../design_references/08_EVALUATION.md) §3에 있다.

### 6.3 연산

`Compute`는 DMA 하나와 compute array 하나의 사용 가능 시각을 관리한다. 필요한 weight가 대상 entry에 모두 적재되면 batch의 추론 요청을 하나씩 처리한다. 각 추론 요청은 모델 전체를 순서대로 연산한다.

```text
적재 완료 = max(T + 0.244 µs, 앞 DMA 완료) + 적재 B ÷ DDR3 bandwidth  (고정 비용이 앞 전송과 겹칠 수 있음)
연산 시작 s = max(적재 완료, compute array가 비는 시각)
추론 요청 i 완료 = s + 앞 추론 요청들의 연산 합 + 추론 요청 i의 연산
```

Membrane potential이 DDR3에 있으면 weight 전송 뒤에 추론 요청 수 × (읽기 B ÷ 읽기 bandwidth + 쓰기 B ÷ 쓰기 bandwidth)만큼 DMA 사용 시간을 더한다. 다음 batch의 적재는 그만큼 늦어진다. Membrane potential을 읽는 시간은 준비 buffer를 통해 연산과 겹친다고 가정한다.

## 7. 실행기

### 7.1 Setup 조립 순서

`Setup(e)`는 실험 점 하나의 설정 e로 다음 순서대로 부품을 만들고 BRAM을 배분한다.

1. `Hardware`(§3)
2. `Compute`
3. Cache 정책을 만든다. 전체 예산은 `tile_budget` − `bram_reserve_tiles`이며 결과 CSV의 `budget`에 기록한다. Cache 정책에는 이 예산에서 준비 buffer(`Compute.tiles()`)를 뺀 값을 배정한다.
4. 사용 tile을 계산한다. Cache 정책의 `tiles()`(entry 수 × `entry_tiles` + 메타데이터)에 준비 buffer를 더한 값이다. 예산을 넘거나 entry가 2개보다 적으면 배치할 수 없는 실험 점으로 분류한다. Run·bound·adversarial mode에서는 해당 점을 실행하지 않는다.
5. `split`이면 `Hardware.split_membrane`이 남는 tile에 들어갈 on-chip 트랙 수를 정한다. 예산에 들어가는 가장 큰 16의 배수로 정하고 `Setup.on_chip_tracks`에 저장한다. 추론 요청당 DDR3 membrane potential byte는 on-chip 트랙 비율만큼 줄인다. Entry 4개이면 남는 200.5 tile에 768트랙(199 tile)이 들어간다([04_MEMORY.md](../design_references/04_MEMORY.md) §2). `onchip`이면 트랙 전부를, `ddr`이면 0을 `Setup.on_chip_tracks`에 저장한다.
6. Scheduler

`Setup.workload(scn, seed)`는 §4.1의 추론 요청열을 만들고 `Setup.run(scn, seed)`는 그 추론 요청열을 끝까지 돌린다.

### 7.2 환경 파일과 키 이름

환경 파일은 `simulation/environment/template.toml`과 같은 키를 사용해야 한다. 키가 빠지거나 추가되면 engine은 실행 전에 오류를 내고 멈춘다. 키 이름은 `대상_속성[_단위]` 형식이다.

| 대상 | 키 |
|---|---|
| `sim` | `sim_mode`, `sim_scenarios`, `sim_seeds`, `sim_seed0`, `sim_warmup_periods`, `sim_meas_periods` |
| `model` | `model_size`, `model_count` |
| `compute` | `compute_lanes`, `compute_input`, `compute_spikes_per_cycle`, `compute_ctrl_scale` |
| `membrane` | `membrane_place`, `membrane_bits` |
| `bram`, `ddr`, `track` | `bram_reserve_tiles`, `ddr3_bandwidth_mbps`, `track_count` |
| `host` | `host_offset`, `host_jitter_ms`, `host_jitter_dist`, `host_jitter_trace`, `host_model_group_delay_trace`, `host_gather_ms`, `host_gather_to_max`, `host_packet_gap_us`, `host_fixed_delay_us`, `host_link` |
| `fpga` | `fpga_drop_busy` |
| `cache`, `scheduler` | `cache_policy`, `cache_entries`, `cache_attrs`, `scheduler`, `scheduler_attrs` |
| `search`, `tune` | `search_key`, `search_values`, `search_step`, `tune_attr`, `tune_values`, `tune_conds` |

`[sweep]`의 축 이름이 환경 키와 같으면 해당 키에 적용할 값 목록을 지정한다. 환경 키가 아닌 이름이면 값으로 설정 표를 지정한다. 설정 표 하나에서 여러 환경 키를 함께 바꿀 수 있으며, `label`은 해당 설정의 이름이 된다.

실험 점 이름은 각 축의 이름표를 ` · `로 이어 만든다. 축이 없으면 `base`를 쓴다. `check`는 실행 전에 모든 실험 점의 설정을 확인한다.

### 7.3 Mode

| `sim_mode` | 작업 단위와 실행 방법 | 점별 요약 |
|---|---|---|
| `run` | (점, 시나리오, seed) 하나를 끝까지 돌린다. 배치할 수 없는 점은 건너뛴다 | `summarize` + seed 통계 |
| `search` | 점 하나에서 `search_key`를 `search_values` 순서로 바꿔 모든 시나리오·seed에서 deadline miss가 0인 마지막 값을 찾는다 | 찾은 값, 탐색 범위의 상한 도달 여부 |
| `tune` | (점, 후보 값) 하나를 `tune_conds` × 시나리오 × seed 조합으로 실행한다 | deadline miss가 0인 후보 중 weight byte가 가장 작은 값. 동점이면 response time 관측 최대가 짧은 값. 통과 후보가 없으면 deadline miss가 발생한 실행이 가장 적은 값 |
| `bound` | 점 하나의 조건부 response time을 `part_deadline.bound`로 계산한다. Simulation은 돌리지 않는다 | R_single, R_cond, Host 처리 지연 최대 H, 같은 트랙 추론 요청 사이 최소 간격, 두 조건의 성립 여부 |
| `adversarial` | 점 하나에서 모델별 지연 패턴(`DelayPattern`)을 바꾸며 송신 뒤 response time(`t_recv − t_send`)의 관측 최대를 키운다 | 선택한 패턴의 지표(`adv_*`), 탐색한 모든 패턴의 관측 최대(`seen_*`), `bound`의 값 |

Search는 값이 커지거나 작아지는 순서대로 통과 여부가 한 방향으로만 바뀐다고 가정한다. 탐색 범위를 2배씩 넓힌 뒤 이분 탐색한다. `track_count`의 값 목록이 비어 있으면 연산 가동률 100%까지 `search_step` 간격으로 후보를 만든다.

Adversarial search는 모든 모델에 같은 지연 패턴을 적용한 시작점 30개와 무작위 시작점 8개를 먼저 시험한다. 그중 송신 뒤 response time이 가장 긴 패턴에서 모델 3개의 패턴을 바꿔 본다. 값이 더 커지면 변경을 채택하는 과정을 24번 반복한다.

탐색 난수는 송신 방식 키(`host_gather_ms`·`host_gather_to_max`·`host_packet_gap_us`)를 제외한 점 번호로 정한다. 따라서 송신 방식이 달라도 시작점과 난수열이 같다. 결과는 관측 최대이며 상한을 증명하지 않는다.

Search·tune의 각 실행은 측정 구간에서 deadline miss가 발생하면 즉시 멈춘다. Bound·adversarial도 BRAM에 배치할 수 없는 실험 점은 건너뛴다.

`bound`의 식은 [05_SCHEDULING.md](../design_references/05_SCHEDULING.md) §6.1과 같다. 같은 트랙의 추론 요청 사이 최소 간격은 즉시 송신에서 32 ms − (G_max − G_min) − J다. 모아 보내기에서도 대기가 끝난 뒤 준비된 추론 요청은 바로 보낸다. 따라서 최소 간격은 32 ms − (H − G_min)으로, 즉시 송신과 같은 값이다. 바쁜 구간 하나에 같은 모델의 두 주기 작업이 함께 들어오지 않으려면 R_single이 이 간격보다 짧아야 한다. 이는 필요조건이다.

`DelayPattern`의 모델 그룹 지연은 모델마다 정하며 범위는 [0, G_max)다. 추론 요청별 지연은 트랙마다 정하며 범위는 [0, J)다.

| 지연 종류 | 패턴 | 적용 값 |
|---|---|---|
| 모델 그룹 지연 | `g0` | 0 |
| 모델 그룹 지연 | `gmax` | 최댓값 |
| 모델 그룹 지연 | `galt` | 주기마다 최댓값과 0을 번갈아 적용 |
| 모델 그룹 지연 | `galign` | 모델 offset을 G_max 간격의 경계까지 늦춰 여러 모델이 동시에 도착하도록 설정 |
| 모델 그룹 지연 | `grand` | Uniform(0, G_max) |
| 추론 요청별 지연 | `early` | 0 |
| 추론 요청별 지연 | `late` | 최댓값 |
| 추론 요청별 지연 | `spread` | 트랙 순서대로 0부터 최댓값까지 분배 |
| 추론 요청별 지연 | `alt` | 트랙·주기마다 0과 최댓값을 번갈아 적용 |
| 추론 요청별 지연 | `rand` | Uniform(0, J) |
| 추론 요청별 지연 | `pkt` | 모델의 첫 packet(23트랙)은 0, 나머지는 최댓값 |

### 7.4 결과 CSV

결과는 `simulation/result/<환경 이름>.csv`와 `<환경 이름>_runs.csv.gz`다.

| 파일 | 행 | 열 |
|---|---|---|
| `<이름>.csv` | 점 하나 | `point`, `label`, 환경 값 전부, `tiles`, `budget`, `feasible`, `on_chip_tracks`(split), mode 요약 |
| `_runs.csv.gz` (run) | (점, 시나리오, seed) | `point`, `label`, `scn`, `seed`, `simulate` 지표, `c_req`, `model_b`, `hist`(response time [칸, 개수], 0.05 ms 칸) |
| `_runs.csv.gz` (search) | (점, 시험한 값) | `point`, `label`, `key`, `value`, `passed` |
| `_runs.csv.gz` (tune) | (점, 후보) | `point`, `label`, `attr`, `value`, `fails`, `w_kib`, `ddr3_traffic_kib`, `max_ms` |
| `_runs.csv.gz` (bound) | 점 하나 | `point`, `label`, `bound` 값 |
| `_runs.csv.gz` (adversarial) | (점, 시험한 패턴) | `point`, `label`, `step`, `model_group_delay_pattern`, `request_pattern`, 해당 패턴에서 송신 뒤 response time의 관측 최대가 가장 큰 시나리오의 지표 |

- CSV의 문자열 값은 그대로 쓴다. 숫자·참거짓·목록·표는 JSON으로 저장하고, `read_csv`가 원래 자료형으로 복원한다.
- Gzip에는 생성 시각을 넣지 않는다. 따라서 내용이 같으면 압축 파일의 byte도 같다.
- 지표 열 이름(`w_bytes`, `ddr3_traffic_kib`, `min_deadline_margin_ms` 등)은 그림 script가 쓰는 형식이다.

`summarize`는 여러 실행의 결과를 합친다.

- 히스토그램을 합친 뒤 해당 구간의 상단 경계값으로 p99를 구한다.
- `w_kib`·`ddr3_traffic_kib`는 측정 구간 byte ÷ 측정 구간에 연산한 추론 요청 수 ÷ 1024다.
- `ddr3_used_bandwidth_mbps`는 byte ÷ 측정 구간 시간이다.

`seed_stats`는 seed마다 시나리오 결과를 먼저 합친다. 이 값으로 seed 사이의 표준편차, 95% bootstrap CI(재표본 2,000개), 최솟값·최댓값을 구한다.

## 8. 검증

검증 항목은 [07_SIMULATION.md](../design_references/07_SIMULATION.md) §5에 있다. 모두 `test_engine.py`에 있다.

## 9. 관련 문서

- [07_SIMULATION.md](../design_references/07_SIMULATION.md): 비용·지연 모델, workload, 모델링하지 않는 것
- [04_MEMORY.md](../design_references/04_MEMORY.md) §3: weight cache와 PNU 교체 식
- [05_SCHEDULING.md](../design_references/05_SCHEDULING.md): Grouping, Offset Assignment, deadline 분석
- [08_EVALUATION.md](../design_references/08_EVALUATION.md): 지표, 비교군, 실험 목록
- `simulation/environment/template.toml`: 키 설명과 제안 구성
