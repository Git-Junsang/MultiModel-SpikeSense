# B28: Multi-user Co-inference

원문: `B28_MultiuserCoInference_TWC2023.pdf`
Wenqi Shi, Sheng Zhou, Zhisheng Niu, Miao Jiang, Lu Geng, IEEE Transactions on Wireless Communications 22(1), pp. 286–300, 2023, DOI 10.1109/TWC.2022.3192613(서지는 OpenAlex 기준). 받은 PDF는 arXiv:2206.06304v1(2022-06-03) 판이라 저널 표기·DOI가 없다
읽은 범위: 원문 전체(arXiv v1, 부록 A·B 포함)

## 한 줄 요약

같은 DNN을 쓰는 모바일 기기들이 sub-task 일부를 GPU edge server에 맡길 때, latency constraint가 모두 같고 edge 계산 시간이 batch 크기와 무관하면 기기마다 따로 나눌 지점을 정하고 같은 sub-task를 모두 batch 하나로 모으는 것이 최적임을 보였다(Theorem 1). 이를 넓힌 IP-SSA는 offline simulation에서 기기 에너지를 PS 대비 최대 94.9% 줄였다(초록, §V-C).

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | latency constraint를 지키면서 기기 에너지 합이 가장 작도록 offloading(기기마다 어느 sub-task부터 edge server에 맡길지)과 scheduling(받은 sub-task를 어떤 batch로 언제 돌릴지)을 함께 정한다(§II-D, P1). 같은 sub-task만 한 batch에 들고(Eq. 8) Batch는 든 sub-task가 모두 준비돼야 시작한다(Eq. 9) |
| 방법 | Theorem 1: latency constraint가 모두 같고 edge 계산 시간이 batch 크기와 무관하면 다음을 만족하는 최적해가 있다. 기기는 sub-task 하나를 맡기면 뒤 sub-task도 모두 맡긴다. 맡긴 같은 sub-task는 모두 batch 하나에 든다. Batch 시작 시각은 deadline에서 거꾸로 `s*_N = l − F_N(1)`, `s*_n = s*_{n+1} − F_n(1)`로 정한다. 기기는 latency constraint를 지키는 가장 낮은 주파수를 쓴다(§III, Eq. 17) |
| 방법 | Alg. 1: batch 시작 시각을 먼저 정하면 기기 사이 결정이 서로 얽히지 않는다. 기기마다 나눌 지점을 모두 해 본다. 지점마다 앞부분 계산과 upload가 다음 batch 시작 시각에 끝나도록 주파수를 정하고(Eq. 18) 에너지가 가장 작은 지점을 고른다. 계산량은 O(MN)이다 |
| 방법 | IP-SSA(Alg. 2): batch 크기 b를 M부터 줄이며 F_n(1)을 F_n(b)로 바꿔 Alg. 1을 호출한다. 실제 가장 큰 batch가 b 이하인 해 중 에너지가 가장 작은 것을 고른다(§IV-A). OG(Alg. 3): latency constraint 순으로 이어진 기기끼리 group을 만드는 최적해가 있다는 Theorem 2로 dynamic programming을 한다(§IV-B). Online에서는 DDPG가 slot마다 기다릴지, 기기에서 처리할지, OG를 호출할지와 edge 점유를 줄이는 기준 l_th를 정한다(§IV-C) |
| 가정·조건 | 모델은 하나다. 모든 기기가 같은 학습된 DNN을 가진다(§II). Edge server는 GPU 1개이고 batch를 한 번에 하나만 돌린다(Eq. 11). Offline은 모든 입력이 t = 0에 준비된다(Eq. 16). Online은 25 ms slot 단위의 Bernoulli 도착 등이다(§IV-C, §V-D, Table IV). 평가 DNN은 mobilenet-v2와 3dssd이고 sub-task 계산 시간은 RTX3090에서 쟀다(§V-A) |

## 결론

- Offline, 3dssd(latency constraint 250 ms), M = 15: IP-SSA는 기기 에너지를 W = 1 MHz에서 FIFO보다 40.6%, PS보다 51.7% 줄였다. W = 5 MHz에서는 93.1%, 94.9% 줄였다(§V-C, Fig. 5a)
- mobilenet-v2, M = 10: 앞쪽 sub-task는 평균 batch 크기가 작고 뒤쪽은 크다. Latency constraint가 길수록 batch가 커졌다. 100 ms에서는 B5부터 평균 batch 크기가 10.0으로 기기 10대가 모두 한 batch에 들었다(§V-C, Table III)
- Online, M = 14, Bernoulli 도착: DDPG-OG가 DDPG-IP-SSA보다 에너지를 3dssd에서 최대 8.92%, mobilenet-v2에서 최대 8.85% 덜 썼다. 고정 time window마다 IP-SSA나 OG를 호출하는 방식은 M ≥ 2에서 성능이 낮았다(§V-D, Fig. 8, Table V)
- 평가 방식: simulation이다. Sub-task 계산 시간만 RTX3090에서 쟀고 무선 전송(Shannon 용량, 반지름 100 m)과 기기 에너지는 식으로 계산했다(§V-A·B, Table II)

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| 같은 DNN 부분을 쓰는 여러 입력을 가속기 하나에서 batch 하나로 처리한다. 같은 sub-task(이 연구는 같은 모델)만 한 batch에 든다(Eq. 8) | 모델은 하나이고 batch는 sub-task 단위다(§II). 목표는 기기 에너지이고 weight 전송은 다루지 않는다. 이 연구는 모델 40개 weight 4.97 MiB가 BRAM보다 커서 weight 전송이 병목이다 | [구조] 모델이 여러 개이고 weight 합이 on-chip 메모리보다 큰 경우를 다룬다. PNU-Count가 다음 사용이 가장 늦을 모델을 내보낸다 |
| 같은 batch에 들 입력이 거의 같은 시각에 준비된다 | offline은 입력이 모두 t = 0에 생긴다고 둔다(Eq. 16). 기기가 주파수를 낮춰 upload가 다음 batch 시작 시각에 끝나게 한다(Eq. 18). Edge server는 deadline에서 거꾸로 정한 가장 늦은 시각에 batch를 시작한다(Eq. 17). 이 연구는 Host가 같은 모델 트랙에 같은 offset을 줘 생성 시각을 맞추고 Grouping은 기다리지 않는다 | [구조] batch 시작을 가장 늦은 시각까지 미루지 않아 기다리는 시간이 response time에 더해지지 않는다 |
| | online은 slot마다 Bernoulli로 도착하고 DDPG가 기다릴지와 OG를 호출할지 정한다. 기다리면 batch가 커지는 trade-off를 학습으로 푼다(§IV-C). 도착 시각을 바꾸는 장치는 없다 | [구조] offset으로 같은 모델 추론 요청이 함께 생겨 기다리지 않아도 batch가 생긴다 |

## 인용할 때

- 이 논문이 먼저 한 것: 같은 DNN을 쓰는 여러 기기의 같은 sub-task를 edge GPU에서 batch 하나로 모으는 것이 최적이라는 증명(Theorem 1, 부록 A), 그 batch를 전제로 offloading과 scheduling을 함께 정하는 최적화. 같은 모델의 묶음 처리 자체와 같은 시각 도착으로 batch 만들기 자체는 신규성으로 주장하지 않는다([09_RELATED_WORK §3](../../design_references/09_RELATED_WORK.md#3-신규성-경계))
- 최적성 조건: latency constraint가 모두 같고(l_m = l) edge 계산 시간이 batch 크기와 무관하다(F_n(b) = F_n(1), §III). 증명은 모든 입력이 t = 0에 준비되고(Eq. 16) edge가 기기보다 빠르다는 것도 쓴다(부록 A). 두 조건을 풀면 Theorem 1이 성립하지 않아 IP-SSA·OG는 최적이 아니다(§IV-A). OG는 가정 (19)·(20) 아래의 group 나누기만 최적이다(Theorem 2)
- 근거 위치: 문제 §II-D(P1), Theorem 1 §III·부록 A, Alg. 1 Eq. 17·18, IP-SSA §IV-A, OG §IV-B(Theorem 2·부록 B), online §IV-C, 결과 §V-C(Fig. 5–7, Table III)·§V-D(Fig. 8, Table V)
- 주의: 도착을 맞추는 효과는 offline에만 있다. Eq. 18은 upload가 다음 batch 시작 시각에 끝나도록 기기 주파수를 고른다. 원문은 이를 도착 맞추기라고 부르지 않고 에너지를 줄이는 데 쓴다. 생성 시각은 정하지 않고 t = 0으로 둔다. 도착 시각이 기기마다 다른 경우는 각주 3에서 식만 넓혔다
- 주의: 받은 판은 arXiv v1이다. TWC 게재판의 절·식·그림 번호와 수치는 확인하지 못했다. Simulation 비교군에 없다
