"""Host offset 단위 모아 보내기: 대기 D × jitter의 DDR3 KiB/추론과 최대 응답 시간, entry 2 (P3.17)

입력: simulation/result/p317_gather.csv
"""
import os
import sys

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.sim_style()
from matplotlib.lines import Line2D  # noqa: E402

rows = [r for r in cm.points("p317_gather") if r["entries"] == 2]
Js = sorted({r["jitter_ms"] for r in rows})
Ds = sorted({r["gather_ms"] for r in rows})
pt = {(r["jitter_ms"], r["gather_ms"]): r for r in rows}
col = dict(zip(Js, cm.BLUE[2:]))
x = np.arange(len(Ds))
fig, axes = plt.subplots(1, 2, figsize=(8.4, 3.3))
for ax, key, lab in zip(axes, ("dram_kib", "max_ms"), ("DDR3 KiB/추론", "최대 응답 시간 ms")):
    for j in Js:
        ax.plot(x, [pt[(j, d)][key] for d in Ds], color=col[j], linewidth=2, marker="o", markersize=4,
                markeredgecolor=cm.SURF, markeredgewidth=1)
        k = Ds.index(j)                                                   # D = jitter인 점
        ax.scatter(x[k], pt[(j, j)][key], s=80, facecolor="none", edgecolor=cm.INK, linewidth=1.1, zorder=4)
    ax.set_xticks(x, ["0\n즉시" if d == 0 else f"{d:g}" for d in Ds], fontsize=8)
    ax.set_xlabel("offset 단위 모아 보내기 대기 D ms")
    ax.set_title(lab, loc="left", fontsize=9)
    cm.clean(ax)
axes[0].set_yscale("log")
axes[0].set_yticks([5, 10, 20, 50, 100], ["5", "10", "20", "50", "100"])
axes[1].axhline(32, color=cm.INK, linewidth=0.8, linestyle=(0, (3, 3)))
axes[1].text(x[0], 31, "deadline 32 ms", fontsize=7.5, va="top")
axes[1].set_ylim(0, 34)
h = [Line2D([], [], color=col[j], linewidth=2, label=f"jitter {j:g} ms") for j in Js]
h.append(Line2D([], [], color=cm.INK, marker="o", markerfacecolor="none", linestyle="", markersize=8, label="D = jitter"))
cm.header(fig, "그림 2. offset 단위 모아 보내기(D ≥ jitter)면 entry 2로 jitter와 상관없이 6.3 KiB/추론. 대신 최대 응답 시간이 약 jitter만큼 는다",
          "simulation, 제안 구성에서 entry 2, 보내기 방식만 바꿈. 모델·주기마다 요청이 다 준비되거나 offset + D가 되면 한꺼번에 보낸다. "
          "시나리오 6 × seed 10, 모든 점 deadline miss 0", legend=h, top=0.78)
cm.save(fig, __file__, dpi=170, bbox_inches="tight")
