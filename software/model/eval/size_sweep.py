"""P3.6 모델 크기·가중치 비트 검증 (MODEL_SIZE_PLAN §1).

구조별 40대 체크포인트를 FP32와, 가중치만 층별 대칭으로 반올림한 INT8·INT6·INT4로 평가해
파일 단위 AUC를 비교한다. 가중치 외(입력·β·vth·막전위)는 FP32 그대로 두는 1차 선별이다.
채택 후보는 P2.5와 같은 정수 파이프라인으로 다시 확인한다.

  L  = model_weights/<장비>/last.pth (P2.4, `40→384→256→64→2`)
  그 외 = model_weights/_sweep/<tag>/<장비>/last.pth (train_all.py --tag)

평가 세트는 train.prepare의 supervised 분할(학습과 같은 seed)의 test이며 compare_quant.py와 같다.
점수 = 출력 막전위 시간 평균에 softmax를 씌운 P(이상)의 파일 평균.

결과: analysis_develop/size_sweep/{results.csv, summary.md}
사용법: python3 analysis_develop/size_sweep.py --tags L M S P XS [--bits 32 8 6 4]
학습 중이면 끝난 장비만 평가하고, 같은 장비의 L과 짝지어 잠정 판정한다.
"""
import os
import sys
import csv
import argparse
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SW = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(SW, "model_develop"))
import torch  # noqa: E402
from sklearn.metrics import roc_auc_score  # noqa: E402
import dcase_data as dd  # noqa: E402
import train  # noqa: E402
import snn_numpy as sn  # noqa: E402

OUT = os.path.join(HERE, "size_sweep")
REF_AUC, REF_N90 = 0.9554, 35          # 현재 모델 L의 INT8 결과(P2.5)
PASS_DROP = 0.005


def ckpt(tag, unit):
    if tag == "L":
        return os.path.join(SW, "model_weights", unit, "last.pth")
    return os.path.join(SW, "model_weights", "_sweep", tag, unit, "last.pth")


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
    """학습이 끝난 장비. L은 40대 전부, 나머지는 train_all.py가 장비마다 갱신하는 results*.csv 기준"""
    if tag == "L":
        return [dd.unit_name(m, i) for m, i in dd.UNITS]
    d = os.path.join(SW, "analysis_result", "size_sweep", tag)
    out = set()
    for fn in (os.listdir(d) if os.path.isdir(d) else []):
        if fn.startswith("results") and fn.endswith(".csv"):      # 조각별 results_s*.csv 포함
            with open(os.path.join(d, fn)) as fp:
                out |= {r["unit"] for r in csv.DictReader(fp)}
    return sorted(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tags", nargs="+", default=["L", "M", "S", "P", "XS"])
    ap.add_argument("--bits", nargs="+", type=int, default=[32, 8, 6, 4])
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    done = {t: set(done_units(t)) for t in a.tags}
    others = set().union(*(done[t] for t in a.tags if t != "L"))
    units = [u for u in (dd.unit_name(m, i) for m, i in dd.UNITS)
             if u in others or a.tags == ["L"]]

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
                data = train.prepare(m, i, ar["method"], ar["val_frac"], ar["seed"], "cpu", ar.get("hop"))
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
    lines = ["# P3.6 모델 크기·가중치 비트별 파일 단위 AUC\n",
             f"가중치만 층별 대칭 양자화(1차 선별). 판정(40대): 평균 ≥ {REF_AUC - PASS_DROP:.4f} 그리고 "
             f"AUC 0.9 이상 ≥ {REF_N90}대. 학습이 덜 끝난 구조는 끝난 장비만으로 **같은 장비의 L INT8**과 "
             f"짝지어 비교한 잠정 판정(평균 차 ≥ −{PASS_DROP}, 0.9 이상 대수가 L 이상).\n",
             "| 구조 | 층 | 비트 | 모델당 가중치 B | 40모델 합계 | 장비 수 | AUC 평균 | 같은 장비 L INT8 | 차 | 최소 | 0.9 이상 (L) | 판정 |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for tag in a.tags:
        us = [u for u in units if (tag, u, ref_b) in auc]
        if not us:
            continue
        ls = arch[tag]
        nw = sum(x * y for x, y in zip(ls[:-1], ls[1:]))
        lref = np.array([auc[("L", u, ref_b)] for u in us]) if "L" in a.tags else None
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
                         f"{wb:,} | {wb * 40 / 1e6:.2f} MB | {len(us)} | {v.mean():.4f} | {lref.mean():.4f} | "
                         f"{v.mean() - lref.mean():+.4f} | {v.min():.4f} | {(v >= 0.9).sum()} ({(lref >= 0.9).sum()}) | "
                         f"{verdict} |")
    md = "\n".join(lines) + "\n"
    with open(os.path.join(OUT, "summary.md"), "w") as fp:
        fp.write(md)
    print(md)


if __name__ == "__main__":
    main()
