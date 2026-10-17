"""방법별로 deadline miss 0을 지키는 최대 트랙 수, spike 2개/cycle과 모든 입력 spike(dense) (P3.21)

입력: simulation/result/p321_scale.csv (search, entry 4, seed 0~2, 시험값 1,024~6,144트랙)
"""
import os
import sys

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.sim_style()
from matplotlib.patches import Patch  # noqa: E402

pts = cm.points("p321_scale")
names = [n for n in cm.METHOD_ORDER if any(r["label"].startswith(n + " ·") for r in pts)]
modes = list(dict.fromkeys(r["label"].split(" · ")[1] for r in pts))
pt = {tuple(r["label"].split(" · ")): r for r in pts}
col = dict(zip(modes, (cm.SERIES[0], cm.GRAY)))
fig, ax = plt.subplots(figsize=(7.2, 3.8))
y = np.arange(len(names))[::-1]
for i, m in enumerate(modes):
    for yi, n in zip(y, names):
        r = pt[(n, m)]
        v = r["found"] or 0
        ax.barh(yi + (0.5 - i) * 0.36 - 0.18, v, height=0.34, color=col[m], edgecolor=cm.INK if n == "SW+HW: 제안" else "none")
        ax.text(v + 60, yi + (0.5 - i) * 0.36 - 0.18, f"{v:,}" + ("+" if r["capped"] else "") if v else "1,024 미만",
                fontsize=7.5, va="center")
ax.axvline(1024, color=cm.INK, linewidth=0.8, linestyle=(0, (3, 3)))
ax.text(1024, y[0] + 0.62, "지금 목표 1,024", fontsize=7.5, ha="center", va="bottom")
ax.set_yticks(y, names, fontsize=8)
ax.set_xlabel("deadline miss 0인 최대 트랙 수 (시험값 1,024 · 1,536 · 2,048 · … · 6,144)")
ax.set_xlim(0, 7000)
ax.grid(axis="y", visible=False)
cm.clean(ax)
cm.header(fig, "그림 13. deadline miss 0 최대 트랙 수는 compute array가 정한다. spike 0 건너뛰기면 4,096~4,608, 모든 입력 spike면 모두 1,024~1,536 사이",
          "simulation, 같은 BRAM(entry 4)·trace·DDR3 3,015 MB/s, jitter 0.8 ms, 시나리오 6 × seed 3. + = 시험값 상한",
          legend=[Patch(color=col[m], label=m) for m in modes], top=0.82)
cm.save(fig, __file__, dpi=170, bbox_inches="tight")
