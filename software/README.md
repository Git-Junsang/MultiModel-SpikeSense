# software/ 구성

갱신일: 2026-10-07

| 폴더 | 내용 |
|---|---|
| `model_develop/` | 모델·학습 코드. `snn_model.py`(PLIF-T `40→384→256→64→2`), `dcase_data.py`(파일 목록·mel 추출·캐시), `train.py`/`train_all.py`(학습), `snn_numpy.py`(FP32 참조), `snn_int8.py`(INT8 골든), `model_format.py`(DDR3 형식), `export_models.py`(P2.6 생성), `make_golden_vectors.py`(P2.7 생성), `verify_p1_artifacts.py`(전수 검증) |
| `model_develop/references/` | 선행 SpikeSense-Edge 코드 원본. 수정하지 않고 참고용으로만 둔다 |
| `analysis_develop/` | 분석·그래프 코드. `analyze_runs.py`(학습 기록 → 요약표·곡선), `exp_lowscore.py`(학습 방식 비교 실험), `check_numpy_fp.py`(선행 NumPy 재현·NumPy↔PyTorch FP 일치 검증, 결과 `numpy_fp/`), `compare_quant.py`(INT8 ↔ FP32 40대 정확도 비교), `quant_variants.py`(양자화 후보 비교). 두 결과는 `quant_int8/` |
| `analysis_data/` | 분석 산출물. `all40/`(40대 결과표·학습 기록·보고서), `figures/`(논문용 그림) |
| `model_weights/` | 장비별 체크포인트 `<기종>_id<ID>/{last.pth, best_val.pth}`. 채택본은 `last.pth` |
| `data/dataset_dcase/` | DCASE 2020 Task 2 원본 wav + `eval_data_list.csv` |
| `data/mel_dcase/` | mel 특징 세그먼트 캐시 `<장비>_<split>_seg31[_hop16].npz` |

## 장비 이름 규칙

`<기종>_id<ID 두 자리>` (예: `fan_id01`). 기종은 DCASE 폴더 이름 그대로 `fan`, `pump`,
`slider`, `valve`, `ToyCar`, `ToyConveyor`이고 ID는 wav 파일명 `normal_id_00_*.wav`의 두 자리다.
`pump`·`valve` 00–06, `fan` 01–06, `slider` 00–06, `ToyCar` 01–07, `ToyConveyor` 01–06으로 모두 40대이며
모델 1개가 장비 1대를 맡는다. 41대 중 `fan` id_00을 제외했고 그 wav는 삭제했다
(제외 장비 선정 경위는 `analysis_data/REPORT.md` 참고).
