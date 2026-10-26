"""p326_m3_group.py — M3 원자료(p325_mel_load.py 출력) → 모델·period 모델 그룹 지연 표(period, model_id, delay_us = t_ready − t_frame µs).
같은 모델·period 트랙은 t_ready가 같다(퍼짐 0). 그래서 모델 그룹마다 한 줄이고, 다르면 멈춘다. 처음 16 period(0.5 s)는 뺀다.
원자료가 있는 폴더(sub1 ~/mmss_jobs/p325, m3/m3_<조건>.csv.gz)에서 실행하고, 출력 m3/m3_group_<조건>.csv.gz를
hardware/board_test/p325_meas/result/로 가져온다. Simulation의 host_model_group_delay_trace가 읽는다(P3.26).

    ~/mmss_venv/bin/python p326_m3_group.py
"""
import csv, gzip, json
import numpy as np
for c in ('pin-none_load0', 'pin3_load0', 'pin-none_load8', 'pin3_load8'):
    seen = {}
    with gzip.open(f'm3/m3_{c}.csv.gz', 'rt') as f:
        r = csv.reader(f)
        next(r)
        for row in r:
            k, m = int(row[0]), int(row[2])
            if k < 16:
                continue
            d = (int(row[5]) - int(row[3])) / 1000.0
            v = seen.setdefault((k, m), d)
            assert v == d, (c, k, m, v, d)
    keys = sorted(seen)
    with gzip.open(f'm3/m3_group_{c}.csv.gz', 'wt', newline='') as f:
        w = csv.writer(f)
        w.writerow(['period', 'model_id', 'delay_us'])
        for k, m in keys:
            w.writerow([k, m, f'{seen[(k, m)]:.3f}'])
    d = np.array([seen[x] for x in keys])
    print(json.dumps(dict(cond=c, rows=len(keys), periods=len({k for k, _ in keys}), p50=float(np.percentile(d, 50)),
                          p99=float(np.percentile(d, 99)), p999=float(np.percentile(d, 99.9)), max=float(d.max()), min=float(d.min()))))
