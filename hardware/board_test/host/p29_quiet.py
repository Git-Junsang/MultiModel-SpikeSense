"""보드 배치(P5.3 입력)에서 조용한 frame 기준(QUIET_DB)별 Python 전체 경로 AUC, 40개 모델. 저장소 root에서 돈다. <data 폴더>는 `p52_acc.py prep` 출력(eval.s16, layout.json)이다.
FPGA 출력은 같은 입력의 snn_int8과 bit 단위로 같으므로(P5.3, P2.9) 이 값이 그 규칙으로 보드를 돌린 AUC다.
  python3 p29_quiet.py <data 폴더> <출력 json> [기준 dB ...]
"""
import json
import os
import sys
from multiprocessing import Pool

import numpy as np

ROOT = os.getcwd()
sys.path[:0] = [os.path.join(ROOT, 'hardware/board_test/host'), os.path.join(ROOT, 'software/model'), os.path.join(ROOT, 'software/dataset')]
import p52_acc as pa  # noqa: E402
import p325_mel_load as ml  # noqa: E402
import snn_fp32  # noqa: E402
import snn_int8 as si  # noqa: E402
from sklearn.metrics import roc_auc_score  # noqa: E402

DATA, OUT = sys.argv[1], sys.argv[2]
QUIETS = [float(x) for x in sys.argv[3:]] or [15.0, 20.0, 30.0]
lay = json.load(open(os.path.join(DATA, 'layout.json')))
man = json.load(open(pa.MANIFEST))['models']
model_of, slots, SC = np.array(lay['model_of']), lay['slots'], lay['slot_cycles']
kmax = lay['n_slots'] * SC * pa.SEG


def run(m):
    wav = np.memmap(os.path.join(DATA, 'eval.s16'), np.int16, 'r').reshape(-1, pa.N_TRACKS)
    trs = np.flatnonzero(model_of == m)
    idx = np.arange(kmax)[:, None] * pa.HOP + pa.offset(m) + np.arange(pa.FRAME)
    db = np.stack([ml.mel_db(wav[idx, tr].astype(np.float32) / 32768.0) for tr in trs])
    q = si.quantize(snn_fp32.load_params(os.path.join(ROOT, man[m]['checkpoint'])))
    sc = man[m]['weight_scales'][3]
    res = {}
    for qd in QUIETS:
        ml.QUIET_DB = qd
        norm, rows, X = ml.TrackNorm(len(trs)), np.arange(len(trs)), np.zeros(db.shape, np.uint8)
        for k in range(kmax):
            X[:, k] = si.quantize_input(norm(db[:, k], rows))
        files = {}
        for ti, tr in enumerate(trs):
            cyc = [(path, lab, (j * SC + c) * pa.SEG + np.arange(pa.SEG)) for j, (path, lab, n) in enumerate(slots[tr]) for c in range(n)]
            o = si.forward(q, X[ti][np.array([c[2] for c in cyc])].astype(np.int64), store_bits=12)
            for (path, lab, _), oo in zip(cyc, o):
                s0, s1 = oo.sum(0)
                files.setdefault(path, [lab, []])[1].append(1 / (1 + np.exp(-(s1 - s0) / pa.SEG * sc)))
        res[qd] = roc_auc_score([v[0] for v in files.values()], [np.mean(v[1]) for v in files.values()])
    print(man[m]['unit'], {k: round(v, 3) for k, v in res.items()}, flush=True)
    return res


if __name__ == '__main__':
    with Pool(8) as p:
        r = p.map(run, range(40), chunksize=1)
    out = {str(qd): [x[qd] for x in r] for qd in QUIETS}
    json.dump({'units': [m['unit'] for m in man], 'auc': out}, open(OUT, 'w'), indent=1)
    for qd in QUIETS:
        a = np.array(out[str(qd)])
        print(f'QUIET {qd:g} dB: 평균 {a.mean():.4f}, 0.9 이상 {(a >= 0.9).sum()}')
