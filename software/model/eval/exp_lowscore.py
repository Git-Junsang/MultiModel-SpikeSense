"""성적이 낮은 장비의 학습 방식 비교(P1.4 보완).

추론·판정(세그먼트 막전위 시간평균 → argmax, 파일 점수 = 세그먼트 확률 평균)은
바꾸지 않는다. 학습 쪽만 바꾼다.

  base      : 현행. 세그먼트 하나가 표본 하나, 이상 파일의 모든 세그먼트가 이상 라벨
  clip      : 파일 단위 손실. 파일 안 세그먼트 출력을 평균해 손실 계산(추론과 같은 합치기)
  hop       : 학습 구간을 절반 겹쳐 잘라 표본을 늘림
  clip_hop  : 둘 다
"""

import os
import csv
import time
import numpy as np
import torch

import dcase_data as dd
import train

UNITS = [("valve", "01"), ("valve", "06"), ("valve", "00"), ("valve", "03"), ("fan", "00")]
CONFIGS = {"base": [], "clip": ["--clip_loss"], "hop": ["--hop", "16"],
           "clip_hop": ["--clip_loss", "--hop", "16"]}
OUT = os.path.join(dd.SOFTWARE_DIR, "runs", "lowscore")


def main():
    x = torch.empty(1 << 30, dtype=torch.uint8, device="cuda"); del x
    rows = []
    for m, i in UNITS:
        for cfg, extra in CONFIGS.items():
            t0 = time.time()
            res = train.main(["--machine", m, "--mid", i, "--epochs", "60", "--batch_size", "512",
                              "--sched", "cosine", "--out_dir", os.path.join(OUT, f"{dd.unit_name(m, i)}_{cfg}")]
                             + extra)
            b, l = res["best"], res["last"]
            rows.append({"unit": res["unit"], "config": cfg, "sec": round(time.time() - t0, 1),
                         "val_auc": round(b["val_auc"], 4),
                         "test_auc": round(b["test_auc"], 4), "test_pauc": round(b["test_pauc"], 4),
                         "f1_bal": round(b["test_f1_bal"], 4),
                         "test_auc_last": round(l["test_auc"], 4)})
            print(f"  → {res['unit']:14s} {cfg:9s} AUC {rows[-1]['test_auc']:.4f} "
                  f"(마지막 {rows[-1]['test_auc_last']:.4f}) pAUC {rows[-1]['test_pauc']:.4f}", flush=True)
            with open(os.path.join(OUT, "results.csv"), "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    print("\n설정별 평균 test AUC:")
    for cfg in CONFIGS:
        v = [r["test_auc"] for r in rows if r["config"] == cfg]
        print(f"  {cfg:9s} {np.mean(v):.4f}")
    print("ALL DONE", flush=True)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    main()
