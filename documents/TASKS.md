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
| [x] | P3.7 | 추론 요청 시나리오 6개 | uniform, skewed, synchronized, intermittent, skewed-synchronized, fluctuating 반영 |
| [x] | P3.8 | cache·scheduler·연산 비교 | SlackBatch 제안, P3.6~P3.8 보고서 참고 |
| [x] | P3.9 | architecture spec 동결 | L·64 lane·1,024트랙, packet·register map, SlackBatch guard 개선, P3.9 보고서 참고 |
| [x] | P3.10 | 모델 export·golden | L 64 lane slot 40모델, golden 82개 검증, 1 lane golden과 일치 |
| [x] | P3.11 | 비교군 공정성 재검토·선행연구 비교 | 조절값 공통 조정, 선행연구식 비교군 4개 추가. SlackBatch byte 우위 유지, XL Dysta 견고성 결론 철회, cache 교체 규칙(RT-Swap Method·Ogden Method)이 LRU보다 DDR3 −15 % |
| [x] | P3.12 | 평균 응답 시간 단축 | 평균 6.16 → 1.51 ms(−75 %). 연산 방식(spike 0 건너뛰기)과 즉시 입출력이 대부분을 줄였고 scheduler·cache 교체는 0.05 ms. WSPT는 근거 약함 |
| [x] | P3.13 | Host offset 배정과 BRAM 배분 | offset 배정 + Grouping + offset-order cache entry 4에서 DDR3 8.6 KiB/추론, 평균 0.18 ms, 악조건 miss 0. offset을 배정하면 기다리지 않는 scheduler는 모두 같다. 필요한 entry는 jitter에 비례 |
| [x] | P3.14 | 폴더 정리와 engine 결과 재생성 | 환경 파일 21개를 engine으로 다시 돌려 CSV로 저장. 옛 결과와 같다. offset 배정 없음 점은 offset 난수만 달라 합산 차이 0.07 ms 이하. 대역폭 하한은 조절값을 고정해 3개 scheduler가 0.4 → 0.65~1.0 GB/s |
| [x] | P3.15 | 설계 정본 작성 | `design_references` 01~09(2026-10-15). 옛 설계 문서 `archive/design`은 2026-10-17에 지웠다 |
| [ ] | P3.16 | Host 지연 측정 | Xeon Host 처리 지연은 P3.25에서 쟀다(모델 묶음 지연 p99 0.71~6.70 ms, 기록된 묶음 안 퍼짐 0). 남은 것: 라즈베리파이 5(8 GB) Host의 1,024트랙 처리량·모델 묶음 지연·추론 요청별 도착 퍼짐, Ethernet 지연·packet 간격, mic–Host 지연·clock drift ([06_HOST_INTERFACE.md](design_references/06_HOST_INTERFACE.md) §9). 그 값으로 entry 수를 정한다(교체 정책은 PNU-count로 확정, 2026-10-24). 측정 code는 `hardware/board_test/host/p325_*.py`, Pi에서는 Host program `software/host`의 `run --pace --loop --log`(P4.8). 장치가 없어 BLOCKED |
| [ ] | P3.17 | simulation 보강 | 추론 요청별 지연 분포와 trace 재생(P3.25), 모델 묶음 지연 재생과 drop 규칙(P3.26)은 넣었다. 목표 Host의 묶음 지연 표, 측정한 추론 요청별 퍼짐, Ethernet 지연·packet 간격 재생이 남음 ([07_SIMULATION.md](design_references/07_SIMULATION.md) §6) |
| [ ] | P3.18 | offset 배정 선행연구 검색 | 대체 검색(OpenAlex·Semantic Scholar)에서 주기 센서 데이터의 도착 시각을 맞춰 batch를 키운 Nakayama 외를 찾았다. 주장 1을 좁히는 수정안은 사용자 결정 전([P3.18 보고서](<reports/P3.18 Research Report.md>)). IEEE Xplore 검색(API 계정 비활성, 403), Nexus·CAN offset 원문 확인 뒤 신규성 경계 확정 ([09_RELATED_WORK.md](design_references/09_RELATED_WORK.md)) |
| [x] | P3.19 | membrane potential 저장 보강 | layer별 [9, 9, 9, 12] bit(L2·L3 아래 1 bit 버림)면 두 checkpoint 모두 손실 없음, entry 4에서 1,024트랙 on-chip. offset 순서 연속 배치는 모아 보내기에서만 DMA −84 %. membrane potential은 12 bit 유지로 결정, on-chip 트랙 수는 jitter 측정 뒤 정한다(P3.21 보고서) |
| [ ] | P3.20 | Ethernet interface 설계 | UDP framing(datagram 하나에 추론 요청 1~23개, 결과는 하나씩 즉시, 재전송 없음), 주소 공간과 제어 packet(모델 image 적재 포함), MAC `verilog-ethernet`은 정함(2026-10-24, [06_HOST_INTERFACE.md](design_references/06_HOST_INTERFACE.md) §3·§4·§7). 남은 것: `MARGIN_US` 값(Ethernet 측정 뒤) |
| [x] | P3.21 | 하드웨어 없이 할 수 있는 실험 보강 | jitter 10~20 ms는 entry 10으로도 DDR3 2.3~6.5배. 모아 보내기(D ≥ jitter)면 entry 2로 6.3 KiB/추론, 응답 시간 +jitter. offset 간격 비례는 채택 안 함. 같은 BRAM에서 Dysta Method 대비 DDR3 −89 %·평균 응답 시간 −89 %, DeepRT Method 대비 DDR3 −44 %·평균 응답 시간 1/44(비교군은 Dysta Method·DeepRT Method 둘로 줄임), jitter가 크면 offset-order cache가 LRU보다 DDR3 최대 −45 %. layer별 membrane potential bit, 실시간 정규화 평가. P3.21 보고서 참고 |
| [x] | P3.22 | deadline을 mic 수음 시각부터 재기(P3.25에서 Host 도착 기준으로 바꿈) | deadline = frame 마지막 소리 수음 + 32 ms(오디오·전처리·전송 포함, 사용자 결정). 외부 지연 0~20 ms: 평상시 모두 miss 0, 악조건 겹침에서 기존 셋은 10 ms부터 5.1 %, 제안은 20 ms까지 0. SlackBatch는 덜 기다려 DDR3 7.2 → 17.5 KiB/추론. worst case 계산이 보장하는 오디오·전처리·링크 몫은 약 7 ms. offset-order cache의 일정 지연 오류를 고침(P3.22 보고서) |
| [x] | P3.23 | 문서·코드 용어 통일 | design_references 수치·용어 갱신(deadline 보장 25 ms 등). 보고서·TASKS·코드 주석·simulation label·그림을 [01_OVERVIEW.md](design_references/01_OVERVIEW.md) §3 용어로 통일(데이터는 그대로). 설정 키 align과 실험 이름 두 개(slot_width, compare_aligned)를 offset 계열 이름으로 바꿈. 값이 다르거나 폐기한 그림은 `analysis/discards/`로 옮김 |
| [x] | P3.24 | RTL 연산 cycle 반영 재실험 | control overhead 67(P4.1)을 넣고 비교를 다시 돌림. jitter 0.8 ms에서 제안 6.36 KiB/추론·최대 0.69 ms, Dysta Method 57.0 KiB·5.84 ms. entry 4개는 jitter 3.2 ms까지 버팀(3.6 ms에서 DDR3 두 배). jitter 0~3.2 ms의 가장 나쁜 값 7.07 KiB/추론·최대 1.44 ms로도 Dysta Method 대비 DDR3 −87.6 %·최대 응답 시간 −75.4 %. design_references는 아직 안 바꿈(P3.24 보고서). jitter 결과는 cache가 트랙 위상을 알던 구조라 P3.25로 대신함 |
| [x] | P3.25 | DAC 2027 재실험과 시간 기준·jitter 정의 확정 | 시간 기준을 frame 마지막 샘플의 Host 도착으로, jitter를 같은 모델 추론 요청의 Host 처리 완료 퍼짐으로 정함(2026-10-18, 사용자). cache를 LRU·offset-only·PNU-timeout·PNU-count·Oracle MIN으로 나누고 미래 정보 누출 test 포함 104항목 통과. entry 4·jitter 3.2 ms에서 offset-only 40.96, PNU-count 7.02 KiB/추론(Oracle과 같음). Dysta Method 대비 jitter 0.8 ms에서 DDR3 −88.8 %·최대 응답 시간 −67.8 %, 이득은 offset 배정에서 나옴. cache는 robustness로 주장. 즉시 송신의 보장된 상한은 증명 못 함(모아 보내기만 조건부). Xeon Host 처리 지연 측정에서 모델 단위 계산이면 jitter 0, Host 처리 지연 p99 0.71~6.70 ms. 라즈베리파이 5 측정과 design_references 반영은 남음(P3.25 보고서 §7·§8) |
| [x] | P3.26 | Host 처리 지연 분해 재실험 | Host 처리 지연을 모델 묶음 지연(Xeon Host 처리 지연 측정 재생) + 추론 요청별 지연 j ~ Uniform(0, J)로 나누고, PNU가 묶음 지연을 반영하게 고침. 06 §4.3 drop 규칙(같은 트랙 이전 추론 요청이 안 끝났으면 버림)을 넣음. 125항목 통과, P3.25 결과 그대로. CPU 고정 조건 J ≤ 0.8 ms에서 제안 6.38 KiB/추론(Dysta Method −88.7 %), J = 3.2 ms에서 12.37(−78.9 %). 최대 응답 시간은 Host 꼬리가 정함(차이 −5~−10 %), 준비 완료 뒤 최대는 −71.5~−91.0 %. 묶음 지연을 무시한 P3.25 식은 J = 3.2 ms에서 83 % 더 적재. 고른 entry는 J ≤ 0.8 ms 2, 1.6 ms 3, 3.2 ms 6. drop 0. 조건부 응답 시간은 CPU 고정 19.9~26.6 ms(보장 아님). 라즈베리파이 5 측정 뒤 entry·PNU 결정(P3.26 보고서 §6) |
| [x] | P3.27 | 설계 정본 갱신과 용어 통일 | design_references 01~09를 P3.24~P3.26·P4.1 결과로 다시 씀: Host 도착 기준 deadline, Host 처리 지연 = 모델 묶음 지연 + 추론 요청별 지연, PNU-count cache, control overhead 67 cycle, 조건부 deadline 분석. 보고서 23개의 용어를 통일(데이터 그대로). 코드 이름(`t_gen` → `t_host`, `host_phase = "slot"` → `"offset"`, 그룹핑 → Grouping)과 `template.toml`(제안 구성)을 고치고 test_engine 125항목 통과. 설계 정본과 값이 다른 그림은 `analysis/discards/`로 옮김 |
| [x] | P3.28 | simulation engine 정리 | design_references와 관계없는 저장 정책·scheduler와 옛 구현(BRAM 계산 rev 1~3, control overhead 10 % 가정, 옛 jitter, Host 모아 읽기·perturb·tail_us·트랙별 membrane 위치, 한 줄씩 연산)을 지우고 그것만 쓰던 P3.5~P3.24 환경 파일 41개를 지움(`Project/_backup/2026-10-22_engine_cleanup.tar`, 결과 CSV는 둠). engine을 실행기 `engine.py`와 부품 `part_*.py`로 나누고 환경 키를 `대상_속성[_단위]`로 바꿈. 남은 21개 환경 파일의 1,147점·tune 25개가 개편 전과 비트 단위로 같고 분석 script·RTL trace·그림도 같음. test_engine 84항목 통과. 10-23 2차: Host 처리 지연 분포를 분포별 class(`part_jitter.py`)로 나눔. 부품이 모두 `reset(wl)`을 쓰고 대기열·시각을 인자로 받게 맞춤. 묶음 지연 더하기·모아 보내기·고정 지연을 `Workload`로 옮김. entry 0(예산 최대)·split에서 on-chip 트랙을 entry 0개로 세던 BRAM 이중 계산을 고치고 준비 버퍼를 4 tile(04 §2)로 맞춤. 그룹별 적재 B 목록과 `w_xfers` 열(`weight_loads`와 같은 값)을 지움. Dysta η·DeepRT window 기본값을 비교에 쓴 값으로 바꿈. lane 수가 128의 약수가 아니면 출력 layer word를 내림으로 세던 것을 올림으로 고침(64 lane은 같음). 독립 검토(agent 8개) 지적 15건 반영. 1,147점·주요 81점 전체 길이·tune 25·search·RTL trace·분석 script 출력이 같음. 달라진 것은 `tiles` +3 tile, 지운 열, 기본값을 쓰는 tune 환경 기준점 2개(tune mode는 돌리지 않음)뿐. test_engine 88항목 통과(`Project/_backup/2026-10-23_engine_refactor.tar`). 구조와 식은 [simulation_engine.md](design_references/simulation_engine.md) |
| [x] | P3.29 | deadline 분석 engine 통합과 결과 다시 뽑기 | `simulation/analysis/`의 deadline script를 engine mode로 옮김: 조건부 응답 시간 `bound`, adversarial search `adversarial`(지연 꼴 `DelayPattern`, `part_deadline.py`), packet 분할 `Workload.packetize`, 환경 키 `host_gather_to_max`·`host_packet_gap_us`, 송신 뒤 최대 `send_side_max_ms`. `simulation/analysis/`·`simulation/result/` 전체와 P3.25 환경 파일 10개를 지움(`Project/_backup/2026-10-23_results_reset.tar`). 08 §3·§4의 결과만 sub1·sub2에서 다시 뽑음: p326_final_compare·cache_policy·jitter_entry·deadline_bound·deadline_adversarial, p325_crossover·scale_bw·scale_tracks·dysta_tune·deeprt_tune. 옛 결과와 비교하면 bound 48행과 adversarial 옛 104행이 같고(새 88행은 packet 변형을 모든 조건으로 넓힌 것), run·tune 결과는 최대·p99·miss·drop·DDR3 전송량이 같다. 평균 계열 값만 서버 간 합산 순서 차이로 상대 4e-14 이하 다르고, 나머지 차이는 10-22 키 이름 변경에 따른 이름뿐. 그림 5개가 pixel까지 같음. test_engine 93항목 통과(sub1) |

설계 정본은 [design_references](design_references/01_OVERVIEW.md)다. Model-Grouped Offset Assignment + 즉시 송신 + Grouping + PNU-count weight cache(entry 4, 수는 Host 측정 뒤 결정) + 남는 BRAM의 12 bit membrane potential + spike 0 건너뛰기, 1,024트랙, 64 lane @100 MHz, Host 링크 Ethernet. 근거는 simulation과 compute array RTL이다.

문서: [P3.1~P3.4 보고서](<reports/P3.1~3.4 Research Report.md>), [P3.6~P3.8 보고서](<reports/P3.6~3.8 Research Report.md>), [P3.9 보고서](<reports/P3.9 Research Report.md>), [P3.10 보고서](<reports/P3.10 Research Report.md>), [P3.11 보고서](<reports/P3.11 Research Report.md>), [P3.12 보고서](<reports/P3.12 Latency Research Report.md>), [P3.13 보고서](<reports/P3.13 Research Report.md>), [P3.14 보고서](<reports/P3.14 Research Report.md>), [P3.18 보고서](<reports/P3.18 Research Report.md>), [P3.21 보고서](<reports/P3.21 Research Report.md>), [P3.22 보고서](<reports/P3.22 Research Report.md>), [P3.24 보고서](<reports/P3.24 Research Report.md>), [P3.25 보고서](<reports/P3.25 Research Report.md>), [P3.26 보고서](<reports/P3.26 Research Report.md>)

## 4. RTL

P3.10 뒤 시작한다. 기준 문서는 [03_ARCHITECTURE.md](design_references/03_ARCHITECTURE.md)~[06_HOST_INTERFACE.md](design_references/06_HOST_INTERFACE.md)다.

보고서: [P4.1](<reports/P4.1 Research Report.md>), [P4.2](<reports/P4.2 Research Report.md>), [P4.3](<reports/P4.3 Research Report.md>), [P4.4](<reports/P4.4 Research Report.md>), [P4.5·P4.6](<reports/P4.5~4.6 Research Report.md>), [P4.7](<reports/P4.7 Research Report.md>), [P4.8](<reports/P4.8 Research Report.md>), [P4.10](<reports/P4.10 Research Report.md>)

| 상태 | ID | 작업 | 완료 기준 |
|---|---|---|---|
| [x] | P4.1 | `compute_array`, `plift_core` | golden_l64 82개(추론 2,542) bit 일치(xsim, Verilator). 100 MHz OOC 배선 WNS +0.311 ns(entry 4개 + mux 포함). spike 2개/cycle은 port B + pre-adder로 구현. control overhead 67(가정 203), 실데이터 평균 535.9 cycle. P4.1 보고서 참고 |
| [x] | P4.2 | `membrane_bank`·membrane potential 경로 | `golden_l64_m12` 82개를 트랙 82개(on-chip 60, DDR3 22)로 bit 일치(xsim, Verilator), 같은 모델 트랙 번갈아 처리해도 분리, `RESET_STATE`면 DDR3 읽기 생략. on-chip 768트랙 187 tile, DDR3 트랙 1,088 B(beat 34개). entry 4개와 함께 OOC 100 MHz WNS +0.348 ns. P4.2 보고서 참고 |
| [x] | P4.3 | weight entry와 cache 교체 | `weight_cache`·`next_use_predictor`가 simulator(engine.PNURTL) 교체 계획 187,090개와 결정 일치(xsim, Verilator), 연산 중 entry 보호. 정수 µs·256 µs 칸 표의 DDR3 전송량 차이 0.7 % 이하(p43_pnu_rtl). predictor LUT 812·FF 481·BRAM 1 tile, 전체 OOC 100 MHz WNS +0.365 ns. entry 수는 P3.16 뒤 결정. P4.3 보고서 참고 |
| [x] | P4.4 | DMA·prefetch | `dma`(AXI4 master, burst 16 beat × 동시 4개)와 `accel_core`(compute array·weight cache·membrane storage·dma, 추론 시작 조건, `stall_cyc`). `golden_l64_m12` 82개를 DDR3 AXI slave 모델 3가지(멈춤 없음, 무작위 backpressure·ID 사이 순서 바꾸기, 오류 응답)로 bit 일치(xsim, Verilator). 적재 672번 모두 entry 전체가 slot과 같고 AXI 규칙·우선순위 위반 0. batch가 적재보다 길면 weight 대기 0, 짧으면 적재가 끝날 때까지 연산 정지. 멈춤 없는 slave에서 4,114 beat를 4,145 cycle에 받음. OOC 100 MHz WNS +0.295 ns, dma LUT 120·FF 1,555·BRAM 0. P4.4 보고서 참고 |
| [x] | P4.5 | `track_scheduler` (Grouping) | `ingest`·`req_table`·`track_scheduler`·`result`(frontend). simulator(Grouping + PNU-count) 실행 6개(offset 배정 모델별·모두 같음·없음, J 0~3.2 ms, 추론 요청 138,122개, batch 78,096개)를 사건 순서대로 넣어 교체 계획 순서·모델·계획 때 queue, batch 구성원·순서, 결과 32 B가 모두 일치(xsim, Verilator). 여러 모델이 대기한 계획 21,232번 포함. 고장 17개 모두 FAIL. P4.5·P4.6 보고서 참고 |
| [x] | P4.6 | queue·timestamp·counter | `regs`(06 §7 주소표, 시각, counter, 첫 오류)와 frontend의 검사 오류 1~5·drop·결과 backpressure·DDR3 결과 순서. 출력 사건과 `pending_n` 대조, regs 검사 310개, 고장 20개 모두 FAIL. `SAT_COUNT`·결과 flag는 16 bit 연산 포화로 정함(12 bit 저장 포화는 실데이터 추론의 95 %에서 남). P4.5·P4.6 보고서 참고 |
| [x] | P4.7 | Ethernet·Host 연동 | `eth_link`(`verilog-ethernet` MAC·UDP, MIT)와 `ctrl`(제어 packet). 같은 core로 만든 Host와 RGMII로 맞대어 추론 요청·결과 bit 일치, 길이 오류, 결과·응답 받는 곳, register·DDR3 창, FCS 오류, ARP 확인(xsim, Verilator). 고장 20개 모두 FAIL. 합성 LUT 2,675, FF 3,980, BRAM 4 tile, clock 사이 여유 모두 양수. UDP checksum 생성기 결함으로 송신 checksum 0. 보드·라즈베리파이 확인과 시각 맞추기(Host 쪽)는 P4.8·P5. P4.7 보고서 참고 |
| [ ] | P4.8 | USB mic preprocessing·offset 배정 | `track_id`, timestamp, Host clock 기준으로 offset에 맞춘 frame 경계, 저지연 오디오 buffer, P3.16에서 고른 보내기 방식. 2026-10-25: C Host program `software/host`(시작 설정·PNU 표, 특징 추출, offset 배정, 즉시 송신, 시각 맞추기, 판정, deadline 확인)을 만듦. qemu-aarch64와 FPGA mock에서 Python 특징 추출·snn_int8 판정과 같음(`verify_host.py`, [P4.8 보고서](<reports/P4.8 Research Report.md>)). 남은 것: 라즈베리파이 5 실행, mic 입력의 ALSA timestamp |
| [ ] | P4.9 | load generator | Host(라즈베리파이 5)에서 도는 프로그램. 장치가 오기 전에는 PC로 시작한다. DCASE mel로 만든 64 B 추론 요청을 `t_host` + Host 처리 지연(측정 분포에서 뽑음) 시각에 UDP로 보내고 송신·수신 시각을 기록. simulator는 결과의 FPGA 도착 시각을 넣어 같은 조건으로 비교 |
| [x] | P4.10 | 통합 test | `accel_sys`(eth_link·ctrl·regs·frontend·accel_core)를 `verilog-ethernet` Host와 DDR3 AXI 모델에 맞대어 06 §6 순서(MIG 보정 전, 모델 적재, 설정·PNU 표, 추론, SOFT_RESET, 오류)로 시험. 트랙 80개(DDR3 20) × 31 = 추론 요청 2,480개 결과와 DDR3 트랙 membrane potential이 `golden_l64_m12`와 bit 일치(xsim, Verilator), counter와 DDR3 beat 일치. 고장 9개 모두 FAIL. xsim에서만 보인 X 두 가지(`compute_array` 함수, `membrane_buf` 마지막 beat)를 고침. P4.10 보고서 참고 |

## 5. 보드 통합

보고서: [P5.2](<reports/P5.2 Research Report.md>), [P5.3](<reports/P5.3 Research Report.md>)

| 상태 | ID | 작업 | 완료 기준 |
|---|---|---|---|
| [x] | P5.1 | synthesis·P&R | `accel_top`(MIG·Ethernet 포함) 전체 배치·배선과 bitstream. 모든 제약 만족(WNS 0.231 ns, WHS 0.020 ns, 100 MHz 0.466 ns). LUT 29,417, FF 20,809, BRAM 317.5 tile, DSP 82. RGMII 수신 IDELAY tap 1(STA, 보드에서 다시 맞춤). P4.10 보고서 참고. 최종 bitstream은 P5.2(`LINK_TUNE` 추가, 수신 tap 8·송신 −80단계, WNS 0.231 ns) |
| [x] | P5.2 | bitstream·ILA | sub1을 임시 Host로 보드에 Ethernet 직결. RGMII 송신 clock 위상이 맞지 않아 frame이 깨져 `LINK_TUNE`(수신 tap·송신 위상)을 넣고 실측으로 수신 tap 8, 송신 90°에서 −80단계로 정함. 기본값 bitstream(STA 모두 만족)에서 tb_sys 순서의 보드 시험 PASS: 추론 요청 2,480개 결과·DDR3 트랙 membrane potential이 golden과 일치, `CMP_BUSY`가 simulation과 같음, Host CRC 오류 0. ILA waveform은 보지 않음. P5.2 보고서 참고 |
| [x] | P5.3 | 단계별 board test | 다중 트랙(80, P5.2)에 이어 목표 부하: `mmss_host`로 평가 파일 12,671개를 1,024트랙 실시간(166.7 s, 추론 5,330,965개) 음원 → mel → FPGA → 판정. FPGA 출력이 Host가 보낸 입력의 snn_int8과 bit 일치(판정 주기 129,755개), AUC 보드 0.9383 = Python 전체 경로(학습 특징 0.9554와의 차는 실시간 seg 정규화 탓). 응답 시간 중앙값 3.76 ms·최대 13.5 ms(대부분 Host 대기, Xeon), FPGA 시간 최대 0.48 ms, 32 ms 초과 0. 결과 38개 손실(원인 미확정). P5.3 보고서 참고 |
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
