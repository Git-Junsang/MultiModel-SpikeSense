"""논문용 entry 수 그림: 추론 요청별 퍼짐 J × entry의 DDR3 전송량(PNU-count). 테두리 = 그 J에서 고른 entry

입력: simulation/result/p326_jitter_entry.csv (P3.26 E2, 시나리오 6 × seed 30). Host 처리 지연 = Xeon M3(CPU 고정·부하 없음)의
모델·주기 묶음 지연 재생 + 추론 요청별 Uniform(0, J) 합성. entry가 늘면 on-chip membrane potential 트랙이 준다(괄호 안 값).
entry 선택 규칙(P3.25·P3.26과 같음): deadline miss 0, 최소 deadline 여유 > 0, DDR3 KiB/추론이 그 J에서 entry 2~10 중 최솟값의
110 % 이내인 가장 작은 entry. 값은 P3.26 보고서 §3.3 표와 같다

    python3 analysis/develop/entry/fig1_x-jitter_y-entry_c-ddr.py
"""
import os
import sys

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LogNorm
from matplotlib.patches import Rectangle

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.paper_style()
rows = {(r["host_jitter_ms"], r["cache_entries"]): r for r in cm.points("p326_jitter_entry")
        if r["label"].startswith("PNU-count")}
Js = sorted({j for j, _ in rows})
Es = sorted({e for _, e in rows})
val = np.array([[rows[(j, e)]["dram_kib"] for j in Js] for e in Es])


def pick(j):
    ok = [e for e in Es if rows[(j, e)]["miss"] == 0 and rows[(j, e)]["min_slack_ms"] > 0]
    best = min(rows[(j, e)]["dram_kib"] for e in ok)
    return next(e for e in ok if rows[(j, e)]["dram_kib"] <= 1.1 * best)


chosen = [pick(j) for j in Js]
assert chosen == [2, 2, 3, 6], chosen  # P3.26 보고서 §3.3

fig, ax = plt.subplots(figsize=(3.5, 2.0))
norm = LogNorm(val.min(), val.max())
im = ax.imshow(val, cmap=cm.seq_cmap(), norm=norm, aspect="auto", origin="lower")
for (i, k), v in np.ndenumerate(val):
    ax.text(k, i, f"{v:.2f}" if v < 10 else f"{v:.1f}", ha="center", va="center", fontsize=6.3, color="white" if norm(v) > 0.55 else cm.INK)
for k, e in enumerate(chosen):
    ax.add_patch(Rectangle((k - 0.5, Es.index(e) - 0.5), 1, 1, fill=False, edgecolor=cm.INK, linewidth=1.2))
ax.set_xticks(range(len(Js)), [f"{j:g}" for j in Js])
ax.set_yticks(range(len(Es)), [f"{e} ({rows[(Js[0], e)]['onchip_tracks']})" for e in Es])
ax.set_xlabel("Jitter J (ms): measured group delay + Uniform(0, J)", labelpad=1)
ax.set_ylabel("Entries (on-chip tracks)", labelpad=1)
ax.tick_params(length=0, pad=2)
ax.grid(False)
for sp in ax.spines.values():
    sp.set_visible(False)
cb = fig.colorbar(im, ax=ax, pad=0.02, fraction=0.06)
cb.set_ticks([6, 10, 20, 40], labels=["6", "10", "20", "40"])
cb.ax.minorticks_off()
cb.ax.tick_params(length=0, pad=2)
cb.outline.set_visible(False)
cb.set_label("DDR3 traffic (KiB/inference)", labelpad=2)
fig.tight_layout(pad=0.2)
cm.save(fig, __file__, exts=("pdf", "png"), dpi=300, bbox_inches="tight", pad_inches=0.01)
