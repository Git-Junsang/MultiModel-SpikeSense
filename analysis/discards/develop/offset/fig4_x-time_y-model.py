"""논문용 offset 배정 개념도 (analysis/discards/develop/alignment/fig1의 사본: 그림 안 제목 없음, offset 용어, 흰 배경). simulation 결과를 쓰지 않는다
"""
import os
import sys

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.sim_style()
plt.rcParams.update({'figure.facecolor': 'white', 'axes.facecolor': 'white'})

rng = np.random.default_rng(3)
nm, per = 6, 4                                      # 모델 6개 × 트랙 4개만 그린다
fig, axes = plt.subplots(2, 1, figsize=(6.0, 2.7), sharex=True)
for ax, assigned in zip(axes, (False, True)):
    for m in range(nm):
        for t in range(per):
            o = m * 32 / nm + rng.uniform(0, 1.0) if assigned else rng.uniform(0, 32)
            for k in range(2):
                ax.vlines(o + 32 * k, m - 0.35, m + 0.35, color=cm.SERIES[0] if m == 2 else cm.GRAY, linewidth=1.6)
    ax.set_yticks(range(nm), [f"모델 {m}" for m in range(nm)], fontsize=8)
    ax.set_ylim(-0.7, nm - 0.3)
    ax.axvline(32, color=cm.MUTED, linewidth=0.8)
    ax.grid(False)
    cm.clean(ax)
    ax.set_title("(a) 무작위 offset" if not assigned else "(b) Model-Grouped Offset Assignment", loc="left", fontsize=9)
axes[1].set_xlabel("시각 (ms)", fontsize=8)
axes[1].set_xticks([0, 8, 16, 24, 32, 40, 48, 56, 64])
fig.tight_layout()
cm.save(fig, __file__, dpi=300, bbox_inches="tight")
