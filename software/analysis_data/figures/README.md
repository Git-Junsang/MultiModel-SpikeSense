# 논문용 그림

생성일: 2026-09-23 | 생성: `software/analysis_develop/collect_scores.py` → `make_figures.py`

각 그림은 `.pdf`(벡터, 본문 삽입용)와 `.png`(300 dpi, 미리보기용)로 같은 이름으로 나온다.
라벨은 영문이다. 한글이 필요하면 `make_figures.py`의 `font.family`를 `Noto Sans CJK KR`로 바꾼다
(이 서버에 설치돼 있다).

| 파일 | 크기(in) | 내용 | 설명문에 쓸 수치 |
|---|---|---|---|
| `fig1_auc_per_unit` | 7.0 × 2.8 | 장비 40대의 파일 단위 ROC-AUC 막대그래프, 기종별 색 | 평균 0.9563, 0.9 이상 35대, 최저 0.8175 |
| `fig2_auc_by_type` | 3.4 × 2.6 | 기종별 AUC 분포(상자그림 + 개별 점) | slider 0.973 … valve 0.907 |
| `fig3_training_curves` | 3.4 × 2.6 | 에포크별 test AUC의 중앙값·사분위 범위, 최종 최저 장비 | 30~50에포크에서 포화 → 60에포크 채택 근거 |
| `fig4_checkpoint_selection` | 3.4 × 3.0 | val loss 최소 시점 vs 마지막 에포크 AUC 산점도 | 평균 0.8479 → 0.9563, 40대 모두 대각선 위 |
| `fig5_roc` | 3.4 × 3.0 | 40대 ROC 곡선(회색) + 최저·1사분위·중앙·최고 강조, pAUC 구간 음영 | pAUC 평균 0.9134 |
| `fig6_membrane_headroom` | 3.4 × 2.6 | 층별 막전위 최대치(하드웨어 정수 단위)와 INT16 한계 | L3가 최악 16,707 = 한계의 51.0%, 초과 0/40 |
| `fig7_model_size_bram` | 7.0 × 2.5 | (좌) 층별 INT8 가중치 바이트 (우) BRAM 예산 분할 | L2가 98,304 B = 75.5%, 막전위 706 KiB = 43.3% |

## 원자료

| 파일 | 내용 |
|---|---|
| `scores.npz` | 장비별 파일 단위 이상 점수와 정답. 평가 분할은 `train.prepare`와 동일(학습에 쓴 이상 파일 절반 제외)이며, 여기서 계산한 AUC는 `../results.csv`의 `test_auc`와 최대 5e-5 차이로 일치한다 |
| `membrane_headroom.csv` | 장비별·층별 막전위 최대치(정수 단위). 환산 규칙은 선행 `export_weights.py`의 `scale_W = max|W| / 127` |

## 다시 만들기

```
cd software/analysis_develop
python3 collect_scores.py     # GPU 필요, 40대 추론 약 2분
python3 make_figures.py       # GPU 불필요
```

## 주의

- AUC는 **실제 이상 파일 절반을 학습에 쓴 지도학습 조건**에서 나온 값이다. DCASE 2020 공식
  순위표(정상만으로 학습)와 직접 비교하지 않는다.
- 40대는 41대 중 `fan_id00`을 제외한 구성이고, 그 제외는 학습 결과를 보고 한 선택이다.
  41대 기준 평균은 0.9510이다. 경위는 `../REPORT.md`에 있다.
- `fig7`의 BRAM 분할은 PROPOSAL.md §3.2의 **기준 배분 가정**이지 실측 점유가 아니다.
