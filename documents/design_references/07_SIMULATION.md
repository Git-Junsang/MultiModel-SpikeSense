# 07. Simulation

## 1. 요약

Event simulator는 Host의 추론 요청과 FPGA의 scheduler, DMA, weight cache, Membrane Storage, compute array 동작을 모델링한다. DDR3 전송 시간은 보드 실측 회귀식으로 계산하고, 연산 cycle은 compute array RTL의 식을 쓴다. Host 처리 지연은 Xeon에서 측정한 모델 그룹 지연에 합성한 추론 요청별 지연을 더한다. 이 simulation의 결과는 보드 실측값과 구분한다.

## 2. 구성

`simulation/engine/engine.py`가 환경 파일(`simulation/environment/*.toml`) 하나로 실험 하나를 실행하고 결과를 `simulation/result/`에 CSV로 남긴다. 제안 구성은 `template.toml`이다. 코드 구조, 식, 환경 키, CSV 형식은 [simulation_engine.md](../manual/simulation_engine.md), 실행 방법은 [README](../../README.md#simulation)에 있다.

## 3. 비용과 지연 모델

| 대상 | 모델링 방법 | 근거 |
|---|---|---|
| DDR3 | DMA 하나가 전송을 순서대로 처리. `T_read = 0.244 µs + B ÷ 3.015 GB/s`, `T_write = B ÷ 2.768 GB/s`. RTL은 membrane potential 전송을 weight 적재 사이에 먼저 끼워 넣는다 | P3.1 보드 실측 |
| weight 적재 | parameter와 정렬을 포함한 131,648 B를 DMA 한 번으로 적재 | slot 형식 |
| membrane potential | 12 bit 저장. DDR3 트랙은 추론마다 1,059 B를 읽고 같은 양을 쓴다. On-chip 트랙 비율만큼 추론 요청당 평균 DDR3 전송을 줄인다. RTL은 beat 34개(1,088 B)를 전송하므로 DDR3 traffic이 약 0.2% 크다 | 계산 |
| 연산 | test 입력의 spike 수로 `240 + 4⌈n1/2⌉ + ⌈n2/2⌉ + 2 + 67` cycle, 100 MHz. 모든 spike 발생은 1,205 cycle | P4.1 RTL |
| prefetch | 지금 batch를 연산하는 동안 다음 batch의 모델 전체를 빈 entry로 적재한다. 한 batch 앞만 본다 | 설계 |
| cache | entry 수와 교체 정책(LRU, offset-only, PNU-Timeout, PNU-Count, Oracle Belady MIN(이하 Oracle MIN)). 실행마다 Belady 하한을 따로 구한다 | 설계 |
| Host 처리 지연 | 측정한 모델·주기별 모델 그룹 지연 G + 추론 요청별 지연 j ~ Uniform(0, J). G 표는 Xeon(P3.25) 또는 라즈베리파이 5(P3.16)에서 잰 값이다. 라즈베리파이 5에서 잰 j는 p99.9 17 µs라 J = 0으로 둔다(P3.17) | Xeon·라즈베리파이 5 측정, 합성 |
| 링크 지연 | 입력과 결과에 링크 지연 실측 표본을 한 번씩 더한다. PCIe 64 B(P3.3) 또는 라즈베리파이 5–보드 Ethernet(P3.16)을 환경 키 `host_link`로 고른다 | P3.3, P3.16 |
| 송신 | 즉시 송신. 모아 보내기는 비교 구성 | 설계 |
| 같은 트랙 순서 | 뒤 주기 추론 요청이 먼저 준비되면 앞 주기보다 이르지 않게 준비 시각을 조정한다. Adversarial search는 입력한 지연을 조정하지 않는다(G + J > 32 ms이면 순서가 뒤집혀 drop이 늘 수 있다) | Host 동작 |
| drop | 같은 트랙의 이전 추론 요청이 FPGA 연산을 마치기 전에 도착한 추론 요청은 버리고 deadline miss로 센다 | [06_HOST_INTERFACE.md](06_HOST_INTERFACE.md) §4.3 |
| 측정 | 16주기 예열 뒤 64주기(2.048 s)를 잰다 | |

Simulator는 `t_host`, `t_ready`, `t_send`, `t_arr`, `t_done`, `t_recv`를 따로 둔다([01_OVERVIEW.md](01_OVERVIEW.md) §4).

측정한 Host 처리 지연은 다음 규칙으로 simulation에 넣는다.

- 측정 원자료(조건마다 9,375주기)에서 처음 0.5 s를 제외하고 모델·주기마다 모델 그룹 지연 G 하나를 추출한다. 측정 당시 모델 번호 m은 트랙 번호를 40으로 나눈 나머지로 정했다.
- 앞 절반 4,679주기는 PNU가 참조할 모델 그룹 지연 분포를 추정하는 데 쓴다. 뒤 절반 4,680주기는 simulation 입력으로 쓴다. Seed s는 뒤 절반의 s × 80번째 주기부터 예열과 측정을 합친 80주기를 사용한다. Seed 30개의 입력 구간은 겹치지 않는다.
- j는 추론 요청·주기마다 새로 뽑는다.
- 모든 방법에 같은 모델·주기별 G를 넣는다. FPGA 쪽만 비교하려는 단순화다([05_SCHEDULING.md](05_SCHEDULING.md) §7).

DDR3 refresh와 bank 충돌은 회귀식의 평균 효과로만 반영한다. Control overhead 밖의 RTL pipeline 정지, scheduler 결정 시간과 회로 비용, Ethernet, 전력은 모델링하지 않는다.

## 4. Workload

Workload는 트랙 1,024개, 모델 40개, 주기 32 ms를 기준으로 한다. 시나리오별로 트랙의 모델 배정, offset, 추론 요청 빈도를 정한다.

| 시나리오 | 모델 배정 | offset | 추론 요청 |
|---|---|---|---|
| uniform | 균등 | 트랙마다 무작위 | 매 주기 |
| skewed | 편중: 모델 k의 트랙 비율 ∝ 1/(k+1) | 무작위 | 매 주기 |
| synchronized | 균등 | 동시 시작 | 매 주기 |
| skewed_synchronized | 편중 | 동시 시작 | 매 주기 |
| intermittent | 균등 | 무작위 | 주기마다 25%(간헐적 추론 요청) |
| fluctuating | 균등 | 무작위 | 주기마다 켜진 트랙 비율 25–100% 무작위(운영 중 트랙 구성 변경) |

| 도착 조건 | offset |
|---|---|
| unaligned | 시나리오의 offset 그대로 |
| Model-Grouped Offset Assignment (제안) | 모델 m의 트랙은 `O_m = m × 0.8 ms`. synchronized·skewed_synchronized에도 적용 |
| global alignment | 모든 트랙의 nominal offset 0 |

| 실험 | 추론 요청별 지연 조건 | seed |
|---|---|---|
| 방법 비교 | 0, 0.8, 3.2 ms | 시나리오 6개 × 30 |
| cache 정책 비교, entry 수 | 0, 0.8, 1.6, 3.2 ms | 시나리오 6개 × 30 |
| 비교군 조정 | 추론 요청별 합성 지연 | 100–109 (평가 seed와 겹치지 않음) |
| 합성 민감도: 교차점 (G = 0) | 0.8–20 ms | 시나리오 6개 × 30 |
| 합성 민감도: DDR3 bandwidth·트랙 수 (G = 0) | 0.8 ms | 시나리오 6개 × 10 |

합성 민감도 실험은 모델 그룹 지연 없이 추론 요청별 지연만 넣었고 drop 규칙을 쓰지 않았다.

## 5. 검증

| 확인 | 방법 |
|---|---|
| simulator 본체 | [test_engine.py](../../simulation/engine/test_engine.py) 1부: 적재·cache hit 시간, DDR3 traffic, 비교군 정책 동작, 모아 보내기를 손계산과 비교 |
| 미래 정보 | 미래 추론 요청의 지연만 바꿔도 그 전 시각의 PNU-Count·PNU-Timeout 결정이 같다. Oracle MIN은 바뀐다 |
| 모델 그룹 지연 | 같은 모델·주기 추론 요청이 같은 G를 받는다. 모델 그룹 지연을 넣은 PNU 예측이 손계산과 같다 |
| drop | 이전 추론 요청이 늦게 끝나면 다음 추론 요청을 버리고 deadline miss와 drop으로 센다 |
| 연산 cycle | rtl67 cycle이 P4.1 식과 같고 모든 spike 발생이 1,205 cycle이다 |
| BRAM | entry 설정 4와 0(예산에 들어가는 최대 entry 수)에서 entry + 준비 buffer + on-chip membrane potential이 예산 안에 들어가는지 확인. Entry 4개이면 on-chip 768트랙 |
| deadline 분석 | packet 분할 뒤 도착 시각과 지연 패턴 값을 확인. R_single이 손계산과 일치하고, [05_SCHEDULING.md](05_SCHEDULING.md) §6.1의 14.41 ms·R_cond 24.22 ms가 나오는지 확인. 작은 사례에서 adversarial search의 완료와 최댓값 선택을 확인 |
| Belady 하한 | 작은 예에서 전수 탐색 최솟값과 같다 |
| 환경 파일 | test_engine 3부: 환경 파일을 모두 읽고 첫 점을 한 번 돌린다 |
| 결과 CSV | test_engine 4부: 쓰고 다시 읽은 값이 같다 |
| 결과 재현 | test_engine이 p326_final_compare의 Dysta Method·DeepRT Method·제안 점을 다시 돌려 결과 CSV의 weight byte와 최대 response time이 같은지 본다 |

방법 비교 실험은 계산 서버 두 대에서 각각 실행했고 결과가 일치했다(P3.26).

## 6. 추가할 측정값

라즈베리파이 5의 모델 그룹 지연 표, 추론 요청별 퍼짐, Ethernet 링크 지연은 P3.17에서 넣었다. 남은 것은 아래 두 가지다.

| 항목 | 이유 |
|---|---|
| 부하 조건의 추론 요청별 퍼짐 꼬리 | busy loop 3개에서 드물게 2.2–5.5 ms 퍼졌다(P3.16, 원인 미확인). 지금은 넣지 않는다 |
| 부하 조건의 Ethernet 링크 지연 | 링크 지연 표본은 tcpdump를 켠 부하 없음 조건 하나에서 쟀다 |

## 7. 관련 문서

- [08_EVALUATION.md](08_EVALUATION.md): 지표와 실험 목록
- [P3.26 보고서](<../reports/P3.26 Research Report.md>) §2: 모델 그룹 지연, PNU 예측, drop 규칙
- [P3.25 보고서](<../reports/P3.25 Research Report.md>) §3: 추론 요청 시각 분리, 지연 분포, 교체 정책, rtl67
- [P3.14 보고서](<../reports/P3.14 Research Report.md>): 옛 실험 script와 engine의 차이
