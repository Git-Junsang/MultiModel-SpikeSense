# 학습 결과 그림

Code: `collect_scores.py`, `make_figures.py`

PDF는 vector, PNG는 300 dpi preview다.

| 파일 | 내용 | 핵심 값 |
|---|---|---|
| `fig1_auc_per_unit` | 장비별 ROC-AUC | 평균 0.9563, 0.9 이상 35대 |
| `fig2_auc_by_type` | 기종별 AUC | valve 평균 0.9067 |
| `fig3_training_curves` | epoch별 AUC | 30~50 epoch에서 포화 |
| `fig4_checkpoint_selection` | checkpoint 비교 | 0.8479→0.9563 |
| `fig5_roc` | 장비별 ROC | pAUC 평균 0.9209 |
| `fig6_membrane_headroom` | INT16 여유 | L3 최대 16,707 |
| `fig7_model_size_bram` | weight와 BRAM | L2 75.5 %, 막전위 706 KiB |

## 원자료

| 파일 | 내용 |
|---|---|
| `scores.npz` | 장비별 file score와 label |
| `membrane_headroom.csv` | 장비·layer별 membrane 최대 |

## 재생성

```bash
cd software/analysis_develop
python3 collect_scores.py
python3 make_figures.py
```

`collect_scores.py`는 GPU가 필요하다.

## 주의

- Supervised DCASE 조건이다. Official leaderboard와 비교하지 않는다.
- 41대 중 `fan_id00`을 평가 뒤 제외했다. 41대 평균은 0.9510이다.
- `fig7` BRAM은 당시 가정이다. 최신값은 [ONCHIP_MEMORY.md](../../../documents/design/ONCHIP_MEMORY.md)를 따른다.
