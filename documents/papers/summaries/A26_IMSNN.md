# A26: IM-SNN

원문: `A26_IMSNN_ICONS2024.pdf`
Ahmed Hasssan, Jian Meng, Anupreetham Anupreetham, Jae-sun Seo, ICONS 2024, pp. 148–155, DOI 10.1109/ICONS62911.2024.00029
읽은 범위: 원문 전체

## 한 줄 요약

SNN의 membrane potential을 timestep마다 ternary {−1, 0, +1}(원문 표기 1.5 bit)로 양자화하고 weight를 4·2 bit로 줄이는 학습 방법(IM-SNN)을 냈다. CIFAR-10 ResNet-19에서 전체 메모리를 60.94 MB에서 7.49 MB로 8.13배 줄이고 정확도는 0.45%p 떨어졌다. Hardware 구현은 없다.

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | spike는 1 bit지만 membrane potential은 full precision이라 DNN activation만큼 메모리를 쓰고 timestep마다 읽고 쓴다. 기존 연구의 membrane potential은 12·24 bit 고정소수점(Q-SpiNN, Loihi)에 머문다(§I) |
| 방법 | 음의 clipping: membrane potential 아래쪽을 c로 자른다. 충분히 음인 값은 이후 spike에 거의 영향이 없다는 관찰이 근거다. ResNet-19 CIFAR-10에서 c = −1.0으로 잘라도 정확도는 94.53%에서 94.09%다(§IV-A, Fig. 2, Table I) |
| 방법 | 양자화: 매 timestep 누산·발화·reset을 마친 값을 가장 가까운 level로 바꿔 저장한다. 다음 timestep은 저장한 level에 decay를 곱하고 입력을 더한다. Dequantization scale 곱이 없는 integer-only 방식이다(§IV-B, Algorithm 1, 식 (6)) |
| 방법 | 학습: 양자화 함수의 시간 방향 gradient를 sigmoid 합으로 근사한다(Stacked Gradient Surrogation, SGS)(§IV-B, 식 (9)–(11)) |
| 방법 | membrane pruning: ternary 값이 −1인 뉴런은 spike와 이후 갱신에서 뺀다. Weight는 Power-of-Two(PoT) 양자화로 4 bit 또는 2 bit로 줄인다(§IV-C, §IV-D) |
| 가정·조건 | PyTorch로 학습·추론한다(A6000 GPU 4개). 메모리는 weight·membrane potential·spike 개수에 bit 수를 곱한 계산값이다(식 (15)). 정지 image는 T번 반복해 넣는다. Hardware, 주기 deadline, 여러 모델은 원문에 나오지 않는다 |

## 결론

- CIFAR-10 ResNet-19(weight 4 bit, membrane 1.5 bit, T = 2): 전체 7.49 MB(32 bit 기준선 60.94 MB의 1/8.13), 정확도 94.11%(기준선 94.56%보다 0.45%p 낮음)다. Membrane potential 몫은 5.5 MB에서 0.25 MB로 준다(§V-C, Table V)
- DVS-CIFAR10 VGG-9(weight 2 bit, T = 10): 3.75 MB(48.58 MB의 약 1/13), 77.94%(−0.51%p)다. Prophesee Gen1 object detection(weight 4 bit): 31.57 MB(223.20 MB의 1/7.08), mAP 0.240 → 0.198이다(Table VI·VII)
- Membrane pruning은 membrane 메모리를 절반으로 줄이고(ResNet-19 CIFAR-100, 250 → 125 KB) 정확도는 1%p 미만 떨어진다. 연산 수는 27.52 → 15.72 MOPs다(§IV-C, Table III)
- 평가 방식: GPU software simulation. 메모리는 식 (15)로 센 계산값이다

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| membrane potential을 넓은 폭으로 계산하고 좁은 폭으로 줄여 저장한다(Algorithm 1) | IM-SNN은 값을 3 level로 바꾸고 학습(SGS)으로 정확도를 되찾는다. 이 연구는 16 bit로 계산하고 12 bit로 포화만 한다 | 없음. 저장 폭은 IM-SNN이 훨씬 좁다 |
| state를 timestep 사이에 넘긴다 | IM-SNN은 한 입력의 timestep 사이 state만 다루고 메모리 감소는 식으로 센 값이다. 이 연구는 트랙마다 state를 32 ms 추론 요청 사이에 이어 간다 | [구조] 줄인 저장 폭으로 남는 BRAM에 768트랙의 state를 둔다 |
| weight 메모리가 부담이다 | IM-SNN은 network 하나의 weight bit 수를 줄인다. 이 연구는 모델 40개 weight 4.97 MiB가 BRAM(약 1.6 MiB)보다 커서 DDR3에서 적재하는 횟수가 문제다 | [구조] Grouping으로 같은 모델 추론 요청을 묶고 PNU-Count로 다시 쓸 모델을 entry에 남겨 DDR3 traffic을 줄인다 |

## 인용할 때

- Hasssan 등이 먼저 했다: membrane potential을 timestep마다 ternary까지 줄여 저장하고 학습으로 정확도를 지켰다. Membrane potential 저정밀 저장 자체는 신규성으로 주장하지 않는다(P3.18 §1.2). 09 §3 주장 2는 12 bit Membrane Storage를 다른 기법과 결합한 구조다
- 원문은 Q-SpiNN(Putra·Shafique, IJCNN 2021)이 12 bit, Loihi가 24 bit membrane potential을 이미 썼다고 적는다(§I). 12 bit라는 폭을 새롭다고 쓰지 않는다
- 근거 위치: clipping §IV-A·Table I, 양자화 §IV-B·Algorithm 1, pruning §IV-C·Table III, weight §IV-D, 메모리 식 (15)–(17), 결과 Table V–VII
- 주의: 원문은 ternary를 1.5 bit로 센다(§IV-B). 3 level을 1.5 bit에 담는 저장 형식은 적지 않는다. 8.13배·13배는 이 값으로 센 계산 결과다
- 주의: 선행 연구 비교(Table V·VI)는 network와 T가 서로 다르다. 감소 배수는 같은 network의 32 bit 기준선 대비다
- 주의: 식 (5)는 −1과 0의 구간이 겹쳐 적혀 있다(u ≤ 0, u ≤ 0.5). 본문 설명(가장 가까운 level)과 Algorithm 1을 따른다
- 주의: 저장소의 PDF는 IEEE Xplore 판이다(쪽마다 Xplore 다운로드 표시). `references/INDEX.md`는 NSF PAR 공개본이라고 적었다. 저자 이름 Hasssan은 원문 표기 그대로다
