"""layer별 membrane potential 최대 |값|과 INT16 한계, L_normal_noaug INT8 (P2.5, 옛 fig6_membrane_headroom)

입력: software/train_result/eval/scores/membrane_headroom.csv (software/model/eval/scores.py)
"""
import csv
import os
import sys

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.model_style()

with open(os.path.join(cm.TRAIN, "eval", "scores", "membrane_headroom.csv")) as f:
    rows = list(csv.DictReader(f))
layers = ["L1", "L2", "L3", "L4"]
V = np.array([[float(r[l]) for l in layers] for r in rows])
fig, ax = plt.subplots(figsize=(3.4, 2.6))
bp = ax.boxplot([V[:, i] for i in range(4)], patch_artist=True, widths=0.55,
                medianprops=dict(color="k", lw=1.1), flierprops=dict(ms=3))
for p in bp["boxes"]:
    p.set_facecolor("#3b6ea5"); p.set_alpha(0.5); p.set_edgecolor("k"); p.set_linewidth(0.7)
ax.axhline(32767, color="#c0623b", lw=1.2, ls="--")
ax.text(4.45, 32767 * 1.06, "INT16 limit\n32,767", color="#c0623b", fontsize=7.5, ha="right")
ax.set_yscale("log"); ax.set_ylim(3e2, 8e4)
ax.set_xticklabels([f"{l}\n({n})" for l, n in zip(layers, [384, 256, 64, 2])])
ax.set_ylabel("Peak |membrane| (integer units)")
ax.set_xlabel("Layer")
cm.save(fig, __file__, exts=("pdf", "png"), dpi=300)
