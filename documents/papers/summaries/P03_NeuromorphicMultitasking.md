# P03: Neuromorphic Multitasking

원문: `P03_Intel_NeuromorphicMultitasking_EP3547227A1.pdf`
출원인 Intel Corporation, 발명자 Seth Pugsley, Berkin Akin, 공개 번호 EP 3 547 227 A1(2019-10-02), 우선일 2018-03-27(US 15/937,486), 등록일 2024-08-21(EP 3 547 227 B1, Google Patents 기준)
읽은 범위: 청구항 15개, 요약, [0001]–[0092](FIG. 1–9). [0093] 이후(FIG. 10–20의 일반 processor 구조와 Examples)는 읽지 않았다

## 한 줄 요약

Axon processor에 둔 NATU가 spike message의 physical neuron ID(PNID)를 network ID(NID)와 network 안 neuron ID(LNID)로 바꿔 여러 SNN을 한 neuromorphic 가속기에서 섞이지 않게 함께 돌리는 특허다. 같은 SNN을 복제할 때는 neuron state만 새로 두고 synapse 데이터는 공유한다. 실험은 없다.

## 설계

| 항목 | 내용 |
|---|---|
| 문제 | SNN은 spike가 드물어 hardware가 자주 논다. 여러 SNN을 같은 hardware에 올리면 neuron 주소가 겹친다([0008], [0060]) |
| 방법 | 청구항 1 요지: NATC(명세서의 NATU)가 spike를 낸 neuron의 PNID가 든 spike message를 받는다. PNID를 NID와 LNID로 바꾸고 NID로 synapse 데이터를 찾아 synapse 데이터와 LNID를 axon processor에 넘긴다(청구항 1) |
| 방법 | NATU 표는 network마다 NID, PNID 범위(begin, end), synapse 메모리 범위(begin, end)를 둔다. LNID = PNID − PNID_begin이고 반대 방향은 PNID_begin을 더한다. Synapse list가 LNID로 적혀 있어 network마다 자기 neuron만 가리킨다([0045], [0063]–[0071], FIG. 6A·6B·7) |
| 방법 | 복제: neuron state를 NSM의 다른 영역으로 복사하고(무작위 값으로 초기화해도 된다) 새 NID 항목을 만들되 synapse pointer는 원래 network와 같게 둔다. 두 network는 neuron state를 따로 갖고 synapse를 공유한다(청구항 10·11, [0052]·[0053], [0076]–[0078], FIG. 8A–8C) |
| 가정·조건 | neuron state는 neuron processor 옆 SRAM(NSM)에, synapse 데이터는 외부 메모리(HBM, HMC, DDRx-SDRAM 등)에 둔다. Synapse 데이터가 몇 자릿수 크고 접근 국소성이 달라서다([0020], [0027]–[0029], [0037], [0040]). Time step 단위 event 처리다. Work item 순서는 FCFS나 QoS 방식 등 아무것이나 쓴다([0061], [0072]). 원문에 주기와 deadline이 나오지 않는다 |

## 결론

- 명세서가 밝힌 효과: SNN을 따로 설계하지 않아도 여러 SNN을 함께 돌려 hardware 이용률을 높인다([0008], [0062]). 복제 network는 synapse 메모리 공간을 늘리지 않고 같은 시각에 다른 입력을 처리한다([0054]). 한 복제가 학습(STDP)으로 바꾼 synapse를 다른 복제가 바로 쓴다([0055], [0082])
- 실험, simulation, 수치가 없다
- 평가 방식: 없음(특허 명세서)

## 이 연구와 비교

| 같은 점 | 다른 점 | 이 연구가 나은 점 |
|---|---|---|
| 같은 모델을 여러 입력에 쓰면서 state는 입력마다 따로 두고 weight(synapse)는 한 벌만 둔다 | Intel은 복제마다 NID와 neuron 메모리 영역을 새로 만들고 synapse pointer를 같게 둔다([0052], [0078]). 이 연구는 트랙마다 membrane potential을 따로 두고 같은 모델을 쓰는 트랙들이 weight 한 벌을 쓴다 | [구조] Intel의 공유는 synapse 메모리 공간을 아낀다([0054]). 복제들이 외부 메모리에서 synapse를 한 번 읽어 함께 쓰는지는 적지 않았다([0080]). 이 연구는 Model-Grouped Offset Assignment와 Grouping으로 같은 모델 추론 요청을 weight 적재 한 번에 처리해 DDR3 traffic을 줄인다 |
| state는 on-chip에, weight는 off-chip DRAM에 둔다 | Intel은 neuron state를 모두 on-chip SRAM에 두고 spike를 낸 neuron의 synapse를 time step마다 외부 메모리에서 읽는다([0028], [0031], [0034]). 이 연구는 weight 4.97 MiB를 DDR3에 두고 BRAM entry 4개에 모델 단위로 올린다. Membrane potential은 12 bit로 저장해 768트랙의 state를 남는 BRAM에 둔다 | [구조] PNU-Count가 entry에 둘 모델을 다음 사용 예측으로 고른다. 12 bit Membrane Storage로 state 자리를 줄인다. Intel 명세서는 NPU 연산을 16 bit 같은 낮은 정밀도로 예시할 뿐 저장 정밀도를 다루지 않는다([0039]) |
| 여러 모델을 한 가속기에서 돌린다 | Intel은 NID로 network를 격리하고 event가 오는 대로 처리한다. 원문에 주기와 deadline이 없다 | 없음. 이 연구는 network 격리 방법을 다루지 않는다 |

## 인용할 때

- Intel(Pugsley·Akin)이 먼저 했다: network ID로 여러 SNN을 한 neuromorphic 가속기에서 함께 돌리는 것, SNN을 복제하며 neuron state는 따로 두고 synapse 데이터를 공유하는 것, neuron state는 on-chip SRAM에, synapse 데이터는 외부 DRAM에 나눠 두는 것. On-chip state와 off-chip weight 배치 자체는 신규성으로 주장하지 않는다(09 §3). 같은 모델 트랙이 weight를 함께 쓰고 membrane potential을 따로 두는 구조도 이 특허의 복제에 이미 있다
- 근거 위치: NID 다중 실행은 청구항 1–4, [0008], [0032], [0043]–[0048], [0060]–[0074], FIG. 6A·6B·7·9. 복제는 청구항 10–13, [0009], [0051]–[0055], [0075]–[0082], FIG. 8A–8C. On-chip SRAM·외부 DRAM은 [0005], [0020], [0027]–[0029], [0037], [0040], FIG. 3·4A·4B
- 주의: 받은 PDF는 출원 공개본(A1)이다. 등록본(B1)과 같은 우선권의 미국 등록본 US 11,366,998 B2(2022-06-21, Google Patents 기준)의 청구항은 읽지 않았다
- 주의: 복제의 주 용도는 synapse를 공유하며 여러 입력으로 함께 학습하는 것과 network가 쉬는 시간을 다른 입력 처리로 메우는 것이다([0055], [0082]). 이용률 향상은 기대 효과이고 잰 값이 아니다
- 비교군: 옮기지 않았다
