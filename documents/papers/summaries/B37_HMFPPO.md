# B37: HMF-PPO

원문: `B37_HMFPPO_INFOCOM2026.pdf`
Yikai Fu, Xiaochen Zhang, Meng Zhang(ZJU-UIUC Institute, Zhejiang University), "Heterogeneous Mean-field Reinforcement Learning for Age-minimal GPU Batching", IEEE INFOCOM 2026, 10쪽(PDF에 쪽 번호 없음), DOI 10.1109/INFOCOM59046.2026.11571668
읽은 범위: 원문 전체

## 한 줄 요약

User는 다음 task를 만들기 전 대기 시간과 보낼 server를 고르고 server는 task가 올 때 batch를 시작할지 고른다. 두 결정을 heterogeneous mean-field 강화학습(HMF-PPO)으로 함께 학습해 평균 AoI를 줄였고 같은 알고리즘에서 batch 없이 처리할 때보다 AoI가 47% 낮았다(초록, Table II).

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | batch를 쓰는 기존 edge 연구는 AoI를 목표로 두지 않거나 user 도착을 Poisson 같은 외부 확률 과정으로 본다(§II-A). User는 batch 형성에 맞춰 생성 시각을 정해야 하고 server의 batch 결정은 모든 user의 도착 pattern에 달려 있어 두 결정이 얽힌다(§I-B) |
| 방법(행동) | user i의 행동은 다음 task를 만들기 전 대기 시간 Z와 offloading server c다. Server j의 행동은 task가 도착할 때 batch를 시작할지(I_j)다. 시작하면 batch 크기는 min(b_max, queue 길이)이고 처리 시간은 θ_j(b)다(§III-A) |
| 방법(목표) | user 평균 AoI의 장기 평균을 줄인다(Eq. 4). AoI는 지금 쓰는 결과의 생성 시각부터 흐른 시간이다(Eq. 1–3) |
| 방법(학습) | user와 server 두 class의 SMDP로 놓고 다른 agent의 영향을 평균값(평균 AoI, 평균 queue 길이)으로 근사한다. Actor는 local state(AoI, 갈 수 있는 server 목록)만 보고 critic은 평균값을 함께 본다. AC판은 actor도 평균값을 본다(§IV-B, §V-A). 근사 오차는 agent 수 N이 늘면 O(1/√N)으로 줄어든다(Theorem 1) |
| 방법(생성 시각과 batch) | 생성 시각을 정해 user에게 내려 주는 offset이나 group 배정은 없다. 생성 시각은 user마다 학습된 policy가 정하고 batch에 맞추는 행동은 학습에서 나온다. 학습 초기(epoch 25 근처)에 user는 server queue가 비어도 생성을 늦춰 batch의 맨 앞 task가 되지 않으려 했다(§V-B1). 원문은 이것을 batch 형성에 "predictively synchronize"한다고 적었다(§I-C) |
| 가정·조건 | 시간은 slot 단위다. 전송 지연은 추론 시간보다 작다고 보아 뺐다(§III-A). Batch 처리 시간은 batch 크기의 결정적 함수다. User에게 고정 주기가 없고 대기 시간으로 생성 빈도까지 바꾼다. Weight 적재와 메모리는 다루지 않는다 |
| 가정·조건 | 모델은 VGG-19 하나(224 × 224 영상 분류)다. GoogLeNet, ResNet-50, VGG-19는 Jetson TX2와 RTX 4090에서 batch 처리 시간을 잴 때만 썼다(Fig. 2, §V-A). Server는 Jetson TX2 15대이고 학습은 RTX 4090 8장으로 했다. User 15–120명, server 5–15대다(Table I). 비교는 MAPPO, MASAC, IPPO와 고정 batch 크기 1·2·4·8이다(§V-A, Table II) |

## 결론

- 고정 batch와 비교(Table II): HMF-PPO(AC)의 평균 AoI는 dynamic batch 40.19, batch 크기 1(batch 없음) 75.71로 47% 낮았다. 고정 batch 중 가장 좋은 크기 4는 44.50이었다. Table II의 user·server 수는 적혀 있지 않다
- 규모별 최종 AoI(Table I): user 120명·server 15대에서 HMF-PPO(AC) 66.17, IPPO 78.04, MAPPO 103.82, MASAC 170.12였다. User 15–80명 규모에서도 HMF-PPO 두 판 중 하나가 가장 낮았고 표준편차도 작았다
- User 30명·server 5대에서 시작해 150·300 epoch에 5명씩 더하고 450 epoch에 5명을 빼도 다시 수렴했다. 최종값은 처음부터 학습한 값과 같았다(Fig. 4c)
- 평가 방식: 원문은 Jetson TX2 15대 testbed 실험이라고 적었다. User가 실제 장치인지, server가 매번 VGG-19를 실행했는지 θ(b)로 처리 시간을 넣었는지는 적혀 있지 않다. AoI 단위(slot 길이)도 없다

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| 입력을 만드는 시각을 server batch와 맞춘다. 학습된 user는 batch 맨 앞에서 오래 기다리지 않도록 생성을 늦췄다(§V-B1) | 생성 시각은 user마다 학습된 policy가 정하고 user끼리 맞출 group이나 offset 표가 없다. 같은 시각 도착이 실제로 생기는지는 보이지 않았다. 이 연구는 Host가 같은 모델 트랙에 같은 offset을 주어 같은 모델 추론 요청이 같은 시각에 생기게 한다 | [구조] 같은 모델 추론 요청이 함께 생기는 것을 offset 설계로 정하고 학습·수렴 과정이 없다 |
| | 모델은 하나이고 목적은 평균 AoI다. User는 생성 빈도까지 바꾼다. 이 연구는 트랙마다 32 ms마다 추론 요청 하나가 생기고 `O_m = m × 0.8 ms`는 고정이며 feedback이 없다. 지표는 DDR3 traffic과 response time이다 | [구조] 모델끼리 0.8 ms씩 벌려 모델 40개의 weight 적재를 줄이는 순서를 만든다. HMF-PPO는 모델 전환과 weight 적재를 다루지 않는다 |
| | server는 task가 올 때마다 batch를 시작할지 policy로 정하고 시작하지 않으면 다음 task를 기다린다(§III-A). 이 연구의 Grouping은 기다리지 않고 이미 도착한 같은 모델 추론 요청만 묶는다 | 없음 |

## 인용할 때

- 이 논문이 먼저 한 것: user의 생성 시각(대기 시간)과 server의 batch 시작 결정을 함께 최적화해 AoI를 줄이는 것, 생성 시각을 batch 형성에 맞추는 것이 이득이라는 관찰(§I-C, §V-B1). 원문은 "age-minimal GPU batching" 문제를 처음 다룬다고 적었다. 생성 시각을 batch에 맞추는 것 자체는 신규성으로 주장하지 않는다
- 우리가 주장할 수 있는 범위: 모델을 기준으로 offset을 설계해 weight 재사용을 만드는 것, offset이 고정이고 feedback이 없는 것, 기다리지 않는 Grouping과 Predicted-Next-Use (PNU) Weight Cache를 결합한 것
- 근거 위치: 행동·batch 모델 §III-A, AoI Eq. 1–4, SMDP §III-C, 오차 상한 Theorem 1, 알고리즘 §IV-B·Alg. 1, 실험 조건 §V-A, 결과 Table I·II, Fig. 4
- 주의: 47%는 HMF-PPO(AC) 안에서 dynamic batch와 batch 없음(B1)을 비교한 값이다. 다른 학습 방식 대비가 아니다. AoI 값에 단위가 없고 Fig. 2의 batch 처리 시간 말고는 지연 수치가 없다
- 주의: "synchronize"는 user 각자의 생성을 batch 시작에 맞춘다는 뜻이다. User끼리 같은 시각에 생기게 하는 규칙은 없다
- 관련: 참고문헌 [13] Cang 등과 [17] Shi 등은 `B32_JointBatchingAsyncArrivals_TWC2024.pdf`, `B28_MultiuserCoInference_TWC2023.pdf`와 제목이 같다. [12] Inoue의 queueing 분석은 Nakayama 등(B25)도 인용한다
