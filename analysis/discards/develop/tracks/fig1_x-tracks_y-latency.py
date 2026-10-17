"""트랙 수별 최대 응답, 연산(dense, spike 1·2개/cycle) × 정렬 끔/켬, 동시 도착 S (P3.13 그림 5, 옛 fig45_p313_capacity)

입력: simulation/result/p313_capacity.csv, p313_capacity_runs.csv.gz
"""
import os
import sys

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.sim_style()
SUB = "시뮬레이션, L·64 lane, 1,024트랙, 즉시 입출력, spike 건너뛰기"
from matplotlib.lines import Line2D  # noqa: E402

sc = cm.engine.sc
pts = cm.points("p313_capacity")
runs = cm.by_point(cm.runs("p313_capacity"))
ns = sorted({r["tracks"] for r in pts})
CNAME = {0: "dense", 1: "spike 1개/cycle", 2: "spike 2개/cycle"}
ANAME = {"none": "정렬 끔", "model": "정렬 켬"}
ccol = {0: cm.INK, 1: cm.SERIES[0], 2: cm.SERIES[2]}
style = {"none": "-", "model": (0, (4, 2))}
smax = {(r["tracks"], r["spk"], r["align"]): cm.agg([x for x in runs[r["point"]] if x["scn"] == "S"])["max_ms"] for r in pts}
h2c, c2h = sc.load_samples(sc.D_IN_FILE).max(), sc.load_samples(sc.D_OUT_FILE).max()
fig, ax = plt.subplots(figsize=(7.2, 3.6))
worst = []
for n in ns:
    sc.configure(64, n, mem="ddr", rev=4, arch=cm.engine.ARCHS["L"])
    worst.append((h2c + sc.T0 + sc.MODEL_B / sc.BW + n * sc.C_REQ + c2h) / 1000)
ax.plot(ns, worst, color=cm.GRAY, linewidth=1, linestyle=(0, (1, 2)), zorder=1)
ax.text(ns[-1] + 12, worst[-1], "최악 계산\ndense", fontsize=7.5, color=cm.MUTED, ha="left", va="center")
for c in CNAME:
    for a, ls in style.items():
        v = np.array([smax[(n, c, a)] for n in ns])
        over = v > 40
        ax.plot(ns, np.where(over, np.nan, v), color=ccol[c], linewidth=2, linestyle=ls, marker="o", markersize=4,
                markeredgecolor=cm.SURF, markeredgewidth=1, zorder=3)
        for n, o in zip(ns, over):
            if o:
                ax.scatter(n, 39.2, marker="^", s=38, color=ccol[c], edgecolor=cm.SURF, linewidth=1, zorder=4)
ax.axhline(32, color=cm.INK, linewidth=0.8, linestyle=(0, (3, 3)))
ax.text(ns[2], 32.3, "마감 32 ms", fontsize=7.5, color=cm.INK, va="bottom", ha="center")
ax.set_xlabel("트랙 수")
ax.set_ylabel("최대 응답 ms (동시 도착 S)")
ax.set_ylim(0, 40)
ax.set_xticks(ns, [f"{n:,}" for n in ns], fontsize=8)
cm.clean(ax)
h = [Line2D([], [], color=ccol[c], linewidth=2, label=CNAME[c]) for c in CNAME]
h += [Line2D([], [], color=cm.MUTED, linewidth=1.5, linestyle=ls, label=ANAME[a]) for a, ls in style.items()]
h.append(Line2D([], [], color=cm.MUTED, marker="^", linestyle="", markersize=6, label="과부하(miss)"))
ax.legend(handles=h, loc="upper left", ncol=2, frameon=False, fontsize=8)
ax.set_xlim(ns[0] - 40, ns[-1] + 120)
cm.header(fig, "그림 5. 한계는 연산기다. 정렬은 한계를 바꾸지 않고, spike 건너뛰기가 여유를 만든다",
          f"{SUB} 조건에서 연산만 바꿈. 정렬 끔 = LRU 10, 켬 = slot 4. 시드 5. 정렬 켬은 세 연산이 0.2~1 ms로 겹친다", top=0.86)
cm.save(fig, __file__, dpi=170, bbox_inches="tight")
