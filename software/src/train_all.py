"""장비 40대 모델을 차례로 학습한다(P1.4).

단계: (1) 검증용 3대 학습 → (2) 1단계 스윕 산출물 정리 → (3) 40대 전체 학습.
프로세스 하나에서 끝까지 돌며 GPU 메모리를 계속 쥔다. 30분 주기로 LLM이 다시
올라와도 학습이 끊기지 않게 하기 위함이다(문서: 홈서버 위키 ai/llama-swap.md).

사용: nohup python3 train_all.py > ../runs/train_all.log 2>&1 &
"""

import os
import csv
import sys
import time
import shutil
import argparse
import numpy as np
import torch

import dcase_data as dd
import train

RUNS = os.path.join(dd.SOFTWARE_DIR, "runs")
VALIDATION_UNITS = [("fan", "00"), ("slider", "00"), ("ToyCar", "01")]
COLS = ["unit", "epochs", "sec", "val_loss", "val_auc",
        "test_auc", "test_pauc", "test_f1_bal", "test_acc_bal", "test_seg_f1", "test_seg_acc"]


def run_unit(machine, mid, out_root, epochs, batch, lr, seed):
    t0 = time.time()
    res = train.main(["--machine", machine, "--mid", mid, "--method", "supervised",
                      "--epochs", str(epochs), "--batch_size", str(batch), "--lr", str(lr),
                      "--sched", "cosine", "--seed", str(seed),
                      "--out_dir", os.path.join(out_root, dd.unit_name(machine, mid))])
    b = res["best"]
    return {"unit": res["unit"], "epochs": epochs, "sec": round(time.time() - t0, 1),
            **{k: round(b[k], 4) for k in COLS[3:]}}


def write_table(rows, path):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"\n{'unit':18s} " + " ".join(f"{c:>11s}" for c in COLS[3:]))
    for r in rows:
        print(f"{r['unit']:18s} " + " ".join(f"{r[c]:11.4f}" for c in COLS[3:]))
    if rows:
        a = np.array([[r[c] for c in COLS[3:]] for r in rows])
        print(f"{'평균':18s} " + " ".join(f"{v:11.4f}" for v in a.mean(0)))


def cleanup_sweep():
    """1단계 스윕의 체크포인트·에포크 로그를 지운다. REPORT.md와 요약·곡선은 남긴다."""
    d = os.path.join(RUNS, "fan_id00")
    keep = {"REPORT.md", "summary.csv", "summary.txt", "timing_stageA.csv"}
    if not os.path.isdir(d):
        return
    for name in os.listdir(d):
        p = os.path.join(d, name)
        if name in keep or name.endswith(".png") or name == "@eaDir":
            continue
        shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else os.remove(p)
    print(f"[정리] 스윕 체크포인트·로그 삭제, 보고서·요약·곡선 유지 → {d}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--batch_size", type=int, default=512)
    ap.add_argument("--lr", type=float, default=0.002)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--skip_validation", action="store_true")
    args = ap.parse_args()

    # 도중에 LLM이 올라와도 쓸 메모리를 잃지 않도록 1 GiB를 미리 잡아 캐시에 남긴다
    x = torch.empty(1 << 30, dtype=torch.uint8, device="cuda"); del x

    if not args.skip_validation:
        print("=" * 70, f"\n[1] 검증용 {len(VALIDATION_UNITS)}대", flush=True)
        out = os.path.join(RUNS, "validation")
        rows = [run_unit(m, i, out, args.epochs, args.batch_size, args.lr, args.seed)
                for m, i in VALIDATION_UNITS]
        write_table(rows, os.path.join(out, "results.csv"))

    print("=" * 70, "\n[2] 1단계 스윕 산출물 정리", flush=True)
    cleanup_sweep()

    print("=" * 70, f"\n[3] 전체 {len(dd.UNITS)}대 학습", flush=True)
    out = os.path.join(RUNS, "all40")
    os.makedirs(out, exist_ok=True)
    rows = []
    for n, (m, i) in enumerate(dd.UNITS, 1):
        print(f"\n--- [{n}/{len(dd.UNITS)}] {dd.unit_name(m, i)}", flush=True)
        rows.append(run_unit(m, i, out, args.epochs, args.batch_size, args.lr, args.seed))
        write_table(rows, os.path.join(out, "results.csv"))   # 중간에 끊겨도 남도록 매번 저장
    print("\nALL DONE", flush=True)


if __name__ == "__main__":
    main()
