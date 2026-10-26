# 모델 40개 학습 결과

작성일: 2026-09-23

Code: `software/model/{train,train_all}.py`
Checkpoint: `software/weights/L_normal_noaug/<unit>/last.pth`

## 1. 조건

| 항목 | 값 |
|---|---|
| 모델 | PLIF-T `40→384→256→64→2` |
| 입력 | 16 kHz, 40 mel, 31 frame, 약 992 ms |
| 학습 | 지도학습, 실제 이상 절반 사용 |
| batch / epoch | 512 / 60 |
| Optimizer | Adam, lr 0.002, cosine decay |
| Loss | focal loss, gamma 2, file 단위 |
| Augmentation | time·frequency mask |
| Checkpoint | 마지막 epoch |
| GPU | RTX 3090 Ti |

Validation 이상 file이 20개 안팎이라 validation loss가 많이 흔들렸다. Minimum validation loss checkpoint의 평균 AUC는 0.8479였다. 마지막 epoch는 0.9563이었다.

## 2. Batch와 epoch

단일 장비 예비 실험에서 batch를 32→512로 키우면 epoch 시간이 13.7→0.86초로 줄었다. Validation AUC 차이는 0.006 이하였다. 그래서 batch 512를 썼다.

Validation AUC는 30–50 epoch에서 거의 포화했다. 여유를 두고 60 epoch와 cosine decay를 썼다.

이 예비 실험은 나중에 제외한 `fan_id00`, 8출력, 가짜 이상 조건이었다. Training speed와 대략적인 수렴 시점만 참고했다.

## 3. 장비 선택

DCASE에는 41개 ID가 있다. 처음에는 `slider_id06`을 뺐다. 전체 학습 뒤 `fan_id00` AUC는 0.738, `slider_id06`은 0.9982였다. 최종 구성에서는 `fan_id00`을 뺐다.

이 선택은 평가 결과를 보고 했다. 40대 평균은 selection 뒤 값이다. 41대 전체 평균 AUC 0.9510도 함께 보고한다.

## 4. 결과

| 지표 | 값 |
|---|---:|
| File ROC-AUC 평균 | 0.9563 |
| pAUC 평균 | 0.9209 |
| 균형 F1 평균 | 0.8231 |
| 균형 accuracy 평균 | 0.8286 |
| Segment F1 평균 | 0.7813 |
| Segment accuracy 평균 | 0.8305 |
| AUC ≥ 0.9 | 35/40 |
| 최저 | 0.8175 |
| 총 training time | 85.2분 |

기종별 AUC:

| 종류 | 수 | 평균 AUC |
|---|---:|---:|
| fan | 6 | 0.9825 |
| slider | 7 | 0.9767 |
| ToyConveyor | 6 | 0.9710 |
| ToyCar | 7 | 0.9590 |
| pump | 7 | 0.9477 |
| valve | 7 | 0.9067 |

Valve가 가장 약했다. 하위 장비는 `valve_id06` 0.8175, `ToyCar_id05` 0.8175, `valve_id03` 0.8770이었다.

장비별 전체 표는 `results.csv`를 따른다.

## 5. 뉴런 상태

| 항목 | L1 | L2 | L3 | L4 |
|---|---:|---:|---:|---:|
| Spike rate | 0.21 | 0.46 | 0.47 | — |
| 정수 환산 membrane 최대 | 3,446 | 8,544 | 16,707 | 4,276 |
| INT16 대비 | 10.5% | 26.1% | 51.0% | 13.0% |

INT16 범위를 넘은 모델은 없었다. Threshold도 모두 127 이하였다. Membrane potential은 16 bit를 유지했다.

출력 layer soft reset을 끄면 평균 AUC가 0.9563→0.9543으로 떨어졌다. 기존 뉴런 규칙을 유지했다.

## 6. 주의

- 실제 이상 절반을 학습에 썼다. DCASE official leaderboard와 직접 비교하지 않는다.
- 40대 구성은 test 결과를 보고 1대를 제외했다.
- 장비별 training seed는 하나다.
- INT8 결과는 [P2.5 보고서](<../../../documents/reports/P2.5 Research Report.md>)를 따른다.
