# software/ 구성

갱신일: 2026-10-12

| 폴더 | 내용 |
|---|---|
| `model_develop/` | 모델·학습 코드. `snn_model.py`(PLIF-T `40→384→256→64→2`), `dcase_data.py`(파일 목록·mel 추출·캐시), `train.py`/`train_all.py`(학습), `snn_numpy.py`(FP32 참조), `snn_int8.py`(INT8 골든), `model_format.py`(DDR3 형식), `export_models.py`(P2.6 생성), `make_golden_vectors.py`(P2.7 생성), `verify_p1_artifacts.py`(전수 검증). P3.6: `train.py --layers`, `train_all.py --layers --tag --nshard --units`(구조별 재학습, 기록 `analysis_result/size_sweep/<tag>/`, 체크포인트 `model_weights/_sweep/<tag>/`) |
| `model_develop/references/` | 선행 SpikeSense-Edge 코드 원본. 수정하지 않고 참고용으로만 둔다 |
| `analysis_develop/` | 분석·그래프 코드. `analyze_runs.py`(학습 기록 → 요약표·곡선), `exp_lowscore.py`(학습 방식 비교 실험), `check_numpy_fp.py`(선행 NumPy 재현·NumPy↔PyTorch FP 일치 검증, 결과 `numpy_fp/`), `compare_quant.py`(INT8 ↔ FP32 40대 정확도 비교), `quant_variants.py`(양자화 후보 비교). 두 결과는 `quant_int8/`. P3: `analyze_p3.py`(DDR3·PCIe 보드 측정 원자료 → `p3_meas/summary_*.md`, 원자료 `p3_meas/raw/`), `bram_plan.py`(온칩 메모리 BRAM 타일 계산), `size_sweep.py`(P3.6 구조·가중치 비트별 AUC → `size_sweep/`) |
| `sim_develop/` | 시뮬레이터 설계(코드). P3.5 설계 결정 시뮬레이터([SIM_PLAN.md](../documents/design/SIM_PLAN.md)): `sim_core.py`(요청 도착·실측 비용 모델·진행 규칙·지표·사이클 회계), `policies.py`(저장 정책·스케줄러·연산 방식 부품), `run_sim.py`(`--selftest` 손계산 대조, 24조합 실행·대역폭 단계), `plot_sim.py`, `dse.py`(P3.8 설계 공간 탐색: 최대 트랙, `--rev 2·3`, `--verify`·`--axes`·`--sens`), `plot_dse.py`, `plot_max_tracks.py`(그림 7~13), `compare_figs.py`(L·XL 비교), `fixedn.py`(트랙 고정 비교), `target_exp.py`(P3.8 마무리: 시나리오별 최대 트랙·목표 트랙 지표·민감도, `--sch`·`--prefix`·`--only`로 스케줄러 비교), `plot_target.py`(최종 비교 그림 18·19, `--old`로 이전 그림 14~17). 최종 비교 대상과 구현 스케줄러(SlackBatch)는 [MODEL_SIZE_PLAN](../documents/design/MODEL_SIZE_PLAN.md) §5.12 |
| `sim_result/` | 시뮬레이션 결과. `*.jsonl`(실행별 원자료)·`*.md`(요약 표)·`*.log`, `figures/`(그림, `compare/` L·XL 비교, `discarded/` 최종 정리 전 그림) |
| `analysis_result/` | 분석 산출물(이전 이름 `analysis_data/`). `all40/`(40대 결과표·학습 기록·보고서), `size_sweep/`(P3.6 구조별 학습 기록), `figures/`(논문용 그림). 폴더 안 학습 기록(`*.log`, `args.json`)의 경로는 실행 당시 이름(`analysis_data`) 그대로다 |
| `model_weights/` | 장비별 체크포인트 `<기종>_id<ID>/{last.pth, best_val.pth}`. 채택본은 `last.pth` |
| `data/dataset_dcase/` | DCASE 2020 Task 2 원본 wav + `eval_data_list.csv` |
| `data/mel_dcase/` | mel 특징 세그먼트 캐시 `<장비>_<split>_seg31[_hop16].npz` |

## 장비 이름 규칙

`<기종>_id<ID 두 자리>` (예: `fan_id01`). 기종은 DCASE 폴더 이름 그대로 `fan`, `pump`,
`slider`, `valve`, `ToyCar`, `ToyConveyor`이고 ID는 wav 파일명 `normal_id_00_*.wav`의 두 자리다.
`pump`·`valve` 00–06, `fan` 01–06, `slider` 00–06, `ToyCar` 01–07, `ToyConveyor` 01–06으로 모두 40대이며
모델 1개가 장비 1대를 맡는다. 41대 중 `fan` id_00을 제외했고 그 wav는 삭제했다
(제외 장비 선정 경위는 `analysis_result/REPORT.md` 참고).
