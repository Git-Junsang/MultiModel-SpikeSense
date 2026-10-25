#!/usr/bin/env python3
"""analyze_p325.py — M1·M3·M4 로그 → simulator trace CSV와 jitter 요약 (P3.25)

    python3 hardware/board_test/host/analyze_p325.py --m3 <m3 로그> --out <trace.csv>
    python3 hardware/board_test/host/analyze_p325.py --m1 <m1> --m3 <m3> --m4 <m4> --out <trace.csv> [--epochs 400]
출력: <trace>(.csv 또는 .csv.gz), <trace>.summary.json, 화면 요약. 있는 파일은 덮어쓰지 않는다.

trace 열(µs, 시각 원점 = 기준 로그의 가장 이른 t_gen):
  epoch,track_id,model_id,t_gen_us,t_ready_us,t_send_us,t_arr_us,t_done_us,t_recv_us,status
  status = ok | lost(M4 결과 없음) | xrun(M1 frame 안에서 녹음이 끊김). 없는 값은 빈 칸이고 t_gen_us·t_ready_us는 늘 있다.
  simulation/engine/part_jitter.py의 TraceJitter(host_jitter_dist = "trace")는 epoch, track_id, t_gen_us, t_ready_us만 읽는다. 앞 절반 epoch로
  분포(PNU LUT)를 만들고 뒤 절반을 재생한다. 그래서 --epochs(기본 400 = 12.8 s)로 앞에서부터 자른다. 0이면 전부 쓴다.
  요약은 자르기 전 전체로 낸다.

로그 합치기: 기준 격자(트랙 × epoch)는 --m3다(없으면 --m1, 그다음 --m4). 다른 로그의 지연은 engine의 trace 재생처럼 트랙·epoch
순번을 그 로그의 트랙 수·epoch 수로 나눈 나머지 칸에서 가져와 더한다. 단계 지연이 서로 독립이라는 가정이다.
M1 장치가 트랙보다 적으면 여러 트랙이 같은 장치의 지연을 받는다.
  t_gen   = M3 t_frame | M1 수음 시각 | M4 t_sched
  t_ready = t_gen + M1 frame 준비 지연 + M3 준비 지연(t_ready − t_frame)
  t_send  = t_ready + M4 보내기 지연(t_send − t_sched). M4가 없으면 t_send 이후는 빈 칸
  t_arr   = t_send + 편도(추론 요청), t_done = t_arr + (받는 쪽 t_done − t_arr), t_recv = t_done + 편도(결과)
M1 수음 시각: 장치마다 1초 창의 가장 빨리 온 block으로 drift 직선을 맞추고, xrun 구간마다 가장 빠른 block에 붙인다.
  그래서 frame 준비 지연은 '가장 빠른 block 대비'이고 ADC·USB 고정 지연은 빠진다(06_HOST_INTERFACE.md §5).
  장치 요약: drift_ppm(+면 장치가 빠름), err_ms_per_hour(보정 없이 1시간에 쌓이는 frame 끝 오차), cut_err_first/last_ms
  (nominal rate로 자른 frame 끝의 수음 시각 − offset 시각, 처음과 끝), block_delay(block 전달 지연), xrun_blocks
M4 편도: 1초 창마다 왕복(받는 쪽 처리 제외)이 가장 짧은 packet으로 clock 차이 θ = ((t_arr − t_send) + (t_done − t_recv)) / 2를
  구한다. θ(t) = 창 값들의 직선(clock drift) + 창 사이 나머지의 선형 보간이다. 양방향 대칭 가정이다.
  loopback 로그는 'M4 loopback code-check'로 표시한다.
파생값(01_OVERVIEW.md §3, 실험 요청서 §4):
  delta_ready = t_ready − t_gen, delta_send = t_send − t_ready, delta_net = t_arr − t_send, delta_total = t_arr − t_gen
  cm_* = 같은 epoch의 중앙값(common-mode), diff_* = 추론 요청 − 그 epoch 중앙값(differential)
  spread_* = 같은 모델·epoch 추론 요청의 최대 − 최소(jitter 폭 J)
"""
import argparse
import json
import os
import sys
import warnings

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from p325_common import M, OFF_NS, P_NS, SR, open_in, open_out, read_meta  # noqa: E402

TRACE_COLS = 'epoch,track_id,model_id,t_gen_us,t_ready_us,t_send_us,t_arr_us,t_done_us,t_recv_us,status'
LOOPBACK_WARN = 'M4 loopback code-check: 같은 PC의 127.0.0.1이다. Ethernet 측정값으로 쓰지 않는다'


def load(path, cols):
    with open_in(path) as f:
        head = f.readline().strip().split(',')
        a = np.loadtxt(f, delimiter=',', dtype=np.int64, usecols=[head.index(c) for c in cols], ndmin=2)
    return {c: a[:, i] for i, c in enumerate(cols)}


def grid(track, epoch, **vals):
    """(트랙, epoch) 표. 없는 칸은 NaN"""
    tu, ti = np.unique(track, return_inverse=True)
    eu, ei = np.unique(epoch, return_inverse=True)
    g = dict(track=tu, epoch=eu)
    for k, v in vals.items():
        g[k] = np.full((tu.size, eu.size), np.nan)
        g[k][ti, ei] = v
    return g


def pct(v_ns):
    """ns 값 → µs 분포 요약"""
    v = np.asarray(v_ns, float).ravel()
    v = v[np.isfinite(v)] / 1e3
    if not v.size:
        return dict(n=0)
    q = np.percentile(v, [50, 95, 99, 99.9])
    return dict(n=int(v.size), p50=q[0], p95=q[1], p99=q[2], p99_9=q[3], max=float(v.max()))


def first_min(key, val):
    """key 값마다 val이 가장 작은 원소의 위치"""
    o = np.lexsort((val, key))
    return o[np.r_[True, np.diff(key[o]) != 0]]


def m1(path):
    r = load(path, ['device_id', 'track_id', 'model_id', 'sample_index', 'host_block_arrival_ns', 'frame_ready_ns',
                    'epoch', 'frame_end_index', 'xrun'])
    meta = read_meta(path)
    rate = meta.get('rate', SR)
    frame, per0, T0 = 2 * rate * 32 // 1000, 1e9 / rate, meta.get('T0_ns')
    devs, F = [], {k: [] for k in ('track', 'epoch', 'model', 't_gen', 'd_audio', 'xrun')}
    for d in np.unique(r['device_id']):
        sel = r['device_id'] == d
        b = sel & (r['track_id'] == r['track_id'][sel].min())       # block 줄(장치의 첫 트랙만)
        x, a, xr = r['sample_index'][b], r['host_block_arrival_ns'][b], r['xrun'][b]
        y = a - x * per0                                            # 도착 − nominal 경과
        seg = np.cumsum(xr)                                         # xrun이면 샘플이 빠졌으므로 구간을 나눈다
        long_ = seg == np.bincount(seg).argmax()
        w = first_min(x[long_] // rate, y[long_])                   # 1초 창마다 가장 빨리 온 block
        xm, ym = x[long_][w], y[long_][w]
        c1 = np.polyfit(xm, ym, 1)[0] if xm.size >= 3 else 0.0      # 창이 3개 미만이면 drift를 재지 못한다
        c0 = np.full(seg.max() + 1, np.nan)                         # 구간마다 가장 빨리 온 block에 붙인다
        for s in np.unique(seg):
            c0[s] = np.min(y[seg == s] - c1 * x[seg == s])
        dl = y - c0[seg] - c1 * x                                   # block 전달 지연(가장 빠른 block 대비)
        per = per0 + c1
        f = sel & (r['frame_ready_ns'] >= 0)
        e = r['frame_end_index'][f]
        t_gen = c0[seg[np.minimum(np.searchsorted(x, e), x.size - 1)]] + e * per     # frame 끝이 든 block의 구간
        B = int(np.median(np.diff(x))) if x.size > 1 else 1
        xs = x[xr > 0]
        bad = np.searchsorted(xs, e + B - 1, 'right') > np.searchsorted(xs, e - frame + 1, 'left')
        for k, v in (('track', r['track_id'][f]), ('epoch', r['epoch'][f]), ('model', r['model_id'][f]), ('t_gen', t_gen),
                     ('d_audio', r['frame_ready_ns'][f] - t_gen), ('xrun', bad)):
            F[k].append(v)
        dm = meta.get('devices') or []
        info = dm[d] if d < len(dm) else {}
        cut = t_gen - (T0 + r['model_id'][f] * OFF_NS + r['epoch'][f] * P_NS) if T0 is not None and e.size else None
        devs.append(dict(device=int(d), name=info.get('name'), latency_s=info.get('latency_s'), block=B, blocks=int(x.size),
                         xrun_blocks=int(xr.sum()), windows=int(xm.size), drift_ppm=(per0 / per - 1) * 1e6,
                         err_ms_per_hour=(per / per0 - 1) * 3.6e6,
                         fit_resid_max_us=float(np.ptp(ym - c1 * xm)) / 1e3 if xm.size else None,
                         cut_err_first_ms=float(cut[0]) / 1e6 if cut is not None else None,
                         cut_err_last_ms=float(cut[-1]) / 1e6 if cut is not None else None,
                         block_delay=pct(dl), frame_ready=pct(r['frame_ready_ns'][f] - t_gen)))
    F = {k: np.concatenate(v) for k, v in F.items()}
    g = grid(F['track'], F['epoch'], t_gen=F['t_gen'], d_audio=F['d_audio'], xrun=F['xrun'], model=F['model'])
    return g, dict(path=path, label=meta.get('note') or 'M1', rate=rate, devices=devs, frames=int(F['track'].size),
                   frame_ready=pct(F['d_audio']), xrun_frames=int(F['xrun'].sum()))


def m3(path):
    r = load(path, ['epoch', 'track_id', 'model_id', 't_frame_ns', 't_compute_start_ns', 't_ready_ns', 'cpu', 'thread'])
    meta = read_meta(path)
    g = grid(r['track_id'], r['epoch'], t_gen=r['t_frame_ns'], d_mel=r['t_ready_ns'] - r['t_frame_ns'], model=r['model_id'])
    _, i = np.unique(r['epoch'] * M + r['model_id'], return_index=True)       # (epoch, 모델) 묶음 하나씩
    i = i[np.argsort(r['t_compute_start_ns'][i], kind='stable')]
    mig = {int(t): int((np.diff(r['cpu'][i][r['thread'][i] == t]) != 0).sum()) for t in np.unique(r['thread'][i])}
    return g, dict(path=path, label=meta.get('note') or 'M3', tracks=int(g['track'].size), epochs=int(g['epoch'].size),
                   audio=meta.get('audio'), pin=meta.get('pin'), load=meta.get('load'), loadavg_end=meta.get('loadavg'),
                   wake=pct(r['t_compute_start_ns'][i] - r['t_frame_ns'][i]),
                   compute=pct(r['t_ready_ns'][i] - r['t_compute_start_ns'][i]),
                   ready=pct(r['t_ready_ns'][i] - r['t_frame_ns'][i]),
                   cpus={int(t): sorted(set(r['cpu'][i][r['thread'][i] == t].tolist())) for t in mig}, cpu_changes=mig)


def m4(path):
    c = ['track_id', 'model_id', 'epoch', 't_send_host_ns', 't_arr_fpga_ns', 't_done_fpga_ns', 't_recv_host_ns', 'lost',
         'reordered', 'retransmitted', 't_sched_host_ns']
    r = load(path, c)
    meta = read_meta(path)
    ok = r['lost'] == 0
    t1, t2, t3, t4 = (r[k].astype(float) for k in c[3:7])
    nan = np.full(t1.size, np.nan)
    fwd, back, fpga, drift = nan, nan, nan, None
    if ok.any():
        rtt = (t4 - t1) - (t3 - t2)                                 # 받는 쪽 처리를 뺀 왕복
        th = ((t2 - t1) + (t3 - t4)) / 2                            # 받는 쪽 clock − Host clock
        i = np.flatnonzero(ok)
        x = t1 - t1[i].min()
        pick = i[first_min(x[i] // 1e9, rtt[i])]
        cf = np.polyfit(x[pick], th[pick], 1) if pick.size >= 3 else (0.0, float(np.median(th[pick])))
        # 직선(drift) + 창 사이 나머지를 선형으로. 처음·마지막 창 바깥은 직선만 따라간다
        theta = np.polyval(cf, x) + np.interp(x, x[pick], th[pick] - np.polyval(cf, x[pick]))
        fwd, back, fpga = (np.where(ok, v, np.nan) for v in (t2 - t1 - theta, t4 - t3 + theta, t3 - t2))
        drift = float(cf[0] * 1e6) if pick.size >= 3 else None
    late = t1 - r['t_sched_host_ns']
    g = grid(r['track_id'], r['epoch'], t_gen=r['t_sched_host_ns'], d_late=late, d_fwd=fwd, d_fpga=fpga, d_back=back,
             lost=r['lost'], model=r['model_id'])
    loop = meta.get('mode') == 'loopback'
    return g, dict(path=path, label=LOOPBACK_WARN if loop else (meta.get('label') or 'M4'), mode=meta.get('mode'),
                   note=meta.get('note'), requests=int(ok.size), lost=int((~ok).sum()), lost_ratio=float((~ok).mean()),
                   reordered=int(r['reordered'].sum()), retransmitted=int(r['retransmitted'].sum()),
                   send_late=pct(late), fwd=pct(fwd), back=pct(back), remote=pct(fpga),
                   rtt=pct(np.where(ok, t4 - t1, np.nan)), clock_drift_ppm=drift)


def compose(logs):
    """기준 로그 격자에 다른 로그의 단계 지연을 더한다. 반환: 트랙·epoch·모델, 시각 표(ns), status 표"""
    b = logs.get('m3') or logs.get('m1') or logs.get('m4')
    T, E = b['t_gen'].shape

    def take(name, key):
        g = logs[name][key]
        return g[np.arange(T)[:, None] % g.shape[0], np.arange(E)[None, :] % g.shape[1]]

    t = dict(t_gen=b['t_gen'])
    t['t_ready'] = t['t_gen'] + (take('m1', 'd_audio') if 'm1' in logs else 0) + (take('m3', 'd_mel') if 'm3' in logs else 0)
    if 'm4' in logs:
        t['t_send'] = t['t_ready'] + take('m4', 'd_late')
        t['t_arr'] = t['t_send'] + take('m4', 'd_fwd')
        t['t_done'] = t['t_arr'] + take('m4', 'd_fpga')
        t['t_recv'] = t['t_done'] + take('m4', 'd_back')
    for k in ('t_send', 't_arr', 't_done', 't_recv'):
        t.setdefault(k, np.full((T, E), np.nan))
    status = np.full((T, E), 'ok', dtype=object)
    if 'm1' in logs:
        status[take('m1', 'xrun') == 1] = 'xrun'
    if 'm4' in logs:
        status[take('m4', 'lost') == 1] = 'lost'
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)
        model = np.nanmax(b['model'], 1).astype(int)
    return b['track'], b['epoch'], model, t, status


def summarize(model, t):
    d = dict(delta_ready=t['t_ready'] - t['t_gen'], delta_send=t['t_send'] - t['t_ready'],
             delta_net=t['t_arr'] - t['t_send'], delta_total=t['t_arr'] - t['t_gen'])
    out = {k: pct(v) for k, v in d.items()}
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)
        for k in ('ready', 'total'):
            cm = np.nanmedian(d['delta_' + k], 0)
            out['cm_' + k], out['diff_' + k] = pct(cm), pct(d['delta_' + k] - cm[None, :])
        for k in ('t_ready', 't_arr'):
            sp = [np.nanmax(t[k][model == m], 0) - np.nanmin(t[k][model == m], 0) for m in np.unique(model)]
            out['spread_' + k[2:]] = pct(np.concatenate(sp))
    return out


def write_trace(path, track, epoch, model, t, status, n_epochs):
    origin = np.nanmin(t['t_gen'])
    E = t['t_gen'].shape[1] if not n_epochs else min(n_epochs, t['t_gen'].shape[1])
    keys = ('t_gen', 't_ready', 't_send', 't_arr', 't_done', 't_recv')
    n = dropped = 0
    with open_out(path) as f:
        f.write(TRACE_COLS + '\n')
        for j in range(E):
            for i in range(track.size):
                v = [(t[k][i, j] - origin) / 1e3 for k in keys]
                if not (np.isfinite(v[0]) and np.isfinite(v[1])):          # engine은 빈 칸을 트랙 중앙값으로 채운다
                    dropped += 1
                    continue
                f.write(f'{epoch[j]},{track[i]},{model[i]},' + ','.join(f'{x:.3f}' if np.isfinite(x) else '' for x in v)
                        + f',{status[i, j]}\n')
                n += 1
    return dict(rows=n, dropped=dropped, epochs=E, time_origin_ns=float(origin))


def show(name, s):
    if s.get('n'):
        print(f"  {name:13s} n {s['n']:>9d}  p50 {s['p50']:9.1f}  p95 {s['p95']:9.1f}  p99 {s['p99']:9.1f}  "
              f"p99.9 {s['p99_9']:9.1f}  최대 {s['max']:9.1f} µs")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--m1', default='')
    ap.add_argument('--m3', default='')
    ap.add_argument('--m4', default='')
    ap.add_argument('--out', required=True, help='trace CSV(.csv 또는 .csv.gz)')
    ap.add_argument('--epochs', type=int, default=400, help='trace에 쓸 앞쪽 epoch 수. 0 = 전부')
    a = ap.parse_args()
    if os.path.exists(a.out) or os.path.exists(a.out + '.summary.json'):
        sys.exit(f'출력 파일이 이미 있다: {a.out}')
    logs, info = {}, {}
    for name, fn in (('m1', m1), ('m3', m3), ('m4', m4)):
        if getattr(a, name):
            logs[name], info[name] = fn(getattr(a, name))
    if not logs:
        sys.exit('--m1, --m3, --m4 중 하나 이상이 필요하다')
    track, epoch, model, t, status = compose(logs)
    summ = dict(inputs={k: v['path'] for k, v in info.items()}, labels={k: v['label'] for k, v in info.items()},
                base=next(k for k in ('m3', 'm1', 'm4') if k in logs), stats=summarize(model, t), **info)
    summ['trace'] = dict(path=a.out, **write_trace(a.out, track, epoch, model, t, status, a.epochs))
    with open_out(a.out + '.summary.json') as f:
        json.dump(summ, f, ensure_ascii=False, indent=1, default=float)
    for k, v in info.items():
        print(f"[{k}] {v['label']}  ({v['path']})")
    if info.get('m4', {}).get('mode') == 'loopback':
        print(f'주의: {LOOPBACK_WARN}')
    for d in info.get('m1', {}).get('devices', []):
        print(f"  M1 장치 {d['device']} {d['name']}: drift {d['drift_ppm']:+.2f} ppm({d['err_ms_per_hour']:+.1f} ms/시간), "
              f"xrun block {d['xrun_blocks']}, block {d['block']} 샘플")
        show('block 지연', d['block_delay'])
    for k in ('m3',):
        if k in info:
            for name in ('wake', 'compute', 'ready'):
                show(f'M3 {name}', info[k][name])
    if 'm4' in info:
        v = info['m4']
        print(f"  M4 추론 요청 {v['requests']}, 결과 없음 {v['lost']}({v['lost_ratio']:.2e}), 순서 바뀜 {v['reordered']}, "
              f"clock drift {v['clock_drift_ppm']} ppm")
        for name in ('send_late', 'fwd', 'back', 'rtt'):
            show(f'M4 {name}', v[name])
    for k, s in summ['stats'].items():
        show(k, s)
    tr = summ['trace']
    print(f"trace {tr['rows']}줄(빠진 칸 {tr['dropped']}), epoch {tr['epochs']}개 → {a.out}, 요약 {a.out}.summary.json")


if __name__ == '__main__':
    main()
