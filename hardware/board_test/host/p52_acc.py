#!/usr/bin/env python3
"""p52_acc.py — 음원 → mel(Host) → FPGA → 판정(Host) 정확도와 속도 (P5.2). 개발 서버에서 준비·비교, 보드 실행은 FPGA Host

평가 파일(40개 모델, 학습에 쓰지 않은 test 파일, 02 §3)을 1,024트랙에 나눠 1,024채널 raw(S16LE, 머리말 없음) 하나로 만든다.
WAV 머리말의 data 크기는 32 bit라 4 GiB를 넘을 수 있어 raw로 둔다(mmss_host --channels 1024).
파일마다 판정 주기 12개 칸(12 × 31 × 512 = 190,464 샘플)을 준다. 학습 평가와 같은 수의 앞 주기(10 s 파일 10개,
ToyCar 11 s 파일 11개)의 frame은 모두 파일 안에 들고, 나머지 주기는 버린다. 모델 m의 frame k는 샘플 [O_m + 512k, O_m + 512k + 1,024)다(06 §2).

  prep  평가 목록, 트랙 배정, <out>/eval.s16(1,024채널 S16LE raw), <out>/map.txt, <out>/layout.json
  ref   보드 실행 산출물(<run>/board_result.csv, board_judge.csv, req.pcap)과 비교:
        1) FPGA: Host가 실제로 보낸 입력(pcap)에 snn_int8.forward(12 bit 저장)를 쓴 값 = 보드 out0·out1
        2) Host 특징: Python 특징(p325_mel_load.mel_db + SegNorm + quantize_input) = 보낸 입력
        3) 판정: Host 판정 = 보드 출력으로 Python이 구한 판정
        4) AUC(파일 단위, 02 §3): 보드, Python 전체 경로, 학습 특징(파일 정규화)·seg 정규화 software 값
        5) 속도: 응답 시간(Host 수신 − t_host), FPGA 시간(t_done − t_in), deadline miss

    python3 hardware/board_test/host/p52_acc.py prep --out <dir> [--jobs 4]
    python3 hardware/board_test/host/p52_acc.py ref  --out <dir> --run <dir>
"""
import argparse
import csv
import json
import os
import struct
import sys
from multiprocessing import Pool

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..', '..'))
SW = os.path.join(ROOT, 'software')
sys.path[:0] = [HERE, os.path.join(SW, 'model'), os.path.join(SW, 'train'), os.path.join(SW, 'dataset'),
                os.path.join(SW, 'model', 'eval')]

N_TRACKS, SEG, HOP, FRAME, SR = 1024, 31, 512, 1024, 16000
SLOT_CYC = 12                                # 파일 하나의 칸 = 판정 주기 12개, 앞 (파일의 학습 구간 수)개만 쓴다
SLOT = SLOT_CYC * SEG * HOP                  # 190,464 샘플
MANIFEST = os.path.join(ROOT, 'hardware', 'data', 'models_l64', 'manifest.json')


def offset(m):
    return (512 * m + 20) // 40              # software/host와 같은 offset 샘플


def eval_files(m):
    """모델 m의 평가 파일 (경로, 라벨, 구간 수) 목록. train_1unit.prepare의 test_keep과 같은 파일"""
    import torch
    import dcase_data as dd
    import train_1unit
    man = json.load(open(MANIFEST))['models'][m]
    machine, mid = next((a, b) for a, b in dd.UNITS if dd.unit_name(a, b) == man['unit'])
    arg = torch.load(os.path.join(ROOT, man['checkpoint']), map_location='cpu', weights_only=False)['args']
    data = train_1unit.prepare(machine, mid, arg['method'], arg['val_frac'], arg['seed'], 'cpu', arg.get('hop'))
    fi = dd.load_unit(machine, mid, 'test')['file_idx'][data['test_keep']]
    paths, labels = dd.list_files(machine, mid, 'test')
    files = np.unique(fi)
    nc = np.bincount(fi)[files]
    assert nc.max() < SLOT_CYC
    return [(os.path.relpath(paths[i], ROOT), int(labels[i]), int(c)) for i, c in zip(files, nc)]


def prep(a):
    import soundfile as sf
    with Pool(a.jobs) as p:
        ev = p.map(eval_files, range(40), chunksize=1)
    n = np.array([len(e) for e in ev])
    t = np.maximum(1, np.floor(N_TRACKS * n / n.sum()).astype(int))       # 모델마다 트랙 수(파일 수에 비례, 합 1,024)
    for i in np.argsort(-(N_TRACKS * n / n.sum() - t))[:N_TRACKS - t.sum()]:
        t[i] += 1
    assert t.sum() == N_TRACKS
    base = np.concatenate([[0], np.cumsum(t)[:-1]])
    model_of = np.repeat(np.arange(40), t)
    slots = [[] for _ in range(N_TRACKS)]    # 트랙마다 칸 순서의 (경로, 라벨)
    for m in range(40):
        for f, e in enumerate(ev[m]):
            slots[base[m] + f % t[m]].append(e)
    ns = max(len(s) for s in slots)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, 'map.txt'), 'w') as f:
        f.writelines(f'{m}\n' for m in model_of)
    json.dump({'slot': SLOT, 'slot_cycles': SLOT_CYC, 'n_slots': ns, 'model_of': model_of.tolist(),
               'slots': slots}, open(os.path.join(a.out, 'layout.json'), 'w'))
    L = ns * SLOT + SLOT                     # 끝에 빈 칸 하나: 마지막 파일의 결과가 다 돌아올 때까지 Host가 돈다
    path = os.path.join(a.out, 'eval.s16')
    with open(path, 'wb') as f:
        for j in range(ns + 1):
            blk = np.zeros((SLOT, N_TRACKS), np.int16)
            for tr in range(N_TRACKS):
                if j < len(slots[tr]):
                    w = sf.read(os.path.join(ROOT, slots[tr][j][0]), dtype='int16')[0][:SLOT]
                    blk[:len(w), tr] = w
            f.write(blk.tobytes())
            print(f'칸 {j + 1}/{ns + 1}', flush=True)
    print(f'파일 {n.sum()}개(정상 {sum(x[1] == 0 for e in ev for x in e)}, 이상 {sum(x[1] == 1 for e in ev for x in e)}), '
          f'트랙 {N_TRACKS}, 칸 {ns}, 길이 {L / SR:.1f} s, {path} {os.path.getsize(path) / 2**30:.2f} GiB')


def read_pcap(path, nk):
    """Host → FPGA 추론 요청 → x[트랙, frame, 40](uint8), 있는지[트랙, frame]. frame = seq(이 시험은 65,536 미만)"""
    x = np.zeros((N_TRACKS, nk, 40), np.uint8)
    have = np.zeros((N_TRACKS, nk), bool)
    d = open(path, 'rb').read()
    o = 24
    hl = 14 if struct.unpack_from('<I', d, 20)[0] == 1 else 16          # Ethernet 또는 Linux cooked
    while o + 16 <= len(d):
        cap = struct.unpack_from('<IIII', d, o)[2]
        pk = d[o + 16:o + 16 + cap]
        o += 16 + cap
        ihl = (pk[hl] & 0xF) * 4
        if pk[hl + 9] != 17 or struct.unpack_from('>H', pk, hl + ihl + 2)[0] != 5000:
            continue
        r = np.frombuffer(pk[hl + ihl + 8:], np.uint8).reshape(-1, 64)
        tr = r[:, 2].astype(int) | r[:, 3].astype(int) << 8
        k = r[:, 4].astype(int) | r[:, 5].astype(int) << 8
        x[tr, k] = r[:, 16:56]
        have[tr, k] = True
    return x, have


def ref(a):
    import snn_fp32
    import snn_int8 as si
    import p325_mel_load as ml
    from sklearn.metrics import roc_auc_score
    lay = json.load(open(os.path.join(a.out, 'layout.json')))
    man = json.load(open(MANIFEST))['models']
    model_of, slots = np.array(lay['model_of']), lay['slots']
    nk = (lay['n_slots'] + 1) * lay['slot_cycles'] * SEG
    # track_id,seq,epoch,model_id,flags,batch_n,t_host_us,t_in_us,t_start_us,t_done_us,out0,out1,t_host_ns,t_recv_ns,resp_us
    r = np.loadtxt(os.path.join(a.run, 'board_result.csv'), delimiter=',', skiprows=1, usecols=(0, 2, 5, 7, 8, 9, 10, 11, 14))
    tr_r, k_r = r[:, 0].astype(int), r[:, 1].astype(int)
    out_b = np.zeros((N_TRACKS, nk, 2), np.int64)
    have_r = np.zeros((N_TRACKS, nk), bool)
    out_b[tr_r, k_r] = r[:, 6:8].astype(np.int64)
    have_r[tr_r, k_r] = True
    x_b, have_q = read_pcap(os.path.join(a.run, 'req.pcap'), nk)
    judge = {(int(j[0]), int(j[1])): (int(j[3]), float(j[4])) for j in csv.reader(open(os.path.join(a.run, 'board_judge.csv'))) if j[0].isdigit()}
    lost = np.argwhere(have_q & ~have_r)
    print(f'결과 {len(r)}, 잡은 추론 요청 {int(have_q.sum())}, Host 판정 {len(judge)}, 결과가 없는 요청 {len(lost)}', flush=True)

    wav = np.memmap(os.path.join(a.out, 'eval.s16'), np.int16, 'r').reshape(-1, N_TRACKS)
    st = dict(cyc=0, fpga_bad=0, fpga_bad_val=0, x_diff_val=0, x_diff_req=0, x_vals=0, judge_bad=0, missing=0)
    score = {'board': {}, 'python': {}}          # (모델, 파일 경로) → [라벨, cycle 점수]
    for m in range(40):
        q = si.quantize(snn_fp32.load_params(os.path.join(ROOT, man[m]['checkpoint'])))
        sc = man[m]['weight_scales'][3]
        for tr in np.flatnonzero(model_of == m):
            cyc, K = [], []                       # 트랙의 판정 주기를 모아 forward 한 번
            for j, (path, lab, ncyc) in enumerate(slots[tr]):
                for c in range(ncyc):
                    ks = (j * lay['slot_cycles'] + c) * SEG + np.arange(SEG)
                    if not (have_r[tr, ks].all() and have_q[tr, ks].all()):
                        st['missing'] += 1
                        continue
                    cyc.append((j, c, path, lab))
                    K.append(ks)
            if not cyc:
                continue
            K = np.array(K)
            X, G = x_b[tr, K].astype(np.int64), out_b[tr, K]
            w = wav[K[..., None] * HOP + offset(m) + np.arange(FRAME), tr].astype(np.float32) / 32768.0
            db = ml.mel_db(w.reshape(-1, FRAME)).reshape(len(K), SEG, -1)
            hi = np.maximum.accumulate(db.max(2), axis=1)          # SegNorm과 같은 누적 최대·최소(판정 주기마다 새로)
            lo = np.maximum(np.minimum.accumulate(db.min(2), axis=1), hi - 80.0)
            XP = si.quantize_input(np.clip((db - lo[..., None]) / np.maximum(hi - lo, 1e-8)[..., None], 0, 1)).astype(np.int64)
            out = si.forward(q, X, store_bits=12)
            op = si.forward(q, XP, store_bits=12)
            st['cyc'] += len(cyc)
            st['fpga_bad'] += int((out != G).any((1, 2)).sum())
            st['fpga_bad_val'] += int((out != G).sum())
            d = XP != X
            st['x_diff_val'] += int(d.sum())
            st['x_diff_req'] += int(d.any(2).sum())
            st['x_vals'] += d.size
            for (j, c, path, lab), g, o in zip(cyc, G, op):
                s0, s1 = g.sum(0)
                pb = 1 / (1 + np.exp(-(s1 - s0) / SEG * sc))
                jd = judge.get((int(tr), j * lay['slot_cycles'] + c))
                st['judge_bad'] += int(jd is None or jd[0] != int(s1 > s0) or abs(jd[1] - pb) > 1e-6)
                p0, p1 = o.sum(0)
                score['board'].setdefault((m, path), [lab, []])[1].append(jd[1] if jd else pb)
                score['python'].setdefault((m, path), [lab, []])[1].append(1 / (1 + np.exp(-(p1 - p0) / SEG * sc)))
        print(f'모델 {m:2d}: 누적 판정 주기 {st["cyc"]}, FPGA 다름 {st["fpga_bad"]}, 특징 다른 값 {st["x_diff_val"]}', flush=True)

    auc = {}
    for k in score:
        for m in range(40):
            v = [(lab, np.mean(sv)) for (mm, _), (lab, sv) in score[k].items() if mm == m]
            auc.setdefault(k, []).append(roc_auc_score([l for l, _ in v], [s_ for _, s_ in v]))
    off = {}
    for row in csv.DictReader(open(os.path.join(SW, 'train_result', 'eval', 'realtime_norm', 'results.csv'))):
        if row['ckpt'] == 'L_normal_noaug' and row['method'] in ('file', 'seg'):
            off.setdefault(row['method'], {})[row['unit']] = float(row['auc'])
    for meth in ('file', 'seg'):
        auc['sw_' + meth] = [off[meth][man[m]['unit']] for m in range(40)]

    lat = r[:, 8]
    fpga = (r[:, 5].astype(np.int64) - r[:, 3].astype(np.int64)) & 0xFFFF_FFFF
    wait = (r[:, 4].astype(np.int64) - r[:, 3].astype(np.int64)) & 0xFFFF_FFFF
    pc = lambda v, p_: float(np.percentile(v, p_))
    out = dict(stats=st, auc_mean={k: float(np.mean(v)) for k, v in auc.items()},
               auc_ge_0_9={k: int(np.sum(np.array(v) >= 0.9)) for k, v in auc.items()},
               auc_per_model={k: [round(x_, 6) for x_ in v] for k, v in auc.items()},
               n_files=len(score['board']), lost=lost.tolist(),
               resp_us={p_: pc(lat, p_) for p_ in (50, 99, 99.9, 100)}, fpga_us={p_: pc(fpga, p_) for p_ in (50, 99, 99.9, 100)},
               wait_us={p_: pc(wait, p_) for p_ in (50, 99, 100)}, batch_n_mean=float(r[:, 2].mean()), n_results=len(r),
               late_32ms=int((lat > 32000).sum()))
    json.dump(out, open(os.path.join(a.run, 'acc_summary.json'), 'w'), indent=1, ensure_ascii=False)
    print(json.dumps({k: out[k] for k in ('stats', 'auc_mean', 'auc_ge_0_9', 'n_files', 'resp_us', 'fpga_us', 'wait_us',
                                         'batch_n_mean', 'n_results', 'late_32ms')}, indent=1, ensure_ascii=False))
    print('결과가 없는 요청 (트랙, frame):', lost.tolist()[:40])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=['prep', 'ref'])
    ap.add_argument('--out', required=True)
    ap.add_argument('--run', default='')
    ap.add_argument('--jobs', type=int, default=4)
    a = ap.parse_args()
    prep(a) if a.mode == 'prep' else ref(a)


if __name__ == '__main__':
    main()
