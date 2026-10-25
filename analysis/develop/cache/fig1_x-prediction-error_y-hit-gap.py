"""보고서·보조 자료용 predictor 진단: (a) cache hit rate, (b) 예측 오차(MAE), (c) DDR3 전송량 차이(Oracle MIN 대비, Belady 하한 대비)

입력: simulation/result/p326_cache_policy.csv (P3.26 E1, entry 4, 시나리오 6 × seed 30). Host 처리 지연 = Xeon M3(CPU 고정·부하 없음)의
모델·주기 묶음 지연 재생 + 추론 요청별 Uniform(0, J) 합성. PNU-count(P3.25 식)는 묶음 지연을 모르고 jitter 분포만 쓰는 예측이다.
hit rate = cache에 있던 batch 비율. 예측 오차 = 교체할 때 후보마다 |예측한 다음 사용 − 실제 다음 도착| µs(측정 구간).
Belady 하한 = 그 정책이 실제로 만든 batch 순서에서 가능한 최소 적재(적재 수의 하한). Oracle MIN은 하한이 아니라 미래 정보 기준선이다.
P3.25 합성 조건 판은 analysis/discards/*/cache/fig1_*_p325.*

    python3 analysis/develop/cache/fig1_x-prediction-error_y-hit-gap.py
"""
import os
import sys

import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator, NullFormatter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.paper_style()
rows = {(r["label"].split(" · ")[0], r["host_jitter_ms"]): r for r in cm.points("p326_cache_policy")
        if r["cache_entries"] == 4 and "pin3_load0" in r["host_group_trace"]}
Js = sorted({j for _, j in rows})
BLUE, ORANGE, GRAY = cm.SERIES[0], cm.SERIES[1], cm.MUTED
OLD = "PNU-count, 묶음 지연 모름(P3.25 식)"
POL = [("LRU", "LRU", GRAY, "-", "s"), ("offset-only", "Offset-only", ORANGE, "--", "^"),
       (OLD, "PNU-count, jitter only", BLUE, (0, (3, 1.5)), "x"), ("PNU-timeout", "PNU-timeout", BLUE, ":", "v"),
       ("PNU-count", "PNU-count", BLUE, "-", "o")]

fig, (ax_a, ax_b, ax_c) = plt.subplots(3, 1, figsize=(3.5, 3.9), sharex=True)
for st, lab, c, ls, m in POL:
    rs = [rows[(st, j)] for j in Js]
    kw = dict(color=c, linestyle=ls, marker=m, markersize=2.8, linewidth=1.0, markeredgewidth=0.6 if m == "x" else 0, label=lab)
    ax_a.plot(Js, [r["hit"] for r in rs], **kw)
    if st != "LRU":                                               # LRU는 다음 사용을 예측하지 않는다
        ax_b.plot(Js, [r["prediction_mae_us"] / 1000 for r in rs], **kw)
    if st in (OLD, "PNU-timeout", "PNU-count"):
        ora = [rows[("Oracle MIN", j)]["dram_kib"] for j in Js]
        ax_c.plot(Js, [100 * (r["dram_kib"] / o - 1) for r, o in zip(rs, ora)], **{**kw, "label": f"{lab} vs Oracle MIN"})
pc = [rows[("PNU-count", j)] for j in Js]
ax_c.plot(Js, [100 * (r["dram_kib"] / r["belady_kib"] - 1) for r in pc], color=BLUE, linestyle="-", marker="o", markersize=2.8,
          linewidth=0.6, alpha=0.6, markerfacecolor="white", label="PNU-count vs Belady bound")
ax_c.axhline(0, color=cm.INK, linewidth=0.6)
ax_a.set_ylabel("Cache hit rate", labelpad=1)
ax_b.set_ylabel("Next-use error\nMAE (ms)", labelpad=1)
ax_b.set_yscale("log")
ax_c.set_ylabel("DDR3 traffic\ngap (%)", labelpad=1)
ax_c.xaxis.set_major_locator(FixedLocator(Js))
ax_c.set_xlabel("Jitter J (ms): measured group delay + Uniform(0, J), 4 entries", labelpad=1)
for ax, tag in ((ax_a, "(a)"), (ax_b, "(b)"), (ax_c, "(c)")):
    ax.xaxis.set_minor_formatter(NullFormatter())
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:g}")
    ax.grid(which="minor", visible=False)
    ax.tick_params(which="both", length=0, pad=2)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.text(0.995, 0.03 if ax is ax_a else 0.97, tag, transform=ax.transAxes, ha="right", va="bottom" if ax is ax_a else "top", fontsize=7)
ax_a.legend(ncol=2, loc="lower left", bbox_to_anchor=(0, 1.0), frameon=False, fontsize=6.3, handlelength=2.2, columnspacing=0.9)
ax_c.legend(ncol=1, loc="upper left", bbox_to_anchor=(0.0, 1.0), frameon=False, fontsize=6, handlelength=2.2)
fig.tight_layout(pad=0.2, h_pad=0.4)
cm.save(fig, __file__, exts=("pdf", "png"), dpi=300, bbox_inches="tight", pad_inches=0.01)
