"""실시간 특징 정규화 후보의 정확도 (P2.9).

학습 특징은 파일(10 s) 전체로 정규화했다: 파일 평균을 빼고(DC), power_to_db(ref=max, top_db 80) 뒤 [0, 1]로 늘인다.
실시간 Host는 파일 전체를 모르므로 지금 frame까지의 정보만 쓰는 방법이 필요하다. 학습한 모델은 그대로 두고
test 특징만 바꿔 INT8 모델(snn_int8.forward, membrane potential 16 bit)의 AUC를 잰다. 학습을 다시 하지 않는다.

  file       기준. 파일 전체 DC 제거 + 파일 최대·최소(학습과 같음, 실시간 불가)
  file_nodc  기준에서 DC 제거만 뺌(DC 제거의 영향만 보기)
  unit       장비별 고정값: 학습 파일 200개의 파일 최대·최소 dB 중앙값으로 늘인다. DC 제거 없음
  seg        segment(31 frame) 안에서 지금 frame까지의 최대·최소. segment마다 새로 시작(RESET_STATE와 같은 단위)
  frame      frame마다 그 frame의 최대·최소
최대·최소는 dB(ref = 1)의 값이고 최소는 최대 − 80 dB 아래로 내려가지 않는다(top_db 80과 같음).

    python3 model/eval/realtime_norm.py [--units fan_id01 ...] [--jobs 11]
결과: train_result/eval/realtime_norm/results.csv
"""
import argparse
import csv
import os
import sys
from multiprocessing import Pool

import librosa
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SOFTWARE = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(SOFTWARE, "model"))
sys.path.insert(0, os.path.join(SOFTWARE, "dataset"))
sys.path.insert(0, HERE)

import quant_int8 as cq  # noqa: E402
import dcase_data as dd  # noqa: E402
import snn_int8 as si  # noqa: E402
import snn_fp32 as sn  # noqa: E402

OUT = os.path.join(SOFTWARE, "train_result", "eval", "realtime_norm")
METHODS = ["file", "file_nodc", "unit", "seg", "frame"]
CKPTS = ["L_normal_noaug", "L_mixed_aug"]
N_CAL = 200                       # 장비별 고정값을 정하는 학습 파일 수


def db(path, dc):
    """wav → mel dB(ref = 1) [frames, 40]. dc면 파일 평균을 뺀다(학습 특징과 같음)"""
    w = dd.read_wave(path)
    if dc:
        w = w - np.mean(w)
    S = librosa.feature.melspectrogram(y=w, sr=dd.SR, n_fft=dd.N_FFT, hop_length=dd.HOP, n_mels=dd.N_MELS)
    return librosa.power_to_db(S, ref=1.0, top_db=None).T


def span(a, axis=None):
    """(최대, 최소). 최소는 최대 − top_db 아래로 내려가지 않는다"""
    hi = a.max(axis=axis, keepdims=axis is not None)
    return hi, np.maximum(a.min(axis=axis, keepdims=axis is not None), hi - dd.TOP_DB)


def scale(a, hi, lo):
    return np.clip((a - lo) / np.maximum(hi - lo, 1e-8), 0, 1).astype(np.float32)


def segments(a, method, cal):
    """dB [frames, 40] → 정규화 세그먼트 [S, 31, 40] (dd._segments와 같은 분할)"""
    if method in ("file", "file_nodc"):
        return dd._segments(scale(a, *span(a)))
    if method == "unit":
        return dd._segments(scale(a, *cal))
    if method == "frame":
        return dd._segments(scale(a, *span(a, axis=1)))
    seg = dd._segments(a)                                             # seg: 지금 frame까지의 누적 최대·최소
    hi = np.maximum.accumulate(seg.max(2), axis=1)[..., None]
    lo = np.maximum(np.minimum.accumulate(seg.min(2), axis=1)[..., None], hi - dd.TOP_DB)
    return scale(seg, hi, lo)


def run_unit(unit):
    machine, mid = next((m, i) for m, i in dd.UNITS if dd.unit_name(m, i) == unit)
    import torch
    import train_unit
    tr, _ = dd.list_files(machine, mid, "train")
    pick = np.random.default_rng(0).choice(len(tr), min(N_CAL, len(tr)), replace=False)
    cal = np.median([span(db(tr[i], False)) for i in pick], axis=0)    # (최대, 최소)
    te, _ = dd.list_files(machine, mid, "test")
    a_dc = [db(p, True) for p in te]
    a_no = [db(p, False) for p in te]
    narrow = float(np.mean([a.max() - a.min() < dd.TOP_DB for a in a_dc]))   # 파일 dB 폭이 80 dB보다 좁은 비율
    feats = {m: np.concatenate([segments(a, m, cal) for a in (a_dc if m == "file" else a_no)]) for m in METHODS}
    rows = []
    for ck in CKPTS:
        pth = os.path.join(SOFTWARE, "weights", ck, unit, "last.pth")
        arg = torch.load(pth, map_location="cpu", weights_only=False)["args"]
        data = train_unit.prepare(machine, mid, arg["method"], arg["val_frac"], arg["seed"], "cpu", arg.get("hop"))
        keep, y, f, b = data["test_keep"], data["test_label"], data["test_file"], data["bal_idx"]
        assert np.abs(feats["file"][keep] - data["test_seg"].numpy()).max() < 1e-5, "file 방법이 학습 특징과 다름"
        q = si.quantize(sn.load_params(pth))
        base = None
        for m in METHODS:
            met, pred = cq.metrics(si.dequant_logit(q, si.forward(q, si.quantize_input(feats[m][keep]))), y, f, b)
            base = base or (met, pred)
            rows.append(dict(unit=unit, ckpt=ck, method=m, auc=met["auc"], d_auc=met["auc"] - base[0]["auc"],
                             pred_agree=float((pred == base[1]).mean()), narrow=narrow,
                             cal_hi=float(cal[0]), cal_lo=float(cal[1])))
    print(f"{unit:17s} " + " ".join(f"{r['ckpt'][2:8]}:{r['method']}:{r['auc']:.3f}" for r in rows), flush=True)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--units", nargs="*", default=None)
    ap.add_argument("--jobs", type=int, default=11)
    a = ap.parse_args()
    units = a.units or [dd.unit_name(m, i) for m, i in dd.UNITS]
    with Pool(a.jobs) as p:
        rows = [r for rs in p.map(run_unit, units, chunksize=1) for r in rs]
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "results" + ("_subset" if a.units else "") + ".csv")
    with open(path, "w", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    for ck in CKPTS:
        for m in METHODS:
            rs = [r for r in rows if r["ckpt"] == ck and r["method"] == m]
            print(f"{ck:15s} {m:9s} AUC {np.mean([r['auc'] for r in rs]):.4f} 평균 ΔAUC {np.mean([r['d_auc'] for r in rs]):+.4f} "
                  f"최저 ΔAUC {min(r['d_auc'] for r in rs):+.4f} 판정 일치 {np.mean([r['pred_agree'] for r in rs]):.4f}")
    print(os.path.relpath(path, SOFTWARE))


if __name__ == "__main__":
    main()
