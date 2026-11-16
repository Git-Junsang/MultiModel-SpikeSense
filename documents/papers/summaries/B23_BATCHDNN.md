# B23: BATCH-DNN

원문: `B23_BATCHDNN_EuroPar2025.pdf`
Piyumal Ranawaka, Per Stenstrom(Chalmers University of Technology·University of Gothenburg), "BATCH-DNN: Adaptive and Dynamic Batching for Multi-DNN Accelerators", Euro-Par 2025, LNCS 15901, pp. 103–117(2026), DOI 10.1007/978-3-031-99857-7_8
읽은 범위: 원문 전체(15쪽)

## 한 줄 요약

여러 DNN이 on-chip 메모리를 함께 쓰는 multi-DNN accelerator에서 batch 크기를 layer마다 남은 on-chip 메모리에 맞춰 바꾼다. 메모리가 모자라면 batch를 둘로 나눠 일부만 진행하고 메모리가 풀리면 다시 합친다. Cycle 단위 simulation에서 throughput이 최대 26.97%, 기하평균 5.8% 올랐다. 추론이 언제 도착해 batch가 되는지는 다루지 않는다.

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | 기존 multi-DNN 묶음 처리는 모든 layer에 같은 batch 크기를 compile 때 정한다. Layer 하나의 on-chip 메모리 요구는 N × F + W(N batch 크기, F feature map, W weight)다. 다른 workload가 메모리를 차지하고 있으면 그 layer 연산이 멈춘다(§1, §2.2, Fig. 2) |
| 방법 1 | Adaptive cascaded sub-batching: compute task가 끝날 때마다 남은 메모리 ÷ OFMAP footprint로 이번 layer의 최대 batch 크기를 구한다. 앞 layer의 batch 크기를 넘지 않는다. 앞 layer 크기를 유지하지 못하면 batch를 둘로 나눠 앞쪽만 진행하고 남은 sub-batch의 layer와 크기를 stack에 적는다. 크기가 0이면 멈춘다(§3.3, Fig. 5) |
| 방법 2 | Adaptive sub-batch merging: 가장 최근에 멈춘 sub-batch를 stack에서 꺼낸다. 사이 layer들이 남은 메모리에 들어가면 그 sub-batch를 현재 layer까지 따라오게 한 뒤 합친다. Sub-batch는 LIFO로 다룬다(§3.1, §3.3, Fig. 3) |
| 방법 3 | Weight는 off-chip에 두고 실행 전에 on-chip으로 올린다(§2.1). Batch 안 추론이 모두 끝나야 그 weight 메모리를 비운다(§3.3). Footprint는 offline profiling으로 구해 scheduling table에 넣고 stack과 scheduler는 hardware로 둔다(AI-MT 확장, §3.2, Fig. 4) |
| 가정·조건 | deadline은 고려하지 않는다(§2.2). Batch 크기는 benchmark마다 on-chip 메모리에 맞춘 고정 값이다(Table 1b). Batch는 queue에서 FCFS로 실행 slot에 들어간다(§2.2). Systolic array 256개(각 32×32 PE), on-chip 44 MB, HBM2 256 GB/s, 16 bit, 1 GHz(Table 1a, 원문 단위). Benchmark 10개 중 4개를 고른 조합 450개(§4) |

## 결론

- Throughput(단위 시간당 MAC) 향상은 조합 450개에서 최대 26.97%, 평균 7.66%, 기하평균 5.8%였다. 179개 조합은 0–5%였다(Fig. 6(A), §5)
- Throughput이 20% 넘게 오른 14개 조합에서 compute 사용률 향상은 48.2–70.9%, 평균 60.4%였다. 같은 조합의 메모리 사용률 향상은 −2.3%에서 29.4%, 평균 3.8%였다(Fig. 6(B)(C))
- Compute·메모리 자원을 2·4·8배로 늘려도 사용률은 변하지 않았다(§5)
- 평가 방식: cycle 단위 simulation(BATCH-DNN Sim, output stationary systolic array 모형). 실측과 합성 결과는 없다

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| 같은 모델 추론 여러 개가 한 번 올린 weight를 함께 쓴다(§2.2) | BATCH-DNN은 batch가 이미 주어졌다고 보고 그 batch를 layer별로 나누고 합친다. 추론이 언제 생겨 batch가 되는지는 다루지 않는다. 이 연구는 Host가 같은 모델 추론 요청이 함께 생기게 하고 Grouping이 이미 도착한 것만 묶는다 | [구조] batch가 생기는 쪽을 다룬다. Model-Grouped Offset Assignment로 같은 모델 추론 요청의 생성 시각을 맞춘다 |
| Weight는 off-chip에 두고 쓸 때 on-chip으로 올린다(§2.1) | BATCH-DNN에는 모델 단위 교체 정책이 없다. 이 연구는 entry 4개에 모델 한 벌씩 두고 교체한다 | [구조] PNU-Count가 다음 사용이 가장 늦은 모델을 내보낸다 |
| on-chip 메모리를 weight와 추론별 데이터가 나눠 쓴다 | BATCH-DNN은 feature map 크기가 layer마다 달라 batch 크기를 실행 중 바꾼다. 이 연구의 추론별 데이터는 트랙의 membrane potential이고 entry 수는 고정이다 | 없음. Layer별 batch 크기 조절은 하지 않는다 |
| | BATCH-DNN은 deadline을 고려하지 않는다(§2.2) | [구조] 32 ms deadline 아래에서 response time과 DDR3 traffic을 함께 본다 |

## 인용할 때

- 이 논문이 먼저 한 것: layer별 on-chip 메모리 여유에 맞춰 batch를 나누고 다시 합치는 것, 그 stack을 hardware scheduler에 두는 것. 같은 모델 추론의 weight 공유는 이 논문도 기존 원리로 두고 고정 batch 크기의 선행 연구[2, 3, 18, 19]를 기준으로 삼았다(§2.2). 묶음 처리·weight 공유 자체는 신규성으로 주장하지 않는다(09 §3)
- 원문 확인: 초록만 보고 적은 "추론 요청 생성 시각을 맞추지 않는다"는 원문과 맞다. 전문에 추론 도착을 다루는 모형이 없고 batch 크기는 benchmark마다 정한 값이다(Table 1b). 서론은 cloud에서 workload 조합과 도착 시각을 미리 알 수 없다고만 적었다(§1)
- 근거 위치: 문제 §1·§2.2(Fig. 2), 기법 §3.1–3.3(Fig. 3–5), 실험 조건 §4(Table 1), 결과 §5(Fig. 6)
- 주의: 초록의 "compute 사용률 60% 향상"은 throughput이 20% 넘게 오른 14개 조합의 평균이다(§5). 초록의 "평균 6%"는 기하평균 5.8%이고 산술 평균은 7.66%다
- 주의: 저자는 이 기법이 메모리 접근량은 바꾸지 않고 연산 멈춤만 줄인다고 적었다(§5). DDR3 traffic처럼 off-chip으로 오간 byte 수를 잰 결과는 없다
- 비교군: simulation 비교군에 없다
