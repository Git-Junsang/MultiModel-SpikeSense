#!/usr/bin/env python3
"""p325_mel_load.py — M3 Host 전처리·OS jitter (P3.25, papers/journal/DAC_2027_experiment_figure_request.md §4)

트랙 N개(기본 1,024)의 mel을 32 ms마다 구하며, 모델 묶음마다 계산 시작·끝 시각을 Host clock(CLOCK_MONOTONIC)으로 남긴다.
음성은 DCASE wav 하나를 트랙마다 다른 위치에서 읽어 복제한다. wav가 없으면 합성 noise를 쓰고 <out>.json에 적는다.
처리 순서는 모델별이다. 모델 m의 트랙(track % 40 = m)은 epoch k의 offset 시각 t_frame = T0 + k × 32 ms + m × 0.8 ms에
frame이 준비됐다고 보고 한 번에 계산한다. 그래서 같은 모델·epoch의 트랙은 t_compute_start와 t_ready가 같다.
계산 thread는 t_frame까지 time.sleep으로 기다린다. 깨어나는 지연(timer slack, scheduling)도 OS jitter로 잰다.

mel 식은 학습 특징(software/dataset/dcase_data.py: librosa melspectrogram power 2 → power_to_db)을 frame 하나에 쓴 것이다.
  periodic Hann 1,024 → rfft → |X|² → Slaney mel 40 → 10·log10(max(S, 1e-10))
실시간 정규화는 아직 정하지 않았다(02_MODEL.md §5). P3.21에서 손실이 가장 적던 seg 방식(segment 31 frame 안 누적 최대·최소,
top_db 80, model/eval/realtime_norm.py)을 쓰고, 0~127 양자화는 snn_int8.quantize_input을 쓴다. 같은 식인지는 test_p325.py가
librosa와 비교한다. BLAS thread는 1개로 둔다(계산 thread와 CPU를 다투지 않게).

    python3 hardware/board_test/host/p325_mel_load.py --seconds 300                       # pinning 없음, 부하 없음
    python3 hardware/board_test/host/p325_mel_load.py --seconds 300 --pin 3               # 계산 thread를 CPU 3에 고정
    python3 hardware/board_test/host/p325_mel_load.py --seconds 300 --pin 3 --load 8      # + CPU 부하 process 8개
    python3 hardware/board_test/host/p325_mel_load.py --seconds 300 --load 8              # pinning 없음 + 부하
출력: --out(기본 p325_meas/result/m3_t<트랙>_w<thread>_pin<CPU>_load<n>.csv.gz)과 <out>.json(조건·머신)
  epoch, track_id, model_id, t_frame_ns, t_compute_start_ns, t_ready_ns, cpu, thread, load_condition
  cpu = 계산을 시작한 CPU(sched_getcpu), thread = 계산 thread 번호, load_condition = load<부하 process 수>.
  load0은 이 script가 부하를 더하지 않았다는 뜻일 뿐이다. 다른 작업이 돌고 있으면 idle이 아니다(<out>.json의 loadavg).
1,024트랙 300 s는 960만 줄이다(gzip 줄당 약 14 B, 약 130 MB). 측정은 실제 Host(sdsl-llm 등)에서 하고 개발 서버 결과는 기능 확인으로만 쓴다.
"""
import os

for _k in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(_k, '1')
import argparse  # noqa: E402
import ctypes  # noqa: E402
import sys  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..', '..'))
sys.path[:0] = [HERE, os.path.join(ROOT, 'software', 'dataset'), os.path.join(ROOT, 'software', 'model')]
import librosa  # noqa: E402
import dcase_data as dd  # noqa: E402
import snn_int8 as si  # noqa: E402
from p325_common import FRAME, HOP, M, OFF_NS, P_NS, RESULT, SEG, CpuLoad, open_out, parse_cpus, write_meta  # noqa: E402

assert (dd.SR, dd.N_FFT, dd.HOP, dd.SEG_FRAMES) == (16000, FRAME, HOP, SEG)
WIN = librosa.filters.get_window('hann', dd.N_FFT, fftbins=True).astype(np.float32)
BASIS_T = np.ascontiguousarray(librosa.filters.mel(sr=dd.SR, n_fft=dd.N_FFT, n_mels=dd.N_MELS).T)   # (513, 40) Slaney
WAV = os.path.join(ROOT, 'software', 'dataset', 'dcase', 'fan', 'train', 'normal_id_01_00000000.wav')
COLS = 'epoch,track_id,model_id,t_frame_ns,t_compute_start_ns,t_ready_ns,cpu,thread,load_condition'
_libc = ctypes.CDLL(None)


def mel_db(x):
    """frame (n, 1,024) → mel dB (n, 40). melspectrogram(power 2) + power_to_db(ref 1, top_db 없음)의 frame 하나"""
    p = np.abs(np.fft.rfft(x * WIN, axis=1)) ** 2
    return 10.0 * np.log10(np.maximum(p @ BASIS_T, 1e-10))


class SegNorm:
    """seg 정규화: segment 첫 frame부터 지금까지의 최대·최소 dB로 늘인다. 최소는 최대 − 80 dB 아래로 내려가지 않는다"""

    def __init__(self, n):
        self.hi, self.lo = np.zeros(n), np.zeros(n)

    def __call__(self, db, rows, first):
        hi, lo = db.max(1), db.min(1)
        if not first:
            hi, lo = np.maximum(hi, self.hi[rows]), np.minimum(lo, self.lo[rows])
        self.hi[rows], self.lo[rows] = hi, lo
        lo = np.maximum(lo, hi - dd.TOP_DB)
        return np.clip((db - lo[:, None]) / np.maximum(hi - lo, 1e-8)[:, None], 0, 1)


def load_audio(path):
    if path and os.path.exists(path):
        return dd.read_wave(path).astype(np.float32), path
    return (0.1 * np.random.default_rng(0).standard_normal(10 * dd.SR)).astype(np.float32), 'synthetic noise (seed 0, 10 s)'


def run(tracks, epochs, workers, pin, wave, t0):
    """계산 thread workers개. 모델 m은 thread m % workers가 맡는다. 반환 (epoch, 모델)별 [시작, 끝, cpu, thread]"""
    groups = [np.flatnonzero(np.arange(tracks) % M == m) for m in range(M)]
    start = (np.arange(tracks) * 7919) % wave.size                 # 트랙마다 wav의 다른 위치
    ar, L = np.arange(FRAME), wave.size
    norm, payload = SegNorm(tracks), np.zeros((tracks, dd.N_MELS), np.uint8)
    log = np.full((epochs, M, 4), -1, np.int64)

    def work(i):
        if pin:
            os.sched_setaffinity(0, {pin[i % len(pin)]})
        mine = [m for m in range(M) if m % workers == i and groups[m].size]
        for k in range(epochs):
            for m in mine:
                d = t0 + k * P_NS + m * OFF_NS - time.monotonic_ns()
                if d > 0:
                    time.sleep(d / 1e9)
                ts, cpu = time.monotonic_ns(), _libc.sched_getcpu()
                rows = groups[m]
                x = wave[(start[rows, None] + (k * HOP) % L + ar) % L]
                payload[rows] = si.quantize_input(norm(mel_db(x), rows, k % SEG == 0))   # 추론 요청의 x
                log[k, m] = ts, time.monotonic_ns(), cpu, i

    th = [threading.Thread(target=work, args=(i,)) for i in range(workers)]
    for t in th:
        t.start()
    for t in th:
        t.join()
    return log, groups


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--tracks', type=int, default=1024)
    ap.add_argument('--seconds', type=float, default=300.0)
    ap.add_argument('--workers', type=int, default=1, help='계산 thread 수(모델 m은 thread m %% workers)')
    ap.add_argument('--pin', default='', help='계산 thread를 고정할 CPU, 쉼표로(없으면 고정 안 함)')
    ap.add_argument('--load', type=int, default=0, help='CPU 부하 process 수(고정한 CPU는 피한다)')
    ap.add_argument('--wav', default=WAV, help="복제할 wav. ''면 합성 noise")
    ap.add_argument('--note', default='', help='<out>.json에 남길 설명(예: 기능 확인, 측정 아님)')
    ap.add_argument('--out', default='')
    a = ap.parse_args()
    assert 1 <= a.workers <= M and a.tracks >= 1
    pin = parse_cpus(a.pin)
    lc = f'load{a.load}'
    out = a.out or os.path.join(RESULT, f"m3_t{a.tracks}_w{a.workers}_pin{a.pin.replace(',', '-') or 'none'}_{lc}.csv.gz")
    f = open_out(out)
    wave, src = load_audio(a.wav)
    epochs = int(round(a.seconds * 1e9 / P_NS))
    for _ in range(20):                                            # FFT·BLAS 첫 호출을 측정 밖에서
        mel_db(np.zeros((a.tracks // M + 1, FRAME), np.float32))
    print(f'M3: {a.tracks}트랙, {epochs} epoch({a.seconds:g} s), thread {a.workers}, pin {pin or "없음"}, {lc}, 음성 {src}')
    with CpuLoad(a.load, pin):
        t0 = time.monotonic_ns() + 200_000_000
        log, groups = run(a.tracks, epochs, a.workers, pin, wave, t0)
    write_meta(out, test='M3', tracks=a.tracks, epochs=epochs, workers=a.workers, pin=pin, load=a.load, audio=src,
               t0_ns=t0, note=a.note, blas_threads=os.environ['OPENBLAS_NUM_THREADS'], numpy=np.__version__)
    fmt = '%d,%d,%d,%d,%d,%d,%d,%d,' + lc
    with f:
        f.write(COLS + '\n')
        for k in range(epochs):
            rows = [np.c_[np.full(g.size, k), g, np.full(g.size, m), np.full(g.size, t0 + k * P_NS + m * OFF_NS),
                          np.tile(log[k, m], (g.size, 1))] for m, g in enumerate(groups) if g.size]
            np.savetxt(f, np.concatenate(rows), fmt=fmt)
    tf = t0 + np.arange(epochs)[:, None] * P_NS + np.arange(M)[None, :] * OFF_NS
    ok = log[..., 0] >= 0
    for name, v in (('깨어남 지연(t_compute_start − t_frame)', log[..., 0] - tf), ('계산(t_ready − t_compute_start)', log[..., 1] - log[..., 0]),
                    ('준비 지연(t_ready − t_frame)', log[..., 1] - tf)):
        p = np.percentile(v[ok] / 1e3, [50, 99, 99.9])
        print(f'  {name}: p50 {p[0]:.1f} µs, p99 {p[1]:.1f} µs, p99.9 {p[2]:.1f} µs, 최대 {v[ok].max() / 1e3:.1f} µs')
    print(out)


if __name__ == '__main__':
    main()
