#!/usr/bin/env python3
"""verify_host.py — software/host의 mmss_host 확인. aarch64 binary를 qemu-aarch64로 돌리고 Python 기준과 비교한다

장치 없이 FPGA mock(mock_fpga.py)과 localhost UDP로 돈다. 시간은 실제 Host·FPGA 값이 아니다. 약 1분.
  1 setup: 모델 image 40개가 DDR3 창에 그대로 있다. 설정 블록. PNU 표 = 04 §3.1 식(numpy). engine PNURTL 표와의 차이(참고)
  2 run: 2채널 WAV(DCASE fan_id06 정상·이상), 트랙 34개(모델 5에 30개 → datagram 23 + 7개), 실시간 속도(--pace)
    2a 추론 요청 필드: RESET_STATE, seq, model_id, n_expect, 빈 byte, datagram 크기, t_host_us(FPGA 시각, 2^32 되감기 포함)
    2b x = Python 특징 추출(p325_mel_load.mel_db + TrackNorm + snn_int8.quantize_input)을 같은 샘플 구간에 쓴 값.
       채널 1에 2 s 무음(무음 frame은 기준 멈춤), 트랙 33은 map 둘째 칸으로 하한 −60 dB
    2c mock 결과 = snn_int8.forward(checkpoint 양자화, 12 bit 저장)를 받은 x에 쓴 값. 모델 image 적재와 RESET_STATE 확인
    2d 판정 = mock 결과로 Python이 구한 판정(decision 같음, score 차 < 1e-9). 버린 추론 요청이 든 판정 주기는 판정 없음
    2e summary: 보낸 수 = mock이 받은 수, 버린 1개 = lost, 늦춘 1개(45 ms) = late, missing_cycles 1, unmatched 0
  3 stop: counter REQ_IN·RES_OUT

    python3 software/host/verify_host.py [--keep]          (저장소 root에서. 빌드: make -C software/host)
"""
import argparse
import csv
import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
sys.path[:0] = [os.path.join(ROOT, 'hardware', 'board_test', 'host'), os.path.join(ROOT, 'simulation', 'engine')]
import p325_mel_load as ml  # noqa: E402  (software/dataset, software/model 경로도 넣는다)
import snn_fp32  # noqa: E402
import snn_int8 as si  # noqa: E402
from part_jitter import TraceJitter, UniformJitter  # noqa: E402

BIN = os.path.join(HERE, 'build', 'mmss_host')
IMG = os.path.join(ROOT, 'hardware', 'data', 'models_l64', 'models.ddr3.bin')
MANIFEST = os.path.join(ROOT, 'hardware', 'data', 'models_l64', 'manifest.json')
TRACE = os.path.join(ROOT, 'hardware', 'board_test', 'p325_meas', 'result', 'm3_group_pin3_load0.csv.gz')
WAVS = [os.path.join(ROOT, 'software', 'dataset', 'dcase', 'fan', 'test', f'{c}_id_06_00000000.wav') for c in ('normal', 'anomaly')]
MAP = [5] * 30 + [0, 1, 39, 20]                  # 트랙 → 모델. 트랙 i는 채널 i % 2
FLOOR = {33: -60.0}                              # map 둘째 칸으로 준 트랙별 하한(나머지는 기본 −80 dB)
DROP, DELAY = (31, 40), (7, 70, 45)              # (트랙, seq) 버림, (트랙, seq, ms) 늦춤
J_US, SLOT, USED, SEG = 800, 0x40000, 131648, 31
ok = True


def check(name, cond, detail=''):
    global ok
    ok &= bool(cond)
    print(('ok   ' if cond else 'FAIL ') + name + (f'  ({detail})' if detail else ''), flush=True)


def host(*args, **kw):
    return subprocess.run(['qemu-aarch64', BIN, *args, '--fpga', '127.0.0.1'], cwd=ROOT, capture_output=True, text=True, **kw)


def expected_tables(tmp):
    """앞 절반 주기의 G(engine TraceJitter의 calib와 같은 표본) → (G 파일, 04 §3.1 식 표, engine 표)"""
    with gzip.open(TRACE, 'rt') as f:
        rows = list(csv.DictReader(f))
    eps = sorted({int(r['period']) for r in rows})
    cut = eps[len(eps) // 2]
    g = np.array([float(r['delay_us']) for r in rows if int(r['period']) < cut])
    path = os.path.join(tmp, 'group.csv')
    with open(path, 'w') as f:
        f.write('period,model_id,delay_us\n')
        f.writelines(f"{r['period']},{r['model_id']},{r['delay_us']}\n" for r in rows if int(r['period']) < cut)
    mean_above = [np.rint((g[g > e] - e).mean()) if (g > e).any() else 0.0 for e in (np.arange(128) + 0.5) * 256]
    remain = (1.0, 2.0, 3.5, 6.5, 12.5, 24.0)
    jt, gt = UniformJitter(J_US), TraceJitter(TRACE)
    lut_u = [[round(jt.delta((i + 0.5) * 256, r)) for r in remain] + [0, 0] for i in range(128)]
    exp = dict(tau=[int(np.ceil(g.max())), J_US, int(np.rint(g.mean()))], lut_g=[int(v) for v in mean_above],
               lut_u=sum(lut_u, []))
    eng = dict(lut_g=[round(gt.delta((i + 0.5) * 256, 1)) for i in range(128)], eg=round(gt.delta(0.0, 1)),
               tau_g=int(np.ceil(gt.quantile(1.0))))
    check('PNU G 표본 = engine calib', g.size == gt.calib.size, f'{g.size}개')
    return path, exp, eng


def make_wav(tmp):
    import soundfile as sf
    if all(os.path.exists(w) for w in WAVS):
        ch = [sf.read(w, dtype='int16')[0] for w in WAVS]
        src = 'DCASE fan_id06 정상·이상'
    else:
        r = np.random.default_rng(0)
        ch = [(r.standard_normal(160000) * a).astype(np.int16) for a in (800, 3000)]
        src = '합성 noise(DCASE wav 없음)'
    n = min(len(c) for c in ch)
    pcm = np.stack([c[:n] for c in ch], 1)
    pcm[48000:80000, 1] = 0                      # 채널 1의 3–5 s: 무음(정규화 기준을 멈추는지)
    path = os.path.join(tmp, 'test.wav')
    sf.write(path, pcm, 16000, subtype='PCM_16')
    return path, pcm, src


def ref_features(pcm, track, model, ks):
    """트랙 하나의 frame k들(0부터 이어짐) → 0–127 (C와 같은 샘플 구간, Python 식)"""
    off = (model * 512 + 20) // 40
    w = pcm[:, track % 2].astype(np.float32) / 32768.0
    db = ml.mel_db(np.stack([w[off + 512 * k: off + 512 * k + 1024] for k in ks]))
    norm, out = ml.TrackNorm(1, FLOOR.get(track, ml.FLOOR_DB)), []
    for i, k in enumerate(ks):
        out.append(si.quantize_input(norm(db[i:i + 1], np.array([0])))[0])
    return np.array(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--keep', action='store_true', help='임시 폴더를 남긴다')
    a = ap.parse_args()
    subprocess.run(['make', '-s', '-C', HERE], check=True)
    tmp = tempfile.mkdtemp(prefix='verify_host_')
    mock = None
    try:
        with open(os.path.join(tmp, 'map.txt'), 'w') as f:
            f.writelines(f'{m} {FLOOR[t]}\n' if t in FLOOR else f'{m}\n' for t, m in enumerate(MAP))
        gpath, exp, eng = expected_tables(tmp)
        wav, pcm, src = make_wav(tmp)
        mock = subprocess.Popen([sys.executable, os.path.join(HERE, 'mock_fpga.py'), '--out', os.path.join(tmp, 'mock'),
                                 '--drop', '%d:%d' % DROP, '--delay', '%d:%d:%d' % DELAY], stdout=subprocess.PIPE, text=True)
        assert mock.stdout.readline().strip() == 'ready'
        mp = os.path.join(tmp, 'map.txt')

        # ---- 1. setup ----
        r = host('setup', '--map', mp, '--models', IMG, '--model-group-delay-trace', gpath, '--jitter-us', str(J_US), timeout=600)
        print(r.stdout + r.stderr, end='')
        check('1 setup 종료 코드 0', r.returncode == 0)
        r_run = host('run', '--map', mp, '--in', wav, '--pace', '--log', os.path.join(tmp, 'run'), timeout=120)
        r_stop = host('stop', timeout=60)
        print(r_run.stderr + r_stop.stdout + r_stop.stderr, end='')
        d = np.load(os.path.join(tmp, 'mock', 'requests.npz'))
        regs = json.load(open(os.path.join(tmp, 'mock', 'regs.json')))
        ddr, img = open(os.path.join(tmp, 'mock', 'ddr3.bin'), 'rb').read(), open(IMG, 'rb').read()
        check('1a 모델 image 40개 = models.ddr3.bin', all(ddr[m * SLOT:m * SLOT + USED] == img[m * SLOT:m * SLOT + USED] for m in range(40)))
        cfg = [regs['cfg'][str(0x300 + 4 * i)] for i in range(6)]
        check('1b 설정 블록', cfg == [len(MAP), 40, 0, 0x0200_0000, 32000, 0], str(cfg))
        pnu = {int(k): v for k, v in regs['pnu'].items()}
        rd = lambda base, n: [pnu.get(base + 4 * i, -1) for i in range(n)]  # noqa: E731
        nreg = [MAP.count(m) for m in range(40)]
        check('1c OFFSET_TABLE = m, N_REG = 모델별 트랙 수', rd(0x1000, 40) == list(range(40)) and rd(0x1100, 40) == nreg)
        check('1d TAU_G·TAU_U·EG, LUT_G, LUT_U = 04 §3.1 식', rd(0x1200, 3) == exp['tau'] and rd(0x1400, 128) == exp['lut_g']
              and rd(0x2000, 1024) == exp['lut_u'], f"TAU_G {exp['tau'][0]}, EG {exp['tau'][2]} µs")
        dg = max(abs(x - y) for x, y in zip(rd(0x1400, 128), eng['lut_g']))
        print(f'     참고: engine PNURTL 표와 차이 LUT_G 최대 {dg} µs, EG {rd(0x1200, 3)[2] - eng["eg"]} µs, '
              f'TAU_G {rd(0x1200, 3)[0] - eng["tau_g"]} µs (engine은 5 µs 칸 수치 적분)')

        # ---- 2. run ----
        check('2 run 종료 코드 0', r_run.returncode == 0, src)
        tr, seq, mdl = d['track'], d['seq'], d['model']
        n = tr.size
        order = np.lexsort((seq, tr))
        k = np.zeros(n, np.int64)                    # seq는 16 bit. 이 시험은 10 s라 period = seq
        k[:] = seq
        check('2a model_id = map, RESET_STATE = (k % 31 == 0), 빈 byte 0',
              (mdl == np.array(MAP)[tr]).all() and (d['flags'] == (k % SEG == 0)).all() and d['pad_ok'].all())
        check('2a n_expect = 모델별 트랙 수', (d['n_expect'] == np.array(nreg)[mdl]).all())
        sizes = {m: sorted({int(x) for x in d['dgram_n'][mdl == m]}) for m in set(MAP)}
        check('2a datagram 크기: 모델 5는 23 + 7, 나머지 1', sizes[5] == [7, 23] and all(sizes[m] == [1] for m in (0, 1, 39, 20)),
              str(sizes))
        lag = (d['t_rx_us'] - d['t_host_us']) & 0xFFFF_FFFF
        step = np.array([(int(d['t_host_us'][j]) - int(d['t_host_us'][i])) & 0xFFFF_FFFF for i, j in zip(order[:-1], order[1:])
                         if tr[i] == tr[j]])
        check('2a t_host_us: FPGA 시각 기준, 받은 시각보다 0~32 ms 앞', (lag < 32000).all(), f'최대 {lag.max()} µs')
        check('2a t_host_us: 같은 트랙 이웃 frame 차이 32 ms', np.abs(step - 32000).max() < 300,
              f'차이 {step.min()}~{step.max()} µs, 2^32 되감기 {int((np.diff(d["t_host_us"]) < -2**31).sum())}번')
        x_c = d['x']
        x_r = np.zeros_like(x_c)
        for t in range(len(MAP)):
            idx = order[tr[order] == t]
            x_r[idx] = ref_features(pcm, t, MAP[t], k[idx])
        diff = np.abs(x_c.astype(int) - x_r.astype(int))
        check('2b x = Python 특징 추출 (1 차이까지)', diff.max() <= 1,
              f'{n}개 추론 요청, 값 {diff.size}개 중 다른 값 {int((diff > 0).sum())}개, 최대 차 {diff.max()}')

        man = json.load(open(MANIFEST))['models']
        res = {(int(t), int(s)): (o0, o1, dr) for t, s, o0, o1, dr in d['res']}
        bad, n_cmp = 0, 0
        for m in sorted(set(MAP)):
            q = si.quantize(snn_fp32.load_params(os.path.join(ROOT, man[m]['checkpoint'])))
            for t in [t for t in range(len(MAP)) if MAP[t] == m]:
                idx = order[tr[order] == t]
                for c in range(len(idx) // SEG):
                    cyc = idx[c * SEG:(c + 1) * SEG]
                    if any(res[(t, int(seq[i]))][2] for i in cyc):
                        continue
                    out = si.forward(q, x_c[cyc][None].astype(np.int64), store_bits=12)[0]
                    got = np.array([res[(t, int(seq[i]))][:2] for i in cyc])
                    bad += int((out != got).any())
                    n_cmp += 1
        check('2c mock 결과 = snn_int8.forward(checkpoint, 12 bit 저장)', bad == 0, f'판정 주기 {n_cmp}개 중 다름 {bad}개')

        rows = list(csv.DictReader(r_run.stdout.splitlines()))
        got = {(int(r['track_id']), int(r['cycle'])): r for r in rows}
        want = {}
        for t in range(len(MAP)):
            idx = order[tr[order] == t]
            for c in range(len(idx) // SEG):
                v = [res[(t, int(seq[i]))] for i in idx[c * SEG:(c + 1) * SEG]]
                if any(x[2] for x in v):
                    continue
                s0, s1 = sum(x[0] for x in v), sum(x[1] for x in v)
                l0, l1 = s0 / SEG * man[MAP[t]]['weight_scales'][3], s1 / SEG * man[MAP[t]]['weight_scales'][3]
                want[(t, c)] = (int(s1 > s0), 1 / (1 + np.exp(l0 - l1)))
        same = set(got) == set(want) and all(int(got[kk]['decision']) == v[0] and abs(float(got[kk]['score']) - v[1]) < 1e-9
                                             and int(got[kk]['model_id']) == MAP[kk[0]] for kk, v in want.items())
        n_anom = sum(int(r['decision']) for r in rows)
        check('2d 판정 = Python 판정, 버린 추론 요청의 판정 주기는 없음', same and (DROP[0], DROP[1] // SEG) not in got,
              f'판정 {len(got)}개(기대 {len(want)}), 이상 판정 {n_anom}개')

        sm = dict(kv.split('=') for kv in r_run.stderr.strip().splitlines()[-1].split()[1:])
        sm = {kk: float(v) for kk, v in sm.items()}
        check('2e summary: sent = mock이 받은 수, lost 1, late 1, deadline_miss 2, missing_cycles 1, unmatched 0, send_err 0',
              sm['sent'] == n and sm['lost'] == 1 and sm['late'] == 1 and sm['deadline_miss'] == 2 and sm['missing_cycles'] == 1
              and sm['unmatched'] == 0 and sm['send_err'] == 0 and sm['judged'] == len(want),
              f"응답 시간 평균 {sm['response_time_mean_us']:.0f} µs, 최대 {sm['response_time_max_us']:.0f} µs(늦춘 결과), overrun {sm['overrun']:.0f}, "
              f"시각 맞추기 {sm['sync_ok']:.0f}번")
        with open(os.path.join(tmp, 'run_model_group.csv')) as f:
            nb = sum(1 for _ in f) - 1
        check('2e 묶음 log = 모델 묶음 수', nb == len({(int(m), int(s)) for m, s in zip(mdl, seq)}), f'{nb}줄')

        # ---- 3. stop ----
        cnt = dict(line.split() for line in r_stop.stdout.splitlines())
        check('3 stop: REQ_IN = 받은 수, RES_OUT = 결과 수', r_stop.returncode == 0 and int(cnt['REQ_IN']) == n - 1
              and int(cnt['RES_OUT']) == n - 1 and int(cnt['REQ_DROP']) == 1)
    finally:
        if mock:
            mock.terminate()
            mock.wait()
        if a.keep:
            print('임시 폴더:', tmp)
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    print('PASS' if ok else 'FAIL')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
