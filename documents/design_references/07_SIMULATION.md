# 07. Simulation

## 1. 요약

event simulator가 Host 추론 요청, scheduler, DMA, weight cache, membrane storage, compute array의 동작을 모델링한다. DDR3 비용은 보드 실측 회귀식, 연산 cycle은 compute array RTL의 식을 쓴다. Host 처리 지연은 Xeon에서 잰 모델 묶음 지연을 재생하고 추론 요청별 지연을 합성해 더한다. 결과는 보드 실측이 아니다.

## 2. 구성

| 구성 | 위치 |
|---|---|
| 엔진 | `simulation/engine/`. 실행기 [engine.py](../../simulation/engine/engine.py)가 환경 파일 하나(실험 하나)를 읽어 돌리고, 부품(하드웨어 조건, 추론 요청열, Host 처리 지연 분포, 시뮬레이터, cache 정책, scheduler, 연산, deadline 분석, 결과 CSV)은 `part_*.py`에 있다. deadline 분석(조건부 응답 시간, adversarial search)도 mode 하나씩이다. 구조·식·환경 키·CSV 형식은 [simulation_engine.md](simulation_engine.md) |
| 환경 | `simulation/environment/*.toml`. 제안 구성은 `template.toml`이다 |
| 결과 | `simulation/result/<환경 이름>.csv`(점별), `_runs.csv.gz`(실행별) |

실행 방법, 파일 이름 규칙, CSV 형식은 [README](../../README.md#simulation)에 있다.

## 3. 비용과 지연 모델

| 대상 | 모델링 방법 | 근거 |
|---|---|---|
| DDR3 | DMA 하나가 순서대로 처리. `T_read = 0.244 µs + B ÷ 3.015 GB/s`, `T_write = B ÷ 2.768 GB/s` | P3.1 보드 실측 |
| weight 적재 | parameter와 정렬을 포함한 131,648 B를 DMA 한 번으로 | slot 형식 |
| membrane potential | 12 bit. DDR3 트랙은 추론마다 1,059 B 읽기와 쓰기. on-chip 트랙은 그 비율만큼 추론 요청당 평균으로 뺀다. RTL은 beat 34개(1,088 B)를 전송해 DDR3 전송량이 약 0.2 % 크다 | 계산 |
| 연산 | test 입력의 spike 수로 `240 + 4⌈n1/2⌉ + ⌈n2/2⌉ + 2 + 67` cycle, 100 MHz. 모든 spike 발생은 1,205 cycle | P4.1 RTL |
| prefetch | 지금 batch를 연산하는 동안 다음 batch의 모델 전체를 빈 entry로 적재한다. 한 batch 앞만 본다 | 설계 |
| cache | entry 수와 교체 정책(LRU, offset-only, PNU-timeout, PNU-count, Oracle MIN). 실행마다 Belady 하한을 따로 낸다 | 설계 |
| Host 처리 지연 | 측정한 모델·주기별 묶음 지연 G + 추론 요청별 지연 j ~ Uniform(0, J) | Xeon 측정, 합성 |
| 링크 지연 | 입력과 결과에 PCIe 64 B 전송 실측 표본을 한 번씩 더한다 | P3.3. Ethernet 미측정 |
| 송신 | 즉시 송신. 모아 보내기는 비교 구성 | 설계 |
| 같은 트랙 순서 | 준비 순서가 뒤집히면 앞 주기의 준비 시각보다 이르지 않게 맞춘다. adversarial search는 넣은 지연을 맞추지 않고 그대로 쓴다(G + J > 32 ms면 순서가 뒤집혀 drop이 늘 수 있다) | Host 동작 |
| drop | 같은 트랙의 이전 추론 요청이 FPGA 연산을 마치기 전에 도착한 추론 요청은 버리고 deadline miss로 센다 | [06_HOST_INTERFACE.md](06_HOST_INTERFACE.md) §4.3 |
| 측정 | 16주기 예열 뒤 64주기(2.048 s)를 잰다 | |

simulator는 `t_host`, `t_ready`, `t_send`, `t_arr`, `t_done`, `t_recv`를 따로 둔다([01_OVERVIEW.md](01_OVERVIEW.md) §4).

Host 처리 지연 재생 규칙:

- 측정 원자료(조건마다 9,375주기)에서 처음 0.5 s를 빼고 모델·주기마다 G 하나를 뽑는다. 측정에서 모델 m은 트랙 번호를 40으로 나눈 나머지다.
- 앞 절반 4,679주기는 PNU가 쓰는 묶음 지연 분포로, 뒤 절반 4,680주기는 재생에 쓴다. seed s는 뒤 절반의 s × 80번째 주기부터 예열과 측정을 합친 80주기를 쓴다. seed 30개가 겹치지 않는다.
- j는 추론 요청·주기마다 새로 뽑는다.
- 모든 방법에 같은 모델·주기별 G를 넣는다. FPGA 쪽만 비교하려는 단순화다([05_SCHEDULING.md](05_SCHEDULING.md) §7).

모델링하지 않는 것: DDR3 refresh와 bank 충돌(회귀식의 평균으로만 들어감), control overhead 밖의 RTL pipeline 정지, scheduler 결정 시간과 회로, Ethernet, 전력.

## 4. Workload

트랙 1,024개, 모델 40개, 주기 32 ms다. 시나리오가 모델 배정, offset, 추론 요청 빈도를 정한다.

| 시나리오 | 모델 배정 | offset | 추론 요청 |
|---|---|---|---|
| uniform | 균등 | 트랙마다 무작위 | 매 주기 |
| skewed | 편중: 모델 k의 트랙 비율 ∝ 1/(k+1) | 무작위 | 매 주기 |
| synchronized | 균등 | 동시 시작 | 매 주기 |
| skewed-synchronized | 편중 | 동시 시작 | 매 주기 |
| intermittent | 균등 | 무작위 | 주기마다 25 %(간헐 추론 요청) |
| fluctuating | 균등 | 무작위 | 주기마다 켜진 트랙 비율 25~100 % 무작위(활성 트랙 변화) |

| 도착 조건 | offset |
|---|---|
| Unaligned | 시나리오의 offset 그대로 |
| Model-grouped (제안) | 모델 m의 트랙은 `O_m = m × 0.8 ms`. synchronized·skewed-synchronized에도 적용 |
| Global alignment | 모든 트랙의 nominal offset 0 |

| 실험 | J | seed |
|---|---|---|
| 방법 비교 | 0, 0.8, 3.2 ms | 시나리오 6개 × 30 |
| cache 정책 비교, entry 수 | 0, 0.8, 1.6, 3.2 ms | 시나리오 6개 × 30 |
| 비교군 조정 | 추론 요청별 합성 지연 | 100~109 (평가 seed와 겹치지 않음) |
| 합성 민감도: 교차점 (G = 0) | 0.8~20 ms | 시나리오 6개 × 30 |
| 합성 민감도: DDR3 대역폭·트랙 수 (G = 0) | 0.8 ms | 시나리오 6개 × 10 |

합성 민감도 실험은 묶음 지연 없이 추론 요청별 지연만 넣었고 drop 규칙을 쓰지 않았다.

## 5. 검증

| 확인 | 방법 |
|---|---|
| simulator 본체 | [test_engine.py](../../simulation/engine/test_engine.py) 1부: 적재·hit 시간, 전송량, 비교군 정책 동작, 모아 보내기를 손계산과 비교 |
| 미래 정보 | 미래 추론 요청의 지연만 바꿔도 그 전 시각의 PNU-count·PNU-timeout 결정이 같다. Oracle MIN은 바뀐다 |
| 묶음 지연 | 같은 모델·주기 추론 요청이 같은 G를 받는다. 묶음 지연을 넣은 PNU 예측이 손계산과 같다 |
| drop | 앞 추론 요청이 늦게 끝나면 다음 추론 요청을 버리고 miss와 drop으로 센다 |
| 연산 cycle | rtl67 cycle이 P4.1 식과 같고 모든 spike 발생이 1,205 cycle이다 |
| BRAM | entry 4와 entry 0(예산에 들어가는 최대)에서 entry + 준비 버퍼 + on-chip membrane potential이 예산 안이다. entry 4면 on-chip 768트랙 |
| deadline 분석 | packet 분할 도착 시각, R_single 손계산과 05 §6.1의 14.41 ms·R_cond 24.22 ms, 지연 꼴 값, 작은 사례에서 adversarial search가 끝까지 돌고 고른 꼴이 가장 나쁜지 |
| Belady 하한 | 작은 예에서 전수 탐색 최솟값과 같다 |
| 환경 파일 | test_engine 3부: 환경 파일을 모두 읽고 첫 점을 한 번 돌린다 |
| 결과 CSV | test_engine 4부: 쓰고 다시 읽은 값이 같다 |
| 결과 재현 | test_engine이 p326_final_compare의 Dysta Method·DeepRT Method·제안 점을 다시 돌려 결과 CSV의 weight byte와 최대 응답 시간이 같은지 본다 |

방법 비교는 계산 서버 두 대에서 한 번씩 돌려 값이 같았다(P3.26).

## 6. 추가할 것

| 항목 | 이유 |
|---|---|
| 목표 Host의 묶음 지연 표 | 지금은 Xeon 측정이다. 라즈베리파이 5 측정값으로 바꾼다 |
| 추론 요청별 퍼짐 측정값 | 지금 j는 합성이다. UDP 송신까지 포함한 측정 분포로 바꾼다 |
| Ethernet 지연과 packet 간격 | 지금은 PCIe 64 B 표본이고 packet 분할은 adversarial search의 모아 보내기에만 넣었다 |

## 7. 관련 문서

- [08_EVALUATION.md](08_EVALUATION.md): 지표와 실험 목록
- [P3.26 보고서](<../reports/P3.26 Research Report.md>) §2: 묶음 지연, PNU 예측, drop 규칙
- [P3.25 보고서](<../reports/P3.25 Research Report.md>) §3: 추론 요청 시각 분리, 지연 분포, 교체 정책, rtl67
- [P3.14 보고서](<../reports/P3.14 Research Report.md>): 옛 실험 script와 engine의 차이
