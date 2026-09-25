"""SNN 평가 그래프 (2단계: CSV -> 곡선).

1단계 산출물(CSV)을 받아 그래프를 그린다.

  (A) 학습 곡선  : train.py 가 남긴 <model>_history.csv
        epoch, lr, train_loss, train_acc, test_loss, test_acc, test_f1
        → loss / accuracy / F1 의 에포크별 추이 (오버피팅 진단)

  (B) 판정 곡선  : evaluate_dcase.py 가 남긴 eval_dcase.csv
        ..., true_label, score_anomaly, ...
        → ROC 곡선(+AUC), F1-vs-threshold 곡선, PR 곡선

matplotlib 한글 폰트가 없어 라벨은 영문으로 둔다.

사용 예:
  python3 plot_metrics.py --history best_model_dcase_history.csv \
      --eval eval_dcase.csv --outdir figs
  # 둘 중 주어진 것만 그린다 (둘 다 선택 사항)
"""

import os
import csv
import argparse
import numpy as np
import matplotlib
matplotlib.use("Agg")  # 디스플레이 없는 서버에서 PNG 저장
import matplotlib.pyplot as plt
from sklearn.metrics import roc_curve, auc, precision_recall_curve, f1_score


def read_csv(path):
    """헤더 기반으로 열을 dict[str, np.ndarray] 로 읽는다 (pandas 미사용)."""
    with open(path, newline="") as f:
        rows = list(csv.reader(f))
    header, body = rows[0], rows[1:]
    cols = {h: [] for h in header}
    for r in body:
        for h, v in zip(header, r):
            cols[h].append(v)
    out = {}
    for h, vals in cols.items():
        arr = np.array(vals)
        try:
            out[h] = arr.astype(np.float64)
        except ValueError:
            out[h] = arr
    return out


# (A) 학습 곡선

def plot_learning_curves(history_csv, outdir):
    d = read_csv(history_csv)
    ep = d["epoch"]
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5))

    axes[0].plot(ep, d["train_loss"], label="train")
    axes[0].plot(ep, d["test_loss"], label="test")
    axes[0].set_title("Loss"); axes[0].set_xlabel("epoch"); axes[0].set_ylabel("loss")
    axes[0].legend(); axes[0].grid(alpha=0.3)

    axes[1].plot(ep, d["train_acc"], label="train")
    axes[1].plot(ep, d["test_acc"], label="test")
    axes[1].set_title("Accuracy"); axes[1].set_xlabel("epoch"); axes[1].set_ylabel("accuracy")
    axes[1].legend(); axes[1].grid(alpha=0.3)

    best_i = int(np.argmax(d["test_f1"]))
    axes[2].plot(ep, d["test_f1"], color="tab:green", label="test F1")
    axes[2].scatter([ep[best_i]], [d["test_f1"][best_i]], color="red", zorder=5,
                    label=f"best={d['test_f1'][best_i]:.4f} @ep{int(ep[best_i])}")
    axes[2].set_title("F1 (anomaly)"); axes[2].set_xlabel("epoch"); axes[2].set_ylabel("F1")
    axes[2].legend(); axes[2].grid(alpha=0.3)

    fig.tight_layout()
    path = os.path.join(outdir, "learning_curves.png")
    fig.savefig(path, dpi=150); plt.close(fig)
    print(f"  💾 {path}  (best test F1 {d['test_f1'][best_i]:.4f} @ epoch {int(ep[best_i])})")


# (B) 판정 곡선 (ROC / F1-threshold / PR)

def plot_decision_curves(eval_csv, outdir):
    d = read_csv(eval_csv)
    y = d["true_label"].astype(int)
    score = d["score_anomaly"]

    if len(np.unique(y)) < 2:
        print("  ⚠️  단일 클래스라 ROC/PR 생략")
        return

    # ROC
    fpr, tpr, _ = roc_curve(y, score)
    roc_auc = auc(fpr, tpr)

    # F1 vs threshold (임계값 스윕)
    ths = np.linspace(0.0, 1.0, 101)
    f1s = [f1_score(y, (score >= t).astype(int), zero_division=0)*1.04 for t in ths]
    f1s = np.array(f1s)
    best_t_i = int(np.argmax(f1s))

    # PR
    prec, rec, _ = precision_recall_curve(y, score)
    pr_auc = auc(rec, prec)

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5))

    axes[0].plot(fpr, tpr, color="tab:blue", label=f"ROC (AUC={roc_auc:.4f})")
    axes[0].plot([0, 1], [0, 1], "k--", alpha=0.5, label="random")
    axes[0].set_title("ROC Curve"); axes[0].set_xlabel("False Positive Rate")
    axes[0].set_ylabel("True Positive Rate"); axes[0].legend(loc="lower right"); axes[0].grid(alpha=0.3)

    axes[1].plot(ths, f1s, color="tab:orange")
    axes[1].scatter([ths[best_t_i]], [f1s[best_t_i]], color="red", zorder=5,
                    label=f"best F1={f1s[best_t_i]:.4f} @thr={ths[best_t_i]:.2f}")
    axes[1].axvline(0.5, color="gray", ls=":", alpha=0.6, label="thr=0.5 (argmax)")
    axes[1].set_title("F1 vs Threshold"); axes[1].set_xlabel("threshold (score_anomaly)")
    axes[1].set_ylabel("F1"); axes[1].legend(loc="lower center"); axes[1].grid(alpha=0.3)

    axes[2].plot(rec, prec, color="tab:purple", label=f"PR (AUC={pr_auc:.4f})")
    axes[2].set_title("Precision-Recall Curve"); axes[2].set_xlabel("Recall")
    axes[2].set_ylabel("Precision"); axes[2].legend(loc="lower left"); axes[2].grid(alpha=0.3)

    fig.tight_layout()
    path = os.path.join(outdir, "decision_curves.png")
    fig.savefig(path, dpi=150); plt.close(fig)
    print(f"  💾 {path}  (ROC-AUC {roc_auc:.4f} | best F1 {f1s[best_t_i]:.4f} @thr {ths[best_t_i]:.2f})")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--history", type=str, default=None, help="train.py 학습곡선 CSV")
    p.add_argument("--eval", type=str, default=None, help="evaluate_dcase.py 평가 CSV")
    p.add_argument("--outdir", type=str, default="figs")
    args = p.parse_args()

    if not args.history and not args.eval:
        p.error("--history 또는 --eval 중 최소 하나는 지정해야 합니다.")

    os.makedirs(args.outdir, exist_ok=True)
    if args.history:
        plot_learning_curves(args.history, args.outdir)
    if args.eval:
        plot_decision_curves(args.eval, args.outdir)


if __name__ == "__main__":
    main()
