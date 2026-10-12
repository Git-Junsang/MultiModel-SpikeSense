#!/usr/bin/env python3
"""dse.py — P3.8 설계 공간 탐색: 설계마다 '모든 시나리오에서 마감 위반 0인 최대 트랙 수'를 찾는다.

설계 = 레인 × 막전위 위치(온칩·DDR3) × 저장(A 전체 캐시, B L1 상주, C 혼합, D 스트림)
       × 스케줄러 × 연산 방식(한 번에, 한 줄씩).
모델은 L INT8 고정(P3.6). DDR3 3.015 GB/s(칩 2개, 실측).
트랙 수 N에 따라 막전위 BRAM이 늘고 가중치 예산이 줄어든다(온칩). A·C의 엔트리 수는 남은 예산의 최대값이며
2벌 미만이면(적재·연산 동시 불가) 배치 불가로 본다.

rev 1 (MODEL_SIZE_PLAN §3): 레인 32·64·128, 스케줄러 FCFS·그룹핑·점수, 시나리오 U·K·S·I·SK × 시드 2, 32트랙 단위.
    python3 software/sim_develop/dse.py                 → sim_result/dse_capacity.{jsonl,md}
rev 2 (MODEL_SIZE_PLAN §4, 최대 트랙 실험): 호스트 1 ms 묶음 입출력, 막전위 쓰기 실측, 한 줄씩 묶음 ≤ 64 + 스파이크 버퍼.
       레인 32·64·128·256, 스케줄러 4종, 시나리오 + R × 시드 3, 16트랙 단위.
    python3 software/sim_develop/dse.py --rev 2           1단계 전수        → sim_result/dse2_capacity.{jsonl,md}
    python3 software/sim_develop/dse.py --rev 2 --verify  2단계 시드 20 확인 → sim_result/dse2_verify.{jsonl,md}
    python3 software/sim_develop/dse.py --rev 2 --axes    3단계 축별 기여    → sim_result/dse2_axes.md
    python3 software/sim_develop/dse.py --rev 2 --sens    4단계 민감도      → sim_result/dse2_sens.{jsonl,md}
모델 크기 비교(MODEL_SIZE_PLAN §4.7): 시뮬레이터는 크기만 쓰므로 학습 없이 구조만 바꾼다.
    python3 software/sim_develop/dse.py --rev 2 --arch 40,768,512,128,2 --tag xl [--verify|--axes|--sens] → sim_result/dse2_xl_*
"""
import argparse
import itertools
import json
import os
import sys
import time
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sim_core as sc  # noqa: E402
from policies import (EDF, AllAtOnce, FCFS, FullCache, Grouping, Hybrid,  # noqa: E402
                      L1Resident, RowByRow, Score, Stream)

MEMS = ['onchip', 'ddr']
STO = [FullCache, L1Resident, Hybrid, Stream]
CMP = [AllAtOnce, RowByRow]
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'sim_result')   # 결과는 software/sim_result

REV = {
    1: dict(rev=1, lanes=[32, 64, 128], sch=[FCFS, Grouping, Score], scen=['U', 'K', 'S', 'I', 'SK'],
            seeds=2, step=32, host=None, prefix='dse'),
    2: dict(rev=2, lanes=[32, 64, 128, 256], sch=[FCFS, EDF, Grouping, Score],
            scen=['U', 'K', 'S', 'I', 'SK', 'R'], seeds=3, step=16, host=1000.0, prefix='dse2'),
    3: dict(rev=3, lanes=[32, 64, 128, 256], sch=[FCFS, EDF, Grouping, Score],          # rev 2 + 엔트리 실제 깊이
            scen=['U', 'K', 'S', 'I', 'SK', 'R'], seeds=3, step=16, host=1000.0, prefix='dse3'),
}
VERIFY_SEEDS = 20
SENS = [('W_h 0.25 ms', dict(host=250.0)), ('W_h 0.5 ms', dict(host=500.0)), ('W_h 2 ms', dict(host=2000.0)),
        ('DDR3 2.0 GB/s', dict(bw=2000.0)), ('PCIe 꼬리 +700 µs', dict(tail=700.0))]


def sch_list(cfg):
    return cfg['sch']


def build(d, n, cfg):
    lanes, mem, si, qi, ci = d
    sc.configure(lanes, n, mem=mem, rev=cfg['rev'], arch=cfg.get('arch', sc.ARCH_L))
    sc.BW = cfg.get('bw', 3015.0)
    c = CMP[ci]()
    st = STO[si](budget=sc.TILE_BUDGET - c.mem_tiles())
    t = st.tiles() + c.extra_tiles(st)
    ok = sc.TILE_BUDGET > 0 and t <= sc.TILE_BUDGET and getattr(st, 'E', 2) >= 2
    return st, sch_list(cfg)[qi](), c, t, ok


def workload(n, seed, scn, cfg):
    wl = sc.make_workload(n, seed, host=cfg['host'], **sc.SCENARIOS[scn])
    tail = cfg.get('tail', 0.0)
    if tail:                                         # 모든 H2C·C2H 전송에 꼬리 지연을 더함
        wl.t_arr = wl.t_arr + tail
        if wl.out_w:
            wl.out_lat = wl.out_lat + tail
        else:
            wl.d_out = wl.d_out + tail
    return wl


def passes(d, n, cfg, seeds):
    st, q, c, t, ok = build(d, n, cfg)
    if not ok:
        return False
    for scn in cfg['scen']:
        for seed in seeds:
            r = sc.simulate(workload(n, seed, scn, cfg), st, q, c, stop_on_miss=True)
            if r['miss']:
                return False
    return True


def name(d, cfg):
    lanes, mem, si, qi, ci = d
    return dict(lanes=lanes, mem=mem, storage=STO[si].name, scheduler=sch_list(cfg)[qi].name, compute=CMP[ci].name)


def info(d, n, cfg):
    if not n:
        return {}
    st, q, c, t, _ = build(d, n, cfg)
    return dict(tiles=t, budget=sc.TILE_BUDGET, mem_tiles=sc.MEM_T, entries=getattr(st, 'E', None),
                l1_models=getattr(st, 'R', None), cmp_util=round(n * sc.C_REQ / sc.P, 4),
                queue_lut=round(n * 5472 / 512))


def capacity(job):
    d, cfg = job
    step = cfg['step']
    sc.configure(d[0], 512, arch=cfg.get('arch', sc.ARCH_L))
    hi = int(sc.P / sc.C_REQ) // step + 1            # 연산 한계보다 위에서 시작
    lo = 0
    seeds = range(cfg['seeds'])
    while lo < hi:                                   # 통과하는 가장 큰 N/step
        mid = (lo + hi + 1) // 2
        if passes(d, mid * step, cfg, seeds):
            lo = mid
        else:
            hi = mid - 1
    n = lo * step
    return dict(**name(d, cfg), capacity=n, **info(d, n, cfg), **{k: cfg[k] for k in ('host',) if cfg.get(k)},
                **{k: cfg[k] for k in ('bw', 'tail') if k in cfg})


def table(rows, cfg):
    sch = sch_list(cfg)
    rev2 = cfg['rev'] >= 2
    model = 'L INT8' if cfg.get('arch', sc.ARCH_L) == sc.ARCH_L else f"{'→'.join(map(str, cfg['arch']))} INT8 (크기만, 더미 가중치)"
    head = (f'# 설계별 최대 트랙 수 (모든 시나리오 위반 0) — {model}, DDR3 3.015 GB/s\n' if not rev2 else
            f'# 설계별 최대 트랙 수 (rev 2: 호스트 1 ms 묶음 입출력, 모든 시나리오 위반 0) — {model}, DDR3 3.015 GB/s\n')
    lines = [head,
             f"시뮬레이션 값. 시나리오 {'·'.join(cfg['scen'])} × 시드 {cfg['seeds']}개, {cfg['step']}트랙 단위. "
             '0 = 가장 작은 단위도 불가(BRAM 부족 등).\n']
    for lanes, mem in itertools.product(cfg['lanes'], MEMS):
        sc.configure(lanes, 512, mem=mem, rev=cfg['rev'], arch=cfg.get('arch', sc.ARCH_L))
        lines.append(f'\n## {lanes}레인, 막전위 {"온칩" if mem == "onchip" else "DDR3"} '
                     f'(연산 한계 {int(sc.P / sc.C_REQ)}트랙, 엔트리 {sc.ENTRY_T:g} 타일)\n')
        lines.append('| 저장 · 연산 | ' + ' | '.join(q.name for q in sch) + ' |')
        lines.append('|---|' + '---:|' * len(sch))
        for st, c in itertools.product(STO, CMP):
            cells = []
            for q in sch:
                r = next(x for x in rows if (x['lanes'], x['mem'], x['storage'], x['scheduler'], x['compute'])
                         == (lanes, mem, st.name, q.name, c.name))
                e = f" (엔트리 {r['entries']})" if r.get('entries') is not None and r['capacity'] else ''
                cells.append(f"{r['capacity']:,}{e}")
            lines.append(f'| {st.name} · {c.name} | ' + ' | '.join(cells) + ' |')
    return '\n'.join(lines) + '\n'


def key(r):
    return (r['lanes'], r['mem'], r['storage'], r['scheduler'], r['compute'])


def load(cfg, what='capacity'):
    with open(os.path.join(OUT, f"{cfg['prefix']}_{what}.jsonl")) as f:
        return [json.loads(x) for x in f]


def index(r, cfg):
    return (r['lanes'], r['mem'], [s.name for s in STO].index(r['storage']),
            [s.name for s in sch_list(cfg)].index(r['scheduler']), [c.name for c in CMP].index(r['compute']))


def best_per_group(rows):
    """(레인, 막전위)마다 최대 트랙 설계. 같으면 BRAM 타일이 적은 것"""
    out = {}
    for r in rows:
        g = (r['lanes'], r['mem'])
        if r['capacity'] and (g not in out or (r['capacity'], -r['tiles']) > (out[g]['capacity'], -out[g]['tiles'])):
            out[g] = r
    return [out[g] for g in sorted(out)]


# ---- 2단계: 시드 20 확인 --------------------------------------------------------
def verify_one(d, n, cfg):
    st, q, c, t, ok = build(d, n, cfg)
    if not ok:
        return dict(n=n, ok=False, worst_ms=None, miss=None, bram=False)
    worst, miss, fails = 0.0, 0, []
    for scn in cfg['scen']:
        for seed in range(VERIFY_SEEDS):
            r = sc.simulate(workload(n, seed, scn, cfg), st, q, c)
            worst = max(worst, r['max_ms'])
            miss += r['miss']
            if r['miss']:
                fails.append(f'{scn}/{seed}')
    return dict(n=n, ok=miss == 0, worst_ms=round(worst, 3), miss=miss, fails=fails[:6], bram=True)


def verify_scan(job):
    """1단계 N*에서 시작. 통과하면 한 단계 위를 확인하고, 실패하면 통과할 때까지 한 단계씩 내린다"""
    d, n0, cfg = job
    step, out = cfg['step'], []
    v = verify_one(d, n0, cfg)
    out.append(v)
    if v['ok']:
        out.append(verify_one(d, n0 + step, cfg))
    else:
        n = n0
        while not v['ok'] and n > step:
            n -= step
            v = verify_one(d, n, cfg)
            out.append(v)
    return out


def s_worst_bound(lanes, cfg):
    """S(동시 도착)의 해석 상한: 입력·결과 대기가 모두 W_h(최악 위상), H2C·C2H 실측 최대, 첫 모델 전송 1회 +
    N × 요청당 연산 ≤ 32 ms인 가장 큰 step 배수. 막전위 DDR3(연산 한계 영역)에서만 의미가 있다"""
    sc.configure(lanes, 512, mem='ddr', rev=cfg['rev'], arch=cfg.get('arch', sc.ARCH_L))
    w = cfg['host'] or 0.0
    h, c = sc.load_samples(sc.H_IN_FILE).max(), sc.load_samples(sc.H_OUT_FILE).max()
    n = 0
    while True:
        m = n + cfg['step']
        t = 2 * w + h + (m * sc.IN_B - 64) / sc.H2C_BW + c + sc.T0 + sc.MODEL_B / sc.BW + m * sc.C_REQ
        if t > sc.P:
            return n
        n = m


def verify(cfg, jobs):
    rows = load(cfg)
    best = best_per_group(rows)
    todo = [(index(r, cfg), r['capacity'], cfg) for r in best]
    with Pool(jobs) as p:
        res = p.map(verify_scan, todo, chunksize=1)
    out, lines = [], ['# 2단계: 최고 설계의 시드 20 확인 (rev 2)\n',
                      f"시나리오 {'·'.join(cfg['scen'])} × 시드 {VERIFY_SEEDS}개 전체 실행. 1단계 N*에서 시작해 통과하면 한 단계 위를, "
                      '실패하면 통과할 때까지 한 단계씩 내려 확인했다. 최대 응답 = 측정 구간 모든 요청의 최대(생성 → 결과가 '
                      '호스트에 도착). 여유 = 32 ms − 최대 응답. S 최악 위상 = 입력·결과 대기가 모두 W_h인 경우의 해석 상한'
                      '(막전위 DDR3만).\n',
                      '| 레인 | 막전위 | 설계 | 1단계 N* | N | 위반 | 최대 응답 ms | 여유 ms | 실패 예 | S 최악 위상 상한 |',
                      '|---:|---|---|---:|---:|---:|---:|---:|---|---:|']
    for (d, n0, _), vs in zip(todo, res):
        r = next(x for x in best if index(x, cfg) == d)
        sb = f'{s_worst_bound(d[0], cfg):,}' if d[1] == 'ddr' else '–'
        for v in vs:
            out.append(dict(**name(d, cfg), stage1=n0, s_bound=sb, **v))
            slack = f"{32 - v['worst_ms']:.2f}" if v['worst_ms'] is not None else '–'
            lines.append(f"| {d[0]} | {d[1]} | {r['storage']} · {r['scheduler']} · {r['compute']} | {n0:,} | {v['n']:,} | "
                         f"{v['miss'] if v['bram'] else 'BRAM 부족'} | {v['worst_ms'] if v['worst_ms'] is not None else '–'} | "
                         f"{slack} | {' '.join(v.get('fails', []))} | {sb} |")
    with open(os.path.join(OUT, f"{cfg['prefix']}_verify.jsonl"), 'w') as f:
        for o in out:
            f.write(json.dumps(o, ensure_ascii=False) + '\n')
    md = '\n'.join(lines) + '\n'
    with open(os.path.join(OUT, f"{cfg['prefix']}_verify.md"), 'w') as f:
        f.write(md)
    print(md)


# ---- 3단계: 축별 기여 (1단계 표만 사용) -----------------------------------------
def axes(cfg):
    rows = load(cfg)
    cap = {key(r): r['capacity'] for r in rows}
    sto, sch, cmp_ = [s.name for s in STO], [s.name for s in sch_list(cfg)], [c.name for c in CMP]
    lines = ['# 3단계: 축별 기여 (rev 2, 1단계 표에서 계산)\n',
             '## 최고 설계에서 한 축만 바꿨을 때\n',
             '각 칸 = 그 축의 후보로 바꿨을 때의 최대 트랙 수(나머지 두 축은 최고 설계 그대로). 범위 = 최대 − 최소.\n',
             '| 레인 | 막전위 | 최고 설계 | N* | 스케줄러 축 | 저장 축 | 연산 축 |', '|---:|---|---|---:|---|---|---|']
    for b in best_per_group(rows):
        L, m = b['lanes'], b['mem']
        col = []
        for ax, vals in ((1, sch), (0, sto), (2, cmp_)):
            vs = []
            for v in vals:
                k = [b['storage'], b['scheduler'], b['compute']]
                k[ax] = v
                vs.append((v, cap[(L, m, k[0], k[1], k[2])]))
            rng = max(x for _, x in vs) - min(x for _, x in vs)
            col.append(' / '.join(f'{v} {x:,}' for v, x in vs) + f' (범위 {rng:,})')
        lines.append(f"| {L} | {m} | {b['storage']} · {b['scheduler']} · {b['compute']} | {b['capacity']:,} | "
                     + ' | '.join(col) + ' |')

    lines += ['\n## 한 축씩 차례로 고르기 vs 전수 최적\n',
              '기준안(A.전체캐시 · FCFS · 한번에)에서 출발해 정한 순서로 한 축씩, 나머지를 고정한 채 최대 트랙 후보로 바꾼다'
              '(같으면 유지). 6가지 순서의 결과와 전수 최적을 비교한다.\n',
              '| 레인 | 막전위 | 기준안 | 순서별 결과 (스=스케줄러, 저=저장, 연=연산) | 순서 최선 | 전수 최적 | 차 |',
              '|---:|---|---:|---|---:|---:|---:|']
    axn = {0: '저', 1: '스', 2: '연'}
    for L, m in itertools.product(cfg['lanes'], MEMS):
        base = ['A.전체캐시', 'FCFS', '한번에']
        res = []
        for order in itertools.permutations((1, 0, 2)):
            k = list(base)
            for ax in order:
                vals = (sto, sch, cmp_)[ax]
                cur = cap[(L, m, *k)]
                for v in vals:
                    t = list(k)
                    t[ax] = v
                    if cap[(L, m, *t)] > cur:
                        k, cur = t, cap[(L, m, *t)]
            res.append((''.join(axn[a] for a in order), cap[(L, m, *k)], ' · '.join(k)))
        opt = max(cap[(L, m, a, b, c)] for a in sto for b in sch for c in cmp_)
        gbest = max(x for _, x, _ in res)
        lines.append(f"| {L} | {m} | {cap[(L, m, *base)]:,} | " + ', '.join(f'{o} {x:,}' for o, x, _ in res)
                     + f' | {gbest:,} | {opt:,} | {gbest - opt:+,} |')
    md = '\n'.join(lines) + '\n'
    with open(os.path.join(OUT, f"{cfg['prefix']}_axes.md"), 'w') as f:
        f.write(md)
    print(md)


# ---- 4단계: 민감도 ---------------------------------------------------------------
def sens(cfg, jobs):
    rows = load(cfg)
    best = best_per_group(rows)
    todo = [(index(r, cfg), dict(cfg, **ov)) for r in best for _, ov in SENS]
    with Pool(jobs) as p:
        res = p.map(capacity, todo, chunksize=1)
    lines = ['# 4단계: 민감도 (rev 2, (레인, 막전위)별 최고 설계)\n',
             f"시나리오 {'·'.join(cfg['scen'])} × 시드 {cfg['seeds']}개, {cfg['step']}트랙 단위. 기준 = 1단계 N*(W_h 1 ms, DDR3 3.015 GB/s).\n",
             '| 레인 | 막전위 | 설계 | 기준 | ' + ' | '.join(s for s, _ in SENS) + ' |',
             '|---:|---|---|---:|' + '---:|' * len(SENS)]
    out = []
    for i, r in enumerate(best):
        vals = res[i * len(SENS):(i + 1) * len(SENS)]
        out += [dict(v, cond=s) for (s, _), v in zip(SENS, vals)]
        lines.append(f"| {r['lanes']} | {r['mem']} | {r['storage']} · {r['scheduler']} · {r['compute']} | {r['capacity']:,} | "
                     + ' | '.join(f"{v['capacity']:,}" for v in vals) + ' |')
    with open(os.path.join(OUT, f"{cfg['prefix']}_sens.jsonl"), 'w') as f:
        for o in out:
            f.write(json.dumps(o, ensure_ascii=False) + '\n')
    md = '\n'.join(lines) + '\n'
    with open(os.path.join(OUT, f"{cfg['prefix']}_sens.md"), 'w') as f:
        f.write(md)
    print(md)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', type=int, default=11)
    ap.add_argument('--rev', type=int, default=1, choices=[1, 2, 3])
    ap.add_argument('--seeds', type=int)
    ap.add_argument('--lanes', type=int, nargs='+')
    ap.add_argument('--arch', help='모델 층 크기, 예: 40,768,512,128,2 (가중치 값은 쓰지 않으므로 학습 불필요)')
    ap.add_argument('--tag', help='결과 파일 접미사, 예: xl → dse2_xl_*')
    ap.add_argument('--verify', action='store_true')
    ap.add_argument('--axes', action='store_true')
    ap.add_argument('--sens', action='store_true')
    a = ap.parse_args()
    cfg = dict(REV[a.rev])
    if a.seeds:
        cfg['seeds'] = a.seeds
    if a.lanes:
        cfg['lanes'] = a.lanes
    if a.arch:
        cfg['arch'] = tuple(int(x) for x in a.arch.split(','))
    if a.tag:
        cfg['prefix'] += '_' + a.tag
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    if a.verify:
        verify(cfg, a.jobs)
    elif a.axes:
        axes(cfg)
    elif a.sens:
        sens(cfg, a.jobs)
    else:
        designs = list(itertools.product(cfg['lanes'], MEMS, range(len(STO)), range(len(cfg['sch'])),
                                         range(len(CMP))))
        designs.sort(key=lambda d: -d[0])            # 오래 걸리는 넓은 레인부터
        with Pool(a.jobs) as p:
            rows = p.map(capacity, [(d, cfg) for d in designs], chunksize=1)
        with open(os.path.join(OUT, f"{cfg['prefix']}_capacity.jsonl"), 'w') as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
        md = table(rows, cfg)
        with open(os.path.join(OUT, f"{cfg['prefix']}_capacity.md"), 'w') as f:
            f.write(md)
        print(md)
        print(f'{len(designs)}개 설계')
    print(f'{time.time() - t0:.0f} s')


if __name__ == '__main__':
    main()
