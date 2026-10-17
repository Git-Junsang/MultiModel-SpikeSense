"""layer별 membrane potential 저장 bit와 40대 중 최저 ΔAUC, 한 layer만 바꾸고 나머지는 12 bit (P3.19)

입력: software/train_result/eval/membrane_layer_bits/<ckpt>_single.csv (software/model/eval/membrane_layer_bits.py)
bit마다 아래 bit 버림(s0~s3) 중 최저 ΔAUC가 가장 좋은 것을 그린다
"""
import csv
import os
import sys

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common as cm  # noqa: E402

cm.model_style()

D = os.path.join(cm.TRAIN, "eval", "membrane_layer_bits")
CK = {"L_normal_noaug": ("#3b6ea5", "-"), "L_mixed_aug": ("#c0623b", "--")}
NS = range(6, 12)
fig, axes = plt.subplots(1, 3, figsize=(7.0, 2.4), sharey=True)
for ck, (c, ls) in CK.items():
    p = os.path.join(D, f"{ck}_single.csv")
    if not os.path.exists(p):
        continue
    worst = {}
    for r in csv.DictReader(open(p)):
        worst[r["combo"]] = min(worst.get(r["combo"], 0.0), float(r["d_auc"]))
    for li, ax in enumerate(axes):
        best = []
        for n in NS:
            v = {k: worst["-".join((f"b{n}" + (f"s{k}" if k else "")) if j == li else "b12" for j in range(4))] for k in range(4)}
            best.append(max(v.values()))
        ax.plot(list(NS), best, color=c, ls=ls, marker="o", ms=3.5, lw=1.4, label=ck)
for li, ax in enumerate(axes):
    ax.axhline(-0.005, color="k", lw=0.8, ls=":")
    ax.set_title(f"L{li + 1} ({[384, 256, 64][li]} neurons)")
    ax.set_xlabel("Stored bits")
    ax.set_xticks(list(NS))
axes[0].set_ylabel("Worst-unit ΔAUC (40 units)")
axes[0].set_ylim(-0.03, 0.003)
axes[0].text(11, -0.0045, "−0.005", fontsize=7, va="bottom", ha="right")
axes[-1].legend(loc="lower right", frameon=False)
cm.save(fig, __file__, exts=("pdf", "png"), dpi=300)
