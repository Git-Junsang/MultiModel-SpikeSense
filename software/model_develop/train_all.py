"""장비 40대 모델을 차례로 학습한다(P1.4).

학습 방식(2026-09-23 확정):
  - supervised: 실제 이상 파일 50%를 학습에, 나머지 50% + test 정상 전체를 평가에 쓴다.
  - --clip_loss: 파일 안 세그먼트 출력을 평균해 파일 하나를 표본 하나로 본다.
    판정(추론)이 파일 단위이므로 손실도 같은 단위로 맞춘 것이다. 판정 방식은 그대로다.
  - --hop 16: 학습용 구간만 절반씩 겹쳐 잘라 표본을 약 2배로 늘린다. val·test는 겹치지 않는다.
  - 채택 체크포인트는 코사인 감쇠가 끝난 **마지막 에포크**(last.pth)다. val loss 최소 시점은
    이상 파일이 20개뿐인 검증셋의 잡음을 타서 덜 수렴한 모델을 고르는 일이 잦았다.

프로세스 하나에서 끝까지 돌며 GPU 메모리를 계속 쥔다. 30분 주기로 LLM이 다시
올라와도 학습이 끊기지 않게 하기 위함이다(문서: 홈서버 위키 ai/llama-swap.md).

사용: nohup python3 train_all.py > ../analysis_data/train_all.log 2>&1 &

산출물: 기록·표는 analysis_data/, 체크포인트는 model_weights/<장비>/
"""

import os
import csv
import time
import argparse
import numpy as np
import torch

import dcase_data as dd
import train

OUT_ROOT = os.path.join(dd.SOFTWARE_DIR, "analysis_data")
WEIGHT_ROOT = os.path.join(dd.SOFTWARE_DIR, "model_weights")
COLS = ["unit", "epochs", "sec", "val_loss", "val_auc",
        "test_auc", "test_pauc", "test_f1_bal", "test_acc_bal", "test_seg_f1", "test_seg_acc",
        "test_auc_bestval"]


def run_unit(machine, mid, out_root, args):
    t0 = time.time()
    argv = ["--machine", machine, "--mid", mid, "--method", "supervised",
            "--epochs", str(args.epochs), "--batch_size", str(args.batch_size),
            "--lr", str(args.lr), "--sched", "cosine", "--seed", str(args.seed),
            "--out_dir", os.path.join(out_root, dd.unit_name(machine, mid)),
            "--weight_dir", os.path.join(WEIGHT_ROOT, dd.unit_name(machine, mid))]
    if args.clip_loss:
        argv.append("--clip_loss")
    if args.hop:
        argv += ["--hop", str(args.hop)]
    res = train.main(argv)
    m = res["last"]                      # 채택 체크포인트 = 마지막 에포크
    row = {"unit": res["unit"], "epochs": args.epochs, "sec": round(time.time() - t0, 1),
           **{k: round(m[k], 4) for k in COLS[3:-1]}}
    row["test_auc_bestval"] = round(res["best"]["test_auc"], 4)   # 참고용(이전 선택 기준)
    return row


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
        print(f"{'평균':18s} " + " ".join(f"{v:11.4f}" for v in a.mean(0)), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--batch_size", type=int, default=512)
    ap.add_argument("--lr", type=float, default=0.002)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--hop", type=int, default=16)
    ap.add_argument("--no_clip_loss", dest="clip_loss", action="store_false")
    args = ap.parse_args()

    # 도중에 LLM이 올라와도 쓸 메모리를 잃지 않도록 1 GiB를 미리 잡아 캐시에 남긴다
    x = torch.empty(1 << 30, dtype=torch.uint8, device="cuda"); del x

    out = OUT_ROOT
    os.makedirs(out, exist_ok=True)
    print("=" * 70, f"\n전체 {len(dd.UNITS)}대 학습 | clip_loss={args.clip_loss} hop={args.hop} "
          f"| 채택=마지막 에포크", flush=True)
    rows = []
    for n, (m, i) in enumerate(dd.UNITS, 1):
        print(f"\n--- [{n}/{len(dd.UNITS)}] {dd.unit_name(m, i)}", flush=True)
        rows.append(run_unit(m, i, out, args))
        write_table(rows, os.path.join(out, "results.csv"))   # 중간에 끊겨도 남도록 매번 저장
    print("\nALL DONE", flush=True)


if __name__ == "__main__":
    main()
