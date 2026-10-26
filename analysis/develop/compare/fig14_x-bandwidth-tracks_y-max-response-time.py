"""논문용 DDR3 bandwidth·트랙 수-관측 최대 response time 그림(Fig. 5 교체). P4.1 rtl67 비용, Host 처리 jitter Uniform(0, 0.8 ms), PNU-Count, 조정한 비교군

입력: simulation/result/p325_scale_bandwidth.csv (1,024트랙), p325_scale_tracks.csv (3,015 MB/s). 시나리오 6 × seed 10.
P3.25 합성 조건이다: Host 처리 지연은 추론 요청마다 Uniform(0, 0.8 ms)이고 모델 그룹 지연이 없다. P3.26(M3 모델 그룹 지연 재생)에서는 다시 돌리지 않았다.
y = 관측 최대 response time(simulation, 증명된 상한이 아님). Response time은 frame 마지막 샘플이 Host에 들어온 시각부터 결과 수신까지(Host 처리 지연 포함, mic–Host 지연 제외, P3.25 D1). 최대 response time이 2주기(64 ms)를 넘는 점은 queue가 쌓여 커지는 것으로 보고
값 대신 위 끝에 unstable(×)로 둔다. 점선 = 32 ms deadline.

    python3 analysis/develop/compare/fig14_x-bandwidth-tracks_y-max-response-time.py
"""
import os
import sys

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import FixedLocator, NullFormatter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.paper_style()
bandwidth = {(r["label"].split(" · ")[-1], r["ddr3_bandwidth_mbps"]): r for r in cm.points("p325_scale_bandwidth")}
tr = {(r["label"].split(" · ")[-1], r["track_count"]): r for r in cm.points("p325_scale_tracks")}
METH = {"Model-Grouped Offset Assignment + Grouping + PNU-Count (제안)": ("proposed", cm.SERIES[0], "o", "-"),
        "Dysta Method (unaligned, LRU)": ("Dysta Method", cm.SERIES[1], "s", "-"),
        "DeepRT Method (unaligned, LRU)": ("DeepRT Method", cm.SERIES[2], "^", "-"),
        "global alignment + Grouping (LRU)": ("global alignment + Grouping", cm.SERIES[3], "D", "--")}
UNSTABLE, YMAX = 64.0, 80.0
Bs = sorted({b for _, b in bandwidth}, reverse=True)
Ns = sorted({n for _, n in tr})

fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(3.5, 1.9), sharey=True, gridspec_kw={"width_ratios": [1.15, 1]})
for ax, pts, xs in ((ax_a, bandwidth, Bs), (ax_b, tr, Ns)):
    for i, (k, (name, c, m, ls)) in enumerate(METH.items()):
        ys = [pts[(k, x)]["max_ms"] for x in xs]
        ok = [(x, y) for x, y in zip(xs, ys) if y <= UNSTABLE]
        ax.plot([x for x, _ in ok], [y for _, y in ok], color=c, marker=m, markersize=3, markeredgewidth=0, linestyle=ls,
                linewidth=1.3 if name == "proposed" else 0.9, zorder=3)
        bad = [x for x, y in zip(xs, ys) if y > UNSTABLE]
        if bad:
            ax.plot(bad, [YMAX * 0.85 ** i] * len(bad), linestyle="none", marker="x", markersize=4, color=c, clip_on=False, zorder=4)
    ax.axhline(32, color=cm.INK, linewidth=0.7, linestyle=(0, (4, 2)), zorder=2)
    ax.set_yscale("log")
    ax.set_ylim(0.3, YMAX)
    ax.yaxis.set_major_locator(FixedLocator([1, 3, 10, 32]))
    ax.yaxis.set_minor_formatter(NullFormatter())
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:g}")
    ax.grid(which="minor", visible=False)
    ax.tick_params(which="both", length=0, pad=2)
    for sp in ax.spines.values():
        sp.set_visible(False)
ax_a.set_xscale("log")
ax_a.invert_xaxis()
ax_a.xaxis.set_major_locator(FixedLocator([3015, 1000, 400, 200]))
ax_a.xaxis.set_minor_formatter(NullFormatter())
ax_a.xaxis.set_major_formatter(lambda v, _: f"{v:,.0f}")
ax_a.set_xlabel("DDR3 bandwidth (MB/s), 1,024 tracks", labelpad=1)
ax_b.xaxis.set_major_locator(FixedLocator([512, 1024, 2048, 3072, 4096]))
ax_b.xaxis.set_major_formatter(lambda v, _: f"{v / 1024:g}K" if v >= 1024 else f"{v:g}")
ax_b.set_xlabel("Tracks, 3,015 MB/s", labelpad=1)
ax_a.set_ylabel("Observed max. response time (ms)", labelpad=1)
ax_a.text(0.02, 0.97, "(a)", transform=ax_a.transAxes, ha="left", va="top", fontsize=7)
ax_b.text(0.02, 0.97, "(b)", transform=ax_b.transAxes, ha="left", va="top", fontsize=7)
ax_a.text(0.02, 0.03, "Host delay Uniform(0, 0.8 ms) per request,\nno model-group delay (synthetic)", transform=ax_a.transAxes, ha="left",
          va="bottom", fontsize=6.3, color=cm.MUTED)
h = [Line2D([], [], color=c, marker=m, linestyle=ls, markersize=3, markeredgewidth=0, label=n) for n, c, m, ls in METH.values()]
h.append(Line2D([], [], color=cm.MUTED, marker="x", linestyle="none", markersize=4, label="unstable (queue grows)"))
fig.legend(handles=h, ncol=3, loc="lower center", bbox_to_anchor=(0.5, 1.0), frameon=False, fontsize=6.3,
           handlelength=1.8, columnspacing=0.8, handletextpad=0.4, borderaxespad=0)
fig.tight_layout(pad=0.2, w_pad=0.6)
cm.save(fig, __file__, exts=("pdf", "png"), dpi=300, bbox_inches="tight", pad_inches=0.01)
