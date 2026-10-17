"""도착 패턴별 DDR3 KiB/추론과 최대 응답 시간, P3.13 제안 구성(membrane potential은 모두 DDR3에 16 bit) (P3.13 그림 4, 옛 fig44_p313_arrival)

입력: simulation/result/p313_arrival.csv
"""
import os
import sys

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.sim_style()
SUB = "simulation, L·64 lane, 1,024트랙, 즉시 입출력, spike 0 건너뛰기"

rows = cm.points("p313_arrival")
pats = [r["label"] for r in rows]
fig, axes = plt.subplots(1, 2, figsize=(8.4, 3.2), sharey=True)
y = len(pats) - 1 - np.arange(len(pats))              # 첫 패턴이 위
for ax, key, title, fmt in zip(axes, ("dram_kib", "max_ms"), ("DDR3 KiB/추론", "최대 응답 시간 ms"), ("{:.1f}", "{:.1f}")):
    v = [r[key] for r in rows]
    bars = ax.barh(y, v, height=0.6, color=cm.SERIES[2], label="Grouping")
    for b, x in zip(bars, v):
        ax.text(x, b.get_y() + b.get_height() / 2, " " + fmt.format(x), va="center", ha="left", fontsize=7, color=cm.INK)
    ax.set_yticks(y, pats, fontsize=8)
    ax.set_title(title, loc="left", fontsize=9)
    ax.set_xlim(0, ax.get_xlim()[1] * 1.12)
    cm.clean(ax)
cm.header(fig, "그림 4. offset을 주는 것이 아니라 모델별로 모으는 것이 핵심 — 교대·지연에도 유지",
          f"{SUB}, 제안 구성(Grouping, offset-order cache entry 4, membrane potential은 모두 DDR3에 16 bit).\n균등·편중 배정 합산, seed 20. 지연 = 요청의 1·5 %가 0~16 ms 늦게 도착. "
          + ("모두 deadline miss 0" if not any(r["miss"] for r in rows) else f"deadline miss {sum(r['miss'] for r in rows):,}"), top=0.83)
cm.save(fig, __file__, dpi=170, bbox_inches="tight")
