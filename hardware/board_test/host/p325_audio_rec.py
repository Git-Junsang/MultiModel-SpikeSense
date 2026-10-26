#!/usr/bin/env python3
"""p325_audio_rec.py — M1 오디오 frame 준비 지연, M2 sample-clock drift (P3.25)

USB mic 여러 개를 동시에 stream으로 받으며 block마다 Host clock(CLOCK_MONOTONIC) 도착 시각과 샘플 위치를 남긴다.
장치별 drift ppm, block 전달 지연, frame 준비 지연, xrun은 analyze_p325.py --m1이 구한다.
sounddevice(PortAudio)가 없거나 입력 장치가 없으면 BLOCKED_BY_HARDWARE를 내고 끝난다(종료 코드 2). 값은 만들지 않는다.

    python3 hardware/board_test/host/p325_audio_rec.py --list
    python3 hardware/board_test/host/p325_audio_rec.py --devices 3,5 --buffer-ms 1 --minutes 30             # idle
    python3 hardware/board_test/host/p325_audio_rec.py --devices 3,5 --buffer-ms 1 --minutes 30 --load 8    # CPU 부하
buffer 1·2·4·10 ms를 따로 돌린다. M2는 --minutes 60. USB mic가 16 kHz를 직접 못 하면 --rate 48000으로 hw 장치를 연다
(ALSA plug·PulseAudio가 resampling하면 장치 고유의 block 시각이 가려진다). 같은 clock의 다채널 장치는 --channels로 트랙을 늘린다.

Frame 자르기는 06_HOST_INTERFACE.md §2처럼 Host clock 기준이다. 트랙(장치의 channel 하나) t의 모델 m = t % 40이고,
frame k의 끝 시각은 T0 + m × 0.8 ms + k × 32 ms다(T0 = 녹음 시작, 모든 장치 공통이라 period k가 장치 사이에 맞는다).
이 시각을 샘플 번호로 바꿀 때 장치 clock을 nominal rate로 가정한다. drift가 있으면 frame 끝이 offset에서 점점 벗어난다(M2).
열(block 하나 × 트랙 하나가 한 줄, −1 = 값 없음):
  device_id, track_id, model_id, sample_index(block 마지막 샘플 번호), nominal_sample_time_ns(그 샘플의 nominal 수음 시각),
  host_block_arrival_ns(callback 진입 시각), frame_ready_ns(이 block에서 frame이 끝나면 block 처리를 마친 시각),
  period, frame_end_index(frame 마지막 샘플 번호), xrun(PortAudio input overflow), buffer_ms
nominal 수음 시각 = 첫 block 도착 − 첫 block 길이 + 샘플 번호 / rate. 첫 block의 지연만큼 어긋나므로 analyze_p325.py가
가장 빨리 온 block들로 수음 시각 직선을 다시 맞춘다(t_gen). ADC·USB 고정 지연은 이 방법으로 보이지 않는다(loopback 필요, 06 §5).
callback 안에서는 numpy 배열에 적기만 하고 파일은 녹음이 끝난 뒤 쓴다(파일 쓰기가 callback을 늦추지 않게).
"""
import argparse
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from p325_common import M, OFF_NS, P_NS, RESULT, SR, CpuLoad, blocked, open_out, write_meta  # noqa: E402

COLS = ('device_id,track_id,model_id,sample_index,nominal_sample_time_ns,host_block_arrival_ns,frame_ready_ns,'
        'period,frame_end_index,xrun,buffer_ms')


class Recorder:
    """block 기록. sounddevice callback이 block()을 부르고, test_p325.py는 합성 block으로 부른다"""

    def __init__(self, n_dev, channels, rate, buffer_ms, cap, T0):
        assert (rate * 32) % 1000 == 0 and 0 < buffer_ms < 32, 'hop 32 ms가 정수 샘플이어야 하고 block ≤ frame 끝 하나'
        self.rate, self.ch, self.buf, self.T0 = rate, channels, buffer_ms, T0
        self.frame = 2 * rate * 32 // 1000                          # 64 ms
        self.count, self.t0 = [0] * n_dev, [None] * n_dev           # 장치별 받은 샘플 수, 샘플 0의 nominal 수음 시각
        self.next = {}                                              # 트랙 → [period, frame 끝 샘플 번호]
        self.rows, self.n, self.now = np.full((cap, 11), -1, np.int64), 0, time.monotonic_ns

    def end(self, d, t, k):
        """트랙 t의 period k frame 끝(T0 + offset + k × 32 ms)에 마지막으로 수음한 샘플 번호(nominal rate)"""
        return (self.T0 + (t % M) * OFF_NS + k * P_NS - self.t0[d]) * self.rate // 10**9

    def block(self, d, frames, t, xrun):
        if self.t0[d] is None:
            self.t0[d] = t - frames * 10**9 // self.rate
            for c in range(self.ch):
                tr, k = d * self.ch + c, 0
                while self.end(d, tr, k) < self.frame - 1:         # 첫 frame은 1,024샘플이 다 있는 것부터
                    k += 1
                self.next[tr] = [k, self.end(d, tr, k)]
        last = self.count[d] + frames - 1
        self.count[d] += frames
        nom = self.t0[d] + last * 10**9 // self.rate
        for c in range(self.ch):
            tr = d * self.ch + c
            k, e = self.next[tr]
            ready = ek = ee = -1
            if e <= last:                                           # block ≤ 32 ms라 frame 끝은 많아야 하나
                ready, ek, ee = self.now(), k, e
                self.next[tr] = [k + 1, self.end(d, tr, k + 1)]
            if self.n < len(self.rows):
                self.rows[self.n] = d, tr, tr % M, last, nom, t, ready, ek, ee, xrun, self.buf
                self.n += 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--list', action='store_true', help='입력 장치 목록')
    ap.add_argument('--devices', default='', help='PortAudio 입력 장치 번호나 이름, 쉼표로. 순서 = device_id')
    ap.add_argument('--buffer-ms', type=int, default=1, help='callback block 길이 ms(1, 2, 4, 10)')
    ap.add_argument('--minutes', type=float, default=30.0)
    ap.add_argument('--rate', type=int, default=SR)
    ap.add_argument('--channels', type=int, default=1)
    ap.add_argument('--load', type=int, default=0, help='CPU 부하 process 수')
    ap.add_argument('--note', default='')
    ap.add_argument('--out', default='')
    a = ap.parse_args()
    try:
        import sounddevice as sd
    except (ImportError, OSError) as e:
        blocked(f'오디오 backend 없음 ({type(e).__name__}: {e}). /dev/snd {"있음" if os.path.exists("/dev/snd") else "없음"}',
                'pip install sounddevice, PortAudio(libportaudio2), USB mic 2개 이상(arecord -l로 확인)')
    ins = [(i, d) for i, d in enumerate(sd.query_devices()) if d['max_input_channels'] > 0]
    if a.list or not a.devices:
        for i, d in ins:
            print(f"[{i}] {d['name']}  입력 {d['max_input_channels']}ch, 기본 {d['default_samplerate']:.0f} Hz, "
                  f"hostapi {sd.query_hostapis(d['hostapi'])['name']}")
        if not ins:
            blocked('입력 장치 없음', 'USB mic 2개 이상(arecord -l로 확인)')
        if not a.list:
            sys.exit('--devices를 정한다(위 목록의 번호)')
        return
    devs = [int(x) if x.strip().isdigit() else x.strip() for x in a.devices.split(',')]
    info = []
    for x in devs:
        try:
            info.append(sd.query_devices(x, 'input'))
        except ValueError as e:
            blocked(f'입력 장치 {x!r} 없음 ({e})', 'USB mic 2개 이상(--list로 번호 확인)')
    if len(devs) < 2:
        print('주의: M1(장치 사이 jitter)은 장치 2개 이상이 필요하다. 이 녹음으로는 M2(drift)만 본다')
    bs = a.rate * a.buffer_ms // 1000
    lc = f'load{a.load}'
    out = a.out or os.path.join(RESULT, f'm1_buf{a.buffer_ms}_n{len(devs)}_{lc}.csv.gz')
    f = open_out(out)
    cap = int(len(devs) * a.channels * a.minutes * 60e3 / a.buffer_ms * 1.1) + 10_000
    rec = Recorder(len(devs), a.channels, a.rate, a.buffer_ms, cap, 0)

    def cb(d):
        def _cb(indata, frames, ti, status):
            rec.block(d, frames, time.monotonic_ns(), int(status.input_overflow))
        return _cb

    with CpuLoad(a.load):                                          # 부하 process를 stream보다 먼저 fork한다
        ss = [sd.InputStream(device=x, channels=a.channels, samplerate=a.rate, blocksize=bs, latency=a.buffer_ms / 1000,
                             dtype='int16', callback=cb(d)) for d, x in enumerate(devs)]
        dinfo = [dict(id=d, arg=x, name=i['name'], hostapi=sd.query_hostapis(i['hostapi'])['name'],
                      default_rate=i['default_samplerate'], device_delay_s=s.latency, blocksize=s.blocksize)
                 for d, (x, i, s) in enumerate(zip(devs, info, ss))]
        print(f'M1/M2: 장치 {len(devs)}개 × {a.channels}ch, {a.rate} Hz, block {bs} 샘플({a.buffer_ms} ms), '
              f'{a.minutes:g}분, {lc}. 실제 latency {[round(s.latency * 1e3, 2) for s in ss]} ms')
        rec.T0 = time.monotonic_ns()
        for s in ss:
            s.start()
        time.sleep(a.minutes * 60)                                  # callback은 PortAudio thread에서 돈다
        for s in ss:
            s.stop()
            s.close()
    write_meta(out, test='M1/M2', rate=a.rate, channels=a.channels, buffer_ms=a.buffer_ms, minutes=a.minutes, load=a.load,
               T0_ns=rec.T0, t0_ns=rec.t0, rows=rec.n, rows_dropped=max(0, sum(rec.count) // bs * a.channels - rec.n),
               devices=dinfo, sounddevice=sd.__version__, portaudio=sd.get_portaudio_version()[1], note=a.note)
    with f:
        f.write(COLS + '\n')
        np.savetxt(f, rec.rows[:rec.n], fmt='%d', delimiter=',')
    x = rec.rows[:rec.n]
    print(f'block {rec.n}줄, frame {(x[:, 6] >= 0).sum()}개, xrun block {(x[:, 9] > 0).sum()}개 → {out}')


if __name__ == '__main__':
    main()
