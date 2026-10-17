"""비교군(Dysta Method·DeepRT Method)·ablation vs SW·HW 협력 설계: 방법 × 시나리오의 DDR3 KiB/추론과 최대 응답 시간 열지도 (P3.21)

입력: simulation/result/p321_compare.csv, p321_compare_runs.csv.gz (entry 4 = 제안과 같은 BRAM)
"""
import os
import sys

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.sim_style()
from matplotlib.colors import LogNorm  # noqa: E402

pts = sorted([r for r in cm.points("p321_compare") if r["entries"] == 4], key=lambda r: cm.METHOD_ORDER.index(r["label"].split(" · ")[0]))
runs = cm.by_point(cm.runs("p321_compare"))
SC = ["U", "K", "S", "I", "SK", "R"]
names = [r["label"].split(" · ")[0] for r in pts]
cell = {(i, s): cm.agg([x for x in runs[r["point"]] if x["scn"] == s]) for i, r in enumerate(pts) for s in SC}
tot = {i: cm.agg(runs[r["point"]]) for i, r in enumerate(pts)}
cols = SC + ["전체"]
get = lambda i, s, k: (tot[i] if s == "전체" else cell[(i, s)])[k]
fig, axes = plt.subplots(1, 2, figsize=(9.6, 5.4))
for ax, key, lab, norm, fmt in ((axes[0], "dram_kib", "DDR3 KiB/추론", LogNorm(4, 120), "{:.1f}"),
                                (axes[1], "max_ms", "최대 응답 시간 ms", LogNorm(0.5, 32), "{:.1f}")):
    v = np.array([[get(i, s, key) for s in cols] for i in range(len(pts))])
    ax.imshow(v, cmap=cm.seq_cmap(), norm=norm, aspect="auto")
    for (yi, xi), x in np.ndenumerate(v):
        miss = key == "max_ms" and get(yi, cols[xi], "miss") > 0
        ax.text(xi, yi, fmt.format(x) + ("*" if miss else ""), ha="center", va="center", fontsize=7.5,
                color=cm.SURF if norm(x) > 0.55 else cm.INK, fontweight="bold" if yi == len(pts) - 1 else None)
    ax.axhline(1.5, color=cm.INK, linewidth=1.2)
    ax.axvline(len(SC) - 0.5, color=cm.SURF, linewidth=2)
    ax.set_xticks(range(len(cols)), cols, fontsize=8)
    ax.set_yticks(range(len(pts)), names if ax is axes[0] else [""] * len(pts), fontsize=8)
    ax.set_title(lab, loc="left", fontsize=9)
    ax.set_xlabel("시나리오")
    ax.grid(False)
    cm.clean(ax)
cm.header(fig, "그림 8. 비교군은 DDR3(Dysta Method 56.8 KiB/추론)나 응답 시간(DeepRT Method 최대 17.4 ms) 중 하나가 크다. SW+HW는 6.4 KiB/추론, 최대 1.1 ms다",
          "simulation, 모든 방법이 같은 BRAM(weight entry 4 + 12 bit membrane potential 768트랙 on-chip)·trace·DDR3 조건. jitter 0.8 ms, seed 10. "
          "가로선 위: 비교군(offset 배정 없음, LRU), 아래: ablation. * = deadline miss 있음", top=0.88)
cm.save(fig, __file__, dpi=170, bbox_inches="tight")
