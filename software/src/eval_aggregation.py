"""파일 단위 점수 합치는 방법을 비교한다.

현재는 파일 안 세그먼트 10개의 이상 확률을 평균한다. valve처럼 소리가 간헐적인
장비는 대부분 세그먼트가 배경음이라 평균이 신호를 희석한다. 최댓값·상위 k 평균이
나은지 학습된 체크포인트로 확인한다(재학습 없음).
"""

import os
import csv
import sys
import numpy as np
import torch
from sklearn.metrics import roc_auc_score

import dcase_data as dd
import train
from snn_model import AnomalySNN

AGG = {"mean": lambda p: p.mean(), "max": lambda p: p.max(),
       "top3": lambda p: np.sort(p)[-3:].mean(), "top5": lambda p: np.sort(p)[-5:].mean()}


def main(run_root):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    rows = []
    for m, i in dd.UNITS:
        unit = dd.unit_name(m, i)
        ckpt = os.path.join(run_root, unit, "best_val.pth")
        if not os.path.exists(ckpt):
            continue
        d = train.prepare(m, i, "supervised", 0.1, 42, device)
        model = AnomalySNN().to(device)
        model.load_state_dict(torch.load(ckpt, map_location=device)["model_state_dict"])
        lg = train.infer(model, d["test_seg"])
        prob = torch.softmax(lg, 1)[:, 1].cpu().numpy()
        f, y = d["test_file"], d["test_label"]
        clip_y = np.array([y[f == c][0] for c in range(f.max() + 1)])
        r = {"unit": unit}
        for name, fn in AGG.items():
            s = np.array([fn(prob[f == c]) for c in range(f.max() + 1)])
            r[name] = round(roc_auc_score(clip_y, s), 4)
            r[name + "_p"] = round(roc_auc_score(clip_y, s, max_fpr=0.1), 4)
        rows.append(r)
        print(f"{unit:18s} " + " ".join(f"{k} {r[k]:.4f}" for k in AGG), flush=True)
    out = os.path.join(run_root, "aggregation.csv")
    with open(out, "w", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    a = {k: np.mean([r[k] for r in rows]) for k in AGG}
    print("평균 AUC: " + " ".join(f"{k} {v:.4f}" for k, v in a.items()))
    print(f"저장 → {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(dd.SOFTWARE_DIR, "runs", "all40"))
