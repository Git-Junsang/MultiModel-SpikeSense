"""논문용 jitter-DDR3 전송량 그림 (fig3 왼쪽의 사본: 영문, 그림 안 제목 없음, 단 폭 3.5 in). offset 배정을 켠 채 cache 교체 방식과 entry 수만 바꾼다

입력: simulation/result/p321_compare_jitter.csv (entry 4·10), p317_jitter_wide.csv (entry 2, 같은 조건), p321_compare.csv (비교군).
논문 Table 5의 값이다. 비교군은 offset 배정을 하지 않아 jitter와 상관없다(가로선)
"""
import os
import sys

import matplotlib.pyplot as plt
from matplotlib.patheffects import withStroke
from matplotlib.ticker import FixedLocator, NullFormatter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.paper_style()
cj = {(r["label"].split(" · ")[0], r["entries"], r["jitter_ms"]): r for r in cm.points("p321_compare_jitter")}
jw = {(r["entries"], r["jitter_ms"]): r for r in cm.points("p317_jitter_wide")}
base = {r["label"].split(" · ")[0]: r for r in cm.points("p321_compare") if r["entries"] == 4}
Js = sorted({j for _, _, j in cj})
H, S = "SW+HW: 제안", "SW만: Host offset 배정"
assert all(abs(jw[(4, j)]["dram_kib"] - cj[(H, 4, j)]["dram_kib"]) < 1e-9 for j in Js)   # 두 실험이 같은 조건인지
BLUE, GRAY = cm.SERIES[0], cm.MUTED
LINES = [("Offset-order, 2 entries", BLUE, ":", "o", 1.0, [jw[(2, j)] for j in Js]),
         ("Offset-order, 4 entries", BLUE, "-", "o", 1.6, [cj[(H, 4, j)] for j in Js]),
         ("Offset-order, 10 entries", BLUE, "--", "o", 1.0, [cj[(H, 10, j)] for j in Js]),
         ("LRU, 4 entries", GRAY, "-", "s", 1.0, [cj[(S, 4, j)] for j in Js]),
         ("LRU, 10 entries", GRAY, "--", "s", 1.0, [cj[(S, 10, j)] for j in Js])]

fig, ax = plt.subplots(figsize=(3.5, 2.3))
for k in ("Dysta Method", "DeepRT Method"):
    name, c, _ = cm.PAPER_METHOD[k]
    v = base[k]["dram_kib"]
    ax.axhline(v, color=c, linewidth=0.8, linestyle=(0, (1, 1.5)), zorder=1)
    ax.text(0.74, v * 1.06, f"{name} (no offset assignment)", color=c, fontsize=6.5, ha="left", va="bottom",
            path_effects=[withStroke(linewidth=2, foreground="white")])   # 흰 테두리: 이름이 길어져 선과 겹치는 곳에서도 읽히게
for lab, c, ls, m, lw, rows in LINES:
    ax.plot(Js, [r["dram_kib"] for r in rows], color=c, linestyle=ls, linewidth=lw, marker=m, markersize=2.6,
            markeredgewidth=0, label=lab, zorder=3 if c == BLUE else 2)

ax.set_xscale("log")
ax.set_yscale("log")
ax.set_xlim(0.7, 23)
ax.set_ylim(5, 110)
ax.xaxis.set_major_locator(FixedLocator(Js))
ax.yaxis.set_major_locator(FixedLocator([5, 10, 20, 50, 100]))
for a in (ax.xaxis, ax.yaxis):
    a.set_minor_formatter(NullFormatter())
    a.set_major_formatter(lambda v, _: f"{v:g}")
ax.grid(which="minor", visible=False)
ax.set_xlabel("Jitter (ms)", labelpad=1)
ax.set_ylabel("DDR3 traffic (KiB/inference)", labelpad=1)
ax.tick_params(which="both", length=0, pad=2)
for sp in ax.spines.values():
    sp.set_visible(False)
ax.legend(ncol=2, loc="lower left", bbox_to_anchor=(0, 1.0), frameon=False, fontsize=6.5, handlelength=2.2,
          columnspacing=0.9, handletextpad=0.4, borderaxespad=0.2)
fig.tight_layout(pad=0.2)
cm.save(fig, __file__, exts=("pdf", "png"), dpi=300, bbox_inches="tight", pad_inches=0.01)
