#!/usr/bin/env python3
"""run_sim.py — P3.5 손계산 대조와 24조합(저장 3 × 스케줄러 4 × 연산 2) × 시드 실행

    python3 software/sim_develop/run_sim.py --selftest
    python3 software/sim_develop/run_sim.py                 # N=512, 시드 0~4
    python3 software/sim_develop/run_sim.py --tracks 640
    python3 software/sim_develop/run_sim.py --bw 2.0         # DDR3 대역폭을 낮춘 가상 조건(GB/s)
    python3 software/sim_develop/run_sim.py --sweep --dist zipf   # 대역폭 단계별 위반율, 조합별 최저 통과 대역폭
    python3 software/sim_develop/run_sim.py --lanes 64 --tracks 1024   # 확장 환경(막전위 DDR3)

결과: software/sim_result/sim_n{N}[_bw{BW}].jsonl (실행별), summary_n{N}[_bw{BW}].md (조합별, 시드 합산)
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
import sim_core  # noqa: E402
from sim_core import BW, C_REQ, MODEL_B, P, T0, make_workload, simulate  # noqa: E402
from policies import (COMPUTES, SCHEDULERS, STORAGES, AllAtOnce, FCFS, FullCache,  # noqa: E402
                      Dysta, Grouping, L1Resident, LazyGroup, PartialAll, PinnedHybrid, RowByRow,
                      ScoreGuard, ScoreWait, Stream, Timeout, TimeoutBatch)

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'sim_result')   # 결과는 software/sim_result
COMBOS = list(itertools.product(range(len(STORAGES)), range(len(SCHEDULERS)), range(len(COMPUTES))))


def selftest():
    ok = True

    def check(name, got, exp, tol):
        nonlocal ok
        good = abs(got - exp) <= tol
        ok &= good
        print(f'{"PASS" if good else "FAIL"}  {name}: 시뮬 {got:.6f}, 기대 {exp:.6f}')

    # 1. 트랙 1개: 응답 = d_in + 전송 + 연산 + d_out, 두 번째 요청부터는 캐시 적중이라 전송 0
    wl = make_workload(1, warm=0, meas=4, d_in=27.0, d_out=25.0, phase=100.0, track_model=[0])
    for C in (AllAtOnce, RowByRow):
        r = simulate(wl, FullCache(), FCFS(), C())['resp']
        if C is AllAtOnce:
            check('1a 트랙 1개 첫 요청(한번에) µs', r[0], 27 + T0 + MODEL_B / BW + C_REQ + 25, 1e-6)
        else:   # 한 줄씩은 전송·연산이 겹치므로 max(전송, 연산) ≤ 시간 ≤ 전송 + 연산
            lo, hi = 52 + max(T0 + MODEL_B / BW, C_REQ), 52 + T0 + MODEL_B / BW + C_REQ
            check('1b 트랙 1개 첫 요청(한줄씩) 범위 안', float(lo <= r[0] <= hi), 1.0, 0)
        check(f'1c 적중 요청({C.name}) µs', r[1:].max(), 27 + C_REQ + 25, 1e-6)

    # 2. 모든 트랙 동시 도착 + 그룹핑 + 캐시 5벌: 주기마다 사용 모델 수 × 131,588 B
    wl = make_workload(512, seed=1, d_in=0.0, d_out=0.0, phase=0.0)
    used = len(set(wl.track_model.tolist()))
    for C in (AllAtOnce, RowByRow):
        res = simulate(wl, FullCache(), Grouping(), C())
        check(f'2 완전 그룹핑 전송률({C.name}) MB/s', res['mbps'], used * MODEL_B / P, 1e-6)

    # 3. 캐시가 40모델을 모두 담으면 워밍업 뒤 전송 0
    res = simulate(wl, FullCache(entries=40), Grouping(), RowByRow())
    check('3 캐시 40벌 전송률 MB/s', res['mbps'], 0.0, 0)

    # 4. 연산 가동률 = N × 요청당 연산 / 주기 (실측 지연 표본, 위상 무작위)
    wl = make_workload(512, seed=2)
    res = simulate(wl, L1Resident(), Grouping(), RowByRow())
    check('4 연산 가동률', res['cmp_util'], 512 * C_REQ / P, 0.005)

    # ---- rev 2 (MODEL_SIZE_PLAN §4.2) ----
    # 5. 호스트 묶음 전송: 트랙 1개, 캐시 적중 요청의 응답 = 결과 읽기 시각 + C2H 지연 − 생성 시각
    wl = make_workload(1, warm=0, meas=6, phase=100.0, track_model=[0], host=1000.0)
    r = simulate(wl, FullCache(), FCFS(), AllAtOnce())['resp']
    fin = wl.t_arr[1:] + C_REQ
    j = np.ceil((fin - wl.out_phi) / 1000.0)
    exp = wl.out_phi + j * 1000.0 + wl.out_lat[j.astype(int)] - wl.t_gen[1:]
    check('5a 호스트 묶음 응답(적중) 최대 오차 µs', float(np.abs(r[1:] - exp).max()), 0.0, 1e-6)
    wait = wl.t_arr - wl.t_gen
    check('5b 입력 대기 + H2C ≤ W_h + 실측 최대', float(wait.max() <= 1000.0 + 120.3), 1.0, 0)
    # 동시 도착 512개는 H2C 1회(32 KiB): 지연 = 표본 + (512 × 64 − 64) / 758
    wl = make_workload(512, seed=3, phase=0.0, host=1000.0)
    w = wl.t_arr[wl.t_gen == wl.t_gen.min()] - wl.t_gen.min()
    lo = sim_core.load_samples(sim_core.H_IN_FILE).min() + (512 * 64 - 64) / 758.0
    hi = 1000.0 + sim_core.load_samples(sim_core.H_IN_FILE).max() + (512 * 64 - 64) / 758.0
    check('5c 동시 도착 512개 지연이 [표본 최소 + 크기 항, W_h + 표본 최대 + 크기 항] 안', float(lo <= w[0] <= hi), 1.0, 0)
    check('5d 동시 도착은 한 번에 도착(같은 시각)', float(np.ptp(w)), 0.0, 1e-9)

    # 6. 막전위 DDR3 비용(rev 2): 읽기 1,412 / 3,015 + 쓰기 1,412 / 2,768 B/µs
    sim_core.configure(64, 1024, mem='ddr', rev=2)
    check('6 막전위 왕복 DMA µs/요청', sim_core.mem_time(1), 1412 / 3015 + 1412 / 2768, 1e-9)

    # 7. 한 줄씩 묶음 ≤ 64 (rev 2, 막전위 온칩): 같은 모델 512트랙 동시 도착 → 주기마다 묶음 8개 × 64
    sim_core.configure(32, 512, mem='onchip', rev=2)
    wl = make_workload(512, seed=1, d_in=0.0, d_out=0.0, phase=0.0, track_model=[0] * 512)
    res = simulate(wl, FullCache(), Grouping(), RowByRow())
    check('7 한 줄씩 묶음 평균(상한 64)', res['batch_mean'], 64.0, 1e-9)

    # ---- 목표 트랙 실험 (target_exp.py) ----
    # 8. 사이클 회계: 트랙 1개, 첫 요청만 미스. 연산 = 4 × 요청당 연산, 정지 = 첫 적재, 유휴 = 나머지
    sim_core.configure()
    wl = make_workload(1, warm=0, meas=4, d_in=27.0, d_out=25.0, phase=100.0, track_model=[0])
    res = simulate(wl, FullCache(), FCFS(), AllAtOnce(), detail=True)
    ld = sim_core.T0 + sim_core.MODEL_B / sim_core.BW
    check('8a 연산 사이클', res['cyc_busy'], 4 * sim_core.C_REQ * 100, 1e-6)
    check('8b 정지 사이클 = 첫 모델 적재', res['cyc_stall'], ld * 100, 1e-6)
    check('8c 연산 + 정지 + 유휴 = 측정 구간', res['cyc_busy'] + res['cyc_stall'] + res['cyc_idle'], 4 * P * 100, 1e-3)
    check('8d 응답 분해 입력 + FPGA + 출력 = 평균 응답 ms', res['in_ms'] + res['fpga_ms'] + res['out_ms'], res['mean_ms'], 1e-9)
    check('8e FPGA 체류 평균 ms', res['fpga_ms'], (ld + 4 * sim_core.C_REQ) / 4 / 1000, 1e-9)
    # 9. 실측 지연 표본·무작위 위상(한 줄씩): 연산 ≤ FPGA 체류 구간, 연산 사이클 ≈ 가동률 × 구간
    wl = make_workload(512, seed=2)
    res = simulate(wl, FullCache(), Grouping(), RowByRow(), detail=True)
    span = (wl.w1 - wl.w0) * 100
    check('9a 연산 + 정지 + 유휴 = 측정 구간', res['cyc_busy'] + res['cyc_stall'] + res['cyc_idle'], span, 1e-3)
    check('9b 정지 ≥ 0', float(res['cyc_stall'] >= 0), 1.0, 0)
    check('9c 연산 사이클 / 구간 ≈ 연산 가동률', res['cyc_busy'] / span, res['cmp_util'], 0.002)
    # 10. 예산 맞춤 B는 L 32레인 기준 환경에서 B.L1상주와 같다(층 1 전체 + β·vth 상주)
    c = RowByRow()
    b, b0 = PartialAll(compute=c), L1Resident()
    check('10 B.부분상주 = B.L1상주 (L 32레인)', float(b.k == sim_core.N_L1 and b.bv and b.loads == sim_core.L2L4
                                                    and b.tiles() + c.extra_tiles(b) == b0.tiles() + c.extra_tiles(b0)), 1.0, 0)
    # 11. 고정 혼합: 고정 모델만 쓰는 트랙은 첫 요청부터 전송 없이 연산
    wl = make_workload(1, warm=0, meas=4, d_in=27.0, d_out=25.0, phase=100.0, track_model=[0])
    for C in (AllAtOnce, RowByRow):
        res = simulate(wl, PinnedHybrid(compute=C()), FCFS(), C())
        check(f'11 고정 모델 응답({C.name}) µs', res['resp'].max(), 27 + C_REQ + 25, 1e-6)
    # 12. rev 4 슬라이스 칸: XL 256레인은 층 2 그룹 768 word, L 32레인은 rev 3과 같음
    sim_core.configure(256, 1024, mem='ddr', rev=4, arch=(40, 768, 512, 128, 2))
    check('12a XL 256레인 칸 word', sim_core.SLOT_WORDS, 768, 0)
    check('12b XL 256레인 이중 버퍼 타일', sim_core.SLICE_T, 85.5, 0)
    sim_core.configure(32, 512, rev=4)
    check('12c L 32레인 이중 버퍼 타일(rev 3과 같음)', sim_core.SLICE_T, 7.5, 0)
    sim_core.configure()

    # ---- 점수 방식 개선 (점수2·3) ----
    # 13. 마감 가드 손계산(L 32레인, 막전위 온칩이라 막전위 DMA 0): 후보 (마감, 모델, n, 남은 전송)
    g = ScoreGuard(margin=0.0)
    cand = [(500.0, 0, 1, 100.0), (20000.0, 1, 10, 0.0)]
    check('13a 가장 늦은 시작 = min(500 − (100 + C), 20,000 − (100 + 11C))', g._latest_start(cand),
          min(500 - (100 + C_REQ), 20000 - (100 + 11 * C_REQ)), 1e-9)
    check('13b 모델 1을 먼저 하면 모델 0이 늦음 → 불가', float(g._safe(cand[1], cand, 0.0)), 0.0, 0)
    cand[0] = (10000.0, 0, 1, 100.0)
    check('13c 모델 0 마감이 넉넉하면 → 가능', float(g._safe(cand[1], cand, 0.0)), 1.0, 0)
    # 14. 점수3: 트랙 1개는 다음 요청이 32 ms 뒤라 기다리지 않는다 → 1a와 같은 응답
    wl = make_workload(1, warm=0, meas=4, d_in=27.0, d_out=25.0, phase=100.0, track_model=[0])
    r = simulate(wl, FullCache(), ScoreWait(margin=0.0), AllAtOnce())['resp']
    check('14 점수3 트랙 1개 첫 요청 µs (기다리지 않음)', r[0], 27 + T0 + MODEL_B / BW + C_REQ + 25, 1e-6)
    # 15. 점수3: 같은 모델 트랙 2개(위상 0, 1 ms)는 두 번째 요청을 기다려 한 묶음 → 주기마다 모델 1번 적재(스트림)
    wl = make_workload(2, warm=0, meas=4, d_in=27.0, d_out=25.0, phase=[0.0, 1000.0], track_model=[0, 0])
    for Q, per in ((Grouping, 2), (ScoreWait, 1)):
        res = simulate(wl, Stream(), Q(margin=0.0) if Q is ScoreWait else Q(), AllAtOnce())
        check(f'15 {Q.name} 요청당 가중치 B (주기마다 적재 {per}번)', res['w_bytes'] / res['req_win'], MODEL_B * per / 2, 1e-6)
    # 16. 시간제한 묶음: 같은 모델 트랙 2개가 10 ms 간격이면 W = 8 ms는 따로(적재 2번), W = 16 ms는 함께(1번)
    wl = make_workload(2, warm=0, meas=4, d_in=27.0, d_out=25.0, phase=[0.0, 10000.0], track_model=[0, 0])
    for W, per in ((8000.0, 2), (16000.0, 1)):
        res = simulate(wl, Stream(), TimeoutBatch(margin=0.0, max_wait=W), AllAtOnce())
        check(f'16 시간제한 W = {W / 1000:.0f} ms 요청당 가중치 B (적재 {per}번)', res['w_bytes'] / res['req_win'],
              MODEL_B * per / 2, 1e-6)
    # 17. 지연 그룹핑도 마감 여유 안이면 두 번째 요청을 기다려 한 묶음(적재 1번), 첫 요청 응답 = 10 ms 대기 + 전송 + 연산 2개
    res = simulate(wl, Stream(), LazyGroup(margin=0.0), AllAtOnce())
    check('17a 지연 그룹핑 요청당 가중치 B (적재 1번)', res['w_bytes'] / res['req_win'], MODEL_B / 2, 1e-6)
    check('17b 지연 그룹핑 첫 요청 응답 µs', res['resp'][0], 10000 + 27 + T0 + MODEL_B / BW + C_REQ + 25, 1e-6)
    # 18. Dysta식은 기다리지 않는다: 트랙 1개 첫 요청 = 1a
    wl = make_workload(1, warm=0, meas=4, d_in=27.0, d_out=25.0, phase=100.0, track_model=[0])
    r = simulate(wl, FullCache(), Dysta(margin=0.0), AllAtOnce())['resp']
    check('18 Dysta식 트랙 1개 첫 요청 µs', r[0], 27 + T0 + MODEL_B / BW + C_REQ + 25, 1e-6)
    # 19. Timeout(가드 없음): 트랙 1개 첫 요청은 도착 뒤 W를 기다린 다음 처리
    r = simulate(wl, FullCache(), Timeout(max_wait=3000.0), AllAtOnce())['resp']
    check('19 Timeout W = 3 ms 트랙 1개 첫 요청 µs', r[0], 27 + 3000 + T0 + MODEL_B / BW + C_REQ + 25, 1e-6)
    return ok


def run_one(job):
    si, qi, ci, seed, n, bw, dist, keep, lanes, scen = job
    sim_core.configure(lanes, n)
    sim_core.BW = bw * 1000.0                     # GB/s → B/µs
    st, q, c = STORAGES[si](), SCHEDULERS[qi](), COMPUTES[ci]()
    kw = dict(sim_core.SCENARIOS[scen])
    if dist != 'uniform':
        kw['dist'] = dist
    res = simulate(make_workload(n, seed, **kw), st, q, c)
    res.update(storage=st.name, scheduler=q.name, compute=c.name, seed=seed, tracks=n, bw=bw, dist=kw.get('dist', 'uniform'), lanes=lanes, scenario=scen,
               tiles=st.tiles() + c.extra_tiles(st))
    if not keep:
        del res['resp']
    return (si, qi, ci), res


SWEEP_BW = [3.015, 2.0, 1.5, 1.0, 0.75, 0.5, 0.35, 0.25, 0.2, 0.15, 0.1]


def summarize_sweep(rows, n, seeds, dist):
    miss, tot, info = {}, {}, {}
    for key, r in rows:
        kb = (key, r['bw'])
        miss[kb] = miss.get(kb, 0) + r['miss']
        tot[kb] = tot.get(kb, 0) + r['n_req']
        info[key] = r
    lines = [f'# 대역폭 단계별 마감 위반율 — {sim_core.LANES}레인, N={n}, 시나리오 {rows[0][1]["scenario"]}, 모델 분포 {rows[0][1]["dist"]}, 시드 {seeds}개\n',
             '시뮬레이션 값(가상 대역폭). 칸은 위반율 %(0 = 위반 없음, 위 단계에서 100 %면 아래 단계는 실행 생략). 최저 통과 = 그 대역폭과 그 위의 모든 '
             f'단계에서 위반 0인 가장 낮은 대역폭. BRAM 예산 {sim_core.TILE_BUDGET:g} 타일'
             f'{", 막전위 DDR3" if sim_core.MEM_OFFCHIP else ""}.\n',
             '| 저장 | 스케줄러 | 연산 | BRAM | ' + ' | '.join(f'{b:g}' for b in SWEEP_BW) + ' | 최저 통과 GB/s |',
             '|---|---|---|---:|' + '---:|' * len(SWEEP_BW) + '---:|']
    for key in COMBOS:
        r, cells, low, ok = info[key], [], None, True
        for b in SWEEP_BW:
            x = miss[(key, b)] / tot[(key, b)] * 100
            cells.append('0' if x == 0 else (f'{x:.2f}' if x < 1 else f'{x:.0f}'))
            ok &= x == 0
            if ok:
                low = b
        t = r['tiles']
        lines.append(f"| {r['storage']} | {r['scheduler']} | {r['compute']} | {t:g}{'' if t <= sim_core.TILE_BUDGET else ' 초과'} | "
                     + ' | '.join(cells) + f" | {'—' if low is None else f'**{low:g}**'} |")
    return '\n'.join(lines) + '\n'


def summarize(rows, n, seeds, bw):
    by = {}
    for key, r in rows:
        by.setdefault(key, []).append(r)
    lines = [f'# 24조합 시뮬레이션 결과 — {sim_core.LANES}레인, N={n}, DDR3 {bw:g} GB/s, 시나리오 {rows[0][1]["scenario"]}, 모델 분포 {rows[0][1]["dist"]}, 시드 {seeds}개\n',
             f'시뮬레이션 값. 측정 구간 64주기(2.048 s, 워밍업 16주기 제외), 시드 합산. '
             f'BRAM은 가중치·β·vth·적재 버퍼 타일, 예산 {sim_core.TILE_BUDGET:g}'
             f'{" (막전위 DDR3, 가동률에 막전위 이동 포함)" if sim_core.MEM_OFFCHIP else ""}.\n',
             '| 저장 | 스케줄러 | 연산 | BRAM | 위반율 % | 위반 수 | 전송 MB/s | p99 ms | 최악 ms '
             '| 평균 묶음 | 적중률 | DMA·연산 가동률 |',
             '|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|']
    for key in COMBOS:
        rs = by[key]
        resp = np.concatenate([r['resp'] for r in rs])
        miss = sum(r['miss'] for r in rs)
        t = rs[0]['tiles']
        lines.append(
            f"| {rs[0]['storage']} | {rs[0]['scheduler']} | {rs[0]['compute']} | "
            f"{t:g}{'' if t <= sim_core.TILE_BUDGET else ' 초과'} | {miss / resp.size * 100:.3f} | {miss:,} | "
            f"{np.mean([r['mbps'] for r in rs]):.1f} | {np.percentile(resp, 99) / 1000:.2f} | "
            f"{resp.max() / 1000:.2f} | {np.mean([r['batch_mean'] for r in rs]):.2f} | "
            f"{np.mean([r['hit_rate'] for r in rs]):.2f} | "
            f"{np.mean([r['dma_util'] for r in rs]):.2f} · {np.mean([r['cmp_util'] for r in rs]):.2f} |")
    return '\n'.join(lines) + '\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--tracks', type=int, default=512)
    ap.add_argument('--seeds', type=int, default=5)
    ap.add_argument('--jobs', type=int, default=10)
    ap.add_argument('--bw', type=float, default=BW / 1000, help='DDR3 대역폭 GB/s (기본 실측 3.015)')
    ap.add_argument('--dist', choices=['uniform', 'zipf'], default='uniform', help='트랙→모델 배정')
    ap.add_argument('--sweep', action='store_true', help='SWEEP_BW 대역폭 단계 전체 실행')
    ap.add_argument('--lanes', type=int, default=32, choices=[32, 64], help='연산 레인 수')
    ap.add_argument('--scenario', default='U', choices=list(sim_core.SCENARIOS), help='요청 시나리오(MODEL_SIZE_PLAN §2.1)')
    a = ap.parse_args()
    if a.selftest:
        sys.exit(0 if selftest() else 1)

    sim_core.configure(a.lanes, a.tracks)
    lt = ('' if a.lanes == 32 else f'_l{a.lanes}') + ('' if a.scenario == 'U' else f'_{a.scenario}')
    t0 = time.time()
    os.makedirs(OUT, exist_ok=True)
    if a.sweep:
        # 대역폭을 내려가며 실행. 한 단계에서 모든 시드가 위반 100 %인 조합은 아래 단계를 생략하고 100 %로 채운다
        rows, dead, n_jobs = [], {}, 0
        with Pool(a.jobs) as pool:
            for b in SWEEP_BW:
                jobs = [(*c, s, a.tracks, b, a.dist, False, a.lanes, a.scenario)
                        for c in COMBOS if c not in dead for s in range(a.seeds)]
                n_jobs += len(jobs)
                out = pool.map(run_one, jobs, chunksize=1)
                rows += out
                for c in COMBOS:
                    if c in dead:
                        rows += [(c, dict(r, bw=b, skipped=True)) for r in dead[c]]
                    else:
                        rs = [r for k, r in out if k == c]
                        if all(r['miss'] == r['n_req'] for r in rs):
                            dead[c] = rs
        jobs = range(n_jobs)
        tag = f'n{a.tracks}{lt}_{a.dist}'
        with open(os.path.join(OUT, f'sweep_{tag}.jsonl'), 'w') as f:
            for _, r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
        md = summarize_sweep(rows, a.tracks, a.seeds, a.dist)
        with open(os.path.join(OUT, f'sweep_{tag}.md'), 'w') as f:
            f.write(md)
        print(md)
        print(f'{len(jobs)}회 실행, {time.time() - t0:.0f} s')
        return

    jobs = [(*c, s, a.tracks, a.bw, a.dist, True, a.lanes, a.scenario) for c in COMBOS for s in range(a.seeds)]
    tag = f'n{a.tracks}{lt}' + ('' if a.bw == BW / 1000 else f'_bw{a.bw:g}') + ('' if a.dist == 'uniform' else f'_{a.dist}')
    with Pool(a.jobs) as pool:
        rows = pool.map(run_one, jobs)
    with open(os.path.join(OUT, f'sim_{tag}.jsonl'), 'w') as f:
        for _, r in rows:
            f.write(json.dumps({k: v for k, v in r.items() if k != 'resp'}, ensure_ascii=False) + '\n')
    md = summarize(rows, a.tracks, a.seeds, a.bw)
    with open(os.path.join(OUT, f'summary_{tag}.md'), 'w') as f:
        f.write(md)
    print(md)
    print(f'{len(jobs)}회 실행, {time.time() - t0:.0f} s')


if __name__ == '__main__':
    main()
