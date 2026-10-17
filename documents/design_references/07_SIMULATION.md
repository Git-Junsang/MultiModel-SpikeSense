# 07. Simulation

## 1. 요약

architecture simulator는 Host 요청, scheduler, DMA, weight cache, membrane storage, compute array를 event 단위로 흉내 낸다. 설계 결정의 근거는 대부분 이 simulator다. DDR3 전송 비용과 입출력 지연에만 보드 실측값을 쓴다. 결과는 보드 성능 실측이 아니며 RTL을 만든 뒤 보드 동작과 대조한다.

## 2. 구성

| 구성 | 위치 |
|---|---|
| 엔진 | [engine.py](../../simulation/engine/engine.py) 한 파일. BRAM 계산, simulator 본체(가정 판 rev 4), 부품(저장 정책·연산 방식·scheduler), 실행기가 들어 있다. 환경 파일 하나(실험 하나)를 읽어 돌린다 |
| 환경 | `simulation/environment/*.toml`. 제안 구성은 `template.toml`이다 |
| 결과 | `simulation/result/<환경 이름>.csv`(점별), `_runs.csv.gz`(실행별) |

실행 방법, 파일 이름 규칙, CSV 형식은 [README](../../README.md#simulation)에 있다.

## 3. 비용 모델

| 대상 | 흉내 내는 방법 | 근거 |
|---|---|---|
| DDR3 전송 | DMA 하나가 순서대로 처리. read 한 번 = 0.244 µs + byte ÷ 3.015 GB/s. write는 2.768 GB/s | P3.1 보드 실측 회귀 |
| weight 적재 | 131,588 B (weight 130,176 B + 누설 계수·threshold 1,412 B). DDR3 slot의 32 B 정렬 padding은 빼고 센다 | 계산 |
| membrane potential | 추론마다 읽기 + 쓰기. 16 bit면 1,412 B, 12 bit면 1,059 B씩. layer마다 bit를 따로 줄 수 있다. on-chip 트랙은 비율만큼 요청당 평균으로 빼거나(`mem_place = avg`), 트랙별로 정한다(`id`, `offset`). 트랙별이면 DDR3 자리가 이어진 트랙끼리 읽기·쓰기 DMA를 한 번씩 하고 DMA마다 0.244 µs를 더한다 | 계산 |
| 연산 | 추론마다 spike 수에 따른 cycle ÷ 100 MHz. batch 안의 추론은 차례로 처리 | test 입력 80개의 spike 수, [03_ARCHITECTURE.md](03_ARCHITECTURE.md) §4 |
| 제어 비용 | dense word의 10% (203 cycle) | 가정 |
| 입출력 지연 | 64 B 전송 실측 표본에서 뽑는다 | P3.3 PCIe 실측. Ethernet은 미측정 |
| prefetch | 지금 batch를 연산하는 동안 다음 batch의 weight를 빈 entry로 받는다. 한 batch 앞만 본다 | 설계 |
| cache | entry 수와 교체 규칙(LRU, offset-order)을 그대로 따라간다 | 설계 |
| scheduler | compute array가 빌 때마다 정책 코드가 모델과 batch를 고른다 | `engine.py` 부품 |
| 측정 | 16주기를 버리고 다음 64주기(2.048 s)를 잰다 | |

흉내 내지 않는 것: DDR3 refresh와 bank 충돌(회귀식의 평균으로만 들어감), RTL pipeline의 세부 정지(제어 비용으로 뭉뚱그림), Host CPU 시간, Ethernet 지연, 전력.

## 4. Workload

트랙 1,024개가 각자 offset + 32 ms × k에 frame을 끝낸다. 이 시각이 수음 시각 `t_gen`이고 deadline의 기준이다. 외부 지연(`pre_us`, 오디오 buffer·전처리. 기본 0)과 입력 지연을 더해 FPGA에 도착한다. 시나리오가 offset, 모델 배정, 요청을 빠뜨리는 비율을 정한다.

| 시나리오 | offset | 모델 배정 | 요청 |
|---|---|---|---|
| U | 트랙마다 무작위 | 균등 무작위 | 매 주기 |
| K | 무작위 | 편중: 모델 k의 트랙 비율 ∝ 1/(k+1), 상위 5개 53% | 매 주기 |
| S | 모두 0 (동시 시작) | 균등 | 매 주기 |
| SK | 모두 0 | 편중 | 매 주기 |
| I | 무작위 | 균등 | 주기마다 25% (간헐 요청) |
| R | 무작위 | 균등 | 주기마다 켜진 트랙 비율 25~100% 무작위 (활성 트랙 변화) |

| 도착 패턴 | offset |
|---|---|
| offset 배정 없음 | 시나리오의 offset 그대로 |
| Model-Grouped Offset Assignment | 모델 m의 트랙은 m × 0.8 ms + [0, jitter) 균등 무작위. S·SK에도 적용 |
| offset 간격 비례 | offset 간격을 모델의 트랙 수에 비례하게 둔다(`offset = "model_w"`) |
| 고르게 나눈 offset | 모델과 상관없이 트랙의 offset을 주기 안에 고르게 나눈다 |
| 교대 | offset 배정 + 트랙 30%는 측정 중간에 합류, 30%는 중간에 이탈 |
| 지연 1·5% | offset 배정 + 요청의 1·5%가 0~16 ms 늦게 도착(생성 시각과 deadline은 그대로) |

Host offset 단위 모아 보내기(`gather_ms` = 대기 D)는 모델·주기마다 요청이 다 준비되거나 offset + D가 되면 한꺼번에 보낸다. 그 뒤에 준비된 요청은 준비되는 대로 보낸다.

| 악조건 | 바꾸는 것 |
|---|---|
| 전송 꼬리 +700 µs | 모든 입출력에 700 µs |
| 제어 비용 +20% | 제어 배수 1.1 → 1.2 |
| DDR3 2.0 GB/s | 실행 대역폭만 낮춤 |
| 모든 input spike | dense와 같은 연산 시간 |
| 악조건 겹침 | 모든 input spike + 제어 비용 +20% + DDR3 2.0 GB/s |

방법 비교는 시나리오 6개 × seed 10, ablation은 seed 20으로 돌린다. 기본 jitter는 0.8 ms다.

## 5. 검증

| 확인 | 방법 | 결과 |
|---|---|---|
| simulator 본체 | [test_engine.py](../../simulation/engine/test_engine.py) 1부: 1트랙 적재·hit 시간, 동시 도착 전송량, 비교군 정책 동작, 모아 보내기·offset 간격·트랙별 membrane potential·layer별 bit를 손계산과 비교 | 통과 |
| 환경 파일 | test_engine 2부: 환경 파일을 모두 읽고 첫 점을 한 번 돌린다 | 통과 |
| 결과 CSV | test_engine 3부: 쓰고 다시 읽은 값이 같다 | 통과 |
| engine = 옛 실험 스크립트 | 같은 조건을 engine과 옛 스크립트로 돌려 실행별 결과(응답 시간 배열 포함)를 비교했고 환경 파일 21개 결과도 옛 결과와 맞춰 봤다(2026-10-15, 옛 스크립트는 그 뒤 삭제) | offset 배정 없음의 난수 차이와 대역폭 하한의 조절값 차이를 빼면 같음 |

옛 결과와의 차이는 [P3.14 보고서](<../reports/P3.14 Research Report.md>)에 정리했다.

## 6. 추가할 것

측정값이 있어야 넣을 수 있다.

| 항목 | 이유 |
|---|---|
| jitter 분포 입력 | 지금은 균등분포 폭 하나다. M1·M3·M4 측정값을 그대로 넣는다 |
| Ethernet 지연 표본 | 지금은 PCIe 64 B 표본이다. M4 측정 뒤 바꾼다 |

## 7. 관련 문서

- [08_EVALUATION.md](08_EVALUATION.md): 지표와 실험 목록
- [P3.13 보고서](<../reports/P3.13 Research Report.md>) §1.1: 실험 조건
- [P3.21 보고서](<../reports/P3.21 Research Report.md>): 모아 보내기, 트랙별 membrane potential, offset 간격 비례 추가
