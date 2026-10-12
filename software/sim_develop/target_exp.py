#!/usr/bin/env python3
"""target_exp.py — P3.8 마무리 실험: XL 모델 · 256레인 · 막전위 DDR3 (P3.6~3.8 리포트 확정안)

  1단계 cap     설계 × 시나리오마다 마감 위반 0인 최대 트랙 수(시드 3, 16트랙 단위)
  2단계 verify  시나리오별 최고 설계와 전 시나리오 최고 설계를 시드 20으로 확인 + 동시 도착(S·SK) 최악 위상 해석 상한
  3단계 fixed   목표 트랙 수 N에서 설계마다 위반율·평균 처리 시간·오프칩 접근·사이클(시나리오 6 × 시드 20)

설계 = 저장 4 × 스케줄러 4(FCFS, EDF, 그룹핑, 점수) × 연산 2(한 번에, 한 줄씩) = 32.
  저장: A 전체 캐시(엔트리 LRU), B 부분 상주(40모델 앞쪽 그룹), C 고정 혼합(인기 모델 엔트리 고정 + 층 1 상주), D 스트림.
  중간보고의 세 저장 정책 A·B·C가 24조합이고, D(가중치 보관 없음)는 참고 8조합이다.
  B·C는 XL 256레인 BRAM 예산에 맞게 다시 정의했다(policies.PartialAll, PinnedHybrid). 원래 정의는 배치 불가였다.
시뮬레이터 rev 4 = rev 3 + 슬라이스 이중 버퍼 칸을 가장 큰 뉴런 그룹(층 2, 768 word)에 맞춤(sim_core.configure).

    python3 software/sim_develop/target_exp.py --stage cap               → sim_result/p38_cap.{jsonl,md}
    python3 software/sim_develop/target_exp.py --stage verify            → sim_result/p38_verify.{jsonl,md}
    python3 software/sim_develop/target_exp.py --stage fixed --n 1024    → sim_result/p38_fixed_n1024.{jsonl,md}
    python3 software/sim_develop/target_exp.py --stage margin --n 1024   → sim_result/p38_margin_n1024.{jsonl,md} (목표 여유)
스케줄러 비교(점수 방식 개선): --sch grouping,score,score_nocap,score2,score3 --prefix p38s → sim_result/p38s_*
스케줄러 후보 비교(문헌 기반): --sch grouping,score2,score3,dysta,lazy,timeout,timeout16,score3r,lazyr --prefix p38t
    --only A:한번에,A:한줄씩,D:한줄씩 → sim_result/p38t_*,  간이 가드: --sch grouping,lazys --prefix p38t2 → sim_result/p38t2_*
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
import dse  # noqa: E402
import sim_core as sc  # noqa: E402
from policies import (EDF, FCFS, STORAGES_FIT, AllAtOnce, Grouping, RowByRow,  # noqa: E402
                      Dysta, LazyGroup, LazyGroupSimple, Score, SlackBatch, SlackBatchLite, Timeout, ScoreGuard, ScoreNoCap, ScoreWait, TimeoutBatch, TimeoutBatch16,
                      robust)

ARCH = (40, 768, 512, 128, 2)
LANES, MEM, REV, HOST = 256, 'ddr', 4, 1000.0
SCEN = ['U', 'K', 'S', 'I', 'SK', 'R']
STO, SCH, CMP = STORAGES_FIT, [FCFS, EDF, Grouping, Score], [AllAtOnce, RowByRow]
MAIN = {'A.전체캐시', 'B.부분상주', 'C.고정혼합'}           # 중간보고 저장 정책 3종 = 24조합
STEP, SEEDS_CAP, SEEDS_VERIFY = 16, 3, 20
# 요청 큐·트랙 메타를 분산 RAM에 둘 때의 LUT (P3.2 fit: 512트랙 큐·메타 = 10,111 − 4,639 = 5,472 LUT)
LUT_PER_TRACK = 5472 / 512
LUTRAM_FREE = 46200 - 4639          # XC7A200T LUT as Memory 46,200 − 큐 외 사용(fit 4111 구성)
OUT = dse.OUT
DESIGNS = list(itertools.product(range(len(STO)), range(len(SCH)), range(len(CMP))))
PREFIX = 'p38'                     # 결과 파일 접두사. --sch로 스케줄러를 바꾸면 --prefix로 따로 둔다
SCH_BY_KEY = {'fcfs': FCFS, 'edf': EDF, 'grouping': Grouping, 'score': Score, 'score_nocap': ScoreNoCap,
              'score2': ScoreGuard, 'score3': ScoreWait, 'dysta': Dysta, 'lazy': LazyGroup, 'lazys': LazyGroupSimple,
              'timeout': TimeoutBatch, 'timeout16': TimeoutBatch16,
              'score2r': robust(ScoreGuard), 'score3r': robust(ScoreWait), 'lazyr': robust(LazyGroup),
              'timeoutr': robust(TimeoutBatch)}


def renamed(cls, nm, **attrs):
    """같은 동작에 결과 표·그림용 이름만 바꾼 클래스"""
    return type(cls.__name__ + '_' + nm.replace('-', '_'), (cls,), dict(name=nm, **attrs))


# 최종 비교 대상(MODEL_SIZE_PLAN §5.12): 기존 FCFS·EDF·Grouping, 선행연구 Dysta(B03)·Timeout(동적 배칭 대기 상한, 가드 없음),
# 제안 SlackBatch-Lite·SlackBatch. Timeout의 W는 설계마다 조정 시드(100~104)에서 위반 0인 가장 큰 값(선행연구에 유리하게)
FINAL_TIMEOUT_W = {('A', '한번에'): 5000.0, ('A', '한줄씩'): 5000.0, ('D', '한줄씩'): 2000.0}
SCH_BY_KEY.update({'final_grouping': renamed(Grouping, 'Grouping'), 'final_dysta': renamed(Dysta, 'Dysta'),
                   'final_timeout': Timeout, 'slackbatch': SlackBatch,
                   'slackbatch_lite': SlackBatchLite})
PCIE_WORST = 795.3                 # µs, P1.7 H2C 64 B 62.5 µs 간격 측정의 관측 최대(P3.3 리포트 §4). 강건 변형의 회수 여유
CFG = dict(rev=REV, host=HOST, step=STEP, arch=ARCH)        # dse.s_worst_bound용


def lutram_cap():
    """요청 큐·트랙 메타를 분산 RAM에 둘 때 들어가는 최대 트랙 수(STEP 배수)"""
    return int(LUTRAM_FREE / LUT_PER_TRACK) // STEP * STEP


def build(d, n):
    si, qi, ci = d
    sc.configure(LANES, n, mem=MEM, rev=REV, arch=ARCH)
    c = CMP[ci]()
    st = STO[si](budget=sc.TILE_BUDGET - c.mem_tiles(), compute=c)
    t = st.tiles() + c.extra_tiles(st)
    ok = t <= sc.TILE_BUDGET and (not st.uses_entry or st.E >= 2)   # 엔트리 LRU는 2벌 이상이어야 적재·연산이 겹침
    q = SCH[qi]()
    if isinstance(q, Timeout):
        q.W = FINAL_TIMEOUT_W.get((STO[si].name[0], CMP[ci].name), 4000.0)
    if isinstance(q, ScoreGuard):                         # 점수2·3: 결과 회수 여유와 묶음 한도
        worst = PCIE_WORST if q.robust else sc.load_samples(sc.H_OUT_FILE).max()
        q.margin = HOST + worst + 20.0          # 결과 회수: 읽기 대기 W_h + C2H 최악(표준: 1 ms 주기 표본 최대, 강건: 실측 최악) + 여분
        q.cap = c.max_batch()
    return st, q, c, t, ok


def name(d):
    si, qi, ci = d
    return dict(storage=STO[si].name, scheduler=SCH[qi].name, compute=CMP[ci].name)


def label(r):
    return f"{r['storage']} · {r['scheduler']} · {r['compute']}"


def workload(n, seed, scn, host=HOST, tail=0.0):
    wl = sc.make_workload(n, seed, host=host, **sc.SCENARIOS[scn])
    if tail:                                         # 모든 H2C·C2H 전송에 꼬리 지연을 더함(dse.workload와 같음)
        wl.t_arr = wl.t_arr + tail
        wl.out_lat = wl.out_lat + tail
    return wl


def storage_info(st):
    """저장 정책의 크기 정보(표에 적음)"""
    out = {}
    for k in ('E', 'R', 'k', 'bv'):
        if hasattr(st, k):
            out[k] = getattr(st, k)
    return out


def passes(d, n, scns, seeds):
    st, q, c, t, ok = build(d, n)
    if not ok:
        return False
    for scn in scns:
        for seed in seeds:
            if sc.simulate(workload(n, seed, scn), st, q, c, stop_on_miss=True)['miss']:
                return False
    return True


# ---- 1단계: 설계 × 시나리오 최대 트랙 ---------------------------------------------------
def activity(scn):
    """주기마다 요청을 내는 트랙의 평균 비율 (I: p_req, R: 혼잡도 범위의 평균, 나머지 1)"""
    kw = sc.SCENARIOS[scn]
    if 'p_req' in kw:
        return kw['p_req']
    if 'congestion' in kw:
        return sum(kw['congestion']) / 2
    return 1.0


def stable_cap(scn):
    """평균 연산 가동률 ≤ 100 %인 가장 큰 STEP 배수. 이보다 크면 큐가 길게 보면 끝없이 쌓이므로
    2.56 s 시뮬레이션을 통과해도 최대 트랙으로 인정하지 않는다"""
    sc.configure(LANES, 1024, mem=MEM, rev=REV, arch=ARCH)
    return int(sc.P / (sc.C_REQ * activity(scn))) // STEP * STEP


def capacity(job):
    """위반 0인 가장 큰 STEP 배수. 2배씩 키워 실패 지점을 찾은 뒤 이분 탐색(통과가 N에 대해 단조라고 가정).
    상한은 stable_cap"""
    d, scn = job
    seeds = range(SEEDS_CAP)
    cap = stable_cap(scn)
    lo, x, fail = 0, STEP, None
    while True:
        if passes(d, x, [scn], seeds):
            lo = x
            if x >= cap:
                break
            x = min(2 * x, cap)
        else:
            fail = x
            break
    if fail is not None:
        a, b = lo // STEP, fail // STEP - 1
        while a < b:
            mid = (a + b + 1) // 2
            if passes(d, mid * STEP, [scn], seeds):
                a = mid
            else:
                b = mid - 1
        lo = a * STEP
    n = lo
    st, _, _, t, ok = build(d, max(n, STEP))
    return dict(**name(d), scenario=scn, capacity=n, tiles=t, feasible=ok, **storage_info(st),
                cmp_util=round(n * activity(scn) * sc.C_REQ / sc.P, 4), capped=n >= cap, cap=cap)


def stage_cap(jobs):
    todo = [(d, s) for d in DESIGNS for s in SCEN]
    todo.sort(key=lambda j: (j[1] != 'I', j[0][1] < 2))      # 오래 걸리는 I·묶음 스케줄러부터
    with Pool(jobs) as p:
        rows = p.map(capacity, todo, chunksize=1)
    with open(os.path.join(OUT, f'{PREFIX}_cap.jsonl'), 'w') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    md = cap_table(rows)
    with open(os.path.join(OUT, f'{PREFIX}_cap.md'), 'w') as f:
        f.write(md)
    print(md)


def cap_index(rows):
    return {(r['storage'], r['scheduler'], r['compute'], r['scenario']): r for r in rows}


def cap_table(rows):
    ix = cap_index(rows)
    sc.configure(LANES, 1024, mem=MEM, rev=REV, arch=ARCH)
    lines = [f'# 1단계: 설계 × 시나리오별 최대 트랙 수 — XL {"→".join(map(str, ARCH))} INT8, {LANES}레인, 막전위 DDR3, rev {REV}\n',
             f'시뮬레이션 값. 칸 = 그 시나리오에서 마감 위반 0인 최대 트랙 수(시드 {SEEDS_CAP}개, {STEP}트랙 단위). '
             f'전 시나리오 = 여섯 칸의 최솟값. 연산 한계 = 32 ms ÷ 요청당 연산 {sc.C_REQ:.3f} µs = {int(sc.P / sc.C_REQ):,}트랙'
             f'(활성 비율 100 % 기준). 탐색 상한 = 평균 연산 가동률 100 % 이하인 {STEP}의 배수: '
             + ', '.join(f'{s} {stable_cap(s):,}' for s in SCEN) + '. 상한에 닿은 칸은 *기울임*. '
             f'BRAM 예산 {sc.TILE_BUDGET:g} 타일.\n',
             '| 저장 · 스케줄러 · 연산 | BRAM | ' + ' | '.join(SCEN) + ' | 전 시나리오 |',
             '|---|---:|' + '---:|' * (len(SCEN) + 1)]
    for d in DESIGNS:
        nm = name(d)
        rs = [ix[(nm['storage'], nm['scheduler'], nm['compute'], s)] for s in SCEN]
        mark = '' if nm['storage'] in MAIN else ' (참고)'
        cell = [f"*{r['capacity']:,}*" if r['capped'] else f"{r['capacity']:,}" for r in rs]
        lines.append(f"| {label(nm)}{mark} | {rs[0]['tiles']:g} | " + ' | '.join(cell)
                     + f" | **{min(r['capacity'] for r in rs):,}** |")
    lines += ['\n## 시나리오별 최고 설계 (1단계)\n', '| 시나리오 | 최대 트랙 | 설계 |', '|---|---:|---|']
    for s in SCEN:
        top = max(r['capacity'] for r in rows if r['scenario'] == s)
        best = [label(r) for r in rows if r['scenario'] == s and r['capacity'] == top]
        lines.append(f"| {s} | {top:,} | {', '.join(best)} |")
    return '\n'.join(lines) + '\n'


# ---- 2단계: 시드 20 확인 ----------------------------------------------------------------
def verify_one(d, n, scns):
    st, q, c, t, ok = build(d, n)
    worst, miss, fails = 0.0, 0, []
    for scn in scns:
        for seed in range(SEEDS_VERIFY):
            r = sc.simulate(workload(n, seed, scn), st, q, c)
            worst = max(worst, r['max_ms'])
            miss += r['miss']
            if r['miss']:
                fails.append(f'{scn}/{seed}')
    return dict(n=n, ok=miss == 0, worst_ms=round(worst, 3), miss=miss, fails=fails[:6])


def verify_scan(job):
    """1단계 값에서 시작. 통과하면 한 단계 위도 확인하고(가동률 상한 안에서만), 실패하면 통과할 때까지 한 단계씩 내린다"""
    kind, d, scns, n0 = job
    cap = min(stable_cap(s) for s in scns)
    out = [verify_one(d, n0, scns)]
    if out[-1]['ok'] and n0 + STEP <= cap:
        out.append(verify_one(d, n0 + STEP, scns))
    else:
        n = n0
        while not out[-1]['ok'] and n > STEP:
            n -= STEP
            out.append(verify_one(d, n, scns))
    passed = max((v['n'] for v in out if v['ok']), default=0)
    return dict(kind=kind, **name(d), scenarios='·'.join(scns), stage1=n0, verified=passed, runs=out,
                cap=cap, capped=passed >= cap)


def stage_verify(jobs):
    with open(os.path.join(OUT, f'{PREFIX}_cap.jsonl')) as f:
        rows = [json.loads(x) for x in f]
    ix = cap_index(rows)
    di = {(STO[a].name, SCH[b].name, CMP[c].name): (a, b, c) for a, b, c in DESIGNS}
    todo = []
    for s in SCEN:                                     # 시나리오별 최고 설계 (같으면 BRAM이 적은 것)
        r = max((r for r in rows if r['scenario'] == s), key=lambda r: (r['capacity'], -r['tiles']))
        todo.append(('scenario', di[(r['storage'], r['scheduler'], r['compute'])], [s], r['capacity']))
    allmin = {k: min(ix[(*k, s)]['capacity'] for s in SCEN) for k in di}
    for sto in [s.name for s in STO]:                  # 저장 정책마다 전 시나리오 최고 설계
        if not any(k[0] == sto for k in di):           # --only로 뺀 저장 정책
            continue
        k = max((k for k in di if k[0] == sto), key=lambda k: (allmin[k], -ix[(*k, 'U')]['tiles']))
        todo.append(('all', di[k], SCEN, allmin[k]))
    if len({q.name for q in SCH} - {'FCFS', 'EDF'}) > 2:   # 스케줄러 비교 실행: 스케줄러마다 전 시나리오 최고 설계
        for q in SCH:
            k = max((k for k in di if k[1] == q.name), key=lambda k: (allmin[k], -ix[(*k, 'U')]['tiles']))
            if di[k] not in [t[1] for t in todo if t[0] == 'all']:
                todo.append(('all', di[k], SCEN, allmin[k]))
    with Pool(jobs) as p:
        res = p.map(verify_scan, todo, chunksize=1)
    bound = dse.s_worst_bound(LANES, CFG)
    for r in res:
        sync = any(s in ('S', 'SK') for s in r['scenarios'].split('·'))
        r['s_bound'] = bound if sync else None
        r['guaranteed'] = min(r['verified'], bound) if sync else r['verified']
    with open(os.path.join(OUT, f'{PREFIX}_verify.jsonl'), 'w') as f:
        for r in res:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    sc.configure(LANES, 1024, mem=MEM, rev=REV, arch=ARCH)
    lines = ['# 2단계: 시드 20 확인과 보장값\n',
             f'1단계 값에서 시작해 시드 {SEEDS_VERIFY}개 전체를 실행하고, 통과하면 한 단계 위를, 실패하면 통과할 때까지 한 단계씩 내렸다. '
             '최대 응답 = 측정 구간 모든 요청의 최대(생성 → 결과가 호스트에 도착). 동시 도착(S·SK)은 호스트 입출력 위상이 최악인 경우의 '
             f'해석 상한 {bound:,}트랙(dse.s_worst_bound)과 비교해 작은 값을 보장값으로 쓴다. '
             f'큐·메타 분산 RAM LUT = 트랙 × {LUT_PER_TRACK:.2f}(P3.2 fit), 쓸 수 있는 분산 RAM {LUTRAM_FREE:,} LUT → '
             f'분산 RAM 한계 {lutram_cap():,}트랙. 가동률 상한에 닿은 값은 *기울임*.\n',
             '| 구분 | 시나리오 | 설계 | 1단계 | 시드 20 통과 | 최대 응답 ms (통과 N) | 해석 상한 | **보장값** | 큐 LUT (분산 RAM %) | 실행 기록 (N: 위반) |',
             '|---|---|---|---:|---:|---:|---:|---:|---:|---|']
    for r in res:
        okr = [v for v in r['runs'] if v['n'] == r['verified']]
        g = r['guaranteed']
        lut = g * LUT_PER_TRACK
        sb = '–' if r['s_bound'] is None else f"{r['s_bound']:,}"
        lines.append(f"| {'시나리오별' if r['kind'] == 'scenario' else '전 시나리오'} | {r['scenarios']} | {label(r)} | "
                     f"{r['stage1']:,} | {r['verified']:,} | {okr[0]['worst_ms'] if okr else '–'} | {sb} | "
                     f"**{'*' if r['capped'] else ''}{g:,}{'*' if r['capped'] else ''}** | {lut:,.0f} ({lut / LUTRAM_FREE * 100:.0f} %) | "
                     + ', '.join(f"{v['n']:,}: {v['miss']}" for v in r['runs']) + ' |')
    md = '\n'.join(lines) + '\n'
    with open(os.path.join(OUT, f'{PREFIX}_verify.md'), 'w') as f:
        f.write(md)
    print(md)


# ---- 3단계: 목표 트랙 수에서 설계별 운영 지표 ------------------------------------------------
SUMS = ('n_req', 'miss', 'w_bytes', 'm_bytes', 'w_xfers', 'req_win', 'cyc_busy', 'cyc_stall', 'cyc_idle', 'cyc_n')


def _agg(runs, resp):
    """실행 여러 개를 합친 지표. 비율·요청당 값은 합을 나눠 낸다(실행마다 요청 수가 달라도 요청 기준)"""
    a = {k: sum(r[k] for r in runs) for k in SUMS}
    span = sum(r['cyc_busy'] + r['cyc_stall'] + r['cyc_idle'] for r in runs)
    nb = sum(r['req_win'] / r['batch_mean'] for r in runs if r['batch_mean'])
    rr = np.concatenate(resp) / 1000
    w = np.array([r['n_req'] for r in runs], float)
    mem_x = 2 if sc.MEM_B else 0                              # 막전위 읽기·쓰기 DMA (요청마다)
    return dict(
        miss_rate=a['miss'] / a['n_req'], n_req=a['n_req'],
        mean_ms=float(rr.mean()), p99_ms=float(np.percentile(rr, 99)), max_ms=float(rr.max()),
        in_ms=float(np.dot(w, [r['in_ms'] for r in runs]) / w.sum()),
        fpga_ms=float(np.dot(w, [r['fpga_ms'] for r in runs]) / w.sum()),
        out_ms=float(np.dot(w, [r['out_ms'] for r in runs]) / w.sum()),
        acc_req=a['w_xfers'] / a['req_win'] + mem_x, w_acc_req=a['w_xfers'] / a['req_win'],
        kb_req=(a['w_bytes'] + a['m_bytes']) / a['req_win'] / 1024, w_kb_req=a['w_bytes'] / a['req_win'] / 1024,
        ddr_mbps=(a['w_bytes'] + a['m_bytes']) / (span * sc.CLK),
        cyc_req=(a['cyc_busy'] + a['cyc_stall']) / a['cyc_n'], cyc_busy_req=a['cyc_busy'] / a['cyc_n'],
        cyc_stall_req=a['cyc_stall'] / a['cyc_n'],
        busy_frac=a['cyc_busy'] / span, stall_frac=a['cyc_stall'] / span, idle_frac=a['cyc_idle'] / span,
        cyc_total_m=(a['cyc_busy'] + a['cyc_stall']) / len(runs) / 1e6,     # 실행 하나(측정 2.048 s = 2억 480만 사이클)당 연산 + 정지
        batch_mean=a['req_win'] / nb if nb else 0.0,
        hit_rate=float(np.mean([r['hit_rate'] for r in runs])),
    )


def run_fixed(job):
    d, n, seeds = job
    st, q, c, t, ok = build(d, n)
    out = dict(**name(d), n=n, tiles=t, feasible=ok, **storage_info(st))
    if not ok:
        return out
    allr, allresp, per = [], [], {}
    for scn in SCEN:
        runs, resp = [], []
        for seed in range(seeds):
            r = sc.simulate(workload(n, seed, scn), st, q, c, detail=True)
            resp.append(r.pop('resp'))
            runs.append(r)
        per[scn] = _agg(runs, resp)
        allr += runs
        allresp += resp
    out.update(_agg(allr, allresp), per=per)
    out['worst_scn'] = max(SCEN, key=lambda s: per[s]['miss_rate'])
    return out


def stage_fixed(n, seeds, jobs):
    todo = [(d, n, seeds) for d in DESIGNS]
    todo.sort(key=lambda j: j[0][1] >= 2)                     # 오래 걸리는 FCFS·EDF(과부하)부터
    with Pool(jobs) as p:
        rows = p.map(run_fixed, todo, chunksize=1)
    rows.sort(key=lambda r: DESIGNS.index(next(d for d in DESIGNS if name(d) == {k: r[k] for k in ('storage', 'scheduler', 'compute')})))
    stem = os.path.join(OUT, f'{PREFIX}_fixed_n{n}')
    with open(stem + '.jsonl', 'w') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    md = fixed_table(rows, n, seeds)
    with open(stem + '.md', 'w') as f:
        f.write(md)
    print(md)


def _info(r):
    s = r['storage']
    if s.startswith('A'):
        return f"엔트리 {r['E']}"
    if s.startswith('B'):
        return f"앞 {r['k']}그룹{' + β·vth' if r['bv'] else ''}"
    if s.startswith('C'):
        return f"고정 {r['E']} + 층 1 {r['R']}모델"
    return '보관 없음'


def dma_cyc(r):
    """요청당 DDR3 데이터 이동 사이클(100 MHz): 가중치 읽기 + 막전위 읽기·쓰기. DMA 고정 비용 0.244 µs는 넣지 않음"""
    return (r['w_kb_req'] * 1024 / sc.BW + sc.mem_time(1)) / sc.CLK


def fixed_table(rows, n, seeds):
    sc.configure(LANES, n, mem=MEM, rev=REV, arch=ARCH)
    cyc_cmp = sc.WORDS * sc.OVH
    L = [f'# 3단계: 목표 {n:,}트랙에서 설계별 지표 — XL INT8, {LANES}레인, 막전위 DDR3, rev {REV}\n',
         f'시뮬레이션 값. 시나리오 {"·".join(SCEN)} × 시드 {seeds}개, 실행마다 측정 구간 64주기(2.048 s). 위반율·평균·p99는 모든 요청을 합친 값. '
         '평균 처리 시간 = 생성 → 결과가 호스트에 도착(호스트 1 ms 묶음 입출력 포함), 괄호 = FPGA 안(도착 → 연산 완료). '
         '오프칩 접근 = 요청당 DDR3 DMA 횟수(가중치: 한 번에는 묶음당 1회, 한 줄씩은 적재하는 뉴런 그룹마다 1회. 막전위: 읽기·쓰기 2회), '
         '괄호 = 가중치 DMA만. 1 DMA는 AXI 256 bit(32 B) 버스트 여러 개로 나뉘며, 32 B 단위 접근 수 = KB × 32다.\n',
         f'사이클(100 MHz): 요청당 연산은 모든 설계가 {cyc_cmp:,.1f}사이클({sc.WORDS:,} word × 1.1)로 같다. '
         'DMA = 요청당 DDR3 데이터 이동 사이클(가중치 + 막전위). 연산 배열 사이클 = 요청당 (연산 + 정지), 정지 = FPGA에 요청이 있는데 '
         '연산 배열이 가중치를 기다린 사이클. 요청이 계속 도착하는 U·K·I·R에서는 FPGA 안에 대기 요청이 늘 있어 쉬는 시간이 모두 정지가 되므로, '
         '이 값은 설계와 무관하게 측정 구간 ÷ 요청 수(U 3,125)가 된다. 여유는 유휴 시간이 아니라 더 작은 묶음(더 많은 전송)으로 쓰인다. '
         '그래서 설계 차이는 동시 도착 S의 몰림 처리 사이클로 본다. 정지 비율 = 측정 구간 중 정지 사이클 비율(전 시나리오). 굵은 글씨 = 위반 0.\n',
         '| 저장 · 스케줄러 · 연산 | 저장 크기 | BRAM | 위반율 | 가장 나쁜 시나리오 | 평균 처리 시간 ms (FPGA 안) | p99 ms | '
         '오프칩 접근 횟수/요청 (가중치) | 오프칩 KB/요청 | DMA 사이클/요청 | S 몰림 연산 배열 사이클/요청 | 정지 비율 | 평균 묶음 |',
         '|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        nm = label(r) + ('' if r['storage'] in MAIN else ' (참고)')
        if not r['feasible']:
            L.append(f"| {nm} | {_info(r)} | {r['tiles']:g} 초과 | BRAM 배치 불가 | | | | | | | | | |")
            continue
        ok = r['miss_rate'] == 0
        b = (lambda x: f'**{x}**') if ok else (lambda x: x)
        worst = '–' if ok else f"{r['worst_scn']} {r['per'][r['worst_scn']]['miss_rate'] * 100:.1f} %"
        L.append(f"| {b(nm)} | {_info(r)} | {r['tiles']:g} | {b(f'{r['miss_rate'] * 100:.2f} %')} | "
                 f"{worst} | "
                 f"{r['mean_ms']:,.2f} ({r['fpga_ms']:,.2f}) | {r['p99_ms']:,.2f} | {r['acc_req']:.2f} ({r['w_acc_req']:.2f}) | "
                 f"{r['kb_req']:.1f} | {dma_cyc(r):,.0f} | {r['per']['S']['cyc_req']:,.0f} | {r['stall_frac'] * 100:.1f} % | "
                 f"{r['batch_mean']:.1f} |")
    feas = [r for r in rows if r['feasible']]
    for title, f in (('위반율 %', lambda x: f"{x['miss_rate'] * 100:.2f}"),
                     ('평균 처리 시간 ms', lambda x: f"{x['mean_ms']:,.2f}"),
                     ('오프칩 접근 횟수/요청', lambda x: f"{x['acc_req']:.2f}"),
                     ('오프칩 KB/요청', lambda x: f"{x['kb_req']:.1f}"),
                     ('DMA 사이클/요청', lambda x: f'{dma_cyc(x):,.0f}'),
                     ('연산 배열 사이클/요청 (연산 + 정지)', lambda x: f"{x['cyc_req']:,.0f}"),
                     ('평균 묶음', lambda x: f"{x['batch_mean']:.1f}")):
        L += [f'\n## 시나리오별 {title}\n', '| 저장 · 스케줄러 · 연산 | ' + ' | '.join(SCEN) + ' |', '|---|' + '---:|' * len(SCEN)]
        for r in feas:
            L.append(f'| {label(r)} | ' + ' | '.join(f(r['per'][s]) for s in SCEN) + ' |')
    return '\n'.join(L) + '\n'


# ---- 목표 여유: 민감도 조건에서 목표 N 통과 여부 -----------------------------------------------
MARGIN_COND = [('기준', {}), ('호스트 주기 W_h 2 ms', dict(host=2000.0)), ('PCIe 꼬리 +700 µs', dict(tail=700.0)),
               ('제어 오버헤드 20 %', dict(ovh=1.2)), ('DDR3 2.0 GB/s', dict(bw=2000.0))]
MARGIN_COND_SCORE = MARGIN_COND + [('W_h 2 ms (가드에 반영)', dict(host=2000.0, inform=True)),
                                   ('PCIe 꼬리 +700 µs (가드에 반영)', dict(tail=700.0, inform=True))]
MARGIN_DESIGNS_SCORE = [(s, q, c) for s in ('A.전체캐시', 'D.스트림') for q in ('그룹핑', '점수2', '점수3')
                        for c in ('한줄씩', '한번에')]
MARGIN_DESIGNS = [('A.전체캐시', '그룹핑', '한줄씩'), ('A.전체캐시', '그룹핑', '한번에'), ('A.전체캐시', '점수', '한줄씩'),
                  ('B.부분상주', '그룹핑', '한줄씩'), ('C.고정혼합', '그룹핑', '한줄씩'), ('D.스트림', '그룹핑', '한줄씩')]


def s_worst_resp(n, cond):
    """동시 도착의 최악 위상 해석 응답 ms: 입력·결과 대기 W_h씩 + H2C·C2H 실측 최대(+ 꼬리) + 크기 항 + 첫 모델 전송 + N × 요청당 연산"""
    w = cond.get('host', HOST)
    h, c = sc.load_samples(sc.H_IN_FILE).max(), sc.load_samples(sc.H_OUT_FILE).max()
    t = (2 * w + h + c + 2 * cond.get('tail', 0.0) + (n * sc.IN_B - 64) / sc.H2C_BW
         + sc.T0 + sc.MODEL_B / cond.get('bw', 3015.0) + n * sc.C_REQ)
    return t / 1000


def run_margin(job):
    d, n, cname, cond = job
    sc.OVH = cond.get('ovh', 1.10)                   # configure(build) 전에 정해야 요청당 연산에 반영된다
    st, q, c, t, ok = build(d, n)
    sc.BW = cond.get('bw', 3015.0)
    if cond.get('inform') and isinstance(q, ScoreGuard):   # 가드가 실제 결과 회수 경로(W_h + C2H 최대 + 꼬리)를 안다
        q.margin = cond.get('host', HOST) + sc.load_samples(sc.H_OUT_FILE).max() + cond.get('tail', 0.0) + 20.0
    elif cond.get('host_known') and isinstance(q, ScoreGuard):   # W_h는 설계값이라 가드가 안다(꼬리 지연만 모름)
        q.margin += cond['host'] - HOST
    miss = tot = 0
    worst, by = 0.0, {}
    for scn in SCEN:
        m = 0
        for seed in range(SEEDS_VERIFY):
            r = sc.simulate(workload(n, seed, scn, host=cond.get('host', HOST), tail=cond.get('tail', 0.0)), st, q, c)
            m += r['miss']
            tot += r['n_req']
            worst = max(worst, r['max_ms'])
        by[scn] = m
        miss += m
    out = dict(**name(d), cond=cname, n=n, miss=miss, n_req=tot, worst_ms=worst, by=by,
               c_req=sc.C_REQ, s_worst_ms=s_worst_resp(n, cond))
    sc.OVH, sc.BW = 1.10, 3015.0
    return out


MARGIN_COND_GEN = [('기준', {}), ('호스트 주기 W_h 2 ms (설계값이라 가드가 앎)', dict(host=2000.0, host_known=True)),
                   ('PCIe 꼬리 +700 µs (가드가 모름)', dict(tail=700.0)), ('제어 오버헤드 20 %', dict(ovh=1.2)),
                   ('DDR3 2.0 GB/s', dict(bw=2000.0))]
MARGIN_GEN = False                 # True(--only를 쓴 스케줄러 비교)면 DESIGNS 전부를 MARGIN_COND_GEN으로 확인


def margin_sets():
    """스케줄러 비교 실행(점수2가 있음)이면 점수 방식용 설계·조건, 아니면 기본"""
    if MARGIN_GEN:
        return [tuple(name(d).values()) for d in DESIGNS], MARGIN_COND_GEN
    if any(q is ScoreGuard for q in SCH):
        return MARGIN_DESIGNS_SCORE, MARGIN_COND_SCORE
    return MARGIN_DESIGNS, MARGIN_COND


def stage_margin(n, jobs):
    di = {(STO[a].name, SCH[b].name, CMP[c].name): (a, b, c) for a, b, c in DESIGNS}
    designs, conds = margin_sets()
    todo = [(di[k], n, cn, cd) for k in designs for cn, cd in conds]
    with Pool(jobs) as p:
        res = p.map(run_margin, todo, chunksize=1)
    with open(os.path.join(OUT, f'{PREFIX}_margin_n{n}.jsonl'), 'w') as f:
        for r in res:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    md = margin_table(res, n)
    with open(os.path.join(OUT, f'{PREFIX}_margin_n{n}.md'), 'w') as f:
        f.write(md)
    print(md)


def margin_table(res, n):
    designs, conds = margin_sets()
    L = [f'# 목표 {n:,}트랙의 여유 — 민감도 조건 (시나리오 {"·".join(SCEN)} × 시드 {SEEDS_VERIFY}개)\n',
         '시뮬레이션 값. 칸 = 위반 수 / 최대 응답 ms(생성 → 결과 도착). 0이면 굵게. 마지막 행 = 동시 도착(S·SK)에서 호스트 입출력 '
         '위상이 최악일 때, 첫 모델 전송 1회 뒤 연산이 쉬지 않고 이어진다고 본 해석 응답 ms. 어떤 설계도 이보다 짧을 수 없으므로 '
         '32 ms를 넘으면 그 조건에서는 목표 트랙을 보장할 수 없다.\n',
         '| 설계 | ' + ' | '.join(cn for cn, _ in conds) + ' |', '|---|' + '---:|' * len(conds)]
    for k in designs:
        cells = []
        for cn, _ in conds:
            r = next(x for x in res if (x['storage'], x['scheduler'], x['compute']) == tuple(k) and x['cond'] == cn)
            cells.append(f"**0 / {r['worst_ms']:.1f}**" if r['miss'] == 0 else f"{r['miss']:,} / {r['worst_ms']:.1f}")
        L.append(f"| {' · '.join(k)} | " + ' | '.join(cells) + ' |')
    srow = [next(x for x in res if x['cond'] == cn)['s_worst_ms'] for cn, _ in conds]
    L.append('| S 최악 위상 해석 응답 ms | ' + ' | '.join(f'{v:.1f}' for v in srow) + ' |')
    return '\n'.join(L) + '\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stage', required=True, choices=['cap', 'verify', 'fixed', 'margin'])
    ap.add_argument('--n', type=int, default=1024, help='3단계 목표 트랙 수')
    ap.add_argument('--seeds', type=int, default=SEEDS_VERIFY, help='3단계 시나리오마다 시드 수')
    ap.add_argument('--jobs', type=int, default=11)
    ap.add_argument('--table', action='store_true', help='fixed·margin: 저장된 jsonl로 표만 다시 만든다')
    ap.add_argument('--sch', help='스케줄러 목록(쉼표): ' + ', '.join(SCH_BY_KEY) + '. 기본 fcfs,edf,grouping,score')
    ap.add_argument('--prefix', help='결과 파일 접두사(기본 p38)')
    ap.add_argument('--only', help='설계 제한: 저장 머리글자:연산 이름 목록, 예 A:한번에,A:한줄씩,D:한줄씩')
    a = ap.parse_args()
    global SCH, DESIGNS, PREFIX, MARGIN_GEN
    if a.sch:                            # Pool은 fork이므로 바꾼 전역이 작업 프로세스에도 그대로 간다
        SCH = [SCH_BY_KEY[k] for k in a.sch.split(',')]
        DESIGNS = list(itertools.product(range(len(STO)), range(len(SCH)), range(len(CMP))))
    if a.prefix:
        PREFIX = a.prefix
    if a.only:                           # 예: A:한번에,A:한줄씩,D:한줄씩
        keep = {tuple(x.split(':')) for x in a.only.split(',')}
        DESIGNS = [d for d in DESIGNS if (STO[d[0]].name[0], CMP[d[2]].name) in keep]
        MARGIN_GEN = True
    if a.table:
        what = {'fixed': f'{PREFIX}_fixed', 'margin': f'{PREFIX}_margin'}[a.stage]
        with open(os.path.join(OUT, f'{what}_n{a.n}.jsonl')) as f:
            rows = [json.loads(x) for x in f]
        md = fixed_table(rows, a.n, a.seeds) if a.stage == 'fixed' else margin_table(rows, a.n)
        with open(os.path.join(OUT, f'{what}_n{a.n}.md'), 'w') as f:
            f.write(md)
        print(md)
        return
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    if a.stage == 'cap':
        stage_cap(a.jobs)
    elif a.stage == 'verify':
        stage_verify(a.jobs)
    elif a.stage == 'margin':
        stage_margin(a.n, a.jobs)
    else:
        stage_fixed(a.n, a.seeds, a.jobs)
    print(f'{time.time() - t0:.0f} s')


if __name__ == '__main__':
    main()
