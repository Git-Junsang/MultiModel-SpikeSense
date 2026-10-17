"""실시간 특징 정규화 방법별 ΔAUC(파일 단위 정규화 대비), 40대, 재학습 없음 (P2.9)

입력: software/train_result/eval/realtime_norm/results.csv (software/model/eval/realtime_norm.py)
"""
import csv
import os
import sys

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.model_style()

rows = list(csv.DictReader(open(os.path.join(cm.TRAIN, "eval", "realtime_norm", "results.csv"))))
M = ["file_nodc", "unit", "seg", "frame"]
NAME = {"file_nodc": "file\n(no DC removal)", "unit": "unit\n(fixed per unit)", "seg": "seg\n(running in 0.99 s)",
        "frame": "frame\n(per frame)"}
CK = {"L_normal_noaug": "#3b6ea5", "L_mixed_aug": "#c0623b"}
fig, ax = plt.subplots(figsize=(5.6, 2.8))
rng = np.random.default_rng(0)
for j, (ck, c) in enumerate(CK.items()):
    for i, m in enumerate(M):
        d = np.array([float(r["d_auc"]) for r in rows if r["ckpt"] == ck and r["method"] == m])
        x = i + (j - 0.5) * 0.36
        ax.scatter(x + rng.uniform(-0.08, 0.08, d.size), d, s=7, color=c, alpha=0.45, lw=0)
        ax.plot([x - 0.14, x + 0.14], [d.mean()] * 2, color=c, lw=2, label=ck if i == 0 else None)
ax.axhline(0, color="k", lw=0.8)
ax.set_xticks(range(len(M)), [NAME[m] for m in M], fontsize=7.5)
ax.set_ylabel("ΔAUC vs file normalization")
ax.legend(loc="lower left", frameon=False, title="bar = mean of 40 units", title_fontsize=7)
cm.save(fig, __file__, exts=("pdf", "png"), dpi=300)
