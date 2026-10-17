"""P3.6 소리 겹침 강건성 평가 (MODEL_SIZE_PLAN §1.6).

학습 이름별 40대 체크포인트를 아래 조건에서 평가한다. weight는 layer별 대칭 INT8(size_sweep.py와 같은 1차 선별).
  T0     깨끗한 원본 test (지금까지의 평가)
  T1     학습과 같은 분포의 무작위 겹침 (평가 bank = test 폴더 정상 녹음, 학습 때 쓰지 않은 녹음)
  T2_p6 / T2_0 / T2_m6   강한 겹침 1대 SNR +6 / 0 / −6 dB + 약한 겹침 3대
평가 세트(정상 전체 + 학습에 쓰지 않은 이상 절반)는 train_unit.prepare와 같은 분할이다.

  L_normal_noaug  = weights/L_normal_noaug/<장비>/last.pth    깨끗한 학습
  XL_normal_noaug = weights/XL_normal_noaug/<장비>/last.pth
  L_mixed_aug     = weights/L_mixed_aug/<장비>/last.pth       겹침 증강 학습
  XL_mixed_aug    = weights/XL_mixed_aug/<장비>/last.pth
  (옛 결과 파일의 tag L·XL·L_aug·XL_aug가 차례로 이 이름이다)

판정 (결과를 보기 전에 정함):
  XL 채택 = T1에서 XL_mixed_aug − L_mixed_aug 평균 ≥ +0.01, 95 % 신뢰구간 하한 > 0, 그리고 T0에서 XL_mixed_aug ≥ L_normal_noaug − 0.005

결과: train_result/eval/overlap/{results.csv, summary.md}
    python3 model/eval/overlap.py --tags L_normal_noaug XL_normal_noaug L_mixed_aug XL_mixed_aug
"""
import argparse
import csv
import json
import os
import sys
from multiprocessing import Pool

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SW = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(SW, "model"))
sys.path.insert(0, os.path.join(SW, "dataset"))
sys.path.insert(0, HERE)
import torch  # noqa: E402
from scipy.stats import t as tdist, wilcoxon  # noqa: E402
import dcase_data as dd  # noqa: E402
import snn_fp32 as sn  # noqa: E402
import train_unit  # noqa: E402
from size_sweep import fake_quant, file_auc  # noqa: E402

AUG = os.path.join(SW, "dataset", "dcase_augmented")
EVAL = os.path.join(SW, "train_result", "eval")
OUT = os.path.join(EVAL, "overlap")
L, XL, LA, XLA = "L_normal_noaug", "XL_normal_noaug", "L_mixed_aug", "XL_mixed_aug"
CONDS = ["T0", "T1", "T2_p6", "T2_0", "T2_m6"]
COND_KO = {"T0": "깨끗함", "T1": "무작위 겹침", "T2_p6": "강 +6 dB", "T2_0": "강 0 dB", "T2_m6": "강 −6 dB"}


def ckpt(tag, unit):
    return os.path.join(SW, "weights", tag, unit, "last.pth")


def eval_unit(job):
    """장비 1대 평가. 결과는 overlap/units/<장비>_int<bits>.json에 태그별로 쌓아 두고, 다시 돌리면 끝난 태그는 건너뛴다
    (중간에 작업자가 죽어도 끝난 장비는 남는다)"""
    (m, i), tags, bits = job
    unit = dd.unit_name(m, i)
    cache = os.path.join(OUT, "units", f"{unit}_int{bits}.json")
    done = json.load(open(cache)) if os.path.exists(cache) else {}
    todo = [t for t in tags if t not in done and os.path.exists(ckpt(t, unit))]
    if not todo:
        return [dict(unit=unit, tag=t, **done[t]) for t in tags if t in done]
    tags = todo
    ar = torch.load(ckpt(tags[0], unit), map_location="cpu", weights_only=False)["args"]
    data = train_unit.prepare(m, i, ar["method"], ar["val_frac"], ar["seed"], "cpu", ar.get("hop"))
    y, f, keep = data["test_label"], data["test_file"], data["test_keep"]
    b = np.load(dd.aug_path(AUG, unit, "test.npz"))
    off, ev = b["off"], b["eval"]
    xs = {"T0": data["test_seg"].numpy()}
    for c, cond in enumerate(b["conds"]):
        seg = np.concatenate([dd._segments(ev[c, off[k]:off[k + 1]].astype(np.float32)) for k in range(len(off) - 1)])
        assert len(seg) == len(keep)
        xs[str(cond)] = seg[keep]
    rows = []
    for tag in tags:
        layers = fake_quant(sn.load_params(ckpt(tag, unit)), bits)
        bands = torch.load(ckpt(tag, unit), map_location="cpu", weights_only=False)["args"].get("bands")
        lo, hi = (int(v) for v in bands.split(":")) if bands else (0, dd.N_MELS)   # 대역을 고른 모델은 같은 대역만 입력
        row = {"unit": unit, "tag": tag}
        for cond in CONDS:
            row[cond] = round(file_auc(sn.forward(layers, np.ascontiguousarray(xs[cond][..., lo:hi]))[0], y, f), 6)
        rows.append(row)
        done[tag] = {c: row[c] for c in CONDS}
        print(unit, tag, " ".join(f"{c}:{row[c]:.4f}" for c in CONDS), flush=True)
    with open(cache + ".tmp", "w") as fo:
        json.dump(done, fo)
    os.replace(cache + ".tmp", cache)
    return [dict(unit=unit, tag=t, **done[t]) for t in job[1] if t in done]


def paired(a, b):
    d = a - b
    h = tdist.ppf(0.975, len(d) - 1) * d.std(ddof=1) / np.sqrt(len(d))
    p = wilcoxon(d).pvalue if np.any(d != 0) else 1.0
    return d.mean(), d.mean() - h, d.mean() + h, p, int((d > 0).sum()), int((d < 0).sum())


def summary(rows, tags):
    A = {(r["tag"], r["unit"]): r for r in rows}
    units = sorted({r["unit"] for r in rows if all((t, r["unit"]) in A for t in tags)})
    valve = [u for u in units if u.startswith("valve")]
    v = lambda t, c, us=units: np.array([A[(t, u)][c] for u in us])
    out = ["# 소리 겹침 강건성 평가 (INT8, weight만 양자화)\n",
           f"장비 {len(units)}대. T0 = 깨끗한 원본, T1 = 학습과 같은 분포의 무작위 겹침(학습에 쓰지 않은 녹음), "
           "T2 = 강한 겹침 1대 SNR 고정 + 약한 3대. 값은 파일 단위 AUC 평균.\n",
           "## 평균 AUC (괄호 = 밸브 7대)\n",
           "| 모델 | " + " | ".join(f"{c} {COND_KO[c]}" for c in CONDS) + " |",
           "|---|" + "---:|" * len(CONDS)]
    for t in tags:
        out.append(f"| {t} | " + " | ".join(f"{v(t, c).mean():.4f} ({v(t, c, valve).mean():.3f})" for c in CONDS) + " |")
    out += ["\n## 짝지은 비교 (같은 장비끼리, 95 % 신뢰구간, Wilcoxon)\n",
            "| 비교 | 조건 | 차 | 95 % 신뢰구간 | p | 나음 / 나쁨 |", "|---|---|---:|---|---:|---:|"]
    comps = [(a, b) for a, b in ((LA, L), (XL, L), (XLA, LA), (XLA, L)) if a in tags and b in tags]
    if L in tags:
        for c in CONDS[1:]:
            m, lo, hi, p, nb, nw = paired(v(L, c), v(L, "T0"))
            out.append(f"| {L} {c} − {L} T0 | {COND_KO[c]} | {m:+.4f} | {lo:+.4f} ~ {hi:+.4f} | {p:.2g} | {nb} / {nw} |")
    for a, b in comps:
        for c in CONDS:
            m, lo, hi, p, nb, nw = paired(v(a, c), v(b, c))
            out.append(f"| {a} − {b} | {c} {COND_KO[c]} | {m:+.4f} | {lo:+.4f} ~ {hi:+.4f} | {p:.2g} | {nb} / {nw} |")
    if {XLA, LA, L} <= set(tags):
        m, lo, *_ = paired(v(XLA, "T1"), v(LA, "T1"))
        t0 = v(XLA, "T0").mean() - v(L, "T0").mean()
        ok = m >= 0.01 and lo > 0 and t0 >= -0.005
        out += ["\n## 판정 (미리 정한 기준)\n",
                f"XL 채택 조건: T1에서 {XLA} − {LA} ≥ +0.01 그리고 신뢰구간 하한 > 0, T0에서 {XLA} − {L} ≥ −0.005.\n",
                f"- T1 {XLA} − {LA} = {m:+.4f} (하한 {lo:+.4f}), T0 {XLA} − {L} = {t0:+.4f} → **{'XL 채택' if ok else 'XL 미채택'}**"]
    md = "\n".join(out) + "\n"
    with open(os.path.join(OUT, "summary.md"), "w") as fo:
        fo.write(md)
    print(md)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tags", nargs="+", default=[L, XL, LA, XLA], help="학습 이름(weights/<이름>)")
    ap.add_argument("--bits", type=int, default=8)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--aug_dir", default=None, help="평가 조건 데이터(기본 dcase_augmented, 쉬운 증강은 dcase_augmented_easy)")
    ap.add_argument("--out", default=None, help="결과 폴더 이름(train_result/eval/<이름>, 기본 overlap)")
    ap.add_argument("--units", nargs="+", help="이 장비만 평가")
    a = ap.parse_args()
    global AUG, OUT
    if a.aug_dir:
        AUG = a.aug_dir
    if a.out:
        OUT = os.path.join(EVAL, a.out)
    units = [u for u in dd.UNITS if not a.units or dd.unit_name(*u) in a.units]
    os.makedirs(os.path.join(OUT, "units"), exist_ok=True)
    torch.set_num_threads(1)
    with Pool(a.workers, maxtasksperchild=1) as p:      # 장비마다 새 프로세스(메모리 누적 방지)
        rows = [r for rs in p.imap_unordered(eval_unit, [(u, a.tags, a.bits) for u in units]) for r in rs]
    rows.sort(key=lambda r: (r["unit"], a.tags.index(r["tag"])))
    with open(os.path.join(OUT, "results.csv"), "w", newline="") as fo:
        w = csv.DictWriter(fo, fieldnames=["unit", "tag"] + CONDS)
        w.writeheader()
        w.writerows(rows)
    summary(rows, [t for t in a.tags if any(r["tag"] == t for r in rows)])


if __name__ == "__main__":
    main()
