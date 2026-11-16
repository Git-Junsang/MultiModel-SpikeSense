# D08: AnRAD

원문: `D08_AnRAD_TNNLS2018.pdf`
Qiuwen Chen, Ryan Luley, Qing Wu, Morgan Bishop, Richard W. Linderman, Qinru Qiu, "AnRAD: A Neuromorphic Anomaly Detection Framework for Massive Concurrent Data Streams", IEEE TNNLS 29(5), 2018, pp. 1622–1636, DOI 10.1109/TNNLS.2017.2676110
읽은 범위: 원문 전체(참고문헌 제외)

## 한 줄 요약

확률 추론망(cogent confabulation)으로 비지도 이상 탐지를 하고 GPU와 Xeon Phi에서 병렬로 돌렸다. 전체 망 구조는 하나로 두고 지역(zone)마다 knowledge base를 따로 학습해 차량 stream이 자기 zone의 것을 쓰게 했다. 장치 하나로 차량 최대 16,000대를 실시간으로 검사했다(초록, §VI-H).

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | 라벨 없는 데이터로 끊임없이 들어오는 stream을 실시간 학습·탐지해야 하고 상황(context)마다 정상 분포가 다르다(§I) |
| 방법 | 모델: 특징을 lexicon(node), 특징 사이 조건부 확률을 knowledge link로 둔 2층 추론망이다. 초기 데이터로 망 구조를 정하고(self-structuring), knowledge link는 stream을 받으며 episode 단위로 계속 갱신한다. DNN이 아니다(§III-A, §IV) |
| 방법 | 모델 공유: "multiple knowledge contexts share a global network structure, and train separate knowledge bases using their local data samples"(§IV). 차량 감시는 지역을 342 zone으로 나누고 zone마다 knowledge base를 둔다. Context selection module이 차량을 그 zone의 knowledge base에 잇는다(§VI-H) |
| 방법 | 병렬화: key lexicon 하나를 CUDA block 하나(최대 thread 192개)에 두고 sparse 행렬을 strip 단위로 읽어 atomic add로 누산한다. 여러 stream은 같은 시간 frame의 차량을 grid의 x축, 그 차량의 key lexicon을 y축에 두는 2차원 grid로 한꺼번에 처리한다(§VI-C·D·H, Fig. 10) |
| 가정·조건 | 데이터: 차량 궤적(1 s 주기, 342 zone), DARPA 1998 침입 탐지(300 ms frame), ADFA-LD system call(§V-A). 장치: Tesla C2075(6 GB), Xeon Phi 5100, Tesla K20c, Jetson TK1(§VI-F·G). 모든 zone의 knowledge base를 장치 메모리에 미리 올린다(§VI-D·H) |

## 결론

- 처리량: 무작위 100 zone에서 Tesla C2075는 차량 약 7,500–10,500대/s, Xeon Phi 5100은 약 11,000–16,000대/s다(Fig. 12). 차량 1대 판정은 0.2 ms 미만이다(초록). Zone 342개의 knowledge base는 모두 합쳐 약 3–4 GB라 장치 하나에 다 들어간다(Fig. 11)
- Stream 하나의 frame당 시간: 최적화한 GPU 0.0742–0.210 ms로 CPU thread 1개보다 442–1,663배 빠르다(Table VI). Active 전력은 K20c 86.3–102.4 W, Jetson TK1 2.5–3.5 W다(Table VII)
- 정확도: zone별 knowledge base가 네 zone을 합친 knowledge base 하나보다 같은 threshold에서 오탐률이 약 40% 낮다(§V-C, Fig. 2). DARPA에서 AUC가 비교군(LOF, CFA, RNN, SOM, HTM) 중 가장 높다(Table II)
- 평가 방식: CPU, GPU, Xeon Phi 실측. SNN 구현은 simulator에서만 돌렸다(§VII, 상관계수 0.925)

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| 구조는 같고 weight만 다른 모델을 상황마다 두고 같은 모델을 쓰는 stream끼리 weight를 함께 쓴다. 이 연구는 장비 ID마다 모델이 하나다(02 §1) | Chen 등은 knowledge base 342개(3–4 GB)를 모두 장치 메모리에 올려 둔다. 이 연구는 weight 4.97 MiB가 BRAM 약 1.6 MiB보다 커서 DDR3에서 entry 4개로 적재한다 | [구조] 모델 weight 합이 on-chip 메모리보다 커도 돌린다. PNU-Count가 entry에 둘 모델을 고른다 |
| 같은 시간 frame의 stream 여러 개를 한 번에 처리한다 | Chen 등은 frame마다 그 frame의 차량을 모두 한 grid로 처리하고 zone끼리 시각을 나누지 않는다. 실시간 기준은 입력 주기(1 s)뿐이다 | [구조] Offset Assignment가 같은 모델 추론 요청을 함께 생기게 하고 모델끼리 0.8 ms씩 벌린다. 32 ms deadline 안의 response time을 본다 |
| | Chen 등은 GPU·Xeon Phi 위의 확률 추론망이다. 이 연구는 FPGA 위의 SNN이다 | 없음. 이 연구는 stream 수를 늘리며 처리량을 재지 않았다 |

## 인용할 때

- Chen 등이 먼저 했다: 망 구조는 공유하고 context마다 knowledge base(weight)를 따로 둔 모델을 장치 하나에서 동시 stream 수천 개에 쓰는 이상 탐지(§IV, §VI-H). 같은 모델 stream끼리 weight를 함께 쓰는 것 자체는 신규성으로 주장하지 않는다([09_RELATED_WORK §3](../../design_references/09_RELATED_WORK.md#3-신규성-경계))
- 근거 위치: 구조 공유와 지역별 knowledge base §IV 첫 부분(1625쪽), 다중 stream 확장 §VI-H(1633쪽)와 Fig. 10–12, 지역별·단일 knowledge base 비교 §V-C와 Fig. 2, 단일 stream 시간 Table VI, 전력 Table VII
- 주의: "16,000"은 차량 수이고 원문은 차량 하나를 stream 하나로 센다. 그림의 처리량은 대/s이고 차량 데이터 주기가 1 s라 같은 값이 된다. 같은 grid 안에서 zone이 다른 차량을 섞는지, zone 순서로 묶는지는 원문에 없다
- 주의: 제목의 neuromorphic은 뇌를 본뜬 추론 방식이라는 뜻이다. 평가한 장치는 GPU와 Xeon Phi이고 SNN은 simulator 결과뿐이다. Xeon Phi 5100의 메모리를 §VI-F는 16 GB, §VI-H는 8 GB로 적었다
- 비교군: 옮기지 않았다
