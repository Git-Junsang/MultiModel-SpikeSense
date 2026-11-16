#!/usr/bin/env python3
"""p316_alsa_rec.py — USB mic 여러 개를 ALSA로 직접 받아 block 도착 시각, ALSA timestamp, xrun을 기록한다 (P3.16 측정 3)

p325_audio_rec.py와 같은 기록(Recorder, 같은 열, 같은 <out>.json)을 남겨 analyze_p325.py --m1로 drift·block 전달 지연·
frame 준비 지연·xrun을 구한다. 다른 점은 backend다. PortAudio(sounddevice) 대신 libasound.so.2를 ctypes로 부른다
(라즈베리파이에 PortAudio가 없고 설치에 root가 필요하다). 장치마다 thread 하나가 snd_pcm_readi로 period 하나씩 읽는다.
추가로 <out>_alsa.csv.gz에 read마다 ALSA status를 남긴다:
  device_id, sample_index(이번 block 마지막 샘플 번호), t_ret_ns(readi가 돌아온 CLOCK_MONOTONIC),
  htstamp_ns(마지막 hw pointer 갱신 시각, CLOCK_MONOTONIC), avail(read 뒤 buffer에 남은 frame), xrun
htstamp 시점까지 들어온 샘플 수는 sample_index + 1 + avail이다. ADC·USB 고정 지연은 이 방법으로 보이지 않는다(loopback 필요).

    python3 p316_alsa_rec.py --devices hw:CARD=Microphone,hw:CARD=Microphone_1 --rate 48000 --buffer-ms 4 --minutes 5 --out run/x.csv.gz
"""
import argparse
import ctypes as C
import os
import sys
import threading
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from p325_audio_rec import COLS, Recorder  # noqa: E402
from p325_common import CpuLoad, open_out, write_meta  # noqa: E402

A = C.CDLL('libasound.so.2')
A.snd_pcm_readi.restype = C.c_long
A.snd_pcm_status_get_avail.restype = C.c_ulong
A.snd_strerror.restype = C.c_char_p
CAPTURE, ACCESS_RW_INTERLEAVED, FORMAT_S16_LE, TSTAMP_ENABLE, TSTAMP_MONOTONIC, EPIPE = 1, 3, 2, 1, 1, 32


class Timespec(C.Structure):
    _fields_ = [('tv_sec', C.c_long), ('tv_nsec', C.c_long)]


def ck(rc, what):
    if rc < 0:
        sys.exit(f'{what}: {A.snd_strerror(rc).decode()}')
    return rc


def open_pcm(name, rate, period, periods):
    """capture PCM을 열고 period·buffer를 맞춘다. ALSA timestamp는 CLOCK_MONOTONIC"""
    pcm, hw, sw = C.c_void_p(), C.c_void_p(), C.c_void_p()
    ck(A.snd_pcm_open(C.byref(pcm), name.encode(), CAPTURE, 0), f'{name} open')
    A.snd_pcm_hw_params_malloc(C.byref(hw))
    ck(A.snd_pcm_hw_params_any(pcm, hw), 'hw any')
    ck(A.snd_pcm_hw_params_set_access(pcm, hw, ACCESS_RW_INTERLEAVED), 'access')
    ck(A.snd_pcm_hw_params_set_format(pcm, hw, FORMAT_S16_LE), 'format S16_LE')
    ck(A.snd_pcm_hw_params_set_channels(pcm, hw, 1), 'channels 1')
    ck(A.snd_pcm_hw_params_set_rate(pcm, hw, rate, 0), f'rate {rate}')
    ck(A.snd_pcm_hw_params_set_period_size(pcm, hw, C.c_ulong(period), 0), f'period {period}')
    ck(A.snd_pcm_hw_params_set_periods(pcm, hw, periods, 0), f'periods {periods}')
    ck(A.snd_pcm_hw_params(pcm, hw), 'hw params')
    p, b = C.c_ulong(), C.c_ulong()
    A.snd_pcm_hw_params_get_period_size(hw, C.byref(p), None)
    A.snd_pcm_hw_params_get_buffer_size(hw, C.byref(b))
    A.snd_pcm_sw_params_malloc(C.byref(sw))
    ck(A.snd_pcm_sw_params_current(pcm, sw), 'sw current')
    ck(A.snd_pcm_sw_params_set_tstamp_mode(pcm, sw, TSTAMP_ENABLE), 'tstamp mode')
    ck(A.snd_pcm_sw_params_set_tstamp_type(pcm, sw, TSTAMP_MONOTONIC), 'tstamp type')
    ck(A.snd_pcm_sw_params(pcm, sw), 'sw params')
    return pcm, p.value, b.value


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--devices', required=True, help='ALSA 장치, 쉼표로. 순서 = device_id (예: hw:CARD=Microphone)')
    ap.add_argument('--rate', type=int, default=48000)
    ap.add_argument('--buffer-ms', type=int, default=4, help='period(한 번에 읽는 block) 길이 ms')
    ap.add_argument('--periods', type=int, default=4, help='ALSA buffer = period × periods')
    ap.add_argument('--minutes', type=float, default=5.0)
    ap.add_argument('--load', type=int, default=0, help='CPU 부하 process 수')
    ap.add_argument('--note', default='')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    devs = [x.strip() for x in a.devices.split(',')]
    B = a.rate * a.buffer_ms // 1000
    f, fa = open_out(a.out), open_out(a.out.replace('.csv', '_alsa.csv'))
    cap = int(len(devs) * a.minutes * 60e3 / a.buffer_ms * 1.1) + 10_000
    rec = Recorder(len(devs), 1, a.rate, a.buffer_ms, cap, 0)
    alsa, na, lock = np.full((cap, 6), -1, np.int64), [0], threading.Lock()
    with CpuLoad(a.load):                                          # 부하 process를 thread보다 먼저 fork한다
        pcms = [open_pcm(x, a.rate, B, a.periods) for x in devs]
        for x, (_, p, b) in zip(devs, pcms):
            if p != B:
                sys.exit(f'{x}: period {p} 샘플(요청 {B})')
        stop = time.monotonic_ns() + int(a.minutes * 60e9)

        def run(d, pcm):
            buf, st, ts, xr = C.create_string_buffer(2 * B), C.c_void_p(), Timespec(), 0
            A.snd_pcm_status_malloc(C.byref(st))
            while time.monotonic_ns() < stop:
                n = A.snd_pcm_readi(pcm, buf, C.c_ulong(B))            # ctypes는 호출 동안 GIL을 놓는다
                t = time.monotonic_ns()
                if n == -EPIPE:                                        # overrun: 샘플이 빠졌다. 다음 block에 xrun을 단다
                    xr = 1
                    ck(A.snd_pcm_recover(pcm, n, 1), 'recover')
                    continue
                ck(n, 'readi')
                A.snd_pcm_status(pcm, st)
                A.snd_pcm_status_get_htstamp(st, C.byref(ts))
                av = A.snd_pcm_status_get_avail(st)
                with lock:
                    rec.block(d, n, t, xr)
                    if na[0] < cap:
                        alsa[na[0]] = d, rec.count[d] - 1, t, ts.tv_sec * 10**9 + ts.tv_nsec, av, xr
                        na[0] += 1
                xr = 0

        th = [threading.Thread(target=run, args=(d, p[0])) for d, p in enumerate(pcms)]
        rec.T0 = time.monotonic_ns()
        for x in th:
            x.start()
        for x in th:
            x.join()
        for pcm, _, _ in pcms:
            A.snd_pcm_close(pcm)
    x = alsa[:na[0]]
    lag = x[:, 2] - x[:, 3]
    assert 0 <= np.median(lag) < 1e9, f'ALSA timestamp가 CLOCK_MONOTONIC이 아니다(t_ret − htstamp 중앙값 {np.median(lag)} ns)'
    dinfo = [dict(id=d, arg=n, name=n, hostapi='ALSA direct', device_delay_s=b / a.rate, blocksize=p, buffer_frames=b)
             for d, (n, (_, p, b)) in enumerate(zip(devs, pcms))]
    write_meta(a.out, test='M1/M2 ALSA', rate=a.rate, channels=1, buffer_ms=a.buffer_ms, periods=a.periods, minutes=a.minutes,
               load=a.load, T0_ns=rec.T0, t0_ns=rec.t0, rows=rec.n, devices=dinfo, alsa_rows=int(na[0]), note=a.note)
    with f:
        f.write(COLS + '\n')
        np.savetxt(f, rec.rows[:rec.n], fmt='%d', delimiter=',')
    with fa:
        fa.write('device_id,sample_index,t_ret_ns,htstamp_ns,avail,xrun\n')
        np.savetxt(fa, x, fmt='%d', delimiter=',')
    r = rec.rows[:rec.n]
    print(f'block {rec.n}줄, frame {(r[:, 6] >= 0).sum()}개, xrun block {(r[:, 9] > 0).sum()}개, '
          f't_ret − htstamp p50 {np.median(lag) / 1e3:.0f} µs, max {lag.max() / 1e3:.0f} µs → {a.out}')


if __name__ == '__main__':
    main()
