# 선행연구 조사

**대상 주제**: 다중 모델·다중 트랙 실시간 SNN 추론 가속기 (효율적 메모리 접근)

조사일: 2026-09-09 (rev.3 — 구독 문헌 6편 확보) | 수집 논문 **39편** → [papers/](papers/)

> **조사 범위.** 최대 위험 문헌이었던 **SNAVA는 원문 확보 후 판정 완료(§2 — 충돌 없음)**. ACM DL·ScienceDirect·Springer 구독 문헌도 확보했다. 미확보 3편은 §6 참조.

---

## 1. 요약 — 네 갈래와 빈 자리

| 갈래 | 무엇을 다루나 | 무엇을 안 다루나 |
|---|---|---|
| **A. SNN 가속기** | 스파이크 희소성, 데이터플로우, 메모리 계층 | 단일 모델 전제. 다중 테넌시·데드라인 없음 |
| **B. 다중 DNN 스케줄링** | 다중 테넌트, 데드라인, 공정성 | 전부 ANN. SNN의 시간축 상태(막전위) 없음 |
| **C. 가중치 스트리밍** | 온칩/오프칩 가중치 관리, 프리페치 | 단일 모델, 정적 스케줄 |
| **D. 다중 모델 SNN 시뮬레이터** | 뉴런 모델 프로그래머빌리티, 다중 FPGA 확장 | **전량 온칩 BRAM.** 오프칩 계층·스케줄링 없음 |

**빈 자리**: *(다중 모델 DRAM 상주) × (다수 동시 트랙) × (주기적 하드 데드라인) × (SNN)* 을 동시에 다루는 연구를 찾지 못했다.

---

## 2. SNAVA 정밀 분석 — **충돌하지 않음 (판정 완료)**

> Sripad et al., *SNAVA—A real-time multi-FPGA multi-model spiking neural network simulation architecture*, Neural Networks 97 (2018) 28–45. Universitat Politècnica de Catalunya.
> 원문 확보: `papers/D00_SNAVA_multimodel_SNN.pdf` (18p)

제목에 real-time + multi-model + SNN이 모두 들어 있어 최대 위험 문헌으로 분류했으나, **원문 확인 결과 용어가 다른 것을 가리킨다.**

### 2.1 용어의 실제 의미

| 용어 | SNAVA에서의 의미 | 본 제안에서의 의미 |
|---|---|---|
| **multi-model** | **뉴런 모델**의 프로그래머빌리티 — LIF / Izhikevich / Iglesias-Villa / Synfire chain을 같은 SIMD 어레이에서 실행. 커스텀 ISA로 알고리즘을 바꿔 끼움 | **학습된 네트워크 인스턴스** M개를 동시 서빙. 설비별 개인화 가중치 |
| **real-time** | **생물학적 1 ms 타임스텝**을 놓치지 않는 것 (뉴런 시간해상도 추종) | **응용 하드 데드라인 32 ms.** 위반 = 탐지 누락 |
| **virtualization** | PE 하나가 가상뉴런 128개를 시분할 | 데이터패스 1벌이 트랙 N개를 시분할 (개념은 유사) |

### 2.2 메모리 구조 — 결정적 차이

SNAVA는 **오프칩 DRAM을 전혀 쓰지 않는다.** 논문 §3의 세 가지 설계 축 중 두 번째:

> "A **distributed memory system** has been implemented... The memory system allows accessing the memory in **each processor by spending a single clock cycle**. Putting into practice of such a system was possible since modern FPGAs have **thousands of Blocks of RAM** integrated in them."

PE마다 Synaptic BRAM + Neural BRAM + CAM을 두고 전량 온칩에서 해결한다. **모델 캐시도, 가중치 스트리밍도, 메모리 스케줄링도 존재하지 않는다.** 본 제안의 문제(모델이 온칩에 안 들어감)가 아예 발생하지 않는 설계다.

### 2.3 규모 — 오히려 본 제안을 뒷받침하는 근거

논문 Table 2 (단일 FPGA 기준):

| 구현 | 뉴런 | 시냅스 | 디바이스 |
|---|---|---|---|
| **SNAVA** | 12,800 (가상) | **20,000** | Kintex-7 XC7K325T |
| Minitaur | 65,536 | 16,780,000 | Spartan-6 XC6SLX150 |
| Bluehive | 64,000 | 64,000,000 | Altera Stratix IV |

**SNAVA는 XC7A200T보다 큰 Kintex-7 325T를 쓰고도 시냅스 20,000개에서 멈춘다.** 온칩 BRAM만 쓰기 때문이다. 본 제안은 DDR3 1GB에 **39.2M 시냅스(512모델 × 130,560 × 2)** 를 두고 캐시 계층으로 접근한다. 규모가 3자리수 차이 난다.

> **활용 방향**: SNAVA를 경쟁 문헌이 아니라 **motivation 근거로 인용**한다 — "다중 모델 SNN을 온칩 BRAM만으로 구현하면 단일 보드당 시냅스 2만 개에서 막힌다(SNAVA). 개인화 모델을 수백 개 서빙하려면 오프칩 메모리 계층이 불가피하다."

### 2.4 그 밖의 차이

| 축 | SNAVA | 본 제안 |
|---|---|---|
| 목적 | 신경과학 시뮬레이션·프로토타이핑 도구 | 산업 이상탐지 추론 가속기 |
| 스케줄링 | 없음 (동기 SIMD, 고정 사이클 수) | **재사용↔데드라인 최적화가 핵심 기여** |
| 확장 방식 | 다중 FPGA 링 (최대 127보드) | 단일 보드 + DRAM 계층 |
| 데드라인 위반 개념 | 없음 | 핵심 평가 지표 |
| 응용 | Synfire chain, STDP 실험 | 다채널 설비 이상음 8-class 진단 |
| 학습 | STDP 온칩 지원 | 추론 전용 (학습은 호스트) |

**결론: 차별화 지점을 다시 잡을 필요 없음.** 제안의 축은 그대로 유지한다.

### 2.5 SNAVA에서 가져올 것

- **AER 기반 스파이크 분배**(Dorta et al. 2016, 링 토폴로지) — 다중 보드 확장 시 참고
- 성능 모델링 방식: `NT = K1·N·NV + K2·NV + K3·S + NF·NCHIPS` 형태의 사이클 수 해석식. 본 제안도 유사한 해석 모델을 세워 실측과 대조하면 좋다
- 16-bit 고정소수점 정밀도 분석 방법론 (v(t) 7 decimal bits 등)
- CPU/GPU 대비 벤치마크 구성 (Table 1: 1.78 ms vs GPU 6.96 ms vs CPU 230 ms) — 본 제안의 §7.2 비교군 설계 참고

---

## 3. 갈래 A — SNN 가속기와 메모리

### 3.1 핵심 전제를 뒷받침하는 문헌

**FeNN-DMA (2026, Univ. of Sussex)** — `papers/A05_FeNN_DMA_RISCV_SNN.pdf`
> "SNNs have a **much lower arithmetic intensity** than ANNs and are therefore not well-matched to standard accelerators like GPUs and TPUs. **FPGAs are designed for such memory-bound workloads.**"

본 제안의 전제를 명시적으로 진술한 최신 문헌. RISC-V SoC에 DMA를 붙여 오프칩에서 가중치를 스트리밍하며 코어당 16K 뉴런 / **256M 시냅스**를 시뮬레이션한다.

- **활용**: 제안서 배경 절에 직접 인용
- **차이**: 프로그래머블 SoC, 한 번에 하나의 네트워크. 다중 테넌시·데드라인 없음

**Minitaur (TVLSI 2014, Neil & Liu, UZH/ETH)** — `papers/A22_Minitaur_TVLSI2014.pdf`
> "This implementation was primarily used for **prototyping caching strategies** since **memory bandwidth, rather than compute time, fundamentally limits the performance** of the hardware."
> "**Cache locality is critical** in optimizing neuron weight and state lookups."

**본 제안과 구조적으로 가장 가까운 선행 문헌.** Spartan-6 LX150(BRAM 549 kB) + **DDR2 128 MB 메인 메모리** 구성에 32개 코어를 두고, 각 코어가 state 캐시와 weight 캐시를 갖는다. 뉴런 ID 하위 5비트로 코어에 striping해 지역성을 확보하고, 연결은 range-rule 형식으로 압축 저장한다. 65K 뉴런 / 1.5 W.

- **인정해야 할 점**: "SNN 가중치를 오프칩 DRAM에 두고 온칩 캐시로 접근한다"는 구성은 **2014년에 이미 나왔다.** 이 조합 자체는 신규성이 아니다
- **활용**: 메모리 대역폭이 SNN 가속기의 진짜 병목이라는 명제를 12년 전 문헌으로 뒷받침. 제안서 §1의 가장 강한 인용
- **차이**: ① 단일 네트워크 — 모델이 여러 개일 때의 전환·캐시 교체가 없다 ② 캐시 지역성이 **한 네트워크 안의 뉴런 지역성**이지 **모델 정체성**이 아니다 ③ 하드 데드라인 개념이 없다(이벤트 구동, 정확도-지연 트레이드오프만) ④ 스케줄링 문제가 존재하지 않는다

**SpinalFlow (ISCA 2020, Univ. of Utah)** — `papers/A01_SpinalFlow_ISCA2020.pdf`
> "SNN dataflows must consider neuron potentials for **several ticks**, introducing a new data structure and a new dimension to the reuse pattern."

SNN이 타임스텝마다 가중치를 반복 fetch하고 막전위를 유지해야 하는 문제를 정식화한 기준 논문. 4-bit/90% 희소도에서 Eyeriss 대비 에너지 1.8배 절감.

- **중요**: 초기 후보였던 "타임스텝 가중치 재읽기" 아이디어는 **이 논문이 이미 해결**했다. 신규 기여가 아니라 재현할 baseline이다

### 3.2 메모리 계층·데이터플로우

**SpikeX (2025, UCSB, TCAD)** — `papers/A03_SpikeX_2025.pdf`
시스톨릭 어레이 SNN 가속기. **3단 메모리 계층(오프칩 RAM → GLB → 더블버퍼 L1)** 으로 multi-bit weight 이동을 줄인다. 본 제안의 캐시 계층과 가장 가까운 구조적 참고 문헌.
- **차이**: 단일 모델. 모델 간 전환·캐시 교체 정책 없음

**LoAS (2024, Yale/UCF)** — `papers/A04_LoAS_dual_sparse.pdf`
Dual-sparse SNN(스파이크 + 가중치 모두 희소)의 spMspM 가속.
- **차이**: 희소성 축. 본 제안과 직교 → **결합 가능성 있음**

**SparkXD / EnforceSNN** — `papers/A06_*.pdf`, `papers/A14_*.pdf`
근사 DRAM에서 SNN을 견고하게 돌리는 연구. SNN 가속기의 DRAM 접근을 직접 다룬 드문 사례지만, 방향이 에너지·내결함성이며 스케줄링이 아니다.

**Identifying Efficient Dataflows for SNNs (ISLPED 2022, Purdue, Kaushik Roy)** — `papers/A16_IdentifyingDataflows_SNN.pdf`
> "SNNs require **one additional data structure — the membrane potential (Vmem) for each neuron** which is updated every timestep. Hence, the dataflow requirements for energy-efficient hardware implementation of SNNs **can be different from the standard ANNs**."

본 제안이 지목한 **"막전위가 온칩 자원을 두고 가중치와 경쟁한다"** 는 긴장을 정식화한 문헌. 온칩 자원량이 다른 3가지 아키텍처에 대해 최적 데이터플로우 규칙을 도출하고 EDP 90% 이상 개선을 보고한다.

- **활용**: 제안서 §3.5(막전위 712KB가 BRAM의 43%)의 이론적 근거. 데이터플로우 선택 규칙을 그대로 참조
- **차이**: 단일 모델, 단일 추론. 다중 테넌시·데드라인·오프칩 모델 전환 없음

**A Large-Scale SNN Accelerator for FPGA Systems (ICANN 2012, Cheung & Schultz, Imperial College)** — `papers/A18_LargeScaleSNN_FPGA_ICANN2012.pdf`
> "We utilize **on-chip memory to store frequently accessed variables**... such that **most of the memory bandwidth is used to access neuronal parameters and synaptic data**."

온칩/오프칩 분담을 명시적으로 설계한 초기 문헌. 단일 FPGA로 64K 뉴런을 실시간의 2.5배로 시뮬레이션하며, 실행 시간이 발화율에 비례한다.

- **활용**: SNN 가중치 스트리밍의 직접 조상. 온칩에 무엇을 남기고 무엇을 흘릴지의 분담 원칙
- **차이**: 시뮬레이션 목적, 단일 네트워크, 스케줄링 없음

**A reconfigurable FPGA-based SNN accelerator (Microelectronics Journal 2024, 북경대)** — `papers/A15_Reconfigurable_SNN_accel.pdf`
"reconfigurable"이 **다중 모델을 뜻하지 않는다.** 공간 컨볼루션 모듈과 시간 누적 모듈 사이의 데이터패스 재구성을 가리키며, STBP 온칩 학습과 sparse zero-hopping을 지원한다(추론 5.98 TOPS, 6.94 W).

- **판정**: 용어 겹침일 뿐 충돌 없음. SNAVA와 같은 경우

**Spiking Transformer Hardware Accelerators in 3D Integration (ICCAD 2024, UCSB+GaTech)** — `papers/A17_SpikingTransformer_3D.pdf`
스파이킹 트랜스포머 전용 3D 집적 가속기. SpikeX(A03)와 같은 그룹(Peng Li)의 후속.
- **차이**: 대규모 단일 모델. 본 제안과 직교

**기타**: `A02_S2N2`, `A07~A10`(희소 압축·벡터와이즈·자원효율·FireFly), `A11_NeuroRing`(다중 FPGA 링), `A12_LIFonly`, `A13_SharingLIF`

### 3.3 관찰

SNN 가속기 분야에서 **메모리 최적화는 이미 밀집 지역**이다. 초기 검토했던 "스파이크 구동 랜덤 접근 비닝" 아이디어는 SpikeX·LoAS·SpinalFlow·SparkXD가 인접 영역을 점유하고 있어 신규성 확보가 어렵다. **다중 테넌시·실시간 축으로 선회한 판단은 타당하다.**

---

## 4. 갈래 B — 다중 DNN / 다중 테넌트 스케줄링

본 제안의 **방법론적 조상**. 전부 ANN 대상이다.

**Sparse-DySta (2023, Samsung AI Center & Cambridge)** — `papers/B03_SparseDySta_multiDNN.pdf`
희소 다중 DNN 워크로드 스케줄링. 정적 + 동적 이중 스케줄러. **"latency constraint violation rate"** 를 핵심 지표로 사용하고 공개 벤치마크를 구축(SamsungLabs/Sparse-Multi-DNN-Scheduling).

- **가장 중요한 참고 문헌.** 평가 지표와 실험 설계를 그대로 참고
- 위반율 10% 감소, 평균 정규화 turnaround 4배 개선
- **차이**: ANN, 데이터센터/모바일, soft real-time

**Terastal (RTCSA 2026, UC Irvine)** — `papers/B01_Terastal_multiDNN_RT.pdf`
이기종 가속기 상의 실시간 다중 DNN. **FCFS / EDF / DREAM 대비 마감 위반율 40.58% / 30.53% / 36.27% 감소.**
- **활용**: EDF를 baseline으로 삼는 근거
- **차이**: 레이어를 이기종 가속기에 매핑. 가중치 오프칩 전송 비용은 다루지 않음

**Spatial- and time-division multiplexing in CNN accelerator (Parallel Computing 2022, NTT)** — `papers/B07_SpatialTimeDivMux_CNN.pdf`
하나의 FPGA 가속기를 여러 작업이 공간·시간 분할로 공유하는 구조. 본 제안의 시분할 다중 트랙과 개념적으로 가장 가까운 선행이다.
- **차이**: CNN 대상, 모델 오프칩 전환 비용·하드 데드라인 없음

**IsoSched / THEMIS / B05 / B06** — 선점형 타일 스케줄링, 다중 테넌트 FPGA 시공간 공정성(부분 재구성), 확정적 실시간 스케줄링, GPU 런타임 인지 스케줄링

### 4.1 관찰

다중 테넌트 스케줄링 문헌은 성숙했지만 **모두 ANN이고, 대부분 "모델은 이미 메모리에 있다"고 가정**한다. 본 제안의 핵심인 *모델 자체를 DRAM에서 끌어오는 비용이 스케줄링 결정에 들어가는* 구조는 다루어지지 않는다. 또한 **주기적 하드 데드라인**은 데이터센터의 soft SLO와 성격이 다르다.

---

## 5. 갈래 C — 가중치 스트리밍과 프리페치

**AutoWS (2023, Imperial College London)** — `papers/C01_AutoWS_weight_streaming.pdf`
레이어별 파이프라인 DNN 가속기에서 온칩/오프칩 메모리를 함께 활용하는 가중치 저장 최적화. **오픈소스**(github.com/Yu-Zhewen/AutoWS).
- **활용**: 캐시/스트리밍 설계공간 탐색 방법론. 코드 확인 가치 있음
- **차이**: 단일 모델, **정적 스케줄** 전제

**PRESERVE (2025)** — `papers/C03_PRESERVE_prefetch.pdf`
분산 LLM 서빙에서 모델 가중치와 KV-cache 프리페치. 프리페치-통신 오버랩 기법 참고.

**Tessera (2026) / C04 / C05** — UMA 엣지 가속기 가중치 스트리밍, NN 메모리 계층 구성, 다중 컴퓨트 엔진 분석 비용 모델

---

## 6. 문헌 확보 현황

**계획했던 문헌을 모두 확보했다(39편).** 09-09에 SATA(`A20`, arXiv 판본), Bluehive(`A21`, 케임브리지 공개본), Minitaur(`A22`, UZH ZORA 공개본)를 마지막으로 미확보 목록이 비었다. 셋 다 IEEE 구독 없이 오픈 판본으로 대체했다.

> **조사에서 제외**: "FPGA-based spiking attention NN accelerator"는 **실재하지 않는 문헌**으로 확인되어 제거했다.
> **정정(09-09)**: "Efficient spiking conv NN accelerator with multi-structure compatibility"는 한때 함께 제외했으나 **실재하는 논문이며**(Front. Neurosci. 2025, DOI 10.3389/fnins.2025.1662886) `A19`로 등록했다. 초기 다운로드 실패는 DOI 추정 오류 때문이었다.

## 7. 차별화 논거

> **Minitaur(2014) 확인 후 조정됨.** "SNN 가중치를 오프칩 DRAM에 두고 온칩 캐시로 접근한다"는 구성 자체는 신규성이 아니다. 기여는 **다중 모델 · 하드 데드라인 · 스케줄링** 세 축에 집중해야 한다.

**신규성을 주장할 수 있는 것**

1. **모델 전송 비용이 스케줄링 결정에 들어간다.** 갈래 B(다중 DNN 스케줄링)는 모델이 이미 온칩에 있다고 가정한다. Minitaur는 캐싱을 하지만 스케줄링 문제가 없다(단일 네트워크). 본 제안은 **모델 fetch 비용과 데드라인을 동시에 최적화**한다.
2. **캐시의 단위가 모델이다.** Minitaur의 지역성은 *한 네트워크 안의 뉴런* 지역성이고, 본 제안의 지역성은 *모델 정체성*이다 — 같은 모델을 쓰는 트랙을 묶는 것이 최적화 대상이다.
3. **주기적 하드 데드라인.** 센서 샘플링 주기(32 ms)에서 오는 하드 제약은 데이터센터 soft SLO와도, Minitaur의 정확도-지연 트레이드오프와도 다르다. 위반이 곧 탐지 누락이다.
4. **트랙 수에 비례하는 막전위 압력.** ISLPED'22(A16)가 단일 모델 기준으로 막전위 데이터플로우를 정식화했으나, **N에 비례해 막전위가 커져 모델 캐시와 온칩 자원을 다투는 다중 테넌트 상황**은 다루지 않았다(N=512에서 BRAM의 43%).
5. **모델 수 M이 정확도 손잡이이자 대역폭 손잡이.** 정확도-메모리 트레이드오프를 M 하나로 스윕할 수 있다.

**신규성을 주장하면 안 되는 것**

- SNN이 memory-bound라는 관찰 (Minitaur 2014, FeNN-DMA 2026이 이미 명시)
- 오프칩 가중치 + 온칩 캐시 구조 (Minitaur 2014, A18 ICANN 2012)
- 타임스텝 간 가중치 재사용 데이터플로우 (SpinalFlow 2020)
- 막전위가 별도 데이터 구조로 압력을 준다는 지적 (A16 ISLPED 2022)

## 8. 다음 조사 단계

- [x] ~~SNAVA 원문 확보 및 정독~~ → **완료. 충돌 없음(§2)**
- [x] ~~Minitaur (TVLSI 2014) 확보~~ → **완료 `A22`. DDR2 + 온칩 캐시 구조 확인 — 가장 가까운 선행**
- [x] ~~Bluehive (FCCM 2012) 확보~~ → **완료 `A21`**
- [x] ~~SATA 확보~~ → **완료 `A20`**
- [x] ~~ACM DL / ScienceDirect / Springer 구독 문헌 확보~~ → **완료 (A15·A16·A17·A18·B07)**
- [ ] SpinalFlow / SpikeX / Sparse-DySta forward citation 추적
- [ ] `multi-tenant SNN`, `deadline-aware SNN accelerator`, `model caching FPGA` 키워드 Google Scholar 재검색
- [ ] 산업 예지보전에서 **설비별 개인화 모델**이 실제 사용되는지 근거 문헌 확보 (제안서 §1.3 뒷받침)
- [ ] 8클래스 결함 라벨 음향 데이터셋 조사 (MIMII/DCASE는 이진 중심)

---

## 부록 — 수집 논문 목록

### A. SNN 가속기 (22편)
| 파일 | 논문 |
|---|---|
| A01 | SpinalFlow: An Architecture and Dataflow Tailored for SNNs (ISCA 2020) |
| A02 | S2N2: A FPGA Accelerator for Streaming SNNs (FPGA 2021) |
| A03 | SpikeX: Accelerator Architecture and Network-Hardware Co-Optimization (2025) |
| A04 | LoAS: Fully Temporal-Parallel Dataflow for Dual-Sparse SNNs (2024) |
| A05 | FeNN-DMA: A RISC-V SoC for SNN Acceleration (2026) |
| A06 | SparkXD: SNN Inference using Approximate DRAM |
| A07 | Sparse Compressed SNN Accelerator for Object Detection |
| A08 | VSA: Reconfigurable Vectorwise SNN Accelerator |
| A09 | A Resource-efficient SNN Accelerator Supporting Emerging Neural Encoding |
| A10 | FireFly: High-Throughput HW Accelerator for SNNs |
| A11 | NeuroRing: Scaling SNNs via Multi-FPGA Bidirectional Ring Topologies (2026) |
| A12 | Lightweight LIF-only SNN accelerator using differential time encoding |
| A13 | Sharing Leaky-Integrate-and-Fire Neurons for Memory-Efficient SNNs |
| A14 | EnforceSNN: SNN Inference with Approximate DRAM |
| A15 | A reconfigurable FPGA-based SNN accelerator (Microelectronics J. 2024) |
| A16 | **Identifying Efficient Dataflows for SNNs (ISLPED 2022)** — 막전위 데이터플로우 |
| A17 | Spiking Transformer Hardware Accelerators in 3D Integration (ICCAD 2024) |
| A18 | A Large-Scale SNN Accelerator for FPGA Systems (ICANN 2012) — 온칩/오프칩 분담 |
| A19 | Efficient spiking conv NN accelerator with multi-structure compatibility (Front. Neurosci. 2025) |
| A20 | **SATA: Sparsity-Aware Training Accelerator for SNNs (TCAD)** — 에너지 분해에서 메모리 지배 |
| A21 | **Bluehive: FPCM for Extreme-Scale Real-Time NN Simulation (FCCM 2012)** — 64M 시냅스, 오프칩 구조 |
| A22 | **Minitaur (TVLSI 2014)** — DDR2 + 온칩 가중치 캐시. **가장 가까운 선행** |

### B. 다중 DNN / 다중 테넌트 스케줄링 (7편)
| 파일 | 논문 |
|---|---|
| B01 | Terastal: Layer-Variant Scheduling for Real-Time Multi-DNN (RTCSA 2026) |
| B02 | IsoSched: Preemptive Tile Cascaded Scheduling of Multi-DNN (2025) |
| B03 | Sparse-DySta: Sparsity-Aware Dynamic and Static Scheduling (2023) |
| B04 | THEMIS: Scheduling for Fair Multi-Tenant Use in FPGAs |
| B05 | Towards Fair and Firm Real-Time Scheduling in DNN Multi-Tenant Systems |
| B06 | Automated Runtime-Aware Scheduling for Multi-Tenant DNN Inference on GPU |
| B07 | Spatial- and time-division multiplexing in CNN accelerator (Parallel Computing 2022) |

### C. 가중치 스트리밍 / 메모리 계층 (5편)
| 파일 | 논문 |
|---|---|
| C01 | AutoWS: Automate Weights Streaming in Layer-wise Pipelined DNN Accelerators |
| C02 | Tessera: Near-Line-Rate Weight Streaming for UMA Edge Accelerators |
| C03 | PRESERVE: Prefetching Model Weights and KV-Cache in Distributed LLM Serving |
| C04 | A Configurable and Efficient Memory Hierarchy for NN Hardware Accelerator |
| C05 | An Analytical Cost Model for Multiple Compute-Engine CNN Accelerators |

### D. 다중 모델 SNN 시뮬레이터 / 응용 / 서베이 (5편)
| 파일 | 논문 |
|---|---|
| **D00** | **SNAVA: real-time multi-FPGA multi-model SNN simulation architecture (Neural Networks 2018)** — 판정 완료, 충돌 없음 |
| D01 | Anomalous Sound Detection with Machine Learning: A Systematic Review |
| D02 | Hardware-Accelerated Event-Graph Neural Networks on SoC FPGA |
| D03 | Architectural Design and Performance Analysis of FPGA based AI Accelerators (2026) |
| D04 | FPGA-Based Neural Network Accelerators for Space Applications: A Survey |

---

## 관련 문서

- 제안서: [PROPOSAL.md](PROPOSAL.md)
