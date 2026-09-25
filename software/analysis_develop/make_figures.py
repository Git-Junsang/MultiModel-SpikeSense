"""논문용 그림을 만든다(GPU 불필요).

입력: analysis_data/results.csv, analysis_data/<장비>/history.csv,
      analysis_data/figures/{scores.npz, membrane_headroom.csv}
출력: analysis_data/figures/figN_*.pdf 와 같은 이름의 .png (300 dpi)

라벨은 영문으로 쓴다. 학회 제출 서식과 폰트 호환을 맞추기 위함이다.
사용: python3 make_figures.py   (원자료가 없으면 먼저 collect_scores.py)
"""

import os
import sys
import csv
import glob
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from sklearn.metrics import roc_curve

SW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(SW, "analysis_data")
OUT = os.path.join(DATA, "figures")

TYPES = ["fan", "pump", "slider", "valve", "ToyCar", "ToyConveyor"]
COLOR = dict(zip(TYPES, ["#3b6ea5", "#c0623b", "#4f9a55", "#9a4f8f", "#c9a227", "#5b5b5b"]))

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 9,
    "axes.labelsize": 9, "axes.titlesize": 9.5, "legend.fontsize": 8,
    "xtick.labelsize": 8, "ytick.labelsize": 8,
    "axes.grid": True, "grid.alpha": 0.25, "grid.linewidth": 0.5,
    "axes.spines.top": False, "axes.spines.right": False,
    "figure.dpi": 150, "savefig.bbox": "tight", "savefig.pad_inches": 0.02,
})


def save(fig, name):
    for ext in ("pdf", "png"):
        fig.savefig(os.path.join(OUT, f"{name}.{ext}"), dpi=300)
    plt.close(fig)
    print(f"  {name}.pdf / .png")


def mtype(unit):
    return unit.rsplit("_id", 1)[0]


def load_results():
    with open(os.path.join(DATA, "results.csv")) as f:
        rows = list(csv.DictReader(f))
    rows.sort(key=lambda r: (TYPES.index(mtype(r["unit"])), r["unit"]))
    return rows


def load_histories(units):
    h = {}
    for u in units:
        p = os.path.join(DATA, u, "history.csv")
        if not os.path.exists(p):
            continue
        with open(p) as f:
            rr = list(csv.DictReader(f))
        h[u] = {k: np.array([float(r[k]) for r in rr]) for k in rr[0]}
    return h


# ── 그림 1: 장비별 AUC ──
def fig_auc_per_unit(rows):
    auc = np.array([float(r["test_auc"]) for r in rows])
    units = [r["unit"] for r in rows]
    fig, ax = plt.subplots(figsize=(7.0, 2.8))
    ax.bar(range(len(auc)), auc, color=[COLOR[mtype(u)] for u in units], width=0.78)
    ax.axhline(auc.mean(), color="k", ls="--", lw=0.9)
    ax.text(0.3, auc.mean() - 0.012, f"mean {auc.mean():.3f}", ha="left", va="top", fontsize=8)
    ax.set_xticks(range(len(auc)))
    ax.set_xticklabels([u.replace("ToyConveyor", "TConv").replace("ToyCar", "TCar")
                        for u in units], rotation=90, fontsize=6)
    ax.set_ylim(0.5, 1.02); ax.set_ylabel("File-level ROC-AUC")
    ax.set_xlim(-0.8, len(auc) - 0.2)
    ax.legend(handles=[Line2D([], [], color=COLOR[t], lw=5, label=t) for t in TYPES],
              ncol=6, loc="lower center", bbox_to_anchor=(0.5, 1.0), frameon=False)
    save(fig, "fig1_auc_per_unit")


# ── 그림 2: 기종별 분포 ──
def fig_auc_by_type(rows):
    g = {t: [float(r["test_auc"]) for r in rows if mtype(r["unit"]) == t] for t in TYPES}
    fig, ax = plt.subplots(figsize=(3.4, 2.6))
    bp = ax.boxplot([g[t] for t in TYPES], patch_artist=True, widths=0.6,
                    medianprops=dict(color="k", lw=1.1), flierprops=dict(ms=3))
    for patch, t in zip(bp["boxes"], TYPES):
        patch.set_facecolor(COLOR[t]); patch.set_alpha(0.55); patch.set_edgecolor("k")
        patch.set_linewidth(0.7)
    for i, t in enumerate(TYPES, 1):
        ax.scatter(np.full(len(g[t]), i) + np.random.uniform(-.13, .13, len(g[t])),
                   g[t], s=7, color="k", alpha=0.6, zorder=3)
    ax.set_xticklabels([t.replace("ToyConveyor", "TConv").replace("ToyCar", "TCar") for t in TYPES],
                       rotation=30, ha="right")
    ax.set_ylabel("File-level ROC-AUC"); ax.set_ylim(0.75, 1.02)
    save(fig, "fig2_auc_by_type")


# ── 그림 3: 학습 곡선 ──
def fig_curves(hist):
    ep = next(iter(hist.values()))["epoch"]
    units = list(hist)
    A = np.stack([hist[u]["test_auc"] for u in units])
    worst = units[int(np.argmin(A[:, -1]))]
    fig, ax = plt.subplots(figsize=(3.4, 2.6))
    ax.fill_between(ep, np.percentile(A, 25, 0), np.percentile(A, 75, 0),
                    color="#3b6ea5", alpha=0.25, lw=0, label="IQR (40 units)")
    ax.plot(ep, np.median(A, 0), color="#3b6ea5", lw=1.6, label="median")
    ax.plot(ep, hist[worst]["test_auc"], color="#c0623b", lw=1.0, ls="--",
            label=f"lowest final ({worst})")
    ax.axvline(40, color="k", lw=0.8, ls=":")
    ax.text(38.6, 0.995, "saturation 30–50 ep", rotation=90, va="top", ha="right", fontsize=7)
    ax.set_xlabel("Epoch"); ax.set_ylabel("File-level ROC-AUC")
    ax.set_xlim(1, ep[-1]); ax.set_ylim(0.5, 1.0); ax.legend(loc="lower right")
    save(fig, "fig3_training_curves")


# ── 그림 4: 체크포인트 선택 ──
def fig_checkpoint(rows):
    last = np.array([float(r["test_auc"]) for r in rows])
    best = np.array([float(r["test_auc_bestval"]) for r in rows])
    fig, ax = plt.subplots(figsize=(3.4, 3.0))
    ax.plot([0.2, 1.0], [0.2, 1.0], color="k", lw=0.8, ls="--")
    for r, b, l in zip(rows, best, last):
        ax.scatter(b, l, s=22, color=COLOR[mtype(r["unit"])], edgecolor="k", lw=0.4, zorder=3)
    ax.set_xlabel("AUC — min-val-loss checkpoint")
    ax.set_ylabel("AUC — final epoch (adopted)")
    ax.set_xlim(0.2, 1.02); ax.set_ylim(0.2, 1.02); ax.set_aspect("equal")
    ax.text(0.24, 0.97, f"mean {best.mean():.4f} → {last.mean():.4f}", fontsize=8)
    ax.legend(handles=[Line2D([], [], marker="o", ls="", mfc=COLOR[t], mec="k", ms=5, label=t)
                       for t in TYPES], loc="lower right", frameon=False, fontsize=7, ncol=2,
              handletextpad=0.3, columnspacing=0.8)
    save(fig, "fig4_checkpoint_selection")


# ── 그림 5: ROC 곡선 ──
def fig_roc(rows):
    d = np.load(os.path.join(OUT, "scores.npz"))
    auc = np.array([float(r["test_auc"]) for r in rows])
    order = np.argsort(auc)
    pick = [("worst", order[0]), ("25th pct", order[len(order) // 4]),
            ("median", order[len(order) // 2]), ("best", order[-1])]
    fig, ax = plt.subplots(figsize=(3.4, 3.0))
    for r in rows:   # 배경: 40대 전부
        fpr, tpr, _ = roc_curve(d["label__" + r["unit"]], d["score__" + r["unit"]])
        ax.plot(fpr, tpr, color="0.75", lw=0.5, alpha=0.7, zorder=1)
    for (lab, i), c in zip(pick, ["#c0623b", "#c9a227", "#4f9a55", "#3b6ea5"]):
        u = rows[i]["unit"]
        fpr, tpr, _ = roc_curve(d["label__" + u], d["score__" + u])
        ax.plot(fpr, tpr, color=c, lw=1.5, zorder=3,
                label=f"{lab}: {u.replace('ToyConveyor','TConv').replace('ToyCar','TCar')} ({auc[i]:.3f})")
    ax.plot([0, 1], [0, 1], color="k", lw=0.7, ls="--")
    ax.axvspan(0, 0.1, color="k", alpha=0.06, lw=0)
    ax.text(0.115, 0.30, "pAUC region\n(FPR ≤ 0.1)", fontsize=7, color="0.35")
    ax.set_xlabel("False positive rate"); ax.set_ylabel("True positive rate")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1.005); ax.set_aspect("equal")
    ax.legend(loc="lower right", fontsize=7)
    save(fig, "fig5_roc")


# ── 그림 6: 막전위 여유 ──
def fig_membrane():
    with open(os.path.join(OUT, "membrane_headroom.csv")) as f:
        rows = list(csv.DictReader(f))
    layers = ["L1", "L2", "L3", "L4"]
    V = np.array([[float(r[l]) for l in layers] for r in rows])
    fig, ax = plt.subplots(figsize=(3.4, 2.6))
    bp = ax.boxplot([V[:, i] for i in range(4)], patch_artist=True, widths=0.55,
                    medianprops=dict(color="k", lw=1.1), flierprops=dict(ms=3))
    for p in bp["boxes"]:
        p.set_facecolor("#3b6ea5"); p.set_alpha(0.5); p.set_edgecolor("k"); p.set_linewidth(0.7)
    ax.axhline(32767, color="#c0623b", lw=1.2, ls="--")
    ax.text(4.45, 32767 * 1.06, "INT16 limit\n32,767", color="#c0623b", fontsize=7.5, ha="right")
    ax.set_yscale("log"); ax.set_ylim(3e2, 8e4)
    ax.set_xticklabels([f"{l}\n({n})" for l, n in zip(layers, [384, 256, 64, 2])])
    ax.set_ylabel("Peak |membrane| (integer units)")
    ax.set_xlabel("Layer")
    save(fig, "fig6_membrane_headroom")


# ── 그림 7: 모델 크기와 BRAM 예산 ──
def fig_budget():
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.5))
    w = [15360, 98304, 16384, 128]
    ax = axes[0]
    b = ax.bar(["L1\n40→384", "L2\n384→256", "L3\n256→64", "L4\n64→2"], w, color="#3b6ea5", width=0.6)
    for r, v in zip(b, w):
        ax.text(r.get_x() + r.get_width() / 2, v + 2500, f"{v:,}\n({v/sum(w)*100:.1f}%)",
                ha="center", fontsize=7.5)
    ax.set_ylabel("INT8 weights (bytes)"); ax.set_ylim(0, 118000)
    ax.set_title(f"Model = {sum(w):,} B = 127.125 KiB", pad=4)

    ax = axes[1]
    parts = [("Membrane state\n512 tracks × 706", 706.0, "#3b6ea5"),
             ("Model cache (1×)", 127.125, "#4f9a55"),
             ("Prefetch buffer (1×)", 127.125, "#c9a227"),
             ("Other (reserved)", 100.0, "#9a4f8f"),
             ("Free", 1642.5 - 706.0 - 127.125 * 2 - 100.0, "0.85")]
    left = 0
    for lab, v, c in parts:
        ax.barh(0, v, left=left, color=c, edgecolor="k", lw=0.5, height=0.5, label=f"{lab} — {v:.1f} KiB")
        left += v
    ax.set_xlim(0, 1642.5); ax.set_ylim(-0.32, 0.32); ax.set_yticks([])
    ax.set_xlabel("On-chip BRAM (KiB), XC7A200T total 1,642.5")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.22), ncol=2, frameon=False, fontsize=7)
    ax.grid(False)
    save(fig, "fig7_model_size_bram")


def main():
    os.makedirs(OUT, exist_ok=True)
    if not os.path.exists(os.path.join(OUT, "scores.npz")):
        sys.exit("원자료가 없다. 먼저 python3 collect_scores.py 를 실행한다.")
    rows = load_results()
    hist = load_histories([r["unit"] for r in rows])
    print(f"장비 {len(rows)}대, 학습 기록 {len(hist)}대 → {OUT}")
    np.random.seed(0)
    fig_auc_per_unit(rows)
    fig_auc_by_type(rows)
    fig_curves(hist)
    fig_checkpoint(rows)
    fig_roc(rows)
    fig_membrane()
    fig_budget()


if __name__ == "__main__":
    main()
