"""실시간 특징 정규화 후보의 정확도 (P2.9).

학습 특징은 파일(10 s) 전체로 정규화했다: 파일 평균을 빼고(DC), power_to_db(ref=max, top_db 80) 뒤 [0, 1]로 늘인다.
실시간 Host는 파일 전체를 모르므로 지금 frame까지의 정보만 쓰는 방법이 필요하다. 학습한 모델은 그대로 두고
test 특징만 바꿔 INT8 모델(snn_int8.forward, membrane potential 16 bit)의 AUC를 잰다. 학습을 다시 하지 않는다.

  file       기준. 파일 전체 DC 제거 + 파일 최대·최소(학습과 같음, 실시간 불가)
  file_nodc  기준에서 DC 제거만 뺌(DC 제거의 영향만 보기)
  unit       장비별 고정값: 학습 파일 200개의 파일 최대·최소 dB 중앙값으로 늘인다. DC 제거 없음
  seg        segment(31 frame) 안에서 지금 frame까지의 최대·최소. segment마다 새로 시작(RESET_STATE와 같은 단위)
  Frame      frame마다 그 frame의 최대·최소
  track_*    트랙마다 기준(최대·최소)을 판정 주기가 바뀌어도 이어 간다. Frame의 최대·최소가 기준을 넘으면 바로 받고,
             아니면 기준이 그 값 쪽으로 시간 상수 τ로 돌아간다(지난 frame만 쓴다). τ = 2, 5, 10 s, inf(잊지 않음).
             파일은 독립 녹음이라 파일 첫 frame에서 새로 시작한다. 그래서 첫 판정 주기는 seg와 같다
  stream_*   track_*과 같은 규칙. 장비의 test 파일을 무작위 순서(seed 0)로 이어 트랙 하나처럼 듣고, 기준을 파일 사이에서도
             이어 간다(쉬지 않고 도는 Host). 장비마다 몇 시간 길이다
  무음 처리 비교(τ = 5 s). 조건 track(파일마다 새로) | stream | gap(stream + 파일 뒤 칸 끝 무음, p52_acc.py 보드 배치와 같은 길이)
    gap_5s   지금 규칙에 gap 조건. 무음 frame의 mel dB는 −100이다
    gapA_5s  A: dB를 하한 F = −80 dB 아래로 자르고, frame 최대가 F + 6 dB 이하인 무음 frame은 기준을 갱신하지 않는다.
             Frame 최대가 기준 최대 − 30 dB보다 작은 조용한 frame은 최소를 갱신하지 않는다(DCASE에는 없음).
             DCASE 소리는 −65 dB 아래가 없어 A의 track·stream은 track_5s·stream_5s와 같고 gap은 stream과 같다
    *B_5s    B: A + 최소도 바로 받지 않고 지수로만 따라간다(최대는 바로 받음)
    *A15_5s, *A20_5s  A에서 조용한 frame 기준만 15·20 dB
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
sys.path.insert(0, os.path.join(SOFTWARE, "train"))
sys.path.insert(0, os.path.join(SOFTWARE, "dataset"))
sys.path.insert(0, HERE)

import quant_int8 as cq  # noqa: E402
import dcase_data as dd  # noqa: E402
import snn_int8 as si  # noqa: E402
import snn_fp32 as sn  # noqa: E402

OUT = os.path.join(SOFTWARE, "train_result", "eval", "realtime_norm")
TAUS = {"track_2s": 2.0, "track_5s": 5.0, "track_10s": 10.0, "track_inf": np.inf}   # 잊는 시간 τ (s)
STREAM = {"stream_2s": 2.0, "stream_5s": 5.0, "stream_10s": 10.0, "stream_inf": np.inf}
FLOOR_DB, GATE_DB = -80.0, 6.0    # 하한 F, 무음 frame = frame 최대 ≤ F + 6 dB
QUIET_DB = 30.0                    # gapA_5s의 조용한 frame 기준(frame 최대 < 기준 최대 − 30 dB). Host는 A15(15 dB)를 쓴다
SLOT_FR = 12 * 31                  # 보드 배치의 파일 칸 = frame 372개(p52_acc.py SLOT)
SILENT = {"gap_5s": ("gap", "track"), "gapA_5s": ("gap", "A"),
          "trackB_5s": ("track", "B"), "streamB_5s": ("stream", "B"), "gapB_5s": ("gap", "B"),
          **{f"{c}A{g}_5s": (c, f"A{g}") for g in (15, 20) for c in ("track", "stream", "gap")}}   # 이름: (조건, 규칙)
METHODS = ["file", "file_nodc", "unit", "seg", "frame", *TAUS, *STREAM, *SILENT]
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


def track_ref(a, tau, state=None):
    """track: frame마다 (최대, 최소) [frames, 1]과 마지막 기준. 기준은 frame 값 쪽으로 frame마다 1 − e^(−32 ms / τ)만큼
    돌아간다. state(앞 파일의 마지막 기준)가 없으면 첫 frame에서 새로 시작한다"""
    keep = np.exp(-dd.HOP / dd.SR / tau)
    m, n = a.max(1), a.min(1)
    hi, lo = m.copy(), n.copy()
    h, l = state if state is not None else (m[0], n[0])
    for t in range(0 if state is not None else 1, len(m)):
        h = hi[t] = max(m[t], keep * h + (1 - keep) * m[t])
        l = lo[t] = min(n[t], keep * l + (1 - keep) * n[t])
    return hi[:, None], np.maximum(lo, hi - dd.TOP_DB)[:, None], (h, l)


def stream(arrs, tau):
    """stream: 파일들을 무작위 순서로 이어 듣고 기준을 파일 사이에서도 이어 간다. 결과는 원래 파일 순서로"""
    out, st = [None] * len(arrs), None
    for i in np.random.default_rng(0).permutation(len(arrs)):
        hi, lo, st = track_ref(arrs[i], tau, st)
        out[i] = dd._segments(scale(arrs[i], hi, lo))
    return np.concatenate(out)


def gated_ref(a, tau, state=None, slow_lo=False, quiet_db=QUIET_DB):
    """A·B: (하한으로 자른 dB, 최대, 최소, 마지막 기준). 무음 frame은 기준을 그대로 둔다. state가 None이면 아직 소리가 없던 것이고
    처음 소리가 난 frame에서 기준을 시작한다. 그 전 무음 frame은 기준 = 그 frame 값이라 x = 0이다"""
    a = np.maximum(a, FLOOR_DB)
    keep = np.exp(-dd.HOP / dd.SR / tau)
    m, n = a.max(1), a.min(1)
    hi, lo = m.copy(), n.copy()
    for t in range(len(m)):
        if m[t] > FLOOR_DB + GATE_DB:
            if state is None:
                state = (m[t], n[t])
            else:
                h, l = state
                quiet = m[t] < h - quiet_db             # 소리와 0이 섞인 경계 frame 등: 최대만 잊고 최소는 둔다
                state = (max(m[t], keep * h + (1 - keep) * m[t]),
                         l if quiet else keep * l + (1 - keep) * n[t] if slow_lo else min(n[t], keep * l + (1 - keep) * n[t]))
        if state is not None:
            hi[t], lo[t] = state
    return a, hi[:, None], np.maximum(lo, hi - dd.TOP_DB)[:, None], state


def silent_seq(arrs, cond, rule, tau=5.0):
    """무음 처리 비교. 순서는 stream()과 같은 무작위 순서(track 조건은 파일마다 새로 시작이라 순서와 상관없다)"""
    out, st = [None] * len(arrs), None
    for i in np.random.default_rng(0).permutation(len(arrs)):
        st = None if cond == "track" else st
        qd = float(rule[1:]) if rule[1:] else QUIET_DB                  # A15·A20: 조용한 frame 기준 15·20 dB
        if rule == "track":
            a, (hi, lo, st) = arrs[i], track_ref(arrs[i], tau, st)
        else:
            a, hi, lo, st = gated_ref(arrs[i], tau, st, rule == "B", qd)
        out[i] = dd._segments(scale(a, hi, lo))
        if cond == "gap" and len(arrs[i]) < SLOT_FR:
            sil = np.full((SLOT_FR - len(arrs[i]), arrs[i].shape[1]), -100.0)
            st = track_ref(sil, tau, st)[2] if rule == "track" else gated_ref(sil, tau, st, rule == "B", qd)[3]
    return np.concatenate(out)


def segments(a, method, cal):
    """dB [frames, 40] → 정규화 segment [S, 31, 40] (dd._segments와 같은 분할)"""
    if method in ("file", "file_nodc"):
        return dd._segments(scale(a, *span(a)))
    if method in TAUS:
        return dd._segments(scale(a, *track_ref(a, TAUS[method])[:2]))
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
    import train_1unit
    tr, _ = dd.list_files(machine, mid, "train")
    pick = np.random.default_rng(0).choice(len(tr), min(N_CAL, len(tr)), replace=False)
    cal = np.median([span(db(tr[i], False)) for i in pick], axis=0)    # (최대, 최소)
    te, _ = dd.list_files(machine, mid, "test")
    a_dc = [db(p, True) for p in te]
    a_no = [db(p, False) for p in te]
    narrow = float(np.mean([a.max() - a.min() < dd.TOP_DB for a in a_dc]))   # 파일 dB 폭이 80 dB보다 좁은 비율
    feats = {m: np.concatenate([segments(a, m, cal) for a in (a_dc if m == "file" else a_no)])
             for m in METHODS if m not in STREAM and m not in SILENT}
    feats.update({m: stream(a_no, tau) for m, tau in STREAM.items() if m in METHODS})
    feats.update({m: silent_seq(a_no, *c) for m, c in SILENT.items() if m in METHODS})
    rows = []
    for ck in CKPTS:
        pth = os.path.join(SOFTWARE, "weights", ck, unit, "last.pth")
        arg = torch.load(pth, map_location="cpu", weights_only=False)["args"]
        data = train_1unit.prepare(machine, mid, arg["method"], arg["val_frac"], arg["seed"], "cpu", arg.get("hop"))
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
    ap.add_argument("--methods", nargs="*", default=None, help="이 method만 다시 재서 results.csv의 같은 method 줄을 바꾼다")
    a = ap.parse_args()
    units = a.units or [dd.unit_name(m, i) for m, i in dd.UNITS]
    if a.methods:
        METHODS[:] = ["file"] + [m for m in a.methods if m != "file"]       # file은 ΔAUC 기준이라 늘 잰다(fork로 worker에 넘어감)
    with Pool(a.jobs) as p:
        rows = [r for rs in p.map(run_unit, units, chunksize=1) for r in rs]
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "results" + ("_subset" if a.units else "") + ".csv")
    if a.methods and os.path.exists(path):                              # 다른 method 줄은 그대로 둔다
        with open(path, newline="") as fp:
            old = [r for r in csv.DictReader(fp) if r["method"] not in METHODS]
        rows = old + rows
    with open(path, "w", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    for ck in CKPTS:
        for m in METHODS:
            rs = [r for r in rows if r["ckpt"] == ck and r["method"] == m]
            print(f"{ck:15s} {m:9s} AUC {np.mean([r['auc'] for r in rs]):.4f} 평균 ΔAUC {np.mean([r['d_auc'] for r in rs]):+.4f} "
                  f"최저 ΔAUC {min(r['d_auc'] for r in rs):+.4f} 판정 일치 {np.mean([r['pred_agree'] for r in rs]):.4f}")
    kinds = list(dd.MACHINE_IDS)
    for ck in CKPTS:                                                  # 장비 종류별 평균 AUC와 최저 모델
        print(f"{ck:15s} {'':9s} " + " ".join(f"{k:>11s}" for k in kinds) + "  최저 모델")
        for m in METHODS:
            rs = [r for r in rows if r["ckpt"] == ck and r["method"] == m]
            low = min(rs, key=lambda r: r["auc"])
            print(f"{'':15s} {m:9s} " + " ".join(f"{np.mean([r['auc'] for r in rs if r['unit'].rsplit('_id', 1)[0] == k]):11.4f}"
                                                 for k in kinds) + f"  {low['unit']} {low['auc']:.3f}")
    print(os.path.relpath(path, SOFTWARE))


if __name__ == "__main__":
    main()
