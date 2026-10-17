"""Host 위상 정렬 개념도: 마이크 입력 → 정렬 전 → 정렬 후의 frame 경계와 요청 순서. 시뮬레이션 결과를 쓰지 않는다
"""
import os
import sys

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.sim_style()
plt.rcParams.update({"hatch.color": cm.MUTED, "hatch.linewidth": 0.6})

T, END = 32.0, 100.0                       # frame 주기, 그릴 시간 (ms)
TRACKS = "ABADCEEACD"                      # 트랙 0~9의 모델. 모델 5개만 그린다
N = len(TRACKS)
SLOT = T / 5                               # slot 간격 = 32 ms ÷ 모델 수. 실제는 40개라 0.8 ms
COLOR = dict(zip("ABCDE", list(cm.TYPE_COLOR.values())[:5]))
_r = np.random.default_rng(5)              # 정렬 전 위상: 32 ms를 10칸으로 나눠 무작위로 준다(글자가 겹치지 않게)
PHASE = 1.6 + 3.2 * _r.permutation(N) + _r.uniform(-0.6, 0.6, N)
REQ_Y = N + 2.0                            # 요청 줄의 y
SUB = ("개념도. 모델 5개·트랙 10개만 그린다. slot 간격 = 32 ms ÷ 모델 수(그림 6.4 ms, 실제 40개 0.8 ms). "
       "③은 같은 모델 트랙을 모아 그렸다")


def track_axis(ax, order, title, top=-0.6):
    ax.set_xlim(0, END)
    ax.set_ylim(N - 0.4, top)
    ax.set_yticks(range(N), [f"트랙 {t} · {TRACKS[t]}" for t in order], fontsize=7.5)
    for lab, t in zip(ax.get_yticklabels(), order):
        lab.set_color(COLOR[TRACKS[t]])
    ax.vlines([0, 32, 64, 96], -0.6, N - 0.4, color=cm.GRAY, linewidth=0.6, zorder=0)
    ax.set_xticks([])
    ax.grid(False)
    cm.clean(ax)
    ax.set_title(title, loc="left", fontsize=9)


def bar(ax, row, t, segs, **kw):
    c = COLOR[TRACKS[t]]
    ax.broken_barh(segs, (row - 0.32, 0.64), **{"facecolor": c + "33", "edgecolor": c, "linewidth": 1.0, **kw})


def frames(ax, row, t, edges):
    """edges 사이를 32 ms frame 상자로 그린다"""
    bar(ax, row, t, [(a, b - a) for a, b in zip(edges[:-1], edges[1:]) if b > a])


def requests(ax, times):
    """트랙 아래 줄에 요청(frame 끝) 시각을 모델 글자로 찍는다. 같은 시각이면 위로 쌓고, 32~64 ms 순서와 모델 전환 횟수를 적는다"""
    seen = []
    for x, t in sorted(times):
        k = sum(abs(x - s) < 1.5 for s in seen)
        seen.append(x)
        ax.text(x, REQ_Y - 0.62 * k, TRACKS[t], color=COLOR[TRACKS[t]], fontsize=7.5, fontweight="bold",
                ha="center", va="center")
    ax.hlines(N + 0.1, 0, END, color=cm.GRAY, linewidth=0.6)
    ax.vlines([0, 32, 64, 96], N + 0.1, REQ_Y + 0.4, color=cm.GRAY, linewidth=0.6, zorder=0)
    ax.text(-1.2, REQ_Y, "요청 도착", fontsize=7.5, color=cm.MUTED, ha="right", va="center")
    seq = [TRACKS[t] for x, t in sorted(times) if 32 <= x < 64]
    n = sum(a != b for a, b in zip(seq, seq[-1:] + seq[:-1]))   # 주기 경계를 넘어 이어 센다
    ax.text(END, REQ_Y + 1.0, f"32~64 ms 요청 순서  {' '.join(seq)}   →  모델 전환 {n}번 / 32 ms",
            fontsize=8, color=cm.INK, ha="right", va="center")
    ax.set_ylim(REQ_Y + 1.4, ax.get_ylim()[1])


fig = plt.figure(figsize=(7.2, 8.2))
ax_a, ax_b, ax_c = fig.subplots(3, 1, gridspec_kw={"height_ratios": [N, N + 3.7, N + 5.7]})
raw = list(range(N))

# ① 마이크 입력
track_axis(ax_a, raw, "① 마이크 입력: 트랙마다 끊김 없이 들어온다. frame을 어디서 자를지는 Host가 정한다")
for row, t in enumerate(raw):
    bar(ax_a, row, t, [(0, END)])

# ② 정렬 전: 트랙마다 아무 시각에 자른다
track_axis(ax_b, raw, "② 정렬 전: 트랙마다 아무 시각에 32 ms씩 자른다")
req_b = []
for row, t in enumerate(raw):
    cuts = [x for x in PHASE[t] + T * np.arange(4) if x <= END]
    frames(ax_b, row, t, [0, *cuts, END])
    req_b += [(x, t) for x in cuts]
requests(ax_b, req_b)

# ③ 위상 정렬: 모델 m의 트랙은 slot(m) + 32 ms × k에서 자른다
order = sorted(raw, key=lambda t: (TRACKS[t], t))
track_axis(ax_c, order, "③ 위상 정렬: 모델 m의 트랙은 slot(m) + 32 ms × k에서 자른다. 첫 경계 전 소리는 버린다", top=-2.0)
req_c = []
for row, t in enumerate(order):
    s = SLOT * "ABCDE".index(TRACKS[t])
    if s:
        ax_c.broken_barh([(0, s)], (row - 0.32, 0.64), facecolor="white", edgecolor=cm.MUTED, hatch="////", linewidth=0.8)
    frames(ax_c, row, t, [s + T * k for k in range(4) if s + T * k <= END] + [END])
    req_c += [(s + T * k, t) for k in range(1, 4) if s + T * k <= END]
for i, m in enumerate("ABCDE"):            # slot 위치
    ax_c.vlines(SLOT * i, -0.5, N - 0.4, color=COLOR[m], linewidth=0.8, linestyle=":", zorder=0)
    ax_c.text(SLOT * i, -0.8, f"slot {m}", color=COLOR[m], fontsize=7, ha="center", va="center")
ax_c.annotate("", (0, -1.55), (SLOT, -1.55), arrowprops=dict(arrowstyle="<->", color=cm.MUTED, linewidth=0.8, shrinkA=0, shrinkB=0))
ax_c.text(SLOT + 0.8, -1.55, "6.4 ms", fontsize=7, color=cm.MUTED, ha="left", va="center")
requests(ax_c, req_c)
ax_c.set_xticks([0, 32, 64, 96])
ax_c.set_xlabel("시각 (ms). 요청 = frame 끝. 마감 = 요청 + 32 ms", fontsize=8)

legend = [Patch(facecolor=cm.GRAY + "55", edgecolor=cm.MUTED, label="frame 32 ms"),
          Patch(facecolor="white", edgecolor=cm.MUTED, hatch="////", label="버림")]
cm.header(fig, "그림. Host 위상 정렬: frame을 자르는 시각만 모델별 slot에 맞춘다. 계산량·마감은 그대로",
          SUB, legend, top=0.93)
cm.save(fig, __file__, dpi=170, bbox_inches="tight")
