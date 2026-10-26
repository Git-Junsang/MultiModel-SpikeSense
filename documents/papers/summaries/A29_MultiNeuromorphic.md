# A29: Multiple Neuromorphic Components

원문: `A29_MultiNeuromorphic_NCE2026.pdf`
Evan Eames, Priyadarshini Kannan, Ronan Sangouard, Philipp Plank, Elvin Hajizada, Gintautas Palinauskas, Lana Amaya, Michael Neumeier, Sai Thejeshwar Sharma, Marcella Toth, Prottush Sarkar, Axel von Arnim, Neuromorphic Computing and Engineering 6(2) 024001, 2026, DOI 10.1088/2634-4386/ae4a47
읽은 범위: 원문 전체(Supplementary material 제외)

## 한 줄 요약

DVS camera로 socket을 찾아 plug를 꽂는 robot pipeline의 SNN 구성요소 6개를 neuromorphic hardware에 함께 올리고 실행 순서는 neuron으로 만든 neural state machine(NSM)이 정하게 해 off-chip process 관리 logic 없이 돌렸다. Loihi 2에서 timestep 하나에 88 ms가 걸리고 78 mJ을 썼으며 전체 전력은 0.88 W였다.

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | 여러 SNN을 이어 쓰려면 지금은 off-chip의 non-spiking hardware가 전체를 관리해야 해서 neuromorphic hardware의 저지연·저전력 이점이 줄어든다(§1) |
| 방법 | 구성요소는 selective DNF(볼 socket 고르기), relational network(RN, 고른 사분면만 통과), SLAYER로 학습한 분류기, 메모리 DNF(이미 본 socket 억제), visual servoing actor, force-torque 삽입 actor다(§3.2–3.7, Fig. 1) |
| 방법 | NSM은 동작을 elementary behavior(EB) 두 개(visual search, visual servoing)로 나눈다. EB마다 intention과 condition of satisfaction(CoS) neuron을 두고 visual search에는 condition of dissatisfaction(CoD) neuron도 둔다. Precondition neuron이 다음 EB를 연다. 틀린 socket이면 CoD가 DNF peak를 무너뜨려 다음 socket을 찾게 한다(§2.3, §3.8, Fig. 4) |
| 방법 | 구성요소는 모두 동시에 올라가 있고 intention neuron의 흥분·억제로 단계가 바뀐다. Chip 배치는 LAVA compiler가 정하며 실행마다 neurocore 배치가 조금 달라진다(§3.8, §4.1, §5.1) |
| 가정·조건 | Loihi 2 Kapoho Point(8-chip system, Intel vlab), LAVA 0.10.0. DVS event를 20 ms frame으로 묶고 80 × 80으로 줄인다. 입력 camera는 하나다. 원문에 주기 deadline, weight 적재, 모델 교체가 나오지 않는다(§3, §3.1, Table 1) |

## 결론

- Neuron은 약 30,000개라 이론상 neurocore 4개면 되지만 연결이 많아(특히 DNF 두 개) chip 2–3개, neurocore 250–300개를 쓴다. Chip 하나에 neurocore가 128개이고 neurocore 하나가 neuron 8,192개를 돌린다(§4.1)
- Loihi 2 측정(녹화한 event 입력): timestep 하나에 88 ms, 평균 78 mJ(dynamic 59 mJ), 전체 0.88 W(dynamic 0.67 W)다. DNF peak는 약 1.8 s에 다 생기고 분류 결과는 5–6 s에 나온다(§4.1, Table 1, Fig. 5)
- MuJoCo simulation(simulated LAVA, 250회): visual servoing 성공 68%, 분류 약 90%다. 실제 robot(simulated LAVA, 삽입 actor만 Loihi 1): 분류와 visual servoing 100%, 삽입 성공 70%, 평균 위치 오차 4 mm다(§4.2–4.4, Table 2)
- 평가 방식: Loihi 2 실측(전력·지연·동작 확인), simulated LAVA로 돌린 MuJoCo simulation과 실제 robot 시험

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| 여러 SNN을 한 장치에서 돌린다 | Eames 등은 구성요소를 모두 neurocore에 동시에 올려 pipeline 하나로 잇는다. 이 연구는 독립된 모델 40개가 compute array 하나를 나눠 쓰고 BRAM(약 1.6 MiB)보다 큰 weight 4.97 MiB를 DDR3에 두고 entry 4개에 적재한다 | [구조] weight 합이 on-chip 메모리보다 커도 돌린다. PNU-Count가 entry에 둘 모델을 고르고 Grouping이 같은 모델 추론 요청을 batch로 묶는다 |
| neuron state가 다음 timestep으로 이어진다 | Eames 등은 camera 하나라 state가 한 벌이고 deadline이 없다. 이 연구는 mic 트랙 1,024개가 32 ms마다 추론 요청을 내고 트랙마다 membrane potential을 따로 둔다 | [구조] 12 bit Membrane Storage로 768트랙의 state를 BRAM에 둔다 |
| 구성요소의 실행 순서를 정하는 부분이 있다 | Eames 등은 neuron으로 만든 NSM이 정한다. 이 연구는 Host가 offset을, FPGA의 Grouping이 처리할 모델을 정한다 | 없음. Neuron 기반 process 관리는 다루지 않는다 |

## 인용할 때

- Eames 등이 먼저 했다: 여러 SNN 구성요소를 neuromorphic hardware에 함께 올리고 neuron으로 만든 NSM으로 순서를 정했다. 원문은 이것을 "first example"이라고 쓴다(초록, §1). 09 §3의 주장 범위와 겹치는 기법은 없다. 여러 SNN을 한 장치에서 처음 돌렸다고 쓰지 않는다
- 근거 위치: 신규성 주장 §1 끝, NSM §2.3·§3.8·Fig. 4, 구성요소 §3.2–3.7, chip·neurocore 수 §4.1, 전력·지연 Table 1, 시험 결과 Table 2, partition 문제 §5.1
- 주의: 제목의 "on-chip"은 chip 하나라는 뜻이 아니다. Pipeline은 Kapoho Point 보드 하나에서 chip 2–3개를 쓴다(§1, §4.1). P3.18 §3.2 표는 초록 기준으로 "Loihi 2 한 칩"이라고 적었다
- 주의: 원문은 전력을 "milliwatt regime"(§5.1), "sub-milliwatt regime"(§1, §5.3)이라고 쓰지만 Table 1 값은 dynamic 0.67 W, 전체 0.88 W다
- 주의: 실제 robot 시험은 Loihi가 아니라 simulated LAVA로 돌렸고 삽입 actor만 Loihi 1에서 돌렸다(§4.3). Loihi 2에서는 녹화한 입력이라 정확도를 재지 못했다(§5.2). 실제 robot의 분류 100%는 socket 위치가 늘 같은 조건이다(§4.4)
- 비교군: 옮기지 않았다
