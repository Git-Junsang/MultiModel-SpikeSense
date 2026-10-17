"""scheduler별 DDR3 전송 ↔ 응답, 정렬 없음·LRU 10 + 제안 점 (P3.13 그림 2, 옛 fig42_p313_scheduler_pareto)

입력: simulation/result/p313_pareto.csv
"""
import os
import sys

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.sim_style()
SUB = "시뮬레이션, L·64 lane, 1,024트랙, 즉시 입출력, spike 건너뛰기"
from matplotlib.patches import Patch  # noqa: E402

GCOL = {"기준선": cm.GRAY, "선행연구식": cm.SERIES[0], "scheduler 상한": cm.SERIES[1], "제안": cm.SERIES[2]}
NAME = {"grouping": "Grouping", "dysta": "Dysta식", "clockwork": "Clockwork식", "timeout W1": "Timeout 1", "timeout W2": "Timeout 2",
        "timeout W4": "Timeout 4", "timeout W8": "Timeout 8", "deeprt": "DeepRT식", "symphony": "Symphony식",
        "slackbatch": "SlackBatch", "slackbatch_lite": "SlackBatch-Lite", "정렬·Grouping·slot4": "제안: 정렬 + Grouping + slot 4"}


def group(k):
    if k == "grouping":
        return "기준선"
    if k.startswith("slackbatch"):
        return "scheduler 상한"
    if k.startswith("정렬"):
        return "제안"
    return "선행연구식"


d = {r["label"]: dict(kib=r["dram_kib"], mean=r["mean_ms"], p99=r["p99_ms"]) for r in cm.points("p313_pareto")}
fig, axes = plt.subplots(1, 2, figsize=(8.4, 3.6), sharex=True)
ymax = dict(mean=14.0, p99=34.0)
# 이름 위치: (dx KiB, dy × y축 길이, 정렬). 겹치는 점은 좌우로 나눈다
base = {"deeprt": (-1.0, 0.03, "right"), "timeout W8": (1.0, -0.03, "left"), "symphony": (-1.0, 0.0, "right"),
        "timeout W4": (1.0, -0.035, "left"), "grouping": (1.0, 0.035, "left"), "dysta": (1.0, -0.035, "left"),
        "slackbatch": (1.0, -0.03, "left"), "slackbatch_lite": (1.0, 0.035, "left")}
OFFS = {"mean": base, "p99": dict(base, slackbatch=(1.0, -0.05, "left"), slackbatch_lite=(1.0, 0.045, "left"),
                                 grouping=(1.0, 0.06, "left"), **{"timeout W1": (-1.0, -0.03, "right")})}
for ax, ykey, ylab in zip(axes, ("mean", "p99"), ("평균 응답 ms", "p99 응답 ms")):
    tw = sorted((k for k in d if k.startswith("timeout")), key=lambda k: int(k[9:]))
    ax.plot([d[k]["kib"] for k in tw], [d[k][ykey] for k in tw], color=cm.SERIES[0], linewidth=1, alpha=0.5, zorder=1)
    for k, a in d.items():
        g = group(k)
        ax.scatter(a["kib"], a[ykey], s=46 if g == "제안" else 30, color=GCOL[g], edgecolor=cm.SURF, linewidth=1.2, zorder=3)
        if k == "clockwork":
            continue                                    # Dysta식과 같은 점. 이름은 Dysta식에 같이 적는다
        dx, dy, ha = OFFS[ykey].get(k, (1.0, 0.0, "left"))
        txt = "Dysta식 = Clockwork식" if k == "dysta" else NAME[k]
        ax.annotate(txt, (a["kib"], a[ykey]), xytext=(a["kib"] + dx, a[ykey] + dy * ymax[ykey]), fontsize=7,
                    color=cm.INK if g in ("제안", "기준선") else cm.MUTED, va="center", ha=ha)
    ax.set_xlabel("DDR3 읽기·쓰기 KiB/추론 (weight + 막전위)")
    ax.set_ylabel(ylab)
    ax.set_xlim(0, 62)
    ax.set_ylim(0, ymax[ykey])
    cm.clean(ax)
axes[1].axhline(32, color=cm.INK, linewidth=0.8, linestyle=(0, (3, 3)))
axes[1].text(61, 32.3, "마감 32 ms", ha="right", va="bottom", fontsize=7.5, color=cm.INK)
cm.header(fig, "그림 2. scheduler는 DDR과 응답을 맞바꾼다. 정렬은 둘 다 줄인다",
          f"{SUB}. 정렬 없음·LRU 10 entry, Timeout 뒤 숫자 = 대기 상한 ms. 시나리오 6 × 시드 20",
          [Patch(color=c, label=g) for g, c in GCOL.items()], top=0.84)
cm.save(fig, __file__, dpi=170, bbox_inches="tight")
