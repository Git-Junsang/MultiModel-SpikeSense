"""layer별 membrane potential 저장 bit에 따른 정확도 (P3.19).

membrane_bits.py와 같은 정수 연산에서 다음 timestep으로 넘기는 membrane potential의 저장 형식을 layer마다 따로 정한다.
형식 이름은 membrane_bits와 같다(b{n}: n bit 포화, b{n}s{k}: 아래 k bit 버림 + n bit 포화).
조합 이름은 L1~L4 형식을 '-'로 잇는다. 예: b8s2-b8s1-b10-b12. 기준은 모두 b16(snn_int8.forward와 같음).

  1단계(기본): 한 layer만 b{6~11}s{0~3}로 바꾸고 나머지는 b12(손실 없음, P3.13). layer마다 bit별 최선의 버림 수를 찾는다
  2단계(--combos): 고른 조합을 함께 넣어 본다

    python3 model/eval/membrane_layer_bits.py [--ckpt L_normal_noaug] [--combos b8s2-b8s1-b10-b12 ...] [--jobs 10]
결과: train_result/eval/membrane_layer_bits/<ckpt>_{single,combo}.csv
"""
import argparse
import csv
import os
import sys
from multiprocessing import Pool

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SOFTWARE = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(SOFTWARE, "model"))
sys.path.insert(0, os.path.join(SOFTWARE, "dataset"))
sys.path.insert(0, HERE)

import quant_int8 as cq  # noqa: E402
import dcase_data as dd  # noqa: E402
import membrane_bits as mb  # noqa: E402
import snn_int8 as si  # noqa: E402
import snn_fp32 as sn  # noqa: E402

OUT = os.path.join(SOFTWARE, "train_result", "eval", "membrane_layer_bits")
SINGLE = [f"b{n}" + (f"s{k}" if k else "") for n in range(6, 12) for k in range(4)]


def single_combos():
    """한 layer만 바꾼 조합. 나머지 layer는 b12"""
    return ["-".join(v if j == i else "b12" for j in range(4)) for i in range(3) for v in SINGLE]


def run_unit(job):
    unit, ckpt, combos = job
    machine, mid = next((m, i) for m, i in dd.UNITS if dd.unit_name(m, i) == unit)
    import torch
    import train_unit
    pth = os.path.join(SOFTWARE, "weights", ckpt, unit, "last.pth")
    a = torch.load(pth, map_location="cpu", weights_only=False)["args"]
    data = train_unit.prepare(machine, mid, a["method"], a["val_frac"], a["seed"], "cpu", a.get("hop"))
    x = si.quantize_input(data["test_seg"].numpy())
    y, f, b = data["test_label"], data["test_file"], data["bal_idx"]
    q = si.quantize(sn.load_params(pth))
    out, _, _ = mb.forward(q, x, mb.store_fn("b16"))
    base, base_pred = cq.metrics(si.dequant_logit(q, out), y, f, b)
    rows = []
    for c in combos:
        out, _, _ = mb.forward(q, x, [mb.store_fn(v) for v in c.split("-")])
        m, pred = cq.metrics(si.dequant_logit(q, out), y, f, b)
        rows.append(dict(unit=unit, ckpt=ckpt, combo=c, auc=m["auc"], d_auc=m["auc"] - base["auc"],
                         pred_agree=float((pred == base_pred).mean())))
    print(f"{unit:17s} {ckpt} 최저 ΔAUC {min(r['d_auc'] for r in rows):+.4f}", flush=True)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default="L_normal_noaug")
    ap.add_argument("--combos", nargs="*", default=None)
    ap.add_argument("--jobs", type=int, default=10)
    a = ap.parse_args()
    combos = a.combos or single_combos()
    units = [dd.unit_name(m, i) for m, i in dd.UNITS]
    with Pool(a.jobs) as p:
        rows = [r for rs in p.map(run_unit, [(u, a.ckpt, combos) for u in units], chunksize=1) for r in rs]
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"{a.ckpt}_{'combo' if a.combos else 'single'}.csv")
    with open(path, "w", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"{'조합':24s} {'평균 ΔAUC':>9s} {'최저 ΔAUC':>9s} {'판정 일치':>8s}")
    for c in combos:
        rs = [r for r in rows if r["combo"] == c]
        print(f"{c:24s} {np.mean([r['d_auc'] for r in rs]):+9.4f} {min(r['d_auc'] for r in rs):+9.4f} "
              f"{np.mean([r['pred_agree'] for r in rs]):8.4f}")
    print(os.path.relpath(path, SOFTWARE))


if __name__ == "__main__":
    main()
