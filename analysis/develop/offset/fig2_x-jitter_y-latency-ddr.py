"""편중 배정(K)에서 offset 간격: 같은 간격(0.8 ms) vs 트랙 수 비례 (P3.17)

입력: simulation/result/p317_offset_width.csv, p317_offset_width_runs.csv.gz (시나리오 K만)
"""
import os
import sys

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.sim_style()
from matplotlib.patches import Patch  # noqa: E402

pts = cm.points("p317_offset_width")
runs = cm.by_point(cm.runs("p317_offset_width"))
k = {(r["offset"], r["jitter_ms"]): cm.agg([x for x in runs[r["point"]] if x["scn"] == "K"]) for r in pts}
Js = sorted({r["jitter_ms"] for r in pts})
OFS = {"model": ("같은 간격 0.8 ms", cm.GRAY), "model_w": ("트랙 수 비례", cm.SERIES[0])}
fig, axes = plt.subplots(1, 3, figsize=(8.4, 3.0))
x = np.arange(len(Js))
for ax, key, lab, fmt in zip(axes, ("mean_ms", "max_ms", "dram_kib"), ("평균 응답 시간 ms", "최대 응답 시간 ms", "DDR3 KiB/추론"),
                             ("{:.2f}", "{:.2f}", "{:.1f}")):
    for i, (a, (_, c)) in enumerate(OFS.items()):
        v = [k[(a, j)][key] for j in Js]
        b = ax.bar(x + (i - 0.5) * 0.38, v, width=0.36, color=c)
        for r, y in zip(b, v):
            ax.text(r.get_x() + r.get_width() / 2, y, fmt.format(y), ha="center", va="bottom", fontsize=7)
    ax.set_xticks(x, [f"{j:g}" for j in Js], fontsize=8)
    ax.set_xlabel("jitter ms")
    ax.set_title(lab, loc="left", fontsize=9)
    ax.margins(y=0.15)
    cm.clean(ax)
h = [Patch(color=c, label=lb) for lb, c in OFS.values()]
cm.header(fig, "그림 3. 편중 배정에서 offset 간격을 트랙 수에 비례하게 하면 평균 응답 시간은 줄지만 DDR3 전송량이 는다",
          "simulation, 제안 구성(entry 4), 시나리오 K(모델 k의 트랙 비율이 1/(k+1)에 비례)만, seed 20. 모든 점 deadline miss 0",
          legend=h, top=0.78)
cm.save(fig, __file__, dpi=170, bbox_inches="tight")
