# C14: ZeroSwap

원문: `C14_ZeroSwap_RTAS2026.pdf`
Woosung Kang, Filippo Muzzini, Gianluca Brilli, Jong-Chan Kim, Jinkyu Lee, Hoon Sung Chwa, RTAS 2026, pp. 234–246, DOI 10.1109/RTAS68450.2026.00030
읽은 범위: 원문 전체

## 한 줄 요약

CPU와 GPU가 물리 메모리를 함께 쓰는 integrated GPU에서 SSD로 swap하는 실시간 다중 DNN framework다. Weight만 SSD에서 다시 읽고 swap-out을 없애며 읽기를 같은 job의 앞 segment 실행과 겹쳐서 schedulability 분석(식 (4))으로 센 schedulable task set이 RT-Swap(B18)보다 74.7% 많았다.

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | integrated GPU는 CPU 메모리로 swap해도 자리가 늘지 않아 SSD로 swap해야 하는데 할당·해제, 복사, SSD I/O 비용이 모두 swap 양에 따라 커져 deadline을 지키기 어렵다(§I, §III, Fig. 2) |
| 방법 | 무엇을 swap하나: weight만 swap-in한다. Weight는 바뀌지 않으므로 swap-out 때 저장하지 않는다. Activation과 workspace는 job이 끝나면 버리므로 옮기지 않는다(SASS, §IV-A, §V-B) |
| 방법 | 모든 task의 swap 영역을 같은 host-pinned 물리 메모리에 mapping한다. Mapping은 초기화 때 정하고 바꾸지 않아 실행 중 할당·해제와 CPU·GPU 사이 복사가 없다. 공유 영역 크기는 task별 sharing volume의 합이 아니라 최댓값이다(SPA, §IV-B, §V-A, 식 (3)) |
| 방법 | DNN을 앞·뒤 segment로 나누고 뒤 segment의 weight(x_i)를 앞 segment 실행 중에 읽는다. 뒤 segment는 끝 layer의 weight부터 채운다. Sharing volume은 메모리 조건(식 (3))과 schedulability 조건(식 (4))을 지키며 Σx_i가 가장 작도록 Gurobi로 offline에 정한다(SLO, §IV-C, §VI-B–D) |
| 방법 | 교체 순서: 내보낼 task를 다음 사용으로 고르는 규칙이 없다. 공유 영역에는 마지막으로 swap-in을 마친 task의 weight만 남고 job마다 x_i를 다시 읽는다(§V-B, §VI-B 식 (1)) |
| 가정·조건 | 주기 task model(task 하나가 DNN 모델 하나, job 하나가 추론 하나, D_i = T_i), job 단위 비선점 EDF, 한 번에 job 하나만 실행한다. Jetson Orin Nano(8 GB LPDDR5, DNN에 쓸 수 있는 메모리 약 7.5 GB), SK hynix P41 SSD(PCIe 3.0 x4), PyTorch, DNN 4종(§V-C, §VI-A, §VII-A) |

## 결론

- Schedulability simulation(task 4–11개, 점마다 task set 100개, 전체 utilization 0.3): schedulable task set이 Base, GPUpaging, Demand-Layering, RT-Swap보다 각각 111.1%, 101.7%, 66.8%, 74.7% 많다. RT-Swap은 task 7개, ZeroSwap은 9개까지 schedule했고 DNN 실행 시간은 평균 3.6% 늘었다(§VII-B, Fig. 10(a))
- 4-camera case study(YOLOv7 4개, 합 5.44 GB, 쓸 수 있는 메모리 5 GB): 가능한 가장 짧은 주기(앞뒤 camera·좌우 camera)가 RT-Swap 757·2,271 ms, ZeroSwap 203·609 ms다. Sampling rate가 3.8배다. 최대 관측 response time은 RT-Swap 1,385.9 ms, ZeroSwap 436.2 ms다(§VII-C, Table III, Fig. 11)
- τ1의 swap: RT-Swap은 192 MB를 swap-in에 79.1 ms, swap-out에 76.9 ms 들여 옮겼다. ZeroSwap은 54 MB만 28.1 ms에 읽었고 그중 58.3%(16.4 ms)를 YOLOv7 실행과 겹쳤다(§VII-C, Fig. 12)
- 평가 방식: 식 (4)로 판정한 schedulability와 Jetson Orin Nano 실측(case study). RT-Swap은 host-pinned 메모리와 SSD swap으로 바꿔 옮겼다(§VII-A)

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| weight는 바뀌지 않으므로 내보낼 때 쓰지 않고 원본(SSD, DDR3)에서 다시 읽는다 | ZeroSwap은 job마다 x_i를 다시 읽는다. 이 연구는 entry에 남은 모델을 다시 읽지 않고 entry가 모자랄 때 PNU-Count로 내보낼 모델을 고른다 | [구조] Grouping이 같은 모델 추론 요청을 batch로 묶어 weight 적재 한 번을 여러 추론 요청이 나눠 쓴다. ZeroSwap은 job 하나가 추론 하나다 |
| 연산하는 동안 다음 weight를 읽는다 | ZeroSwap은 같은 job의 앞 segment를 실행하는 동안 뒤 segment weight를 읽는다. 이 연구는 지금 batch를 연산하는 동안 다음 batch 모델 전체를 적재하고 layer로 나누지 않는다 | 없음. Prefetch 자체는 주장하지 않는다(09 §3) |
| 주기가 있는 다중 모델 추론 | ZeroSwap은 Theorem 1의 조건(식 (4))으로 schedulability를 판정한다 | 없음. 이 연구는 32 ms hard deadline 보장을 주장하지 않는다(09 §3) |

## 인용할 때

- ZeroSwap이 먼저 했다: integrated GPU의 SSD swap에서 weight만 읽고 swap-out을 없애기, task 사이 물리 메모리 공유, 같은 job 안에서 weight 읽기와 실행 겹치기, 겹침을 넣은 비선점 EDF schedulability 분석. 부분 상주와 prefetch 자체는 신규성으로 주장하지 않는다(09 §3)
- 근거 위치: 비용 분석 §III·Fig. 2, 설계 원리 §IV-A–C, SPA §V-A와 Fig. 7, SASS §V-B와 Fig. 8, scheduler §V-C, task model §VI-A, 실행 시간 식 (1), segment 경계 §VI-C, 공유량 식 (2)–(5) §VI-D, 결과 §VII-B Fig. 10과 §VII-C Table III·Fig. 11·12
- 주의: 초록의 최대 101.7%는 GPUpaging 대비다. Base 대비는 111.1%, RT-Swap 대비는 74.7%다. 이 비율은 실측이 아니라 식 (4)로 판정한 값이다(§VII-B)
- 주의: case study의 response time은 방식마다 schedulable한 가장 짧은 주기에서 쟀다. 같은 주기 비교가 아니다(§VII-C, Table III)
- B18과 이어서: 저자 셋(Woosung Kang, Jinkyu Lee, Hoon Sung Chwa)이 RT-Swap과 같다. RT-Swap은 다음 job release가 가장 늦은 task부터 내보냈지만 ZeroSwap에는 이 교체 순서가 없다
- 비교군: 원리가 같지 않으므로 offset-only(RT-Swap과 같은 원리) 비교를 ZeroSwap 비교로 쓰지 않는다. 지금 비교군에 옮긴 것이 없다
