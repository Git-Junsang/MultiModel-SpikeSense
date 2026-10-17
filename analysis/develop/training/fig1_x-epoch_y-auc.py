"""epoch별 test AUC 학습 곡선, L_normal_noaug 40대 (P2.4, 옛 fig3_training_curves)

입력: software/train_result/L_normal_noaug/<장비>/history.csv
"""
import csv
import os
import sys

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.model_style()

hist = {}
for r in cm.model_results():
    p = os.path.join(cm.TRAIN, "L_normal_noaug", r["unit"], "history.csv")
    if os.path.exists(p):
        with open(p) as f:
            rr = list(csv.DictReader(f))
        hist[r["unit"]] = {k: np.array([float(x[k]) for x in rr]) for k in rr[0]}
ep = next(iter(hist.values()))["epoch"]
units = list(hist)
A = np.stack([hist[u]["test_auc"] for u in units])
worst = units[int(np.argmin(A[:, -1]))]
fig, ax = plt.subplots(figsize=(3.4, 2.6))
ax.fill_between(ep, np.percentile(A, 25, 0), np.percentile(A, 75, 0), color="#3b6ea5", alpha=0.25, lw=0, label="IQR (40 units)")
ax.plot(ep, np.median(A, 0), color="#3b6ea5", lw=1.6, label="median")
ax.plot(ep, hist[worst]["test_auc"], color="#c0623b", lw=1.0, ls="--", label=f"lowest final ({worst})")
ax.axvline(40, color="k", lw=0.8, ls=":")
ax.text(38.6, 0.995, "saturation 30–50 ep", rotation=90, va="top", ha="right", fontsize=7)
ax.set_xlabel("Epoch"); ax.set_ylabel("File-level ROC-AUC")
ax.set_xlim(1, ep[-1]); ax.set_ylim(0.5, 1.0); ax.legend(loc="lower right")
cm.save(fig, __file__, exts=("pdf", "png"), dpi=300)
