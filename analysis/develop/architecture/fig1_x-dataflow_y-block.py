"""논문용 시스템 구조도 (영문, 그림 안 제목 없음, 단 폭 3.5 in). 논문 IV절 첫 문단과 design_references/03 §2의 block을 그린다.
simulation 결과를 쓰지 않는다. 파란 block이 제안 부분(offset 배정, Grouping, offset-order cache, 12 bit membrane potential)
"""
import os
import sys

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.paper_style()
W, H = 3.5, 2.45                            # 좌표 = inch
C = [(0.22, 1.20), (1.36, 2.34), (2.50, 3.48)]   # 세 열의 x 범위
LINE, HL_FILL, HL_EDGE, BAND = "#3d3d3a", "#e8f1fc", cm.SERIES[0], "#f3f3f0"

fig = plt.figure(figsize=(W, H))
ax = fig.add_axes([0, 0, 1, 1])
ax.set_xlim(0, W)
ax.set_ylim(0, H)
ax.axis("off")


def band(y0, y1, name):
    ax.add_patch(Rectangle((0.02, y0), W - 0.04, y1 - y0, facecolor=BAND, edgecolor="none", zorder=0))
    ax.text(0.10, (y0 + y1) / 2, name, rotation=90, ha="center", va="center", fontsize=7, fontweight="bold")


def box(x0, x1, y0, y1, text, hl=False, fill="white"):
    ax.add_patch(FancyBboxPatch((x0, y0), x1 - x0, y1 - y0, boxstyle="round,pad=0,rounding_size=0.03",
                                facecolor=HL_FILL if hl else fill, edgecolor=HL_EDGE if hl else LINE,
                                linewidth=0.8 if hl else 0.6, zorder=2))
    ax.text((x0 + x1) / 2, (y0 + y1) / 2, text, ha="center", va="center", fontsize=6.5, linespacing=1.1, zorder=3)


def arrow(p0, p1, both=False):
    ax.annotate("", p1, p0, arrowprops=dict(arrowstyle="<|-|>" if both else "-|>", color=LINE, linewidth=0.7,
                                            mutation_scale=6, shrinkA=0, shrinkB=0), zorder=1)


def mid(c):
    return sum(C[c]) / 2


def note(x, y, text, ha="left"):
    ax.text(x, y, text, ha=ha, va="center", fontsize=6, style="italic", color=cm.MUTED)


band(1.92, 2.42, "Host")
band(0.48, 1.84, "FPGA")
band(0.02, 0.38, "DDR3")

# Host
HY = (2.02, 2.32)
box(*C[0], *HY, "Mel features\n(1,024 tracks)")
box(*C[1], *HY, "Model-Grouped\nOffset Assignment", hl=True)
box(*C[2], *HY, "Classification")
arrow((C[0][1], sum(HY) / 2), (C[1][0], sum(HY) / 2))

# FPGA: Ethernet, 1행(요청 → batch → 연산), 2행(DMA → cache, membrane potential)
EY, R1, R2 = (1.55, 1.73), (1.10, 1.40), (0.58, 0.88)
box(C[0][0], C[2][1], *EY, "Gigabit Ethernet MAC (UDP)", fill="#e9e8e3")
box(*C[0], *R1, "Request\ntable")
box(*C[1], *R1, "Grouping\nscheduler", hl=True)
box(*C[2], *R1, "64-lane\ncompute array")
box(*C[0], *R2, "DMA")
box(*C[1], *R2, "Weight cache\n(4 entries)", hl=True)
box(*C[2], *R2, "Membrane bank\n(768 tracks, 12-bit)", hl=True)

arrow((mid(1), HY[0]), (mid(1), EY[1]))
note(mid(1) + 0.04, 1.87, "requests")
arrow((mid(2), EY[1]), (mid(2), HY[0]))
note(mid(2) + 0.04, 1.87, "results")
arrow((mid(0), EY[0]), (mid(0), R1[1]))
arrow((mid(2), R1[1]), (mid(2), EY[0]))
arrow((C[0][1], sum(R1) / 2), (C[1][0], sum(R1) / 2))
arrow((C[1][1], sum(R1) / 2), (C[2][0], sum(R1) / 2))
arrow((C[0][1], sum(R2) / 2), (C[1][0], sum(R2) / 2))
arrow((mid(1), R1[0]), (mid(1), R2[1]))
note(mid(1) + 0.04, sum((R1[0], R2[1])) / 2, "next model")
arrow((C[1][1], R2[1]), (C[2][0], R1[0]))
arrow((mid(2), R2[1]), (mid(2), R1[0]), both=True)
note(mid(2) + 0.04, sum((R1[0], R2[1])) / 2, "state")

# DDR3
DY = (0.08, 0.32)
box(C[0][0], C[2][1], *DY, "Weights of 40 models (4.97 MiB)   ·   membrane of 256 tracks")
arrow((mid(0), DY[1]), (mid(0), R2[0]), both=True)
note(mid(0) + 0.04, (DY[1] + R2[0]) / 2, "weights, state")

cm.save(fig, __file__, exts=("pdf", "png"), dpi=300)
