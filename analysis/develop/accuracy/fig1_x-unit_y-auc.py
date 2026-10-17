"""장비별 파일 단위 ROC-AUC, L_normal_noaug (P2.4, 옛 fig1_auc_per_unit)

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
auc = np.array([float(r["test_auc"]) for r in rows])
units = [r["unit"] for r in rows]
fig, ax = plt.subplots(figsize=(7.0, 2.8))
ax.bar(range(len(auc)), auc, color=[cm.TYPE_COLOR[cm.mtype(u)] for u in units], width=0.78)
ax.axhline(auc.mean(), color="k", ls="--", lw=0.9)
ax.text(0.3, auc.mean() - 0.012, f"mean {auc.mean():.3f}", ha="left", va="top", fontsize=8)
ax.set_xticks(range(len(auc)))
ax.set_xticklabels([u.replace("ToyConveyor", "TConv").replace("ToyCar", "TCar") for u in units], rotation=90, fontsize=6)
ax.set_ylim(0.5, 1.02); ax.set_ylabel("File-level ROC-AUC")
ax.set_xlim(-0.8, len(auc) - 0.2)
ax.legend(handles=[Line2D([], [], color=cm.TYPE_COLOR[t], lw=5, label=t) for t in cm.TYPES],
          ncol=6, loc="lower center", bbox_to_anchor=(0.5, 1.0), frameon=False)
cm.save(fig, __file__, exts=("pdf", "png"), dpi=300)
