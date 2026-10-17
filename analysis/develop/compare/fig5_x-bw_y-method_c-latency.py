"""DDR3 대역폭을 줄일 때 방법별 평균·최대 응답 시간 열지도 (P3.21)

입력: simulation/result/p321_compare_ddrbw.csv (entry 4, 시나리오 6 × seed 3, 조절값 고정)
"""
import os
import sys

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.sim_style()
from matplotlib.colors import LogNorm  # noqa: E402

pts = cm.points("p321_compare_ddrbw")
names = [n for n in cm.METHOD_ORDER if any(r["label"].startswith(n + " ·") for r in pts)]
Bs = sorted({r["bw_mbps"] for r in pts}, reverse=True)
pt = {(r["label"].split(" · ")[0], r["bw_mbps"]): r for r in pts}
fig, axes = plt.subplots(1, 2, figsize=(9.4, 3.9))
for ax, key, lab, norm in ((axes[0], "mean_ms", "평균 응답 시간 ms", LogNorm(0.1, 32)),
                           (axes[1], "max_ms", "최대 응답 시간 ms", LogNorm(0.5, 64))):
    v = np.array([[pt[(n, b)][key] for b in Bs] for n in names])
    ax.imshow(np.minimum(v, norm.vmax), cmap=cm.seq_cmap(), norm=norm, aspect="auto")
    for (yi, xi), x in np.ndenumerate(v):
        miss = pt[(names[yi], Bs[xi])]["miss"] > 0
        ax.text(xi, yi, (f"{x:.0f}" if x >= 10 else f"{x:.1f}" if x >= 1 else f"{x:.2f}") + ("*" if miss else ""),
                ha="center", va="center", fontsize=7.5, color=cm.SURF if norm(min(x, norm.vmax)) > 0.55 else cm.INK,
                fontweight="bold" if yi == len(names) - 1 else None)
    ax.axhline(1.5, color=cm.INK, linewidth=1.2)
    ax.set_xticks(range(len(Bs)), [f"{b:,.0f}" for b in Bs], fontsize=8)
    ax.set_yticks(range(len(names)), names if ax is axes[0] else [""] * len(names), fontsize=8)
    ax.set_xlabel("DDR3 대역폭 MB/s (3,015 = 보드 실측)")
    ax.set_title(lab, loc="left", fontsize=9)
    ax.grid(False)
    cm.clean(ax)
cm.header(fig, "그림 12. DDR3 대역폭을 줄여도 SW·HW 협력 설계는 응답 시간이 그대로다. 비교군은 대역폭이 줄면 응답 시간이 커진다",
          "simulation, 같은 BRAM(entry 4)·trace, jitter 0.8 ms, 시나리오 6 × seed 3, 조절값 고정. * = deadline miss 있음", top=0.86)
cm.save(fig, __file__, dpi=170, bbox_inches="tight")
