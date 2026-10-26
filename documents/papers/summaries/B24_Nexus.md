# B24: Nexus

원문: `B24_Nexus_SOSP2019.pdf`
Haichen Shen, Lequn Chen, Yuchen Jin, Liangyu Zhao, Bingyu Kong, Matthai Philipose, Arvind Krishnamurthy, Ravi Sundaram, SOSP 2019, pp. 322–337, DOI 10.1145/3341301.3359658
읽은 범위: 원문 전체(부록 A 포함)

## 한 줄 요약

Batch 크기에 따라 비용이 바뀌는 점을 넣은 bin packing(squishy bin packing)으로 GPU마다 맡을 모델과 batch 크기를 정하고 GPU 하나에서는 모델별 batch를 duty cycle 안에서 round-robin으로 돌렸다. 16 GPU에서 추론 요청 99%가 latency SLO 안에 드는 최대 throughput이 TF Serving·Clipper의 1.8–12.7배였다(초록, §7.3).

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | GPU cluster에서 여러 DNN의 추론 요청을 batch로 묶어 GPU 사용률을 높이면서 latency SLO를 지켜야 한다. 같은 모델 추론 요청을 많이 모을수록 하나당 비용이 줄어 크기가 고정된 물건을 담는 보통 bin packing과 다르다(§4.1) |
| 방법 | session(모델과 latency SLO의 쌍)마다 SLO를 지키는 가장 큰 batch를 고른다. GPU 하나를 다 채우지 못하는 session은 occupancy가 큰 순서로 best fit으로 합친다. 합칠 때는 짧은 duty cycle에 맞춰 batch를 줄인다. Batch 실행 시간의 합이 duty cycle 안에 들고 메모리가 남아야 합친다(§6.1, Algorithm 1, Fig. 7) |
| 방법 | GPU 하나는 맡은 session의 batch를 round-robin으로 돌고 한 바퀴를 duty cycle 안에 마친다(§4.1, §6.1, §6.3). Duty cycle d는 b개 입력을 모으는 시간 b/r이고 worst case latency는 d와 batch 실행 시간의 합이다(§6.1, Eq. 2) |
| 방법 | 모델 적재: global scheduler가 epoch(보통 30–60 s, 간격은 10 s 이상, 부하가 크게 바뀌면 새로 시작)마다 어느 backend에서 어떤 모델을 어떤 batch 크기로 돌릴지 정한다. Backend는 schedule을 받으면 그 모델들을 GPU 메모리에 올린다(§5). 적재에 수백 ms–수 초가 걸려 미리 올려 두고 다시 쓴다(§2.2). Epoch 사이에는 모델 이동이 적도록 고치고 과부하인 backend에서는 가장 싼 session부터 빼서 다시 bin packing한다(§6.1) |
| 방법 | prefix batching: 모델을 등록할 때 공통 sub-tree를 찾아 두고 실행 때 마지막 layer만 다른 모델들을 prefix까지 한 batch로 돌린 뒤 suffix를 차례로 돌린다. Early drop: queue를 batch 크기 window로 훑어 window 전체를 실행할 시간이 남은 첫 추론 요청 앞의 추론 요청을 버린다(§6.3) |
| 가정·조건 | GPU 16–100대 cluster, application 7개, 모델 12개(§1, §7). 추론 요청마다 latency SLO가 있고 SLO 안에 못 끝낼 추론 요청은 버려도 된다고 본다(§5). Frame 도착 간격은 따로 적지 않으면 uniform으로 뽑는다. 100 GPU 실험은 Poisson이다(§7.1, §7.4) |

## 결론

- 16 GPU 단일 application: game 분석(SLO 50 ms)에서 throughput이 Clipper의 9.4배, TF Serving의 12.7배였다. Traffic 분석(SLO 400 ms)에서는 1.8–4.4배였다(§1, §7.3, Fig. 10–12)
- 여러 application 동시 배치: GTX 1080Ti 16대 uniform 부하에서 평균 11.7 GPU를 써 이론 하한 9.8 GPU 대비 GPU 효율이 84%였다. K80 100대 Poisson 부하에서 SLO를 넘긴 추론 요청은 평균 0.27%였다(§7.4, Fig. 13)
- GPU 하나에 Inception 사본 여러 개(SLO 100 ms)를 돌리면 throughput이 TF Serving의 1.4–2.1배, Clipper의 1.9–9.8배였다(§7.5, Fig. 14a). Prefix batching은 throughput을 최대 110% 높였다(Fig. 15a)
- 평가 방식: GPU cluster 실측(Docker Swarm 배포, §7). Lazy drop과 early drop 비교만 simulation이다(§4.3, §6.3, Fig. 5·9)

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| 한 주기를 모델별 시간 칸으로 나눠 같은 모델 추론 요청을 함께 처리한다. Nexus는 duty cycle 안에서 session마다 batch 하나를 round-robin으로 돌린다(§4.1, §6.1). 이 연구는 32 ms 주기 안에서 모델 m의 추론 요청이 `O_m = m × 0.8 ms`에 생긴다 | Nexus의 칸은 GPU 실행 쪽에 있고 도착 시각은 바꾸지 않는다. 추론 요청은 자기 session 차례까지 queue에서 기다린다. 그래서 모으는 시간 d가 worst case latency에 더해진다(Eq. 2). 이 연구는 Host가 같은 모델 트랙의 frame 생성 시각을 맞춰 같은 모델 추론 요청이 함께 도착하고 Grouping은 기다리지 않는다 | [구조] batch를 모으려고 기다리는 시간이 response time에 더해지지 않는다 |
| | Nexus는 duty cycle을 도착률과 SLO로 정하고(d = b/r, 합칠 때는 짧은 쪽) 모델별 칸 길이는 그 batch의 실행 시간이다(§6.1). GPU마다 bin packing으로 고른 몇 개 session만 돌고 epoch마다 다시 정한다(§5). 이 연구는 주기 32 ms와 `O_m = m × 0.8 ms`가 고정이고 모델 40개가 FPGA 하나를 나눠 쓴다 | 없음. 이 연구의 offset은 부하에 따라 다시 정하지 않는다 |
| 모델을 가속기 메모리에 올려 두고 여러 추론 요청에 다시 쓴다(§2.2) | Nexus는 GPU 메모리에 들어가는 session만 한 GPU에 합치고 배치는 epoch마다 바꾼다(§5, §6.1). Epoch 안에서 모델을 내보내고 다시 올리는 교체 정책은 없다. 이 연구는 모델 40개 weight 4.97 MiB가 BRAM보다 커서 weight 전송이 병목이다 | [구조] PNU-Count가 다음 사용이 가장 늦을 모델을 내보내 weight 합이 on-chip 메모리보다 커도 FPGA 하나에서 모델 40개를 돌린다 |

## 인용할 때

- Nexus가 먼저 했다: batch 크기에 따라 비용이 바뀌는 squishy bin packing, GPU 하나에서 여러 모델의 batch를 duty cycle 안에 round-robin으로 돌리는 시간 나누기, prefix batching, early drop. 같은 모델의 묶음 처리 자체와 기다려 묶기 자체는 신규성으로 주장하지 않는다([09_RELATED_WORK §3](../../design_references/09_RELATED_WORK.md#3-신규성-경계))
- 근거 위치: duty cycle과 round-robin §4.1(Fig. 2b)·§6.1(Algorithm 1, Eq. 2, Fig. 7)·§6.3 "GPU Multiplexing", 모델 적재 §2.2·§5(Fig. 6), epoch 사이 갱신 §6.1 끝 문단, prefix batching·early drop §6.3(Fig. 9, Fig. 15), 도착 분포 §7.1·§7.4, NP-hard 증명 부록 A
- 주의: 추론 요청 도착 시각을 정하거나 옮기는 장치는 원문에 없다. Frame을 고르는 일은 application code가 하고 Nexus는 DNN 분석 단계를 맡는다(§2). 부하가 몰리면 추론 요청을 버리고(§5, §6.3) epoch마다 GPU를 다시 배정한다(§7.4)
- 주의: duty cycle의 모델별 칸은 Model-Grouped Offset Assignment와 비슷하게 읽힌다. Nexus의 칸은 GPU 실행 시간이고 도착은 그대로다. Runtime은 정한 batch 크기가 찰 때까지 기다리지 않지만(§7.5) 차례가 오기 전까지는 queue에서 모은다(Eq. 2)
- 주의: 1.8–12.7배는 Nexus 저자가 TF Serving·Clipper에 batch를 고려하지 않는 scheduler를 붙여 잰 값이다(§7.2). Game 비교에서 두 baseline은 ResNet만 돌렸다(§7.3.1). Simulation 비교군에 없다
