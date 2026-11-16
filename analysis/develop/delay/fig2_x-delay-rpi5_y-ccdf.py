"""보고서용 라즈베리파이 5 Host 측정 CCDF: (a) 모델 그룹 지연 G = t_ready − t_host, (b) response time = t_recv − t_host. 조건 6개

입력: hardware/board_test/p316_meas/result/ccdf.csv (analyze_p316.py, 라즈베리파이 5 + 보드, C Host program, 1,024트랙, 조건마다 300 s,
처음 16주기 제외). 비교로 Xeon CPU 고정·부하 없음(Python, p325_meas/result/m3_delay_ccdf.csv)을 (a)에 회색 점선으로 둔다.
t_host는 frame 마지막 샘플이 든 4 ms block의 도착 시각이다. 부하 = busy loop 3개(고정 조건은 계산 CPU 3을 피함).

    python3 analysis/develop/delay/fig2_x-delay-rpi5_y-ccdf.py
"""
import csv
import os
import sys

import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator, NullFormatter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

SRC = os.path.join(cm.ROOT, "hardware", "board_test", "p316_meas", "result", "ccdf.csv")
XEON = os.path.join(cm.ROOT, "hardware", "board_test", "p325_meas", "result", "m3_delay_ccdf.csv")
data = {}
with open(SRC) as f:
    for r in csv.DictReader(f):
        data.setdefault((r["cond"], r["quantity"]), []).append((float(r["value_us"]) / 1000, float(r["ccdf"])))
with open(XEON) as f:
    xeon = [(float(r["delay_us"]) / 1000, float(r["ccdf"])) for r in csv.DictReader(f) if r["cond"] == "pin3_load0"]

cm.paper_style()
COND = [("pin-none_ondemand_load0", "Unpinned, ondemand, idle", cm.SERIES[0], "-", "s"),
        ("pin3_ondemand_load0", "Pinned, ondemand, idle", cm.SERIES[0], "--", "o"),
        ("pin3_performance_load0", "Pinned, performance, idle", cm.SERIES[0], ":", "D"),
        ("pin-none_ondemand_load3", "Unpinned, ondemand, loaded", cm.SERIES[1], "-", "^"),
        ("pin3_ondemand_load3", "Pinned, ondemand, loaded", cm.SERIES[1], "--", "v"),
        ("pin3_performance_load3", "Pinned, performance, loaded", cm.SERIES[1], ":", "P")]
fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.3), sharey=True)
for ax, q, xlab in ((axes[0], "G", "Model-group delay (ms): frame at Host → mel ready"),
                    (axes[1], "response_time", "Response time (ms): frame at Host → result at Host")):
    for key, lab, c, ls, m in COND:
        pts = [(x, y) for x, y in data[(key, q)] if y > 0]
        ax.plot([x for x, _ in pts], [y for _, y in pts], color=c, linestyle=ls, linewidth=1.0, marker=m, markevery=24,
                markersize=2.8, markeredgewidth=0, label=lab)
    if q == "G":
        pts = [(x, y) for x, y in xeon if y > 0]
        ax.plot([x for x, _ in pts], [y for _, y in pts], color=cm.MUTED, linestyle=(0, (2, 1.5)), linewidth=0.9,
                label="Xeon (Python), pinned, idle")
    ax.axvline(32, color=cm.INK, linewidth=0.6, linestyle=(0, (1, 1.5)))
    ax.text(34, 1e-3, "deadline 32 ms", fontsize=6.5, color=cm.INK, rotation=90, ha="left", va="center")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(0.3, 40)
    ax.set_ylim(1e-7, 1.5)
    ax.xaxis.set_major_locator(FixedLocator([0.3, 1, 3, 10, 32]))
    ax.yaxis.set_major_locator(FixedLocator([1e-6, 1e-4, 1e-2, 1]))
    ax.xaxis.set_minor_formatter(NullFormatter())
    ax.yaxis.set_minor_formatter(NullFormatter())
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:g}")
    ax.grid(which="minor", visible=False)
    ax.tick_params(which="both", length=0, pad=2)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.set_xlabel(xlab, labelpad=1)
axes[0].set_ylabel("P(value > x)", labelpad=1)
axes[0].text(0.02, 0.03, "(a)", transform=axes[0].transAxes, fontsize=7.5)
axes[1].text(0.02, 0.03, "(b)", transform=axes[1].transAxes, fontsize=7.5)
axes[1].text(0.99, 0.97, "Raspberry Pi 5 + FPGA board, C host program\n1,024 tracks, 300 s each, 4 ms audio blocks\nloaded = 3 busy loops",
             transform=axes[1].transAxes, ha="right", va="top", fontsize=6.3, color=cm.MUTED)
h, lab = axes[0].get_legend_handles_labels()
fig.legend(h, lab, loc="lower center", ncol=4, frameon=False, fontsize=6.5, handlelength=2.2, bbox_to_anchor=(0.5, -0.02))
fig.tight_layout(pad=0.2, rect=(0, 0.13, 1, 1))
cm.save(fig, __file__, exts=("pdf", "png"), dpi=300, bbox_inches="tight", pad_inches=0.01)
