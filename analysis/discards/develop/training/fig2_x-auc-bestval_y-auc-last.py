"""체크포인트 선택: val loss 최소 시점 대 마지막 epoch의 AUC, L_normal_noaug (P2.4, 옛 fig4_checkpoint_selection)

입력: software/train_result/L_normal_noaug/results.csv
"""
import os
import sys

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.model_style()
from matplotlib.lines import Line2D  # noqa: E402

rows = cm.model_results()
last = np.array([float(r["test_auc"]) for r in rows])
best = np.array([float(r["test_auc_bestval"]) for r in rows])
fig, ax = plt.subplots(figsize=(3.4, 3.0))
ax.plot([0.2, 1.0], [0.2, 1.0], color="k", lw=0.8, ls="--")
for r, b, l in zip(rows, best, last):
    ax.scatter(b, l, s=22, color=cm.TYPE_COLOR[cm.mtype(r["unit"])], edgecolor="k", lw=0.4, zorder=3)
ax.set_xlabel("AUC — min-val-loss checkpoint")
ax.set_ylabel("AUC — final epoch (adopted)")
ax.set_xlim(0.2, 1.02); ax.set_ylim(0.2, 1.02); ax.set_aspect("equal")
ax.text(0.24, 0.97, f"mean {best.mean():.4f} → {last.mean():.4f}", fontsize=8)
ax.legend(handles=[Line2D([], [], marker="o", ls="", mfc=cm.TYPE_COLOR[t], mec="k", ms=5, label=t) for t in cm.TYPES],
          loc="lower right", frameon=False, fontsize=7, ncol=2, handletextpad=0.3, columnspacing=0.8)
cm.save(fig, __file__, exts=("pdf", "png"), dpi=300)
