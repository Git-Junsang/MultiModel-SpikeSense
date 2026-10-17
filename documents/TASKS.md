# 작업 목록

표기: `[x]` 완료, `[ ]` 미완료. 상세 결과는 보고서와 설계 문서에 둔다.

## 1. 개발 환경과 보드

| 상태 | ID | 작업 | 결과 |
|---|---|---|---|
| [x] | P1.1 | 개발·학습 서버 확인 | RTX 3090 Ti, PyTorch CUDA 확인 |
| [x] | P1.2 | Vivado·xsim·Verilator 확인 | synthesis, simulation, lint 통과 |
| [x] | P1.3 | JTAG 연결 | `xc7a200t_0` 인식 |
| [x] | P1.4 | XDC와 build script | 87개 port pin 일치 |
| [x] | P1.5 | LED·clock board test | VIO 계산값 일치, 약 200 MHz |
| [x] | P1.6 | MIG DDR3 test | calibration 완료, 360초 error 0 |
| [x] | P1.7 | PCIe XDMA test | Gen2 ×2, 64 KiB 왕복 10/10 |
| [x] | P1.8 | 저장소 구조와 NumPy reference | 선행 golden 일치, 새 FP32 AUC 일치 |

보고서: [P1.1~P1.4](<reports/P1.1~1.4 Research Report.md>), [P1.5~P1.7](<reports/P1.5~1.7 Research Report.md>), [P1.8](<reports/P1.8 Research Report.md>)
환경: [ENVIRONMENT.md](manual/ENVIRONMENT.md)

## 2. 모델

| 상태 | ID | 작업 | 결과 |
|---|---|---|---|
| [x] | P2.1 | dataset과 label 결정 | DCASE 2020 Task 2, 정상/이상 2출력 |
| [x] | P2.2 | 40모델 구성 | 41대 중 40대, 지도학습 채택 |
| [x] | P2.3 | `40→384→256→64→2` 구현 | 4 weight layer, 706뉴런 |
| [x] | P2.4 | 모델 40개 학습 | 평균 ROC-AUC 0.9563, P2.3~P2.4 보고서 참고 |
| [x] | P2.5 | INT8 방식 결정 | 평균 AUC 0.9554, 16 bit membrane potential saturation 적용 |
| [x] | P2.6 | weight export | 모델당 130,176 B, 132 KiB slot |
| [x] | P2.7 | INT8 golden vector | 실데이터 80개 + saturation test 2개 |
| [ ] | P2.8 | checkpoint 교체 | `L_mixed_aug`로 바꾸고 export·golden 재생성. 형식과 RTL은 그대로 ([02_MODEL.md](design_references/02_MODEL.md) §3) |
| [ ] | P2.9 | 실시간 특징 정규화 | 파일 단위 정규화(`ref=max`)를 대신할 방법을 정하고 40대 AUC 확인 ([02_MODEL.md](design_references/02_MODEL.md) §5). 재학습 없는 평가는 P3.21: segment 안 누적 최대·최소가 평균 ΔAUC −0.012~−0.015로 가장 적다. 그 방식으로 재학습이 남았다 |

보고서: [P2.1~P2.2](<reports/P2.1~2.2 Research Report.md>), [P2.3~P2.4](<reports/P2.3~2.4 Research Report.md>), [P2.5](<reports/P2.5 Research Report.md>), [P2.6~P2.7](<reports/P2.6~2.7 Research Report.md>)

## 3. 설계 검증

| 상태 | ID | 작업 | 결과 |
|---|---|---|---|
| [x] | P3.1 | DDR3 대역폭·지연 실측 | read 3.015 GB/s, 모델 43.43 µs |
| [x] | P3.2 | IP resource 실측 | XDMA 20.5 BRAM tile, MIG 0 |
| [x] | P3.3 | PCIe 지연·jitter 실측 | 64 B H2C p50 27.2 µs |
| [x] | P3.4 | 32 lane BRAM 구성 | 모델 entry 28.5 tile, membrane potential 176.5 tile |
| [x] | P3.5 | architecture simulator | self-test 통과, 24조합 비교 |
| [x] | P3.6 | 모델 크기·quantization 비교 | 작은 모델은 정확도 하락, XL은 평균 +0.005 |
| [x] | P3.7 | 요청 시나리오 6개 | U, K, S, I, SK, R 반영 |
| [x] | P3.8 | cache·scheduler·연산 비교 | SlackBatch 제안, P3.6~P3.8 보고서 참고 |
| [x] | P3.9 | architecture spec 동결 | L·64 lane·1,024트랙, packet·register map, SlackBatch guard 개선, P3.9 보고서 참고 |
| [x] | P3.10 | 모델 export·golden | L slot v2 64 lane 40모델, golden 82개 검증, v1 golden과 일치 |
| [x] | P3.11 | 비교군 공정성 재검토·선행연구 비교 | 조절값 공통 조정, 선행연구식 비교군 4개 추가. SlackBatch byte 우위 유지, XL Dysta 견고성 결론 철회, cache 교체 규칙(RT-Swap Method·Ogden Method)이 LRU보다 DRAM −15 % |
| [x] | P3.12 | 평균 응답 시간 단축 | 평균 6.16 → 1.51 ms(−75 %). 연산 방식(spike 0 건너뛰기)과 입출력 즉시 전송이 대부분을 줄였고 scheduler·cache 교체는 0.05 ms. WSPT는 근거 약함 |
| [x] | P3.13 | Host offset 배정과 BRAM 배분 | offset 배정 + Grouping + offset-order cache entry 4에서 DDR3 8.6 KiB/추론, 평균 0.18 ms, 악조건 miss 0. offset을 배정하면 기다리지 않는 scheduler는 모두 같다. 필요한 entry는 jitter에 비례 |
| [x] | P3.14 | 폴더 정리와 engine 결과 재생성 | 환경 파일 21개를 engine으로 다시 돌려 CSV로 저장. 옛 결과와 같다. offset 배정 없음 점은 offset 난수만 달라 합산 차이 0.07 ms 이하. 대역폭 하한은 조절값을 고정해 3개 scheduler가 0.4 → 0.65~1.0 GB/s |
| [x] | P3.15 | 설계 정본 작성 | `design_references` 01~09(2026-10-15). 옛 설계 문서 `archive/design`은 2026-10-17에 지웠다 |
| [ ] | P3.16 | Host jitter 측정 | M3·M4(장치 없이) → M1·M2(USB 마이크 2개 이상)로 p99 jitter와 clock drift를 잰다. 즉시 보내기와 offset 단위 모아 보내기 중 고르고 entry 수를 확정 ([06_HOST_INTERFACE.md](design_references/06_HOST_INTERFACE.md) §9) |
| [ ] | P3.17 | simulation 보강 | 측정 jitter 분포 입력, Ethernet 지연 표본(측정 뒤). 모아 보내기(대기 D), jitter 10~20 ms, 트랙별 on-chip membrane potential, 트랙 수 비례 offset 간격은 P3.21에서 했다 ([07_SIMULATION.md](design_references/07_SIMULATION.md) §6) |
| [ ] | P3.18 | offset 배정 선행연구 검색 | IEEE Xplore 검색(API 승인 대기), Nexus·CAN offset 원문 확인 뒤 신규성 경계 확정 ([09_RELATED_WORK.md](design_references/09_RELATED_WORK.md)) |
| [x] | P3.19 | membrane potential 저장 보강 | layer별 [9, 9, 9, 12] bit(L2·L3 아래 1 bit 버림)면 두 checkpoint 모두 손실 없음, entry 4에서 1,024트랙 on-chip. offset 순서 연속 배치는 모아 보내기에서만 DMA −84 %. membrane potential은 12 bit 유지로 결정, on-chip 트랙 수는 jitter 측정 뒤 정한다(P3.21 보고서) |
| [ ] | P3.20 | Ethernet interface 설계 | UDP framing(datagram당 요청 수, 순번·손실 처리), register 읽기·쓰기 packet, 모델 image 적재 경로, `MARGIN_US` 값 ([06_HOST_INTERFACE.md](design_references/06_HOST_INTERFACE.md) §8) |
| [x] | P3.21 | 하드웨어 없이 할 수 있는 실험 보강 | jitter 10~20 ms는 entry 10으로도 DDR3 2.3~6.5배. 모아 보내기(D ≥ jitter)면 entry 2로 6.3 KiB/추론, 응답 시간 +jitter. offset 간격 비례는 채택 안 함. 같은 BRAM에서 Dysta Method 대비 DDR3 −89 %·평균 응답 시간 −89 %, DeepRT Method 대비 DDR3 −44 %·평균 응답 시간 1/44(비교군은 Dysta Method·DeepRT Method 둘로 줄임), jitter가 크면 offset-order cache가 LRU보다 DDR3 최대 −45 %. layer별 membrane potential bit, 실시간 정규화 평가. P3.21 보고서 참고 |
| [x] | P3.22 | deadline을 마이크 수음 시각부터 재기 | deadline = frame 마지막 소리 수음 + 32 ms(오디오·전처리·전송 포함, 사용자 결정). 외부 지연 0~20 ms: 평상시 모두 miss 0, 악조건 겹침에서 기존 셋은 10 ms부터 5.1 %, 제안은 20 ms까지 0. SlackBatch는 덜 기다려 DDR3 7.2 → 17.5 KiB/추론. worst case 계산이 보장하는 오디오·전처리·링크 몫은 약 7 ms. offset-order cache의 일정 지연 오류를 고침(P3.22 보고서) |
| [x] | P3.23 | 문서·코드 용어 통일 | design_references 수치·용어 갱신(deadline 보장 25 ms 등). 보고서·TASKS·코드 주석·simulation label·그림을 [01_OVERVIEW.md](design_references/01_OVERVIEW.md) §3 용어로 통일(데이터는 그대로). 설정 키 align과 실험 이름 두 개(slot_width, compare_aligned)를 offset 계열 이름으로 바꿈. 값이 다르거나 폐기한 그림은 `analysis/discards/`로 옮김 |

설계 정본은 [design_references](design_references/01_OVERVIEW.md)다. Host offset 배정 + 즉시 입출력 + Grouping + offset-order weight cache(entry 4) + 남는 BRAM의 12 bit membrane potential + spike 0 건너뛰기, 1,024트랙, 64 lane @100 MHz, Host 링크 Ethernet. 근거는 simulation이다.

문서: [P3.1~P3.4 보고서](<reports/P3.1~3.4 Research Report.md>), [P3.6~P3.8 보고서](<reports/P3.6~3.8 Research Report.md>), [P3.9 보고서](<reports/P3.9 Research Report.md>), [P3.10 보고서](<reports/P3.10 Research Report.md>), [P3.11 보고서](<reports/P3.11 Research Report.md>), [P3.12 보고서](<reports/P3.12 Latency Research Report.md>), [P3.13 보고서](<reports/P3.13 Research Report.md>), [P3.14 보고서](<reports/P3.14 Research Report.md>), [P3.21 보고서](<reports/P3.21 Research Report.md>), [P3.22 보고서](<reports/P3.22 Research Report.md>)

## 4. RTL

P3.10 뒤 시작한다. 기준 문서는 [03_ARCHITECTURE.md](design_references/03_ARCHITECTURE.md)~[06_HOST_INTERFACE.md](design_references/06_HOST_INTERFACE.md)다.

| 상태 | ID | 작업 | 완료 기준 |
|---|---|---|---|
| [ ] | P4.1 | `compute_array`, `plift_core` | `golden_l64`와 bit 일치, 64 lane @100 MHz timing. spike 2개/cycle(BRAM 두 번째 port + DSP pre-adder) 구현 가능성, 제어 cycle 실측(가정 203) |
| [ ] | P4.2 | `membrane_bank`·membrane potential 경로 | on-chip 12 bit bank와 DDR3 경로, 트랙 state 분리 |
| [ ] | P4.3 | weight entry와 cache 교체 | entry 4, offset-order 교체, 연산 중 entry 보호 |
| [ ] | P4.4 | DMA·prefetch | 전송 완료와 backpressure 검증 |
| [ ] | P4.5 | `track_scheduler` (Grouping) | simulator와 선택 순서 일치 |
| [ ] | P4.6 | queue·timestamp·counter | 계측값 검증 |
| [ ] | P4.7 | Ethernet·Host 연동 | 모델 적재, 요청, 결과 즉시 전송, 시각 맞추기. MAC의 BRAM·LUT와 clock 경계 확인 |
| [ ] | P4.8 | USB mic preprocessing·offset 배정 | `track_id`, timestamp, Host clock 기준으로 offset에 맞춘 frame 경계, 저지연 오디오 buffer, P3.16에서 고른 보내기 방식 |
| [ ] | P4.9 | load generator | 재현 가능한 trace |
| [ ] | P4.10 | 통합 test | xsim, Verilator, state·output 일치 |

## 5. 보드 통합

| 상태 | ID | 작업 | 완료 기준 |
|---|---|---|---|
| [ ] | P5.1 | synthesis·P&R | timing·resource report |
| [ ] | P5.2 | bitstream·ILA | board 동작과 waveform |
| [ ] | P5.3 | 단계별 board test | 단일 요청→다중 트랙→목표 부하 |
| [ ] | P5.4 | end-to-end test | USB mic→Host→FPGA→결과 |

## 6. 평가와 논문

| 상태 | ID | 작업 | 완료 기준 |
|---|---|---|---|
| [ ] | P6.1 | 비교 실험 | 같은 trace·mapping·clock·cache 조건 |
| [ ] | P6.2 | 계측 수집 | miss rate, weight byte, p99, worst |
| [ ] | P6.3 | simulation과 board 비교 | 오차 원인 분석 |
| [ ] | P6.4 | USB mic demo | 통합 시연 |
| [ ] | P6.5 | 논문 | 초안과 재현 자료 |
| [ ] | P6.6 | 전력 측정 | 측정 방법(보드 전원 계측 또는 Vivado 보고 + DDR3 byte 기반 추정)을 정하고 추론당 에너지를 잰다 ([08_EVALUATION.md](design_references/08_EVALUATION.md) §5) |

## 7. 선행 자산

선행 저장소: `/mnt/nas/data/2026-CAU/서울대학교 학부인턴/Project/SpikeSense-Edge`

| 자산 | 사용 위치 |
|---|---|
| 모델·학습·quantization·export code | P1.8, P2 |
| `plift_core.v`, `mac_unit.v` | P4.1 |
| `membrane_mem_mult.v` | P4.2 |
| `anomaly_judge_mult.v`, `control_fsm_mult.v` | P4 참고 |
| `capture_mel.py` | P4.8 |

선행 저장소의 지침을 먼저 읽는다. 동결된 `snn_top.v`, `dual_snn_top.v`는 수정하지 않는다.
