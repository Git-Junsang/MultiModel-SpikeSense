# B38: Batch-MOT

원문: `B38_BatchMOT_TCAD2024.pdf`
Donghwa Kang, Seunghoon Lee, Cheol-Ho Hong, Jinkyu Lee, Hyeongboo Baek, "Batch-MOT: Batch-Enabled Real-Time Scheduling for Multiobject Tracking Tasks", IEEE TCAD, vol. 43, no. 11, pp. 3539–3550, 2024(EMSOFT 2024 발표, ESWEEK-TCAD 특집), DOI 10.1109/TCAD.2024.3443002
읽은 범위: 원문 전체(12쪽, 보충 자료 제외)

## 한 줄 요약

GPU 하나가 camera 여러 대의 주기 MOT task를 처리할 때 이미 release된 job을 실행 중에 batch로 묶고(NPFP^B), job이 하나뿐이면 다른 task의 다음 release를 기다렸다가 묶는다(NPFP^BI). 비선점 고정 priority의 schedulability 검사를 넓혀 batch와 기다림이 deadline을 깨지 않는 범위를 offline에서 정했다. 기다리지 않는 NPFP^B는 Grouping과, 기다려 묶는 NPFP^BI는 DeepRT Method와 원리가 같다.

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | Camera마다 MOT task가 주기 T_i로 job을 내고 deadline은 release + T_i다. 모든 job을 full-size(672×672)로 하나씩 처리하면 deadline을 못 지키고 축소(256×256)로 처리하면 정확도가 떨어진다(§I, §III) |
| 방법 1 | batch 실행은 full-size image 여러 장을 DNN 추론 한 번에 넣는다. Tesla V100·YOLOX에서 12장을 하나씩 처리하는 시간을 1로 두면 batch는 0.46, 축소 image를 하나씩 처리하면 0.74였다(Fig. 1). 이득은 GPU 호출 수가 줄어서 생긴다(§III) |
| 방법 2 | NPFP(비선점 고정 priority)의 schedulability 검사(Lemma 1)를 넓혀 NPADAPT를 만든다. Task마다 허용 편차 Δ_k를 binary search로 offline에서 구한다. 이 범위 안에서는 batch로 길어진 실행과 일부러 쉬는 시간이 생겨도 deadline이 지켜진다(§IV, Theorem 1) |
| 방법 3 | NPFP^B: job이 끝나거나 쉬는 중 release가 생길 때 release됐고 아직 끝나지 않은(active) job 가운데 priority 상위 x개를 batch로 묶는다. 다른 job의 deadline을 깨지 않는지 STOB(Algorithm 1)로 확인하고 가장 큰 x를 binary search로 찾는다. 기다리지 않는다(§V, Algorithm 2) |
| 방법 4 | NPFP^BI: active job이 하나뿐이면 다른 task의 다음 release를 기다렸다가 함께 batch로 실행한다. Task가 엄격히 주기적이라 다음 release 시각을 안다. Δ_k를 넘지 않는 release 시각 가운데 batch가 가장 큰 시각을 고른다(§VI, Algorithm 3·4) |
| 가정·조건 | CPU 여러 개와 GPU 하나. Detector는 batch 실행에 최적화돼 batch WCET가 개별 WCET 합 이하라고 둔다(P2, §III). WCET는 1,000번 측정으로 구한다(§VIII). Tesla V100(Xeon Silver 4215R), Jetson TX2·Xavier·Orin, Python·PyTorch FP16, YOLOX·YOLOv5, SORT, Waymo Open Dataset(§VII-A) |

## 결론

- 주기가 모두 같은 task 4개 set(V100 130 ms, Xavier 310 ms)에서 NPFP^B와 NPFP^BI는 batch 기회가 많아 최대 MOTA(약 40%)를 냈다. RT-MOT는 task가 늘수록 MOTA가 크게 떨어졌다(Fig. 6(a)(b), §VII-B. 수치는 그림에서 읽은 근삿값)
- 주기가 서로 다른 task 4·6개 set에서는 기다리는 NPFP^BI의 MOTA가 NPFP^B보다 약 10%p 높았다. Task 2개 set에서는 RT-MOT가 비슷하거나 더 높았다(같은 그림, 근삿값)
- Task 12개의 scheduling overhead는 RT-MOT가 NPFP^BI보다 V100에서 약 12배(2.4 대 0.2 ms), Xavier에서 9.6배(6.7 대 0.7 ms) 컸다(Fig. 6(c))
- 평가 방식: 실측(Tesla V100 server, Jetson Xavier. TX2·Orin도 비슷했다고 적음). Lemma 1을 통과한 task set만 비교했다(§VII-B)

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| 같은 detector에 들어갈 여러 입력을 batch 하나로 실행한다. NPFP^B는 기다리지 않고 이미 release된 job만 묶는다(§V) | NPFP^B는 priority 상위 x개를 schedulability 검사로 고른다. Grouping은 가장 오래 기다린 추론 요청의 모델을 고르고 queue에 있는 그 모델 추론 요청을 모두 묶는다. Batch로 줄이는 것이 Batch-MOT는 GPU 호출 수, 이 연구는 weight 적재 횟수다 | [구조] 같은 모델 추론 요청이 함께 생기도록 offset을 정해 기다리지 않아도 batch가 생긴다 |
| NPFP^BI는 미래 release를 기다려 묶는다. DeepRT Method의 기다려 묶기와 원리가 같다 | NPFP^BI는 다음 release 시각을 정확히 알고 schedulability가 허용하는 만큼만 기다린다. DeepRT Method는 모델마다 고정 window(14.9 ms)를 기다린다 | [실험] 기다려 묶기를 대표하는 DeepRT Method와 비교했다(Xeon에서 잰 모델 그룹 지연을 넣음, J = 0.8 ms, entry 4). DDR3 traffic은 제안 6.38, DeepRT Method 11.35 KiB/추론이고 최대 response time은 9.58, 23.80 ms다. J = 3.2 ms에서는 DeepRT Method의 DDR3 traffic이 더 적다. NPFP^BI 자체는 옮기지 않았다 |
| 주기 입력과 job별 deadline을 다룬다 | Batch-MOT는 release 시각을 주어진 값으로 받고 바꾸지 않는다. 이 연구는 Host가 모델마다 offset을 정한다 | [구조] Release 시각을 같은 모델끼리 맞춘다. Batch-MOT에는 주기가 같을 때 batch가 쉽게 생긴다는 관찰만 있다(§VII-B) |
| | Batch-MOT는 측정 WCET로 schedulability를 보인다(Theorem 3·5) | 없음. 이 연구는 32 ms hard deadline 보장을 주장하지 않는다 |

## 인용할 때

- 이 논문이 먼저 한 것: 주기 DNN task를 실행 중에 batch로 묶으면서 비선점 고정 priority의 schedulability를 지키는 검사, 미래 release를 기다려 묶는 idling. 기다려 묶기와 기다리지 않고 도착한 것만 묶기 자체는 신규성으로 주장하지 않는다(09 §3)
- 근거 위치: batch 이득 §I(Fig. 1)·§III(P1–P3), NPADAPT §IV(Lemma 1, Theorem 1), NPFP^B §V(Algorithm 1·2, Theorem 2·3), NPFP^BI §VI(Algorithm 3·4, Theorem 4·5), 결과 §VII-B(Fig. 6), WCET 측정 §VIII(Fig. 8)
- 주의: schedulability는 측정 WCET에 기대고 Lemma 1은 충분조건이다. NPFP^BI는 release가 엄격히 주기적이어야 다음 release를 안다. 실험의 task별 release 위상은 원문에 적혀 있지 않다
- 주의: batch는 full-size image로, 하나씩은 축소 image로 처리해 batch로 얻는 것은 정확도(MOTA)다. 저자의 "first" 주장은 여러 camera task의 batch DNN 실행에 엄격한 timing guarantee를 준 것에 한정된다(§I)
- 비교군: simulation 비교군에 없다. 기다려 묶기 원리는 DeepRT Method로 비교했다
