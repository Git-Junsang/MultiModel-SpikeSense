# software

| 폴더 | 내용 |
|---|---|
| `model_develop/` | SNN 모델, 학습, FP32·INT8 reference, model export |
| `model_develop/references/` | 선행 프로젝트 코드 사본. 수정하지 않음 |
| `analysis_develop/` | 정확도, 양자화, DDR3·PCIe 분석 코드와 원자료 |
| `analysis_result/` | 학습 결과와 그림 |
| `sim_develop/` | scheduler·저장 정책 architecture simulation |
| `sim_result/` | simulation 표, JSONL, 그림 |
| `model_weights/` | 장비별 checkpoint |
| `data/` | DCASE dataset과 mel cache |

장비 이름은 `<종류>_id<번호>`로 쓴다. 예: `fan_id01`, `ToyCar_id03`.

주요 문서:

- 학습 결과: [REPORT.md](analysis_result/REPORT.md)
- simulation 결과 읽기: [sim_result/INDEX.md](sim_result/INDEX.md)
- simulation 조건: [SIM_PLAN.md](../documents/design/SIM_PLAN.md)

전체 검증 명령은 각 report의 `재현` 절을 따른다.
