# B29: EdgeSync

원문: `B29_EdgeSync_PerComW2025.pdf`, 특허 `P01_NEC_FrameTiming_WO2025106619A1.pdf`
Qiang Xu(Purdue University, NEC Laboratories America 인턴 때 연구), Ravi K. Rajendran, Murugan Sankaradas, Srimat T. Chakradhar(NEC Laboratories America), "EdgeSync: Efficient Edge-Assisted Video Analytics via Network Contention-Aware Scheduling", IEEE PerCom Workshops 2025, pp. 287–292(쪽은 OpenAlex 기준), DOI 10.1109/PerComWorkshops65533.2025.00079
특허: WO2025106619A1(2025-05-22 공개)과 US판 US20250159339A1(2025-05-15 공개), "Optimizing edge-assisted augmented reality devices". 출원인 NEC Laboratories America, 발명자는 논문 저자 네 명, 우선일 2023-11-14. US판은 Google Patents 기준 심사 중이다
읽은 범위: 논문 전체. 특허 PDF는 이미지라 Google Patents의 명세서와 청구항 20개 본문을 읽었다. 특허 문단 번호는 WO판 기준이고 WO PDF 한 쪽(12쪽)과 번호가 같은지 대조했다. 도면은 보지 않았다

## 한 줄 요약

Edge server가 UE(단말)를 group으로 나누고 같은 group의 frame 촬영 시각은 맞추고 group끼리는 고르게 벌리도록 UE camera의 촬영 시각을 1 ms씩 옮기게 한다. 4G LTE private cellular testbed에서 UE 7대의 추론 요청 93% 이상을 SLO 안에 처리했고 비교 방식은 65–85%였다(초록, §VII-B).

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | batch를 만들려면 먼저 온 추론 요청이 뒤에 올 추론 요청을 기다린다. 모든 UE가 한꺼번에 보내면 network 대역 경합으로 frame 전송이 길어진다(§IV-B) |
| 방법 | 같은 group의 촬영 시각은 맞추고 group끼리는 고르게 벌려 기다리는 시간과 전송 시간 사이의 균형을 잡는다(§IV-B, Fig. 1c). Group 사이 간격을 정하는 식은 원문에 없다 |
| 방법 | group 크기(offline profiler): UE 수와 group 크기의 조합마다 group 수를 ⌈UE 수 / group 크기⌉로 둔다. 그렇게 맞추고 벌린 추론 요청을 batched inference engine에 넣어 request drop rate와 추론 시간을 잰다. UE 수마다 가장 좋은 group 크기를 저장한다(§VI-A, Alg. 1) |
| 방법 | group 기준은 UE 수와 group 크기뿐이고 모델 종류로 나누지 않는다. 특허는 profile 요인을 UE 수와 "선택한 DNN 모델의 batch 크기"로 적었다([0031]). 어느 UE가 어느 자리에 드는지는 다음 행의 배정이 정한다(§VI-B) |
| 방법 | 재배정(alignment planner): UE가 들어오거나 나가면 자리를 옮길 때 드는 촬영 시각 변화로 cost matrix를 만든다. Hungarian algorithm으로 변화의 합이 가장 작게 UE를 배정한다(§VI-B, Eq. 1–3, 특허 청구항 4·5). 변화량의 최소·최대 한도를 지킨다(청구항 6) |
| 방법 | 촬영 시각 옮기기(frame timing controller): k ms를 옮기라는 지시를 받으면 다음 k개 frame의 촬영 시각을 1 ms씩 늦추거나 당긴다. 변화는 대개 10 ms 미만이라 약 10 frame, 167 ms 안에 끝난다(§VI-C, Alg. 2, 특허 [0070]·청구항 7) |
| 방법 | 재계획 시점(논문): UE가 들어오거나 나갈 때 다시 계획한다(§V, §VI-B). §V는 시스템을 계속 감시해 맞춘다고 적었지만 주기는 없다 |
| 방법 | 재계획 시점(특허): performance monitor가 주기적으로 통계를 내고 추론 요청이 처리되지 못하는 UE가 있으면 planner를 다시 부른다([0108]). Latency SLO가 85 ms일 때 86 ms가 걸린 추론 요청이면 촬영 시각을 고칠 수 있다([0050]). 주기 값은 없다 |
| 가정·조건 | SLO를 지킬 수 없을 만큼 오래 밀린 추론 요청은 버린다. Request drop rate는 그 비율이다(§IV-A) |
| 가정·조건 | 시계: server와 UE는 chrony로 시계를 맞추고 오차는 대개 1 ms 미만이다. 원문은 이것을 UE의 frame 준비 시각과 server 수신 시각 사이를 재는 데 쓴다고 적었다(§VII-A). 특허에는 시계 동기 방법이 없다 |
| 가정·조건 | 모델은 DETR(ResNet-101 backbone, TensorRT) 하나다. Edge server 하나(x86 CPU, Nvidia 2070 GPU)와 라즈베리파이 4B(HD camera, JPEG 압축) 8대를 Celona 4G LTE로 연결했고 실험은 UE 1–7대다(§VII-A, Fig. 3). 모든 실험에서 server 부하는 처리 용량을 넘지 않았다 |
| 가정·조건 | weight·메모리 전송과 모델 적재는 다루지 않는다. 모델 caching은 edge orchestration의 예로 한 번 나올 뿐이다(§V) |

## 결론

- Fig. 1의 UE 4대, SLO 85 ms: SLO 위반이 모두 함께(Fig. 1a) 30%, 고르게 벌림(Fig. 1b) 13.5%, 2대씩 group(Fig. 1c) 6.7%였다. 모두 함께 보내면 대역 경합으로 frame 전송이 길어졌다. 고르게 벌리면 batch를 기다리는 시간이 길어졌다(§IV-B)
- UE 1–7대: UE 수가 늘어도 EdgeSync의 request drop rate가 가장 낮았다. 7대에서 추론 요청 93% 이상을 SLO 안에 처리했고 Random, Spaced out, All together는 65–85%였다(초록, §I, Fig. 4)
- UE 수를 20초마다 4대에서 7대로 늘렸다가 다시 줄여도 UE가 새 계획을 따라갔다(Fig. 5). UE 7대에서 SLO를 100–150 ms로 바꿔도 EdgeSync의 request drop rate가 가장 낮았다(Fig. 6)
- 평가 방식: 실측(Celona 4G LTE testbed, §VII-A). EdgeSync 결과는 초록의 93%·65–85%만 글로 적혀 있고 Fig. 4–6의 막대 값은 없다

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| 주기 입력이 생기는 시각을 group 단위로 정한다. 같은 group은 맞추고 group끼리는 고르게 벌려 같은 group 추론 요청이 함께 도착한다(§IV-B, Alg. 1). 이 연구에서 모델끼리 0.8 ms씩 벌리는 것도 같은 모양이다 | EdgeSync의 group은 profile로 고른 크기만큼 UE를 모은 것이고 모델과 무관하다. 평가 모델은 하나다. 이 연구는 같은 모델을 쓰는 트랙이 한 group이고 group 크기는 그 모델의 트랙 수다 | [구조] 같은 모델 추론 요청이 함께 생겨 Grouping이 weight 적재 한 번으로 처리한다. EdgeSync는 weight·메모리 전송을 다루지 않는다 |
| | EdgeSync는 UE 수가 바뀌면 server가 다시 계획한다(§VI-B). 특허는 SLO 위반과 처리되지 못한 추론 요청도 재계획 계기로 적었다([0050]·[0108]). UE는 camera 촬영 시각을 1 ms씩 옮긴다(§VI-C). 이 연구의 offset은 `O_m = m × 0.8 ms`로 고정이다. Host는 mic를 제어하지 않고 mic stream에서 frame을 자르는 시각만 정한다 | [구조] 트랙이 늘거나 줄어도 모델의 offset이 그대로라 다시 배정하지 않는다. Mic 제어와 FPGA에서 Host로 돌려주는 제어 신호가 필요 없다 |
| 같은 group 추론 요청을 batch로 처리한다 | EdgeSync는 batch 추론을 시작하려면 여러 UE의 추론 요청이 도착해야 해서 먼저 온 추론 요청이 기다린다고 적었다(§IV-B). Batch 크기는 adaptive batching으로 정한다(§I, 특허 [0108]). 이 연구의 Grouping은 이미 도착한 같은 모델 추론 요청만 묶는다 | [구조] batch를 채우려고 기다리는 시간이 response time에 더해지지 않는다 |
| 비교 조건이 대응한다. Random(촬영 시각 제어 없음)은 unaligned의 무작위 offset 시나리오(uniform 등), All together(모든 UE가 같은 시각)는 global alignment와 unaligned의 동시 시작 시나리오(synchronized, skewed-synchronized), EdgeSync는 Model-Grouped Offset Assignment에 해당한다. Spaced out(UE마다 고르게 벌림)에 해당하는 조건은 없다 | EdgeSync의 지표는 network 지연을 넣은 request drop rate다. 이 연구의 지표는 DDR3 traffic과 response time이고 링크는 Gigabit Ethernet UDP, 즉시 송신이다. 링크 경합은 평가하지 않았다 | [실험] 같은 PNU-Count에서 J = 0.8 ms이면 제안의 DDR3 traffic이 global alignment보다 약 14% 적다(간이 시험). EdgeSync 자체와는 비교하지 않았다 |

## 인용할 때

- 이 논문과 특허가 먼저 한 것: UE를 group으로 나눠 같은 group의 촬영 시각은 맞추고 group끼리는 고르게 벌리는 방식(§IV-B, Fig. 1c, Alg. 1, 특허 [0032]). Server가 정한 촬영 시각을 UE camera에 적용해 같은 group 추론 요청이 함께 도착하게 하고 batch를 만드는 방법(§VI-B·C, Alg. 2, 특허 청구항 1·7). 이 두 가지는 신규성으로 주장하지 않는다. 같은 시각 도착으로 batch 만들기 자체와 주기 작업의 생성 시각에 간격 두기 자체도 마찬가지다([09_RELATED_WORK §3](../../design_references/09_RELATED_WORK.md#3-신규성-경계))
- 우리가 주장할 수 있는 범위는 group 기준을 모델로 삼아 weight 재사용을 만드는 것과, feedback 없는 고정 offset을 기다리지 않는 Grouping·PNU-Count weight cache와 결합한 것이다
- 근거 위치: 세 방식 비교 §IV-B·Fig. 1, group 크기 profile §VI-A·Alg. 1, 재배정 §VI-B·Eq. 1–3, 1 ms 조정 §VI-C·Alg. 2, chrony·비교 조건 §VII-A, 결과 §VII-B·Fig. 4–6. 특허는 group 정의 [0031]·[0032], SLO 기준 수정 [0050], Hungarian [0053]–[0059], 1 ms 조정 [0070]·청구항 7, 주기 점검 [0108]
- 주의: group을 모델로 나눈다는 문장은 논문과 특허에 없다. 특허는 추론 요청 packet에 실행할 task를 싣고([0098]) task별 최적 batch 크기로 묶는다고만 적었다([0108]). 식의 G를 "DNN 모델의 group 크기"라고 불러서(§VI-B, [0059]) 모델별 group으로 읽히기 쉽다
- 주의: 특허 청구항 1은 촬영 시각 profile, SLO 지표로 추론 요청 분석, 촬영 시각 변화의 합을 줄이는 계획, response packet으로 camera 촬영 시각 조정을 모두 담는다. Testbed는 4G LTE인데 Fig. 2와 색인어는 5G로 적었다. 결론(§VIII)의 energy 감소는 평가하지 않았다
- 주의: All together에 해당하는 조건에서는 이 연구의 이득이 작다. 같은 PNU-Count에서 global alignment와 제안은 J = 0이면 거의 같다(6.34 대 6.36 KiB/추론). Unaligned가 동시 시작인 synchronized·skewed-synchronized 시나리오에서는 Dysta Method 대비 감소폭도 8.5%, 12.1%다. 우리 수치는 Xeon에서 잰 모델 그룹 지연을 넣은 simulation 값이고 보드 측정은 없다
- 비교군: EdgeSync 자체는 simulation 비교군에 없다. 비교 조건의 대응은 위 표의 마지막 행에 있다
