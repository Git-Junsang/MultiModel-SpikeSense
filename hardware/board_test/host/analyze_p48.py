#!/usr/bin/env python3
"""analyze_p48.py — mmss_host run --mic 기록 분석 (P4.8 mic 입력, P5.4 end-to-end)

입력: run --log PREFIX가 남긴 PREFIX_result.csv(.gz), PREFIX_model_group.csv(.gz), run stderr(summary 줄).
  nominal 뒤 도착 d = t_host_us의 FPGA 주기 안 위치 − nominal frame 끝 시각 O_m(frame 끝 샘플 번호 기준).
    mic block은 FPGA 주기 경계와 무관하게 오므로 d는 0–4 ms(block 하나) + USB 전달 흔들림이다. 기울기는 0이어야 한다.
  위상 오차 e = t_host_us 위치 − (주기 경계에서 시작한 64샘플 block 중 frame 끝 샘플이 든 block의 도착). --pace 실행에서만 0 근처다.
    기울기(ppm)는 맞추지 못한 clock 차이다. 보정이 없으면 mic–FPGA clock 차이(보드 약 −65 ppm)만큼 기운다.
  모델 그룹 지연 G = t_ready − t_host, response time = t_recv − t_host (µs).

    python3 analyze_p48.py --log <PREFIX> --runlog <run.log> [--json out.json] [--mic-tracks N]
"""
import argparse
import gzip
import json

import numpy as np


def q(x):
    x = np.asarray(x, float)
    return {k: round(float(v), 1) for k, v in zip(['p1', 'p50', 'p99', 'p99.9', 'max'], np.percentile(x, [1, 50, 99, 99.9, 100]))} | {'min': round(float(x.min()), 1)}


def rd(prefix, name):
    """CSV(.gz) → 열 이름별 int64/float 배열"""
    for ext, op in (('.csv', open), ('.csv.gz', gzip.open)):
        try:
            with op(f'{prefix}_{name}{ext}', 'rt') as f:
                cols = f.readline().strip().split(',')
                a = np.loadtxt(f, delimiter=',', dtype=np.float64, ndmin=2)
            return {c: a[:, i] for i, c in enumerate(cols)}
        except FileNotFoundError:
            pass
    raise FileNotFoundError(f'{prefix}_{name}.csv')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--log', required=True)
    ap.add_argument('--runlog', required=True)
    ap.add_argument('--json')
    ap.add_argument('--mic-tracks', type=int, default=0, help='mic 트랙 수. 주면 mic 트랙과 가상 트랙을 나눠서도 본다')
    a = ap.parse_args()
    r, g = rd(a.log, 'result'), rd(a.log, 'model_group')
    sm = {}
    for line in open(a.runlog):
        if line.startswith('summary '):
            sm = {k: float(v) for k, v in (kv.split('=') for kv in line.split()[1:])}

    th = r['t_host_us'].astype(np.int64)
    un = (th - th[0]) % 2**32 + th[0]
    end0 = (np.arange(40) * 512 + 20) // 40 + 1024                 # OFFSET_SAMPLES(m) + FRAME (host.h)
    ph = (-(-end0 // 64) * 64 * 1000 // 16) % 32000                 # 위상 0에서 시작한 block 중 frame 끝 샘플이 든 block의 도착 위상
    mid = r['model_id'].astype(int)
    e = (un % 32000 - ph[mid] + 16000) % 32000 - 16000
    d = (un % 32000 - ((end0 - 1024) * 1000 // 16)[mid] + 16000) % 32000 - 16000
    t = (r['t_host_ns'] - r['t_host_ns'].min()) / 1e9
    slope = np.polyfit(t, e, 1)[0] if t.max() > 1 else float('nan')   # µs/s = ppm
    first, last = e[t < 60], e[t > t.max() - 60]
    # 추론 요청별 Host 처리 지연 = 모델 그룹 t_ready − 그 추론 요청의 t_host. mic가 여럿이면 그룹 기록의 t_host와 다를 수 있다
    key = lambda k, m: k.astype(np.int64) * 64 + m.astype(np.int64)
    gk = key(g['period'], g['model_id'])
    o = np.argsort(gk)
    i = o[np.searchsorted(gk[o], key(r['period'], r['model_id']))]
    hd = (g['t_ready_ns'][i] - r['t_host_ns']) / 1e3
    out = {
        'audio_s': sm.get('audio_s'), 'sent': sm.get('sent'), 'recv': sm.get('recv'), 'lost': sm.get('lost'),
        'late': sm.get('late'), 'mic_xrun': sm.get('mic_xrun'), 'mic_adj_change': sm.get('mic_adj_change'),
        'sync_rtt_max_us': sm.get('sync_rtt_max_us'),
        'after_nominal_us': q(d), 'after_nominal_slope_ppm': round(float(np.polyfit(t, d, 1)[0]), 3),
        'phase_err_us': q(e), 'phase_err_first60_p50': float(np.median(first)), 'phase_err_last60_p50': float(np.median(last)),
        'phase_slope_ppm': round(float(slope), 3),
        'adj_ppm': round(sm['mic_adj_change'] / 16000 / max(sm['audio_s'] - 1.1, 1) * 1e6, 2) if 'mic_adj_change' in sm else None,
        'model_group_delay_us': q(g['delay_us']), 'host_delay_per_request_us': q(hd), 'response_time_us': q(r['response_time_us']),
    }
    if a.mic_tracks:                                                # run --mic + --in: track_id < N은 mic, 나머지는 가상 트랙
        tid = r['track_id']
        for name, s in (('mic_tracks', tid < a.mic_tracks), ('virtual_tracks', tid >= a.mic_tracks)):
            out[name] = {'n_req': int(s.sum()), 'after_nominal_us': q(d[s]),
                         'after_nominal_slope_ppm': round(float(np.polyfit(t[s], d[s], 1)[0]), 3),
                         'host_delay_per_request_us': q(hd[s]), 'response_time_us': q(r['response_time_us'][s])}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    if a.json:
        json.dump(out, open(a.json, 'w'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
