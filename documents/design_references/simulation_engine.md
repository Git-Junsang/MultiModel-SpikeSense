# Simulation engine

## 1. 요약

engine은 환경 파일 하나를 실험 하나로 돌리는 event simulator다. 이 문서는 코드 구조, 코드에 들어간 식, 환경 키, 결과 CSV 형식을 적는다. 비용·지연 모델과 workload의 근거는 [07_SIMULATION.md](07_SIMULATION.md), 지표의 뜻은 [08_EVALUATION.md](08_EVALUATION.md) §2에 있다.

```bash
python3 simulation/engine/engine.py simulation/environment/<환경>.toml --jobs 11
python3 simulation/engine/test_engine.py             # 모두
python3 simulation/engine/test_engine.py p326 env    # 고른 부만(core p325 p326 env csv)
```

## 2. 파일과 객체

모두 `simulation/engine/`에 있다. `engine.py`가 실행기이고 부품은 종류별로 `part_*.py`에 나눠 두었다.

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
| `part_deadline.py` | `bound`, `DelayPattern`, `model_group_delay_stats`, `host_max_us` | deadline 분석: 조건부 response time 식과 adversarial search의 지연 꼴 |
| `part_result.py` | `read_csv`, `write_csv`, `summarize`, `seed_stats` | 결과 CSV와 실행 합산 |
| `test_engine.py` | | 손계산·결과 재현 시험 |

코드 규칙은 다음과 같다.

- 상태를 가진 것은 class로, 입력을 받아 값을 내는 계산(지표, Belady 하한, CSV)은 함수로 둔다.
- 부품(cache 정책·scheduler·연산)은 `Part(hw, **attrs)`로 만든다. 키워드 인자는 class에 이미 있는 속성만 바꿀 수 있다. 환경의 `cache_attrs`·`scheduler_attrs`도 같은 규칙이다.
- 부품은 모두 `reset(wl)`로 실행 하나를 시작한다. 결정에 쓰는 queue와 시각은 속성으로 넣지 않고 인자로 넘긴다: `scheduler.pick(queue, T, cache, busy_until)`, `cache.plan(m, queue, T)`, `compute.run(T, nbytes, members)`. BRAM tile은 cache 정책과 연산 모두 `tiles()`로 낸다.
- 같은 종류는 같은 method를 가진다. Cache 정책은 `peek`·`plan`·`predict`·`stats`, scheduler는 `pick`·`members`, Host 처리 지연 분포는 `draw`·`surv`·`delta`·`quantile`, mode는 `jobs`·`one`·`summary`·`job_rows`·`table`이다.
- 이름은 보고 뜻을 알 수 있게 짓고 단위를 붙인다(`PERIOD_US`, `dense_req_us`). 약어는 `CLK`처럼 널리 쓰는 것만 쓴다.
- 코드 안 문자열(부품 이름, 오류, 출력 표)은 영어로 쓰고 주석과 docstring은 한국어로 쓴다.

## 3. hardware 조건

`Hardware`는 실행 하나의 가속기 조건이다. 생성자 인자에서 아래 값을 정하고 부품과 추론 요청열이 이 값을 읽는다.

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
| `ddr3_used_bandwidth_mbps` | `ddr3_bandwidth_mbps` | DDR3 유효 bandwidth |

뉴런 그룹은 은닉 layer마다 ⌈뉴런 수 ÷ lane 수⌉개다. 그룹 하나는 lane 수만큼의 뉴런과 입력 전체로 이뤄지고 cycle마다 word 하나를 읽는다. 출력 layer(2뉴런 × 64입력)는 word ⌈128 ÷ lane 수⌉개에 묶는다. L·64 lane이면 그룹은 layer 1에서 6개(40 word씩), layer 2에서 4개(384 word씩), layer 3에서 1개(256 word), layer 4에서 1개(2 word)이고 합은 2,034 word다.

| 값 | 식 | L·64-lane |
|---|---|---|
| `dense_req_us` | (L1·출력 layer word + 가운데 layer word ÷ spikes_per_cycle(올림) + 67 × ctrl_scale) × 0.01 µs | 1,205 cycle = 12.05 µs |
| `model_bytes` | weight + β·vth(뉴런 706개 × 2 B를 64 B 단위로 올림) | 130,176 + 1,472 = 131,648 B |
| `entry_tiles` | word RAM tile. β·vth는 LUTRAM이라 뺀다 | 28.5 tile |
| `membrane_bytes` | ⌈뉴런 수 × bit ÷ 8⌉, 추론 요청마다 읽기와 쓰기 한 번씩 | 12 bit 1,059 B, 16 bit 1,412 B |
| `membrane_buf_tiles` | `membrane_place`가 `split`·`ddr`이면 membrane potential 준비 버퍼 등. split에서 모든 트랙이 on-chip이어도 둔다(`MEMBRANE_PREP_TILES`, [04_MEMORY.md](04_MEMORY.md) §2) | 4 tile |
| `tile_budget` | 365 − XDMA 20.5 − (on-chip이면 모든 트랙의 membrane potential tile) | 344.5 tile |

연산 cycle 식은 L·64 lane에서 RTL과 대조했다(P4.1). 다른 lane 수와 XL에도 같은 식을 쓰는데, 이는 RTL로 확인하지 않은 가정이다. `golden` 연산은 golden의 layer별 spike 수로 추론 요청마다 cycle을 정한다. 첫 timestep은 빼고 golden이 없는 41번째 모델은 40모델의 구간을 모아 쓴다.

Membrane potential 위치에 따라 추론 요청당 DDR3 전송이 달라진다.

| `membrane_place` | 뜻 | 추론 요청당 DDR3 |
|---|---|---|
| `split` (제안) | 남는 BRAM에 들어가는 트랙만 on-chip, 나머지는 DDR3. `split_membrane`이 정한다(§7.1) | `membrane_bytes` × (1 − on-chip 트랙 ÷ 전체 트랙). 평균으로 계산한다 |
| `onchip` | 모든 트랙을 BRAM에 둔다. 그만큼 `tile_budget`이 준다 | 0 |
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

### 4.1 시각 열과 만드는 순서

추론 요청마다 아래 시각을 둔다([01_OVERVIEW.md](01_OVERVIEW.md) §4).

| 열 | 정하는 방법 |
|---|---|
| `t_host` | nominal offset + k × 주기. Deadline = `t_host` + 32 ms |
| `t_ready` | `t_host` + Host 처리 지연(모델 그룹 지연 G + 추론 요청별 지연 j) |
| `t_send` | 즉시 송신이면 `t_ready`, 모아 보내기면 모델 그룹을 보내는 시각 |
| `t_arr` | `t_send` + 입력 링크 지연(PCIe 64 B H2C 실측 표본) |
| 연산 완료 | `simulate`가 정한다 |
| `t_recv` | 연산 완료 + 결과 링크 지연(64 B C2H 실측 표본). `Workload.recv_time` |

`Setup.workload`는 다음 순서로 추론 요청열을 만든다. 1·2는 `Setup`이, 3–5는 `Workload.make`가, 6–8은 `Workload`의 method가 한다.

1. 트랙 → 모델과 offset을 시나리오대로 뽑는다(uniform 균등, skewed 편중 ∝ 1/(k+1), synchronized·skewed-synchronized 동시 시작, intermittent 주기마다 추론 요청 확률 0.25, fluctuating 주기마다 활성 비율 Uniform(0.25, 1)). 코드의 시나리오 키(`part_workload.SCENARIOS`, 환경 키 `sim_scenarios`)는 아직 U·K·S·SK·I·R이다.
2. `host_offset`이 `model`이면 모델 m의 트랙을 m × 32 ms ÷ M에 둔다. `global`이면 모든 트랙을 0에, `none`이면 시나리오 값 그대로 둔다.
3. 추론 요청별 지연 j를 `host_jitter_dist` 분포에서 (트랙, 주기)마다 뽑는다. `host_model_group_delay_trace`가 있으면 모델 그룹 지연 G를 (모델, 주기)마다 더한다. 트랙 안에서 준비 순서가 뒤집히지 않도록 누적 최대를 쓴다. adversarial search처럼 (트랙, 주기) 지연을 직접 넘기면 누적 최대 없이 그대로 Host 처리 지연 전체로 쓴다.
4. 링크 지연 표본과 추론 요청별 연산을 넣는다.
5. 간헐적 추론 요청·운영 중 트랙 구성 변경으로 추론 요청을 거르고 FPGA 도착 순으로 줄 세운다. 두 분포는 PNU가 아는 분포로 추론 요청열에 남는다.
6. `host_gather_ms`가 0보다 크거나 `host_gather_to_max`가 참이면 `gather`로 모아 보내기를 한다. 모델·주기마다 모두 준비되거나 offset + D가 되는 시각에 한꺼번에 보낸다. `host_gather_to_max`면 D는 Host 처리 지연 최대(모델 그룹 지연 표의 최대 + J)다.
7. `host_packet_gap_us`가 0보다 크면 `packetize`가 같은 모델·주기·송신 시각의 추론 요청을 64 B 추론 요청 23개(MTU 1,500 B)씩 packet으로 나누고 j번째 packet을 j × 간격만큼 늦게 도착시킨다.
8. `host_fixed_delay_us`는 `delay`가 송신 전 모든 추론 요청에 같은 지연으로 더한다. Response time에 들어간다.

예열 주기(`sim_warmup_periods`)가 끝난 뒤 측정 주기(`sim_meas_periods`) 동안을 측정 구간으로 잡는다. 추론 요청 지표는 `t_host`가 측정 구간 안에 있는 추론 요청으로, DDR3 지표는 측정 구간에 연산을 시작한 batch로 센다.

### 4.2 Host 처리 지연 분포

분포마다 class가 하나 있고 모두 `Jitter`에서 나온다. 분포 class는 뽑는 방법(`_draw`)과 S(x)(`_surv`)를 정하고, 최대가 J와 다르면 `max_us`도 정한다. `draw`·`surv`·`delta`·`quantile`은 공통이다. `TraceJitter`는 기록을 재생하므로 `draw`와 분위수를 직접 정한다. 추론 요청열은 `draw`로 지연을 뽑는다. PNU는 실제 지연을 읽지 않고 분포의 `delta`·`quantile`·`max_us`만 쓴다. `Jitter.of(host_jitter_dist, J, trace)`가 환경 값으로 분포를 만든다.

| `host_jitter_dist` | class | 추론 요청별 지연 j |
|---|---|---|
| `none` | `NoJitter` | 0 |
| `uniform` | `UniformJitter` | 추론 요청·주기마다 Uniform(0, J) |
| `tail` | `TailJitter` | 95 % Uniform(0, b) + 5 % Uniform(b, J), b = min(0.8 ms, J) |
| `tail1` | `Tail1Jitter` | `tail`과 같은 꼴로 1% |
| `burst` | `BurstJitter` | 주기마다 5% 확률로 모든 추론 요청에 공통 Uniform(0, J), 여기에 추론 요청마다 Uniform(0, b) |
| `cd` | `CommonDelayJitter` | 주기 공통 Uniform(0, J/2) + 추론 요청마다 Uniform(0, J/2) |
| `static` | `StaticJitter` | 트랙마다 Uniform(0, J) 하나를 모든 주기에 쓴다 |
| `trace` | `TraceJitter` | 측정 CSV(`host_jitter_trace`) 재생 |

`delta(e, r)`는 남은 추론 요청 r개가 모두 e 뒤에 온다고 할 때 그중 첫 추론 요청까지 남은 시간의 기대값이다.

```text
δ(e, r) = ∫_e^max (S(x) / S(e))^r dx        S(x) = P(지연 > x)
uniform·static: δ(e, r) = (J − e) / (r + 1)
```

`TraceJitter`는 앞 절반 주기로 분포를 추정하고 뒤 절반 주기를 재생한다. 모델 그룹 지연 표(`host_model_group_delay_trace`, 행 = 모델)도 `TraceJitter`로 읽고, seed s마다 재생 구간의 s × (예열 + 측정 주기 수)번째 주기부터 쓴다. 같은 분포는 `Jitter.of`가 한 번만 만든다.

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

`simulate(wl, cache, scheduler, compute)`는 batch 하나 앞을 미리 정하며(1단 선행) 시간을 진행한다.

1. 결정 시각 T까지 FPGA에 도착한 추론 요청을 `Queue`에 넣는다. Queue가 비면 다음 도착으로 넘어간다.
2. `scheduler.pick(queue, T, cache, busy_until)`이 다음 모델을 고른다. busy_until은 compute array가 비는 시각이다. Scheduler가 기다리기로 하면 다시 고를 시각으로 넘어간다.
3. `cache.plan(m, queue, T)`이 적재할 byte를 정한다. hit면 0이고 miss면 `model_bytes`다.
4. `compute.run(T, nbytes, members)`이 적재 완료 시각과 연산 시작 s를 계산한다. Batch 구성원은 s에 확정하므로 T 이후 s까지 도착한 같은 모델 추론 요청도 들어간다.
5. 다음 결정 시각은 s다. 그래서 batch i를 연산하는 동안 batch i+1의 weight를 적재한다(prefetch).

`fpga_drop_busy`가 참이면 같은 트랙의 이전 추론 요청이 연산을 마치기 전에 도착한 추론 요청은 queue에 넣지 않고 버린다. 버린 추론 요청은 response time을 2주기로 적어 deadline miss로 센다([06_HOST_INTERFACE.md](06_HOST_INTERFACE.md) §4.3).

`belady`는 실행이 만든 batch 순서에 offline Belady MIN을 적용한 적재 수 하한이다. 측정 구간 시작의 entry 내용은 무엇이든 될 수 있다고 보고 둘째 batch부터는 직전 batch의 모델을 내보내지 않는다.

`detail=True`면 compute array cycle 회계(연산 + 정지 + 유휴 = 측정 구간)와 response time 분해(입력 + FPGA + 결과)를 더한다. 정지는 도착한 추론 요청이 남았는데 compute array가 쉰 cycle이고 유휴는 FPGA 안에 추론 요청이 없는 cycle이다.

## 6. 부품

### 6.1 Cache 정책

모든 정책은 weight entry 여러 벌에 모델 weight를 둔다. `cache_entries = 0`이면 entry 수는 ⌊(예산 − 준비 버퍼 − 메타데이터) ÷ `entry_tiles`⌋다(예산은 §7.1). Entry가 2벌보다 적으면 배치할 수 없다. hit면 그 entry를 가장 최근으로 옮긴다. miss인데 entry가 차 있으면 연산 중인 entry(가장 최근)를 뺀 후보 중 `predict` 점수가 가장 큰 모델을 내보낸다. 점수가 같으면 queue가 빈 모델, 그다음 오래 안 쓴 모델을 고른다.

| `cache_policy` | class | `predict` |
|---|---|---|
| `lru` | `LRU` | 모두 0. 가장 오래 안 쓴 모델을 내보낸다 |
| `offset_only` | `OffsetOnly` | queue에 추론 요청이 있으면 지금, 없으면 다음 nominal offset |
| `pnu_count` (제안) | `PNU` | [04_MEMORY.md](04_MEMORY.md) §3.1의 식 |
| `pnu_timeout` | `PNUTimeout` | 같은 식에서 예상 추론 요청 수를 모르고 r = 1 |
| `pnu_rtl` | `PNURTL` | `next_use_predictor.v`와 같은 정수 µs·표 계산 |
| `oracle_min` | `OracleMIN` | 실제 미래 도착(구현할 수 없는 비교 기준) |

PNU 계열의 세부는 다음과 같다.

- 모델 그룹 = (모델, nominal offset)이다. Offset Assignment면 모델마다 하나, 배정이 없으면 트랙마다 하나다.
- 예상 추론 요청 수는 그 주기 첫 추론 요청이 와야 안다. 그 전에는 직전에 안 값을 쓰고 처음에는 등록 트랙 수를 쓴다.
- τ는 분포의 `tau_q` 분위수다(기본 1.0 = 최대).
- `pred = "lut"`이면 δ를 경과 시간 `bin_us` 칸 × 남은 추론 요청 수 6칸 표에서 읽는다. 남은 수 칸은 1, 2, 3–4, 5–8, 9–16, 17 이상이다.
- `model_group_delay_aware = false`면 모델 그룹 지연 분포를 쓰지 않는다(P3.25 식).

모델 그룹 지연 분포가 없을 때의 식은 아래와 같다. 모델 그룹 지연이 있으면 04 §3.1의 식을 쓴다.

```text
kn = ⌊(now − O) / T⌋,  el = now − O − kn·T,  r = 예상 수 − 받은 수
r > 0 이고 el < τ:  t̂ = max(now, O + kn·T + el + δ(el, r))
그 밖:              t̂ = O + (kn + 1)·T + δ(0, n)
```

`PNURTL`은 시각을 µs 정수로 내리고 δ를 256 µs 칸 128개 표에서 읽는다. 모델 그룹마다 가장 최근 주기 하나의 (예상 수, 받은 수, 첫 도착)만 둔다. 추론 요청의 주기는 RTL처럼 도착 시각과 `t_host`로 판정한다. predictor 메타데이터로 0.5 tile을 더 쓴다.

정책마다 측정 구간의 교체에서 실제 다음 사용과 비교한 진단 값을 센다: 교체 수, Oracle MIN과 다른 victim 수, 예측 오차(50 µs 칸 히스토그램). 이 값은 교체 결정에는 쓰지 않는다.

### 6.2 Scheduler

| `scheduler` | class | 규칙 |
|---|---|---|
| `grouping` (제안) | `Grouping` | 가장 오래 기다린 추론 요청의 모델을 고르고 그 모델의 준비된 추론 요청을 모두 묶는다 |
| `dysta_method` | `Dysta` | 점수 = batch 시간 ÷ n + η × (deadline − t0 − batch 시간 − margin)이 가장 작은 모델의 추론 요청 전부 |
| `deeprt_method` | `DeepRT` | 모델마다 길이 W의 window를 두되 모델 m의 시작을 m·W/M로 다르게 하고 window가 끝나면 그동안 온 추론 요청을 job 하나로 묶어 job deadline 순서로 처리한다 |

- Dysta Method의 batch 시간 = 남은 적재 + membrane potential DMA + n × `dense_req_us`다. t0은 결정 시각과 compute array가 비는 시각 중 늦은 쪽이다. η 기본값은 1e-4(p325_dysta_method_tune에서 고른 값)다. margin 기본값은 결과 C2H 표본 최대 + 20 µs이고 `Dysta`를 만들 때 정한다.
- DeepRT Method의 `window = [W µs, flush]`에서 flush가 참이면 compute array가 놀 때 window 끝을 기다리지 않는다. 기본값은 [14,900 µs, false](p325_deeprt_method_tune에서 고른 값)다.
- 비교 실험의 환경 파일은 이 값을 `scheduler_attrs`에 그대로 적는다. 결과 CSV의 `scheduler_attrs` 열이 쓴 값을 남긴다.
- 비교군을 이렇게 옮긴 근거는 [08_EVALUATION.md](08_EVALUATION.md) §3에 있다.

### 6.3 연산

`Compute`는 DMA 하나와 compute array 하나의 시각을 따라간다. 필요한 weight가 교체될 entry에 모두 들어온 뒤 batch의 트랙을 하나씩 모델 전체로 연산한다.

```text
적재 완료 = max(T + 0.244 µs, 앞 DMA 완료) + 적재 B ÷ DDR3 대역폭     (앞 전송과 겹쳐 고정 비용이 숨는다)
연산 시작 s = max(적재 완료, compute array가 비는 시각)
추론 요청 i 완료 = s + 앞 추론 요청들의 연산 합 + 추론 요청 i의 연산
```

Membrane potential이 DDR3에 있으면 weight 전송 뒤에 추론 요청 수 × (읽기 B ÷ 읽기 bandwidth + 쓰기 B ÷ 쓰기 bandwidth)을 DMA에 더한다. 다음 batch의 적재는 그만큼 늦어진다. Membrane potential 읽기 지연은 준비 버퍼로 숨긴다고 가정한다.

## 7. 실행기

### 7.1 Setup 조립 순서

`Setup(e)`는 점 하나의 값 e로 다음을 차례로 만든다.

1. `Hardware`(§3)
2. `Compute`
3. Cache 정책. 예산은 `tile_budget` − `bram_reserve_tiles`(결과 CSV의 `budget`)이고 cache 정책에는 예산 − 준비 버퍼(`Compute.tiles()`)를 준다.
4. 쓰는 tile = cache 정책의 `tiles()`(entry × `entry_tiles` + 메타데이터) + 준비 버퍼. 예산을 넘거나 entry가 2벌보다 적으면 배치할 수 없는 점이고 run·bound·adversarial mode는 돌리지 않는다.
5. `split`이면 `Hardware.split_membrane`이 예산 − 쓰는 tile에 들어가는 가장 큰 16의 배수 트랙을 on-chip에 두고(`Setup.on_chip_tracks`) 추론 요청당 DDR3 membrane potential byte를 그 비율만큼 줄인다. Entry 4면 남는 200.5 tile에 768트랙(199 tile)이 들어간다(04 §2). `onchip`이면 `Setup.on_chip_tracks`는 트랙 전부, `ddr`이면 0이다.
6. Scheduler

`Setup.workload(scn, seed)`는 §4.1의 추론 요청열을 만들고 `Setup.run(scn, seed)`는 그 추론 요청열을 끝까지 돌린다.

### 7.2 환경 파일과 키 이름

환경 파일의 키는 `simulation/environment/template.toml`과 같아야 한다. 키를 빼거나 더하면 engine이 돌기 전에 멈춘다. 키 이름은 `대상_속성[_단위]`이다.

| 대상 | 키 |
|---|---|
| `sim` | `sim_mode`, `sim_scenarios`, `sim_seeds`, `sim_seed0`, `sim_warmup_periods`, `sim_meas_periods` |
| `model` | `model_size`, `model_count` |
| `compute` | `compute_lanes`, `compute_input`, `compute_spikes_per_cycle`, `compute_ctrl_scale` |
| `membrane` | `membrane_place`, `membrane_bits` |
| `bram`, `ddr`, `track` | `bram_reserve_tiles`, `ddr3_bandwidth_mbps`, `track_count` |
| `host` | `host_offset`, `host_jitter_ms`, `host_jitter_dist`, `host_jitter_trace`, `host_model_group_delay_trace`, `host_gather_ms`, `host_gather_to_max`, `host_packet_gap_us`, `host_fixed_delay_us` |
| `fpga` | `fpga_drop_busy` |
| `cache`, `scheduler` | `cache_policy`, `cache_entries`, `cache_attrs`, `scheduler`, `scheduler_attrs` |
| `search`, `tune` | `search_key`, `search_values`, `search_step`, `tune_attr`, `tune_values`, `tune_conds` |

`[sweep]`에서 축 이름이 환경 키면 그 키의 값 목록을 쓴다. 키가 아닌 축 이름은 값이 표여야 하고 표 하나가 여러 키를 한꺼번에 바꾼다. 표의 `label`은 결과의 점 이름이 된다. 점 이름은 축마다 생긴 이름표를 ` · `로 이어 만들고 축이 없으면 `base`다. `check`는 돌리기 전에 모든 점의 값을 확인한다.

### 7.3 mode

| `sim_mode` | 작업 하나 | 점별 요약 |
|---|---|---|
| `run` | (점, 시나리오, seed) 하나를 끝까지 돌린다. 배치할 수 없는 점은 건너뛴다 | `summarize` + seed 통계 |
| `search` | 점 하나에서 `search_key`를 `search_values` 순서로 바꿔 모든 시나리오·seed가 miss 0인 마지막 값을 찾는다. 통과가 값 순서에 대해 단조라고 보고 2배씩 넓힌 뒤 이분 탐색한다. `track_count`는 값 목록을 비우면 연산 가동률 100%까지 `search_step` 단위로 만든다 | 찾은 값, 상한 도달 |
| `tune` | (점, 후보 값) 하나를 `tune_conds` × 시나리오 × seed에 돌린다 | miss 0인 값들과 그중 weight byte가 가장 작은 값(같으면 최대 response time이 작은 값). 없으면 miss 난 실행이 가장 적은 값 |
| `bound` | 점 하나의 조건부 response time을 `part_deadline.bound`로 계산한다. Simulation은 돌리지 않는다 | R_single, R_cond, Host 처리 지연 최대 H, 같은 트랙 추론 요청 사이 최소 간격, 두 조건의 성립 여부 |
| `adversarial` | 점 하나에서 모델별 지연 꼴(`DelayPattern`)을 바꿔 가며 결과가 나온 추론 요청의 송신 뒤 최대(`t_recv − t_send`)를 키운다. 모델마다 같은 꼴인 시작점 30개, 무작위 시작점 8개를 시험한 뒤 가장 나쁜 꼴에서 모델 3개의 꼴을 바꿔 나빠지면 받기를 24번 한다 | 가장 나쁜 꼴의 지표(`adv_*`), 탐색한 모든 꼴에서 본 최대(`seen_*`), `bound`의 값 |

search·tune 실행은 측정 구간에서 deadline miss가 나는 즉시 멈춘다. adversarial의 탐색 난수는 송신 방식 키(`host_gather_ms`·`host_gather_to_max`·`host_packet_gap_us`)를 뺀 점 번호로 정해 송신 방식끼리 같은 시작점과 같은 난수열로 탐색한다. 결과는 관측 최대이고 증명이 아니다. bound·adversarial도 배치할 수 없는 점은 건너뛴다.

`bound`의 식은 [05_SCHEDULING.md](05_SCHEDULING.md) §6.1과 같다. 같은 트랙 추론 요청 사이 최소 간격은 즉시 송신이면 32 ms − (G_max − G_min) − J다. 모아 보내기도 대기가 끝난 뒤 준비된 추론 요청은 바로 보내므로 32 ms − (H − G_min)이고 즉시 송신과 같은 값이다. R_single이 이 간격보다 짧은 것은 바쁜 구간 하나에 같은 모델이 두 주기 들어가지 않을 필요조건이다.

| `DelayPattern` | 꼴 |
|---|---|
| 모델 그룹 지연(모델마다, 범위 [0, G_max)) | g0 0, gmax 최대, galt 주기마다 최대와 0을 번갈아, galign 모델 offset을 G_max 간격 경계까지 늦춰 여러 모델이 한꺼번에 도착, grand Uniform(0, G_max) |
| 추론 요청별 지연(트랙마다, 범위 [0, J)) | early 0, late 최대, spread 트랙 순서대로 0~최대, alt 트랙·주기마다 0과 최대를 번갈아, rand Uniform(0, J), pkt 모델의 앞 packet 하나(23트랙)는 0이고 나머지는 최대 |

### 7.4 결과 CSV

결과는 `simulation/result/<환경 이름>.csv`와 `<환경 이름>_runs.csv.gz`다.

| 파일 | 행 | 열 |
|---|---|---|
| `<이름>.csv` | 점 하나 | `point`, `label`, 환경 값 전부, `tiles`, `budget`, `feasible`, `on_chip_tracks`(split), mode 요약 |
| `_runs.csv.gz` (run) | (점, 시나리오, seed) | `point`, `label`, `scn`, `seed`, `simulate` 지표, `c_req`, `model_b`, `hist`(response time [칸, 개수], 0.05 ms 칸) |
| `_runs.csv.gz` (search) | (점, 시험한 값) | `point`, `label`, `key`, `value`, `passed` |
| `_runs.csv.gz` (tune) | (점, 후보) | `point`, `label`, `attr`, `value`, `fails`, `w_kib`, `ddr3_traffic_kib`, `max_ms` |
| `_runs.csv.gz` (bound) | 점 하나 | `point`, `label`, `bound` 값 |
| `_runs.csv.gz` (adversarial) | (점, 시험한 꼴) | `point`, `label`, `step`, `model_group_delay_pattern`, `request_pattern`, 그 꼴에서 송신 뒤 최대가 가장 큰 시나리오의 지표 |

- 칸 값은 문자열이면 그대로, 숫자·참거짓·목록·표면 JSON으로 쓴다. `read_csv`가 원래 값으로 되돌린다.
- gzip에는 시각을 넣지 않아 내용이 같으면 byte도 같다.
- 지표 열 이름(`w_bytes`, `ddr3_traffic_kib`, `min_deadline_margin_ms` 등)은 그림 script가 쓰는 형식이다.

`summarize`는 실행 여러 개를 합친다.

- p99는 히스토그램을 합쳐 칸 위 경계로 낸다.
- `w_kib`·`ddr3_traffic_kib`는 측정 구간 byte ÷ 측정 구간에 연산한 추론 요청 수 ÷ 1024다.
- `ddr3_used_bandwidth_mbps`는 byte ÷ 측정 구간 시간이다.

`seed_stats`는 seed마다 시나리오를 합친 값으로 seed 사이 표준편차, 95% bootstrap CI(재표본 2,000개), 최소·최대를 낸다.

## 8. 검증

| 확인 | 방법 |
|---|---|
| 본체 손계산 | 트랙 1–512개의 response time, DDR3 bandwidth, cycle 회계, Dysta Method·DeepRT Method 동작, 모아 보내기, membrane potential DMA 시간 |
| 정책 | 미래 지연을 바꿔도 PNU 결정이 같은지, queue·연산 중 entry 보호, 32 ms 경계, 동점 처리, Belady = 전수 탐색 최소 |
| 결과 재현 | p326_final_compare의 Dysta Method·DeepRT Method·제안 점(CPU 고정·부하 없음, J = 0.8 ms)을 다시 돌려 결과 CSV의 weight byte와 최대 response time이 같은지 |
| deadline 분석 | packet 분할 도착 시각, R_single이 손계산과 같고 05 §6.1의 14.41 ms·R_cond 24.22 ms가 나오는지, 지연 꼴 값, 작은 사례에서 adversarial search가 끝까지 돌고 고른 꼴이 가장 나쁜지 |
| 연산 cycle | P4.1 식과 일치, 모든 입력 spike 1,205 cycle |
| BRAM | entry 4와 entry 0(예산에 들어가는 최대)에서 entry + 준비 버퍼 + on-chip membrane potential이 예산 안이다. Entry 4면 768트랙 |
| 환경 파일 | 모든 파일을 읽고 BRAM에 들어가는 첫 점을 한 번 돌린다 |
| 결과 CSV | 쓰고 다시 읽은 값이 같다 |

모두 `test_engine.py`에 있다.

## 9. 관련 문서

- [07_SIMULATION.md](07_SIMULATION.md): 비용·지연 모델, workload, 모델링하지 않는 것
- [04_MEMORY.md](04_MEMORY.md) §3: weight cache와 PNU 교체 식
- [05_SCHEDULING.md](05_SCHEDULING.md): Grouping, Offset Assignment, deadline 분석
- [08_EVALUATION.md](08_EVALUATION.md): 지표, 비교군, 실험 목록
- `simulation/environment/template.toml`: 키 설명과 제안 구성
