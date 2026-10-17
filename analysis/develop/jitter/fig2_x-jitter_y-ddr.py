"""jitter 0.8~20 ms × entry 수의 DDR3 KiB/추론 (P3.17)

입력: simulation/result/p317_jitter_wide.csv
"""
import os
import sys

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.sim_style()
from matplotlib.lines import Line2D  # noqa: E402

rows = cm.points("p317_jitter_wide")
Js = sorted({r["jitter_ms"] for r in rows})
Es = sorted({r["entries"] for r in rows})
pt = {(r["jitter_ms"], r["entries"]): r for r in rows}
ratio = np.mean([r["ddr_mbps"] / r["dram_kib"] for r in rows])          # 모든 점의 추론 요청 수가 같아 MB/s ∝ KiB/추론
col = dict(zip(Es, cm.BLUE[2:]))
fig, ax = plt.subplots(figsize=(7.2, 3.6))
x = np.arange(len(Js))
for E in Es:
    ax.plot(x, [pt[(j, E)]["dram_kib"] for j in Js], color=col[E], linewidth=2, marker="o", markersize=4,
            markeredgecolor=cm.SURF, markeredgewidth=1)
need = [max(2, int(np.ceil(j / 0.8 - 1e-9))) for j in Js]                # 필요 entry ≈ ⌈jitter ÷ 0.8 ms⌉
for xi, j, n in zip(x, Js, need):
    if n in Es:
        ax.scatter(xi, pt[(j, n)]["dram_kib"], s=90, facecolor="none", edgecolor=cm.INK, linewidth=1.2, zorder=4)
ax.set_yscale("log")
ax.set_yticks([5, 10, 20, 50, 100], ["5", "10", "20", "50", "100"])
ax.set_xticks(x, [f"{j:g}" if j < 32 else "32\n(offset 배정 없음과 같음)" for j in Js], fontsize=8)
ax.set_xlabel("jitter ms (같은 모델 트랙의 도착 퍼짐)")
ax.set_ylabel("DDR3 KiB/추론")
sec = ax.secondary_yaxis("right", functions=(lambda k: k * ratio, lambda m: m / ratio))
sec.set_ylabel("DDR3 MB/s")
sec.set_yticks([200, 500, 1000, 2000], ["200", "500", "1,000", "2,000"])
sec.tick_params(length=0)
sec.yaxis.set_minor_formatter(plt.NullFormatter())
ax.set_xlim(-0.3, len(Js) - 0.7)
cm.clean(ax)
h = [Line2D([], [], color=col[E], linewidth=2, label=f"entry {E}") for E in Es]
h.append(Line2D([], [], color=cm.INK, marker="o", markerfacecolor="none", linestyle="", markersize=9,
                label="필요 entry = jitter ÷ 0.8 ms 올림(최소 2)"))
cm.header(fig, f"그림 1. entry 10개로 버티는 jitter는 약 8 ms까지다. jitter 10~20 ms면 DDR3 전송량이 "
          f"{pt[(10.0, 10)]['dram_kib'] / pt[(0.8, 4)]['dram_kib']:.1f}~{pt[(20.0, 10)]['dram_kib'] / pt[(0.8, 4)]['dram_kib']:.1f}배로 는다",
          "simulation, 제안 구성(offset 배정, Grouping, offset-order cache, 12 bit membrane potential 일부 on-chip), 즉시 전송. 시나리오 6 × seed 10. "
          "모든 점 deadline miss 0, 최대 응답 시간 1.2 ms 이하", legend=h, top=0.80)
cm.save(fig, __file__, dpi=170, bbox_inches="tight")
