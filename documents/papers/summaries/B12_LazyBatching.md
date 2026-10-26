# B12: LazyBatching

원문: `B12_LazyBatching_HPCA2021.pdf`
Yujeong Choi, Yunseong Kim, Minsoo Rhu, HPCA 2021, DOI 10.1109/HPCA51647.2021.00049(서지는 references/INDEX.md 기준)
읽은 범위: 원문 전체(arXiv:2010.13103v1 저자 preprint)

## 한 줄 요약

실행 중인 batch를 layer 경계에서 멈추고 나중에 온 추론 요청이 같은 layer까지 따라오면 합쳐 함께 실행한다. Graph 단위 batching보다 평균 response time 15×, throughput 1.5×, SLA satisfaction 5.5× 좋아졌다(초록).

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | graph 단위 batching은 실행 중인 batch에 새 추론 요청을 넣지 못한다. 고정한 batching time-window와 최대 batch 크기는 부하가 바뀌면 맞지 않는다(§III-A, Fig. 4–5) |
| 방법 | layer(graph node) 단위로 scheduling한다. 합쳐도 SLA를 넘기지 않을 것 같으면 실행 중인 batch를 layer 경계에서 선점한다. 새 추론 요청이 같은 node에 이르면 batch를 합친다(§IV-A, Fig. 8). Batching time-window가 없다 |
| 방법 | BatchTable(software stack)이 sub-batch마다 다음 node를 적는다. 맨 위 두 entry의 node가 같아지면 합친다(§IV-B, Fig. 10) |
| 방법 | SLA까지 남은 시간을 `SLA target − (대기 시간 + 추론 요청별 단독 실행 시간의 합)`으로 보수적으로 예측한다(Eq. 1–2). Node 실행 시간은 profiling 표에서 읽는다. 출력 길이가 바뀌는 모델은 학습 데이터 출력 길이의 90%를 덮는 값을 쓴다(Algorithm 1, §IV-C) |
| 가정·조건 | cloud 추론 server. 기본 평가는 server에 모델 하나다(§VI-C). TPU식 NPU의 cycle-level simulation(128×128 systolic array, 700 MHz, on-chip SRAM activation 8 MB·weight 4 MB, 360 GB/s, Table I). 추론 요청은 Poisson 도착이고 주기 입력이 아니다(§V). SLA target은 100 ms로 둔다(§VI-A) |

## 결론

- 가장 좋은 graph batching 설정보다 latency가 ResNet 5.3×, GNMT 2.7×, Transformer 2.5× 낮고 throughput은 1.1×, 1.3×, 1.2× 높았다(Fig. 12–13, §VI-A). Transformer의 99-percentile latency는 54 대 123 ms였다(Fig. 14)
- 부하 1K req/sec에서 SLA target이 ResNet 20 ms, GNMT 40 ms, Transformer 60 ms 이상이면 SLA violation이 없었다(Fig. 15, §VI-B)
- 모델 4개를 함께 둔 server에서 graph batching보다 latency 2.4×, throughput 1.8× 좋았다. GPU 시제품에서는 latency가 1.4–56× 좋아졌다(§VI-C, Fig. 17)
- 평가 방식: NPU simulation(20회 평균), GPU 시제품 실측(NVIDIA Titan Xp, CUDA 10.1, cuDNN 7.0)

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| 같은 모델 추론 요청을 batch로 묶어 weight 공유를 하고 일부러 기다리지 않는다 | LazyBatching은 실행 중인 batch를 layer 경계에서 멈추고 나중 추론 요청과 합친다. Grouping은 선점하지 않고 batch를 끝까지 처리한다 | [구조] 선점과 layer별 진행 기록이 필요 없어 compute array는 batch를 끝까지 처리하면 된다 |
| | LazyBatching은 추론 요청 도착 시각을 바꾸지 않는다. 이 연구는 Host가 모델별 frame offset을 정해 같은 모델 추론 요청이 함께 도착하게 한다 | [구조] 같은 모델 추론 요청이 처음부터 함께 도착해 선점 없이도 batch가 생긴다 |
| | 기본 평가는 모델 하나이고 모델 교체에 따른 weight 전송을 따로 다루지 않는다. 이 연구는 모델 40개 weight 4.97 MiB가 BRAM보다 커서 weight 전송이 병목이다 | [구조] PNU-Count가 다음 사용 시각을 예측해 가장 늦게 쓸 모델을 내보낸다 |

## 인용할 때

- 이 논문이 먼저 한 것: 기다리지 않고 실행 중인 batch에 나중 추론 요청을 layer 단위로 합류시켜 batch를 키우는 것. SLA까지 남은 시간을 예측해 합류 여부를 정하는 것. 같은 모델의 묶음 처리·weight 공유 자체는 신규성으로 주장하지 않는다([09_RELATED_WORK §3](../../design_references/09_RELATED_WORK.md#3-신규성-경계))
- 근거 위치: graph batching의 한계 §III-A(Fig. 4–5), 선점·합류 §IV-A(Fig. 8), BatchTable §IV-B(Fig. 9–10), 남은 시간 예측 §IV-C(Eq. 1–2, Algorithm 1), simulation 조건 §V(Table I–II), 결과 §VI-A–C(Fig. 12–17), overhead §VI-D
- 주의: 초록의 15×·1.5×·5.5×는 graph batching 대비다. 가장 좋은 graph batching 설정과 비교한 latency는 2.5–5.3×다(§VI-A). 비교 대상을 나눠 쓴다
- 주의: 기다려 묶는 방법이 아니다(§IV-A). 기다려 묶기의 선행연구는 DeepRT와 Symphony다([P3.11 보고서](<../../reports/P3.11 Research Report.md>) §3.1)
- 옮긴 방식: simulation 비교군에 없다. 선점을 빼면 Grouping과 같아 P3.11에서 뺐다
