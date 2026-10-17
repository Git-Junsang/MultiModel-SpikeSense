"""BRAM 배분: membrane potential 12 bit vs layer별 [9, 9, 9, 12] bit의 entry 수별 DDR3 KiB/추론 (P3.19)

입력: simulation/result/p319_layer_bits.csv
"""
import os
import sys

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.sim_style()
from matplotlib.lines import Line2D  # noqa: E402

rows = cm.points("p319_layer_bits")
cm.engine.sc.configure(64, 1024, mem="ddr", rev=4, arch=cm.engine.ARCHS["L"])     # entry 1개 tile 수(ENTRY_T)
Js = sorted({r["jitter_ms"] for r in rows})
Es = sorted({r["entries"] for r in rows})
B = {"12": ("12 bit", cm.GRAY), "[9, 9, 9, 12]": ("layer별 [9, 9, 9, 12] bit", cm.SERIES[0])}
pt = {(r["jitter_ms"], str(r["bits"]), r["entries"]): r for r in rows}
TOP = 8.0
fig, axes = plt.subplots(1, 3, figsize=(8.4, 3.2), sharey=True)
x = np.arange(len(Es))
for ax, j in zip(axes, Js):
    for b, (_, c) in B.items():
        v = np.array([pt[(j, b, E)]["dram_kib"] for E in Es])
        ax.plot(x, np.where(v > TOP, np.nan, v), color=c, linewidth=2, marker="o", markersize=4,
                markeredgecolor=cm.SURF, markeredgewidth=1)
        for xi, y in zip(x, v):
            if y > TOP:
                ax.scatter(xi, TOP - 0.08, marker="^", s=36, color=c, edgecolor=cm.SURF, zorder=4)
                ax.text(xi + 0.15, TOP - 0.08 - (0.18 if b == "12" else 0.36), f"{y:.0f}", fontsize=7, color=c, va="center")
    on = {b: [cm.engine.onchip_tracks(pt[(j, b, E)]) for E in Es] for b in B}
    ax.set_xticks(x, [f"{E}\n{a:,}\n{c:,}" for E, a, c in zip(Es, on["12"], on["[9, 9, 9, 12]"])], fontsize=7.5)
    ax.set_title(f"jitter {j:g} ms", loc="left", fontsize=9)
    ax.set_ylim(5.5, TOP)
    cm.clean(ax)
axes[0].set_ylabel("DDR3 KiB/추론")
axes[1].set_xlabel("weight entry 수 (아래: on-chip membrane potential 트랙 수, 12 bit / layer별)")
h = [Line2D([], [], color=c, linewidth=2, label=lb) for lb, c in B.values()]
h.append(Line2D([], [], color=cm.MUTED, marker="^", linestyle="", label="8 KiB 넘음(값)"))
cm.header(fig, "그림 6. layer별 bit [9, 9, 9, 12]면 entry 4에서 1,024트랙 membrane potential이 모두 on-chip에 들어간다",
          "simulation, 제안 구성에서 membrane potential 저장 bit만 바꿈. 9 bit는 BRAM의 9 bit 폭을 그대로 써 8 bit와 tile 수가 같다. "
          "시나리오 6 × seed 10, 모든 점 deadline miss 0", legend=h, top=0.80)
cm.save(fig, __file__, dpi=170, bbox_inches="tight")
