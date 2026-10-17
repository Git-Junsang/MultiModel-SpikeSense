"""BRAM 배분: weight entry 수 × membrane potential bit(16·12) × jitter의 DDR3 KiB/추론 (P3.13 그림 6, 옛 fig46_p313_bram_split)

입력: simulation/result/p313_tradeoff.csv
"""
import os
import sys

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.sim_style()
SUB = "simulation, L·64 lane, 1,024트랙, 즉시 입출력, spike 0 건너뛰기"
from matplotlib.colors import LogNorm  # noqa: E402

rows = cm.points("p313_tradeoff")
cm.engine.sc.configure(64, 1024, mem="ddr", rev=4, arch=cm.engine.ARCHS["L"])     # entry 1개 tile 수(ENTRY_T)
Es = sorted({r["entries"] for r in rows})
Js = sorted({r["jitter_ms"] for r in rows})
bits = (16, 12)
pt = {(r["entries"], r["bits"], r["jitter_ms"]): r for r in rows}
val = {b: np.array([[pt[(E, b, j)]["dram_kib"] for E in Es] for j in Js]) for b in bits}
norm = LogNorm(min(v.min() for v in val.values()), max(v.max() for v in val.values()))
fig, axes = plt.subplots(1, 2, figsize=(8.4, 2.9))
for ax, b in zip(axes, bits):
    v = val[b]
    ax.imshow(v, cmap=cm.seq_cmap(), norm=norm, aspect="auto")
    for (yi, xi), x in np.ndenumerate(v):
        ax.text(xi, yi, f"{x:.1f}", ha="center", va="center", fontsize=8, color=cm.SURF if norm(x) > 0.55 else cm.INK)
    for yi in range(len(Js)):                       # 줄마다 최소 칸에 테두리
        xi = int(v[yi].argmin())
        ax.add_patch(plt.Rectangle((xi - 0.5, yi - 0.5), 1, 1, fill=False, edgecolor=cm.INK, linewidth=1.6))
    ax.set_xticks(range(len(Es)), [f"{E}\n{cm.engine.onchip_tracks(pt[(E, b, Js[0])])}" for E in Es], fontsize=8)
    ax.set_yticks(range(len(Js)), [f"jitter {j:g} ms" for j in Js], fontsize=8)
    ax.set_xlabel("weight entry 수 (아래: on-chip membrane potential 트랙 수)")
    ax.set_title(f"membrane potential {b} bit — DDR3 KiB/추론", loc="left", fontsize=9)
    ax.grid(False)
    cm.clean(ax)
cm.header(fig, "그림 6. weight cache와 membrane potential이 BRAM을 나눠 쓴다 — jitter가 클수록 entry가 더 필요하다",
          f"{SUB}, offset 배정 + Grouping + offset-order 교체. 남은 BRAM에 membrane potential을 둘 수 있는 만큼 on-chip. 테두리 = 줄마다 최소. seed 10",
          top=0.82)
cm.save(fig, __file__, dpi=170, bbox_inches="tight")
