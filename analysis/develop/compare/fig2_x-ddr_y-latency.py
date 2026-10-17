"""비교군(Dysta Method·DeepRT Method)·ablation vs SW·HW 협력 설계: DDR3 KiB/추론 ↔ 평균 응답 시간 (P3.21)

입력: simulation/result/p321_compare.csv (entry 4 = 제안과 같은 BRAM, entry 10은 빈 점)
"""
import os
import sys

import matplotlib.pyplot as plt

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.sim_style()
from matplotlib.lines import Line2D  # noqa: E402

pts = cm.points("p321_compare")
CO = {"Grouping(offset 배정 없음)": cm.MUTED, "HW만: offset-order cache": cm.SERIES[1], "SW만: Host offset 배정": cm.SERIES[2], "SW+HW: 제안": cm.SERIES[0]}
OFF = {"SW+HW: 제안": (6, -10), "SW만: Host offset 배정": (6, 6), "HW만: offset-order cache": (-4, -12), "Grouping(offset 배정 없음)": (6, 6), "Dysta Method": (6, -10)}
LAB = {}
fig, ax = plt.subplots(figsize=(7.2, 4.0))
for r in pts:
    name = r["label"].split(" · ")[0]
    c = CO.get(name, cm.GRAY)
    e4 = r["entries"] == 4
    ax.scatter(r["dram_kib"], r["mean_ms"], s=70 if name == "SW+HW: 제안" else 42, marker="o",
               facecolor=c if e4 else "none", edgecolor=c if not e4 else cm.SURF, linewidth=1.3, zorder=3)
    if e4:
        dx, dy = OFF.get(name, (5, 3))
        ax.annotate(LAB.get(name, name), (r["dram_kib"], r["mean_ms"]), xytext=(dx, dy), textcoords="offset points", fontsize=7.5,
                    color=cm.INK if name in CO else cm.MUTED, ha="right" if dx < 0 else "left")
ax.set_xscale("log")
ax.set_yscale("log")
ax.set_ylim(0.12, 25)
ax.set_xticks([6, 10, 20, 40, 60], ["6", "10", "20", "40", "60"])
ax.set_yticks([0.2, 0.5, 1, 2, 5, 10, 20], ["0.2", "0.5", "1", "2", "5", "10", "20"])
ax.minorticks_off()
ax.set_xlabel("DDR3 KiB/추론 (log)")
ax.set_ylabel("평균 응답 시간 ms (log)")
cm.clean(ax)
h = [Line2D([], [], marker="o", color=cm.GRAY, linestyle="", label="비교군: Dysta Method·DeepRT Method(offset 배정 없음, LRU)")]
h += [Line2D([], [], marker="o", color=c, linestyle="", label=n) for n, c in CO.items()]
h.append(Line2D([], [], marker="o", markerfacecolor="none", color=cm.MUTED, linestyle="", label="entry 10"))
cm.header(fig, "그림 9. SW·HW 협력 설계는 DDR3 전송량과 응답 시간을 함께 줄인다. 비교군은 둘을 맞바꾼다",
          "simulation, 같은 BRAM(entry 4, 채운 점)·trace·DDR3 조건, jitter 0.8 ms, 시나리오 6 × seed 10. 빈 점 = entry 10", legend=None, top=0.84)
ax.legend(handles=h, loc="center left", frameon=False, fontsize=8)
cm.save(fig, __file__, dpi=170, bbox_inches="tight")
