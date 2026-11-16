"""보드 배치에서 A 규칙이 software보다 낮은 원인 가리기(모델 하나). 저장소 root에서 돈다. <data 폴더>는 `p52_acc.py prep` 출력(eval.s16, layout.json)이다.
  board   보드와 같은 TrackNorm(하한 −80, 무음 멈춤, 트랙 전체 이어 감)
  reset   파일 칸 첫 frame마다 기준을 새로 시작(software '파일마다 새로 시작'과 같은 조건)
  rel30   board + frame 최대가 기준 최대 − 30 dB보다 작으면 기준 갱신 안 함
  python3 p29_diag.py <data 폴더> <모델 id>
"""
import json
import os
import sys

import numpy as np

ROOT = os.getcwd()
sys.path[:0] = [os.path.join(ROOT, 'hardware/board_test/host'), os.path.join(ROOT, 'software/model'), os.path.join(ROOT, 'software/dataset')]
import p52_acc as pa  # noqa: E402
import p325_mel_load as ml  # noqa: E402
ml.QUIET_DB = float(os.environ.get('QUIET', ml.QUIET_DB))   # 조용한 frame 기준을 바꿔 보기
import snn_fp32  # noqa: E402
import snn_int8 as si  # noqa: E402
from sklearn.metrics import roc_auc_score  # noqa: E402

data, m = sys.argv[1], int(sys.argv[2])
lay = json.load(open(os.path.join(data, 'layout.json')))
man = json.load(open(pa.MANIFEST))['models']
model_of, slots, SC = np.array(lay['model_of']), lay['slots'], lay['slot_cycles']
wav = np.memmap(os.path.join(data, 'eval.s16'), np.int16, 'r').reshape(-1, pa.N_TRACKS)
kmax = lay['n_slots'] * SC * pa.SEG
trs = np.flatnonzero(model_of == m)
idx = np.arange(kmax)[:, None] * pa.HOP + pa.offset(m) + np.arange(pa.FRAME)
db = np.stack([ml.mel_db(wav[idx, tr].astype(np.float32) / 32768.0) for tr in trs])
q = si.quantize(snn_fp32.load_params(os.path.join(ROOT, man[m]['checkpoint'])))
sc = man[m]['weight_scales'][3]


def feats(variant):
    norm, rows, out = ml.TrackNorm(len(trs)), np.arange(len(trs)), np.zeros(db.shape, np.uint8)
    for k in range(kmax):
        if variant == 'reset' and k % (SC * pa.SEG) == 0:
            norm.has[:] = False
        d = db[:, k]
        if variant == 'rel30':
            m_k = np.maximum(d, ml.FLOOR_DB).max(1)
            quiet = norm.has & (m_k < norm.hi - 30)
            keep = (norm.hi.copy(), norm.lo.copy())
            out[:, k] = si.quantize_input(norm(d, rows))
            norm.hi[quiet], norm.lo[quiet] = keep[0][quiet], keep[1][quiet]
            continue
        out[:, k] = si.quantize_input(norm(d, rows))
    return out


for v in os.environ.get('VARIANTS', 'board,reset,rel30').split(','):
    X = feats(v)
    sc_files = {}
    for ti, tr in enumerate(trs):
        for j, (path, lab, ncyc) in enumerate(slots[tr]):
            for c in range(ncyc):
                ks = (j * SC + c) * pa.SEG + np.arange(pa.SEG)
                o = si.forward(q, X[ti][ks][None].astype(np.int64), store_bits=12)[0]
                s0, s1 = o.sum(0)
                sc_files.setdefault(path, [lab, []])[1].append(1 / (1 + np.exp(-(s1 - s0) / pa.SEG * sc)))
    y = [v_[0] for v_ in sc_files.values()]
    s = [np.mean(v_[1]) for v_ in sc_files.values()]
    print(f"{man[m]['unit']} QUIET {ml.QUIET_DB:g} {v:6s} AUC {roc_auc_score(y, s):.3f}  (파일 {len(y)}개)", flush=True)
