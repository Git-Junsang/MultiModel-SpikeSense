"""층별 INT8 weight byte, L (130,176 B) (P2.6, 옛 fig7_model_size_bram 왼쪽)
"""
import os
import sys

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.model_style()

w = [15360, 98304, 16384, 128]
fig, ax = plt.subplots(figsize=(3.5, 2.5))
b = ax.bar(["L1\n40→384", "L2\n384→256", "L3\n256→64", "L4\n64→2"], w, color="#3b6ea5", width=0.6)
for r, v in zip(b, w):
    ax.text(r.get_x() + r.get_width() / 2, v + 2500, f"{v:,}\n({v/sum(w)*100:.1f}%)", ha="center", fontsize=7.5)
ax.set_ylabel("INT8 weights (bytes)"); ax.set_ylim(0, 118000)
ax.set_title(f"Model = {sum(w):,} B = 127.125 KiB", pad=4)
cm.save(fig, __file__, exts=("pdf", "png"), dpi=300)
