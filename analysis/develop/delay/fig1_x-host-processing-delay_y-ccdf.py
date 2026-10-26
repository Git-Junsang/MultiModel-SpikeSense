"""보고서용 Host 처리 지연 CCDF(M3): frame 마지막 샘플이 Host에 들어온 시각 → 모델 그룹 mel 계산 완료. 조건 4개

입력: hardware/board_test/p325_meas/result/m3_delay_ccdf.csv (sub1 = Xeon W-2255, Python, 1,024트랙, 조건마다 300 s, 처음 0.5 s 제외).
원자료는 sub1의 mmss_jobs/p325/m3/m3_<조건>.csv.gz. 모델 하나의 트랙을 한 번에 계산해 같은 모델 안 퍼짐(jitter)은 4조건 모두 0이다.
개발 서버급 CPU 값이라 최종 Host(라즈베리파이 5급) 근거가 아니다. Mic–Host·Ethernet 구간은 들어 있지 않다(F7은 측정 뒤).

    python3 analysis/develop/delay/fig1_x-host-processing-delay_y-ccdf.py
"""
import csv
import os
import sys

import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator, NullFormatter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

SRC = os.path.join(cm.ROOT, "hardware", "board_test", "p325_meas", "result", "m3_delay_ccdf.csv")
if not os.path.exists(SRC):
    raise SystemExit(f"입력 없음: {os.path.relpath(SRC, cm.ROOT)}")
data = {}
with open(SRC) as f:
    for r in csv.DictReader(f):
        data.setdefault(r["cond"], []).append((float(r["delay_us"]) / 1000, float(r["ccdf"])))

cm.paper_style()
COND = [("pin-none_load0", "Unpinned, idle", cm.MUTED, "-", "s"), ("pin3_load0", "Pinned, idle", cm.MUTED, "--", "o"),
        ("pin-none_load8", "Unpinned, loaded", cm.SERIES[0], "-", "^"), ("pin3_load8", "Pinned, loaded", cm.SERIES[0], "--", "D")]
fig, ax = plt.subplots(figsize=(3.5, 2.2))
for key, lab, c, ls, m in COND:
    pts = [(x, y) for x, y in data[key] if y > 0]
    ax.plot([x for x, _ in pts], [y for _, y in pts], color=c, linestyle=ls, linewidth=1.0, marker=m, markevery=24, markersize=2.8,
            markeredgewidth=0, label=lab)
ax.axvline(0.8, color=cm.INK, linewidth=0.6, linestyle=(0, (1, 1.5)))
ax.text(0.83, 2e-8, "offset gap\n0.8 ms", fontsize=6.5, color=cm.INK, va="bottom")
ax.set_xscale("log")
ax.set_yscale("log")
ax.set_xlim(0.1, 40)
ax.set_ylim(1e-8, 1.5)
ax.xaxis.set_major_locator(FixedLocator([0.1, 0.3, 1, 3, 10, 32]))
ax.yaxis.set_major_locator(FixedLocator([1e-6, 1e-4, 1e-2, 1]))
ax.xaxis.set_minor_formatter(NullFormatter())
ax.yaxis.set_minor_formatter(NullFormatter())
ax.xaxis.set_major_formatter(lambda v, _: f"{v:g}")
ax.grid(which="minor", visible=False)
ax.tick_params(which="both", length=0, pad=2)
for sp in ax.spines.values():
    sp.set_visible(False)
ax.set_xlabel("Host processing delay (ms): frame at Host → mel ready", labelpad=1)
ax.set_ylabel("P(delay > x)", labelpad=1)
ax.text(0.99, 0.03, "Spread within a model: 0\n(a model's tracks computed together)\nXeon W-2255, Python, 1,024 tracks\nloaded = 8 busy processes",
        transform=ax.transAxes, ha="right", va="bottom", fontsize=6.3, color=cm.MUTED)
ax.legend(loc="lower left", bbox_to_anchor=(0.0, 0.14), frameon=False, fontsize=6.5, handlelength=2.2)
fig.tight_layout(pad=0.2)
cm.save(fig, __file__, exts=("pdf", "png"), dpi=300, bbox_inches="tight", pad_inches=0.01)
