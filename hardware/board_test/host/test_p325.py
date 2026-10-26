#!/usr/bin/env python3
"""test_p325.py — P3.25 Host jitter 측정 code 확인. 장치 없이 약 20초 돈다

입력은 모두 합성이고 측정값이 아니다. 파일은 임시 폴더에만 쓴다.
  1 mel: p325_mel_load.mel_db = librosa melspectrogram(power 2) + power_to_db(ref 1) (DCASE wav, 없으면 noise).
    Frame 100–159를 무음(−100 dB), 200–203을 40 dB 작게 바꾸고 TrackNorm을 frame씩 한 값 = realtime_norm.py의 gated_ref(평가한 규칙).
    0–127 입력은 1 차이까지
  2 M3: 8트랙 10 period를 실제로 돌려 모델 그룹 수와 시각 순서(t_frame ≤ t_compute_start ≤ t_ready)
  3 M1: drift +40·−25 ppm, 전달 지연 2 ms + 지수분포 0.3 ms, xrun 1번(160샘플 빠짐)인 합성 block → Recorder → analyze.
    drift ±0.2 ppm, frame 끝 offset 오차의 증가 = drift × 시간(+ xrun으로 빠진 시간), xrun frame 표시
  4 M4: packet byte 위치(06 §4.1·§4.2), 32 bit µs 되감기, 받는 쪽 clock offset 5 s·drift 30 ppm·편도 45 µs + 지수분포 3 µs
    (대칭)인 합성 packet → 편도 오차 ±3 µs, clock drift ±0.5 ppm
  5 trace: M1 + M4 합성 로그로 만든 trace를 engine의 TraceJitter(part_jitter.py)가 읽고 뒤 절반 period를 재생한다

    python3 hardware/board_test/host/test_p325.py
"""
import csv
import json
import os
import shutil
import sys
import tempfile
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..', '..'))
sys.path[:0] = [HERE, os.path.join(ROOT, 'simulation', 'engine'), os.path.join(ROOT, 'software', 'model', 'eval')]
import p325_mel_load as ml  # noqa: E402  (BLAS thread 1, software/ 경로)
import realtime_norm as rn  # noqa: E402
import librosa  # noqa: E402
import snn_int8 as si  # noqa: E402
import analyze_p325 as an  # noqa: E402
import p325_audio_rec as ar  # noqa: E402
import p325_udp_delay as ul  # noqa: E402
from p325_common import M, OFF_NS, P_NS, SEG  # noqa: E402
from part_jitter import TraceJitter  # noqa: E402

ok = True


def check(name, cond, detail=''):
    global ok
    ok &= bool(cond)
    print(('ok   ' if cond else 'FAIL ') + name + (f'  ({detail})' if detail else ''))


# ---- 1. Mel 식 ----
w, src = ml.load_audio(ml.WAV)
K = (w.size - 1024) // 512 + 1
ours = ml.mel_db(np.lib.stride_tricks.sliding_window_view(w, 1024)[::512][:K])
ref = librosa.power_to_db(librosa.feature.melspectrogram(y=w.astype(np.float64), sr=16000, n_fft=1024, hop_length=512,
                                                         n_mels=40), ref=1.0, top_db=None).T[1:K + 1]   # center=True라 한 칸 밀림
d = np.abs(ours - ref).max()
check('1a mel dB = librosa', d < 0.01, f'{src}, frame {K}개, 최대 차 {d:.1e} dB')
n = K
ref, ours = ref.copy(), ours.copy()
ref[100:160] = ours[100:160] = -100.0                                    # 무음: 기준을 멈춰야 한다
ref[200:204] -= 40.0                                                     # 조용한 frame: 최소를 멈춰야 한다
ours[200:204] -= 40.0
a_f, hi, lo, _ = rn.gated_ref(ref, ml.TAU_S, quiet_db=ml.QUIET_DB)
q_ref = si.quantize_input(np.clip((a_f - lo) / np.maximum(hi - lo, 1e-8), 0, 1))
for name, db in (('1b TrackNorm frame씩 = realtime_norm.gated_ref(같은 dB, 무음 포함)', ref), ('1c 0~127 입력: float32 mel과 librosa', ours)):
    norm = ml.TrackNorm(1)
    q = np.concatenate([si.quantize_input(norm(db[k:k + 1], np.array([0]))) for k in range(n)])
    diff = np.abs(q - q_ref)
    check(name, diff.max() == 0 if db is ref else diff.max() <= 1 and (diff > 0).mean() < 1e-3,
          f'{n} frame, 다른 칸 {(diff > 0).mean():.1e}, 최대 차 {diff.max()}')

# ---- 2. M3 실제 실행(짧게) ----
E = 10
t0 = time.monotonic_ns() + 50_000_000
log, groups = ml.run(8, E, 1, [], w, t0)
tf = t0 + np.arange(E)[:, None] * P_NS + np.arange(M)[None, :] * OFF_NS
has = log[..., 0] >= 0
check('2 M3 8트랙 10 period: 묶음 80개, t_frame ≤ 시작 ≤ 끝',
      has.sum() == E * 8 and (log[..., 0][has] >= tf[has]).all() and (log[..., 1][has] >= log[..., 0][has]).all(),
      f'묶음 {has.sum()}개')

tmp = tempfile.mkdtemp(prefix='test_p325_')
rng = np.random.default_rng(1)

# ---- 3. M1 합성 block ----
rate, B, T0, nb, ppm, lost = 16000, 16, 10 ** 12, 120_000, [40.0, -25.0], [0, 160]
arr, dev, xr = [], [], []
for dv in range(2):
    per = 1e9 / (rate * (1 + ppm[dv] * 1e-6))                       # 장치 샘플 하나의 Host 시간
    j = np.arange(nb)
    true_last = (j + 1) * B - 1 + np.where(j >= nb // 2, lost[dv], 0)
    a = T0 + 3_000_000 + dv * 1_234_567 + true_last * per + 2e6 + rng.exponential(3e5, nb)
    arr.append(np.maximum.accumulate(a))                            # 한 장치의 callback은 차례로 온다
    dev.append(np.full(nb, dv))
    xr.append((j == nb // 2) & (lost[dv] > 0))
arr, dev, xr = (np.concatenate(v) for v in (arr, dev, xr))
rec = ar.Recorder(2, 1, rate, 1, 2 * nb + 10, T0)
for i in np.argsort(arr, kind='stable'):
    t = int(arr[i])
    rec.now = lambda t=t: t + 2000                                  # Frame 넘김 = 도착 + 2 µs
    rec.block(int(dev[i]), B, t, int(xr[i]))
p1 = os.path.join(tmp, 'm1.csv')
with open(p1, 'w') as f:
    f.write(ar.COLS + '\n')
    np.savetxt(f, rec.rows[:rec.n], fmt='%d', delimiter=',')
json.dump(dict(rate=rate, T0_ns=T0, devices=[dict(name='합성 0'), dict(name='합성 1')]), open(p1 + '.json', 'w'))
g1, i1 = an.m1(p1)
dd = i1['devices']
check('3a M1 drift ppm', all(abs(x['drift_ppm'] - ppm[k]) < 0.2 for k, x in enumerate(dd)),
      ', '.join(f"{x['drift_ppm']:+.3f}" for x in dd))
span = []
for k, x in enumerate(dd):
    ep = rec.rows[:rec.n][(rec.rows[:rec.n, 0] == k) & (rec.rows[:rec.n, 6] >= 0), 7]
    exp = (ep.max() - ep.min()) * P_NS * (1 / (1 + ppm[k] * 1e-6) - 1) / 1e6 + lost[k] / rate * 1e3
    span.append((x['cut_err_last_ms'] - x['cut_err_first_ms'], exp))
check('3b frame 끝 offset 오차 증가 = drift × 시간 + 빠진 샘플', all(abs(g - e) < 0.1 for g, e in span),
      ', '.join(f'{g:+.3f}/{e:+.3f} ms' for g, e in span))
fr = i1['frame_ready']
check('3c frame 준비 지연 ≥ 0, 1 block + 꼬리 안', fr['n'] > 0 and np.nanmin(g1['d_audio']) > -10e3 and fr['p50'] < 2000,
      f"p50 {fr['p50']:.0f} µs, 최대 {fr['max']:.0f} µs")
check('3d xrun frame 표시', 1 <= i1['xrun_frames'] <= 4, f"{i1['xrun_frames']}개")

# ---- 4. M4 ----
b = ul.REQ.pack(0xA5, 1, 0x0102, 0x0304, 7, 0x0A0B0C0D, bytes(range(40)))
r = ul.RES.pack(0x0102, 0x0304, 7, 4, 0x0506, 1, 2, 3, 4, -5, 6)
check('4a packet byte 위치(06 §4.1·4.2)',
      (b[0], b[1], b[2:4], b[4:6], b[6], b[8:12], b[16:56], len(b)) == (0xA5, 1, b'\x02\x01', b'\x04\x03', 7, b'\x0d\x0c\x0b\x0a',
                                                                       bytes(range(40)), 64)
      and (r[0:2], r[2:4], r[4], r[5], r[6:8], r[12:16], r[20:24], r[24:26], len(r)) == (
          b'\x02\x01', b'\x04\x03', 7, 4, b'\x06\x05', b'\x02\0\0\0', b'\x04\0\0\0', b'\xfb\xff', 32))
ti = (2 ** 32 - 5000 + np.arange(0, 20000, 100)) % 2 ** 32
ua, ud = ul.unwrap_us(ti, (ti + 7) % 2 ** 32)
check('4b 32 bit µs 되감기', (np.diff(ua) == 100_000).all() and (ud - ua == 7000).all())
T, E = 64, 1875
order = np.concatenate([np.flatnonzero(np.arange(T) % M == m) for m in range(M)])
k, tr = np.repeat(np.arange(E), T), np.tile(order, E)
N = k.size
ts = T0 + k * P_NS + (tr % M) * OFF_NS
t1 = ts + rng.uniform(0, 20e3, N)
fwd, back = 45e3 + rng.exponential(3e3, N), 45e3 + rng.exponential(3e3, N)
remote = lambda t: 5e9 + t * (1 + 30e-6)                            # noqa: E731  받는 쪽 clock
t2, t3 = (np.floor(remote(t1 + fwd + p) / 1e3) * 1e3 for p in (0.0, 10e3))
t4 = t1 + fwd + 10e3 + back
gone = rng.random(N) < 1e-3
t2[gone] = t3[gone] = t4[gone] = -1
p4 = os.path.join(tmp, 'm4.csv')
cols = dict(seq=k & 0xFFFF, track_id=tr, model_id=tr % M, period=k, t_send_host_ns=t1, t_arr_fpga_ns=t2, t_done_fpga_ns=t3,
            t_recv_host_ns=t4, lost=gone, reordered=np.zeros(N), retransmitted=np.zeros(N), t_sched_host_ns=ts)
with open(p4, 'w') as f:
    f.write(ul.COLS + '\n')
    np.savetxt(f, np.column_stack([cols[c] for c in ul.COLS.split(',')]).astype(np.int64), fmt='%d', delimiter=',')
g4, i4 = an.m4(p4)
truth = an.grid(tr, k, f=np.where(gone, np.nan, fwd), b=np.where(gone, np.nan, back))
ef, eb = g4['d_fwd'] - truth['f'], g4['d_back'] - truth['b']
check('4c M4 편도 지연 오차 ±3 µs', np.nanmax(np.abs(ef)) < 3e3 and np.nanmax(np.abs(eb)) < 3e3,
      f'추론 요청 최대 {np.nanmax(np.abs(ef)) / 1e3:.2f} µs, 결과 최대 {np.nanmax(np.abs(eb)) / 1e3:.2f} µs')
check('4d M4 clock drift, 결과 없음 수', abs(i4['clock_drift_ppm'] - 30) < 0.5 and i4['lost'] == gone.sum(),
      f"{i4['clock_drift_ppm']:.3f} ppm, 없음 {i4['lost']}")

# ---- 5. trace → engine ----
pt = os.path.join(tmp, 'trace.csv')
track, period, model, t, status = an.compose({'m1': g1, 'm4': g4})
an.write_trace(pt, track, period, model, t, status, 0)
rows = list(csv.DictReader(open(pt)))
check('5a trace 열', list(rows[0]) == an.TRACE_COLS.split(','), f'{len(rows)}줄')
jt = TraceJitter(pt)
eps = sorted({int(x['period']) for x in rows})
tid = sorted({int(x['track_id']) for x in rows})
D = np.full((len(tid), len(eps)), np.nan)
for x in rows:
    D[tid.index(int(x['track_id'])), eps.index(int(x['period']))] = float(x['t_ready_us']) - float(x['t_host_us'])
h = len(eps) // 2
same = np.isfinite(D[:, h:])
check('5b engine trace 재생 = 뒤 절반', jt.replay.shape == D[:, h:].shape and np.allclose(jt.replay[same], D[:, h:][same]),
      f'트랙 {len(tid)}, period {len(eps)}')
shutil.rmtree(tmp)
print('PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
