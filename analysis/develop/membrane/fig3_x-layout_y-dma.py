"""DDR3 membrane potential 배치(track_id 순서 vs offset 순서)와 추론당 membrane potential DMA 횟수 (P3.17·P3.19)

입력: simulation/result/p317_mem_place.csv
"""
import os
import sys

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.sim_style()
from matplotlib.patches import Patch  # noqa: E402

rows = cm.points("p317_mem_place")
pt = {(r["mem_place"], r["gather_ms"]): r for r in rows}
Gs = sorted({r["gather_ms"] for r in rows})
PL = {"id": ("track_id 순서(모델과 무관)", cm.GRAY), "offset": ("offset 순서", cm.SERIES[0])}
fig, ax = plt.subplots(figsize=(5.6, 3.2))
x = np.arange(len(Gs))
for i, (p, (_, c)) in enumerate(PL.items()):
    v = [pt[(p, g)]["mdma"] for g in Gs]
    b = ax.bar(x + (i - 0.5) * 0.36, v, width=0.34, color=c)
    for r, y in zip(b, v):
        ax.text(r.get_x() + r.get_width() / 2, y, f"{y:.3f}", ha="center", va="bottom", fontsize=8)
ax.set_xticks(x, [f"즉시 전송\n(평균 batch {pt[('offset', 0.0)]['batch']:.1f})" if g == 0 else
                  f"offset 단위 모아 보내기 D {g:g} ms\n(평균 batch {pt[('offset', g)]['batch']:.1f})" for g in Gs], fontsize=8)
ax.set_ylabel("membrane potential DMA 횟수/추론")
ax.set_ylim(0, 0.7)
cm.clean(ax)
kib = sorted({round(r["dram_kib"], 2) for r in rows})
ax.legend(handles=[Patch(color=c, label=lb) for lb, c in PL.values()], loc="upper center", ncol=2, frameon=False, fontsize=8)
cm.header(fig, "그림 4. DDR3 membrane potential을 offset 순서로 붙여 두면 batch가 클 때만 DMA가 준다",
          f"simulation, 제안 구성(entry 4, 768트랙 on-chip, 256트랙 DDR3), seed 20. 이어진 트랙은 읽기·쓰기 DMA 한 번씩.\n"
          f"DDR3 {'·'.join(f'{k:g}' for k in kib)} KiB/추론과 응답 시간은 평균 계산(avg)과 같다", top=0.80)
cm.save(fig, __file__, dpi=170, bbox_inches="tight")
