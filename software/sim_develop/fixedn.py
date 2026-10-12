#!/usr/bin/env python3
"""fixedn.py — 트랙 수를 고정하고 설계(저장 × 스케줄러 × 연산 방식)마다 운영 지표를 비교한다 (MODEL_SIZE_PLAN §4.8).

지표 (시나리오 U·K·S·I·SK·R × 시드, 측정 구간 2.048 s)
  위반율        마감(생성 → 결과가 호스트에 도착 32 ms)을 넘긴 요청 비율. 전체와 가장 나쁜 시나리오
  추론 시간     생성 → 결과 도착 평균·p99 (호스트 1 ms 묶음 입출력 포함)
  DDR3 사용     요청당 바이트(가중치 + 막전위 읽기·쓰기), 요청당 DMA 횟수(가중치 DMA + 막전위 2회), 평균 대역폭
  에너지(추정)  요청당 동적 에너지 = DDR3 + BRAM(SRAM) + 연산. 계수는 45 nm 문헌값(Horowitz, ISSCC 2014)으로
                상대 비교용이다. FPGA 실제 값은 몇 배 클 수 있고 정적 전력은 넣지 않았다.
                DDR3 20 pJ/bit(32 bit 640 pJ), SRAM 0.16 pJ/bit(32 bit 5 pJ), 8 bit 곱 0.2 pJ, 32 bit 덧셈 0.1 pJ

    python3 software/sim_develop/fixedn.py --n 1000 --lanes 256 --mem ddr --rev 3 --arch 40,768,512,128,2 --tag xl
결과: sim_result/fixedn_<tag>_n<N>_l<lanes>_<mem>.{jsonl,md}
"""
import argparse
import itertools
import json
import os
import sys
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dse  # noqa: E402
import sim_core as sc  # noqa: E402

E_DDR, E_SRAM, E_MUL8, E_ADD32 = 20.0, 0.16, 0.2, 0.1      # pJ/bit, pJ/bit, pJ, pJ
SEEDS = 5
MEAS = 64                       # 측정 주기 수 (make_workload 기본값)


def energy_per_req(w_b, m_b, arch):
    """요청당 동적 에너지 nJ: DDR3(가중치·막전위), BRAM(DMA로 쓴 가중치 + 연산이 읽는 가중치 전체), 연산"""
    n_w = sum(a * b for a, b in zip(arch[:-1], arch[1:]))
    l1 = arch[0] * arch[1]
    ddr = (w_b + m_b) * 8 * E_DDR
    sram = (w_b + n_w) * 8 * E_SRAM                    # 가중치 1 B = 8 bit
    comp = l1 * (E_MUL8 + E_ADD32) + (n_w - l1) * E_ADD32   # 층 1은 곱셈+누산, 층 2~4는 스파이크라 덧셈만(밀집 계산 가정)
    return ddr / 1e3, sram / 1e3, comp / 1e3


def run_design(job):
    d, n, cfg = job
    st, q, c, t, ok = dse.build(d, n, cfg)
    base = dse.name(d, cfg)
    if not ok:
        return dict(base, feasible=False, tiles=t)
    miss = tot = 0
    worst_scn, mean_l, resp, w_b, m_b, w_x, req, dma_u, cmp_u = {}, [], [], 0.0, 0.0, 0, 0, [], []
    for scn in cfg['scen']:
        ms = ns = 0
        for seed in range(SEEDS):
            r = sc.simulate(dse.workload(n, seed, scn, cfg), st, q, c)
            ms += r['miss']
            ns += r['n_req']
            resp.append(r['resp'])
            w_b += r['w_bytes']
            m_b += r['m_bytes']
            w_x += r['w_xfers']
            req += r['req_win']
            dma_u.append(r['dma_util'])
            cmp_u.append(r['cmp_util'])
        worst_scn[scn] = ms / ns
        miss += ms
        tot += ns
    rr = np.concatenate(resp) / 1000
    span = SEEDS * len(cfg['scen']) * MEAS * sc.P      # 측정 구간 합 µs (B/µs = MB/s)
    e = energy_per_req(w_b / req, m_b / req, cfg.get('arch', sc.ARCH_L))
    return dict(base, feasible=True, tiles=t, entries=getattr(st, 'E', None),
                miss_rate=miss / tot, worst_scn=max(worst_scn, key=worst_scn.get), worst_rate=max(worst_scn.values()),
                mean_ms=float(rr.mean()), p99_ms=float(np.percentile(rr, 99)), max_ms=float(rr.max()),
                bytes_req=(w_b + m_b) / req, w_bytes_req=w_b / req, xfers_req=w_x / req + (2 if sc.MEM_B else 0),
                ddr_mbps=(w_b + m_b) / span, dma_util=float(np.mean(dma_u)), cmp_util=float(np.mean(cmp_u)),
                e_ddr_nj=e[0], e_sram_nj=e[1], e_comp_nj=e[2], e_total_nj=sum(e))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=1000)
    ap.add_argument('--lanes', type=int, default=256)
    ap.add_argument('--mem', default='ddr', choices=['onchip', 'ddr'])
    ap.add_argument('--rev', type=int, default=3)
    ap.add_argument('--arch', default=None)
    ap.add_argument('--tag', default='L')
    ap.add_argument('--jobs', type=int, default=8)
    a = ap.parse_args()
    cfg = dict(dse.REV[a.rev])
    if a.arch:
        cfg['arch'] = tuple(int(x) for x in a.arch.split(','))
    designs = [(a.lanes, a.mem, si, qi, ci) for si, qi, ci in
               itertools.product(range(len(dse.STO)), range(len(cfg['sch'])), range(len(dse.CMP)))]
    with Pool(a.jobs) as p:
        rows = p.map(run_design, [(d, a.n, cfg) for d in designs], chunksize=1)
    stem = os.path.join(dse.OUT, f'fixedn_{a.tag}_n{a.n}_l{a.lanes}_{a.mem}')
    with open(stem + '.jsonl', 'w') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    model = '→'.join(map(str, cfg.get('arch', sc.ARCH_L)))
    L = [f'# 트랙 {a.n}개 고정 비교 — 모델 {model}, {a.lanes}레인, 막전위 {"DDR3" if a.mem == "ddr" else "온칩"}, rev {a.rev}\n',
         f"시뮬레이션 값. 시나리오 {'·'.join(cfg['scen'])} × 시드 {SEEDS}, 측정 구간 2.048 s. 추론 시간 = 생성 → 결과 도착(호스트 1 ms 묶음 입출력 포함). "
         '에너지는 45 nm 문헌 계수로 낸 요청당 동적 에너지 추정(상대 비교용, 정적 전력 제외).\n',
         '| 저장 · 스케줄러 · 연산 | 위반율 | 가장 나쁜 시나리오 | 평균 ms | p99 ms | DDR3 KB/요청 | DMA 횟수/요청 | DDR3 MB/s | 연산 가동률 | 에너지 nJ/요청 (DDR3) |',
         '|---|---:|---|---:|---:|---:|---:|---:|---:|---:|']
    for r in sorted(rows, key=lambda r: (not r['feasible'], r.get('miss_rate', 1), r.get('mean_ms', 1e9))):
        nm = f"{r['storage']} · {r['scheduler']} · {r['compute']}"
        if not r['feasible']:
            L.append(f'| {nm} | BRAM 배치 불가 ({r["tiles"]:g} 타일) | | | | | | | | |')
            continue
        L.append(f"| {nm} | {r['miss_rate'] * 100:.2f} % | {r['worst_scn']} {r['worst_rate'] * 100:.1f} % | {r['mean_ms']:.2f} | "
                 f"{r['p99_ms']:.2f} | {r['bytes_req'] / 1024:.1f} | {r['xfers_req']:.1f} | {r['ddr_mbps']:.0f} | "
                 f"{r['cmp_util']:.2f} | {r['e_total_nj']:.0f} ({r['e_ddr_nj']:.0f}) |")
    md = '\n'.join(L) + '\n'
    with open(stem + '.md', 'w') as f:
        f.write(md)
    print(md)


if __name__ == '__main__':
    main()
