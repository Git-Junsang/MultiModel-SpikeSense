#!/usr/bin/env python3
"""analyze_p3.py — P3.1(DDR3)·P3.3(PCIe) 보드 측정 원자료 → 요약표(Markdown)

입력 (hardware/board_test/p3_meas/result/raw/):
  ddr_<tag>.jsonl          p3_ddr_bench.py 출력 (tag = brc / rbc: MIG 주소 매핑)
  pcie/<시험>_<조건>.txt   pcie_delay.c 출력 (한 줄 = 표본 1개, ns)
  pcie/ts_sync*.txt        "t0_ns ts_cycles t1_ns"
출력: hardware/board_test/p3_meas/result/summary_ddr.md, summary_pcie.md

    python3 hardware/board_test/host/analyze_p3.py
"""
import glob
import json
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', 'p3_meas', 'result')
RAW = os.path.join(OUT, 'raw')
CYC_NS = 10.0                 # ui_clk 100 MHz
ASSUMED_BPS = 2.0e9           # 제안서의 실효 bandwidth 가정


def load_ddr():
    recs = {}
    for f in sorted(glob.glob(os.path.join(RAW, 'ddr_*.jsonl'))):
        for line in open(f):
            r = json.loads(line)
            recs[(r['tag'], r['group'], r['label'])] = r
    return recs


def delay_stats(r, key='log_delay'):
    """전송별 지연 기록(cycle) → µs 통계. 기록이 없으면 min/평균/max만."""
    res = r['res']
    out = {'n': res['xfers'], 'min': res['delay_min'] * CYC_NS / 1e3,
           'avg': res['delay_sum'] / max(res['xfers'], 1) * CYC_NS / 1e3,
           'max': res['delay_max'] * CYC_NS / 1e3}
    v = np.array(res.get(key, []), dtype=np.float64) * CYC_NS / 1e3
    if len(v):
        out.update(p50=float(np.percentile(v, 50)), p99=float(np.percentile(v, 99)), nlog=len(v))
    if key == 'log_fst':
        out['min'] = res['fst_min'] * CYC_NS / 1e3
        out['avg'] = res['fst_sum'] / max(res['xfers'], 1) * CYC_NS / 1e3
        out['max'] = res['fst_max'] * CYC_NS / 1e3
    return out


def f3(x):
    return f'{x:.3f}'


def ddr_summary(recs):
    tags = sorted({k[0] for k in recs})
    L = ['# P3.1 DDR3 측정 요약 (자동 생성: analyze_p3.py)', '',
         '단위: GB/s = 1e9 B/s, 지연 µs. cycle 기준 ui_clk 100 MHz. tag: brc = BANK_ROW_COLUMN, '
         'rbc = ROW_BANK_COLUMN (MIG 주소 매핑).', '']

    def get(tag, grp, lab):
        return recs.get((tag, grp, lab))

    # full
    L += ['## 1 GiB 전 범위 쓰기·검증', '', '| tag | 실행 | GB/s | 오류 | 프로토콜 오류 |', '|---|---|---:|---:|---:|']
    for t in tags:
        for (tg, g, lab), r in recs.items():
            if tg == t and g == 'full':
                L.append(f'| {t} | {lab} | {f3(r["res"]["GBps"])} | {r["res"]["err_cnt"]} | {r["res"]["proto_err"]} |')
    L.append('')

    # burst
    L += ['## 순차 접근: 버스트 길이별 (64 MiB, 동시 버스트 16)', '',
          '| 버스트(beat / B) | ' + ' | '.join(f'{t} 읽기 | {t} 쓰기' for t in tags) + ' |',
          '|---|' + '---:|' * (2 * len(tags))]
    for bl in (1, 2, 4, 8, 16, 32, 64, 128):
        row = [f'{bl} / {bl * 32}']
        for t in tags:
            for op in ('rd', 'wr'):
                r = get(t, 'burst', f'{op}_bl{bl}')
                row.append(f3(r['res']['GBps']) if r else '-')
        L.append('| ' + ' | '.join(row) + ' |')
    L.append('')

    # outst
    L += ['## 순차 읽기: 동시 버스트 수', '', '| tag | 버스트 | 1 | 2 | 4 | 8 | 16 |', '|---|---|---:|---:|---:|---:|---:|']
    for t in tags:
        for bl in (16, 128):
            row = [t, f'{bl} beat']
            for mo in (1, 2, 4, 8, 16):
                r = get(t, 'outst', f'rd_bl{bl}_mo{mo}')
                row.append(f3(r['res']['GBps']) if r else '-')
            L.append('| ' + ' | '.join(row) + ' |')
    L.append('')

    # slice
    sizes = [512, 1024, 2048, 4096, 8192, 15360, 16384, 32768, 65536, 98304, 130176]
    for t in tags:
        L += [f'## 슬라이스 크기별 읽기 ({t})', '',
              '모델 전환 = 매 슬라이스 40개 모델 slot 중 무작위 slot의 시작 주소. 같은 모델 = 연속 주소. '
              'blocking = 앞 슬라이스가 끝나야 다음 전송, pipelined = 연속 전송. '
              '`가정 시간` = 크기 / 2.0 GB/s.', '',
              '| 크기 B | 가정 시간 | 전환·blk GB/s | 전환·blk 지연 평균 / p99 / 최대 | 첫 데이터 평균 | '
              '전환·pipe GB/s | 연속·blk GB/s | 연속·pipe GB/s |',
              '|---:|---:|---:|---|---:|---:|---:|---:|']
        for sz in sizes:
            rb = get(t, 'slice', f'slot_rand_blk_{sz}')
            rp = get(t, 'slice', f'slot_rand_pipe_{sz}')
            sb = get(t, 'slice', f'seq_blk_{sz}')
            sp = get(t, 'slice', f'seq_pipe_{sz}')
            if not rb:
                continue
            s = delay_stats(rb)
            fs = delay_stats(rb, 'log_fst')
            L.append(f'| {sz:,} | {sz / ASSUMED_BPS * 1e6:.3f} | {f3(rb["res"]["GBps"])} | '
                     f'{s["avg"]:.3f} / {s.get("p99", float("nan")):.3f} / {s["max"]:.3f} | {fs["avg"]:.3f} | '
                     f'{f3(rp["res"]["GBps"]) if rp else "-"} | {f3(sb["res"]["GBps"]) if sb else "-"} | '
                     f'{f3(sp["res"]["GBps"]) if sp else "-"} |')
        # 비용 모델용 1차 회귀: blocking 슬라이스 1개 시간 = a + S / b (평균·최대 각각)
        xs, ya, ym = [], [], []
        for sz in sizes:
            rb = get(t, 'slice', f'slot_rand_blk_{sz}')
            if rb:
                st = delay_stats(rb)
                xs.append(sz)
                ya.append(st['avg'])
                ym.append(st['max'])
        if len(xs) >= 2:
            ka, ba = np.polyfit(xs, ya, 1)
            km, bm = np.polyfit(xs, ym, 1)
            ra = np.max(np.abs(np.array(ya) - (ka * np.array(xs) + ba)))
            L += ['', f'회귀(전환·blocking): 평균 t(S) = {ba:.3f} µs + S / {1e-3 / ka:.3f} GB/s '
                  f'(최대 잔차 {ra:.3f} µs), 최대 t(S) = {bm:.3f} µs + S / {1e-3 / km:.3f} GB/s']
        L.append('')

    # model
    L += ['## 모델·layer 단위 가져오기 (blocking, 40 slot)', '',
          '| tag | 구간 | 크기 B | 순서 | GB/s | 지연 평균 / p99 / 최대 µs | 가정 시간 µs |',
          '|---|---|---:|---|---:|---|---:|']
    for t in tags:
        for (tg, g, lab), r in sorted(recs.items()):
            if tg != t or g != 'model':
                continue
            sz = r['cfg']['xfer_beats'] * 32
            s = delay_stats(r)
            sec, order = lab.rsplit('_slot_', 1)
            L.append(f'| {t} | {sec} | {sz:,} | slot_{order} | {f3(r["res"]["GBps"])} | '
                     f'{s["avg"]:.3f} / {s.get("p99", float("nan")):.3f} / {s["max"]:.3f} | '
                     f'{sz / ASSUMED_BPS * 1e6:.3f} |')
    L.append('')

    # single
    L += ['## 단일 beat(32 B) 지연', '', '| tag | 시험 | 최소 | 평균 | p50 | p99 | 최대 (ns) |',
          '|---|---|---:|---:|---:|---:|---:|']
    for t in tags:
        for lab in ('rand_1GiB_blk', 'seq_blk', 'rand_1GiB_blk_wr'):
            r = get(t, 'single', lab)
            if not r:
                continue
            s = delay_stats(r)
            L.append(f'| {t} | {lab} | {s["min"] * 1e3:.0f} | {s["avg"] * 1e3:.0f} | '
                     f'{s.get("p50", 0) * 1e3:.0f} | {s.get("p99", 0) * 1e3:.0f} | {s["max"] * 1e3:.0f} |')
    L.append('')

    # random
    L += ['## 임의 주소 소단위 읽기 처리량 (pipelined, 동시 16)', '',
          '| 크기 B | ' + ' | '.join(f'{t} GB/s' for t in tags) + ' |', '|---:|' + '---:|' * len(tags)]
    for sz in (32, 64, 128, 256, 512, 1024, 2048, 4096):
        row = [f'{sz:,}']
        for t in tags:
            r = get(t, 'random', f'rand_pipe_{sz}')
            row.append(f3(r['res']['GBps']) if r else '-')
        L.append('| ' + ' | '.join(row) + ' |')
    L.append('')
    return '\n'.join(L)


def pct(v, q):
    return float(np.percentile(v, q))


def pcie_summary():
    files = sorted(glob.glob(os.path.join(RAW, 'pcie', '*.txt')))
    L = ['# P3.3 PCIe 지연 요약 (자동 생성: analyze_p3.py)', '',
         '단위 µs. Host CLOCK_MONOTONIC_RAW로 잰 호출 1회 시간. `p` 조건은 주기 대기 후 측정.', '',
         '| 시험 | 표본 | 최소 | 평균 | p50 | p99 | p99.9 | 최대 | 표준편차 |',
         '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    ts_rows = []
    for f in files:
        name = os.path.basename(f)[:-4]
        if 'ts_sync' in name:
            ts_rows.append((name, np.loadtxt(f, dtype=np.float64)))
            continue
        v = np.loadtxt(f, dtype=np.float64) / 1e3
        if v.ndim != 1 or not len(v):
            continue
        L.append(f'| {name} | {len(v):,} | {v.min():.2f} | {v.mean():.2f} | {pct(v, 50):.2f} | '
                 f'{pct(v, 99):.2f} | {pct(v, 99.9):.2f} | {v.max():.2f} | {v.std():.2f} |')
    L.append('')
    if ts_rows:
        L += ['## Host·FPGA 시계 관계 (TS 레지스터 읽기)', '',
              'FPGA TS = ui_clk(보드 200 MHz 발진기 → MIG MMCM 100 MHz) 계수기. Host 시각 = '
              '읽기 전후 중간값. 1차 회귀의 기울기로 상대 주파수 오차(ppm)를, 잔차로 판독 불확도를 본다.', '',
              '| 파일 | 표본 | 구간 s | 주파수 오차 ppm | 잔차 p99 µs | 왕복 p50 µs | 왕복 p99 µs |',
              '|---|---:|---:|---:|---:|---:|---:|']
        for name, a in ts_rows:
            t0, ts, t1 = a[:, 0], a[:, 1], a[:, 2]
            mid = (t0 + t1) / 2.0
            x = (mid - mid[0]) / 1e9
            y = (ts - ts[0]) / 100e6
            k, b = np.polyfit(x, y, 1)
            res = (y - (k * x + b)) * 1e6
            rtt = (t1 - t0) / 1e3
            L.append(f'| {name} | {len(a):,} | {x[-1]:.1f} | {(k - 1) * 1e6:+.2f} | '
                     f'{pct(np.abs(res), 99):.2f} | {pct(rtt, 50):.2f} | {pct(rtt, 99):.2f} |')
        L.append('')
    return '\n'.join(L)


def main():
    os.makedirs(OUT, exist_ok=True)
    recs = load_ddr()
    if recs:
        s = ddr_summary(recs)
        open(os.path.join(OUT, 'summary_ddr.md'), 'w').write(s + '\n')
        print(s)
    if glob.glob(os.path.join(RAW, 'pcie', '*.txt')):
        s = pcie_summary()
        open(os.path.join(OUT, 'summary_pcie.md'), 'w').write(s + '\n')
        print(s)


if __name__ == '__main__':
    main()
