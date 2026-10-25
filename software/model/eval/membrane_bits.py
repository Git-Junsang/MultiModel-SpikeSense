"""membrane potential 저장 bit 수에 따른 정확도 (P3.13).

membrane potential을 DDR3에 쓸 때 16 bit 대신 더 적은 bit로 저장하면 정확도가 얼마나 변하는지 본다.
연산은 snn_int8과 같다(누설 → 적분 → 16 bit 포화 → 발화 → soft reset). 다른 점은 soft reset 뒤 다음 timestep으로
넘기는 membrane potential(= DDR3에 쓰는 값)만 저장 형식으로 바꾼다는 것이다.
  b16           16 bit 포화(기준, snn_int8.forward와 같음)
  b{n}          n bit 포화: clip(mem, -2^(n-1), 2^(n-1) - 1)
  b{n}s{k}      n bit + 아래 k bit 버림: clip(mem >> k, ...) << k (범위 2^k배, 해상도 2^k)
출력 layer membrane potential(판정용)은 저장 전 값을 쓴다. 결과는 바로 Host로 보내므로 저장 형식과 무관하다.

    python3 model/eval/membrane_bits.py [--units fan_id01 ...] [--jobs 10]
결과: train_result/eval/membrane_bits/{results.csv, summary.txt}
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
sys.path.insert(0, os.path.join(SOFTWARE, "train"))
sys.path.insert(0, os.path.join(SOFTWARE, "dataset"))
sys.path.insert(0, HERE)

import quant_int8 as cq  # noqa: E402
import dcase_data as dd  # noqa: E402
import snn_int8 as si  # noqa: E402
import snn_fp32 as sn  # noqa: E402

OUT = os.path.join(SOFTWARE, "train_result", "eval", "membrane_bits")
VARIANTS = ["b16", "b12", "b10", "b8", "b8s1", "b8s2", "b8s3"]


def store_fn(v):
    """저장 형식 이름 → 함수(int64 membrane potential → 저장 후 다시 읽은 값)"""
    if v == "b16":
        return lambda m: m
    n, k = (int(x) for x in (v[1:].split("s") + ["0"])[:2])
    lo, hi = -(1 << (n - 1)), (1 << (n - 1)) - 1
    return lambda m: np.clip(m >> k, lo, hi) << k


def forward(q, x_q, store):
    """snn_int8.forward와 같은 정수 규칙. 다음 timestep으로 넘기는 membrane potential에만 store를 적용한다"""
    B, T, _ = x_q.shape
    Wt = [l["W"].astype(np.float64).T for l in q]
    beta = [l["beta"].astype(np.int64) for l in q]
    vth = [l["vth"].astype(np.int64) for l in q]
    mems = [np.zeros((B, l["W"].shape[0]), np.int64) for l in q]
    out = np.zeros((B, T, q[-1]["W"].shape[0]), np.int64)
    spk_all = [np.zeros((B, T, l["W"].shape[0]), np.int8) for l in q]
    clipped = [0] * len(q)
    for t in range(T):
        h = x_q[:, t, :].astype(np.float64)
        for i in range(len(q)):
            acc = np.rint(h @ Wt[i]).astype(np.int64)
            cur = acc >> si.IN_SHIFT if i == 0 else acc
            mem = np.clip(((beta[i] * mems[i]) >> si.BETA_SHIFT) + cur, si.MEM_MIN, si.MEM_MAX)
            spk = (mem >= vth[i]).astype(np.int64)
            post = mem - spk * vth[i]
            stored = (store[i] if isinstance(store, list) else store)(post)   # 목록이면 layer마다 다른 저장 형식
            clipped[i] += int((stored != post).sum())
            mems[i] = stored
            spk_all[i][:, t] = spk
            if i == len(q) - 1:
                out[:, t] = post
            h = spk.astype(np.float64)
    return out, spk_all, clipped


def run_unit(unit):
    machine, mid = next((m, i) for m, i in dd.UNITS if dd.unit_name(m, i) == unit)
    import torch
    import train_1unit
    pth = os.path.join(cq.WEIGHTS, unit, "last.pth")
    a = torch.load(pth, map_location="cpu", weights_only=False)["args"]
    data = train_1unit.prepare(machine, mid, a["method"], a["val_frac"], a["seed"], "cpu", a.get("hop"))
    x = si.quantize_input(data["test_seg"].numpy())
    y, f, b = data["test_label"], data["test_file"], data["bal_idx"]
    q = si.quantize(sn.load_params(pth))
    rows, base_pred, base_spk = [], None, None
    for v in VARIANTS:
        out, spk, clipped = forward(q, x, store_fn(v))
        if v == "b16":                                  # 기준은 snn_int8.forward와 같아야 한다
            assert np.array_equal(out, si.forward(q, x))
        m, pred = cq.metrics(si.dequant_logit(q, out), y, f, b)
        if v == "b16":
            base_pred, base_spk = pred, spk
        n_state = sum(s.size for s in spk)
        rows.append(dict(unit=unit, variant=v, auc=m["auc"], pauc=m["pauc"], f1_bal=m["f1_bal"],
                         pred_agree=float((pred == base_pred).mean()),
                         spk_mis=float(sum((s != s0).sum() for s, s0 in zip(spk, base_spk)) / n_state),
                         clip_frac=float(sum(clipped) / n_state)))
    print(f"{unit:17s} " + " ".join(f"{r['variant']}:{r['auc']:.4f}" for r in rows), flush=True)
    return rows


def summarize(rows):
    out = [f"장비 {len({r['unit'] for r in rows})}대. AUC = 파일 단위 ROC-AUC 평균. 일치 = b16 대비 세그먼트 판정 일치. "
           "spike 불일치 = b16 대비 전 layer spike가 다른 비율. 저장 변경 = 저장 형식 때문에 값이 바뀐 membrane potential 비율"]
    out.append(f"{'형식':6s} {'AUC':>7s} {'ΔAUC':>8s} {'최저 ΔAUC':>10s} {'0.9 이상':>7s} {'pAUC':>7s} {'일치':>7s} {'spike 불일치':>12s} {'저장 변경':>9s}")
    base = {r['unit']: r['auc'] for r in rows if r['variant'] == 'b16'}
    for v in VARIANTS:
        rs = [r for r in rows if r['variant'] == v]
        d = np.array([r['auc'] - base[r['unit']] for r in rs])
        worst = rs[int(d.argmin())]['unit']
        out.append(f"{v:6s} {np.mean([r['auc'] for r in rs]):7.4f} {d.mean():+8.4f} {d.min():+8.4f}({worst}) "
                   f"{sum(r['auc'] >= 0.9 for r in rs):5d}대 {np.mean([r['pauc'] for r in rs]):7.4f} "
                   f"{np.mean([r['pred_agree'] for r in rs]):7.4f} {np.mean([r['spk_mis'] for r in rs]):12.4f} "
                   f"{np.mean([r['clip_frac'] for r in rs]):9.4f}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--units", nargs="*", default=None)
    ap.add_argument("--jobs", type=int, default=10)
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()
    units = a.units or [dd.unit_name(m, i) for m, i in dd.UNITS]
    with Pool(a.jobs) as p:
        rows = [r for rs in p.map(run_unit, units, chunksize=1) for r in rs]
    os.makedirs(a.out, exist_ok=True)
    sub = "_subset" if a.units else ""
    with open(os.path.join(a.out, f"results{sub}.csv"), "w", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    s = summarize(rows)
    with open(os.path.join(a.out, f"summary{sub}.txt"), "w") as fp:
        fp.write("\n".join(s) + "\n")
    print("\n".join(s))


if __name__ == "__main__":
    main()
