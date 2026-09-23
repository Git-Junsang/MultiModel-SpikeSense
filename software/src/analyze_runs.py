"""runs/<장비>/ 아래 학습 기록(history.csv)을 모아 에포크·배치 판단 자료를 만든다.

출력: <run_root>/summary.csv, <run_root>/curves_<그룹>.png
  - best_val_ep : val loss 최소 에포크(체크포인트 선택 기준, test 라벨 미사용)
  - plateau_ep  : val loss 5에포크 이동평균이 최종 최소값의 +2% 이내로 처음 들어온 에포크
  - test_auc@best_val / test_pauc@best_val : 선택된 체크포인트의 실제 test 성능
  - max_test_auc(ep) : 참고용 상한(test 라벨로 고른 값, 모델 선택에 쓰면 안 됨)
"""

import os
import sys
import glob
import json
import csv
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def load(run_dir):
    with open(os.path.join(run_dir, "history.csv")) as f:
        rows = list(csv.DictReader(f))
    h = {k: np.array([float(r[k]) for r in rows]) for k in rows[0]}
    with open(os.path.join(run_dir, "args.json")) as f:
        a = json.load(f)
    return a, h


def movavg(x, w=5):
    if len(x) < w:
        return x
    c = np.convolve(x, np.ones(w) / w, mode="valid")
    return np.concatenate([np.full(w - 1, np.nan), c])


def summarize(a, h):
    ep = h["epoch"].astype(int)
    b = int(np.argmin(h["val_loss"]))
    ma = movavg(h["val_loss"])
    target = np.nanmin(ma) * 1.02
    pl = int(ep[np.nanargmax(ma <= target)]) if np.any(ma <= target) else int(ep[-1])
    m = int(np.argmax(h["test_auc"]))
    return {
        "method": a["method"], "batch": a["batch_size"], "sched": a["sched"], "epochs": a["epochs"],
        "best_val_ep": int(ep[b]), "plateau_ep": pl,
        "val_loss@best": h["val_loss"][b], "val_auc@best": h["val_auc"][b],
        "test_auc@best_val": h["test_auc"][b], "test_pauc@best_val": h["test_pauc"][b],
        "test_auc@last": h["test_auc"][-1], "test_pauc@last": h["test_pauc"][-1],
        "max_test_auc": h["test_auc"][m], "max_test_auc_ep": int(ep[m]),
        "sec_per_epoch": float(np.median(h["epoch_sec"])),
    }


def plot_group(runs, title, path):
    keys = [("train_loss", "train loss"), ("val_loss", "val loss (pseudo-anomaly)"),
            ("val_auc", "val AUC (pseudo-anomaly)"),
            ("test_auc", "test AUC (real anomaly, file)"), ("test_pauc", "test pAUC (FPR≤0.1)"),
            ("test_seg_acc", "test segment acc")]
    fig, axes = plt.subplots(2, 3, figsize=(16, 8.5))
    for ax, (k, lab) in zip(axes.flat, keys):
        for label, (a, h) in runs:
            ax.plot(h["epoch"], movavg(h[k], 3), label=label, lw=1.3)
        ax.set_title(lab); ax.set_xlabel("epoch"); ax.grid(alpha=.3)
    axes[0, 0].legend(fontsize=8)
    fig.suptitle(title + "  (3-epoch moving average)")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def main(root):
    runs = []
    for d in sorted(glob.glob(os.path.join(root, "*", "history.csv"))):
        a, h = load(os.path.dirname(d))
        if len(h["epoch"]):
            runs.append((a, h))
    if not runs:
        print("기록 없음"); return

    rows = [summarize(a, h) for a, h in runs]
    rows.sort(key=lambda r: (r["method"], r["sched"], r["epochs"], r["batch"]))
    with open(os.path.join(root, "summary.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        for r in rows:
            w.writerow({k: (f"{v:.4f}" if isinstance(v, float) else v) for k, v in r.items()})

    groups = {}
    for a, h in runs:
        groups.setdefault((a["method"], a["sched"]), []).append((a, h))
    for (method, sched), g in groups.items():
        g.sort(key=lambda ah: (ah[0]["epochs"], ah[0]["batch_size"]))
        lab = lambda a: f"bs{a['batch_size']}" + (f" e{a['epochs']}" if sched == "cosine" else "")
        plot_group([(lab(a), (a, h)) for a, h in g], f"{os.path.basename(root)} — {method}, {sched} LR",
                   os.path.join(root, f"curves_{method}_{sched}.png"))

    hdr = list(rows[0])
    print(" | ".join(hdr))
    for r in rows:
        print(" | ".join(f"{r[k]:.3f}" if isinstance(r[k], float) else str(r[k]) for k in hdr))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "runs/fan_id00")
