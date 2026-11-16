"""RTL 블록도 공용 그리기 함수. 좌표는 inch, 원점은 왼쪽 위(y가 아래로 커진다).

모듈 = 굵은 테두리 상자, 이름은 파일 이름(굵게)과 instance 이름. 내부 블록·저장소 = 얇은 상자.
신호선: 1 bit는 가는 선, bus는 굵은 선. 화살표는 신호 방향. clock·reset은 그리지 않는다.
"""
import os
import sys

import matplotlib.pyplot as plt
from matplotlib.patches import Polygon, Rectangle

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

INK, MUTED = "#222222", "#5a5a5a"
FILL_MOD, FILL_SUB, FILL_MEM, FILL_IP = "#ffffff", "#f4f6f9", "#e8eef7", "#efefec"
FS = 9


class Sheet:
    def __init__(self, w, h):
        plt.rcParams.update({"font.family": "Pretendard", "font.size": FS, "axes.unicode_minus": False})
        self.fig = plt.figure(figsize=(w, h))
        self.ax = self.fig.add_axes([0, 0, 1, 1])
        self.ax.set_xlim(0, w)
        self.ax.set_ylim(h, 0)
        self.ax.axis("off")

    # ---------- 상자 ----------
    def module(self, x0, y0, x1, y1, name, inst=None, at="br", lw=1.6, fill=FILL_MOD, size=12, z=1):
        """모듈 테두리. at: 이름 위치 br(오른쪽 아래), tr, bl, tl, bc, tc"""
        self.ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, facecolor=fill, edgecolor=INK, linewidth=lw, zorder=z))
        pad = 0.1
        ha = {"l": "left", "r": "right", "c": "center"}[at[1]]
        va = "top" if at[0] == "t" else "bottom"
        x = {"l": x0 + pad, "r": x1 - pad, "c": (x0 + x1) / 2}[at[1]]
        y = y0 + pad if at[0] == "t" else y1 - pad
        txt = name if inst is None else f"{name}  ({inst})"
        self.ax.text(x, y, txt, ha=ha, va=va, fontsize=size, fontweight="bold", color=INK, zorder=z + 5)

    def block(self, x0, y0, x1, y1, text, fill=FILL_SUB, size=FS, lw=0.8, dashed=False, bold=False, z=3, poly=None):
        """내부 블록·저장소. 첫 줄을 굵게 하려면 bold=True"""
        ls = (0, (3, 2)) if dashed else "-"
        self.ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, facecolor=fill, edgecolor=INK, linewidth=lw,
                                    linestyle=ls, zorder=z))
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        if bold and "\n" in text:
            head, rest = text.split("\n", 1)
            n = rest.count("\n") + 1
            lh = size / 72 * 1.25
            gap = 0.2 * lh                      # 굵은 제목과 설명 사이
            top = cy - ((n + 1) * lh + gap) / 2
            self.ax.text(cx, top + lh / 2, head, ha="center", va="center", fontsize=size, fontweight="bold", zorder=z + 1)
            self.ax.text(cx, top + lh + gap + n * lh / 2, rest, ha="center", va="center", fontsize=size - 0.5,
                         color=MUTED, linespacing=1.25, zorder=z + 1)
        else:
            self.ax.text(cx, cy, text, ha="center", va="center", fontsize=size, linespacing=1.25,
                         fontweight="bold" if bold else "normal", zorder=z + 1)

    def mux(self, x0, y0, x1, y1, text="", sel=None):
        """왼쪽이 넓은 사다리꼴(mux). sel: 아래쪽 선택 신호 이름"""
        d = (y1 - y0) * 0.18
        self.ax.add_patch(Polygon([(x0, y0), (x1, y0 + d), (x1, y1 - d), (x0, y1)], closed=True,
                                  facecolor=FILL_SUB, edgecolor=INK, linewidth=1.0, zorder=3))
        if text:
            self.ax.text((x0 + x1) / 2, (y0 + y1) / 2, text, ha="center", va="center", rotation=90, fontsize=FS - 1, zorder=4)
        if sel:
            xm = (x0 + x1) / 2
            self.wire([(xm, y1 + 0.32), (xm, y1 - d / 2)], end=">")
            self.ax.text(xm, y1 + 0.34, sel, ha="center", va="top", fontsize=FS - 0.5, zorder=4)

    # ---------- 선 ----------
    def wire(self, pts, label=None, bus=False, end=">", seg=0, frac=0.0, side="above", ha="left", size=FS - 0.5,
             color=INK, dx=0.06, dot=None):
        """pts를 잇는 선. end: '>' 끝에 화살표, '<' 시작에 화살표, '<>' 양쪽, '' 없음.
        label은 seg번째 구간 위(side=above) 또는 아래(below), 세로 구간이면 오른쪽(right)·왼쪽(left)에 둔다.
        frac: 구간 안 위치(0 = 시작 쪽). dot: junction 점을 찍을 점 목록"""
        lw = 2.2 if bus else 1.0
        xs, ys = zip(*pts)
        self.ax.plot(xs, ys, color=color, linewidth=lw, solid_capstyle="butt", solid_joinstyle="miter", zorder=2)
        ms = 9 if bus else 7
        if ">" in end:
            self._head(pts[-2], pts[-1], ms, color)
        if "<" in end:
            self._head(pts[1], pts[0], ms, color)
        for p in dot or []:
            self.ax.plot(*p, marker="o", markersize=4.5, color=color, zorder=4)
        if label:
            (ax_, ay), (bx, by) = pts[seg], pts[seg + 1]
            x = ax_ + (bx - ax_) * frac
            y = ay + (by - ay) * frac
            if side in ("above", "below"):
                off = -0.05 if side == "above" else 0.05
                xx = x + (dx if ha == "left" else -dx if ha == "right" else 0)
                self.ax.text(xx, y + off, label, ha=ha, va="bottom" if side == "above" else "top", fontsize=size,
                             color=color, linespacing=1.15, zorder=5)
            else:
                off = 0.07 if side == "right" else -0.07
                self.ax.text(x + off, y, label, ha="left" if side == "right" else "right", va="center", fontsize=size,
                             color=color, linespacing=1.15, zorder=5)

    def _head(self, p0, p1, ms, color):
        self.ax.annotate("", xy=p1, xytext=p0, arrowprops=dict(arrowstyle="-|>", color=color, lw=0,
                                                               mutation_scale=ms * 1.6, shrinkA=0, shrinkB=0), zorder=4)

    def text(self, x, y, s, ha="left", va="center", size=FS, color=INK, bold=False, italic=False):
        self.ax.text(x, y, s, ha=ha, va=va, fontsize=size, color=color, fontweight="bold" if bold else "normal",
                     style="italic" if italic else "normal", linespacing=1.25, zorder=6)

    def save(self, script):
        cm.save(self.fig, script, exts=("png", "pdf"), dpi=200)
