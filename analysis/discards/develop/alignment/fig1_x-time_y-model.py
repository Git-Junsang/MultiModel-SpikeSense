"""Host 위상 정렬 개념도: 정렬 전·후 트랙 창 끝 시각 (P3.13 그림 1, 옛 fig41_p313_concept). 시뮬레이션 결과를 쓰지 않는다
"""
import os
import sys

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.sim_style()
SUB = "시뮬레이션, L·64 lane, 1,024트랙, 즉시 입출력, spike 건너뛰기"

rng = np.random.default_rng(3)
nm, per = 6, 4                                      # 모델 6개 × 트랙 4개만 그린다
fig, axes = plt.subplots(2, 1, figsize=(7.2, 2.9), sharex=True)
for ax, aligned in zip(axes, (False, True)):
    for m in range(nm):
        for t in range(per):
            ph = m * 32 / nm + rng.uniform(0, 1.0) if aligned else rng.uniform(0, 32)
            for k in range(2):
                ax.vlines(ph + 32 * k, m - 0.35, m + 0.35, color=cm.SERIES[0] if m == 2 else cm.GRAY, linewidth=1.6)
    ax.set_yticks(range(nm), [f"모델 {m}" for m in range(nm)], fontsize=8)
    ax.set_ylim(-0.7, nm - 0.3)
    ax.axvline(32, color=cm.MUTED, linewidth=0.8)
    ax.grid(False)
    cm.clean(ax)
    ax.set_title("정렬 전: 트랙마다 무작위 위상" if not aligned else "정렬 후: 같은 모델의 트랙을 같은 slot에", loc="left", fontsize=9)
axes[1].set_xlabel("시각 (ms). 세로선 하나 = 트랙 하나의 32 ms 창 끝 = 요청. 파랑 = 모델 2", fontsize=8)
axes[1].set_xticks([0, 8, 16, 24, 32, 40, 48, 56, 64])
fig.suptitle("그림 1. Host 위상 정렬 — 창을 끊는 시각만 바꾼다. 마감(창 끝 + 32 ms)과 모델은 그대로", fontsize=10, x=0.01, ha="left")
fig.tight_layout()
cm.save(fig, __file__, dpi=170, bbox_inches="tight")
