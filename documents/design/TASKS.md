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

보고서: [P1.1~P1.4](<../reports/P1.1~1.4 Research Report.md>), [P1.5~P1.7](<../reports/P1.5~1.7 Research Report.md>), [P1.8](<../reports/P1.8 Research Report.md>)
환경: [ENVIRONMENT.md](ENVIRONMENT.md)

## 2. 모델

| 상태 | ID | 작업 | 결과 |
|---|---|---|---|
| [x] | P2.1 | dataset과 label 결정 | DCASE 2020 Task 2, 정상/이상 2출력 |
| [x] | P2.2 | 40모델 구성 | 41대 중 40대, 지도학습 채택 |
| [x] | P2.3 | `40→384→256→64→2` 구현 | 4 weight layer, 706뉴런 |
| [x] | P2.4 | 모델 40개 학습 | 평균 ROC-AUC 0.9563, P2.3~P2.4 보고서 참고 |
| [x] | P2.5 | INT8 방식 결정 | 평균 AUC 0.9554, 16 bit 막전위 saturation 적용 |
| [x] | P2.6 | weight export | 모델당 130,176 B, 132 KiB slot |
| [x] | P2.7 | INT8 golden vector | 실데이터 80개 + saturation test 2개 |

보고서: [P2.1~P2.2](<../reports/P2.1~2.2 Research Report.md>), [P2.3~P2.4](<../reports/P2.3~2.4 Research Report.md>), [P2.5](<../reports/P2.5 Research Report.md>), [P2.6~P2.7](<../reports/P2.6~2.7 Research Report.md>)

## 3. 설계 검증

| 상태 | ID | 작업 | 결과 |
|---|---|---|---|
| [x] | P3.1 | DDR3 bandwidth·latency 실측 | read 3.015 GB/s, model 43.43 µs |
| [x] | P3.2 | IP resource 실측 | XDMA 20.5 BRAM tile, MIG 0 |
| [x] | P3.3 | PCIe latency·jitter 실측 | 64 B H2C p50 27.2 µs |
| [x] | P3.4 | 32 lane BRAM 구성 | model entry 28.5 tile, 막전위 176.5 tile |
| [x] | P3.5 | architecture simulator | self-test 통과, 24조합 비교 |
| [x] | P3.6 | 모델 크기·quantization 비교 | 작은 모델은 정확도 하락, XL은 평균 +0.005 |
| [x] | P3.7 | 요청 시나리오 6개 | U, K, S, I, SK, R 반영 |
| [x] | P3.8 | cache·scheduler·연산 비교 | SlackBatch 제안, P3.6~P3.8 보고서 참고 |
| [ ] | P3.9 | architecture spec 동결 | interface, register map, packet, 최종 목표 확정 |

P3.8 제안안:

- XL INT8 + overlap augmentation
- 256 lane, 막전위 DDR3
- synthesis 목표 1,024트랙
- cache entry 2개
- SlackBatch 구현, 6개 비교 정책 runtime 선택

이 안은 simulation 결과다. 512→1,024트랙과 L→XL 변경은 `PROPOSAL.md`에 아직 반영하지 않았다.

문서: [P3.1~P3.4 보고서](<../reports/P3.1~3.4 Research Report.md>), [SIM_PLAN.md](SIM_PLAN.md), [MODEL_SIZE_PLAN.md](MODEL_SIZE_PLAN.md), [P3.6~P3.8 보고서](<../reports/P3.6~3.8 Research Report.md>)

## 4. RTL

P3.9에서 architecture를 동결한 뒤 시작한다.

| 상태 | ID | 작업 | 완료 기준 |
|---|---|---|---|
| [ ] | P4.1 | `compute_array`, `plift_core` | INT8 golden과 bit 일치 |
| [ ] | P4.2 | `membrane_bank` | track state 분리 |
| [ ] | P4.3 | cache와 slice buffer | valid·교체 검증 |
| [ ] | P4.4 | DMA·prefetch | 전송 완료와 backpressure 검증 |
| [ ] | P4.5 | `track_scheduler` | SW 정책과 선택 순서 일치 |
| [ ] | P4.6 | queue·timestamp·counter | 계측값 검증 |
| [ ] | P4.7 | XDMA·Host 연동 | 모델 적재, 요청, 결과 회수 |
| [ ] | P4.8 | USB mic preprocessing | `track_id`와 timestamp 생성 |
| [ ] | P4.9 | load generator | 재현 가능한 trace |
| [ ] | P4.10 | 통합 test | xsim, Verilator, state·output 일치 |

## 5. 보드 통합

| 상태 | ID | 작업 | 완료 기준 |
|---|---|---|---|
| [ ] | P5.1 | synthesis·P&R | timing·resource report |
| [ ] | P5.2 | bitstream·ILA | board 동작과 waveform |
| [ ] | P5.3 | 단계별 board test | 단일 요청→다중 track→목표 부하 |
| [ ] | P5.4 | end-to-end test | USB mic→Host→FPGA→결과 |

## 6. 평가와 논문

| 상태 | ID | 작업 | 완료 기준 |
|---|---|---|---|
| [ ] | P6.1 | 비교 실험 | 같은 trace·mapping·clock·cache 조건 |
| [ ] | P6.2 | 계측 수집 | miss rate, weight byte, p99, worst |
| [ ] | P6.3 | simulation과 board 비교 | 오차 원인 분석 |
| [ ] | P6.4 | USB mic demo | 통합 시연 |
| [ ] | P6.5 | 논문 | 초안과 재현 자료 |

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
