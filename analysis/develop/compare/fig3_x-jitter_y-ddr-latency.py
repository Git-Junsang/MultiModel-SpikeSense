"""jitter가 커질 때 SW+HW(즉시 전송 entry 4·10, offset 단위 모아 보내기 entry 2), SW만(Host offset 배정 + LRU), 비교군·offset 배정 없음 (P3.21)

입력: simulation/result/p321_compare_jitter.csv, p317_gather.csv, p321_compare.csv (모두 seed 0~9)
비교군과 offset 배정 없음은 offset 배정을 하지 않아 jitter와 상관없다(가로선)
"""
import os
import sys

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.sim_style()
from matplotlib.lines import Line2D  # noqa: E402

cj = {(r["label"].split(" · ")[0], r["entries"], r["jitter_ms"]): r for r in cm.points("p321_compare_jitter")}
ga = {r["jitter_ms"]: r for r in cm.points("p317_gather") if r["entries"] == 2 and r["gather_ms"] == r["jitter_ms"]}
base = {r["label"].split(" · ")[0]: r for r in cm.points("p321_compare") if r["entries"] == 4}
Js = sorted({j for _, _, j in cj})
S, H = "SW만: Host offset 배정", "SW+HW: 제안"
OURS = [("SW+HW 즉시 전송, entry 4", cm.SERIES[0], "-", {j: cj[(H, 4, j)] for j in Js}),
        ("SW+HW 즉시 전송, entry 10", cm.SERIES[0], (0, (4, 2)), {j: cj[(H, 10, j)] for j in Js}),
        ("SW만(LRU) 즉시 전송, entry 4", cm.SERIES[2], "-", {j: cj[(S, 4, j)] for j in Js}),
        ("SW만(LRU) 즉시 전송, entry 10", cm.SERIES[2], (0, (4, 2)), {j: cj[(S, 10, j)] for j in Js}),
        ("SW+HW offset 단위 모아 보내기, entry 2", cm.SERIES[1], "-", {j: ga[j] for j in Js if j in ga})]
BASE = {"Dysta Method": "Dysta Method·offset 배정 없음", "DeepRT Method": "DeepRT Method", "Grouping(offset 배정 없음)": None}   # offset 배정 없음은 Dysta Method와 겹쳐 이름 하나로
fig, axes = plt.subplots(1, 2, figsize=(9.6, 3.8))
for ax, key, lab in zip(axes, ("dram_kib", "mean_ms"), ("DDR3 KiB/추론 (log)", "평균 응답 시간 ms (log)")):
    for b, bl in BASE.items():
        y = base[b][key]
        ax.axhline(y, color=cm.GRAY, linewidth=1, zorder=1)
        if bl:
            ax.text(Js[-1] * 1.08, y, bl, fontsize=7, color=cm.MUTED, va="center")
    for lab_, c, ls, d in OURS:
        x = sorted(d)
        ax.plot(x, [d[j][key] for j in x], color=c, linestyle=ls, linewidth=2, marker="o", markersize=4,
                markeredgecolor=cm.SURF, markeredgewidth=1, zorder=3)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xticks(Js, [f"{j:g}" for j in Js], fontsize=8)
    yt = [5, 10, 20, 50, 100] if key == "dram_kib" else [0.05, 0.1, 0.3, 1, 3, 10]
    ax.set_yticks(yt, [f"{t:g}" for t in yt])
    ax.minorticks_off()
    ax.set_xlim(Js[0] * 0.85, Js[-1] * 2.6)
    ax.set_xlabel("jitter ms")
    ax.set_title(lab, loc="left", fontsize=9)
    cm.clean(ax)
h = [Line2D([], [], color=c, linestyle=ls, linewidth=2, label=lb) for lb, c, ls, _ in OURS]
h.append(Line2D([], [], color=cm.GRAY, linewidth=1, label="비교군·offset 배정 없음(jitter 무관)"))
cm.header(fig, "그림 10. jitter가 커지면 HW의 offset-order cache가 SW만 쓸 때보다 DDR3를 최대 45 % 줄인다. 8 ms를 넘으면 offset 단위 모아 보내기가 필요하다",
          "simulation, 같은 BRAM·trace·DDR3 조건, 시나리오 6 × seed 10. offset 단위 모아 보내기는 대기 D = jitter. 회색 = 비교군과 offset 배정 없음(jitter와 상관없음). 모든 점 deadline miss 0",
          top=0.86)
fig.legend(handles=h, loc="upper center", bbox_to_anchor=(0.5, 0.02), ncol=3, frameon=False, fontsize=8)
cm.save(fig, __file__, dpi=170, bbox_inches="tight")
