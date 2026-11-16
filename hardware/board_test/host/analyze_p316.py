#!/usr/bin/env python3
"""analyze_p316.py — 라즈베리파이 5 Host 측정(P3.16) 원자료 → 요약·모델 그룹 지연 표·링크 지연 표본

입력: hardware/board_test/p316_meas/raw/<조건>_{result,model_group}.csv.gz, <조건>.run.log·stop.log·before.txt·after.txt,
      cap_<조건>.pcap.gz(측정 2). p316_pi_run.sh가 Pi에서 만든다.
출력: hardware/board_test/p316_meas/result/
  summary.jsonl                  조건마다 한 줄(측정 1)
  pi_group_<조건>.csv.gz         모델 그룹 지연 표 (period, model_id, delay_us). P3.26 m3_group_*과 같은 형식, 처음 16주기 제외
  ccdf.csv                       cond, quantity, value_us, ccdf (모델 그룹 지연 G, 추론 요청별 지연 j, response time)
  link.json                      측정 2: 왕복·편도 링크 지연, packet 간격, 제어 packet 왕복
  eth_up_ns.txt, eth_down_ns.txt 추론 요청 편도 지연 표본(ns, 한 줄에 하나). P3.3 PCIe 표본(p3_meas/result/raw/pcie)과 같은 형식

    python3 hardware/board_test/host/analyze_p316.py [조건 ...]
정의(01_OVERVIEW §4): t_host = frame 마지막 샘플이 든 block(64샘플 = 4 ms) 도착 예정 시각(--pace),
G = t_ready − t_host(모델 그룹 계산 끝), j = 같은 모델·주기 안에서 FPGA 도착(t_in) − 그 그룹의 가장 이른 t_in.
"""
import gzip
import json
import os
import re
import struct
import sys

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
RAW = os.path.join(ROOT, 'hardware', 'board_test', 'p316_meas', 'raw')
OUT = os.path.join(ROOT, 'hardware', 'board_test', 'p316_meas', 'result')
M, SKIP, PERIOD_US, REQ_B, PER_DG = 40, 16, 32000, 64, 23
Q = (50, 99, 99.9)


def pct(x):
    x = np.asarray(x, float)
    return {**{f'p{q:g}': float(np.percentile(x, q)) for q in Q}, 'max': float(x.max()), 'min': float(x.min()),
            'mean': float(x.mean()), 'n': int(x.size)}


def ccdf_rows(cond, name, x, n=200):
    x = np.sort(np.asarray(x, float))
    v = np.unique(np.quantile(x, 1 - np.logspace(0, -np.log10(x.size), n) + 1e-15, method='lower'))
    return [(cond, name, float(t), float((x >= t).mean())) for t in v]


def group_key(period, model):
    return period.astype(np.int64) * M + model


def per_group_spread(key, t):
    """같은 key(모델·주기) 안에서 t − 그룹 최소, 그룹마다 max − min"""
    o = np.argsort(key, kind='stable')
    k, t = key[o], t[o]
    start = np.r_[0, np.flatnonzero(np.diff(k)) + 1]
    mn, mx = np.minimum.reduceat(t, start), np.maximum.reduceat(t, start)
    cnt = np.diff(np.r_[start, k.size])
    return t - np.repeat(mn, cnt), mx - mn


def read_log(path, key):
    with open(path) as f:
        line = [s for s in f if s.startswith(key)][-1]
    return {k: float(v) for k, v in re.findall(r'(\w+)=([-\d.]+)', line)}


def snap(path):
    s = open(path).read()
    udp = [ln.split() for ln in s.splitlines() if ln.startswith('Udp:')]
    out = dict(zip(udp[0][1:], map(int, udp[1][1:]))) if len(udp) >= 2 else {}
    for k, pat in (('temp_c', r"temp=([\d.]+)"), ('throttled', r'throttled=(0x[0-9a-f]+)'), ('arm_hz', r'frequency\(0\)=(\d+)'),
                   ('rmem_max', r'^(\d+)$'), ('governor', r'^(ondemand|performance|schedutil|powersave|conservative)$')):
        m = re.search(pat, s, re.M)
        if m:
            out[k] = m.group(1)
    out['eth_rx_errors'] = sum(int(v) for v in re.findall(        # macb(ethtool -S) 수신 오류·버림 합
        r'^\s+(?:rx_frame_check_sequence_errors|rx_symbol_errors|rx_alignment_errors|rx_resource_errors|rx_overruns|'
        r'rx_udp_checksum_errors|q\d+_rx_dropped):\s+(\d+)', s, re.M))
    return out


def m1(cond):
    """측정 1: Host 처리 지연, FPGA 도착 퍼짐, response time"""
    p = os.path.join(RAW, cond)
    g = np.loadtxt(p + '_model_group.csv.gz', delimiter=',', skiprows=1, dtype=np.int64,
                   usecols=(0, 1, 3, 4, 5, 6, 7), converters=None)                  # period, model, n_req, t_host, t_start, t_ready, t_send (ns)
    g = g[g[:, 0] >= SKIP]
    G = (g[:, 5] - g[:, 3]) / 1e3
    wait = (g[:, 4] - g[:, 3]) / 1e3
    comp = (g[:, 5] - g[:, 4]) / 1e3
    send = (g[:, 6] - g[:, 5]) / 1e3
    dur_s = (g[:, 3].max() - g[:, 3].min()) / 1e9
    r = np.loadtxt(p + '_result.csv.gz', delimiter=',', skiprows=1, dtype=np.int64, usecols=(0, 2, 3, 6, 7, 8, 9, 12, 13))
    r = r[r[:, 1] >= SKIP]                                                           # track, period, model, t_host_us, t_in, t_start, t_done, t_host_ns, t_recv_ns
    assert np.all((r[:, 0] % M) == r[:, 2]), 'track % 40 = model_id (기본 map)'
    span = r[:, 4].max() - r[:, 4].min()
    assert span < 2**31, 'FPGA µs 시각이 되감겼다'
    key = group_key(r[:, 1], r[:, 2])
    j, spread = per_group_spread(key, r[:, 4].astype(float))
    resp = (r[:, 8] - r[:, 7]) / 1e3
    arr = (r[:, 4] - r[:, 3]).astype(float)                                          # t_in − t_host, FPGA 시각(맞추기 오차 포함)
    fpga = (r[:, 6] - r[:, 4]).astype(float)
    with gzip.open(os.path.join(OUT, f'pi_group_{cond}.csv.gz'), 'wt', newline='') as f:
        f.write('period,model_id,delay_us\n')
        for k, m, d in zip(g[:, 0], g[:, 1], G):
            f.write(f'{k},{m},{d:.3f}\n')
    run = read_log(p + '.run.log', 'summary')
    stop = dict(ln.split()[:2] for ln in open(p + '.stop.log') if re.match(r'^[A-Z_]+ \d+', ln))
    b, a = snap(p + '.before.txt'), snap(p + '.after.txt')
    s = dict(cond=cond, periods=int(np.unique(g[:, 0]).size), model_groups=int(G.size), requests=int(r.shape[0]), audio_s=run['audio_s'],
             G_us=pct(G), wait_us=pct(wait), compute_per_group_us=pct(comp), send_us=pct(send),
             compute_per_req_us=float(comp.sum() / g[:, 2].sum()), compute_busy=float(comp.sum() / 1e6 / dur_s),
             arrival_minus_t_host_us=pct(arr), j_us=pct(j), group_spread_us=pct(spread), response_time_us=pct(resp), fpga_us=pct(fpga),
             over_32ms=int((resp > PERIOD_US).sum()),
             run={k: run[k] for k in ('sent', 'recv', 'lost', 'late', 'deadline_miss', 'overrun', 'send_err', 'unmatched', 'sync_fail',
                                      'sync_rtt_max_us')},
             fpga_counters=stop,
             udp_rcvbuf_errors=a.get('RcvbufErrors', 0) - b.get('RcvbufErrors', 0),
             udp_in_errors=a.get('InErrors', 0) - b.get('InErrors', 0),
             eth_rx_errors=a.get('eth_rx_errors', 0) - b.get('eth_rx_errors', 0),
             temp_c=[b.get('temp_c'), a.get('temp_c')], throttled=[b.get('throttled'), a.get('throttled')],
             governor=b.get('governor'), arm_hz_after=a.get('arm_hz'), rmem_max=b.get('rmem_max'))
    cc = ccdf_rows(cond, 'G', G) + ccdf_rows(cond, 'j', j + 0.5) + ccdf_rows(cond, 'response_time', resp)   # j는 µs 정수라 0.5를 더해 log 축에 둔다
    return s, cc


def save_samples(path, x_us, n=20000):
    """표본 µs → 최소부터 최대까지 고른 분위수 n개(ns 정수). PCIe 표본과 같은 줄 수, 최대값을 남긴다(simulator margin)"""
    np.savetxt(path, np.round(np.quantile(np.asarray(x_us, float), np.linspace(0, 1, n)) * 1e3).astype(np.int64), fmt='%d')


def read_pcap(path):
    """nanosecond pcap(-s 96). 요청 datagram, 결과, 제어 packet을 나눈다"""
    b = gzip.open(path, 'rb').read()
    magic = struct.unpack_from('<I', b)[0]
    assert magic == 0xa1b23c4d, 'nanosecond pcap이어야 한다'
    req, res, ctl_q, ctl_r = [], [], {}, {}
    o = 24
    while o + 16 <= len(b):
        sec, ns, incl, _ = struct.unpack_from('<IIII', b, o)
        t = sec * 1_000_000_000 + ns
        d = b[o + 16:o + 16 + incl]
        o += 16 + incl
        if d[12:14] != b'\x08\x00' or d[23] != 17:
            continue
        ihl = (d[14] & 15) * 4
        u = 14 + ihl
        sp, dp, ulen = struct.unpack_from('>HHH', d, u)
        pl = d[u + 8:]
        src = d[26:30]
        if dp == 5000 and src == bytes([192, 168, 10, 1]):
            tr, seq, m = struct.unpack_from('<HHB', pl, 2)
            req.append((t, tr, seq, m, (ulen - 8) // REQ_B))
        elif sp == 5000 and src == bytes([192, 168, 10, 2]):
            tr, seq, m, fl, bn, th, ti, ts, td = struct.unpack_from('<HHBBHIIII', pl, 0)
            res.append((t, tr, seq, m, ti, ts, td))
        elif dp == 5001:
            ctl_q.setdefault(struct.unpack_from('<H', pl, 2)[0], t)
        elif sp == 5001:
            ctl_r.setdefault(struct.unpack_from('<H', pl, 2)[0], t)
    return np.array(req, np.int64), np.array(res, np.int64), ctl_q, ctl_r


def m2(cond):
    """측정 2: 링크 지연(pcap 시각 ↔ FPGA 시각), packet 간격, 제어 packet 왕복"""
    req, res, cq, cr = read_pcap(os.path.join(RAW, cond + '.pcap.gz'))
    # 요청 datagram → 추론 요청: datagram은 모델 m 트랙 [m, m + 40, ...]의 23개 조각 (기본 map)
    n = req[:, 4]
    rep = np.repeat(np.arange(len(req)), n)
    idx = np.arange(rep.size) - np.repeat(np.cumsum(n) - n, n)
    tr = req[rep, 1] + M * idx
    seq = req[rep, 2]
    kq = seq * 2048 + tr                                                            # 120 s = 3,750주기라 seq가 되감기지 않는다
    assert np.unique(kq).size == kq.size
    o = np.argsort(kq)
    kr = res[:, 2] * 2048 + res[:, 1]
    pos = np.searchsorted(kq[o], kr)
    ok = (pos < kq.size) & (kq[o][np.minimum(pos, kq.size - 1)] == kr)
    dg = rep[o][pos[ok]]
    t_tx, r = req[dg, 0], res[ok]
    keep = r[:, 2] >= SKIP
    t_tx, r, dg = t_tx[keep], r[keep], dg[keep]
    t_rx, t_in, t_done = r[:, 0], r[:, 4].astype(float), r[:, 6].astype(float)
    rtt = (t_rx - t_tx) / 1e3 - (t_done - t_in)                                     # 왕복 링크 = Host 왕복 − FPGA 안 시간
    up_raw, down_raw = t_in - t_tx / 1e3, t_rx / 1e3 - t_done
    # 두 clock 차이 θ: 1초 창마다 양방향 최소가 같다고 보고(대칭 가정) θ = (min up_raw − min down_raw) / 2, 창 사이 선형 보간
    w = (t_tx - t_tx.min()) // 1_000_000_000
    ws = np.unique(w)
    th = np.array([(up_raw[w == i].min() - down_raw[w == i].min()) / 2 for i in ws])
    tc = np.array([t_tx[w == i].mean() for i in ws])
    theta = np.interp(t_tx, tc, th)
    up, down = up_raw - theta, down_raw + theta
    drift_ppm = float(np.polyfit((tc - tc[0]) / 1e9, th, 1)[0])                     # µs/s = ppm
    # packet 간격: 같은 모델·주기 datagram 0 → 1
    gk = req[:, 2] * M + req[:, 3]
    first = np.r_[True, gk[1:] != gk[:-1]]
    nxt = ~first
    gap_host = (req[1:, 0] - req[:-1, 0])[nxt[1:]] / 1e3
    tin_dg = np.full(len(req), np.nan)                                               # datagram 첫 추론 요청의 t_in
    head = idx[o][pos[ok]][keep] == 0
    tin_dg[dg[head]] = t_in[head]
    pair = np.flatnonzero(nxt)
    gf = tin_dg[pair] - tin_dg[pair - 1]
    gap_fpga = gf[np.isfinite(gf)]
    ctl = np.array([(cr[t] - cq[t]) / 1e3 for t in cq if t in cr])
    dgs = np.bincount(np.unique(gk, return_inverse=True)[1])
    out = dict(cond=cond, requests_matched=int(ok.sum()), requests_sent=int(kq.size), results=int(len(res)), datagrams=int(len(req)),
               datagrams_per_group=dict(zip(*[x.tolist() for x in np.unique(dgs, return_counts=True)])),
               link_rtt_us=pct(rtt), up_us=pct(up), down_us=pct(down), clock_drift_ppm=drift_ppm,
               gap_host_us=pct(gap_host), gap_fpga_us=pct(gap_fpga), ctl_rtt_us=pct(ctl),
               note='pcap 시각은 Pi kernel software timestamp. up = 송신 pcap → FPGA t_in, down = FPGA t_done → 수신 pcap. '
                    '편도는 1초 창마다 양방향 최소가 같다는 대칭 가정. 왕복(link_rtt)은 가정 없음. FPGA 시각은 µs 정수')
    for name, x in (('eth_up_ns.txt', up), ('eth_down_ns.txt', down)):
        save_samples(os.path.join(OUT, name), x)
    return out, ccdf_rows(cond, 'link_rtt', rtt) + ccdf_rows(cond, 'up', up) + ccdf_rows(cond, 'down', down)


def mic(path):
    """측정 3: p316_alsa_rec.py의 <이름>_alsa.csv.gz → 장치별 drift(ALSA timestamp 기준), read 지연, block 전달 지연, xrun.
    htstamp 시점까지 들어온 샘플 수 N = sample_index + 1 + avail. 1초 창마다 (htstamp − N / rate) 최솟값으로 직선을 맞춘다.
    xrun이 나면 샘플이 빠지므로 xrun 사이 구간마다 절편을 따로 둔다(기울기는 가장 긴 구간에서)"""
    meta = json.load(open(path.replace('_alsa.csv.gz', '.csv.gz.json')))
    rate = meta['rate']
    x = np.loadtxt(path, delimiter=',', skiprows=1, dtype=np.int64)               # device, sample_index, t_ret, htstamp, avail, xrun
    devs = []
    for d in np.unique(x[:, 0]):
        r = x[x[:, 0] == d]
        n = r[:, 1] + 1 + r[:, 4]
        y = r[:, 3] - n * 1e9 / rate
        seg = np.cumsum(r[:, 5])
        long_ = seg == np.bincount(seg).argmax()
        win = (r[:, 3] - r[0, 3]) // 1_000_000_000
        w = [np.flatnonzero(long_ & (win == i))[np.argmin(y[long_ & (win == i)])] for i in np.unique(win[long_])]
        c1, _ = np.polyfit(n[w].astype(float), y[w], 1)                            # ns/샘플 기울기
        c0 = np.array([np.min(y[seg == s] - c1 * n[seg == s]) for s in range(seg.max() + 1)])
        line = lambda k, s: c0[s] + c1 * k + k * 1e9 / rate                       # noqa: E731  샘플 k가 들어온 가장 이른 시각
        drift = (1e9 / rate / (1e9 / rate + c1) - 1) * 1e6
        devs.append(dict(device=int(d), name=meta['devices'][d]['name'], blocks=int(len(r)), xrun_blocks=int(r[:, 5].sum()),
                         drift_ppm=drift, err_ms_per_hour=-drift * 3.6, windows=len(w),
                         read_lag_us=pct((r[:, 2] - r[:, 3]) / 1e3),                  # readi 반환 − 마지막 hw pointer 갱신
                         urb_jitter_us=pct((y[long_] - c0[seg[long_]] - c1 * n[long_]) / 1e3),
                         block_delay_us=pct((r[:, 2] - line(r[:, 1] + 1, seg)) / 1e3),    # read 반환 − block 마지막 샘플의 가장 이른 도착
                         avail_frames_max=int(r[:, 4].max())))
    out = dict(run=os.path.basename(path).replace('_alsa.csv.gz', ''), rate=rate, buffer_ms=meta['buffer_ms'],
               periods=meta['periods'], load=meta['load'], minutes=meta['minutes'], devices=devs)
    if len(devs) == 2:
        out['relative_drift_ppm'] = devs[0]['drift_ppm'] - devs[1]['drift_ppm']
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    if sys.argv[1:2] == ['--mic']:                                                 # 측정 3만
        with open(os.path.join(OUT, 'mic_summary.jsonl'), 'w') as f:
            for p in sorted(x for x in os.listdir(RAW) if x.startswith('mic_') and x.endswith('_alsa.csv.gz')):
                s = mic(os.path.join(RAW, p))
                print(json.dumps(s, ensure_ascii=False))
                f.write(json.dumps(s, ensure_ascii=False) + '\n')
        return
    conds = sys.argv[1:] or sorted({f[:-len('.run.log')] for f in os.listdir(RAW) if f.endswith('.run.log')})
    summ, cc = [], []
    for c in conds:
        s, x = m1(c)
        print(json.dumps({k: s[k] for k in ('cond', 'G_us', 'j_us', 'response_time_us', 'compute_per_req_us', 'compute_busy', 'run')},
                         ensure_ascii=False))
        summ.append(s)
        cc += x
        if c.startswith('cap_'):
            lk, x = m2(c)
            print(json.dumps(lk, ensure_ascii=False))
            json.dump(lk, open(os.path.join(OUT, 'link.json'), 'w'), ensure_ascii=False, indent=1)
            cc += x
    with open(os.path.join(OUT, 'summary.jsonl'), 'w') as f:
        for s in summ:
            f.write(json.dumps(s, ensure_ascii=False) + '\n')
    with open(os.path.join(OUT, 'ccdf.csv'), 'w') as f:
        f.write('cond,quantity,value_us,ccdf\n')
        for row in cc:
            f.write('%s,%s,%.3f,%.4g\n' % row)


if __name__ == '__main__':
    main()
