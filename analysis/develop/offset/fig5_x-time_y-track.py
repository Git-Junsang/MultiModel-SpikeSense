"""논문용 Offset Assignment 개념도 (analysis/discards/develop/alignment/fig3의 사본: 영문, 그림 안 제목 없음, 단 폭 3.5 in, 흰 배경, mic 입력 단 생략). Simulation 결과를 쓰지 않는다

트랙마다 64 ms mel 창이 32 ms(T)마다 끝나고, 창이 끝나는 시각에 추론 요청이 나간다. 이웃 창은 반씩 겹치므로 두 줄로 엇갈려 그린다.
계속 돌고 있는 stream의 한 구간이라 0 ms 앞의 오디오도 창에 들어간다(버리는 오디오 없음)
(c)는 (b)의 추론 요청이 FPGA에 도착하는 시각이다(P3.26 §2.1). Frame 끝은 O_m에 그대로 있고, Host 처리 지연이 두 부분으로 붙는다.
모델·주기 모델 그룹 지연 G는 그 모델의 모든 트랙에 같이 붙고 주기마다 바뀐다. 그 위에 추론 요청별 지연 j(0 ≤ j < J)가 붙고, jitter J는 이 퍼짐이다.
주기 하나만 그린다. 이 주기에 모델 C는 모델 그룹 전체가 5 ms 늦다(jitter는 그대로 작다). 고정 seed의 설명용 예시이고 simulation 값이 아니다.
교체 전 그림은 analysis/discards/figure/offset/fig5_x-time_y-track*.*에 있다(_p325 = 추론 요청별 지연만 그린 P3.25 판, _3period = 주기 3개를 겹친 판)
"""
import os
import sys

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Patch, Rectangle

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.sim_style()
plt.rcParams.update({"font.family": "serif", "font.serif": ["Liberation Serif"],
                     "mathtext.fontset": "stix", "font.size": 7, "pdf.fonttype": 42,
                     "figure.facecolor": "white", "axes.facecolor": "white",
                     "hatch.color": cm.MUTED, "hatch.linewidth": 0.5})

FAMILY = ["Liberation Serif", "FreeSerif"]   # ①②는 Liberation Serif에 없어 FreeSerif로 채운다
T, END, WIN = 32.0, 98.0, 64.0             # 주기(hop), 그릴 시간, mel 창 (ms)
TRACKS = "ABADCEEACD"                      # 트랙 0–9의 모델. 모델 5개만 그린다
N, M = len(TRACKS), 5
COLOR = dict(zip("ABCDE", list(cm.TYPE_COLOR.values())[:5]))
_r = np.random.default_rng(5)              # 옛 fig3과 같은 무작위 offset
RAND_OFS = 1.6 + 3.2 * _r.permutation(N) + _r.uniform(-0.6, 0.6, N)


def track_axis(ax, order, title, top, req_y):
    """req_y: 추론 요청 줄의 y. 같은 시각 추론 요청을 쌓을 자리만큼 아래로 둔다"""
    ax.set_xlim(-5.5, END + 4.5)           # 막대 앞뒤 ⋯ 자리. 0 ms 추론 요청 글자도 왼쪽 이름과 겹치지 않는다
    ax.set_ylim(req_y + 0.5, top)
    ax.set_yticks([*range(N), req_y], [*(f"$t_{{{t}}}$ ({TRACKS[t]})" for t in order), "requests"])
    ax.req_y = req_y
    for lab, t in zip(ax.get_yticklabels(), order):
        lab.set_color(COLOR[TRACKS[t]])
    ax.vlines([0, 32, 64, 96], -0.6, req_y + 0.4, color=cm.GRAY, linewidth=0.5, zorder=0)
    ax.hlines(N - 0.15, 0, END, color=cm.GRAY, linewidth=0.5)
    ax.set_xticks([])
    ax.grid(False)
    cm.clean(ax)
    ax.tick_params(axis="y", pad=1.5)
    for tick in ax.yaxis.get_major_ticks()[:N]:   # 트랙 이름만 2 pt 더 막대 쪽으로
        tick.set_pad(-0.5)
    ax.set_title(title, loc="left", fontsize=7.5, fontweight="bold", pad=2)


def windows(ax, row, t, first):
    """first + kT에 끝나는 64 ms 창. k의 홀짝으로 위·아래 줄을 나눠 겹침을 보이고, 끝(추론 요청 시각)을 굵게 긋는다. [0, END] 밖은 자른다"""
    c = COLOR[TRACKS[t]]
    for k in range(-2, 6):
        e = first + k * T
        a, b = max(e - WIN, 0), min(e, END)
        if b <= a:
            continue
        y0 = row - 0.4 + 0.44 * (k % 2)
        ax.broken_barh([(a + (0.4 if a > 0 else 0), b - a - (0.4 if a > 0 else 0))], (y0, 0.36), facecolor=c + "40",
                       edgecolor=c, linewidth=0.5)
        if e <= END:
            ax.vlines(e, y0, y0 + 0.36, color=c, linewidth=1.6)
    for x, ha in ((-0.6, "right"), (END + 0.6, "left")):   # stream이 그림 앞뒤로 이어진다
        ax.text(x, row + 0.12, r"$\cdots$", color=cm.MUTED, fontsize=7, ha=ha, va="center")   # 수식 상자 위쪽 여백만큼 내린다


def requests(ax, times):
    """추론 요청(frame 끝) 시각을 모델 글자로 찍고 같은 시각이면 쌓는다. 한 주기 안의 모델 전환 횟수를 오른쪽 위에 적는다"""
    seen = []
    for x, t in sorted(times):
        k = sum(abs(x - s) < 1.0 for s in seen)
        seen.append(x)
        ax.text(x, ax.req_y - 0.62 * k, TRACKS[t], color=COLOR[TRACKS[t]], fontsize=6.5, fontweight="bold",
                ha="center", va="center")
    seq = [TRACKS[t] for x, t in sorted(times) if 32 <= x < 64]
    n = sum(a != b for a, b in zip(seq, seq[-1:] + seq[:-1]))   # 주기 경계를 넘어 이어 센다
    ax.set_title(f"{n} model switches per period", loc="right", fontsize=7, fontweight="normal", color=cm.MUTED, pad=2)


fig, (ax_a, ax_b, ax_c) = plt.subplots(3, 1, figsize=(3.5, 5.85), gridspec_kw={"height_ratios": [N + 1.1, N + 4.95, N + 2.6]})
raw = list(range(N))

# (a) 무작위 offset
track_axis(ax_a, raw, "(a) Random offset", -0.6, N + 0.6)
req = []
for row, t in enumerate(raw):
    windows(ax_a, row, t, RAND_OFS[t])
    req += [(x, t) for x in RAND_OFS[t] + T * np.arange(4) if x <= END]
requests(ax_a, req)

# (b) Model-Grouped Offset Assignment
order = sorted(raw, key=lambda t: (TRACKS[t], t))
track_axis(ax_b, order, "(b) Model-Grouped Offset Assignment", -3.0, N + 1.95)
req = []
for row, t in enumerate(order):
    o = T / M * "ABCDE".index(TRACKS[t])
    windows(ax_b, row, t, o)
    req += [(o + T * k, t) for k in range(4) if o + T * k <= END]
for i, m in enumerate("ABCDE"):
    o = T / M * i
    ax_b.vlines(o, -0.5, N - 0.4, color=COLOR[m], linewidth=0.6, linestyle=":", zorder=0)
    ax_b.text(o, -1.05, f"$O_{m}$", color=COLOR[m], fontsize=7, ha="center", va="center")
ax_b.annotate("", (0, -2.35), (T / M, -2.35), arrowprops=dict(arrowstyle="<->", color=cm.MUTED, linewidth=0.6,
                                                             shrinkA=0, shrinkB=0, mutation_scale=6))
ax_b.text(T / M + 0.6, -2.35, f"$T/M$ = {T / M:g} ms", fontsize=7, color=cm.MUTED, ha="left", va="center")
# 추론 요청 ①(64 ms, 모델 A)과 ②(76.8 ms, 모델 C)가 쓰는 창을 방향이 다른 빗금으로 겹쳐 그린다. 같은 모델 트랙이 한 batch로 처리된다
MARK = [("①", 2 * T, "A", "////"), ("②", 2 * T + 2 * T / M, "C", "\\\\\\\\")]
for num, e, m, hatch in MARK:
    for row, t in enumerate(order):
        if TRACKS[t] == m:
            ax_b.add_patch(Rectangle((e - WIN, row - 0.4), WIN, 0.36, fill=False, hatch=hatch, edgecolor=COLOR[m],
                                     linewidth=0, zorder=2))
ax_b.vlines(MARK[1][1], -0.6, ax_b.req_y + 0.4, color=cm.GRAY, linewidth=0.5, linestyle=(0, (3, 2)), zorder=0)   # 주기 선과 같은 굵기·색
ax_b.legend(handles=[Patch(facecolor="white", edgecolor=cm.MUTED, hatch=h, linewidth=0.5, label=f"frame of request {n}")
                     for n, _, _, h in MARK], loc="center right", bbox_to_anchor=(END, -2.35), bbox_transform=ax_b.transData, ncol=2,
            frameon=False, prop={"family": FAMILY, "size": 6.5}, handlelength=1.6, columnspacing=1.0, borderaxespad=0, borderpad=0)   # T/M 줄과 같은 높이
requests(ax_b, req)
ax_b.set_xticks([0, 32, 64, MARK[1][1], 96], ["0", "32", "64", f"{MARK[1][1]:g}", "96"])
ax_b.tick_params(axis="x", pad=1)
ax_b.set_xlabel("Time (ms)", labelpad=1)

# (c) 실제 도착: frame 끝 O_m + kT 뒤에 모델 그룹 지연 G(모델·주기마다 하나) + 추론 요청별 지연 j(0 ≤ j < J)
J, LATE = 0.8, ("C", 5.0)                   # 이 주기에 모델 C의 모델 그룹 전체가 5 ms 늦다
rg = np.random.default_rng(11)
G = rg.uniform(0.4, 1.6, M)
G["ABCDE".index(LATE[0])] = LATE[1]
delay = G[["ABCDE".index(TRACKS[t]) for t in range(N)]] + rg.uniform(0, J, N)
ax_c.set_xlim(-1.2, T + 0.4)
ax_c.set_ylim(N - 0.45, -1.3)
ax_c.set_yticks(range(N), [f"$t_{{{t}}}$ ({TRACKS[t]})" for t in order])
for lab, t in zip(ax_c.get_yticklabels(), order):
    lab.set_color(COLOR[TRACKS[t]])
ax_c.grid(False)
cm.clean(ax_c)
ax_c.tick_params(axis="y", pad=1.5)
for i, m in enumerate("ABCDE"):
    o = T / M * i
    ax_c.vlines(o, -0.6, N - 0.5, color=COLOR[m], linewidth=0.6, linestyle=":", zorder=1)
    ax_c.text(o, -0.95, f"$O_{m}$", color=COLOR[m], fontsize=7, ha="center", va="center")
rows_c = [row for row, t in enumerate(order) if TRACKS[t] == LATE[0]]
x_late = T / M * "ABCDE".index(LATE[0]) + LATE[1]
ax_c.annotate(f"model {LATE[0]}: the whole model group\nis {LATE[1]:g} ms late ($G(m, k)$), spread stays < $J$", (x_late + J / 2, min(rows_c) - 0.3),
              xytext=(T, 1.3), ha="right", va="center", fontsize=6.3, color=COLOR[LATE[0]],
              bbox=dict(facecolor="white", edgecolor="none", pad=0.6),   # 위를 지나는 O_m 점선이 글자를 가르지 않게
              arrowprops=dict(arrowstyle="->", color=COLOR[LATE[0]], linewidth=0.6, shrinkA=0, shrinkB=1, mutation_scale=6))
for row, t in enumerate(order):
    o = T / M * "ABCDE".index(TRACKS[t])
    ax_c.hlines(row, o, o + delay[t], color=COLOR[TRACKS[t]], linewidth=0.4, zorder=1)
    ax_c.plot(o + delay[t], row, marker="o", markersize=3.2, color=COLOR[TRACKS[t]], linestyle="none", zorder=3)
ax_c.set_xticks([T / M * i for i in range(M)] + [T], [f"{T / M * i:g}" for i in range(M)] + [f"{T:g}"])
ax_c.tick_params(axis="x", pad=1)
ax_c.set_xlabel("Time after the period start (ms)", labelpad=1)
ax_c.set_title(f"(c) Arrival at the FPGA: model-group delay $G(m, k)$ and jitter $J$ = {J:g} ms", loc="left", fontsize=7.2, fontweight="bold", pad=2)
ax_c.text(0.5, -0.2, "arrival = $O_m + kT + G(m, k)$ (same for a model's tracks) $+\\,j(i, k)$ ($0 \\leq j(i, k) < J$)",
          transform=ax_c.transAxes, ha="center", va="top", fontsize=6.5)

fig.legend(handles=[Patch(facecolor=cm.GRAY + "55", edgecolor=cm.MUTED, linewidth=0.5,
                          label="64 ms frame; a request at each frame end, every $T$ = 32 ms")],
           loc="upper center", ncol=1, frameon=False, fontsize=7, bbox_to_anchor=(0.5, 1.0), borderaxespad=0,
           handlelength=1.6, columnspacing=1.2)
fig.tight_layout(pad=0.2, h_pad=0.6, rect=(0, 0, 1, 0.97))
# ①·②를 x축 숫자 64·76.8 바로 앞에 붙인다. 숫자 폭과 높이를 그린 뒤 재서 맞춘다
fig.canvas.draw()
pt = 72 / fig.dpi
bottom = ax_b.get_window_extent().y0
for (num, e, _, _), lab in zip(MARK, [l for l in ax_b.get_xticklabels() if l.get_text() in ("64", f"{MARK[1][1]:g}")]):
    bb = lab.get_window_extent()
    ax_b.annotate(num, (e, 0), xycoords=("data", "axes fraction"), xytext=(-bb.width / 2 * pt - 1, ((bb.y0 + bb.y1) / 2 - bottom) * pt),
                  textcoords="offset points", ha="right", va="center", fontsize=7, color=cm.MUTED, family=FAMILY)
cm.save(fig, __file__, exts=("pdf", "png"), dpi=300, bbox_inches="tight", pad_inches=0.01)
