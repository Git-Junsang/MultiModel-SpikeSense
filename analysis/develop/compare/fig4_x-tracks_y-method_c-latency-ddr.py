"""트랙 수 512~1,536에서 방법별 최대 응답 시간과 DDR3 MB/s 열지도 (P3.21)

입력: simulation/result/p321_compare_tracks.csv (entry 4, seed 5)
"""
import os
import sys

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.sim_style()
from matplotlib.colors import LogNorm  # noqa: E402

pts = cm.points("p321_compare_tracks")
names = [n for n in cm.METHOD_ORDER if any(r["label"].startswith(n + " ·") for r in pts)]
Ns = sorted({r["tracks"] for r in pts})
pt = {(r["label"].split(" · ")[0], r["tracks"]): r for r in pts}
fig, axes = plt.subplots(1, 2, figsize=(9.0, 3.9))
for ax, key, lab, norm, fmt in ((axes[0], "max_ms", "최대 응답 시간 ms", LogNorm(0.5, 100), "{:.1f}"),
                                (axes[1], "ddr_mbps", "DDR3 MB/s", LogNorm(100, 3015), "{:,.0f}")):
    v = np.array([[pt[(n, N)][key] for N in Ns] for n in names])
    ax.imshow(v, cmap=cm.seq_cmap(), norm=norm, aspect="auto")
    for (yi, xi), x in np.ndenumerate(v):
        miss = pt[(names[yi], Ns[xi])]["miss"] > 0
        ax.text(xi, yi, (f"{x:.0f}" if x >= 100 and key == "max_ms" else fmt.format(x)) + ("*" if miss else ""),
                ha="center", va="center", fontsize=7.5, color=cm.SURF if norm(x) > 0.55 else cm.INK,
                fontweight="bold" if yi == len(names) - 1 else None)
    ax.axhline(1.5, color=cm.INK, linewidth=1.2)
    ax.set_xticks(range(len(Ns)), [f"{N:,}" for N in Ns], fontsize=8)
    ax.set_yticks(range(len(names)), names if ax is axes[0] else [""] * len(names), fontsize=8)
    ax.set_xlabel("트랙 수")
    ax.set_title(lab, loc="left", fontsize=9)
    ax.grid(False)
    cm.clean(ax)
cm.header(fig, "그림 11. 트랙이 512 → 1,536개로 3배가 돼도 SW·HW 협력 설계의 DDR3는 154 → 197 MB/s다",
          "simulation, 같은 BRAM(entry 4 + 남는 BRAM에 12 bit membrane potential)·trace·DDR3 조건, jitter 0.8 ms, 시나리오 6 × seed 5. "
          "* = deadline miss 있음", top=0.86)
cm.save(fig, __file__, dpi=170, bbox_inches="tight")
