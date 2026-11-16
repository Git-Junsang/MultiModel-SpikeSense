# C31: SPET

원문: `C31_SPET_DAC2023.pdf`
Changhun Han, Hoon Sung Chwa, Kilho Lee, Sangeun Oh, DAC 2023, 6쪽, DOI 10.1109/DAC56929.2023.10247661
읽은 범위: 원문 전체

## 한 줄 요약

Edge TPU의 on-chip SRAM(8 MB)을 task마다 겹치지 않는 구간으로 나누고 모델을 segment로 잘라 선점 지점을 만든 뒤 task별 SRAM 크기와 segment 수를 response time 분석 조건 아래 MIP로 정했다. Synthetic task set simulation에서 schedulable task set이 기본 Edge TPU보다 79% 많았다.

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | Edge TPU compiler는 deadline과 상관없이 자주 쓰는 layer의 parameter에 SRAM을 준다(B1). EfficientNet-S는 SRAM이 없으면 최대 할당보다 5.2배 느리다. 실행은 비선점 FIFO여서 task 3개의 실행 지연이 0.03–395.75 ms로 퍼진다(B2)(§I, §II-B, Fig. 1) |
| 방법 | Flexible SRAM allocator: co-compilation에 dummy 모델을 끼워 task τ_i에 크기 s*_i, 위치 f_i의 SRAM 구간을 겹치지 않게 준다. Binary의 caching token을 같게 고쳐 모델을 바꿀 때 SRAM 전체를 비우고 다시 올리는 일을 막는다. Compiler는 고치지 않는다(§III-B, Fig. 4) |
| 방법 | DNN model partitioner: 모델을 g*_i개 segment로 나눠 경계를 선점 지점으로 쓴다. 경계는 평균 segment 길이의 배수 ±δ 안에서 upload·download copy 비용이 가장 작은 layer다(§III-B, Fig. 5) |
| 방법 | System-wide scheduler(daemon, priority queue)가 task 단위 고정 우선순위로 segment 경계에서 선점한다. WCRT 식 (1)–(3)을 쓰고 SRAM 합 ≤ M, w_i ≤ T_i를 제약으로 task마다 SRAM 크기와 segment 수를 Gurobi MIP로 고른다(§III-B, §IV, 식 (4)) |
| 가정·조건 | Sporadic task model(task 하나가 DNN 모델 하나, job 하나가 추론 하나, deadline = T_i). SRAM 할당 단위 70 KB. SRAM 몫은 offline에 정하고 실행 중에 바꾸지 않는다. SRAM에 두지 못한 parameter는 추론마다 PCI로 올린다. Google Coral Dev board, TensorFlow Lite, DNN 7개(§II-A, §IV-A, §V) |

## 결론

- Synthetic task set 8,500개(task 8개, image classification 모델 5개 중 무작위, WCET는 Coral에서 profile, DM 우선순위): SPET이 찾은 schedulable task set이 Base-Seg2, Base-Seg6, DPSA, Base-Seg1보다 각각 34%, 42%, 69%, 79% 많다. 차이는 utilization이 클수록 커진다(§V, Fig. 6(a))
- 구성요소: SPET w/o MP(SRAM 할당만)는 DPSA, Base-Seg1보다 16%, 23% 좋다. SPET w/o SA(분할만)는 Base-Seg6, Base-Seg2, Base-Seg1보다 13%, 7%, 41% 좋다. U = 0.7에서 task가 10개보다 적으면 분할이, 많으면 SRAM 할당이 더 효과가 크다(§V, Fig. 6)
- 긴급 제동 case study(PiCar-V, 라즈베리파이 3 B+, Edge TPU USB accelerator, task 3개, 10회): 최대 response time이 Base τ1 500 ms, τ2 399 ms(deadline miss)이고 SPET 239 ms, 317 ms다. 평균 정지 거리는 1.1 m에서 0.5 m, 최대는 1.8 m에서 0.7 m로 줄었다(§V, Fig. 7)
- 평가 방식: synthetic task set simulation(판정 방법은 원문에 따로 없음)과 Edge TPU 실측 case study

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| on-chip 메모리에 모델 parameter를 두어 off-chip 읽기를 줄인다 | SPET은 task마다 SRAM 몫을 compile 때 고정하고 실행 중에 바꾸지 않는다. 몫 밖 parameter는 추론마다 다시 올린다. 이 연구의 PNU Cache는 entry 4개를 모델 40개가 시간을 나눠 쓰고 PNU-Count가 실행 중에 내보낼 모델을 고른다 | [구조] 추론 요청 도착에 따라 entry에 둘 모델을 바꾼다. 같은 모델 추론 요청이 처리되는 동안 그 모델 전체가 entry에 있고 다시 읽지 않는다. SPET의 몫은 도착 패턴을 따라 바뀌지 않는다 |
| 추론을 비선점 단위로 실행한다 | SPET은 job 하나가 추론 하나이고 segment 경계에서 선점한다. 이 연구의 Grouping은 기다리지 않고 선점하지 않으며 같은 모델 추론 요청을 batch로 묶는다 | [구조] batch 하나가 weight 적재 한 번을 나눠 쓴다 |
| deadline이 있는 다중 모델 추론 | SPET은 WCRT 분석(Lemma 1)과 MIP로 schedulability를 보장한다 | 없음. 이 연구는 32 ms hard deadline 보장을 주장하지 않는다(09 §3) |

## 인용할 때

- SPET이 먼저 했다: Edge TPU에서 deadline을 보고 task별 SRAM 몫을 정적으로 나누기, 모델 segment 분할로 선점 지점 만들기, 둘을 WCRT 조건 아래 MIP로 함께 정하기. Off-chip weight와 on-chip cache, 부분 상주 자체는 신규성으로 주장하지 않는다(09 §3)
- 근거 위치: 문제 §II-B·Fig. 1·2, allocator §III-B·Fig. 4, partitioner §III-B·Fig. 5, scheduler §III-B, task model §IV-A, WCRT 식 (1)–(3)·Lemma 1, MIP 식 (4), 결과 §V·Fig. 6·7
- 주의: 초록의 79%는 Base-Seg1(기본 Edge TPU) 대비 synthetic simulation 값이다. 보드 실측은 task 3개 case study뿐이다
- 주의: SRAM 몫은 MIP가 정한 뒤 바뀌지 않고 내보낼 모델을 고르는 교체 정책이 없다. PNU Cache, LRU, offset-only 비교의 근거로 쓰지 않는다
- B18·C14·C29와 이어서: Hoon Sung Chwa가 RT-Swap, ZeroSwap, RT-MDM과 같고 Kilho Lee, Sangeun Oh가 RT-Swap과 같다. RT-MDM(C29)은 SPET을 가장 가까운 연구로 들었다
- 비교군: 지금 비교군에 옮긴 것이 없다
