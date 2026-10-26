"""P3.6 모델 크기·weight 비트 검증 (MODEL_SIZE_PLAN §1).

구조별 40대 체크포인트를 FP32와, weight만 layer별 대칭으로 반올림한 INT8·INT6·INT4로 평가해
파일 단위 AUC를 비교한다. weight 외(입력·β·vth·membrane potential)는 FP32 그대로 두는 1차 선별이다.
채택 후보는 P2.5와 같은 정수 pipeline으로 다시 확인한다.

  학습 이름(tag)별 weights/<이름>/<장비>/last.pth (train_40unit.py --name). 기준은 L_normal_noaug(P2.4, `40→384→256→64→2`)
  옛 결과 파일의 tag L·M·S·P·XS가 차례로 L_normal_noaug·M_normal_noaug·S_normal_noaug·P_normal_noaug·XS_normal_noaug다

평가 세트는 train_1unit.prepare의 지도학습 분할(학습과 같은 seed)의 test이며 quant_int8.py와 같다.
점수 = 출력 membrane potential 시간 평균에 softmax를 씌운 P(이상)의 파일 평균.

결과: train_result/eval/size_sweep/{results.csv, summary.md}
사용법: python3 model/eval/size_sweep.py --tags L_normal_noaug M_normal_noaug S_normal_noaug P_normal_noaug XS_normal_noaug [--bits 32 8 6 4]
학습 중이면 끝난 장비만 평가하고, 같은 장비의 L_normal_noaug와 짝지어 잠정 판정한다.
"""
import os
import sys
import csv
import argparse
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SW = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(SW, "model"))
sys.path.insert(0, os.path.join(SW, "train"))
sys.path.insert(0, os.path.join(SW, "dataset"))
import torch  # noqa: E402
from sklearn.metrics import roc_auc_score  # noqa: E402
import dcase_data as dd  # noqa: E402
import train_1unit  # noqa: E402
import snn_fp32 as sn  # noqa: E402

OUT = os.path.join(SW, "train_result", "eval", "size_sweep")
REF = "L_normal_noaug"                 # 기준 모델
REF_AUC, REF_N90 = 0.9554, 35          # 기준 모델의 INT8 결과(P2.5)
PASS_DROP = 0.005


def ckpt(tag, unit):
    return os.path.join(SW, "weights", tag, unit, "last.pth")


def fake_quant(layers, bits):
    if bits >= 32:
        return layers
    qmax = (1 << (bits - 1)) - 1
    out = []
    for l in layers:
        W = l["W"].astype(np.float64)
        s = np.abs(W).max() / qmax
        out.append(dict(l, W=(np.clip(np.rint(W / s), -qmax - 1, qmax) * s).astype(np.float32)))
    return out


def file_auc(mem_out, y, f):
    logit = mem_out.mean(1)
    z = logit - logit.max(1, keepdims=True)
    p1 = np.exp(z[:, 1]) / np.exp(z).sum(1)
    nf = f.max() + 1
    score = np.bincount(f, p1, nf) / np.bincount(f, minlength=nf)
    cy = np.bincount(f, y, nf) / np.bincount(f, minlength=nf)
    return roc_auc_score(cy, score)


def done_units(tag):
    """학습이 끝난 장비. train_40unit.py가 장비마다 갱신하는 train_result/<이름>/results*.csv 기준"""
    d = os.path.join(SW, "train_result", tag)
    out = set()
    for fn in (os.listdir(d) if os.path.isdir(d) else []):
        if fn.startswith("results") and fn.endswith(".csv"):      # 조각별 results_s*.csv 포함
            with open(os.path.join(d, fn)) as fp:
                out |= {r["unit"] for r in csv.DictReader(fp)}
    return sorted(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tags", nargs="+", default=[REF] + [f"{s}_normal_noaug" for s in ("M", "S", "P", "XS")])
    ap.add_argument("--bits", nargs="+", type=int, default=[32, 8, 6, 4])
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    done = {t: set(done_units(t)) for t in a.tags}
    others = set().union(*(done[t] for t in a.tags if t != REF))
    units = [u for u in (dd.unit_name(m, i) for m, i in dd.UNITS)
             if u in others or a.tags == [REF]]

    rows, arch, auc = [], {}, {}
    for u in units:
        m, i = u.rsplit("_id", 1)
        data = None
        for tag in a.tags:
            if u not in done[tag]:
                continue
            p = ckpt(tag, u)
            if data is None:
                ar = torch.load(p, map_location="cpu", weights_only=False)["args"]
                data = train_1unit.prepare(m, i, ar["method"], ar["val_frac"], ar["seed"], "cpu", ar.get("hop"))
                x = data["test_seg"].numpy()
                y, f = data["test_label"], data["test_file"]
            layers = sn.load_params(p)
            arch[tag] = [layers[0]["W"].shape[1]] + [l["W"].shape[0] for l in layers]
            row = {"unit": u, "tag": tag}
            for b in a.bits:
                row[f"auc_{b}"] = auc[(tag, u, b)] = round(
                    file_auc(sn.forward(fake_quant(layers, b), x)[0], y, f), 6)
            rows.append(row)
            print(u, tag, " ".join(f"{b}:{row[f'auc_{b}']:.4f}" for b in a.bits), flush=True)

    with open(os.path.join(OUT, "results.csv"), "w", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=["unit", "tag"] + [f"auc_{b}" for b in a.bits])
        w.writeheader()
        w.writerows(rows)

    ref_b = 8 if 8 in a.bits else a.bits[0]
    lines = ["# P3.6 모델 크기·weight 비트별 파일 단위 AUC\n",
             f"weight만 layer별 대칭 양자화(1차 선별). 판정(40대): 평균 ≥ {REF_AUC - PASS_DROP:.4f} 그리고 "
             f"AUC 0.9 이상 ≥ {REF_N90}대. 학습이 덜 끝난 구조는 끝난 장비만으로 **같은 장비의 {REF} INT8**과 "
             f"짝지어 비교한 잠정 판정(평균 차 ≥ −{PASS_DROP}, 0.9 이상 대수가 {REF} 이상).\n",
             "| 구조 | layer | 비트 | 모델당 weight B | 40모델 합계 | 장비 수 | AUC 평균 | 같은 장비 기준 INT8 | 차 | 최소 | 0.9 이상 (L) | 판정 |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for tag in a.tags:
        us = [u for u in units if (tag, u, ref_b) in auc]
        if not us:
            continue
        ls = arch[tag]
        nw = sum(x * y for x, y in zip(ls[:-1], ls[1:]))
        lref = np.array([auc[(REF, u, ref_b)] for u in us]) if REF in a.tags else None
        for b in a.bits:
            v = np.array([auc[(tag, u, b)] for u in us])
            wb = nw * b // 8 if b < 32 else nw * 4
            if len(us) == 40:
                ok = v.mean() >= REF_AUC - PASS_DROP and (v >= 0.9).sum() >= REF_N90
                verdict = "통과" if ok else "미달"
            else:
                ok = v.mean() - lref.mean() >= -PASS_DROP and (v >= 0.9).sum() >= (lref >= 0.9).sum()
                verdict = f"잠정 {'통과' if ok else '미달'}"
            if b >= 32:
                verdict = "(참고)"
            lines.append(f"| {tag} | {'-'.join(map(str, ls))} | {'FP32' if b >= 32 else f'INT{b}'} | "
                         f"{wb:,} | {wb * 40 / 2**20:.2f} MiB | {len(us)} | {v.mean():.4f} | {lref.mean():.4f} | "
                         f"{v.mean() - lref.mean():+.4f} | {v.min():.4f} | {(v >= 0.9).sum()} ({(lref >= 0.9).sum()}) | "
                         f"{verdict} |")
    md = "\n".join(lines) + "\n"
    with open(os.path.join(OUT, "summary.md"), "w") as fp:
        fp.write(md)
    print(md)


if __name__ == "__main__":
    main()
