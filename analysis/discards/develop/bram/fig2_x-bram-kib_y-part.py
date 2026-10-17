"""BRAM 예산 구성, 중간보고 기준 512트랙·막전위 on-chip (P2.6, 옛 fig7_model_size_bram 오른쪽)
"""
import os
import sys

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.model_style()

parts = [("Membrane state\n512 tracks × 706", 706.0, "#3b6ea5"),
         ("Model cache (1×)", 127.125, "#4f9a55"),
         ("Prefetch buffer (1×)", 127.125, "#c9a227"),
         ("Other (reserved)", 100.0, "#9a4f8f"),
         ("Free", 1642.5 - 706.0 - 127.125 * 2 - 100.0, "0.85")]
fig, ax = plt.subplots(figsize=(3.5, 2.5))
left = 0
for lab, v, c in parts:
    ax.barh(0, v, left=left, color=c, edgecolor="k", lw=0.5, height=0.5, label=f"{lab} — {v:.1f} KiB")
    left += v
ax.set_xlim(0, 1642.5); ax.set_ylim(-0.32, 0.32); ax.set_yticks([])
ax.set_xlabel("On-chip BRAM (KiB), XC7A200T total 1,642.5")
ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.22), ncol=2, frameon=False, fontsize=7)
ax.grid(False)
cm.save(fig, __file__, exts=("pdf", "png"), dpi=300)
