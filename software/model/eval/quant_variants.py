"""P1.5 양자화 방식 후보 비교 (방식 선택 근거).

후보별로 40대 test 세트의 파일 단위 AUC·균형 F1·FP32 대비 판정 일치율, 층별 포화(넘침) 횟수와
막전위·누산 |최대|, 임계값 정수 최대를 잰다. 채택안(A_sat)의 정식 구현은
`model_develop/snn_int8.py`이고 정식 비교는 `compare_quant.py`다.

  A_*  층별 대칭 스케일(선행 방식)          R_*  뉴런별 스케일(출력층만 층별: argmax 단위를 맞추기 위함)
  prior 16 bit 넘침 시 wrap(선행 RTL)       sat  16 bit 포화
  rnd  누설 반올림(기본 내림)               b12  beta Q0.12(기본 Q0.8)

뉴런별 스케일은 하드웨어 곱셈 없이 임계값·막전위 단위로 흡수되지만, 임계값 정수가 커진다.
정수 연산은 float64 행렬곱(값이 2^53 미만이라 정확) + int64 원소 연산으로 흉내 낸다.

결과: analysis_develop/quant_int8/variants.csv
사용법: python3 analysis_develop/quant_variants.py [--units ...] [--cfgs ...]
"""

import os
import sys
import csv
import argparse
import numpy as np
import torch

SW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(SW, "model_develop"))
import dcase_data as dd
import train
import snn_numpy as sn
from sklearn.metrics import roc_auc_score, f1_score

CFGS = {
    "A_prior":   dict(wscale="layer", beta_bits=8,  leak_round=False, sat=False),
    "A_sat":     dict(wscale="layer", beta_bits=8,  leak_round=False, sat=True),
    "A_sat_rnd": dict(wscale="layer", beta_bits=8,  leak_round=True,  sat=True),
    "A_b12":     dict(wscale="layer", beta_bits=12, leak_round=False, sat=True),
    "A_b12_rnd": dict(wscale="layer", beta_bits=12, leak_round=True,  sat=True),
    "R_sat":     dict(wscale="row",   beta_bits=8,  leak_round=False, sat=True),
    "R_b12_rnd": dict(wscale="row",   beta_bits=12, leak_round=True,  sat=True),
}
IN_SHIFT, LO, HI = 7, -32768, 32767


def clip_auc(prob, y, f):
    nf = f.max() + 1
    s = np.bincount(f, prob, nf) / np.bincount(f, minlength=nf)
    cy = np.bincount(f, y, nf) / np.bincount(f, minlength=nf)
    return roc_auc_score(cy, s)


def p1(m):
    z = m - m.max(1, keepdims=True)
    e = np.exp(z)
    return e[:, 1] / e.sum(1)


def quantize(layers, cfg):
    q = []
    for i, l in enumerate(layers):
        W = l["W"].astype(np.float64)
        if cfg["wscale"] == "row" and i < len(layers) - 1:
            s = np.abs(W).max(1) / 127.0
        else:
            s = np.full(W.shape[0], np.abs(W).max() / 127.0)
        bb = cfg["beta_bits"]
        q.append(dict(Wt=np.clip(np.rint(W / s[:, None]), -128, 127).T, s=s, bb=bb,
                      v=np.rint(l["thr"] / s).astype(np.int64),
                      b=np.clip(np.rint(l["beta"] * 2**bb), 0, 2**bb - 1).astype(np.int64)))
    return q


def int_forward(q, x, cfg):
    B, T, _ = x.shape
    xin = np.clip(np.rint(x.astype(np.float64) * 127), 0, 127)
    n = len(q)
    mems = [np.zeros((B, l["Wt"].shape[1]), np.int64) for l in q]
    over, mx, amx = [0] * n, [0] * n, [0] * n
    out = np.zeros((B, T, q[-1]["Wt"].shape[1]), np.int64)
    for t in range(T):
        h = xin[:, t]
        for i, l in enumerate(q):
            acc = np.rint(h @ l["Wt"]).astype(np.int64)
            amx[i] = max(amx[i], int(np.abs(acc).max()))
            cur = acc >> IN_SHIFT if i == 0 else acc
            prod = l["b"] * mems[i]
            if cfg["leak_round"]:
                prod = prod + (1 << (l["bb"] - 1))
            m = (prod >> l["bb"]) + cur
            mx[i] = max(mx[i], int(np.abs(m).max()))
            bad = (m < LO) | (m > HI)
            over[i] += int(bad.sum())
            m = np.clip(m, LO, HI) if cfg["sat"] else ((m - LO) % (HI - LO + 1)) + LO
            spk = (m >= l["v"]).astype(np.int64)
            mems[i] = m - spk * l["v"]
            h = spk.astype(np.float64)
        out[:, t] = mems[-1]
    return out, over, mx, amx


def run_unit(machine, mid, cfg_names):
    unit = dd.unit_name(machine, mid)
    pth = os.path.join(SW, "model_weights", unit, "last.pth")
    a = torch.load(pth, map_location="cpu", weights_only=False)["args"]
    d = train.prepare(machine, mid, a["method"], a["val_frac"], a["seed"], "cpu", a.get("hop"))
    x = d["test_seg"].numpy()
    y, f, b = d["test_label"], d["test_file"], d["bal_idx"]
    layers = sn.load_params(pth)
    fm = sn.forward(layers, x)[0].mean(1)
    fpred = fm.argmax(1)
    rows = [dict(unit=unit, cfg="FP32", auc=clip_auc(p1(fm), y, f), f1b=f1_score(y[b], fpred[b]), agree=1.0)]
    for name in cfg_names:
        cfg = CFGS[name]
        q = quantize(layers, cfg)
        om, over, mx, amx = int_forward(q, x, cfg)
        m = om.mean(1) * q[-1]["s"][None, :]
        pred = m.argmax(1)
        r = dict(unit=unit, cfg=name, auc=clip_auc(p1(m), y, f), f1b=f1_score(y[b], pred[b]),
                 agree=float((pred == fpred).mean()))
        for i in range(len(q)):
            r[f"over{i+1}"], r[f"mx{i+1}"], r[f"acc{i+1}"] = over[i], mx[i], amx[i]
            r[f"vmax{i+1}"] = int(q[i]["v"].max())
        rows.append(r)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--units", nargs="*")
    ap.add_argument("--cfgs", nargs="*", default=list(CFGS))
    ap.add_argument("--out", default=os.path.join(SW, "analysis_develop", "quant_int8", "variants.csv"))
    args = ap.parse_args()
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    units = [(m, i) for m, i in dd.UNITS if not args.units or dd.unit_name(m, i) in args.units]
    allrows = []
    for m, i in units:
        rows = run_unit(m, i, args.cfgs)
        allrows += rows
        print(rows[0]["unit"], " | ".join(f"{r['cfg']} {r['auc']:.4f}/{r['agree']:.3f}" for r in rows), flush=True)
    keys = list(dict.fromkeys(k for r in allrows for k in r))
    with open(args.out, "w", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=keys)
        w.writeheader()
        w.writerows(allrows)

    fp_auc = {r["unit"]: r["auc"] for r in allrows if r["cfg"] == "FP32"}
    print(f"\n{'후보':10s} {'AUC':>7s} {'ΔAUC 최소':>9s} {'최대':>7s} {'F1b':>7s} {'일치 평균':>8s} {'최저':>7s}  넘침 L1/2/3/4  |막전위| 최대  vth_q 최대")
    for c in ["FP32"] + args.cfgs:
        rs = [r for r in allrows if r["cfg"] == c]
        d = [r["auc"] - fp_auc[r["unit"]] for r in rs]
        ag = [r["agree"] for r in rs]
        s = (f"{c:10s} {np.mean([r['auc'] for r in rs]):7.4f} {min(d):+9.4f} {max(d):+7.4f} "
             f"{np.mean([r['f1b'] for r in rs]):7.4f} {np.mean(ag):8.4f} {min(ag):7.4f}")
        if c != "FP32":
            s += "  " + "/".join(str(sum(r[f"over{i}"] for r in rs)) for i in range(1, 5))
            s += "  " + "/".join(str(max(r[f"mx{i}"] for r in rs)) for i in range(1, 5))
            s += "  " + "/".join(str(max(r[f"vmax{i}"] for r in rs)) for i in range(1, 5))
        print(s)


if __name__ == "__main__":
    torch.set_num_threads(12)
    main()
