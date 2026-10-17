"""장비별 ROC 곡선, L_normal_noaug (P2.4, 옛 fig5_roc)

입력: software/train_result/L_normal_noaug/results.csv, software/train_result/eval/scores/scores.npz
      (scores.npz가 없으면 software/model/eval/scores.py, GPU 필요)
"""
import os
import sys

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.model_style()
from sklearn.metrics import roc_curve  # noqa: E402

rows = cm.model_results()
d = np.load(os.path.join(cm.TRAIN, "eval", "scores", "scores.npz"))
auc = np.array([float(r["test_auc"]) for r in rows])
order = np.argsort(auc)
pick = [("worst", order[0]), ("25th pct", order[len(order) // 4]), ("median", order[len(order) // 2]), ("best", order[-1])]
fig, ax = plt.subplots(figsize=(3.4, 3.0))
for r in rows:   # 배경: 40대 전부
    fpr, tpr, _ = roc_curve(d["label__" + r["unit"]], d["score__" + r["unit"]])
    ax.plot(fpr, tpr, color="0.75", lw=0.5, alpha=0.7, zorder=1)
for (lab, i), c in zip(pick, ["#c0623b", "#c9a227", "#4f9a55", "#3b6ea5"]):
    u = rows[i]["unit"]
    fpr, tpr, _ = roc_curve(d["label__" + u], d["score__" + u])
    ax.plot(fpr, tpr, color=c, lw=1.5, zorder=3,
            label=f"{lab}: {u.replace('ToyConveyor','TConv').replace('ToyCar','TCar')} ({auc[i]:.3f})")
ax.plot([0, 1], [0, 1], color="k", lw=0.7, ls="--")
ax.axvspan(0, 0.1, color="k", alpha=0.06, lw=0)
ax.text(0.115, 0.30, "pAUC region\n(FPR ≤ 0.1)", fontsize=7, color="0.35")
ax.set_xlabel("False positive rate"); ax.set_ylabel("True positive rate")
ax.set_xlim(0, 1); ax.set_ylim(0, 1.005); ax.set_aspect("equal")
ax.legend(loc="lower right", fontsize=7)
cm.save(fig, __file__, exts=("pdf", "png"), dpi=300)
