"""논문용 도착·cache 예시(offset/fig5의 확장): nominal frame 끝과 실제 도착을 나누고, entry 4개의 victim 선택 한 번을 보인다.
영문, 그림 안 제목 없음, 단 폭 3.5 in, 글자 7 pt 이상.

입력: 없음. simulation 결과가 아니라 설명용 예시다(P3.26 §2.1·§2.2)
  모델 A~E(offset 0, 0.8, …, 3.2 ms: 모델 40개 중 이웃한 5개, 나머지 모델은 생략), 모델마다 트랙 3개
  도착 = O_m + G_m(모델 묶음 지연, 그 모델 트랙 모두 같음) + j(추론 요청별, 0 ≤ j < J = 0.8 ms). 값은 손으로 골랐고 C 묶음만 3 ms 늦다
  cache는 앞 주기에서 A·B·C·D를 담은 상태(steady)로 시작한다. 처리 규칙은 engine.py와 같다: Grouping(가장 먼저 도착한 대기
  추론 요청의 모델, 기다리지 않음), 한 batch 앞 적재, 가장 최근 batch의 entry는 잠금, PNU-count 교체. 묶음 지연 분포는 Uniform(0, 4 ms)로 둔다
    첫 추론 요청 전(el < τ_G):      t̂ = 지금 + δ_G(el, 1) = 지금 + (4 − el)/2
    첫 추론 요청 a1 뒤, 남은 r > 0:  t̂ = 지금 + (J − (지금 − a1))/(r + 1)
    그 밖:                       t̂ = 다음 주기 offset + E[G] + J/(n + 1)
  비교용 jitter만 보는 식(P3.25): el < J이고 r > 0일 때만 이번 주기로 보고, 아니면 다음 주기 offset + J/(n + 1)
  weight 적재 43.9 µs, 추론 5.36 µs(P4.1 평균)
실행: python3 analysis/develop/offset/fig6_x-time_y-arrival-cache.py
출력: analysis/figure/offset/fig6_x-time_y-arrival-cache.{pdf,png}. 교체 전 판은 analysis/discards/*/offset/fig6_*_p325.*
"""
import os
import sys
from collections import OrderedDict

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.paper_style()
T, SLOT, J, GMAX = 32.0, 0.8, 0.8, 4.0     # 주기, offset 간격 T/M(M = 40), jitter 폭, 묶음 지연 분포 Uniform(0, GMAX) (ms)
LOAD, INF = 0.0439, 0.00536                # weight 적재 43.9 µs, 추론 1번 535.9 cycle (ms)
NAMES, N, E = "ABCDE", 3, 4                # 모델, 모델당 트랙, entry
SEED = 970743                              # (a)의 무작위 offset(교체 전 판과 같은 그림)
COLOR = dict(zip(NAMES, list(cm.TYPE_COLOR.values())[:5]))
MARK = dict(zip(NAMES, "os^Dv"))
O = {m: SLOT * k for k, m in enumerate(NAMES)}
G = dict(A=0.3, B=0.5, C=3.0, D=0.2, E=0.25)                       # 모델 묶음 지연(C만 늦음)
U = dict(A=(0.05, 0.3, 0.5), B=(0.1, 0.4, 0.75), C=(0.1, 0.3, 0.6), D=(0.0, 0.2, 0.45), E=(0.1, 0.35, 0.6))
arr = sorted((O[m] + G[m] + u, m) for m in NAMES for u in U[m])     # (도착 ms, 모델)

rng = np.random.default_rng(SEED)
rng.random((5, N))                         # 교체 전 판의 도착 난수 자리(같은 (a)를 그리려고 버린다)
rand_ofs = rng.uniform(0, T, (5, N))       # (a) 트랙별 무작위 frame 끝


def t_hat(x, now, queued, got, a1, group=True):
    """PNU-count 다음 사용 예측. group = False면 묶음 지연을 모르는 P3.25 식"""
    if x in queued:
        return now
    el, r, nxt = now - O[x], N - got[x], O[x] + T + J / (N + 1)
    if not group:
        return now + (J - el) / (r + 1) if r > 0 and 0 <= el < J else nxt
    if x not in a1:
        return now + (GMAX - el) / 2 if el < GMAX else nxt + GMAX / 2
    return now + (J - (now - a1[x])) / (r + 1) if r > 0 and now - a1[x] < J else nxt + GMAX / 2


def simulate():
    """engine.simulate의 1단 선행 규칙. 돌려줌: batch [(모델, 시작, 구성원)], 적재 [(entry, 모델, 시작)], 교체 기록"""
    lru, slot, wait, got, a1 = OrderedDict.fromkeys("ABCD", True), list("ABCD"), [], dict.fromkeys(NAMES, 0), {}
    dma = cmp = now = 0.0
    i, batches, loads, dec = 0, [], [], []

    def arrive(t):
        nonlocal i
        while i < len(arr) and arr[i][0] <= t:
            wait.append(i)
            got[arr[i][1]] += 1
            a1.setdefault(arr[i][1], arr[i][0])
            i += 1

    while i < len(arr) or wait:
        arrive(now)
        if not wait:
            now = arr[i][0]
            continue
        m = arr[wait[0]][1]
        hit = m in lru
        if hit:
            lru.move_to_end(m)
        else:
            cur = next(reversed(lru))                   # 가장 최근 batch = 잠금. 적재 대상은 아직 entry에 없다
            q = {arr[j][1] for j in wait} - {m}
            th = {x: t_hat(x, now, q, got, a1) for x in lru if x != cur}
            old = {x: t_hat(x, now, q, got, a1, group=False) for x in lru if x != cur}
            v = max(th, key=lambda x: (th[x], x not in q))
            dec.append(dict(t=now, cur=cur, target=m, th=th, old=old, victim=v, old_victim=max(old, key=old.get)))
            del lru[v]
            k = slot.index(v)
            slot[k] = m
            lru[m] = True
            loads.append((k, m, now))
            dma = max(now, dma) + LOAD
        s = max(dma if not hit else now, cmp)
        arrive(s)
        mem = [j for j in wait if arr[j][1] == m]
        wait[:] = [j for j in wait if arr[j][1] != m]
        cmp = s + INF * len(mem)
        batches.append((m, s, mem))
        now = s
    return batches, loads, dec


batches, loads, dec = simulate()
assert len(dec) == 1, "교체가 한 번이어야 한다"
D0 = dec[0]
TS = D0["t"]
assert (D0["cur"], D0["target"], D0["victim"], D0["old_victim"]) == ("D", "E", "B", "C"), D0
assert D0["th"]["C"] < arr[[m for _, m in arr].index("C")][0] < D0["old"]["C"]   # C는 곧 온다: 고친 식은 맞히고 옛 식은 다음 주기로 본다
nb = {m: sum(b[0] == m for b in batches) for m in NAMES}

W, H, X0, X1 = 3.5, 4.75, 0.30, 3.06       # inch. 축 오른쪽 여백에 batch 수를 적는다
fig = plt.figure(figsize=(W, H))


def axes(top, h):
    """그림 위에서 top inch, 높이 h inch인 축"""
    return fig.add_axes([X0 / W, 1 - (top + h) / H, (X1 - X0) / W, h / H])


ax_a, ax_b, ax_c, ax_d = axes(0.42, 0.60), axes(1.22, 0.60), axes(2.32, 0.98), axes(3.66, 0.64)
ROW = {m: k for k, m in enumerate(NAMES)}


def rows(ax, labels, colors, title, xlim):
    ax.set_xlim(*xlim)
    ax.set_ylim(len(labels) - 0.4, -0.6)
    ax.set_yticks(range(len(labels)), labels)
    for lab, c in zip(ax.get_yticklabels(), colors):
        lab.set_color(c)
    ax.grid(False)
    cm.clean(ax)
    ax.spines["bottom"].set_visible(True)
    ax.spines["bottom"].set_color(cm.GRAY)
    ax.tick_params(axis="x", length=2, pad=1, color=cm.GRAY)
    ax.set_title(title, loc="left", fontsize=7.5, fontweight="bold", pad=3)


def nominal(ax, x, m, y=None, **kw):
    ax.plot(x, ROW[m] if y is None else y, MARK[m], ms=3.6, mfc="white", mec=COLOR[m], mew=0.8, **kw)


def actual(ax, x, m, y=None):
    ax.plot(x, ROW[m] if y is None else y, MARK[m], ms=3.6, color=COLOR[m], mec=COLOR[m], mew=0.5, zorder=3)


# (a) 무작위 offset: 트랙마다 frame 끝이 주기 안에 흩어진다
rows(ax_a, list(NAMES), [COLOR[m] for m in NAMES], "(a) Unaligned: random offsets", (-0.6, T + 0.6))
for m, xs in zip(NAMES, rand_ofs):
    for x in xs:
        nominal(ax_a, x, m)
ax_a.set_xticks([0, 8, 16, 24, 32], [])

# (b) Model-Grouped Offset Assignment: 같은 모델 트랙의 frame 끝이 O_m에서 겹친다. 회색 = 생략한 다른 35모델의 offset
rows(ax_b, list(NAMES), [COLOR[m] for m in NAMES], "(b) Model-Grouped Offset Assignment", (-0.6, T + 0.6))
for m in NAMES:
    nominal(ax_b, O[m], m)
    ax_b.text(O[m] + 0.9, ROW[m], f"$\\times${N}", color=COLOR[m], fontsize=7, va="center")
ax_b.vlines(np.arange(5, 40) * SLOT, 4.25, 4.55, color=cm.GRAY, linewidth=0.6)
ax_b.text(19.6, 3.55, "offsets of the other 35 models", color=cm.MUTED, fontsize=7, ha="center", va="center")
ax_b.set_xticks([0, 8, 16, 24, 32])
ax_b.set_xlabel("Time in period (ms)", labelpad=1)
XZ = (-0.25, 6.65)                          # (c)·(d)가 확대하는 구간
ax_b.add_patch(Rectangle((XZ[0], -0.55), XZ[1] - XZ[0], 5.05, fill=False, edgecolor=cm.MUTED, linewidth=0.5,
                         linestyle=(0, (2, 1.5)), zorder=0))
ax_b.text(XZ[1] + 0.5, 0, "enlarged in (c) and (d)", color=cm.MUTED, fontsize=7, style="italic", va="center")

# (c) 실제 도착: O_m 뒤 묶음 지연 G만큼 밀린 뒤 폭 J 안에 온다. C 묶음은 3 ms 늦다
rows(ax_c, list(NAMES), [COLOR[m] for m in NAMES], f"(c) Arrivals: group delay $G$ + jitter $J$ = {J:g} ms", XZ)
ax_c.set_ylim(4.95, -0.6)
for m in NAMES:
    y = ROW[m]
    ax_c.add_patch(Rectangle((O[m] + G[m], y - 0.32), J, 0.64, facecolor=COLOR[m] + "22", edgecolor=COLOR[m] + "88",
                             linewidth=0.5, zorder=1))
    ax_c.hlines(y, O[m], O[m] + G[m], color=COLOR[m], linewidth=0.5, linestyle=(0, (2, 1.5)), zorder=1)
    nominal(ax_c, O[m], m, zorder=2)
for m, s, mem in batches:
    for j in mem:
        actual(ax_c, arr[j][0], m)
ax_c.text(O["C"] + G["C"] / 2, ROW["C"] - 0.1, f"$G$ = {G['C']:g} ms (whole group late)", color=COLOR["C"], fontsize=6.5,
          ha="center", va="bottom", bbox=dict(facecolor="white", edgecolor="none", pad=0.2), zorder=5)   # t* 선 위
ax_c.text(O["C"] + G["C"] + J / 2, ROW["C"] + 0.42, "$J$", color=COLOR["C"], fontsize=6.5, ha="center", va="top")
for m in NAMES:
    ax_c.text(XZ[1] + 0.15, ROW[m], f"{nb[m]}", color=COLOR[m], fontsize=7, ha="left", va="center", clip_on=False)
ax_c.text(XZ[1] + 0.15, -1.15, "batches", color=cm.MUTED, fontsize=7, ha="left", va="center", clip_on=False)
ax_c.set_xticks(np.arange(0, 6.5, 0.8), [f"{x:g}" for x in np.arange(0, 6.5, 0.8)])

# (d) entry 4개: 앞 주기의 A·B·C·D로 시작해 t*에 E를 적재하며 victim을 고른다
rows(ax_d, [f"e{k + 1}" for k in range(E)], [cm.INK] * E, "(d) Weight cache: victim selection at $t^*$", XZ)
seq = {k: [(XZ[0], m)] for k, m in enumerate("ABCD")}
for k, m, t0 in loads:
    seq[k].append((t0, m))
for k, s in seq.items():
    for (t0, m), nxt in zip(s, s[1:] + [(XZ[1], None)]):
        ax_d.add_patch(Rectangle((t0, k - 0.36), nxt[0] - t0, 0.72, facecolor=COLOR[m] + "33", edgecolor=COLOR[m],
                                 linewidth=0.6, zorder=1))
ax_d.set_xticks(np.arange(0, 6.5, 0.8), [f"{x:g}" for x in np.arange(0, 6.5, 0.8)])
ax_d.set_xlabel("Time (ms)", labelpad=1)
EK = {m: k for k, m in enumerate("ABCD")} | {m: k for k, m, _ in loads}   # 모델 → entry (E는 victim 자리)
th, old = D0["th"], D0["old"]


def role(m, text, left=False):
    ax_d.text(TS + (-0.05 if left else 0.08), EK[m], text, fontsize=7, va="center", ha="right" if left else "left",
              color=cm.INK, zorder=5)


role("B", f"B: $\\hat{{t}}$ = {th['B']:.1f} ms → victim", left=True)
role("E", "E: prefetch target")
role("A", f"A: $\\hat{{t}}$ = {th['A']:.1f} ms → keep")
role("C", f"C: $\\hat{{t}}$ = {th['C']:.1f} ms → keep")
role("D", "D: most recent, locked")
fig.text(0.5, 0.005, f"A jitter-only predictor puts C at $\\hat{{t}}$ = {old['C']:.1f} ms and evicts it;"
         f" C arrives at {min(a for a, m in arr if m == 'C'):.1f} ms.", ha="center", va="bottom", fontsize=6.3, color=cm.MUTED)

for ax in (ax_c, ax_d):
    ax.axvline(TS, color=cm.INK, linewidth=0.6, linestyle=(0, (3, 1.5)), zorder=4)
ax_c.text(TS, 4.62, "$t^*$", ha="center", va="center", fontsize=7, bbox=dict(facecolor="white", edgecolor="none", pad=0.2), zorder=5)

fig.legend(handles=[Line2D([], [], marker="o", ls="", ms=3.6, mfc="white", mec=cm.MUTED, label="nominal frame end"),
                    Line2D([], [], marker="o", ls="", ms=3.6, color=cm.MUTED, label="actual arrival"),
                    Patch(facecolor=cm.GRAY + "44", edgecolor=cm.MUTED, linewidth=0.5, label="$[O_m + G, O_m + G + J)$")],
           loc="upper center", ncol=3, frameon=False, fontsize=7, bbox_to_anchor=(0.5, 1.0), borderaxespad=0.2,
           handlelength=1.2, columnspacing=1.0, handletextpad=0.4)

cm.save(fig, __file__, exts=("pdf", "png"), dpi=300)
