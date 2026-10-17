# 08. 평가

## 1. 요약

핵심 지표는 deadline miss, DDR3 전송량, 응답 시간이다. 비교군은 Dysta Method와 DeepRT Method 둘이고 offset 배정 없이 돌린다. 기여는 offset 배정과 offset-order cache를 켜고 끈 ablation으로 나눠 보인다. 나머지 실험은 제안 구성에서 한 가지씩 바꾼다. offset 배정을 하면 기다리지 않는 scheduler는 결과가 같아지므로 scheduler끼리의 비교는 하지 않는다.

## 2. 지표

| 지표 | 정의 |
|---|---|
| deadline miss | 응답 시간 > 32 ms이거나 결과가 오지 않은 추론 요청 수. 비율도 함께 적는다 |
| DDR3 전송량 | 측정 구간의 DDR3 전송 byte(weight + membrane potential) ÷ 추론 수. KiB/추론 |
| DDR3 전송률 | 측정 구간의 DDR3 전송 byte ÷ 시간. MB/s |
| 응답 시간 | frame 마지막 샘플의 수음부터 Host 결과 수신까지. 평균과 최대. simulation은 외부 지연을 따로 준다(`pre_us`, 기본 0) |
| 최대 트랙 수 | deadline miss 없이 동시에 처리하는 트랙 수 |
| BRAM | 사용 tile |

DDR3 전송량과 전송률은 함께 적는다. 추론 요청이 적은 시나리오(I, R)에서 두 값이 반대로 움직인다. p99가 32 ms보다 작다고 deadline 보장은 아니다. 보장은 worst case 계산으로 따진다([05_SCHEDULING.md](05_SCHEDULING.md) §6). 최종 end-to-end 평가에서는 오디오 장치, Host 전처리, Ethernet 링크의 지연을 직접 재서 넣는다.

## 3. 비교 규칙

같은 비교에서는 trace, 트랙-모델 배정, BRAM 용량, clock, DDR3 조건, cache 조건을 맞춘다. 제안 방식만 trace의 모델별 frame offset을 바꾼다.

| 실험 | 고정 | 바꾸는 것 |
|---|---|---|
| 방법 비교 | 같은 BRAM(entry 4 + 12 bit membrane potential), trace, DDR3 | 비교군 2개(offset 배정 없음, LRU)와 제안 |
| ablation | 같은 trace, membrane potential은 DDR3에 16 bit | offset 배정 있음·없음 × cache 없음·LRU·offset-order |
| 나머지 | 제안 구성(offset 배정, Grouping, offset-order 4) | 한 번에 한 가지 |

| 비교군 | 고른 이유 | 옮긴 방법 | 기다림 |
|---|---|---|---|
| Dysta Method (Sparse-DySta, MICRO'23) | 하드웨어로 구현된 multi-DNN scheduler | 실행 시간·deadline 여유 점수를 모델별 batch에 맞게 바꾸고 weight 적재 비용을 batch 크기로 나눠 넣는다. 비선점 실행이라 동적 선점은 재현하지 않는다. 계수 eta 0.0001 | 없음 |
| DeepRT Method (DeepRT, SEC'21) | 기다려 묶기의 대표, 실시간 DNN | DisBatcher와 EDF를 옮긴다. 모델별로 window(14.9 ms) 동안 온 요청을 모은다. admission control과 입력 해상도 조절은 넣지 않는다 | 있음 |

원 논문의 정책을 이 simulator로 옮긴 것이라 이름에 Method를 붙인다. 결과는 원 논문이 보고한 성능이 아니라 공통 FPGA 모델에서의 simulation 결과다. "옮긴 정책보다 낫다"까지만 말한다.

| ablation 이름 | offset 배정 | cache 교체 |
|---|---|---|
| Grouping(offset 배정 없음) | 없음 | LRU |
| HW만 | 없음 | offset-order |
| SW만 | 있음 | LRU |
| SW+HW (제안) | 있음 | offset-order |

P3.11~P3.13에서 쓴 다른 scheduler(Clockwork, Shepherd, Timeout, Symphony, SlackBatch)는 2026-10-16에 비교군에서 뺐다. Clockwork는 결과가 Dysta Method와 같았고 Timeout·Symphony는 DeepRT Method와 같은 계열이며 SlackBatch는 이전 제안이다.

## 4. 실험 목록

### 4.1 기준 결과

| 결과 | 값 | 환경 파일 | 그림 |
|---|---|---|---|
| 방법 비교(1,024트랙, entry 4) | 제안 6.36 KiB/추론·169 MB/s·평균 0.18 ms·최대 1.08 ms, Dysta Method 56.84·1,515·1.61·7.19, DeepRT Method 11.26·300·7.84·17.37 | `p321_compare` | `compare/fig2`, `compare/fig9` |
| 동시 도착(S) | 세 방법 5.2~5.5 KiB/추론. 최대 응답 시간 Dysta Method 7.1 ms, 제안 0.2 ms | `p321_compare` | `compare/fig1` |
| ablation | 표는 [05_SCHEDULING.md](05_SCHEDULING.md) §4.1 | `p313_ablation` | 표 |
| 비교군 + 같은 offset 배정·cache | Dysta Method 6.36·0.18 ms, DeepRT Method 6.36·7.96 ms | `p321_compare_offset` | 표 |
| jitter × cache | 표는 [04_MEMORY.md](04_MEMORY.md) §4 | `p321_compare_jitter`, `p317_jitter_wide` | `compare/fig3`, `compare/fig10` |
| offset 단위 모아 보내기 | entry 2로 약 6.26 KiB/추론, jitter 20 ms에서 최대 21.8 ms | `p317_gather` | `gather/fig1` |
| 트랙 수 512~1,536 | 제안 154→197 MB/s, 최대 0.24→2.30 ms. Dysta Method 888→1,680 MB/s. DeepRT Method 최대 15.8→19.0 ms. 모두 deadline miss 0 | `p321_compare_tracks` | `compare/fig4` |
| 최대 트랙 수 | 3.015 GB/s: 제안·Dysta Method 4,608, DeepRT Method 4,096. 1,000 MB/s: Dysta Method 1,024, DeepRT Method 4,096, 제안 4,608. 모든 input spike면 셋 다 1,024 | `p321_scale`, `p321_scale_bw` | `compare/fig6`, `fig8` |
| 4,096트랙 실행 | 제안 335 MB/s·최대 11.5 ms, Dysta Method 1,403 MB/s·27.9 ms, DeepRT Method 470 MB/s·31.3 ms | `p321_scale_run` | `compare/fig7`, `compare/fig11` |
| DDR3 대역폭 | 제안은 200 MB/s에서도 최대 1.05→2.44 ms. Dysta Method는 600 MB/s 이하에서 deadline miss, DeepRT Method는 300 MB/s에서 queue가 쌓임 | `p321_compare_ddrbw`, `p321_compare_bw` | `compare/fig5`, `compare/fig11` |
| 외부 지연 0~20 ms | 표는 [05_SCHEDULING.md](05_SCHEDULING.md) §6. DeepRT Method는 평상시 20 ms에서 21.9% miss | `p321_e2e`, `p321_adverse` | 표 |
| 정수화 정확도 | FP32 0.9563, INT8 16·12 bit 저장 0.9554 | `software/model/eval/membrane_bits.py` | 표 |

### 4.2 설계 근거 실험

| 실험 | 바꾸는 것 | 환경 파일 | 그림 |
|---|---|---|---|
| offset 배정 뒤 scheduler | scheduler 8개 | `p313_converge` | 표 |
| 도착 패턴 | 패턴 7개(membrane potential 16 bit 전부 DDR3) | `p313_arrival` | `arrival/fig1` |
| BRAM 배분 | entry 2~10 × membrane potential bit × jitter | `p313_tradeoff` | `entry/fig1` |
| offset 간격 | 같은 간격·트랙 수 비례 × jitter | `p317_offset_width` | `offset/fig2` |
| DDR3 membrane potential 배치 | 평균·트랙별(track_id·offset 순서) × 보내기 방식 | `p317_mem_place` | `membrane/fig3` |
| layer별 membrane potential bit (정확도) | layer마다 6~11 bit, 조합 | `software/model/eval/membrane_layer_bits.py` | `membrane/fig2` |
| layer별 membrane potential bit (BRAM) | 12 bit·[9, 9, 9, 12] × entry × jitter | `p319_layer_bits` | `entry/fig2` |
| 실시간 특징 정규화 | 방법 5개 × checkpoint 2개 | `software/model/eval/realtime_norm.py` | `normalization/fig1` |

그림은 `analysis/figure/` 아래에 있다. 결과는 [P3.13 보고서](<../reports/P3.13 Research Report.md>), [P3.21 보고서](<../reports/P3.21 Research Report.md>), [P3.22 보고서](<../reports/P3.22 Research Report.md>)에 있다. 값이 지금 기준과 다르거나 폐기한 설계의 그림은 `analysis/discards/`에 옮겼다.

## 5. 보드 평가

| 단계 | 내용 |
|---|---|
| 기능 | 추론 요청 하나 → 여러 트랙 → 목표 부하 순서로 늘린다 |
| 부하 | load generator가 1,024트랙 trace를 재현 가능하게 만든다. USB 마이크 demo는 통합 동작만 보이고 1,024트랙 성능 근거로 쓰지 않는다 |
| 계측 | FPGA counter(적재 수, weight·membrane potential byte, 연산·정지 cycle)와 결과의 시각 필드, Host 수신 시각 |
| 비교 | 같은 trace를 simulator로 돌려 지표와 counter를 대조하고 차이의 원인을 찾는다 |
| 자원 | LUT, FF, DSP, BRAM, 100 MHz timing, 전력. 전력 측정 방법은 아직 정하지 않았다 |

보드에서 바꿔 볼 축(offset 배정은 Host 설정, entry 수, 교체 규칙, spike 0 건너뛰기)을 RTL에서 어디까지 바꿀 수 있게 만들지는 미정이다.

## 6. 관련 문서

- [07_SIMULATION.md](07_SIMULATION.md): workload와 비용 모델
- [P3.11 보고서](<../reports/P3.11 Research Report.md>): 비교군 정책 옮기기와 조절값
