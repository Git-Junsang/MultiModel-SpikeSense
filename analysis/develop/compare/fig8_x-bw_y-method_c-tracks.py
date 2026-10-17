"""DDR3 대역폭별로 deadline miss 0인 최대 트랙 수, spike 2개/cycle (P3.21)

입력: simulation/result/p321_scale_bw.csv(1,500·1,000·600·400 MB/s), p321_scale.csv(3,015 MB/s). search, entry 4, seed 0~2
"""
import os
import sys

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.sim_style()
from matplotlib.colors import Normalize  # noqa: E402

pt = {(r["label"].split(" · ")[0], r["bw_mbps"]): r["found"] for r in cm.points("p321_scale_bw")}
for r in cm.points("p321_scale"):
    if r["spk"] == 2:
        pt[(r["label"].split(" · ")[0], r["bw_mbps"])] = r["found"]
names = [n for n in cm.METHOD_ORDER if any(k[0] == n for k in pt)]
Bs = [3015.0, 1500.0, 1000.0, 600.0, 400.0]
v = np.array([[pt[(n, b)] or 0 for b in Bs] for n in names], float)
norm = Normalize(0, 5000)
fig, ax = plt.subplots(figsize=(6.6, 2.6))
ax.imshow(v, cmap=cm.seq_cmap(), norm=norm, aspect="auto")
for (yi, xi), x in np.ndenumerate(v):
    ax.text(xi, yi, f"{x:,.0f}" if x else "1,024 미만", ha="center", va="center", fontsize=8,
            color=cm.SURF if norm(x) > 0.55 else cm.INK, fontweight="bold" if yi == len(names) - 1 else None)
ax.set_xticks(range(len(Bs)), [f"{b:,.0f}" for b in Bs], fontsize=8)
ax.set_yticks(range(len(names)), names, fontsize=8)
ax.set_xlabel("DDR3 대역폭 MB/s (3,015 = 보드 실측)")
ax.grid(False)
cm.clean(ax)
cm.header(fig, "그림 15. DDR3가 1,000 MB/s면 Dysta Method는 1,024트랙, SW+HW는 4,608트랙까지 deadline miss 0이다",
          "simulation, 같은 BRAM(entry 4)·trace, spike 2개/cycle, jitter 0.8 ms, 시나리오 6 × seed 3. 시험값 1,024·1,536·2,048·…·6,144트랙",
          top=0.78)
cm.save(fig, __file__, dpi=170, bbox_inches="tight")
