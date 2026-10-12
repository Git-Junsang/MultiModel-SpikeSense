# 모델 크기와 scheduler 실험

관련 문서: [P3.6~P3.8 보고서](<../reports/P3.6~3.8 Research Report.md>), [SIM_PLAN.md](SIM_PLAN.md), [결과 index](../../software/sim_result/INDEX.md)

## 1. 목적

P3.5에서는 L 모델·512트랙이 너무 가벼워 정책 차이가 거의 없었다. 그래서 두 질문을 따로 확인했다.

1. 현재 모델 크기가 정확도에 필요한가?
2. 확정한 모델에서 cache, scheduler, 연산 순서가 최대 트랙과 전송량을 얼마나 바꾸는가?

기준 목표는 40모델·512트랙·32 ms다. 이 문서의 1,024트랙 안은 simulation 결과에 따른 제안이다.

## 2. 모델 크기

### 2.1 후보와 판정 기준

| 이름 | 구조 | Weight/model | 뉴런 |
|---|---|---:|---:|
| XS | `40→64→32→2` | 4,672 B | 98 |
| P | `40→128→32→2` | 9,280 B | 162 |
| S | `40→128→64→32→2` | 15,424 B | 226 |
| M | `40→256→128→64→2` | 51,328 B | 450 |
| L | `40→384→256→64→2` | 130,176 B | 706 |
| XL | `40→768→512→128→2` | 489,728 B | 1,410 |

L보다 작은 4개 모델은 40대를 같은 조건으로 다시 학습했다. FP32, INT8, INT6, INT4를 비교했다.

사전 통과 기준:

- 평균 AUC ≥ 0.9504
- AUC 0.9 이상 장비 ≥ 35대
- 통과한 조합 중 40모델 weight 합계가 가장 작은 조합 선택

학습 조건은 batch 512, 60 epoch, seed 42다. 장비마다 seed 하나만 썼다.

### 2.2 작은 모델 결과

| 구조·bit | 40모델 합계 | 평균 AUC | L INT8 대비 | 0.9 이상 | 판정 |
|---|---:|---:|---:|---:|---|
| L INT8 | 5.21 MB | 0.9559 | 기준 | 35 | 통과 |
| L INT6 | 3.91 MB | 0.9528 | −0.003 | 35 | 통과 |
| L INT4 | 2.60 MB | 0.8946 | −0.061 | 25 | 실패 |
| M INT8 | 2.05 MB | 0.9493 | −0.007 | 34 | 실패 |
| P INT8 | 0.37 MB | 0.9430 | −0.013 | 33 | 실패 |
| S INT8 | 0.62 MB | 0.9382 | −0.018 | 31 | 실패 |
| XS INT8 | 0.19 MB | 0.9272 | −0.029 | 30 | 실패 |

작은 모델 4개는 모두 L보다 낮았다. 차이는 −0.007~−0.029, Wilcoxon p≤0.015였다. 선행 P 구조는 40대 중 34대에서 낮았다. L 크기는 정확도 근거가 있다.

L INT6은 사전 기준을 통과했지만 채택하지 않았다. 정수 pipeline과 threshold 정밀도를 다시 설계해야 하기 때문이다.

### 2.3 XL 결과

| 모델 | 평균 AUC | L 대비 95 % CI | Wilcoxon p |
|---|---:|---|---:|
| L INT8 | 0.9559 | 기준 | — |
| XL INT8 | 0.9608 | +0.005, −0.004~+0.014 | 0.030 |
| XL INT6 | 0.9565 | +0.001, −0.009~+0.010 | 0.99 |

전체 평균 이득은 작고 CI가 0을 포함한다. 장비 종류별 결과는 달랐다.

| 장비 | M | L | XL |
|---|---:|---:|---:|
| valve 7대 | 0.871 | 0.905 | 0.940 |
| 나머지 33대 | L 대비 −0.001 | 기준 | L 대비 −0.002 |

valve는 7대 모두 XL에서 좋아졌다. 나머지는 M부터 거의 포화했다. 모든 모델을 같은 크기로 쓰는 방식은 정확도와 자원 면에서 비효율적일 수 있다.

### 2.4 소리 overlap

다른 장비의 정상음을 waveform에 섞어 학습·평가했다.

| 조건 | 평균 AUC |
|---|---:|
| L, clean 학습·clean 평가 | 0.956 |
| L, clean 학습·random overlap 평가 | 0.755 |
| L, overlap 학습·random overlap 평가 | 0.821 |
| XL, overlap 학습·random overlap 평가 | 0.826 |
| XL, overlap 학습·strong −6 dB 평가 | 0.765 |
| L, easy overlap +6 dB | 0.906 |

XL은 L보다 random overlap에서 +0.005, strong −6 dB에서 +0.010 높았다. Valve의 strong −6 dB 차이는 +0.052였다. Clean 평균만으로 XL을 고를 근거는 약하지만, overlap과 valve 결과는 XL 쪽을 지지한다.

### 2.5 모델 제안

P3.8 simulation 기준은 **XL INT8 + overlap augmentation**으로 잡았다. 이유는 valve 7/7 향상과 overlap에서의 이득이다.

한계:

- 40대 평균 이득은 통계적으로 약하다.
- 장비별 학습 seed는 하나다.
- overlap 세기가 실제 현장과 같은지 확인하지 않았다.
- 이 선택은 `PROPOSAL.md`의 L 모델을 아직 대체하지 않는다.

## 3. 요청 시나리오

| ID | 상황 | 설정 |
|---|---|---|
| U | 균등 | 40모델 균등, random phase |
| K | 편중 | 상위 5모델 53 % |
| S | 동시 도착 | 모든 track phase 같음 |
| I | 간헐 입력 | 주기마다 요청 확률 적용 |
| SK | 동시+편중 | S와 K 결합 |
| R | random congestion | phase와 혼잡도 random |

모든 시나리오에서 deadline miss 0인 최대 트랙을 찾는다. stage 1은 seed 3개, 확인은 seed 20개다. S·SK는 worst phase 해석값도 함께 쓴다.

## 4. Design-space search

### 4.1 비교 축

| 축 | 후보 |
|---|---|
| lane | 32, 64, 128, 256 |
| 막전위 | BRAM / DDR3 |
| 저장 | 전체 cache, 부분 상주, 혼합, stream |
| scheduler | FCFS, EDF, Grouping, Score |
| 연산 | 한 번에 / 한 줄씩 |

Host는 1 ms마다 입력과 출력을 묶는다. 막전위 DDR3 비용은 read 1,412 B와 write 1,412 B다. 한 줄씩 연산은 최대 64트랙을 묶는다.

256 lane은 simulation 상한 확인용이다. RTL 자원과 timing은 아직 확인하지 않았다.

### 4.2 L 모델 결과

| Lane | 막전위 BRAM | 막전위 DDR3 |
|---:|---:|---:|
| 32 | 656 | 656 |
| 64 | **944** | 1,312 |
| 128 | 896 | 2,336 |
| 256 | 832 | **3,696** |

막전위 BRAM은 capacity가 한계다. 막전위 DDR3는 연산이 한계다. 64 lane·BRAM의 944트랙은 stream + Grouping + 한 줄씩에서 나왔다.

### 4.3 XL 모델 결과

| Lane | 막전위 BRAM | 막전위 DDR3 |
|---:|---:|---:|
| 32 | 160 | 160 |
| 64 | 336 | 336 |
| 128 | 448 | 688 |
| 256 | 400 | **1,232** |

XL은 요청당 weight와 막전위가 커서 256 lane과 DDR3 state가 필요했다. FCFS는 약 176트랙에서 멈췄다.

## 5. 1,024트랙 제안안

### 5.1 고정 조건

| 항목 | 값 |
|---|---|
| 모델 | XL INT8 |
| lane | 256 @ 100 MHz |
| 막전위 | DDR3 |
| Host I/O | 1 ms batch |
| deadline | 생성→Host 결과 32 ms |
| 평가 | 6시나리오 × seed 20 |

시나리오별 miss 0 최대 트랙:

| U | K | S | I | SK | R |
|---:|---:|---:|---:|---:|---:|
| 1,328 | 1,312 | 1,232 | 5,328 | 1,232 | 1,632 |

S·SK가 전체 상한 1,232를 정한다. 1,024는 이 값의 83 %다. 외란 5조건에서도 miss 0을 확인했다.

### 5.2 저장·scheduler·연산 24조합

1,024트랙에서 24조합 중 8개가 miss 0이었다.

- FCFS·EDF는 모두 miss 100 %였다.
- 전체 cache는 latency가 가장 짧았다.
- 부분 상주와 고정 혼합은 XL의 약 4 %만 상주해 stream과 거의 같았다.
- 한 줄씩 연산은 작은 buffer를 쓰지만 전체 cache의 한 번에 방식보다 latency가 길었다.

초기 권고는 전체 cache entry 2개 + Grouping이었다. 이후 scheduler를 다시 비교했다.

## 6. Scheduler

### 6.1 최종 7개

| 범주 | 이름 | 규칙 |
|---|---|---|
| 기존 | FCFS | 도착 순서 |
| 기존 | EDF | deadline 순서 |
| 기존 | Grouping | 가장 오래된 요청의 모델을 모두 묶음 |
| 선행 | Dysta | 남은 처리 시간 + η×slack 최소, η=0.01 |
| 선행 | Timeout | 고정 시간 W만큼 기다린 뒤 Grouping |
| 제안 | SlackBatch-Lite | Grouping 순서, 보수적 합계 guard까지 대기 |
| 제안 | SlackBatch | Grouping 순서, 모델별 누적 deadline guard까지 대기 |

Timeout은 A cache에서 W=5 ms, stream에서 W=2 ms다. 조정 seed에서 miss가 없던 가장 큰 값을 썼다.

SlackBatch는 모델 순서를 바꾸지 않는다. 남은 weight 전송, 연산, state DMA, 결과 회수 시간을 slack에서 뺀 뒤 안전한 만큼 기다린다.

### 6.2 결과

A 전체 cache·한 번에, 1,024트랙 결과다.

| Scheduler | Miss | 평균 latency | Off-chip KB/req | Energy µJ/req | 외란 5조건 |
|---|---:|---:|---:|---:|---|
| FCFS | 100 % | 5.2 s | 442 | 73.6 | 실패 |
| EDF | 100 % | 5.2 s | 442 | 73.7 | 실패 |
| Grouping | 0 | 8.5 ms | 78.8 | 13.7 | 통과 |
| Dysta | 0 | 8.0 ms | 81.0 | 14.1 | 실패 |
| Timeout | 0.014 % | 10.7 ms | 68.9 | 12.1 | 실패 |
| SlackBatch-Lite | 0 | 11.3 ms | 40.2 | 7.3 | 통과 |
| **SlackBatch** | **0** | **14.0 ms** | **31.0** | **5.8** | **통과** |

SlackBatch는 Grouping보다 off-chip byte를 61 %, 추정 동적 energy를 58 % 줄였다. 평균 latency는 8.5→14.0 ms로 늘었다. 외란 중 최대 응답은 29.8 ms였다.

Dysta는 순서만 바꿔 평균 latency가 6 % 줄었지만 전송은 줄지 않았다. DDR3 2.0 GB/s와 control overhead 조건에서 miss가 났다.

Timeout은 몰림에도 고정 W를 기다린다. W를 크게 둘 수 없어 전송 절감이 3~13 %에 그쳤고 평가 seed에서 이미 miss가 났다.

### 6.3 구현안

SlackBatch 구현 초안:

1. model FIFO가 가장 오래된 model 순서를 유지한다.
2. model별 oldest timestamp, request count, cache state를 저장한다.
3. FIFO를 앞에서부터 훑으며 누적 처리 시간이 각 deadline 안인지 확인한다.
4. 안전하면 기다리고, 늦어도 되는 마지막 시각에 실행한다.
5. 한 줄씩 묶음 한도 64를 넘은 요청은 FIFO 앞에 남긴다.

40모델 scan은 약 40~80 cycle로 예상한다. RTL로 확인하지 않았다. SlackBatch-Lite는 같은 block에서 단순 합계 guard mode로 넣을 수 있다.

runtime 비교 정책은 FCFS, EDF, Grouping, Dysta, Timeout, SlackBatch-Lite, SlackBatch다.

## 7. 결론과 상태

P3.9에 넘기는 제안:

- XL INT8 + overlap augmentation
- 256 lane, 막전위 DDR3
- 1,024트랙
- 전체 cache entry 2개
- SlackBatch

근거는 simulation이다. 256 lane timing, scheduler resource, 실제 energy, board deadline은 아직 확인하지 않았다. `PROPOSAL.md`의 512트랙·L 모델을 바꾸려면 별도 확인이 필요하다.

## 8. 재현

```bash
python3 software/sim_develop/run_sim.py --selftest

python3 software/sim_develop/target_exp.py \
  --stage fixed --n 1024 --seeds 20 \
  --sch fcfs,edf,final_grouping,final_dysta,final_timeout,slackbatch_lite,slackbatch \
  --prefix p38f --only A:한번에,A:한줄씩,D:한줄씩
```

`--stage`는 `cap`, `verify`, `fixed`, `margin`을 쓴다. 결과는 `software/sim_result/p38f_*`다. 그림은 `plot_target.py --n 1024`로 만든다.

이전 `p38`, `p38s`, `p38t`, `p38t2`는 중간 실험 기록이다. 파일 뜻은 [sim_result/INDEX.md](../../software/sim_result/INDEX.md)를 따른다.
