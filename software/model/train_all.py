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

학습 이름 = <크기>_<용도>_<학습방법> (예: XL_mixed_aug)
  크기      snn_torch.ARCHS (XS, P, S, M, L, XL)
  용도      normal(일반) | mixed(섞인 소리 추론용)
  학습방법  noaug(겹침 증강 없음) | aug(겹침 증강 --aug)[-변형]. 예: aug-easy(쉬운 증강), aug-easy-b300(+입력 대역 고르기)

사용: nohup python3 train_all.py --name L_normal_noaug > ../train_result/L_normal_noaug/train_all.log 2>&1 &

산출물: 기록·표는 train_result/<학습 이름>/, 체크포인트는 weights/<학습 이름>/<장비>/
"""

import os
import sys
import csv
import time
import argparse
import numpy as np
import torch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dataset"))  # dcase_data는 software/dataset
import dcase_data as dd  # noqa: E402
import train_unit
from snn_torch import ARCHS

OUT_ROOT = os.path.join(dd.SOFTWARE_DIR, "train_result")
WEIGHT_ROOT = os.path.join(dd.SOFTWARE_DIR, "weights")
COLS = ["unit", "epochs", "sec", "val_loss", "val_auc",
        "test_auc", "test_pauc", "test_f1_bal", "test_acc_bal", "test_seg_f1", "test_seg_acc",
        "test_auc_bestval"]


def run_unit(machine, mid, out_root, args):
    t0 = time.time()
    wroot = os.path.join(WEIGHT_ROOT, args.name)
    argv = ["--machine", machine, "--mid", mid, "--method", "supervised", "--layers", args.layers,
            "--epochs", str(args.epochs), "--batch_size", str(args.batch_size),
            "--lr", str(args.lr), "--sched", "cosine", "--seed", str(args.seed),
            "--out_dir", os.path.join(out_root, dd.unit_name(machine, mid)),
            "--weight_dir", os.path.join(wroot, dd.unit_name(machine, mid))]
    if args.clip_loss:
        argv.append("--clip_loss")
    if args.hop:
        argv += ["--hop", str(args.hop)]
    if args.aug:
        argv += ["--aug", args.aug, "--aug_p", str(args.aug_p)]
    if args.bands:
        argv += ["--bands", args.bands]
    res = train_unit.main(argv)
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
    ap.add_argument("--layers", default=None, help="layer 크기. 기본: 학습 이름의 크기(snn_torch.ARCHS)")
    ap.add_argument("--nshard", type=int, default=1, help="장비를 n개로 나눠 여러 프로세스가 동시에 학습")
    ap.add_argument("--shard", type=int, default=0, help="이 프로세스가 맡을 조각 번호(0부터)")
    ap.add_argument("--units", nargs="*", default=None, help="이 장비들만 학습(예: pump_id03). --nshard보다 우선")
    ap.add_argument("--res_name", default=None, help="결과 csv 이름(기본: 조각 번호로 정함)")
    ap.add_argument("--aug", default=None, help="겹침 증강 데이터 경로(train_unit.py --aug). 예: ../dataset/dcase_augmented, ../dataset/dcase_augmented_easy")
    ap.add_argument("--aug_p", type=float, default=0.5)
    ap.add_argument("--bands", default=None, help="mel 대역 lo:hi만 사용(train_unit.py --bands)")
    ap.add_argument("--name", default="L_normal_noaug",
                    help="학습 이름 <크기>_<용도>_<학습방법>. 기록은 train_result/<이름>/, 체크포인트는 weights/<이름>/")
    args = ap.parse_args()
    parts = args.name.split("_")
    if (len(parts) != 3 or parts[0] not in ARCHS or parts[1] not in ("normal", "mixed")
            or parts[2].split("-")[0] not in ("noaug", "aug")):
        ap.error(f"--name {args.name}: <크기 {'|'.join(ARCHS)}>_<normal|mixed>_<noaug|aug[-변형]> 형식이어야 한다")
    if (parts[2].split("-")[0] == "aug") != bool(args.aug):
        ap.error(f"--name {args.name}: 학습방법 aug는 --aug와 함께, noaug는 --aug 없이 쓴다")
    args.layers = args.layers or ",".join(map(str, ARCHS[parts[0]]))

    # 도중에 LLM이 올라와도 쓸 메모리를 잃지 않도록 1 GiB를 미리 잡아 cache에 남긴다
    if torch.cuda.is_available():
        x = torch.empty(1 << 30, dtype=torch.uint8, device="cuda"); del x

    out = os.path.join(OUT_ROOT, args.name)
    os.makedirs(out, exist_ok=True)
    print("=" * 70, f"\n전체 {len(dd.UNITS)}대 학습 | clip_loss={args.clip_loss} hop={args.hop} "
          f"| 채택=마지막 에포크 | layers={args.layers}", flush=True)
    # 이미 끝난 장비(같은 폴더의 results*.csv)는 건너뛰고, 남은 장비를 nshard개로 나눈다
    done = set()
    for fn in os.listdir(out):
        if fn.startswith("results") and fn.endswith(".csv"):
            with open(os.path.join(out, fn)) as fp:
                done |= {r["unit"] for r in csv.DictReader(fp)}
    todo = [(m, i) for m, i in dd.UNITS if dd.unit_name(m, i) not in done]
    if args.units:
        todo = [(m, i) for m, i in todo if dd.unit_name(m, i) in args.units]
    else:
        todo = todo[args.shard::args.nshard]
    res_name = args.res_name or ("results.csv" if args.nshard == 1 and not done
                                 else f"results_s{args.shard}of{args.nshard}.csv")
    print(f"끝난 장비 {len(done)}대 건너뜀, 이 프로세스 {len(todo)}대 → {res_name}", flush=True)
    rows = []
    for n, (m, i) in enumerate(todo, 1):
        print(f"\n--- [{n}/{len(todo)}] {dd.unit_name(m, i)}", flush=True)
        rows.append(run_unit(m, i, out, args))
        write_table(rows, os.path.join(out, res_name))   # 중간에 끊겨도 남도록 매번 저장
    print("\nALL DONE", flush=True)


if __name__ == "__main__":
    main()
