#!/usr/bin/env python3
"""demo.py — P6.4 USB mic demo. 스피커 2대 소리를 mic 2개로 받는 트랙 0·1과 가상 트랙 1,022개의 판정을 ssh 화면 하나에 보인다

구성(06 §2 mic + wav 입력): 트랙 i(0, 1) = mic MICS[i] ← 그 옆 스피커(--speaker i번째, PipeWire node 이름),
트랙 2–1,023 = 가상 트랙(Host가 wav를 반복해 읽는다). 모델은 트랙 0 pump_id04, 트랙 1 slider_id04, 트랙 i(≥ 2)는 i % 40.
스피커는 5 s마다 세트를 바꾼다: (정상, 이상) → (정상, 정상) → (이상, 이상) → 처음부터. 스피커 i는 speaker<i>.wav(트랙 i 소리)를 낸다.
보정: run은 mmss_host를 띄우기 전에 스피커마다 잡음 burst를 재생하고 그 트랙의 mic로 녹음해, pw-play 시작 → mic 도착 지연을 잰다
  (상관 최대, 2번 평균). 상관이 0.05 아래면 mic에 스피커 소리가 들리지 않는 것으로 보고 멈춘다.
리셋: 판정 하나는 소리 1.024 s(frame 31개)로 정한다. 세트가 바뀌면 트랙 0·1 판정을 지우고, 소리 구간이 새 세트 안에 다 든 판정만 보인다.
  판정 줄을 받은 시각 t의 소리 구간은 [t − WIN_S, t]로 본다. 세트 시작 = pw-play 시작 + 잰 지연 + 5 s × 세트 번호.
화면(영문)은 0.2 s마다 새로 그린다(누적 없음). 트랙 0·1은 줄마다 장비, 들려주는 소리, 추론, 맞음·틀림. 가상 트랙은 한 칸이 한 트랙:
  o 정상 추론, x 이상 추론, 초록 맞음, 빨강 틀림, · 아직 없음. 가상 트랙도 판정의 소리부터 지금까지 정상↔이상이 바뀌지 않은 판정만 보인다.
  판정은 모든 트랙이 0.992 s마다 31 ms 안에 끝나므로(offset 40개가 32 ms 안) 갱신은 거의 함께 일어난다. 트랙마다 다른 것은 소리가 바뀌는 시각이다.
트랙 0·1 판정은 모두 mic_judge.csv에 남긴다(받은 시각, 트랙, 판정, P(이상), 재생 중인 소리, 세트 안 판정인지).

speaker0.wav, speaker1.wav: 세트 3개 × 5 s, 16 kHz mono(트랙 0, 1). 소리는 장비 test 파일의 앞 5 s다. Python 기준(mel + TrackNorm + snn_int8)이
  파일 하나로 맞힌 여유가 큰 정상·이상 파일 8개씩에서, 세트 순서대로 3바퀴 이어 넣었을 때 세트 안 판정의 여유 최소가 가장 큰 쌍을 골랐다.
  고른 쌍으로 세트 안 판정이 모두 맞는지 확인한다(assert). 공기 중 전달(스피커 → mic)은 확인하지 않는다.
virtual.wav: 160채널 50 s. 채널 c = 모델 (c + 2) % 40 장비 소리로, 정상 45 s(90%) 사이 채널마다 다른 위치에 이상 5 s(10%)를 넣었다.
  트랙 i(≥ 2)는 채널 (i − 2) % 160을 (i − 2) × VSTEP 샘플 늦춰 읽어 자기 모델 장비의 소리를 듣는다. 채널 하나를 트랙 6–7개가 같이
  쓰지만 위상이 달라 같은 소리를 동시에 듣지 않는다(mmss_host run.c). 정상·이상 파일은
  test 파일 앞 60·30개 가운데 Python 기준 판정의 여유가 큰 것이다. 이상 위치는 virtual_labels.json(화면의 정답).

  개발 서버: python3 software/host/demo.py prep     → software/dataset/demo/{speaker0·1.wav, virtual.wav, virtual_labels.json, map.txt}
  Pi 작업 폴더(저장소 root와 같은 상대 경로)에 software/host/{build/mmss_host, demo.py}, software/dataset/demo/,
    hardware/data/models_l64/{models.ddr3.bin, manifest.json}, pi_group.csv(p316_meas/result/pi_group_pin3_performance_load0.csv.gz를 푼 것)
  Pi:        python3 software/host/demo.py run --speaker <트랙 0 스피커> [--speaker <트랙 1 스피커>]   (Ctrl-C로 멈춘다)
             스피커 = `wpctl status`의 node 이름(wpctl inspect <번호> | grep node.name). 스피커가 없는 트랙은 '-'.
"""
import argparse
import json
import math
import os
import pty
import signal
import subprocess
import sys
import threading
import time
import wave

UNITS = ('pump_id04', 'slider_id04')          # 트랙 0, 1의 장비(모델). ToyCar_id04는 이어 들을 때 세트 안 판정 36개 중 6개가 틀려 뺐다
MICS = ('Microphone', 'Microphone_1')         # 트랙 0, 1의 ALSA card 이름
SETS = ((0, 1), (0, 0), (1, 1))               # 세트마다 (트랙 0, 트랙 1). 0 정상, 1 이상
SET_S = 5.0
WIN_S = 1.024 + 0.05   # 판정 하나의 소리 길이(512 × 30 + 1,024샘플) + mic·USB·결과 지연과 재생 지연 흔들림(Bluetooth ±12 ms) 여유
VIRT_C, VIRT_LOOP_S, VIRT_ABN_S = 160, 50.0, 5.0   # virtual.wav 채널 수(40의 배수: 채널 하나 = 모델 하나), 반복 길이, 그 안의 이상 길이(10%)
VMARGIN_S = 0.3        # 가상 트랙 판정의 소리가 정상↔이상 경계 ± 0.3 s에 걸치면 지운다
VSTEP = 104729         # mmss_host run.c VSTEP: 가상 트랙 i는 virtual.wav를 (i − 2) × VSTEP 샘플(mod 길이) 늦춰 읽는다
V0_LAG_S = 0.1         # shortcut: 가상 트랙 샘플 0 = mmss_host 시작 + 0.1 s로 어림(mic 열기). 어긋나면 경계 근처가 틀린 것처럼 보인다
SR, HOP, FRAME, SEG, N, M = 16000, 512, 1024, 31, 1024, 40
LABEL = ('normal', 'abnormal')
ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
DEMO, BIN = 'software/dataset/demo', 'software/host/build/mmss_host'
MAP, MANIFEST = DEMO + '/map.txt', 'hardware/data/models_l64/manifest.json'


def prep():
    import numpy as np
    import soundfile as sf
    sys.path[:0] = [os.path.join(ROOT, 'hardware', 'board_test', 'host')]
    import p325_mel_load as ml  # noqa: E402  (software/dataset, software/model 경로도 넣는다)
    import dcase_data as dd
    import snn_fp32
    import snn_int8 as si
    man = json.load(open(os.path.join(ROOT, MANIFEST)))['models']
    mid = {x['unit']: x['model_id'] for x in man}
    q = {m: si.quantize(snn_fp32.load_params(os.path.join(ROOT, man[m]['checkpoint']))) for m in (mid[u] for u in UNITS)}
    L = int(SET_S * SR)

    def files(unit, d):                       # test 파일 중 라벨 d(0 정상, 1 이상). 평가용 ID는 eval_data_list.csv 라벨
        p, lab = dd.list_files(*unit.split('_id'), 'test')
        return [f for f, y in zip(p, lab) if y == d]

    def judge(m, w):
        """소리 w → 판정마다 (첫 샘플, 끝 샘플, z). z = (Σout1 − Σout0) / 31 × scale, 양수면 이상(run.c judge와 같다). 정규화는 이어 간다"""
        off = (m * HOP + M // 2) // M
        nk = (w.size - off - FRAME) // HOP + 1
        nk -= nk % SEG
        db = ml.mel_db(np.stack([w[off + HOP * k: off + HOP * k + FRAME] for k in range(nk)]).astype(np.float32))
        norm = ml.TrackNorm(1)
        x = np.stack([si.quantize_input(norm(db[k:k + 1], np.array([0])))[0] for k in range(nk)])
        out = si.forward(q[m], x.reshape(-1, SEG, 40).astype(np.int64), store_bits=12)
        c = np.arange(nk // SEG)
        return off + HOP * SEG * c, off + HOP * (SEG * c + SEG - 1) + FRAME, (out[..., 1] - out[..., 0]).sum(1) / SEG * man[m]['weight_scales'][3]

    def stream(t, w):
        """트랙 t가 세트 순서대로 3바퀴 들을 소리 → (판정마다 여유 = 정답 쪽 z, 세트 안에 다 든 판정인지)"""
        a, b, z = judge(mid[UNITS[t]], np.tile(np.concatenate([w[s[t]] for s in SETS]), 3))
        want = np.array([SETS[(x // L) % len(SETS)][t] for x in a])
        return np.where(want == 1, z, -z), a // L == (b - 1) // L

    clip = {}
    for t, u in enumerate(UNITS):             # 파일 하나로 본 여유 상위 8개씩에서, 이어 들을 때 세트 안 여유 최소가 가장 큰 쌍
        top = []
        for d in (0, 1):
            w = {f: dd.read_wave(f)[:L] for f in files(u, d)}
            top.append(sorted(w.items(), key=lambda x: -((1 if d else -1) * judge(mid[u], x[1])[2]).min())[:8])
        best = max(((n, an) for n in top[0] for an in top[1]), key=lambda p: (lambda g, i: g[i].min())(*stream(t, (p[0][1], p[1][1]))))
        clip[t, 0], clip[t, 1] = best[0][1], best[1][1]
        print(f'트랙 {t} {u}: normal {os.path.basename(best[0][0])}, abnormal {os.path.basename(best[1][0])}')

    rnd = np.stack([np.concatenate([clip[t, s[t]] for s in SETS]) for t in (0, 1)], 1)
    ok = True
    for t, u in enumerate(UNITS):             # 세트 안에 다 든 판정이 모두 맞는지
        g, inside = stream(t, (clip[t, 0], clip[t, 1]))
        ok &= bool((g[inside] > 0).all())
        print(f'트랙 {t} {u}: 판정 {g.size}개, 세트 안 {inside.sum()}개 중 맞음 {(g[inside] > 0).sum()}개(여유 최소 {g[inside].min():.2f}), '
              f'경계에 걸친 {(~inside).sum()}개(화면에서 버림) 중 맞음 {(g[~inside] > 0).sum()}개')
    assert ok, '세트 안 판정이 틀렸다. UNITS를 바꾼다'

    os.makedirs(os.path.join(ROOT, DEMO), exist_ok=True)
    for t in (0, 1):
        sf.write(os.path.join(ROOT, DEMO, f'speaker{t}.wav'), rnd[:, t], SR, subtype='PCM_16')
    # 가상 트랙: 채널 c = 모델 (c + 2) % 40(VIRT_C는 40의 배수). 채널마다 VIRT_LOOP_S 중 정상 90%, 이상 VIRT_ABN_S(10%)를 채널마다 다른 위치에.
    # 정상은 앞 60개 파일 가운데 10 s 판정의 여유(−z 최대)가 큰 것, 이상은 앞 30개 가운데 5 s 판정의 여유(z 최소)가 큰 것
    LV, AV, K = int(VIRT_LOOP_S * SR), int(VIRT_ABN_S * SR), VIRT_C // M
    rng = np.random.default_rng(7)
    virt, starts = np.zeros((LV, VIRT_C), np.float32), [0.0] * VIRT_C
    for m in range(M):
        u = man[m]['unit']
        q.setdefault(m, si.quantize(snn_fp32.load_params(os.path.join(ROOT, man[m]['checkpoint']))))
        nw = [dd.read_wave(f)[:10 * SR] for f in files(u, 0)[:60]]
        aw = [dd.read_wave(f)[:AV] for f in files(u, 1)[:30]]
        nw = [nw[i] for i in np.argsort([-(judge(m, w)[2].max()) for w in nw])[::-1]]
        aw = [aw[i] for i in np.argsort([judge(m, w)[2].min() for w in aw])[::-1]]
        for j in range(K):
            c = (m - 2) % M + M * j
            nrm = np.concatenate([nw[(5 * j + n) % len(nw)] for n in range(5)])[:LV - AV]
            a = int(rng.integers(0, LV - AV + 1))
            virt[:, c], starts[c] = np.concatenate([nrm[:a], aw[j % len(aw)], nrm[a:]]), a / SR
        print(f'가상 채널 모델 {m} {u}: 정상 파일 {min(5 * K, len(nw))}개, 이상 파일 {min(K, len(aw))}개', flush=True)
    hit = np.zeros((2, 2), int)                # [정답, 맞음?] 판정 수: 2바퀴 이어 넣은 Python 기준, 정상·이상이 바뀌는 판정은 뺀다
    for c in range(VIRT_C):
        a, b, z = judge((c + 2) % M, np.tile(virt[:, c], 2).astype(np.float64))
        s0 = int(starts[c] * SR)
        for x, y, zz in zip(a, b, z):
            ab = [(s0 + n * LV, s0 + AV + n * LV) for n in range(3)]
            lab = 1 if any(lo <= x and y <= hi for lo, hi in ab) else 0 if all(y <= lo or x >= hi for lo, hi in ab) else None
            if lab is not None:
                hit[lab, int((zz > 0) == lab)] += 1
    print(f'가상 트랙 Python 기준: 정상 판정 {hit[0].sum()}개 중 맞음 {hit[0, 1]}개, 이상 판정 {hit[1].sum()}개 중 맞음 {hit[1, 1]}개')
    sf.write(os.path.join(ROOT, DEMO, 'virtual.wav'), virt, SR, subtype='PCM_16')
    json.dump({'loop_s': VIRT_LOOP_S, 'abn_s': VIRT_ABN_S, 'abn_start_s': starts}, open(os.path.join(ROOT, DEMO, 'virtual_labels.json'), 'w'))
    with open(os.path.join(ROOT, MAP), 'w') as f:
        f.writelines(f'{mid[UNITS[i]] if i < 2 else i % M}\n' for i in range(N))
    print(f'→ {DEMO}/speaker0·1.wav {rnd.shape[0] / SR:.0f} s, virtual.wav {virt.shape[1]}채널 {virt.shape[0] / SR:.0f} s, map.txt {N}트랙')


def calib(node, mic):
    """스피커 node에 잡음 burst 0.5 s를 재생하고 mic로 녹음해 (pw-play 시작 → mic 도착 지연 s 평균, 상관 최소, 지연들)을 낸다.
    3번 재고 첫 번은 버린다: 쉬던 Bluetooth 스피커는 첫 재생이 늦게 나와 3 s 녹음 창을 넘긴다(2026-11-16 Anker, 상관 0.01)"""
    import numpy as np
    rate, path, lat, cor = 48000, DEMO + '/burst.wav', [], []
    n = np.arange(101) - 50                   # 6 kHz 아래로 거른 잡음: Bluetooth 통화 profile(mSBC 16 kHz)도 다 전한다
    b = np.convolve(np.random.default_rng(1).standard_normal(rate // 2), np.sinc(2 * 6000 / rate * n) * np.hanning(101), 'same')
    b = np.clip(0.25 * b / b.std(), -1, 1)
    with wave.open(path, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((b * 32767).astype('<i2').tobytes())
    for trial in range(3):
        rec = subprocess.Popen(['arecord', '-q', '-D', f'hw:CARD={mic}', '-f', 'S16_LE', '-r', str(rate), '-c', '1', '-t', 'raw',
                                '--period-time=4000', '--buffer-time=16000', '-d', '3'], stdout=subprocess.PIPE)
        buf, t0, pl = bytearray(), float('inf'), None
        while d := os.read(rec.stdout.fileno(), 4096):
            buf += d
            t0 = min(t0, time.monotonic() - len(buf) / 2 / rate)       # 샘플 0의 도착 시각(읽기가 늦은 만큼 커지므로 최솟값)
            if pl is None and len(buf) >= 2 * rate * 0.8:              # 0.8 s 녹음한 뒤 재생
                pl, tp = start(node, path)
                pl, tp = pl or False, tp or 0.0                         # 5번 실패: 상관이 0 근처로 나와 run이 멈춘다
        rec.wait()
        if pl:
            pl.wait()
        x = np.frombuffer(bytes(buf), '<i2') / 32768
        n = 1 << int(np.ceil(np.log2(x.size + b.size)))
        c = np.fft.irfft(np.fft.rfft(x, n) * np.conj(np.fft.rfft(b, n)), n)[:x.size - b.size]
        e = np.concatenate([[0], np.cumsum(x * x)])
        r = c / (np.sqrt((e[b.size:b.size + c.size] - e[:c.size]) * (b @ b)) + 1e-12)   # 정규화 상관
        k = int(np.argmax(r))
        if trial:
            lat.append(t0 + k / rate - tp)
            cor.append(float(r[k]))
        time.sleep(0.3)
    return sum(lat) / len(lat), min(cor), lat


def start(node, path):
    """path를 스피커 node로 재생한다 → (Popen, 시작 시각). dont-fallback: 다른 스피커로 새지 않게.
    WirePlumber가 있는 node를 가끔 못 찾는다(defined target not found, 2026-11-16 BSL110). 0.3 s 안에 끝나면 다시 한다.
    그보다 늦게 실패하는 것은 run이 재생이 끝난 것을 보고 다시 튼다. 5번 실패하면 (None, None)"""
    for _ in range(5):
        t = time.monotonic()
        x = subprocess.Popen(['pw-play', '--target', node, '-P', '{ node.dont-fallback = true }', path],
                             stderr=open(DEMO + '/play.log', 'a'))
        try:
            x.wait(0.3)
        except subprocess.TimeoutExpired:
            return x, t
        time.sleep(0.2)
    return None, None


def at(sched, i, t):
    """트랙 i의 시각 t → (세트 번호, 그 세트 소리가 mic에 오기 시작한 시각). 스피커가 없으면 (None, None)"""
    if sched[i] is None:
        return None, None
    k = min(max(int((t - sched[i]) // SET_S), 0), len(SETS) - 1)
    return k, sched[i] + k * SET_S


def inside(t, a):
    """시각 t에 받은 판정의 소리 [t − WIN_S, t]가 a에서 시작한 세트 안에 다 드는가"""
    return a <= t - WIN_S and t <= a + SET_S


def read(fd, last, sched, log):
    """mmss_host stdout(track_id,cycle,model_id,decision,score) → last[트랙] = (받은 시각, decision, score). 트랙 0·1은 log에도 쓴다"""
    with os.fdopen(fd, 'r', errors='replace') as f:
        try:
            for line in f:
                p = line.split(',')
                if len(p) == 5 and p[0].isdigit():
                    tr, t = int(p[0]), time.monotonic()
                    last[tr] = (t, int(p[3]), float(p[4]))
                    if tr < 2:
                        k, a = at(sched, tr, t)
                        log.write(f'{t:.3f},{tr},{p[1]},{p[3]},{p[4].strip()},'
                                  + (f'{k + 1},{SETS[k][tr]},{int(inside(t, a))}\n' if k is not None else ',,\n'))
                        log.flush()
        except OSError:                       # mmss_host가 끝나면 pty read가 EIO
            pass


def vsound(V, c, u0, u1):
    """가상 채널 c가 mic 시작 뒤 [u0, u1] s 동안 들려준 소리(0 정상, 1 이상). 그 사이에 정상↔이상이 바뀌면 None"""
    L, A, a = V['loop_s'], V['abn_s'], V['abn_start_s'][c]
    for b in (a, a + A):                      # 경계 b + nL이 [u0, u1] 안에 있는가
        if math.ceil((u0 - b) / L) * L + b <= u1:
            return None
    return int(a <= u0 % L < a + A)


def draw(now, sched, last, pl, lost, t_v0, V):
    G, R, D, E = '\033[32m', '\033[31m', '\033[2m', '\033[0m'
    cell = lambda x, act: D + '·' + E if x is None else ('x' if x[1] else 'o') if act is None else (G if x[1] == act else R) + ('x' if x[1] else 'o') + E  # noqa: E731
    r = list(last)
    ks = [at(sched, i, now) for i in (0, 1)]
    act = [SETS[ks[i][0]][i] if ks[i][0] is not None else None for i in (0, 1)]
    for i in (0, 1):                          # 리셋: 소리 구간이 지금 세트 안에 다 들지 않은 판정은 지운다
        if r[i] and ks[i][0] is not None and not inside(r[i][0], ks[i][1]):
            r[i] = None
    C, LV = len(V['abn_start_s']), int(V['loop_s'] * SR)
    for i in range(2, N):                     # 가상 트랙도 트랙마다: 판정의 소리부터 지금까지 정상↔이상이 바뀌지 않은 판정만 보인다
        c, d = (i - 2) % C, (i - 2) * VSTEP % LV / SR - t_v0   # d: 트랙의 늦춤 − 샘플 0 시각 → virtual.wav 위치 = 시각 + d
        act.append(vsound(V, c, now + d, now + d))
        if r[i] and vsound(V, c, r[i][0] + d - WIN_S - VMARGIN_S, max(now, r[i][0] + VMARGIN_S) + d) is None:
            r[i] = None
    word = lambda d: LABEL[d].upper() if d is not None else '-'  # noqa: E731
    j = 0 if ks[0][0] is not None else 1      # 머리말의 세트·경과 시간은 스피커가 있는 첫 트랙 기준
    err = ''.join(f'   {R}pw-play exit {x.returncode} ({DEMO}/play.log){E}' for x in pl if x.returncode)
    err += ''.join(f'   {R}track {i} speaker lost{E}' for i in lost)
    head = (f'speakers: set {ks[j][0] + 1}/{len(SETS)} (5 s each)   {max(now - ks[j][1], 0):.1f} s' if ks[j][0] is not None else 'no speaker')
    out = [f'MultiModel-SpikeSense   {N:,} tracks / {M} SNN models / 1 FPGA', head + err]
    for i in (0, 1):
        x = r[i]
        res = '' if x is None or act[i] is None else f'{G}CORRECT{E}' if x[1] == act[i] else f'{R}WRONG{E}'
        out.append(f'Track {i}  mic  {UNITS[i].replace("_id", " id"):<12} playing {word(act[i]):<8}  inferred '
                   + (f'{word(x[1]):<8}  p={x[2]:.2f}  {res}' if x else 'waiting'))
    v = [x[1] == act[i] for i, x in enumerate(r) if i >= 2 and x]
    nab = sum(act[2:])
    out += [f'Tracks 2-{N - 1}  software (virtual):  playing {N - 2 - nab} NORMAL / {nab} ABNORMAL',
            f'  inferred:  {G}correct {sum(v)}{E} / {len(v)}   {R}wrong {len(v) - sum(v)}{E}   waiting {N - 2 - len(v)}',
            f'o inferred normal   x inferred abnormal   {G}green{E} = correct   {R}red{E} = wrong   {D}·{E} waiting', '']
    for row in range(0, N, 64):
        out.append(f'{row:5} ' + ' '.join(''.join(cell(r[i], act[i]) for i in range(j, j + 8)) for j in range(row, row + 64, 8)))
    sys.stdout.write('\033[H' + '\n'.join(x + '\033[K' for x in out) + '\033[J')
    sys.stdout.flush()


def run(a):
    os.chdir(ROOT)
    host = lambda *x: subprocess.run([BIN, *x]).returncode  # noqa: E731
    host('stop')                              # 앞 실행이 남아 있으면 멈춘다
    if host('setup', '--map', MAP, '--models', 'hardware/data/models_l64/models.ddr3.bin',
            '--model-group-delay-trace', 'pi_group.csv', '--jitter-us', '0'):
        sys.exit('setup failed')
    spk = [None, None]                        # 트랙마다 (스피커 node, 잰 지연 s)
    for i, node in enumerate((a.speaker or [])[:2]):
        if node == '-':
            continue
        lat, cor, each = calib(node, MICS[i])
        print(f'track {i}: {node} -> mic {MICS[i]}  latency {lat * 1e3:.0f} ms ({", ".join(f"{x * 1e3:.0f}" for x in each)}), corr {cor:.2f}')
        if cor < 0.05:
            sys.exit(f'track {i}: mic {MICS[i]} does not hear the speaker (corr {cor:.2f}). Check speaker connection, volume, position')
        spk[i] = (node, lat)
    mfd, sfd = pty.openpty()                  # tty면 mmss_host가 판정을 줄마다 낸다. pipe면 4 KiB씩 모여 늦게 온다
    p = subprocess.Popen([BIN, 'run', '--map', MAP, '--mic', ','.join(MICS), '--in', DEMO + '/virtual.wav', '--cpu', '3'],
                         stdout=sfd, stderr=open(DEMO + '/run.log', 'w'))
    t_v0 = time.monotonic() + V0_LAG_S        # 가상 트랙은 mic 0 block마다 64샘플씩 읽으므로 virtual.wav 위치 = mic 시작 뒤 시간
    V = json.load(open(DEMO + '/virtual_labels.json'))
    os.close(sfd)
    last, sched, log = [None] * N, [None, None], open(DEMO + '/mic_judge.csv', 'w')
    log.write('t_recv_s,track_id,cycle,decision,score,set,played,inside\n')
    threading.Thread(target=read, args=(mfd, last, sched, log), daemon=True).start()
    pl, t_try = [None, None], [0.0, 0.0]      # 트랙마다 재생 중인 pw-play, 다시 틀 수 있는 시각
    sys.stdout.write('\033[?1049h\033[?25l')  # 다른 화면에 그리고 끝나면 원래 화면으로
    try:
        while p.poll() is None:
            now = time.monotonic()
            for i, s in enumerate(spk):           # 트랙마다 따로 15 s 바퀴를 돈다. 끝나거나 실패해 멈추면 바로 다시 튼다
                if s and (pl[i] is None or pl[i].poll() is not None) and now >= t_try[i]:
                    nodes = subprocess.run(['pw-cli', 'ls', 'Node'], capture_output=True, text=True).stdout
                    x, t = start(s[0], f'{DEMO}/speaker{i}.wav') if f'node.name = "{s[0]}"' in nodes else (None, None)
                    pl[i], sched[i], t_try[i] = x, (t + s[1] if x else None), now + 2   # 세트 시각 = 실제 시작 + 잰 지연. 못 틀면 2 s 뒤
            lost = [i for i, s in enumerate(spk) if s and sched[i] is None]
            draw(now, sched, last, [x for x in pl if x], lost, t_v0, V)
            time.sleep(0.2)
    except KeyboardInterrupt:                 # Ctrl-C는 mmss_host·pw-play에도 간다. mmss_host는 summary를 쓰고 끝난다
        pass
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)   # Ctrl-C를 또 눌러도 mmss_host stop까지 마친다
        sys.stdout.write('\033[?25h\033[?1049l')
        sys.stdout.flush()
        for x in pl + [p]:
            if x and x.poll() is None:
                x.terminate()
        p.wait()
        host('stop')
        print(open(DEMO + '/run.log').read()[-1500:])


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('prep', help='개발 서버: demo wav와 map을 만든다')
    r = sub.add_parser('run', help='Pi: setup, run, 재생, 화면')
    r.add_argument('--speaker', action='append', help='트랙 0, 1 순서로 스피커 PipeWire node 이름. 없는 트랙은 -')
    a = ap.parse_args()
    prep() if a.cmd == 'prep' else run(a)
