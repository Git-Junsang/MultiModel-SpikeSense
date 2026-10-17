# 05. Model-Grouped Offset Assignment와 scheduler

## 1. 요약

기존 scheduler는 이미 도착한 요청의 순서와 batch만 바꾼다. 요청을 바로 처리하면 같은 모델의 다음 요청이 오기 전에 weight가 cache에서 밀려나 다시 읽어야 한다. 반대로 같은 모델 요청을 기다려 batch를 키우면 weight 재사용은 늘지만 기다린 시간이 응답 시간에 더해진다.

이 설계는 요청이 생기는 시각을 Host가 정한다. 같은 모델을 쓰는 트랙에 같은 offset을 배정하면 같은 모델의 요청이 FPGA에 함께 도착한다. 그래서 기다리지 않아도 batch가 커지고 scheduler는 가장 단순한 Grouping으로 충분하다. 1,024트랙의 deadline 보장은 worst case 계산(§6)으로 따진다.

## 2. Model-Grouped Offset Assignment

마이크는 쉬지 않고 녹음하므로 frame 경계를 어디에 둘지는 Host가 정한다. 경계를 0, 32, 64 ms에 두든 3.2, 35.2, 67.2 ms에 두든 frame 길이와 간격은 같고 모델이 받는 입력의 성질도 같다.

```text
O_m            = m × T/M = m × 0.8 ms        (T = 32 ms, M = 40, m = 0~39)
frame_end(t,k) = O_m(t) + k × T
```

m(t)는 트랙 t가 쓰는 모델 번호, k는 frame 번호다. 인접한 모델의 offset 간격은 0.8 ms이고 offset은 0~31.2 ms에 놓인다. 서로 다른 모델의 요청은 0.8 ms의 배수 간격으로 도착한다.

| 항목 | 내용 |
|---|---|
| Host가 할 일 | 트랙마다 64 ms frame을 만들고 모델의 offset을 기준으로 frame 끝 시각을 32 ms 간격으로 정한다. 트랙을 처음 켤 때 frame 몇 개 분량을 버리거나 기다려 맞춘다 |
| 바뀌지 않는 것 | 계산량, frame 길이, deadline(frame 끝 + 32 ms) |
| 가속기 쪽 변경 | cache 교체 규칙과 `offset_table` ([04_MEMORY.md](04_MEMORY.md) §3.1) |
| 편중 배정 | 한 모델에 트랙이 240개 안팎 몰리면 batch 하나가 1.6 ms로 offset 간격 0.8 ms보다 길다. 그래서 최대 응답 시간은 편중 배정(K·SK)에서 가장 길다. 방법 비교(seed 10)에서 1.08 ms, offset 간격 실험(seed 20)에서 1.55 ms였고 균등 배정에서는 0.23 ms다 |

모델과 상관없이 offset을 주기 안에 고르게 나눠 주면(CAN offset 배정 방식) DDR3 전송량이 무작위 offset과 같았다(81.6 대 80.6 KiB/추론, P3.13). 효과는 offset을 주는 데서가 아니라 같은 모델을 한 offset에 모으는 데서 나온다.

## 3. 즉시 입출력

Host는 frame이 끝나자마자 추론 요청을 보낸다. FPGA는 추론이 끝나자마자 결과를 보낸다. 입출력 대기가 없어 평균 응답 시간이 1.24 ms 준다(P3.12, 2.80 → 1.56 ms). simulation의 입출력 지연은 PCIe 64 B 실측 표본이고 Ethernet은 아직 재지 않았다. jitter가 클 때 Host가 offset 단위로 모아 보낼지는 jitter 측정 뒤 정한다([04_MEMORY.md](04_MEMORY.md) §4).

## 4. scheduler: Grouping

compute array가 다음 batch를 받을 수 있게 되면 아래 규칙으로 고른다.

| 결정 | 규칙 |
|---|---|
| 모델 | 대기 요청 중 `t_gen`이 가장 이른 요청의 모델. 같으면 `model_id`가 작은 쪽 |
| 구성원 | 구성원을 확정하는 시각까지 도착한 그 모델의 요청 전부 |
| 기다림 | 없다. 요청이 있으면 바로 처리한다 |
| 선점 | 없다. batch 연산이 시작된 뒤 도착한 요청은 다음 batch에서 처리한다 |
| 처리 순서 | batch 안에서는 `t_gen` 순서 |

Grouping은 대기 시간이나 deadline 계산이 필요 없어 하드웨어가 단순하다. 판단 시점과 적재의 관계는 [03_ARCHITECTURE.md](03_ARCHITECTURE.md) §3에 있다.

### 4.1 Grouping을 고른 근거

simulation, 1,024트랙, 시나리오 6 × seed 20, membrane potential은 모두 DDR3에 16 bit로 둔 조건이다.

| offset 배정 | cache | scheduler | DDR3 KiB/추론 | 평균 ms |
|---|---|---|---:|---:|
| 없음 | 없음 | Grouping | 54.0 | 2.06 |
| 없음 | LRU 10개 | Grouping | 52.0 | 1.63 |
| 있음 | 없음 | Grouping | 50.2 | 0.25 |
| 있음 | LRU 4개 | Grouping | 8.9 | 0.18 |
| 있음 | offset-order 4개 | Grouping | 8.6 | 0.18 |

offset 배정이 없으면 기존 scheduler들은 DDR3 전송량과 응답 시간을 맞바꾸는 한 곡선 위에 놓인다. offset 배정 없이 offset-order cache만 쓰면 DDR3 전송량이 약 10% 주는 데 그친다. offset 배정만 하고 cache가 없으면 50.2 KiB/추론으로 거의 줄지 않는다. 둘을 함께 써야 같은 모델의 weight를 여러 batch에서 다시 쓴다.

offset 배정의 효과는 scheduler와 무관하다. Dysta Method에 같은 offset 배정과 offset-order cache를 붙이면 Grouping과 같은 6.36 KiB/추론, 평균 0.18 ms가 나왔다. DeepRT Method에 붙이면 DDR3 전송량은 같았지만 window만큼 기다려 평균 응답 시간이 7.96 ms였다. 평가한 다른 scheduler도 offset 배정과 함께 쓸 때 Grouping보다 나은 결과가 없었다. 그래서 가장 단순한 Grouping을 쓴다.

## 5. jitter와 cache

jitter는 같은 모델 요청의 도착 시각이 배정된 offset에서 달라지는 시간 폭이다. Host 계산 시간과 링크 지연이 트랙마다 달라서 생긴다. 적재와 추론이 짧아서 jitter가 있으면 한 모델의 요청이 여러 batch로 나뉘어 처리된다. 이때 모델이 entry에 남아 있으면 다시 적재하지 않는다. 버틸 수 있는 jitter는 entry 수가 정한다([04_MEMORY.md](04_MEMORY.md) §4).

## 6. deadline 보장

worst case는 1,024트랙의 요청이 한꺼번에 도착하고 spike 0을 하나도 건너뛰지 못하는 경우다. 적재가 연산과 전혀 겹치지 않는다고 보수적으로 잡는다.

```text
R_FPGA ≤ N·C_dense + M·L_weight + N_DDR·C_state
       ≈ 1,024·22.4 µs + 40·43.9 µs + 256·1.2 µs ≈ 25 ms
```

C_dense는 dense 추론 1번(2,237 cycle), L_weight는 weight 적재 1번(131,648 B), C_state는 DDR3 트랙 하나의 membrane potential 읽기·쓰기(1,059 B씩)다. compute array를 쉬게 하지 않는 scheduler면 무엇을 써도 성립한다.

deadline은 수음 시각부터 재므로 외부 지연이 이 계산 앞에 더해진다. worst case로 보장하는 외부 지연은 약 7 ms다. 저지연 오디오 설정(1~4 ms)은 들어가고 기본 설정(10~20 ms)은 보장 밖이다. 보장 밖에서는 spike 0 건너뛰기와 offset 배정으로 줄어든 실제 응답 시간에 기댄다.

| 외부 지연 | Dysta Method, 평상시 | DeepRT Method, 평상시 | 제안, 평상시 | Dysta Method, 악조건 겹침 | DeepRT Method, 악조건 겹침 | 제안, 악조건 겹침 |
|---:|---:|---:|---:|---:|---:|---:|
| 0 ms | 7.2 / 0% | 17.4 / 0% | 1.1 / 0% | 25.2 / 0% | 29.9 / 0% | 10.5 / 0% |
| 10 ms | 17.2 / 0% | 27.3 / 0% | 11.1 / 0% | 35.2 / 5.1% | 39.9 / 7.3% | 20.5 / 0% |
| 20 ms | 27.2 / 0% | 37.3 / 21.9% | 21.1 / 0% | 45.2 / 21.5% | 49.9 / 39.4% | 30.5 / 0% |

칸은 최대 응답 시간 ms / deadline miss 비율이다(simulation). 악조건 겹침은 모든 input에 spike가 나고 제어 비용이 20% 늘고 DDR3 대역폭이 2.0 GB/s로 낮아진 조건을 함께 건 것이다. DeepRT Method는 batch를 만들려고 window만큼 기다려서 평상시에도 외부 지연 20 ms에서 deadline miss가 났다.

실행 중 deadline을 따로 확인하는 장치는 두지 않는다. Grouping은 처리 순서를 바꾸지 않고 1,024트랙에서는 위 계산으로 deadline이 지켜진다. 트랙을 늘리면 다시 계산한다.

offset 배정을 쓰면 Host는 앞으로 올 요청의 시각과 모델을 안다. 트랙을 받을 때 "한 주기의 일과 모델별 batch 길이가 32 ms 안에 드는가"를 한 번 확인하는 방식도 쓸 수 있다(선택, 미정).

## 7. 미정과 한계

- jitter를 재지 않았다. simulation은 jitter를 0.8 ms 균등분포로 가정했다. 측정 계획은 [06_HOST_INTERFACE.md](06_HOST_INTERFACE.md) §9에 있다.
- 늦게 도착하는 요청(1·5%가 최대 16 ms 지연)에도 deadline miss는 0이었지만 최대 응답 시간은 지연만큼 는다(17.4 ms, P3.13).
- 편중 배정에서 offset 간격을 모델의 트랙 수에 비례하게 주면 평균 응답 시간은 줄지만 DDR3 전송량이 는다. 기본은 같은 간격 0.8 ms다.

## 8. 관련 문서

- [P3.13 보고서](<../reports/P3.13 Research Report.md>): offset 배정 실험 전체
- [P3.13 배경 설명](<../reports/P3.13 Scheduling Primer.md>): 용어와 예시
- [P3.12 보고서](<../reports/P3.12 Latency Research Report.md>): 즉시 입출력, spike 0 건너뛰기
- [P3.21 보고서](<../reports/P3.21 Research Report.md>), [P3.22 보고서](<../reports/P3.22 Research Report.md>): 비교군 비교, 외부 지연
- [P3.11 보고서](<../reports/P3.11 Research Report.md>): 비교군 정책 옮기기와 조절값
