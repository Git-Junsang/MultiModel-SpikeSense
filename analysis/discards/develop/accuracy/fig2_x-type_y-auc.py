"""장비 종류별 AUC 분포, L_normal_noaug (P2.4, 옛 fig2_auc_by_type)

입력: software/train_result/L_normal_noaug/results.csv
"""
import os
import sys

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.model_style()

rows = cm.model_results()
np.random.seed(0)
g = {t: [float(r["test_auc"]) for r in rows if cm.mtype(r["unit"]) == t] for t in cm.TYPES}
fig, ax = plt.subplots(figsize=(3.4, 2.6))
bp = ax.boxplot([g[t] for t in cm.TYPES], patch_artist=True, widths=0.6,
                medianprops=dict(color="k", lw=1.1), flierprops=dict(ms=3))
for patch, t in zip(bp["boxes"], cm.TYPES):
    patch.set_facecolor(cm.TYPE_COLOR[t]); patch.set_alpha(0.55); patch.set_edgecolor("k")
    patch.set_linewidth(0.7)
for i, t in enumerate(cm.TYPES, 1):
    ax.scatter(np.full(len(g[t]), i) + np.random.uniform(-.13, .13, len(g[t])), g[t], s=7, color="k", alpha=0.6, zorder=3)
ax.set_xticklabels([t.replace("ToyConveyor", "TConv").replace("ToyCar", "TCar") for t in cm.TYPES], rotation=30, ha="right")
ax.set_ylabel("File-level ROC-AUC"); ax.set_ylim(0.75, 1.02)
cm.save(fig, __file__, exts=("pdf", "png"), dpi=300)
