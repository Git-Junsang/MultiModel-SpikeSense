"""논문용 jitter-cache 그림(Fig. 4 교체): (a) DDR3 traffic, (b) 모델·주기당 window 재적재. Entry 4

입력: simulation/result/p326_cache_policy.csv (P3.26 E1, 시나리오 6 × seed 30). Host 처리 지연 = Xeon M3(CPU 고정·부하 없음)의
모델·주기 모델 그룹 지연 재생 + 추론 요청별 Uniform(0, J) 합성. J는 추론 요청별 퍼짐의 최대다. 선 = 시나리오를 합친 값, 띠 = seed별 값의 최소~최대.
PNU-Count(P3.25 식)는 모델 그룹 지연을 모르고 jitter 분포만 쓰는 예측이다. Oracle MIN은 미래 도착을 아는 구현 불가능한 기준선이다(적재 하한은
아님). 비교군(Dysta Method·DeepRT Method)은 arrival 조건이 달라 이 그림에 넣지 않는다. P3.25 합성 조건 판은 analysis/discards/*/compare/fig13_*_p325.*

    python3 analysis/develop/compare/fig13_x-jitter_y-ddr3-traffic-reload.py
"""
import os
import sys

import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator, NullFormatter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.paper_style()
rows = {(r["label"].split(" · ")[0], r["host_jitter_ms"]): r for r in cm.points("p326_cache_policy")
        if r["cache_entries"] == 4 and "pin3_load0" in r["host_model_group_delay_trace"]}
Js = sorted({j for _, j in rows})
BLUE, ORANGE, GRAY = cm.SERIES[0], cm.SERIES[1], cm.MUTED
LINES = [("LRU", "LRU", GRAY, "-", "s", 1.0),
         ("offset-only", "Offset-only", ORANGE, "--", "^", 1.0),
         ("PNU-Count, 모델 그룹 지연 모름(P3.25 식)", "PNU-Count, jitter only", BLUE, (0, (3, 1.5)), "x", 0.9),
         ("PNU-Count", "PNU-Count (model-group delay + jitter)", BLUE, "-", "o", 1.6),
         ("Oracle MIN", "Oracle MIN (future knowledge)", cm.INK, (0, (1, 1.2)), "", 0.8)]

fig, (ax_a, ax_b) = plt.subplots(2, 1, figsize=(3.5, 3.0), sharex=True)
for key, lab, c, ls, m, lw in LINES:
    rs = [rows[(key, j)] for j in Js]
    for ax, k in ((ax_a, "ddr3_traffic_kib"), (ax_b, "reloads_per_model_period")):
        ax.fill_between(Js, [r[f"{k}_min"] for r in rs], [r[f"{k}_max"] for r in rs], color=c, alpha=0.15, linewidth=0, zorder=1)
        ax.plot(Js, [r[k] for r in rs], color=c, linestyle=ls, linewidth=lw, marker=m, markersize=2.8, markeredgewidth=0.6 if m == "x" else 0,
                label=lab, zorder=3 if key == "PNU-Count" else 2)

ax_a.set_yscale("log")
ax_a.yaxis.set_major_locator(FixedLocator([6, 10, 20, 40]))
ax_a.set_ylabel("DDR3 traffic\n(KiB/inference)", labelpad=1)
ax_b.set_yscale("symlog", linthresh=0.01)
ax_b.set_ylim(0, None)
ax_b.yaxis.set_major_locator(FixedLocator([0, 0.01, 0.1, 1, 10]))
ax_b.set_ylabel("Reloads per\nmodel-period", labelpad=1)
ax_b.xaxis.set_major_locator(FixedLocator(Js))
ax_b.set_xlabel("Jitter J (ms): measured model-group delay + Uniform(0, J), 4 entries", labelpad=1)
for ax, tag in ((ax_a, "(a)"), (ax_b, "(b)")):
    for a in (ax.xaxis, ax.yaxis):
        a.set_minor_formatter(NullFormatter())
        a.set_major_formatter(lambda v, _: f"{v:g}")
    ax.grid(which="minor", visible=False)
    ax.tick_params(which="both", length=0, pad=2)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.text(0.01, 0.97, tag, transform=ax.transAxes, ha="left", va="top", fontsize=7)
ax_a.legend(ncol=2, loc="lower left", bbox_to_anchor=(0, 1.0), frameon=False, fontsize=6.3, handlelength=2.2,
            columnspacing=0.9, handletextpad=0.4, borderaxespad=0.2)
fig.tight_layout(pad=0.2, h_pad=0.4)
cm.save(fig, __file__, exts=("pdf", "png"), dpi=300, bbox_inches="tight", pad_inches=0.01)
