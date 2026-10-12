# 선행연구

원문 목록은 [papers/INDEX.md](../papers/INDEX.md), 개별 해설은 [papers/summaries/](../papers/summaries/)에 있다.

## 1. 결론

관련 연구는 네 그룹으로 나뉜다.

| 그룹 | 다루는 문제 | 빠진 문제 |
|---|---|---|
| SNN accelerator | sparsity, dataflow, memory hierarchy | 다중 model scheduling, deadline |
| Multi-DNN scheduler | multi-tenant, deadline, fairness | SNN membrane state |
| Weight streaming | on-chip/off-chip 배치, prefetch | 비동기 다중 model 요청 |
| Multi-model SNN simulator | 여러 neuron model, multi-FPGA | DRAM cache와 deadline scheduler |

`다중 학습 모델 × 다수 센서 트랙 × 주기적 32 ms deadline × SNN`을 함께 다룬 연구는 찾지 못했다.

다만 다음 요소는 이미 알려진 기법이다.

- SNN이 memory-bound라는 관찰
- off-chip weight와 on-chip cache
- weight streaming과 prefetch
- timestep 사이 weight reuse
- membrane state의 memory pressure
- deadline-aware scheduling과 dynamic batching

따라서 신규성은 이 요소 자체가 아니라, **모델 단위 weight 전송 비용과 track deadline을 함께 반영하는 scheduler**에 둔다.

## 2. 가장 가까운 연구

### 2.1 Minitaur

Minitaur는 DDR2에 SNN weight와 state를 두고, FPGA core마다 cache를 둔다. SNN weight의 off-chip 저장과 cache는 2014년에 이미 제안됐다.

차이:

- Minitaur는 단일 network다.
- cache locality는 한 network 안의 neuron locality다.
- model switch와 model 단위 cache 교체가 없다.
- application deadline scheduler가 없다.

이 연구에서는 cache 단위가 학습된 모델이다. 같은 모델을 쓰는 여러 track을 묶는 것이 핵심이다.

### 2.2 SpikeX와 SpinalFlow

SpikeX는 off-chip RAM, global buffer, double-buffer L1의 3단 memory hierarchy를 쓴다. SpinalFlow는 timestep과 membrane state를 포함한 SNN dataflow를 다룬다.

두 연구 모두 단일 모델을 기준으로 한다. 모델 전환과 multi-tenant deadline은 다루지 않는다. 이들의 buffer와 reuse 방법은 설계 참고 자료로 쓴다.

### 2.3 A16: Identifying Efficient Dataflows for SNNs

A16은 membrane potential이 SNN 전용 state이며, weight와 on-chip memory를 나눠 쓴다는 점을 정리했다.

이 연구에서는 membrane state가 track 수 N에 따라 늘어난다. N=512에서 706 KiB다. 따라서 model cache와 track state의 공간 배분이 scheduler 성능에도 영향을 준다.

### 2.4 Sparse-DySta

Sparse-DySta는 multi-DNN workload에서 남은 실행 시간과 deadline slack으로 순서를 바꾼다. violation rate를 핵심 지표로 쓴다.

차이:

- ANN 대상이다.
- model weight가 이미 준비돼 있다고 본다.
- sparsity로 실행 시간을 갱신한다.
- 주기적 hard deadline이 아니다.

이 연구는 sparsity 대신 남은 weight transfer, cache state, compute를 비용에 넣는다.

### 2.5 AutoWS

AutoWS는 layer별 weight를 on-chip에 둘지 stream할지 자동으로 고른다. 단일 모델과 정적 schedule을 가정한다.

부분 상주와 streaming 비교 방법은 참고할 수 있다. 비동기 요청에서 어느 모델을 먼저 처리할지는 별도 문제다.

## 3. SNAVA 확인

SNAVA 제목에는 `real-time`, `multi-model`, `SNN`이 들어간다. 원문을 확인한 결과 이 연구와 용어 뜻이 다르다.

| 용어 | SNAVA | 이 연구 |
|---|---|---|
| multi-model | LIF, Izhikevich 등 neuron model | 학습된 weight instance 40개 |
| real-time | 생물학적 1 ms timestep | 요청 생성 뒤 32 ms deadline |
| virtualization | PE가 virtual neuron 시분할 | compute array가 track 시분할 |

SNAVA는 weight와 state를 모두 on-chip BRAM에 둔다. model cache, DRAM streaming, deadline scheduler가 없다.

단일 FPGA 결과:

| 구현 | 뉴런 | Synapse | FPGA |
|---|---:|---:|---|
| SNAVA | 12,800 | 20,000 | Kintex-7 XC7K325T |
| Minitaur | 65,536 | 16,780,000 | Spartan-6 XC6SLX150 |
| Bluehive | 64,000 | 64,000,000 | Stratix IV |

SNAVA는 경쟁 연구라기보다 on-chip-only 방식의 규모 한계를 보여 주는 근거다.

## 4. 분야별 정리

### 4.1 SNN accelerator

| 연구 | 참고할 점 | 이 연구와 차이 |
|---|---|---|
| FeNN-DMA | DMA 기반 off-chip weight | 단일 network |
| Minitaur | DDR2 + weight/state cache | model scheduling 없음 |
| SpinalFlow | timestep reuse | 단일 모델 |
| SpikeX | 3단 memory hierarchy | model switch 없음 |
| LoAS | spike·weight sparsity | orthogonal optimization |
| A16 | membrane-aware dataflow | multi-tenant 없음 |
| A18 | on-chip state, off-chip synapse | simulation 목적 |

### 4.2 Multi-DNN scheduler

| 연구 | 참고할 점 | 이 연구와 차이 |
|---|---|---|
| Sparse-DySta | violation rate, dynamic cost | ANN, soft real-time |
| Terastal | EDF 비교, deadline 평가 | heterogeneous accelerator mapping |
| IsoSched | tile-level preemption | SNN state save 비용 없음 |
| THEMIS·FairFirm | fairness | miss 0 목표와 다름 |

### 4.3 Weight streaming

| 연구 | 참고할 점 | 이 연구와 차이 |
|---|---|---|
| AutoWS | 부분 상주 탐색 | 단일 모델, 정적 schedule |
| PRESERVE | prefetch overlap | LLM serving |
| Tessera | high-rate streaming | UMA edge accelerator |

## 5. 신규성 경계

주장할 수 있는 범위:

1. scheduler가 model weight fetch와 deadline을 함께 본다.
2. cache locality의 단위가 model ID다.
3. 같은 모델의 여러 track을 Channel Window로 묶는다.
4. track 수에 따라 늘어나는 membrane state와 model cache를 같은 BRAM에서 비교한다.
5. periodic hard deadline에서 transfer byte와 miss rate를 함께 평가한다.

주장하면 안 되는 범위:

- off-chip weight + on-chip cache 자체
- 부분 상주, prefetch, double buffer 자체
- SNN의 timestep reuse 자체
- membrane state가 memory를 많이 쓴다는 관찰 자체
- slack을 이용한 delayed batching 자체

SlackBatch의 기여는 delayed batching을 처음 제안했다는 것이 아니다. **SNN model transfer와 track state 비용을 deadline guard에 넣고, 같은 deadline 조건에서 DRAM byte를 비교한 것**으로 한정한다.

## 6. 남은 조사

- SpinalFlow, SpikeX, Sparse-DySta의 forward citation 확인
- `multi-tenant SNN`, `deadline-aware SNN accelerator`, `model caching FPGA` 재검색
- 설비별 personalized model의 산업 적용 근거 확보
- LazyBatching, NVIDIA Triton dynamic batching, Clipper 원문 확보

수집한 39편의 파일명과 출처는 [papers/INDEX.md](../papers/INDEX.md)에 있다.
