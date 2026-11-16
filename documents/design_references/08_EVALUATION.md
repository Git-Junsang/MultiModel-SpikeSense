# 08. 평가

## 1. 요약

주요 평가 지표는 deadline miss, drop, DDR3 traffic, DDR3 bandwidth, response time이다. 비교군은 Model-Grouped Offset Assignment를 쓰지 않는 Dysta Method와 DeepRT Method다. 모든 트랙에 같은 nominal offset을 주는 global alignment도 비교한다. Offset Assignment, scheduler, cache의 효과는 각 요소를 하나씩 바꿔 확인한다.

방법 비교 결과는 Xeon에서 측정한 Host 처리 지연을 넣은 simulation이다. 최종 Host와 Ethernet을 통합한 시스템의 실측값은 아니다. 모델 그룹 지연을 넣지 않은 합성 민감도 실험은 §4.2에 따로 정리한다.

## 2. 지표

| 지표 | 정의 |
|---|---|
| deadline miss | response time이 32 ms를 넘었거나 결과가 없는 추론 요청. Drop을 포함한다 |
| drop | 같은 트랙의 이전 추론 요청이 FPGA 연산을 마치기 전에 도착해 버린 추론 요청 |
| DDR3 traffic | 측정 구간의 weight와 membrane potential 읽기·쓰기 byte ÷ 완료한 추론 수. KiB/추론 |
| DDR3 bandwidth | 같은 byte ÷ 측정 구간 시간. MB/s |
| response time | `t_recv − t_host` |
| 준비 완료 뒤 response time | `t_recv − t_ready`. 즉시 송신이면 입력 링크, FPGA 처리, 결과 링크. 모아 보내기면 Host의 송신 대기도 들어간다 |
| 송신 뒤 response time | `t_recv − t_send` |
| 최소 deadline 여유 | 측정 구간에서 구한 `32 ms − response time`의 최솟값 |
| hit rate | batch별 cache hit 비율 |
| 재적재 | 모델·주기당 첫 적재 뒤 다시 읽은 횟수 |
| 다음 사용 예측 오차 | 예측한 다음 사용 시각과 실제 다음 사용 시각의 평균 절대 오차 |
| BRAM | 사용 tile |

- 최댓값은 추론 요청별로 시간 차이를 구한 뒤 계산한다. Response time의 최댓값에서 Host 처리 지연의 최댓값을 빼서 구하지 않는다.
- 결과가 나온 추론 요청의 관측 최대와 결과가 없는 drop을 나눠 적는다.
- DDR3 traffic에는 seed 평균의 95% 신뢰구간을 적는다. Response time의 오차 막대는 seed별 최댓값의 범위를 나타내며, 신뢰구간과 구분한다.
- 간헐적 추론 요청 시나리오가 있으면 평균 추론 요청률이 낮아져 DDR3 traffic과 bandwidth가 같은 비율로 움직이지 않는다. 둘을 함께 적는다.
- Hit rate의 분모인 batch 수는 도착 과정과 정책에 따라 바뀌므로 DDR3 traffic과 함께 해석한다.
- 관측 최대나 p99가 32 ms보다 작아도 hard deadline을 보장하지는 않는다([05_SCHEDULING.md](05_SCHEDULING.md) §6).

## 3. 비교 규칙

모든 방법에 같은 입력, 트랙-모델 배정, 전체 BRAM 예산, DDR3 조건, compute array를 쓴다. 방법 비교의 구성은 모두 entry 4개와 on-chip 768트랙이다. Weight cache에는 114 tile을 배정하고, PNU에는 예측 표용 0.5 tile을 추가로 예약한다. 제안 기법은 모델별 frame offset을 바꾸므로 입력이 같아도 추론 요청의 도착 과정은 달라진다.

모든 방법에 같은 모델·주기별 모델 그룹 지연 G를 넣는다. 측정 Host는 모델당 25–26트랙을 offset 순서로 처리했다. 트랙이 많은 편중 배정 모델, global alignment, Offset Assignment가 없는 조건에서는 실제 Host 작업이 달라진다. 따라서 이 비교는 공통 지연 모델에서 FPGA 쪽의 차이를 보는 실험이다.

| 비교군 | 선택 이유 | 정책 적용 방법 | 대기 여부 | 선택한 설정 |
|---|---|---|---|---|
| Dysta Method (Sparse-DySta, MICRO'23) | hardware로 구현된 multi-DNN scheduler | 실행 시간·deadline 여유 점수를 모델별 batch에 맞게 바꾸고 weight 적재 비용을 batch 크기로 나눠 넣는다. 비선점 실행을 가정하므로 동적 선점과 실행 중 sparsity 갱신은 재현하지 않는다 | 없음 | η 15개(0–10) 중 10⁻⁴ |
| DeepRT Method (DeepRT, SEC'21) | 같은 모델의 추론 요청을 기다려 batch를 만드는 실시간 DNN 기법 | DisBatcher와 EDF를 적용한다. Admission control과 입력 해상도 조절은 넣지 않는다 | 있음 | window 2·4·8·12·14.9 ms × 조기 실행 on/off의 10개 설정 중 14.9 ms·off |

- 설정 조정에는 평가와 겹치지 않는 seed 100–109와 추론 요청별 합성 지연 조건을 썼다. 모든 조정 조건에서 deadline miss가 없는 설정 중 weight의 DDR3 traffic이 가장 작은 것을 골랐다.
- 측정한 모델 그룹 지연을 넣은 조건에서는 설정을 다시 조정하지 않았다. 따라서 해당 조건의 최적 설정이라고 주장하지 않는다.
- 결과는 원 논문이 보고한 성능이 아니라 공통 FPGA 모델에서 돌린 simulation 결과다. Scheduler 결정 시간과 회로 비용은 넣지 않았다. 원 논문의 정책을 옮긴 것이라 이름에 Method를 붙인다.

Cache 비교에서는 Model-Grouped Offset Assignment와 Grouping을 고정하고 교체 정책만 바꾼다. 비교 정책은 LRU, offset-only, PNU-Timeout, PNU-Count, 모델 그룹 지연을 무시한 PNU-Count, Oracle Belady MIN(이하 Oracle MIN)이다. 실행마다 고정 batch 순서에 대한 Belady 하한도 구한다.

## 4. 실험 목록

### 4.1 기준 결과

| 실험 | 결과 위치 | 환경 파일 또는 코드·자료 경로 | 그림 |
|---|---|---|---|
| 방법 비교 | 아래 표 | `p326_final_compare` | `compare/fig12` |
| Offset Assignment와 scheduler 분리, global alignment | [05_SCHEDULING.md](05_SCHEDULING.md) §4 | `p326_final_compare` | `compare/fig12` |
| 교체 정책 비교 | [04_MEMORY.md](04_MEMORY.md) §3.2 | `p326_cache_policy` | `compare/fig13`, `cache/fig1` |
| entry 수 | [04_MEMORY.md](04_MEMORY.md) §4 | `p326_jitter_entry` | 표 |
| 조건부 response time, adversarial search | [05_SCHEDULING.md](05_SCHEDULING.md) §6 | `p326_deadline_bound`(bound mode), `p326_deadline_adversarial`(adversarial mode) | 표 |
| Host 처리 지연 측정 | [06_HOST_INTERFACE.md](06_HOST_INTERFACE.md) §9.1 | `hardware/board_test/p325_meas/` | `delay/fig1` |
| 양자화 정확도 | [02_MODEL.md](02_MODEL.md) §3 | `software/model/eval/membrane_bits.py` | 표 |

방법 비교는 Xeon CPU 고정·부하 없음, entry 4개, 시나리오 6개 × seed 30개 조건이다. DDR3 traffic 값의 대괄호는 95% 신뢰구간이다. 시간은 결과가 나온 추론 요청의 관측 최대를 나타낸다. 모든 조건에서 deadline miss와 drop은 0이다.

| J (ms) | 방법 | DDR3 traffic (KiB/추론) | response time 관측 최대 (ms) | 준비 완료 뒤 response time 관측 최대 (ms) |
|---:|---|---:|---:|---:|
| 0 | Dysta Method | 56.44 | 10.25 | 6.13 |
| 0 | DeepRT Method | 11.26 | 23.20 | 16.70 |
| 0 | 제안 | 6.37 [6.36, 6.38] | 9.27 | 1.75 |
| 0.8 | Dysta Method | 56.62 | 10.58 | 6.90 |
| 0.8 | DeepRT Method | 11.35 | 23.80 | 16.41 |
| 0.8 | 제안 | 6.38 [6.37, 6.39] | 9.58 | 1.42 |
| 3.2 | Dysta Method | 58.74 | 12.11 | 8.57 |
| 3.2 | DeepRT Method | 11.63 | 26.02 | 16.39 |
| 3.2 | 제안 | 12.37 [12.27, 12.46] | 11.53 | 0.77 |

- J = 0.8 ms에서 제안 기법은 Dysta Method보다 DDR3 traffic이 88.7% 적다. Response time의 관측 최대는 9.4%, 준비 완료 뒤 response time의 관측 최대는 79.5% 짧다. 이 실험의 Host 처리 지연 관측 최대는 8.94 ms다. Host 처리 지연까지 포함한 response time에서는 개선 폭이 작아진다.
- J = 3.2 ms에서는 모델 그룹의 도착이 겹치고 재적재가 늘어 제안 기법의 DDR3 traffic이 12.37 KiB/추론이 된다. Dysta Method보다 DDR3 traffic은 78.9% 적고, response time의 관측 최대는 4.8% 짧다.
- DeepRT Method는 같은 모델의 추론 요청을 window 안에서 모아 DDR3 traffic을 줄이지만, response time의 관측 최대가 길다. J = 3.2 ms에서는 제안 기법보다 DDR3 traffic이 적다. 모든 조건에서 두 지표가 함께 가장 낮은 방법은 없다.

### 4.2 합성 민감도 (모델 그룹 지연 G = 0)

추론 요청별 합성 지연만 넣은 보조 실험이다. 모델 그룹 지연과 drop 규칙은 적용하지 않았다.

| 실험 | 결과 | 환경 파일 | 그림 |
|---|---|---|---|
| J를 넓힌 비교 | entry 4개인 제안 기법의 DDR3 traffic은 J = 3.2 ms까지 global alignment보다 적고, 4.8 ms부터 많다. Dysta Method보다는 시험한 J = 10 ms까지 적고, 15 ms부터 비슷하다 | `p325_crossover` | `compare/fig15` |
| DDR3 bandwidth | 1,024트랙에서 3,015 MB/s를 200 MB/s로 낮추면 제안 기법의 response time 관측 최대는 약 1.9 ms에서 2.7 ms로 늘어난다. Deadline miss는 없다. Dysta Method는 1,000 MB/s에서 deadline miss가 발생하고, DeepRT Method는 200 MB/s에서 queue가 계속 쌓인다 | `p325_scale_bandwidth` | `compare/fig14` |
| 트랙 수 | 3,015 MB/s에서 512트랙을 4,096트랙으로 늘리면 제안 기법의 response time 관측 최대는 약 0.9 ms에서 9.1 ms로 늘어난다 | `p325_scale_tracks` | `compare/fig14` |

합성 조건에서 얻은 교차점을 실제 Host가 허용할 수 있는 jitter로 해석하지 않는다. Bandwidth·트랙 수 실험은 합성 조건의 처리 여유를 보여 준다. 모델 그룹 지연을 넣었을 때의 최대 지원 트랙 수를 뜻하지는 않는다.

### 4.3 개념도

| 그림 | 내용 |
|---|---|
| `architecture/fig1` | 시스템 구조([03_ARCHITECTURE.md](03_ARCHITECTURE.md) §2) |
| `offset/fig5` | Offset Assignment와 실제 도착([05_SCHEDULING.md](05_SCHEDULING.md) §2) |
| `offset/fig6` | 모델 그룹 지연을 고려한 cache 교체 예([04_MEMORY.md](04_MEMORY.md) §3.1) |

그림은 `analysis/figure/`에 있다. 각 그림의 원자료는 생성 script 첫머리에 적었다. 현재 기준과 값이 다르거나 폐기한 그림은 `analysis/discards/`에 있다.

## 5. 보드 평가

| 단계 | 내용 |
|---|---|
| 기능 | 추론 요청 하나 → 여러 트랙 → 목표 부하 순서로 늘린다 |
| 부하 | track generator가 1,024트랙 trace를 재현 가능하게 만든다. USB mic demo는 통합 동작만 보이고 1,024트랙 성능 근거로 쓰지 않는다 |
| 계측 | FPGA counter(적재 수, weight·membrane potential byte, 연산·정지 cycle), 결과의 시각 필드, Host 수신 시각 |
| 비교 | 같은 trace를 simulator로 돌려 지표와 counter를 대조하고 차이의 원인을 찾는다 |
| 자원 | LUT, FF, DSP, BRAM, 100 MHz timing, 전력. 전력 측정 방법은 아직 정하지 않았다 |

보드 평가에서 바꿔 볼 후보는 Offset Assignment, entry 수, 교체 정책, spike 0 건너뛰기다. Offset Assignment는 Host 설정으로 바꾼다. 나머지 조건을 RTL에서 어디까지 변경 가능하게 할지는 아직 정하지 않았다.

## 6. 관련 문서

- [07_SIMULATION.md](07_SIMULATION.md): workload와 비용 모델
- [P3.26 보고서](<../reports/P3.26 Research Report.md>): 방법 비교, 교체 정책, entry 수, deadline 분석
- [P3.25 보고서](<../reports/P3.25 Research Report.md>) §4.1, §4.6, §4.10: 비교군 조정, 교차점, 확장성
- [P3.11 보고서](<../reports/P3.11 Research Report.md>): 비교군 정책 옮기기
