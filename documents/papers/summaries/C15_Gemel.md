# C15: Gemel

원문: `C15_Gemel_NSDI2023.pdf`
Arthi Padmanabhan, Neil Agarwal, Anand Iyer, Ganesh Ananthanarayanan, Yuanchao Shu, Nikolaos Karianakis, Guoqing Harry Xu, Ravi Netravali, "Gemel: Model Merging for Memory-Efficient, Real-Time Video Analytics at the Edge", USENIX NSDI 2023, pp. 973–994. DOI 없음(https://www.usenix.org/conference/nsdi23/presentation/padmanabhan)
읽은 범위: 원문 전체(부록 A 포함)

## 한 줄 요약

서로 다른 vision DNN에서 구조가 같은 layer를 weight까지 하나로 합치고 다시 학습해(model merging) edge GPU 메모리 사용을 최대 60.7% 줄였다. 같은 GPU 메모리에서 Nexus 변형 scheduler만 쓸 때보다 swap을 기다리는 시간이 줄어 정확도가 8–39% 높았다(초록, §6).

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | 상용 edge box의 GPU 메모리는 2–16 GB라 workload의 모델 수십 개가 함께 들어가지 않는다(§2, §3.1). 모델을 번갈아 올리면 적재 시간이 대개 추론 시간보다 길어 frame을 놓친다(§1, §3.2) |
| 방법 | 병합 대상: 종류와 종류별 속성이 같은 layer는 weight가 달라도 합칠 후보가 된다(§4.1). 병합한 layer는 weight 한 벌을 함께 쓰므로 GPU 메모리에 한 번만 올린다. 중간값(layer 출력)은 공유하지 않는다(§4) |
| 방법 | 병합 순서: 한 layer가 workload에 나오는 모든 자리를 group으로 묶고 전체 메모리가 큰 group부터 정렬한다. Group을 하나씩 더해 그 layer가 나오는 모든 모델에서 공유하고 cloud에서 함께 다시 학습한다(§5.3) |
| 방법 | 재학습: 모든 모델이 정확도 목표(평가 기본값 95%)를 넘거나 시간 한도(기본 10 epoch)가 지날 때까지 학습한다. 실패하면 group을 반으로 줄여 다시 하거나 다음 group으로 넘어간다. 조기 성공·실패 판단으로 재학습 시간이 평균 28% 줄었다(§5.3) |
| 방법 | edge 적재: Nexus 변형 scheduler가 공유 layer가 많은 모델을 load 순서에서 이웃하게 둬 GPU 메모리에 없는 layer만 적재한다(§5.4). 모델을 내보낼 때는 GPU에 있거나 다음에 올릴 모델이 쓰는 공유 layer를 남긴다(부록 A.1) |
| 방법 | 운영: 처음에는 원래 모델로 추론한다. 병합이 성공할 때마다 병합 모델을 edge로 보낸다. 표본 frame으로 데이터 drift를 보고 정확도가 목표보다 낮으면 원래 모델로 되돌린다(§5.1, Fig. 9) |
| 가정·조건 | 모델은 7개 family(YOLO, Faster RCNN, ResNet, VGG, SSD, Inception, Mobilenet)에서 family마다 최대 4개 변형이고 task는 분류와 검출이다. Workload 15개는 query 3–42개(평균 15), video 3–7개, 서로 다른 모델 2–10개(평균 6)다. 병합으로 줄일 수 있는 메모리 비율에 따라 LP 3개, MP 6개, HP 6개로 골랐다(§2) |
| 가정·조건 | frame마다 처리 SLA가 있다(기본 100 ms, 30 FPS, §6.1·§6.2). GPU 하나 단위로 보고 swap은 CPU에서 PCIe로 GPU 메모리에 올린다(§2, §3.2) |
| 가정·조건 | GPU 메모리는 workload마다 세 가지다. Min은 가장 큰 모델 하나를 batch 크기 1로 돌릴 만큼이고 나머지는 모든 모델을 올려 둘 메모리(no swap)의 50%, 75%다(§2) |

## 결론

- 비교 기준(Nexus 변형): SLA 100 ms에서 frame 19–84%를 처리하지 못했고 정확도가 모든 모델을 올려 둘 때보다 최대 43% 낮았다(§3.2, Fig. 3). Tesla P100에서 모델 하나의 적재에 6.7–117.3 ms가 걸려 batch 크기 1 추론 시간의 0.98–34.4배였다(Table 1). 원문은 이 적재 시간을 원인으로 꼽았다
- 메모리: parameter 메모리가 17.5–60.7%(0.2–5.1 GB) 줄었다. Stem 공유인 Mainstream보다 5.9–52.3% 더 줄었다. 정확도를 무시하고 같은 구조 layer를 모두 합친 Optimal과의 차이는 중앙값 workload에서 9.3–29.0%다(§6.1, Fig. 12·13)
- 정확도: min 메모리에서 중앙값 workload의 정확도가 LP 8.0%, MP 13.5%, HP 39.1% 올랐다. Swap을 기다린 시간이 17.9–84.0% 줄어 frame을 13–44% 더 처리했다(§6.1, Fig. 11). 병합 모델은 정확도 목표를 넘는지 확인한 뒤 edge로 보낸다(§1, §5.1)
- 평가 방식: 두 도시 camera 12대의 video와 PyTorch 구현으로 낸 결과다(§2, §5.1). 적재·실행 시간은 Tesla P100에서 쟀다(Table 1). 평가 GPU와 메모리 제한 방법은 따로 적혀 있지 않다

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| 모델이 정해진 순서로 돌아오는 workload에서 다음 사용이 가장 먼 모델을 내보낸다. 다음 모델의 적재를 지금 실행과 겹친다(Nexus 변형 §3.2, 이 연구의 prefetch) | Nexus 변형은 round-robin 순서가 고정이라 가장 최근에 실행한 모델이 다음 사용이 가장 먼 모델이다. 이 연구에서는 실제 도착이 nominal frame 끝 시각보다 Host 처리 지연과 링크 지연만큼 늦고 모델 그룹 전체가 늦을 수 있다. 그래서 PNU-Count는 queue, 모델 그룹 지연 분포, 추론 요청별 지연 분포, 예상 추론 요청 수(n_expect)로 이번 주기에 아직 올 추론 요청이 있는지 가린다 | [실험] 같은 원리의 offset-only보다 PNU-Count의 DDR3 traffic이 적다. J = 0.8 / 1.6 / 3.2 ms에서 6.63 / 13.08 / 40.11 대 6.38 / 6.56 / 12.37 KiB/추론 |
| weight 합이 가속기 메모리보다 커서 weight 적재가 병목이다(§3.2, Table 1). 이 연구는 모델 40개 weight 4.97 MiB가 BRAM 약 1.6 MiB보다 크다 | Gemel은 서로 다른 모델의 같은 구조 layer를 weight 한 벌로 합치고 다시 학습해 적재량 자체를 줄인다. 이 연구는 모델 weight를 바꾸지 않고 같은 모델을 쓰는 트랙끼리만 weight 공유를 한다 | [구조] weight를 바꾸지 않아 재학습과 정확도 확인이 필요 없다. 서로 다른 모델 사이 weight 공유는 하지 않는다 |
| | Nexus 변형은 offline profile로 정한 모델별 batch 크기로 round-robin을 돈다(§3.2). Gemel에는 추론 요청 도착 시각을 정하는 장치가 없다. 이 연구는 Host가 같은 모델 트랙의 frame 생성 시각을 맞추고 Grouping은 기다리지 않는다 | [구조] Model-Grouped Offset Assignment로 같은 모델 추론 요청이 함께 생겨 기다리지 않아도 batch를 이룬다 |

## 인용할 때

- Gemel이 먼저 한 것: 서로 다른 vision DNN 사이에서 구조가 같은 layer를 weight까지 합치는 model merging, 메모리가 큰 layer group부터 하나씩 더하는 병합 순서, 공유 layer가 많은 모델을 이웃하게 적재하는 순서(§4, §5.3, §5.4). 비교 기준에서는 round-robin 순서로 돌며 다음 사용이 가장 먼(가장 최근에 실행한) 모델을 내보내는 정책을 이미 썼다(§3.2). 다음 사용 시점에 따른 cache 교체 원리, 모델 단위 cache, prefetch, weight 공유 자체는 신규성으로 주장하지 않는다([09_RELATED_WORK §3](../../design_references/09_RELATED_WORK.md#3-신규성-경계))
- 근거 위치: 내보내기 정책은 §3.2 "Space and time sharing"의 마지막 문단이다(976쪽, PDF 5쪽의 왼쪽 단 끝에서 오른쪽 단 위로 이어진다). 원문은 "the most recently run model (i.e., the one whose next use is in the most distant future) is evicted to make space"다. Frame 19–84%와 정확도 최대 43%는 같은 쪽 오른쪽 단과 Fig. 3, 적재 시간은 Table 1, 병합 heuristic은 §5.3, edge 적재는 §5.4와 부록 A.1, 결과는 §6.1(Fig. 11–13)
- 주의: 이 내보내기 정책은 Nexus 원 논문이 아니라 Gemel 저자가 만든 Nexus 변형에 있다. Nexus에는 epoch 안에서 모델을 내보내는 교체 정책이 없다(B24). PNU-Count를 "다음 사용이 가장 먼 모델을 내보낸다"로만 쓰면 이 기준·RT-Swap과 구별되지 않는다. PNU-Count는 여기에 Host 처리 지연 분포와 n_expect를 더해 다음 사용을 예측한다
- 주의: 60.7%는 parameter 메모리 감소다. 중간값과 framework를 넣은 추론 중 메모리 감소는 4.5–48.1%다(§6.1). 8–39%는 min 메모리에서 LP·MP·HP 중앙값 workload의 정확도 차이다. 비교 대상은 같은 GPU 메모리에서 병합 전 모델을 돌린 Nexus 변형이다. Fig. 3·7·11 범례의 메모리 설정 "25%"는 §2 본문의 50% 설정과 다르게 적혀 있다
- 주의: 이 연구의 모델 40개는 구조가 같고 장비 ID마다 weight가 다르다(01 §2). Gemel 방식이라면 모든 layer가 병합 후보다. 이 연구는 weight를 다시 학습해 합치지 않는다
- 비교군: cache 비교의 offset-only가 같은 원리다(nominal offset으로 다음 사용을 본다). Model merging은 비교군에 없다. 우리 수치는 Xeon에서 잰 모델 그룹 지연을 넣은 simulation 값이다(entry 4). PNU는 j(i, k) 분포를 정확히 안다. 보드 측정은 없다
