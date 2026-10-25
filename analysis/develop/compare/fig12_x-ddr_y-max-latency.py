"""논문용 DDR3 전송량-관측 최대 응답 시간 그림(Fig. 3 교체). 점마다 arrival 방식 × scheduler, 같은 BRAM(entry 4)·trace

입력: simulation/result/p326_final_compare.csv (P3.26 E5, 시나리오 6 × seed 30). Host 처리 지연 = Xeon M3(CPU 고정·부하 없음)에서 잰
모델·주기 묶음 지연 재생 + 추론 요청별 Uniform(0, J) 합성. 모든 방법에 같은 (모델, 주기) 지연을 넣었다. 링크는 PCIe 64 B 표본. 열 = J 0.8·3.2 ms.
(a) 행: 응답 시간(t_recv − t_host, frame 마지막 샘플이 Host에 들어온 시각부터, Host 처리 지연 포함) 관측 최대. 가로 선 = 32 ms deadline.
(b) 행: Host 준비 완료 뒤 시간(t_recv − t_ready = 링크 + FPGA + 링크) 관측 최대. 가로 선 = 32 ms − Host 처리 지연 관측 최대.
최대는 추론 요청별 시간 차이를 구한 뒤 잰다. 색·marker = scheduler, 채움 = arrival(빈 = unaligned, 반 = global alignment, 꽉 = model-grouped).
cache는 model-grouped만 PNU-count, 나머지 LRU. 세로 막대 = seed별 최대의 범위(최소~전체 최대), 가로 막대 = DDR3 95 % CI. 점을 잇지 않는다.

    python3 analysis/develop/compare/fig12_x-ddr_y-max-latency.py
"""
import os
import sys

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import FixedLocator, NullFormatter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.paper_style()
rows = [r for r in cm.points("p326_final_compare") if "pin3_load0" in r["host_group_trace"]]
SCHED = {"grouping": ("Grouping", cm.SERIES[0], "o"), "dysta": ("Dysta Method", cm.SERIES[1], "s"),
         "deeprt": ("DeepRT Method", cm.SERIES[2], "^")}
FILL = {"none": ("Unaligned", "none"), "global": ("Global alignment", "left"), "model": ("Model-grouped", "full")}
Js = (0.8, 3.2)
METRIC = (("max_done_ms", "(a) Max. response (ms)"), ("fpga_side_max_ms", "(b) Max. after Host ready (ms)"))

fig, axes = plt.subplots(2, len(Js), figsize=(3.5, 3.5), sharex=True, sharey=True)
for col, J in enumerate(Js):
    sel = sorted((r for r in rows if r["host_jitter_ms"] == J), key=lambda r: r["host_offset"] == "model" and r["scheduler"] == "grouping")
    host = max(r["host_max_ms"] for r in sel)
    for row, (k, ylab) in enumerate(METRIC):
        ax = axes[row, col]
        for r in sel:                                             # 제안(model-grouped + Grouping)을 마지막에 그린다
            name, c, m = SCHED[r["scheduler"]]
            x, y = r["dram_kib"], r[k]
            prop = r["host_offset"] == "model" and r["scheduler"] == "grouping"
            ax.errorbar(x, y, xerr=[[x - r["dram_kib_ci_lo"]], [r["dram_kib_ci_hi"] - x]], yerr=[[y - r[f"{k}_min"]], [0.0]],
                        fmt="none", ecolor=c, elinewidth=0.6, capsize=0, zorder=2)
            ax.plot(x, y, marker=m, color=c, markersize=4.6 if prop else 3.6, fillstyle=FILL[r["host_offset"]][1], markerfacecoloralt="white",
                    markeredgewidth=0.8, linestyle="none", zorder=5 if prop else 3)
            if prop:
                ax.plot(x, y, marker="o", markersize=8.5, fillstyle="none", color=cm.INK, markeredgewidth=0.6, zorder=6)
                ax.annotate("Proposed", (x, y), xytext=(4, -9 if row else 6), textcoords="offset points", fontsize=6.5, color=cm.INK)
        line, txt = (32.0, "32 ms deadline") if row == 0 else (32.0 - host, f"32 ms − max. Host delay {host:.1f} ms")
        ax.axhline(line, color=cm.INK, linewidth=0.7, linestyle=(0, (4, 2)), zorder=1)
        ax.text(4.3, line * 1.05, txt, fontsize=5.8, color=cm.INK, va="bottom")
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlim(4, 80)
        ax.set_ylim(0.5, 45)
        ax.xaxis.set_major_locator(FixedLocator([5, 10, 20, 50]))
        ax.yaxis.set_major_locator(FixedLocator([1, 3, 10, 32]))
        for a in (ax.xaxis, ax.yaxis):
            a.set_minor_formatter(NullFormatter())
            a.set_major_formatter(lambda v, _: f"{v:g}")
        ax.grid(which="minor", visible=False)
        ax.tick_params(which="both", length=0, pad=2)
        for sp in ax.spines.values():
            sp.set_visible(False)
        if col == 0:
            ax.set_ylabel(ylab, labelpad=1)
        if row == 0:
            ax.set_title(f"Measured G + Uniform(0, {J:g} ms)", fontsize=7, pad=2)
        else:
            ax.set_xlabel("DDR3 traffic (KiB/inference)", labelpad=1)
h = [Line2D([], [], marker=m, color=c, linestyle="none", markersize=4, label=n) for n, c, m in SCHED.values()]
h += [Line2D([], [], marker="o", color=cm.MUTED, fillstyle=fs, markerfacecoloralt="white", linestyle="none", markersize=4, label=n)
      for n, fs in FILL.values()]
fig.legend(handles=h, ncol=3, loc="lower center", bbox_to_anchor=(0.5, 1.0), frameon=False, fontsize=6.5,
           handletextpad=0.3, columnspacing=0.8, borderaxespad=0)
fig.tight_layout(pad=0.2, w_pad=0.6, h_pad=0.5)
cm.save(fig, __file__, exts=("pdf", "png"), dpi=300, bbox_inches="tight", pad_inches=0.01)
