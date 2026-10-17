"""논문용 DDR3 전송량-평균 응답 시간 그림 (fig2의 사본: 영문, 그림 안 제목 없음, 단 폭 3.5 in). 비교군 둘과 제안, 비교군에 offset 배정과 offset-order cache를 붙인 점

입력: simulation/result/p321_compare.csv (entry 4), p321_compare_offset.csv. 논문 Table 3과 VI-C의 값이다
"""
import os
import sys

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import FixedLocator, NullFormatter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.paper_style()
base = {r["label"].split(" · ")[0]: r for r in cm.points("p321_compare") if r["entries"] == 4}
ofs = {r["label"]: r for r in cm.points("p321_compare_offset")}   # 같은 offset 배정·cache에 scheduler만 바꿈


def xy(r):
    return r["dram_kib"], r["mean_ms"]


fig, ax = plt.subplots(figsize=(3.5, 2.0))
ax.plot(*zip(xy(base["Dysta Method"]), xy(base["DeepRT Method"])), color=cm.GRAY, linewidth=0.8, linestyle=":", zorder=1)
for k in ("Dysta Method", "DeepRT Method"):
    name, c, m = cm.PAPER_METHOD[k]
    ax.annotate("", xy(ofs[k]), xy(base[k]), arrowprops=dict(arrowstyle="-|>", color=c, linewidth=0.8, linestyle=(0, (3, 2)),
                                                            shrinkA=4, shrinkB=5, mutation_scale=7), zorder=2)
    ax.scatter(*xy(base[k]), marker=m, s=26, color=c, zorder=3)
name, c, m = cm.PAPER_METHOD["DeepRT Method"]
ax.scatter(*xy(ofs["DeepRT Method"]), marker=m, s=26, facecolor="white", edgecolor=c, linewidth=0.9, zorder=3)
name, c, m = cm.PAPER_METHOD["SW+HW: 제안"]
ax.scatter(*xy(base["SW+HW: 제안"]), marker=m, s=36, color=c, zorder=4)

ax.annotate("Dysta Method", xy(base["Dysta Method"]), xytext=(0, -9), textcoords="offset points", ha="center", va="center")
ax.annotate("DeepRT Method", xy(base["DeepRT Method"]), xytext=(6, 0), textcoords="offset points", ha="left", va="center")
ax.annotate("DeepRT Method + offset assignment + cache", xy(ofs["DeepRT Method"]), xytext=(0, 8), textcoords="offset points", ha="left", va="center")
ax.annotate("Proposed", xy(base["SW+HW: 제안"]), xytext=(6, -5), textcoords="offset points", ha="left", va="center",
            color=cm.SERIES[0], fontweight="bold")
ax.text(30, 0.42, "+ offset assignment\n+ offset-order cache", color=cm.MUTED, fontsize=6.5, ha="center", va="center", style="italic")

ax.set_xscale("log")
ax.set_yscale("log")
ax.set_xlim(4.5, 90)
ax.set_ylim(0.09, 20)
ax.xaxis.set_major_locator(FixedLocator([5, 10, 20, 50]))
ax.yaxis.set_major_locator(FixedLocator([0.1, 0.3, 1, 3, 10]))
for a in (ax.xaxis, ax.yaxis):
    a.set_minor_formatter(NullFormatter())
    a.set_major_formatter(lambda v, _: f"{v:g}")
ax.set_xlabel("DDR3 traffic (KiB/inference)", labelpad=1)
ax.set_ylabel("Mean response time (ms)", labelpad=1)
ax.tick_params(which="both", length=0, pad=2)
for sp in ax.spines.values():
    sp.set_visible(False)
fig.tight_layout(pad=0.2)
# 점선 기울기에 맞춰 글자를 돌려 선 아래에 놓는다 (배치가 끝난 뒤 화면 좌표로 잰다)
p0, p1 = (ax.transData.transform(xy(base[k])) for k in ("Dysta Method", "DeepRT Method"))
ang = np.degrees(np.arctan2(p0[1] - p1[1], p0[0] - p1[0]))
mid = np.sqrt(np.multiply(xy(base["Dysta Method"]), xy(base["DeepRT Method"])))
ax.annotate("trade-off without offset assignment", mid, xytext=(6 * np.sin(np.radians(ang)), -6 * np.cos(np.radians(ang))),
            textcoords="offset points", rotation=ang, rotation_mode="anchor", ha="center", va="center", color=cm.MUTED,
            fontsize=6.5, style="italic")
cm.save(fig, __file__, exts=("pdf", "png"), dpi=300, bbox_inches="tight", pad_inches=0.01)
