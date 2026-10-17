"""트랙 1,024~4,096에서 방법별 DDR3 MB/s와 최대 응답 시간 열지도, spike 2개/cycle (P3.21)

입력: simulation/result/p321_scale_run.csv (entry 4, seed 0~2)
"""
import os
import sys

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.sim_style()
from matplotlib.colors import LogNorm  # noqa: E402

pts = cm.points("p321_scale_run")
names = [n for n in cm.METHOD_ORDER if any(r["label"].startswith(n + " ·") for r in pts)]
Ns = sorted({r["tracks"] for r in pts})
pt = {(r["label"].split(" · ")[0], r["tracks"]): r for r in pts}
fig, axes = plt.subplots(1, 2, figsize=(9.0, 3.4))
for ax, key, lab, norm in ((axes[0], "ddr_mbps", "DDR3 MB/s", LogNorm(100, 3015)),
                           (axes[1], "max_ms", "최대 응답 시간 ms", LogNorm(0.5, 100))):
    v = np.array([[pt[(n, N)][key] for N in Ns] for n in names])
    ax.imshow(np.minimum(v, norm.vmax), cmap=cm.seq_cmap(), norm=norm, aspect="auto")
    for (yi, xi), x in np.ndenumerate(v):
        r = pt[(names[yi], Ns[xi])]
        t = f"{x:,.0f}" if key == "ddr_mbps" or x >= 10 else f"{x:.1f}"
        ax.text(xi, yi, t + ("*" if r["miss"] > 0 else ""), ha="center", va="center", fontsize=7.5,
                color=cm.SURF if norm(min(x, norm.vmax)) > 0.55 else cm.INK, fontweight="bold" if yi == len(names) - 1 else None)
    ax.axhline(1.5, color=cm.INK, linewidth=1.2)
    ax.set_xticks(range(len(Ns)), [f"{N:,}" for N in Ns], fontsize=8)
    ax.set_yticks(range(len(names)), names if ax is axes[0] else [""] * len(names), fontsize=8)
    ax.set_xlabel("트랙 수")
    ax.set_title(lab, loc="left", fontsize=9)
    ax.grid(False)
    cm.clean(ax)
cm.header(fig, "그림 14. 4,096트랙에서 SW+HW는 DDR3 335 MB/s·최대 응답 시간 11.5 ms, Dysta Method는 1,403 MB/s·27.9 ms(deadline까지 4 ms)",
          "simulation, 같은 BRAM(entry 4)·trace·DDR3 3,015 MB/s, spike 2개/cycle, jitter 0.8 ms, 시나리오 6 × seed 3. * = deadline miss 있음",
          top=0.84)
cm.save(fig, __file__, dpi=170, bbox_inches="tight")
