"""보고서·보조 자료용 교차점 그림: jitter를 넓힐 때 (a) DDR3 전송량, (b) 관측 최대 응답 시간이 방법마다 어떻게 바뀌는지

입력: simulation/result/p325_crossover.csv (entry 4, Uniform(0, J), 시나리오 6 × seed 30). jitter는 모든 방법의 Host 처리 지연(frame의 Host 도착 → 추론 요청 준비)에 같이 들어간다(P3.25 D1·D6).
띠 = seed별 값의 최소~최대. 점선 = 32 ms deadline.

P3.25 합성 조건이다(모델 묶음 지연 없음). P3.26(M3 묶음 지연 재생)에서는 다시 돌리지 않았다.

    python3 analysis/develop/compare/fig15_x-jitter_y-method_c-ddr-latency.py
"""
import os
import sys

import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator, NullFormatter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.paper_style()
rows = {(r["label"].split(" · ")[0], r["host_jitter_ms"]): r for r in cm.points("p325_crossover")}
Js = sorted({j for _, j in rows})
METH = [("Model-Grouped + Grouping + PNU-count (제안)", "Proposed (PNU-count, 4 entries)", cm.SERIES[0], "o", "-", 1.5),
        ("Dysta Method (unaligned, LRU)", "Dysta Method", cm.SERIES[1], "s", "-", 1.0),
        ("DeepRT Method (unaligned, LRU)", "DeepRT Method", cm.SERIES[2], "^", "-", 1.0),
        ("Global + Dysta (LRU)", "Global alignment + Dysta", cm.SERIES[3], "D", "--", 1.0),
        ("Global + Grouping (LRU)", "Global alignment + Grouping", cm.MUTED, "v", ":", 1.0)]

fig, (ax_a, ax_b) = plt.subplots(2, 1, figsize=(3.5, 3.1), sharex=True)
for k, lab, c, m, ls, lw in METH:
    rs = [rows[(k, j)] for j in Js]
    for ax, f in ((ax_a, "dram_kib"), (ax_b, "max_ms")):
        ax.fill_between(Js, [r[f"{f}_min"] for r in rs], [r[f"{f}_max"] for r in rs], color=c, alpha=0.15, linewidth=0)
        ax.plot(Js, [r[f] for r in rs], color=c, marker=m, markersize=2.8, markeredgewidth=0, linestyle=ls, linewidth=lw, label=lab)
ax_b.axhline(32, color=cm.INK, linewidth=0.7, linestyle=(0, (4, 2)))
ax_a.set_yscale("log")
ax_a.yaxis.set_major_locator(FixedLocator([5, 10, 20, 50]))
ax_a.set_ylabel("DDR3 traffic\n(KiB/inference)", labelpad=1)
ax_b.set_yscale("log")
ax_b.yaxis.set_major_locator(FixedLocator([2, 5, 10, 20, 32]))
ax_b.set_ylabel("Observed max.\nresponse (ms)", labelpad=1)
ax_b.set_xscale("log")
ax_b.xaxis.set_major_locator(FixedLocator(Js))
ax_b.set_xlabel("Host-side jitter J (ms), Uniform(0, J), no group delay, 4 entries", labelpad=1)
for ax, tag in ((ax_a, "(a)"), (ax_b, "(b)")):
    for a in (ax.xaxis, ax.yaxis):
        a.set_minor_formatter(NullFormatter())
        a.set_major_formatter(lambda v, _: f"{v:g}")
    ax.grid(which="minor", visible=False)
    ax.tick_params(which="both", length=0, pad=2)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.text(0.995, 0.03, tag, transform=ax.transAxes, ha="right", va="bottom", fontsize=7)
ax_a.legend(ncol=2, loc="lower left", bbox_to_anchor=(0, 1.0), frameon=False, fontsize=6.3, handlelength=2.0,
            columnspacing=0.8, handletextpad=0.4, borderaxespad=0.2)
fig.tight_layout(pad=0.2, h_pad=0.4)
cm.save(fig, __file__, exts=("pdf", "png"), dpi=300, bbox_inches="tight", pad_inches=0.01)
