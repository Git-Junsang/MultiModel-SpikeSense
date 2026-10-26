# B18: RT-Swap

원문: `B18_RTSwap_RTAS2024.pdf`
Woosung Kang, Jinkyu Lee, Youngmoon Lee, Sangeun Oh, Kilho Lee, Hoon Sung Chwa, RTAS 2024, pp. 373–385, DOI 10.1109/RTAS61025.2024.00037
읽은 범위: 원문 전체

## 한 줄 요약

Swap-in·swap-out을 DNN 실행과 함께 EDF로 schedule하고 task별 swap volume을 schedulability 분석으로 정해 GPU 메모리보다 큰 다중 DNN task set을 deadline 안에 돌렸다. 분석으로 센 schedulable task set이 비교 방식보다 72–383% 많았다.

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | 주기 DNN task들의 메모리 합이 GPU 메모리보다 클 때, swap 비용을 넣고도 deadline을 지켜야 한다 |
| 방법 | 연산 queue와 swap queue를 모두 EDF로 돌린다. GPU 메모리가 모자라면 GPU에 있는 task 중 다음 job release가 가장 늦은 task부터 swap-out한다(§V-C) |
| 방법 | 가장 급한 job이 swap-in 없이 실행되는 동안 swap-in이 필요한 job 중 가장 급한 job의 swap-in(필요하면 그 앞 swap-out까지)을 겹친다. Swap-in과 그 실행 사이에는 선점을 막아 job마다 swap-in과 swap-out이 많아야 한 번씩이다(§V-C, Property 1, Fig. 5(b)) |
| 방법 | task별 최대 swap volume은 Theorem 1의 schedulability 조건을 지키면서 합이 가장 작도록 offline에 정한다(§V-D). Task 단위로 virtual address를 예약하고 같은 크기 chunk로 swap해 단편화를 줄인다(§IV) |
| 가정·조건 | 주기 task model. Task마다 DNN 모델 1개, job 하나에 추론 요청 하나, 상대 deadline = 주기, 비선점 EDF. GPU 1개(RTX3090 24 GB), 모델 4종 × 해상도 3개 |

## 결론

- Eq. (3)으로 센 simulation에서 schedulable task set이 MIN, MO-VMM, Pageable, Base보다 각각 72%, 139%, 221%, 383% 많다. Task가 12개이고 메모리가 GPU보다 평균 23.1 GB(96.2%) 많아도 schedulable한 task set이 있다(§VII-B, Fig. 7(a))
- RTX3090 실측(task 6개, footprint 합 25.6 GB): Base(UM on-demand paging, LRU)는 모든 task가 deadline을 놓쳤고 최대 관측 response time이 4,438 ms였다. RT-Swap은 모든 task를 schedulable하게 했고 최대 관측 response time을 평균 14배 줄였다(§VII-C, Fig. 9)
- 300 MB를 chunk 64 MB로 옮기면 swap-out 26.2 ms, swap-in 28.3 ms다. Pageable은 192.6 ms, 93.9 ms다(§IV-A, Fig. 4(a))
- 평가 방식: 실측(RTX3090, PCIe 3.0, Darknet)과 schedulability simulation(점마다 task set 100개)

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| 다음 사용이 가장 늦은 대상을 먼저 내보낸다 | RT-Swap은 다음 job release 시각을 그대로 쓴다. 이 연구에서는 실제 도착이 nominal frame 끝 시각보다 Host 처리 지연(모델 그룹 지연, 추론 요청별 지연)과 링크 지연만큼 늦다 | [실험] 같은 원리의 offset-only보다 PNU-Count의 DDR3 traffic이 적다. J = 0.8 / 1.6 / 3.2 ms에서 6.63 / 13.08 / 40.11 대 6.38 / 6.56 / 12.37 KiB/추론 |
| 연산하는 동안 다음 적재를 한다 | RT-Swap은 task마다 정한 swap volume만큼 일부만 옮긴다. Job 하나가 추론 요청 하나이고 묶음 처리는 없다 | [구조] Model-Grouped Offset Assignment로 같은 모델 추론 요청이 함께 생기고 Grouping이 이를 batch로 묶어 weight 적재 한 번으로 처리한다 |
| deadline이 있는 다중 모델 추론 | RT-Swap은 Theorem 1로 deadline 보장을 분석한다 | 없음. 이 연구는 32 ms hard deadline 보장을 주장하지 않는다(09 §3) |

## 인용할 때

- RT-Swap이 먼저 했다: 다음 job release가 가장 늦은 task부터 내보내는 교체 순서, 실행과 swap 겹치기. 다음 사용 시점 교체 원리와 prefetch 자체는 신규성으로 주장하지 않는다(09 §3)
- 근거 위치: 교체 순서 §V-C(379쪽 오른쪽 단, "latest future job release time first"), 겹치기 §V-C "Addressing G2"와 Fig. 5(b), task model §V-A, 보장 분석 §V-D Theorem 1·Lemma 1
- 주의: 초록의 "at least 72%"는 RT-Swap 변형 MIN(chunk 2 MB) 대비이고 실측이 아니라 Eq. (3)으로 판정한 값이다(§VII-A·B). Swap-out은 task마다 정한 최대 swap volume 안에서만 하므로 모델 전체를 내보내는 우리 교체와 단위가 다르다
- 비교군: 지금 cache 비교의 offset-only가 같은 원리다(nominal offset으로 다음 사용을 본다). P3.11 §3.2에서는 F.다음사용(RT-Swap Method)으로 옮겼다
- 우리 수치는 Xeon에서 잰 모델 그룹 지연을 넣은 simulation 값이다(entry 4). PNU는 j(i, k) 분포를 정확히 안다. 보드 측정은 없다
