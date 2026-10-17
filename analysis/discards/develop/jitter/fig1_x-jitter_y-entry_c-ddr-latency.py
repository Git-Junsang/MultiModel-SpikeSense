"""정렬 jitter × entry 열지도: DDR3 KiB/추론, 최대 응답 (P3.13 그림 3, 옛 fig43_p313_jitter_heatmap)

입력: simulation/result/p313_jitter.csv
"""
import os
import sys

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.sim_style()
SUB = "시뮬레이션, L·64 lane, 1,024트랙, 즉시 입출력, spike 건너뛰기"
from matplotlib.colors import LogNorm  # noqa: E402

rows = cm.points("p313_jitter")
Es = sorted({r["entries"] for r in rows})
Js = sorted({r["jitter_ms"] for r in rows})
pt = {(r["entries"], r["jitter_ms"]): r for r in rows}
fig, axes = plt.subplots(1, 2, figsize=(8.4, 2.6))
for ax, key, title, fmt in zip(axes, ("dram_kib", "max_ms"), ("DDR3 KiB/추론", "최대 응답 ms"), ("{:.1f}", "{:.2f}")):
    val = np.array([[pt[(E, j)][key] for j in Js] for E in Es])
    norm = LogNorm(val.min(), val.max()) if key == "dram_kib" else plt.Normalize(0, val.max())
    ax.imshow(val, cmap=cm.seq_cmap(), norm=norm, aspect="auto")
    for (i, j), v in np.ndenumerate(val):
        ax.text(j, i, fmt.format(v), ha="center", va="center", fontsize=8, color=cm.SURF if norm(v) > 0.55 else cm.INK)
    ax.set_xticks(range(len(Js)), [f"{j:g}" for j in Js], fontsize=8)
    ax.set_yticks(range(len(Es)), [f"entry {E}" for E in Es], fontsize=8)
    ax.set_xlabel("같은 모델 트랙의 위상 퍼짐 jitter (ms)")
    ax.set_title(title, loc="left", fontsize=9)
    ax.grid(False)
    cm.clean(ax)
cm.header(fig, "그림 3. 정렬 오차를 cache가 얼마나 흡수하는가 — entry 4는 3.2 ms까지",
          f"{SUB}, 정렬 + Grouping + slot 순서 교체. 시나리오 6 × 시드 10. slot 간격 0.8 ms", top=0.86)
cm.save(fig, __file__, dpi=170, bbox_inches="tight")
