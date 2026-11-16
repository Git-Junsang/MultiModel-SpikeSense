# D07: Self-Supervised Industrial ASD with Sensor Distance

원문: `D07_SelfSupIndustrialASD_Access2026.pdf`
Erich Malan, Valentino Peluso, Andrea Calimera, Enrico Macii(Politecnico di Torino), "Self-Supervised Anomaly Detection for Industrial Machines With Sensor Distance Classification", IEEE Access 14, 2026, pp. 114675–114690, DOI 10.1109/ACCESS.2026.3716851
읽은 범위: 원문 전체(참고문헌 제외)

## 한 줄 요약

장비마다 전용 모델을 그 장비의 정상 소리만으로 학습하는 single-machine training을 위해 mic 배열의 각 mic와 장비 사이 거리를 맞히는 pretext task를 제안했다. MIMII에서 같은 조건의 재구성 방식보다 h-AUC가 최대 14.53 point, 여러 장비 데이터를 모은 machine ID 방식보다 최대 18.58 point 높았다(초록, Table 2·3).

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | 이상 소리는 드물어 정상 소리만으로 학습한다. single-machine training은 장비마다 전용 모델을 학습하지만 성능이 낮은 경우가 많다. multi-machine training은 여러 장비 데이터를 모아 공유 모델을 만들지만 공장과 고객이 흩어져 있으면 전송 비용과 생산 정보 유출 위험이 있다(초록, §I) |
| 방법 | Pretext task: 다채널 녹음의 채널마다 log-Mel segment를 입력해 그 mic와 장비 사이 거리 class를 맞힌다. 거리가 같은 mic는 같은 label이다. 정상 소리로만 학습하므로 이상 소리에서는 맞는 거리의 확률이 낮아진다(§III-A·B, Fig. 2) |
| 방법 | 학습: ConvNet(MicroNet-AD-L)을 cross entropy로 처음부터 학습한다. 64 frame segment, 거리 class 5개(D = 5), 8채널(C = 8), 15,000회, Adam, batch 32(§III-C, §IV-B3) |
| 방법 | 판정: 같은 시간 window의 채널 8개 segment를 batch로 넣고 맞는 거리 class 확률의 음의 logit을 채널 평균해 이상 점수로 쓴다. 10초 clip마다 segment 점수를 평균한다(§III-D, Eq. 3) |
| 가정·조건 | MIMII의 fan, pump, slider, valve 각 4대(ID 00, 02, 04, 06), 지름 68 mm 원형 mic 8개 배열, 장비에서 50 cm(valve는 10 cm). 장비 ID마다 모델을 따로 학습해 16개다(§IV-A, §IV-B3). 비교군 Reconstruction도 장비마다 따로 16개, Machine ID는 장비 종류마다 공유 모델 하나다(§IV-B1·B2). 결과는 초기값 5개 평균이다(§IV-C) |

## 결론

- Single-machine training끼리(6 dB): Sensor Distance가 Reconstruction보다 4종 모두 높다. Valve에서 h-AUC 82.72 → 97.25%, mAUC 77.95 → 92.66%다(§V-A1, Table 2)
- 공유 모델과 비교(6 dB): fan, slider, valve는 Sensor Distance가 높고 valve h-AUC는 78.67 대 97.25%다. Pump는 공유 Machine ID 모델이 92.23 대 84.22%로 높다(§V-A2, Table 3)
- SNR 0·−6 dB에서도 Reconstruction보다 높고 차이가 커진다(Table 4). 같은 방식을 다채널로 넓히기만 해서는 이 이득이 나오지 않는다(Table 6·7)
- 평가 방식: PyTorch 학습·시험(MIMII). hardware 구현과 측정은 없다

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| 장비 ID마다 모델을 따로 둔다 | Malan 등의 이유는 학습 데이터를 한곳에 모을 수 없다는 것이다. 이 연구는 DCASE 2020 Task 2 배포 데이터로 장비 ID마다 모델 40개를 학습한다(02 §1, §3) | 없음. 학습 방법은 이 연구의 주제가 아니다 |
| | Malan 등은 장비 하나에 mic 8개 배열이 필요하고 이상 데이터 없이 학습한다. 이 연구는 트랙(mic 하나)마다 모델이 정해지고 이상 파일 일부로 학습한다(02 §3) | [구조] 장비마다 다른 모델이 있을 때 그 weight 40벌(4.97 MiB)을 FPGA 하나에서 돌리는 문제를 다룬다. Malan 등은 추론 장치를 다루지 않는다 |

## 인용할 때

- 장비별 개인화 모델의 실무 근거로 쓸 문장과 위치
  - 초록(114675쪽): "The first, single-machine training, involves training a dedicated model using local data from each machine. ... The second, multi-machine training, ... aggregating data from multiple machines to train a shared model. This strategy requires transmitting data from geographically dispersed manufacturing sites ... raising concerns about data transmission costs and risks of exposing sensitive production information."
  - §I(114676쪽 왼쪽 단): "a key discriminant factor is the ability to train a specific model in-situ and for each target machine rather than training a single model serving multiple machines." 같은 문단에 공유 모델의 비용 네 가지(저장소, 네트워크 bandwidth, 보안, 데이터 보호 정책)와 "data island" 문제가 있다
  - §II-B1(114677쪽 오른쪽 단): MIMII 저자의 기준 autoencoder는 "trained different weight sets for each machine instance"
  - §II-B2(114678쪽 왼쪽 단): 장비 ID 분류 계열은 "require training data comprising audio recordings from multiple machines of the same type for training a shared model across all machines"
- Malan 등이 먼저 했다: mic와 음원 거리를 pseudo-label로 쓰는 self-supervised 이상음 탐지. 09 §3의 주장 범위와 겹치는 기법은 없다
- 주의: 원문은 장비별 전용 모델의 정확도가 낫다고 하지 않는다. 초록은 single-machine training이 "often yields suboptimal performance"라고 쓰고 pump에서는 공유 모델이 낫다(Table 3). 근거로는 데이터를 모으기 어렵다는 §I 문장을 쓴다
- 주의: 공유 모델(Machine ID)은 장비 종류 안의 4대끼리만 공유한다. 원문의 "14.53%", "18.58%"는 비율이 아니라 h-AUC의 차이(percentage point)다
- 비교군: 옮기지 않았다. 데이터셋과 학습 조건이 달라 AUC를 비교하지 않는다
