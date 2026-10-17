"""논문용 DDR3 대역폭·트랙 수-최대 응답 시간 그림 (fig5·fig7 최대 응답 시간의 사본: 영문, 그림 안 제목 없음, 단 폭 3.5 in). 비교군 둘과 제안

입력: simulation/result/p321_compare_ddrbw.csv (1,024트랙), p321_scale_run.csv (3,015 MB/s). 둘 다 시나리오 6 × seed 3, spike 2개/cycle.
논문 VI-D의 DDR3 대역폭과 트랙 수 값이다. 최대 응답 시간이 32 ms를 넘으면 deadline miss가 있다
"""
import os
import sys

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import FixedLocator, NullFormatter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.paper_style()
bw = {(r["label"].split(" · ")[0], r["bw_mbps"]): r for r in cm.points("p321_compare_ddrbw")}
sc = {(r["label"].split(" · ")[0], r["tracks"]): r for r in cm.points("p321_scale_run")}
Bs = sorted({b for _, b in bw}, reverse=True)
Ns = sorted({n for _, n in sc})
YMAX = 200                                  # DeepRT Method 300·200 MB/s(623·2,212 ms)는 위 끝에 세모로

fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(3.5, 1.75), sharey=True, gridspec_kw={"width_ratios": [1.15, 1]})
for ax, pts, xs in ((ax_a, bw, Bs), (ax_b, sc, Ns)):
    for k, (name, c, m) in cm.PAPER_METHOD.items():
        ys = [pts[(k, x)]["max_ms"] for x in xs]
        ax.plot(xs, [min(y, YMAX) for y in ys], color=c, marker=m, markersize=3, markeredgewidth=0, linewidth=1.2 if k == "SW+HW: 제안" else 1.0,
                zorder=3)
        over = [x for x, y in zip(xs, ys) if y > YMAX]
        if over:                            # 빈 선을 clip_on=False로 그리면 tight bbox가 원점까지 늘어난다
            ax.plot(over, [YMAX] * len(over), linestyle="none", marker="^", markersize=4.5, color=c, clip_on=False, zorder=4)
    ax.axhline(32, color=cm.INK, linewidth=0.7, linestyle=(0, (4, 2)), zorder=2)
    ax.set_yscale("log")
    ax.set_ylim(0.5, YMAX)
    ax.yaxis.set_major_locator(FixedLocator([1, 3, 10, 32, 100]))
    ax.yaxis.set_minor_formatter(NullFormatter())
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:g}")
    ax.grid(which="minor", visible=False)
    ax.tick_params(which="both", length=0, pad=2)
    for sp in ax.spines.values():
        sp.set_visible(False)

ax_a.set_xscale("log")
ax_a.set_xlim(3600, 170)                    # 대역폭이 줄어드는 쪽을 오른쪽으로
ax_a.xaxis.set_major_locator(FixedLocator([3015, 1000, 400, 200]))
ax_a.xaxis.set_minor_formatter(NullFormatter())
ax_a.xaxis.set_major_formatter(lambda v, _: f"{v:,.0f}")
ax_a.set_xlabel("DDR3 bandwidth (MB/s)", labelpad=1)
ax_a.set_ylabel("Max. response time (ms)", labelpad=1)
ax_a.set_title("(a) 1,024 tracks", loc="left", fontweight="bold", pad=3)
ax_a.text(3400, 38, "deadline", fontsize=6.5, color=cm.INK, ha="left", va="bottom")
ax_a.annotate("queue\ngrows", (250, YMAX), xytext=(-2, -12), textcoords="offset points", fontsize=6.5, color=cm.SERIES[2],
              ha="center", va="top")

ax_b.set_xlim(800, 4320)
ax_b.xaxis.set_major_locator(FixedLocator(Ns))
ax_b.xaxis.set_major_formatter(lambda v, _: f"{v:,.0f}")
ax_b.set_xlabel("Tracks", labelpad=1)
ax_b.set_title("(b) 3,015 MB/s", loc="left", fontweight="bold", pad=3)

fig.legend(handles=[Line2D([], [], color=c, marker=m, markersize=3, markeredgewidth=0, label=name)
                    for name, c, m in cm.PAPER_METHOD.values()],
           loc="upper center", ncol=3, frameon=False, fontsize=7, bbox_to_anchor=(0.5, 1.0), borderaxespad=0,
           handlelength=1.8, columnspacing=1.4)
fig.tight_layout(pad=0.2, w_pad=0.8, rect=(0, 0, 1, 0.9))
cm.save(fig, __file__, exts=("pdf", "png"), dpi=300, bbox_inches="tight", pad_inches=0.01)
