"""part_result.py — 결과 CSV 읽기·쓰기와 실행 합산. CSV 형식은 simulation_engine.md §7.4"""
import csv
import gzip
import io
import json

import numpy as np

from part_hardware import CLK, PERIOD_US

RESP_BIN_MS, RESP_BINS = 0.05, 1400   # 응답 시간 히스토그램 0.05 ms 칸, 70 ms 이상은 마지막 칸(합산 p99용)
PRED_ERR_BIN_US = 50.0          # 다음 사용 예측 오차 히스토그램 칸 µs
SEED_STAT_KEYS = ('dram_kib', 'ddr_mbps', 'mean_ms', 'p99_ms', 'max_ms', 'min_slack_ms', 'hit', 'loads_per_model_period',
             'reloads_per_model_period', 'max_done_ms', 'fpga_side_max_ms')


def cell(v):
    """CSV 칸 값: 문자열은 그대로, 숫자·참거짓·목록·표는 JSON"""
    if isinstance(v, str):
        try:
            json.loads(v)                              # 숫자·참거짓처럼 읽히는 문자열만 따옴표를 붙인다
        except ValueError:
            return v
    return json.dumps(v, ensure_ascii=False, default=lambda o: o.item())   # numpy 수는 Python 수로


def _open(path, mode):
    """.gz면 gzip(시각을 넣지 않아 같은 내용이면 같은 byte), 아니면 그냥 연다"""
    if not path.endswith('.gz'):
        return open(path, mode, newline='', encoding='utf-8')
    return io.TextIOWrapper(gzip.GzipFile(path, mode + 'b', mtime=0), newline='', encoding='utf-8')


def write_csv(path, rows):
    cols = list(dict.fromkeys(k for r in rows for k in r))
    with _open(path, 'w') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows({k: cell(v) for k, v in r.items()} for r in rows)


def read_csv(path):
    """engine CSV → dict 목록. 칸마다 JSON으로 읽고, 안 되면 문자열 그대로(빈 칸 = 값 없음)"""
    def val(s):
        try:
            return json.loads(s)
        except ValueError:
            return s
    with _open(path, 'r') as f:
        return [{k: val(v) for k, v in r.items()} for r in csv.DictReader(f)]


def summarize(rs):
    """실행 여러 개를 합산한다. 비율·추론 요청당 값은 합을 나눠 내고 p99는 히스토그램을 합쳐 구한다(칸 위 경계)"""
    n = sum(r['n_req'] for r in rs)
    h = np.zeros(RESP_BINS + 1)
    for r in rs:
        for j, k in r['hist']:
            h[j] += k
    cum = np.cumsum(h)
    rw = sum(r['req_win'] for r in rs)
    span = sum(r['cyc_busy'] + r['cyc_stall'] + r['cyc_idle'] for r in rs) * CLK       # 측정 구간 합 µs
    wavg = lambda k: sum(r['n_req'] * r[k] for r in rs) / n
    return dict(runs=len(rs), n_req=n, miss=sum(r['miss'] for r in rs), drop=sum(r['drop'] for r in rs),
                mean_ms=wavg('mean_ms'), p99_ms=float(np.searchsorted(cum, 0.99 * cum[-1]) + 1) * RESP_BIN_MS,
                max_ms=max(r['max_ms'] for r in rs), in_ms=wavg('in_ms'), fpga_ms=wavg('fpga_ms'), out_ms=wavg('out_ms'),
                w_kib=sum(r['w_bytes'] for r in rs) / rw / 1024, dram_kib=sum(r['w_bytes'] + r['m_bytes'] for r in rs) / rw / 1024,
                ddr_mbps=sum(r['w_bytes'] + r['m_bytes'] for r in rs) / span,
                batch=rw / sum(r['req_win'] / r['batch_mean'] for r in rs if r['batch_mean']),
                hit=float(np.mean([r['hit_rate'] for r in rs])), **_summary_cache(rs, rw),
                **{k: max(r[k] for r in rs) for k in ('max_done_ms', 'host_max_ms', 'fpga_side_max_ms') if k in rs[0]})


def _summary_cache(rs, rw):
    """적재·재적재·Belady 하한(그때 DDR3 KiB/추론)·예측 오차 합산"""
    tot = lambda k: sum(r.get(k) or 0 for r in rs)
    mx = max(r['max_ms'] for r in rs)
    h = np.zeros(1401)
    for r in rs:
        for j, k in r['pred_hist']:
            h[j] += k
    n = tot('pred_n')
    return dict(min_slack_ms=PERIOD_US / 1000 - mx, batch_max=max(r['batch_max'] for r in rs),
                window_loads_max=max(r.get('window_loads_max', 0) for r in rs),
                weight_loads=tot('weight_loads'), window_reloads=tot('window_reloads'),
                loads_per_model_period=tot('weight_loads') / max(1, tot('model_periods')),
                reloads_per_model_period=tot('window_reloads') / max(1, tot('model_periods')),
                belady_loads=tot('belady_loads'), belady_kib=sum(r['belady_loads'] * r['model_b'] + r['m_bytes'] for r in rs) / rw / 1024,
                evictions=tot('evictions'), wrong_victim_rate=tot('wrong_victims') / max(1, tot('evictions')),
                prediction_mae_us=tot('pred_abs_sum') / n if n else float('nan'),
                prediction_p95_us=float(np.searchsorted(np.cumsum(h), 0.95 * n) + 1) * PRED_ERR_BIN_US if n else float('nan'),
                lut_mae_us=tot('lut_abs_sum') / tot('lut_n') if tot('lut_n') else float('nan'))


def seed_stats(rs):
    """seed마다(시나리오를 합쳐) 지표를 내고 seed 사이 표준편차·95 % bootstrap CI(평균)·최소·최대를 낸다"""
    by = {}
    for r in rs:
        by.setdefault(r['seed'], []).append(r)
    per = [summarize(g) for _, g in sorted(by.items())]
    rng, out = np.random.default_rng(12345), {'n_seeds': len(per)}
    for k in SEED_STAT_KEYS:
        v = np.array([p.get(k, np.nan) for p in per], float)
        if np.isnan(v).all():
            continue
        boot = v[rng.integers(0, v.size, (2000, v.size))].mean(1)
        out.update({f'{k}_sd': float(v.std(ddof=1)) if v.size > 1 else float('nan'),
                    f'{k}_ci_lo': float(np.percentile(boot, 2.5)), f'{k}_ci_hi': float(np.percentile(boot, 97.5)),
                    f'{k}_min': float(v.min()), f'{k}_max': float(v.max())})
    return out
