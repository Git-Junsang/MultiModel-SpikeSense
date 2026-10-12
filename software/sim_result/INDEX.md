# Simulation 결과 index

이 폴더의 값은 simulation 결과다. DDR3·PCIe 비용에는 보드 실측값을 썼지만, accelerator 보드 성능 실측은 아니다.

해석 문서: [SIM_PLAN.md](../../documents/design/SIM_PLAN.md), [MODEL_SIZE_PLAN.md](../../documents/design/MODEL_SIZE_PLAN.md)

## 1. 먼저 볼 파일

| 목적 | 파일 |
|---|---|
| 최종 scheduler 7개 비교 | `p38f_*` |
| 1,024트랙 근거 | `p38_cap`, `p38_verify`, `p38_margin_n1024` |
| 최종 그림 | `figures/fig18_*`, `figures/fig19_*` |

나머지는 중간 실험 기록이다.

## 2. 파일 형식

| 확장자 | 내용 |
|---|---|
| `.md` | 사람이 읽는 표 |
| `.jsonl` | 원자료, 한 줄에 JSON object 하나 |
| `.log` | 실행 stdout과 시간 |
| `figures/` | 결과 그림 |

`.md`는 같은 이름의 `.jsonl`에서 만든다.

## 3. 실험 prefix

| Prefix | 실험 | 상태 |
|---|---|---|
| `sim_n*`, `summary_n*` | P3.5 24조합 | 기록 |
| `sweep_n*` | DDR3 bandwidth sweep | 기록 |
| `dse_capacity` | L model DSE rev 1 | 기록 |
| `dse2_*` | L model DSE rev 2 | 기록 |
| `dse2_xl_*` | XL DSE rev 2 | 기록 |
| `dse3_xl_*` | XL DSE rev 3 | 기록 |
| `fixedn_xl_n1000*` | 1,000트랙 비교 | 대체됨 |
| `p38_*` | P3.8 32개 설계 | 1,024트랙 근거 |
| `p38s_*` | score 방식 개선 | 기록 |
| `p38t_*`, `p38t2_*` | scheduler 후보 비교 | 기록 |
| **`p38f_*`** | **최종 scheduler 7개** | **현재 기준** |

`p38*` suffix:

| Suffix | 내용 | Seed |
|---|---|---:|
| `_cap` | scenario별 miss 0 최대 track | 3 |
| `_verify` | 최고 설계 재확인 | 20 |
| `_fixed_n1024` | 1,024트랙 지표 | 6 scenario ×20 |
| `_margin_n1024` | 외란 5조건 | 6 scenario ×20 |

공통 조건:

- scenario: U, K, S, I, SK, R
- 측정: 64주기, 2.048초
- warm-up: 16주기 제외
- Host I/O: 1 ms batch
- DDR3: 3.015 GB/s
- deadline: 생성→Host 결과 32 ms
- 평가 seed: 0~19

## 4. 이름

### 4.1 저장 정책

| 이름 | 뜻 |
|---|---|
| `A.전체캐시` | LRU model entry |
| `B.L1상주` / `B.부분상주` | 모든 model의 일부 weight 상주 |
| `C.혼합` / `C.고정혼합` | entry + 부분 상주 |
| `D.스트림` | weight cache 없음 |

### 4.2 연산

- `한번에`: model 전체 준비 뒤 연산
- `한줄씩`: neuron group 준비 뒤 연산

### 4.3 Scheduler

| 과거 이름 | 최종 이름 |
|---|---|
| `그룹핑` | Grouping |
| `Dysta식` | Dysta |
| `시간제한 묶음` | 중간 후보, 최종 Timeout과 다름 |
| `지연 그룹핑` | SlackBatch |
| `지연 그룹핑(간이 가드)` | SlackBatch-Lite |
| `점수`, `점수2`, `점수3` | 중간 후보, 미채택 |

최종 Timeout은 deadline guard 없는 고정 대기다. W는 A 5 ms, D 2 ms다.

## 5. JSONL 핵심 field

공통:

| Field | 뜻 |
|---|---|
| `storage`, `scheduler`, `compute` | 설계 |
| `n`, `scenario`, `seed` | workload |
| `tiles`, `feasible` | BRAM과 예산 통과 여부 |
| `miss`, `miss_rate`, `n_req` | deadline 결과 |
| `mean_ms`, `p99_ms`, `max_ms` | latency |
| `kb_req`, `w_kb_req` | 전체·weight off-chip KiB/request |
| `ddr_mbps` | 평균 DDR3 rate |
| `batch_mean`, `hit_rate` | 평균 묶음과 cache hit |
| `busy_frac`, `stall_frac`, `idle_frac` | compute 상태 비율 |

File별 추가 field:

| 파일 | 주요 field |
|---|---|
| `*_fixed_n*.jsonl` | scenario별 지표 `per`, cycle 분해 |
| `*_cap.jsonl` | `capacity`, `cap`, `cmp_util` |
| `*_verify.jsonl` | `stage1`, `verified`, `s_bound`, `guaranteed` |
| `*_margin_n*.jsonl` | `cond`, scenario별 miss `by`, `worst_ms` |
| `dse*_capacity.jsonl` | lane, state 위치, 최대 track, queue LUT |

단위:

- `_ms`: ms
- `kb`: KiB
- `mbps`: MB/s
- cycle: 100 MHz 기준
- `miss_rate`: 0~1

Energy는 JSONL에 직접 저장하지 않는다. `fixedn.energy_per_req()`로 weight·state byte와 architecture를 넣어 계산한다.

## 6. 그림

| 그림 | 내용 | 상태 |
|---|---|---|
| `fig1~4` | P3.5 bandwidth 실험 | 기록 |
| `fig5` | DSE rev 1 | 기록 |
| `fig6~13` | DSE rev 2, L·XL | 기록 |
| `discarded/fig14~17` | 최종 비교 전 후보 | 폐기 |
| **`fig18`** | 최종 7개 scheduler 비교 | 현재 |
| **`fig19`** | scenario·설계별 상세 | 현재 |

## 7. 재생성

명령은 [MODEL_SIZE_PLAN.md](../../documents/design/MODEL_SIZE_PLAN.md) §8에 있다. `.md` 표만 다시 만들 때는 `target_exp.py --stage <fixed|margin> --table`을 쓴다.
