"""논문용 시스템 구조도(논문 Fig. 1). 영문, 그림 안 제목 없음, 단 폭 3.5 in, 글자 7 pt.
design_references/03 §2 block에 P3.25 설계(Next-use predictor, Host 메타데이터 경로)를 더했다.
P3.26: predictor 표를 모델 그룹 지연·추론 요청별 지연(jitter) 두 개로, 입력에 모델별 이번 주기 첫 도착 시각을 더했다.
Entry 4개와 membrane 768/256트랙은 평가에 쓴 구성(†)이고 entry 수는 목표 Host 측정 뒤 정한다.

입력: 없음(simulation 결과를 쓰지 않는 개념도)
실행: python3 analysis/develop/architecture/fig1_x-dataflow_y-block.py
출력: analysis/figure/architecture/fig1_x-dataflow_y-block.{pdf,png}
옛 그림·스크립트: analysis/discards/{figure,develop}/architecture/

표기
  실선 = 추론 요청 데이터(mel 입력, 결과, weight, state), 파란 점선 = 제어·메타데이터
  파란 block = 제안. Host Offset Assignment(SW)과 Next-use predictor(HW)를 따로 표시한다(Grouping만의 기여로 읽히지 않게)
  점선 테두리 = RTL이 없는 제안 block. RTL이 있는 block은 compute array 하나(P4.1)라 그 block에 적는다
"""
import os
import sys

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import FancyBboxPatch, Patch, Rectangle

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.paper_style()
W, H, FOOT = 3.5, 3.68, 0.13                       # 좌표 = inch. FOOT = 그림 아래 † 설명 줄
C = [(0.24, 0.92), (1.00, 1.86), (1.94, 2.70), (2.78, 3.46)]   # 네 열의 x 범위
LINE, HL_FILL, HL_EDGE, BAND, CTRL = "#3d3d3a", "#e8f1fc", cm.SERIES[0], "#f3f3f0", cm.SERIES[0]
DASH = (0, (3, 1.6))
ON_CHIP, IN_DDR3 = 768, 256                         # Membrane potential 트랙(12 bit, entry 4). 합 1,024
FS = 7

fig = plt.figure(figsize=(W, H + FOOT))
ax = fig.add_axes([0, 0, 1, 1])
ax.set_xlim(0, W)
ax.set_ylim(-FOOT, H)
ax.axis("off")


def band(y0, y1, name):
    ax.add_patch(Rectangle((0.02, y0), W - 0.04, y1 - y0, facecolor=BAND, edgecolor="none", zorder=0))
    ax.text(0.11, (y0 + y1) / 2, name, rotation=90, ha="center", va="center", fontsize=FS, fontweight="bold")


def box(x0, x1, y0, y1, text="", hl=False, dashed=False, fill="white", z=2):
    ax.add_patch(FancyBboxPatch((x0, y0), x1 - x0, y1 - y0, boxstyle="round,pad=0,rounding_size=0.03",
                                facecolor=HL_FILL if hl else fill, edgecolor=HL_EDGE if hl else LINE,
                                linewidth=0.8 if hl else 0.6, linestyle=DASH if dashed else "-", zorder=z))
    if text:
        ax.text((x0 + x1) / 2, (y0 + y1) / 2, text, ha="center", va="center", fontsize=FS, linespacing=1.1, zorder=z + 1)


def arrow(p0, p1, both=False, ctrl=False):
    """ctrl = 제어·메타데이터(파란 점선), 아니면 추론 요청 데이터(실선)"""
    ax.annotate("", p1, p0, arrowprops=dict(arrowstyle="<|-|>" if both else "-|>", color=CTRL if ctrl else LINE,
                                            linewidth=0.7, linestyle=DASH if ctrl else "-",
                                            mutation_scale=6, shrinkA=0, shrinkB=0), zorder=1)


def mid(c):
    return sum(C[c]) / 2


def note(x, y, text, ha="left", ctrl=False):
    ax.text(x, y, text, ha=ha, va="center", fontsize=FS, style="italic", linespacing=1.05,
            color=CTRL if ctrl else cm.MUTED, zorder=4)


def tag(x, y, text):
    """제안 부분 이름표"""
    ax.text(x, y, text, ha="left", va="top", fontsize=FS, fontweight="bold", color=HL_EDGE, zorder=4)


band(3.06, 3.66, "Host")
band(0.84, 2.98, "FPGA")
band(0.32, 0.78, "DDR3")

# Host: 특징 추출 → Offset Assignment(제안 SW) → 추론 요청. 결과로 판정
HY = (3.13, 3.59)
box(*C[0], *HY, "Mel features\n(1,024 tracks)")
box(C[1][0], C[2][1], *HY, hl=True)
tag(C[1][0] + 0.05, HY[1] - 0.03, "Proposed (SW)")
ax.text(mid(1) / 2 + mid(2) / 2, HY[0] + 0.15, "Model-Grouped Offset Assignment\n$O_m = m \\times 0.8$ ms", ha="center",
        va="center", fontsize=FS, linespacing=1.1, zorder=3)
box(*C[3], *HY, "Classification")
arrow((C[0][1], sum(HY) / 2), (C[1][0], sum(HY) / 2))

# FPGA: Ethernet, B행(추론 요청 → batch → 연산), C행(설정 → Weight cache[predictor, entry]), D행(DMA, membrane bank)
EY, RB, RC = (2.64, 2.78), (2.06, 2.52), (1.22, 1.86)
box(C[0][0], C[3][1], *EY, "Gigabit Ethernet MAC (UDP)", fill="#e9e8e3")
box(*C[1], *RB, "Ingest,\nrequest table")
box(*C[2], *RB, "Grouping\nscheduler\n(no wait)")
box(*C[3], *RB, "64-lane\ncompute array,\n100 MHz\n(RTL-verified)")

box(*C[0], RC[0] + 0.06, RC[1] - 0.06, "Registers:\noffset table,\ndelay LUTs\n(model-group\ndelay, jitter)")
box(C[1][0], C[2][1], *RC, z=1)
ax.text(C[1][0] + 0.05, RC[1] - 0.03, "Weight cache", ha="left", va="top", fontsize=FS, fontweight="bold")
PX, PY = (C[1][0] + 0.05, C[1][0] + 0.77), (RC[0] + 0.05, RC[1] - 0.16)   # Next-use predictor(제안 HW, RTL 없음 → 점선)
box(*PX, *PY, hl=True, dashed=True)
tag(PX[0] + 0.04, PY[1] - 0.025, "Proposed (HW)")
ax.text(sum(PX) / 2, PY[0] + 0.12, "Next-use\npredictor", ha="center", va="center", fontsize=FS, linespacing=1.1, zorder=3)
EX, EW, EG = 2.10, 0.10, 0.03                       # Entry 4개(각 28.5 RAMB36-equivalent tile)
SY = (RC[0] + 0.27, RC[0] + 0.36)
for i in range(4):
    ax.add_patch(Rectangle((EX + (EW + EG) * i, SY[0]), EW, SY[1] - SY[0], facecolor="white", edgecolor=LINE,
                           linewidth=0.6, zorder=3))
ECX = EX + 2 * EW + 1.5 * EG
ax.text(ECX, RC[1] - 0.04, "4 entries$^\\dagger$,\n114 BRAM tiles", ha="center", va="top", fontsize=FS, linespacing=1.05, zorder=3)
note(ECX + 0.02, RC[0] + 0.13, "locks: current,\nprefetch target", ha="center", ctrl=True)
arrow((PX[1], sum(SY) / 2), (EX, sum(SY) / 2), ctrl=True)
note((PX[1] + EX) / 2, sum(SY) / 2 - 0.085, "victim", ha="center", ctrl=True)

RD = (0.92, 1.10)
box(C[0][0], C[2][1], *RD, "DMA (one prefetch ahead)")
BY = (0.90, 1.30)
box(*C[3], *BY, f"Membrane bank\n{ON_CHIP} tracks$^\\dagger$,\n12-bit")

# 추론 요청 데이터(실선)
arrow((mid(1), HY[0]), (mid(1), EY[1]))
note(mid(1) + 0.04, 3.00, "requests")
note(mid(1) + 0.04, 2.87, "+ expected count", ctrl=True)
arrow((mid(3), EY[1]), (mid(3), HY[0]))
note(mid(3) - 0.04, 2.94, "results", ha="right")
arrow((mid(1), EY[0]), (mid(1), RB[1]))
arrow((mid(3), RB[1]), (mid(3), EY[0]))
arrow((C[1][1], sum(RB) / 2), (C[2][0], sum(RB) / 2))
arrow((C[2][1], sum(RB) / 2), (C[3][0], sum(RB) / 2))
arrow((C[2][1], sum(SY) / 2), (mid(3) - 0.17, RB[0]))        # Entry → compute array (weight)
note(C[2][1] + 0.16, sum(SY) / 2, "weights")
arrow((mid(3) + 0.20, RB[0]), (mid(3) + 0.20, BY[1]), both=True)   # Compute array ↔ membrane bank
note(mid(3) + 0.16, (RB[0] + RC[1]) / 2 - 0.02, "state", ha="right")
arrow((ECX, RD[1]), (ECX, RC[0]))                              # DMA → entry
DY = (0.39, 0.69)
box(C[0][0], C[3][1], *DY, f"Weights of 40 models (4.97 MiB) $\\cdot$ membrane potential of {IN_DDR3} tracks$^\\dagger$")
arrow((mid(0), DY[1]), (mid(0), RD[0]), both=True)
note(mid(0) + 0.04, (DY[1] + RD[0]) / 2, "weights, state")

# 제어·메타데이터(파란 점선)
arrow((C[1][0] + 0.10, HY[0]), (C[1][0] + 0.10, EY[1]), ctrl=True)
note(C[1][0] + 0.06, 2.94, "start-up\nregisters", ha="right", ctrl=True)
arrow((C[0][0] + 0.07, EY[0]), (C[0][0] + 0.07, RC[1] - 0.06), ctrl=True)
note(C[0][0] + 0.11, sum(RB) / 2, "offset table,\ndelay LUTs,\ntrack/model\ncounts", ctrl=True)
arrow((C[0][1], sum(PY) / 2), (PX[0], sum(PY) / 2), ctrl=True)
arrow((PX[1] - 0.10, RB[0]), (PX[1] - 0.10, PY[1]), ctrl=True)   # "Weight cache" 글자 오른쪽으로 지난다
note(PX[1] - 0.14, (RB[0] + RC[1]) / 2, "period/count, arrival\ntime, queue state", ha="right", ctrl=True)
arrow((mid(2), RB[0]), (mid(2), RC[1]), ctrl=True)
note(mid(2) + 0.04, (RB[0] + RC[1]) / 2, "next model", ctrl=True)

ax.legend(handles=[Line2D([], [], color=LINE, linewidth=0.7, label="request data"),
                   Line2D([], [], color=CTRL, linewidth=0.7, linestyle=DASH, label="control / metadata"),
                   Patch(facecolor=HL_FILL, edgecolor=HL_EDGE, linewidth=0.8, label="proposed"),
                   Patch(facecolor=HL_FILL, edgecolor=HL_EDGE, linewidth=0.8, linestyle=DASH,
                         label="proposed, no RTL yet")],
          loc="lower center", bbox_to_anchor=(W / 2, 0.0), bbox_transform=ax.transData, ncol=2, frameon=False,
          fontsize=FS, handlelength=1.8, columnspacing=1.2, borderaxespad=0.1, labelspacing=0.3)

ax.text(W / 2, -FOOT / 2, "$^\\dagger$evaluated configuration; the entry count is set after measuring the target Host",
        ha="center", va="center", fontsize=6.5, style="italic", color=cm.MUTED)
cm.save(fig, __file__, exts=("pdf", "png"), dpi=300)
