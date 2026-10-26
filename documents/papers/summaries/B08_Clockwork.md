# B08: Clockwork

원문: `B08_Clockwork_OSDI2020.pdf`
Arpan Gujarati, Reza Karimi, Safya Alzayat, Wei Hao, Antoine Kaufmann, Ymir Vigfusson, Jonathan Mace, OSDI 2020, DOI 확인 못 함(받은 PDF는 INDEX 기준 arXiv 2006.02464 판이라 학회 표기·쪽수·DOI가 없다)
읽은 범위: 원문 전체

## 한 줄 요약

DNN 추론의 실행 시간이 거의 일정하다는 점을 이용해 모델 적재와 실행 결정을 모두 중앙 controller에 모은 model serving system이다. GPU 서버 12대에서 모델 4,026개를 번갈아 올리면서 100 ms SLO를 넘긴 추론 요청이 없었다.

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | 많은 모델이 GPU를 나눠 쓰면서 추론 요청마다 낮은 SLO를 지켜야 한다 |
| 방법 | worker는 GPU에서 EXEC를 한 번에 하나만 돌린다. LOAD·UNLOAD·INFER는 controller가 준 시간 창(earliest, latest) 안에서만 시작하고 창을 놓친 action은 취소한다(§4.4) |
| 방법 | GPU 메모리를 모델 cache(16 MB page)로 쓴다. LOAD할 모델은 모델별 미처리 수요로 만든 우선순위로 고르고 UNLOAD할 모델은 LRU로 고른다(§4.4, §5.2, §5.3) |
| 방법 | 같은 모델 추론 요청을 batch(크기 1, 2, 4, 8, 16)로 묶는다. latest는 deadline에서 batch 실행 시간을 뺀 값이다. SLO를 못 맞출 추론 요청은 실행 전에 취소한다(§4.1 Fig. 4, §5.3) |
| 가정·조건 | GPU 서버(V100 32 GB). 추론 요청마다 SLO가 있고 도착에 주기 가정이 없다(§8). 실행 시간은 최근 측정값으로 예측한다(§5.3) |

## 결론

- MAF trace 6시간, worker 12개, 모델 4,026개(61종 × 66), SLO 100 ms: 평균 9,638 r/s를 처리했다. 추론 요청 2억 800만 개 중 58개만 action 시간 예측이 틀려 실패했다. 100 ms를 넘은 추론 요청은 없었다(§6.5, Fig. 9)
- 시간 예측 오차의 99번째 백분위는 INFER가 과대 예측 144 µs, 과소 예측 55 µs이고 LOAD가 431 µs, 348 µs다(§6.5, Fig. 10)
- GPU 1개에 ResNet50 15개를 올린 비교에서 Clipper와 INFaaS는 SLO 100 ms 아래에서 goodput이 무너졌고 Clockwork만 유지했다. INFaaS는 EC2에서 돌려 조건이 같지 않다(§6.1, Fig. 5)
- 평가 방식: 실측(Dell R740 12대, 서버마다 V100 32 GB 2개). Controller 확장성(§6.6)만 emulated worker로 쟀다

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| 가속기 쪽 메모리(GPU 메모리, BRAM)를 모델 단위 cache로 쓴다 | Clockwork는 UNLOAD 대상을 LRU로 고른다. 이 연구는 PNU-Count로 다음 사용이 가장 늦은 모델을 내보낸다 | [실험] 같은 Model-Grouped Offset Assignment·Grouping에서 교체 정책만 바꾸면 J = 0.8 / 1.6 / 3.2 ms에서 LRU 6.70 / 6.71 / 16.01, PNU-Count 6.38 / 6.56 / 12.37 KiB/추론이다 |
| 같은 모델 추론 요청을 batch로 묶는다 | Clockwork는 도착 시각을 바꾸지 않는다. 추론 요청 하나가 독립된 작업 단위다(§7). 이 연구는 트랙마다 membrane potential을 따로 둔다 | [구조] Host가 같은 모델 트랙에 같은 offset을 줘 같은 모델 추론 요청이 함께 생긴다(Model-Grouped Offset Assignment) |

## 인용할 때

- Clockwork가 먼저 했다: GPU 메모리를 모델 단위 cache로 쓰고 LRU로 내보내기, 측정 기반 시간 예측으로 짠 중앙 schedule, 못 맞출 추론 요청 취소, 같은 모델의 묶음 처리. 모델 단위 cache와 같은 모델의 묶음 처리 자체는 신규성으로 주장하지 않는다(09 §3)
- 근거 위치: LRU는 §5.3 "Scheduling LOAD" 끝 문장, 취소는 §4.1 Fig. 4 ④와 §4.4, batch와 latest 계산은 §5.3 "Scheduling INFER", 실행 시간이 일정하다는 관찰은 §2 Fig. 2
- 주의: LRU는 UNLOAD 대상을 고를 때만 쓴다. 무엇을 LOAD할지는 수요 기반 우선순위로 정한다. Clockwork는 workload에 미리 가정을 두지 않고 worst case 보장도 하지 않는다(§8)
- 비교군: 지금 cache 비교의 LRU 조건이 Clockwork의 UNLOAD 규칙과 같다. P3.11 §3.1에서는 scheduler 비교군 Clockwork Method로 옮겼다
- 우리 수치는 Xeon에서 잰 모델 그룹 지연을 넣은 simulation 값이다(entry 4). PNU는 j(i, k) 분포를 정확히 안다. 보드 측정은 없다
