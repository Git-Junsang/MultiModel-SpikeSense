# B42: SharedDNN/PlanAhead

원문: `B42_SharedDNN_ASAP2020.pdf`
Hsin-Yu Ting, Tootiya Giyahchi, Ardalan Amiri Sani, Eli Bozorgzadeh(UC Irvine), "Dynamic Sharing in Multi-accelerators of Neural Networks on an FPGA Edge Device", IEEE ASAP 2020, pp. 197–204, DOI 10.1109/ASAP49362.2020.00040
읽은 범위: 원문 전체(8쪽)

## 한 줄 요약

FPGA edge 하나가 end device 여러 대의 주기 request를 받는다. 도착 pattern을 미리 안다고 보고 request(원문의 task)마다 accelerator·slot과 실행 순서를 MILP로 미리 정했다(SharedDNN/PlanAhead). 재구성과 parameter 재적재가 줄어 application마다 slot을 고정한 FCFS보다 평균 speedup이 최대 2.20배였다. B35(Razavi 등, DATE 2022)는 이 정적 일정을 비교 기준 Static으로 쓰고 실행 중 보정을 더했다.

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | Request는 DNN 모델과 dataset·정확도 조건을 담고 accelerator는 지정하지 않는다. Edge가 조건에 맞는 BNN accelerator를 골라 slot에 올린다. 도착 순서대로 처리하면 slot 재구성(partial reconfiguration)과 parameter 재적재가 되풀이된다(§III, §V-C) |
| 방법 1 | 시간 구간 안의 task queue를 graph로 나타낸다. Node는 task와 그 task를 처리할 수 있는 accelerator의 쌍이다. Edge 비용은 같은 slot에서 앞 task 뒤에 이어 실행할 때 드는 재구성·parameter 재적재 시간이다. 같은 accelerator·같은 dataset이 이어지면 둘 다 없다. Slot이 k개면 min-cost k-disjoint path 문제가 된다(§IV-A, Fig. 4) |
| 방법 2 | 이를 MILP로 세워 CPLEX로 푼다. 목적은 slot별 완료 시각의 최댓값을 최소로 하는 것이다. 도착 전 시작 금지, slot 크기, 관련 dataset으로 옮길 때의 정확도, 시간 순서가 필요한 task의 순서를 제약으로 둔다. 나머지 task는 도착 순서와 다르게 실행해도 된다(§IV-B, 식 1–8) |
| 방법 3 | 배포 중에는 runtime task manager가 offline 일정을 그대로 따른다. 예정된 task가 network 때문에 늦으면 그 slot을 멈추고 기다린다(§V-B, §V-C) |
| 가정·조건 | End device는 고정 주기로 request를 보내고 edge에 오는 pattern은 미리 안다고 둔다. Pattern은 경험으로 뽑는다고만 적었다(§III). Xilinx ZCU104, slot 구성 LM·LSS·MMS, slot 재구성 120/105/90 ms(L/M/S). BNN accelerator 9개(CIFAR10·CIFAR3·MNIST, Table II). End device 4대, 무선 router, 합계 60·46.6·30 fps(HIGH·MEDIUM·LOW), application set 4개(Table III). 도착에 30% 무작위 편차를 넣은 합성 benchmark를 100번 돌려 평균했다(§V-B) |

## 결론

- FixedDNN/FCFS(application마다 slot을 고정하고 도착 순서로 실행) 대비 평균 speedup은 LM·HIGH에서 2.20배로 가장 컸다. Application set별로는 set 1에서 최대 2.35배, set 3·4에서 최대 2.49배였다(Fig. 5·6, §V-C)
- SharedDNN/FCFS(slot을 함께 쓰되 도착 순서로 실행)는 시간 대부분을 재구성·재적재에 썼다. PlanAhead는 이 전환 시간을 크게 줄였고 쓴 DNN library를 최대 27% 줄였다(Fig. 7·8, 초록)
- 늦은 task를 기다리느라 slot이 노는 시간이 10–23%였다(§V-C)
- 평가 방식: ZCU104에 올린 system에서 잰 값이다. 입력은 30% 편차를 넣은 합성 benchmark다. End device 4대를 실제 장치로 돌렸는지는 원문에서 분명하지 않다

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| 같은 accelerator·parameter를 쓰는 task를 이어 실행해 재적재를 피한다(§IV-A) | 순서를 offline MILP로 정하고 task를 도착 순서와 다르게 실행한다. 예정 task가 늦으면 slot을 멈추고 기다린다. 이 연구의 Grouping은 실행 중에 이미 도착한 같은 모델 추론 요청만 batch로 묶고 기다리지 않는다 | [구조] 도착 pattern을 미리 풀어 두지 않는다. Grouping과 PNU-Count가 실행 중 queue와 지연 분포로 batch와 weight 교체를 정한다 |
| 주기 source의 도착이 규칙적이라는 점을 이용한다 | 도착 시각은 end device가 정하고 edge는 그 pattern을 관측해 쓴다. 이 연구는 Host가 모델마다 offset을 정해 같은 모델 추론 요청이 함께 생기게 한다 | [구조] 도착을 미리 알아 순서를 짜는 대신 Model-Grouped Offset Assignment로 같은 모델 추론 요청의 생성 시각을 맞춘다 |
| FPGA 하나를 여러 모델이 나눠 쓴다 | 전환 단위가 slot 재구성(90–120 ms)과 parameter 재적재다. Deadline 없이 완료 시각을 줄인다. End device 4대 | [구조] 모델 40개, 트랙 1,024개, 32 ms deadline을 다룬다. 같은 모델 트랙도 membrane potential을 따로 둔다 |

## 인용할 때

- 이 논문이 먼저 한 것: 주기 도착 pattern을 미리 안다는 가정으로 FPGA edge의 accelerator 배정과 실행 순서를 offline에서 최적화하는 것, 같은 accelerator·parameter task를 이어 붙여 재구성·재적재를 줄이는 것. 이 둘 자체는 신규성으로 주장하지 않는다
- B35와의 관계: B35는 이 논문을 [6]으로 인용하고 offline 일정을 그대로 따르는 방식을 비교 기준 Static으로 썼다. B35는 여기에 pattern 추출, Wait command로 송신 시각 맞추기, online scheduler를 더했다. 이 논문의 결론도 network 편차에 맞추는 runtime scheduling을 다음 과제로 적었다(§VI)
- 근거 위치: system 구조 §III(Fig. 3), graph §IV-A(Fig. 4), MILP §IV-B(Table I, 식 1–8), 실험 조건 §V-A·B(Table II·III), 결과 §V-C(Fig. 5–8)
- 주의: speedup이 무엇의 비인지 원문에 식으로 적혀 있지 않다. 초록·서론은 전체 실행 시간 최소화라 쓰고 MILP 목적은 slot별 완료 시각의 최댓값 최소화다. Response time이나 deadline 지표는 없다
- 주의: 도착 시각은 바꾸지 않는다. Accelerator 하나를 여러 dataset 모델이 parameter만 바꿔 함께 쓰는 경우가 있어 원문의 accelerator는 이 연구의 모델과 일대일이 아니다
- 비교군: simulation 비교군에 없다
