# B22: LACO

원문: `B22_LACO_ICCAD2024.pdf`
Zhanhong Tan, Zijian Zhu, Mengdi Wu, Kaisheng Ma(Tsinghua University 등), "LACO: A Latency-Constraint Offline Neural Network Scheduler towards Reliable Self-Driving Perception", ICCAD 2024, 9쪽, DOI 10.1145/3676536.3676692
읽은 범위: 원문 전체(9쪽)

## 한 줄 요약

주기가 다른 camera·LiDAR가 query를 내고 query 하나가 DNN 여러 개를 부르는 자율주행 인지 workload(M2-stream)를 다룬다. 도착 시각과 deadline을 미리 안다고 보고 many-core accelerator의 core 배정과 시작 시각을 SAT로 offline에서 정했다. 8×8 accelerator simulation에서 latency-constraint throughput이 비교 scheduler 5개보다 기하평균 1.2–2.4배 높았다.

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | 센서마다 주기가 달라(camera 30·60 Hz, LiDAR 15 Hz) 모든 모델을 한꺼번에 부를 수 없다. Task마다 도착 뒤 deadline 안에 끝나야 한다. 목표는 deadline을 모두 지키면서 붙일 수 있는 camera 수 N_C와 LiDAR 수 N_L의 최댓값이다(§2.1, §3.1) |
| 방법 1 | Mapping brick 생성: 모델마다 core cluster(크기·위치) 후보를 모두 만들고 layer별 mapper(Timeloop·NN-Baton 기반)와 해석적 NoC simulator로 실행 시간을 구한다(§3.2.1, Fig. 3) |
| 방법 2 | SAT 풀이: 시작 시각 변수 st(s, t)(주기 안의 kT + t에 시작)와 core 배정 변수 ac(s, a)를 둔다. 도착 뒤 시작, deadline 전 종료, 의존 순서, 같은 시각 같은 core 금지를 CNF 절로 쓴다. 주어진 N_C·N_L에서 가능한 일정이 있는지 MapleSAT으로 확인하고 task를 늘려 가며 최댓값을 찾는다(§3.2.2, §3.3, Table 1·2, 식 1–3) |
| 방법 3 | deadline은 두 가지다. Tight는 camera 추론이 다음 query 전에 끝나야 한다. Loose는 LiDAR 주기에 맞춘 fusion frame의 공통 deadline이다(§2.1, Fig. 4, §4.1.1) |
| 가정·조건 | 도착 간격이 일정해 도착 시각을 미리 안다(§1, §2.1). Apollo 5.0의 camera 모델 6개와 LiDAR 모델 1개를 쓰고 신호등 모델 4개는 task 하나로 합친다. NVDLA 기반 many-core 4×4·6×6·8×8·12×12(16–144 TOPS). Off-chip 메모리 bandwidth는 병목이 되지 않게 골랐다(§4.1.2). 전처리·후처리 시간은 deadline에 반영하는 고정 값으로 본다(§4.1.1) |

## 결론

- 8×8(64 TOPS)에서 66 ms 주기마다 완료한 MAC이 1.76–1.85 TMAC으로 일정했다. 기하평균 개선은 FCFS 대비 1.5배, PREMA 1.9배, Exclusive 1.6배, MAGMA 2.4배, Planaria 1.2배다(Fig. 8, §4.2)
- LiDAR 1–4대와 함께 30 Hz camera 9–7대, 60 Hz camera 4–3대까지 deadline을 지켰다. 다음으로 좋은 Planaria는 30 Hz camera 8–5대였다(Table 5·6)
- Accelerator 크기 4×4–12×12에서 FCFS 대비 1.2–1.5배였다(Fig. 10, Table 8)
- 평가 방식: simulation(layer별 mapper와 해석적 NoC simulator). 실측은 없다. SAT 풀이 시간과 시간 축을 나눈 간격은 원문에 없다

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| 주기 입력이 여러 모델을 부르고 추론마다 deadline이 있다 | LACO는 도착 시각을 정확히 안다고 보고 모든 task의 시작 시각과 core를 offline에서 정한다. 이 연구의 추론 요청은 Host 처리 지연만큼 늦게 도착하고 그 지연이 흔들린다 | [구조] 도착 시각을 미리 알 필요가 없다. Grouping과 PNU-Count가 실행 중 queue와 지연 분포를 보고 batch와 weight 교체를 정한다 |
| 도착 시각이 주기로 정해진다는 점을 이용한다 | LACO는 센서 도착 시각을 주어진 값으로 받고 바꾸지 않는다. Batch와 weight 재사용도 다루지 않는다. 이 연구는 Host가 모델마다 offset을 정해 같은 모델 추론 요청이 함께 생기게 한다 | [구조] 같은 모델 추론 요청이 함께 생겨 weight 적재 한 번으로 batch를 처리한다 |
| | LACO는 core 공간 분할로 throughput을 얻고 off-chip bandwidth는 병목이 아니게 두었다. 이 연구는 weight 4.97 MiB가 BRAM보다 커서 DDR3 weight 적재가 병목이다 | [구조] weight가 on-chip에 다 들어가지 않는 경우를 다룬다 |
| | LACO는 정해진 도착과 simulator 실행 시간 아래에서 모든 task가 deadline을 지키는 일정만 받는다 | 없음. 이 연구는 32 ms hard deadline 보장을 주장하지 않는다 |

## 인용할 때

- 이 논문이 먼저 한 것: 주기가 다른 여러 센서의 multi-DNN 추론을 도착 시각을 안다는 가정으로 offline SAT scheduling하는 것, core 공간 배정과 시작 시각을 함께 정해 latency-constraint throughput을 높이는 것. 주기 도착을 미리 알고 offline에서 일정을 짜는 것 자체는 신규성으로 주장하지 않는다
- 근거 위치: M2-stream 정의 §1·§2.1(Fig. 2·4), 제약과 목적 §3.1(식 1–2), SAT 변환 §3.2–3.3(Table 1–3, Fig. 6), 실험 조건 §4.1(Fig. 7, Table 4), 결과 §4.2–4.3(Fig. 8–10, Table 5–8)
- 주의: 원문의 task는 sample 하나로 모델 하나를 추론하는 것이다(§1 각주 2). Query는 센서 하나가 한 번에 낸 입력이다. Latency와 throughput은 원문 지표 이름이고 throughput은 완료한 task의 MAC 합이다
- 주의: 센서 도착 시각(위상)을 고르는 기법은 없다. Asynchronism은 주기가 달라 모든 모델을 한꺼번에 부를 수 없다는 성질로만 적었다(§2.1). Jitter와 weight 적재는 모형에 없다
- 주의: 비교 scheduler(FCFS, PREMA, Exclusive, MAGMA, Planaria)는 저자가 M2-stream에 맞게 옮긴 것이다. PREMA·Planaria에는 deadline이 가까운 task에 높은 priority를 주었다(§4.1.3)
- 비교군: simulation 비교군에 없다
