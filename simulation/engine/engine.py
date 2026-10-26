#!/usr/bin/env python3
"""engine.py — simulation 실행기. 환경 파일 하나(simulation/environment/*.toml)가 실험 하나다

    python3 simulation/engine/engine.py simulation/environment/<파일>.toml [--jobs 11]

환경 파일 → Setup(hardware 조건 + 부품 조립) → mode(run·search·tune·bound·adversarial) → 결과 CSV. 부품은 part_*.py에 종류별로 있다.
구조, 식, mode, 결과 CSV 열은 documents/design_references/simulation_engine.md에 있다. 시간은 µs, B/µs = MB/s
"""
import argparse
import itertools
import os
import time
import tomllib
from multiprocessing import Pool

import numpy as np

from part_cache import LRU, PNU, PNURTL, OffsetOnly, OracleMIN, PNUTimeout
from part_compute import Compute
from part_deadline import DelayPattern, bound, model_group_delay_stats, host_max_us
from part_hardware import MODEL_SIZES, PERIOD_US, ROOT, Hardware
from part_jitter import JITTERS, Jitter
from part_result import RESPONSE_TIME_BIN_MS, RESPONSE_TIME_BINS, read_csv, seed_stats, summarize, write_csv  # noqa: F401 (그림 script가 engine.read_csv로 쓴다)
from part_scheduler import DeepRTMethod, DystaMethod, Grouping
from part_simulator import simulate
from part_workload import SCENARIOS, Workload

ENV_DIR = os.path.join(ROOT, 'simulation', 'environment')
TEMPLATE = os.path.join(ENV_DIR, 'template.toml')
OUT = os.path.join(ROOT, 'simulation', 'result')

CACHE_POLICIES = {'lru': LRU, 'offset_only': OffsetOnly, 'pnu_timeout': PNUTimeout, 'pnu_count': PNU, 'pnu_rtl': PNURTL,
                  'oracle_min': OracleMIN}
SCHEDULERS = {'grouping': Grouping, 'dysta_method': DystaMethod, 'deeprt_method': DeepRTMethod}


class Setup:
    """환경 값 하나(점 e) → hardware 조건 hw, 부품 셋(cache·scheduler·compute), BRAM tile, 배치 가능 여부, on-chip 트랙 수.
    추론 요청열과 실행도 여기서 만든다. 조립 순서는 simulation_engine.md §7.1"""

    def __init__(self, e):
        self.e = e
        hw = self.hw = Hardware(e['compute_lanes'], e['track_count'], e['membrane_place'], e['membrane_bits'],
                                MODEL_SIZES[e['model_size']], e['compute_ctrl_scale'], e['compute_spikes_per_cycle'],
                                e['model_count'], e['ddr3_bandwidth_mbps'])
        c = self.compute = Compute(hw)
        budget = hw.tile_budget - e['bram_reserve_tiles']
        st = self.cache = CACHE_POLICIES[e['cache_policy']](hw, entries=e['cache_entries'] or None, budget=budget - c.tiles(),
                                                            **e['cache_attrs'])
        self.used_tiles = st.tiles() + c.tiles()
        self.feasible = self.used_tiles <= budget and st.entries >= 2      # Entry 2벌 이상이어야 적재와 연산이 겹친다
        place = e['membrane_place']                    # on-chip 트랙: split은 weight entry·준비 버퍼를 뺀 남는 BRAM에 들어가는 만큼
        self.on_chip_tracks = (hw.split_membrane(budget - self.used_tiles) if place == 'split'
                              else e['track_count'] if place == 'on_chip' else 0)
        self.scheduler = SCHEDULERS[e['scheduler']](hw, **e['scheduler_attrs'])

    def draw_tracks(self, scn, seed):
        """(트랙 → 모델, 무작위 offset). Workload.make와 같은 난수"""
        return Workload.draw_tracks(self.hw.models, self.e['track_count'], seed, SCENARIOS[scn].get('dist'))

    def workload(self, scn, seed, jit=None):
        """시나리오 scn, seed의 추론 요청열. jit를 주면 (트랙, 주기) Host 처리 지연 µs로 그대로 쓴다(adversarial search).
        PNU는 그래도 host_jitter_dist·host_model_group_delay_trace 분포만 안다. 단계는 simulation_engine.md §4.1"""
        e, hw, M = self.e, self.hw, self.hw.models
        n, kw = e['track_count'], dict(SCENARIOS[scn])
        tm, offs = self.draw_tracks(scn, seed)
        model_off = np.arange(M) * (PERIOD_US / M)     # Model-Grouped Offset Assignment: 모델 m의 offset
        if e['host_offset'] != 'unaligned':                 # unaligned이면 시나리오의 offset 그대로(make가 같은 값을 뽑는다)
            offs = model_off[tm] if e['host_offset'] == 'offset_assignment' else np.zeros(n)   # global_alignment: 모든 트랙 nominal offset 0
            kw.pop('offset', None)
            kw.update(offset=offs, track_model=tm)
        wl = Workload.make(hw, n, seed, warmup=e['sim_warmup_periods'], meas=e['sim_meas_periods'], spike=e['compute_input'] == 'golden',
                           jit=jit, jitter=Jitter.of(e['host_jitter_dist'], e['host_jitter_ms'] * 1000.0, e['host_jitter_trace']),
                           model_group_delay=Jitter.of('trace', 0.0, e['host_model_group_delay_trace']) if e['host_model_group_delay_trace'] else None,
                           drop_busy=e['fpga_drop_busy'], **kw)
        wait = host_max_us(e) if e['host_gather_to_max'] else e['host_gather_ms'] * 1000.0
        if wait:                                       # 모아 보내기: 모델·주기마다 다 준비되거나 offset + D가 되면 한꺼번에
            wl.gather(model_off, wait)
        if e['host_packet_gap_us']:
            wl.packetize(e['host_packet_gap_us'])
        if e['host_fixed_delay_us']:                   # t_host 뒤 송신 전 고정 지연. Response time에 들어간다
            wl.delay(e['host_fixed_delay_us'])
        return wl

    def run(self, scn, seed, jit=None, **kw):
        """추론 요청열 하나를 이 부품 셋으로 끝까지 돌린 simulate() 결과"""
        return simulate(self.workload(scn, seed, jit), self.cache, self.scheduler, self.compute, **kw)


# ---- 환경 파일 ---------------------------------------------------------------------
def load(path):
    """환경 파일을 읽고 모든 점을 확인한다. 키가 template와 다르거나 값이 틀리면 돌리기 전에 멈춘다"""
    with open(path, 'rb') as f:
        env = tomllib.load(f)
    with open(TEMPLATE, 'rb') as f:
        keys = set(tomllib.load(f))
    if set(env) != keys:
        raise SystemExit(f'{path}: keys not in template {sorted(set(env) - keys)}, missing keys {sorted(keys - set(env))}')
    for lb, e in points(env):
        check(lb, e)
    return env


def merge(e, over, where):
    """표 over의 키로 e를 덮어쓴 사본. label은 이름으로만 쓴다"""
    bad = set(over) - set(e) - {'label'}
    if bad:
        raise SystemExit(f'{where}: keys not in template {sorted(bad)}')
    return {**e, **{k: v for k, v in over.items() if k != 'label'}}


def points(env):
    """[sweep] 축의 곱 → [(label, 점 e)]. 축 이름이 환경 키면 그 값을 바꾸고, 아니면 축의 값(표)이 여러 키를 한꺼번에 바꾼다"""
    base = {k: v for k, v in env.items() if k != 'sweep'}
    axes = list(env['sweep'].items())
    out = []
    for combo in itertools.product(*(vals for _, vals in axes)):
        e, tag = base, []
        for (ax, _), v in zip(axes, combo):
            if ax in base:
                if isinstance(v, dict) and not isinstance(base[ax], dict):
                    raise SystemExit(f'[sweep] {ax}: an axis named after an environment key takes only values of that key. '
                                     'Rename the axis to change several keys with a table')
                e = {**e, ax: v}
                tag.append(f'{ax}={v}')
            elif isinstance(v, dict):
                e = merge(e, v, f'[sweep] {ax}')
                tag.append(v.get('label') or ', '.join(f'{k}={x}' for k, x in v.items()))
            else:
                raise SystemExit(f'[sweep] {ax}: an axis that is not an environment key takes tables')
        out.append((' · '.join(tag) or 'base', e))
    return out


def check(lb, e):
    """점 하나의 값을 확인한다. 틀리면 돌리기 전에 멈춘다"""
    def exists(p):
        return os.path.exists(p if os.path.isabs(p) else os.path.join(ROOT, p))
    C, S = CACHE_POLICIES.get(e['cache_policy'], object), SCHEDULERS.get(e['scheduler'], object)
    rules = [('sim_mode', e['sim_mode'] in MODES), ('model_size', e['model_size'] in MODEL_SIZES),
             ('model_count', isinstance(e['model_count'], int) and e['model_count'] >= 1),
             ('compute_spikes_per_cycle', e['compute_spikes_per_cycle'] in (1, 2)), ('compute_input', e['compute_input'] in ('golden', 'dense')),
             ('membrane_place', e['membrane_place'] in ('split', 'on_chip', 'ddr3')), ('membrane_bits', e['membrane_bits'] in (12, 16)),
             ('cache_policy', e['cache_policy'] in CACHE_POLICIES), ('scheduler', e['scheduler'] in SCHEDULERS),
             ('host_offset', e['host_offset'] in ('offset_assignment', 'unaligned', 'global_alignment')),
             ('host_jitter_dist', e['host_jitter_dist'] in JITTERS and (e['host_jitter_dist'] != 'trace' or exists(e['host_jitter_trace']))),
             ('host_model_group_delay_trace', not e['host_model_group_delay_trace'] or exists(e['host_model_group_delay_trace'])),
             ('host_gather_ms', e['host_gather_ms'] >= 0 and (not e['host_gather_ms'] or e['host_offset'] == 'offset_assignment')),
             ('host_gather_to_max', isinstance(e['host_gather_to_max'], bool)
              and (not e['host_gather_to_max'] or (e['host_offset'] == 'offset_assignment' and not e['host_gather_ms']))),
             ('host_packet_gap_us', e['host_packet_gap_us'] >= 0
              and (not e['host_packet_gap_us'] or bool(e['host_gather_ms'] or e['host_gather_to_max']))),
             ('host_fixed_delay_us', e['host_fixed_delay_us'] >= 0),
             ('fpga_drop_busy', isinstance(e['fpga_drop_busy'], bool)),
             ('sim_scenarios', bool(e['sim_scenarios']) and set(e['sim_scenarios']) <= set(SCENARIOS)),
             ('cache_attrs', all(hasattr(C, k) for k in e['cache_attrs'])),
             ('scheduler_attrs', all(hasattr(S, k) for k in e['scheduler_attrs'])),
             ('search_key', e['sim_mode'] != 'search' or (e['search_key'] in e and (e['search_values'] or e['search_key'] == 'track_count'))),
             ('tune_attr', e['sim_mode'] != 'tune' or (hasattr(S, e['tune_attr']) and bool(e['tune_values'])))]
    bad = [f'{k}={e[k]!r}' for k, ok in rules if not ok]
    if bad:
        raise SystemExit(f'{lb}: invalid value {", ".join(bad)}')
    for cond in e['tune_conds']:
        merge(e, cond, f'{lb}: tune_conds')


def seeds(e):
    return range(e['sim_seed0'], e['sim_seed0'] + e['sim_seeds'])


# ---- mode: 같은 이름의 method 다섯 개(jobs·one·summary·job_rows·table)를 가진다 -------------
class Run:
    """run: 점마다 시나리오 × seed를 끝까지 돌려 지표를 낸다. BRAM 예산을 넘는 점은 돌리지 않는다"""

    @staticmethod
    def jobs(pts, info):
        return [(i, lb, e, s, sd) for i, (lb, e) in enumerate(pts) if info[i][2] for s in e['sim_scenarios'] for sd in seeds(e)]

    @staticmethod
    def one(job):
        """실행 하나 → simulate() 지표 + response time 히스토그램"""
        i, lb, e, scn, seed = job
        s = Setup(e)
        r = s.run(scn, seed, detail=True)
        response_time = r.pop('response_time') / 1000
        h = np.bincount(np.minimum((response_time / RESPONSE_TIME_BIN_MS).astype(int), RESPONSE_TIME_BINS))
        return dict(point=i, label=lb, scn=scn, seed=seed, **r, c_req=s.hw.dense_req_us, model_b=s.hw.model_bytes,
                    hist=[[int(j), int(h[j])] for j in np.flatnonzero(h)])

    @staticmethod
    def summary(rs):
        """점 하나의 실행들 → 점별 CSV에 더할 값"""
        return {**summarize(rs), **seed_stats(rs)} if rs else {}

    @staticmethod
    def job_rows(rows):
        return rows

    @staticmethod
    def table(env, pts, info, rows):
        by = {}
        for r in rows:
            by.setdefault(r['point'], []).append(r)
        L = ['| point | runs | miss | mean ms | p99 ms | max ms | in · FPGA · out ms | weight KiB/inference | '
             'DDR3 KiB/inference | DDR3 MB/s | mean batch | hit rate |', '|---|' + '---:|' * 11]
        for i, (lb, _) in enumerate(pts):
            t, budget, ok = info[i]
            if not ok:
                L.append(f'| {lb} | BRAM {t:g} / {budget:g} tile, over budget, not run |' + ' |' * 10)
                continue
            a = summarize(by[i])
            L.append(f"| {lb} | {a['runs']} | {a['miss']:,} | {a['mean_ms']:.3f} | {a['p99_ms']:.2f}{'+' if a['p99_ms'] > 70 else ''} | "
                     f"{a['max_ms']:.2f} | {a['in_ms']:.2f} · {a['fpga_ms']:.2f} · {a['out_ms']:.2f} | {a['w_kib']:.1f} | "
                     f"{a['ddr3_traffic_kib']:.1f} | {a['ddr3_used_bandwidth_mbps']:.0f} | {a['batch']:.1f} | {a['hit']:.2f} |")
        return '\n'.join(L) + '\n'


class Search:
    """search: 점마다 search_key를 search_values 순서로 바꿔 모든 시나리오·seed에서 miss 0인 마지막 값을 찾는다.
    통과가 값 순서에 대해 단조라고 보고 2배씩 넓혀 실패 지점을 찾은 뒤 이분 탐색한다"""

    @staticmethod
    def jobs(pts, info):
        return [(i, lb, e) for i, (lb, e) in enumerate(pts)]

    @staticmethod
    def one(job):
        """점 하나 → 찾은 값, 상한 도달, 시험한 [값, 통과]"""
        i, lb, e = job
        key, vals, tested = e['search_key'], e['search_values'] or Search.track_values(e), []

        def ok(j):                                     # j = 후보 번호(1부터)
            r = Search.passes({**e, key: vals[j - 1]})
            tested.append([vals[j - 1], r])
            return r
        lo, j, fail = 0, 1, None
        while True:
            if ok(j):
                lo = j
                if j == len(vals):
                    break
                j = min(2 * j, len(vals))
            else:
                fail = j
                break
        if fail is not None:
            a, b = lo, fail - 1
            while a < b:
                mid = (a + b + 1) // 2
                if ok(mid):
                    a = mid
                else:
                    b = mid - 1
            lo = a
        return dict(point=i, label=lb, key=key, found=vals[lo - 1] if lo else None, capped=lo == len(vals), tested=tested)

    @staticmethod
    def summary(rs):
        return dict(found=rs[0]['found'], capped=rs[0]['capped'])

    @staticmethod
    def job_rows(rows):
        return [dict(point=r['point'], label=r['label'], key=r['key'], value=v, passed=ok) for r in rows for v, ok in r['tested']]

    @staticmethod
    def table(env, pts, info, rows):
        L = [f"| point | {env['search_key']} found | capped | tested (value: pass) |", '|---|---:|---|---|']
        for r in rows:
            L.append(f"| {r['label']} | {'none' if r['found'] is None else r['found']} | {'yes' if r['capped'] else ''} | "
                     + ', '.join(f"{v}: {'O' if ok else 'X'}" for v, ok in r['tested']) + ' |')
        return '\n'.join(L) + '\n'

    @staticmethod
    def passes(e):
        """모든 시나리오·seed에서 측정 구간 deadline miss가 없는가(BRAM 예산을 넘으면 실패)"""
        s = Setup(e)
        return s.feasible and not any(s.run(scn, sd, stop_on_miss=True)['miss'] for scn in e['sim_scenarios'] for sd in seeds(e))

    @staticmethod
    def track_values(e):
        """track_count 후보: search_step 단위로 평균 연산 가동률 ≤ 100%인 가장 큰 값까지. dense 연산 기준이라 상한이 보수적이다"""
        req_us, step = Setup(e).hw.dense_req_us, e['search_step']
        cap = min(int(PERIOD_US / (req_us * Search._active_share(s))) // step * step for s in e['sim_scenarios'])
        return list(range(step, cap + 1, step))

    @staticmethod
    def _active_share(scn):
        """주기마다 추론 요청을 내는 트랙의 평균 비율(I: p_req, R: 활성 비율 범위의 평균, 나머지 1)"""
        kw = SCENARIOS[scn]
        return kw.get('p_req', sum(kw['congestion']) / 2 if 'congestion' in kw else 1.0)


class Tune:
    """tune: 점마다 scheduler_attrs[tune_attr] 후보를 tune_conds × 시나리오 × seed에 돌려, 모든 실행이 miss 0인 값 중
    weight DDR3 byte가 가장 작은 값을 고른다. 없으면 miss가 난 실행이 가장 적은 값"""

    @staticmethod
    def jobs(pts, info):
        return [(i, lb, e, v) for i, (lb, e) in enumerate(pts) for v in e['tune_values']]

    @staticmethod
    def one(job):
        """(점, 후보 값) 하나 → miss 난 실행 수, 추론 요청당 weight·DDR3 KiB, 최대 response time"""
        i, lb, e, v = job
        fails, wb, mb, req, mx = 0, 0.0, 0.0, 0, 0.0
        for cond in e['tune_conds'] or [{}]:
            x = merge(e, cond, lb)
            x['scheduler_attrs'] = {**x['scheduler_attrs'], e['tune_attr']: v}
            s = Setup(x)
            for scn in x['sim_scenarios']:
                for sd in seeds(x):
                    r = s.run(scn, sd, stop_on_miss=True) if s.feasible else {'miss': 1}
                    if r['miss']:
                        fails += 1
                    else:
                        wb += r['w_bytes']
                        mb += r['m_bytes']
                        req += r['req_win']
                        mx = max(mx, r['max_ms'])
        return dict(point=i, label=lb, attr=e['tune_attr'], value=v, fails=fails, w_kib=wb / req / 1024 if req else None,
                    ddr3_traffic_kib=(wb + mb) / req / 1024 if req else None, max_ms=mx if req else None)

    @staticmethod
    def summary(rs):
        good, best = Tune.pick(rs)
        return dict(passed=[r['value'] for r in good], chosen=best['value'], w_kib=best['w_kib'], fails=best['fails'])

    @staticmethod
    def job_rows(rows):
        return rows

    @staticmethod
    def table(env, pts, info, rows):
        L = ['| point | attribute | passed values | chosen | weight KiB/request | runs with miss |', '|---|---|---|---:|---:|---:|']
        for i, (lb, _) in enumerate(pts):
            good, best = Tune.pick([r for r in rows if r['point'] == i])
            L.append(f"| {lb} | {best['attr']} | {', '.join(str(r['value']) for r in good) or 'none'} | {best['value']} | "
                     f"{'–' if best['w_kib'] is None else f'{best['w_kib']:.1f}'} | {best['fails']} |")
        return '\n'.join(L) + '\n'

    @staticmethod
    def pick(rs):
        """모든 실행이 miss 0인 값들과 그중 weight byte가 가장 작은 값(같으면 최대 response time이 작은 값)"""
        good = [r for r in rs if r['fails'] == 0]
        return good, (min(good, key=lambda r: (round(r['w_kib'], 6), r.get('max_ms') or 0.0)) if good else min(rs, key=lambda r: r['fails']))


class Bound:
    """bound: 점마다 조건부 response time을 식으로 계산한다(part_deadline.bound, 05 §6.1). Simulation은 돌리지 않는다"""

    @staticmethod
    def jobs(pts, info):
        return [(i, lb, e) for i, (lb, e) in enumerate(pts) if info[i][2]]

    @staticmethod
    def one(job):
        """점 하나 → bound() 값"""
        i, lb, e = job
        return dict(point=i, label=lb, **bound(Setup(e)))

    @staticmethod
    def summary(rs):
        return {k: v for k, v in rs[0].items() if k not in ('point', 'label')} if rs else {}

    @staticmethod
    def job_rows(rows):
        return rows

    @staticmethod
    def table(env, pts, info, rows):
        L = ['| point | Host max ms | R_single ms | R_cond ms | min gap ms | R_single < gap | R_cond <= 32 ms |', '|---|---:|---:|---:|---:|---|---|']
        for r in rows:
            L.append(f"| {r['label']} | {r['host_max_ms']:.2f} | {r['single_fpga_ms']:.2f} | {r['cond_e2e_ms']:.2f} | {r['min_gap_ms']:.2f} | "
                     f"{'yes' if r['cond_gap_ok'] else 'no'} | {'yes' if r['cond_e2e_ok'] else 'no'} |")
        return '\n'.join(L) + '\n'


class Adversarial:
    """adversarial: 점마다 모델별 지연 꼴(DelayPattern)을 바꿔 가며 결과가 나온 추론 요청의 송신 뒤 최대(t_recv − t_send)를 키운다
    (05 §6.2). 모델마다 같은 꼴인 시작점 30개와 무작위 시작점 8개를 시험한 뒤, 가장 나쁜 꼴에서 모델 3개의 꼴을 바꿔 더
    나빠지면 받기를 24번 한다. 결과는 관측 최대이고 증명이 아니다. 탐색 난수는 송신 방식 키를 뺀 점 번호로 정해 송신 방식끼리
    같은 시작점과 같은 난수열로 탐색한다"""
    RANDOM_STARTS, CLIMB_STEPS, CLIMB_MODELS = 8, 24, 3
    SEND_KEYS = ('host_gather_ms', 'host_gather_to_max', 'host_packet_gap_us')

    @staticmethod
    def jobs(pts, info):
        """작업마다 송신 방식 키를 뺀 점 번호(탐색 seed)를 붙인다. 배치할 수 없는 점은 뺀다"""
        base = {}
        out = [(i, lb, e, base.setdefault(repr({k: v for k, v in e.items() if k not in Adversarial.SEND_KEYS}), len(base)))
               for i, (lb, e) in enumerate(pts)]
        return [j for j in out if info[j[0]][2]]

    @staticmethod
    def one(job):
        """점 하나 → 가장 나쁜 꼴의 지표, 탐색한 모든 꼴에서 본 최대(seen_*), 조건부 response time, 시험한 꼴 기록"""
        i, lb, e, base = job
        A, s, rng = Adversarial, Setup(e), np.random.default_rng(2000 + base)
        G, J, M = model_group_delay_stats(e['host_model_group_delay_trace'])[1], e['host_jitter_ms'] * 1000.0, e['model_count']
        K = e['sim_warmup_periods'] + e['sim_meas_periods']
        ng, nu = len(DelayPattern.GROUP), len(DelayPattern.REQUEST)
        starts = [DelayPattern(np.full(M, g), np.full(M, u)) for g in range(ng) for u in range(nu)]
        starts += [DelayPattern(rng.integers(0, ng, M), rng.integers(0, nu, M)) for _ in range(A.RANDOM_STARTS)]
        cur, worst, tested = None, None, []
        for k in range(len(starts) + A.CLIMB_STEPS):
            p = starts[k] if k < len(starts) else cur.mutated(rng, A.CLIMB_MODELS)
            v = A.evaluate(s, p, K, G, J)
            tested.append(dict(step=k, model_group_delay_pattern=p.codes()[0], request_pattern=p.codes()[1], **v))
            if worst is None or v['send_max_ms'] > worst['send_max_ms']:
                cur, worst = p, v
        g_code, u_code = cur.codes()
        return dict(point=i, label=lb, evals=len(tested), adv_send_max_ms=worst['send_max_ms'], adv_max_ms=worst['max_ms'],
                    adv_scn=worst['scn'], adv_miss=worst['miss'], adv_drop=worst['drop'], adv_window_loads_max=worst['window_loads_max'],
                    adv_loads_per_model_period=worst['weight_loads'] / max(1, worst['model_periods']), adv_model_group_delay_pattern=g_code,
                    adv_req_pattern=u_code, seen_window_loads_max=max(t['window_loads_max'] for t in tested),
                    seen_drop_max=max(t['drop'] for t in tested), seen_miss_max=max(t['miss'] for t in tested), **bound(s), tested=tested)

    @staticmethod
    def evaluate(s, p, K, G, J):
        """꼴 p를 시나리오마다 한 번 돌려 송신 뒤 최대가 가장 큰 시나리오의 지표"""
        e, worst = s.e, None
        for scn in e['sim_scenarios']:
            tm, _ = s.draw_tracks(scn, e['sim_seed0'])
            r = s.run(scn, e['sim_seed0'], jit=p.delays(tm, K, G, J))
            v = dict(scn=scn, send_max_ms=r.get('send_side_max_ms', 0.0), max_ms=r.get('max_done_ms', r['max_ms']), miss=r['miss'],
                     drop=r['drop'], window_loads_max=r.get('window_loads_max', 0), weight_loads=r.get('weight_loads', 0),
                     model_periods=r.get('model_periods', 1))
            if worst is None or v['send_max_ms'] > worst['send_max_ms']:
                worst = v
        return worst

    @staticmethod
    def summary(rs):
        return {k: v for k, v in rs[0].items() if k not in ('point', 'label', 'tested')} if rs else {}

    @staticmethod
    def job_rows(rows):
        return [dict(point=r['point'], label=r['label'], **t) for r in rows for t in r['tested']]

    @staticmethod
    def table(env, pts, info, rows):
        L = ['| point | send-to-result max ms | response max ms | miss · drop | max loads per model-period | R_cond ms |',
             '|---|---:|---:|---:|---:|---:|']
        for r in rows:
            L.append(f"| {r['label']} | {r['adv_send_max_ms']:.2f} | {r['adv_max_ms']:.2f} | {r['adv_miss']} · {r['adv_drop']} | "
                     f"{r['adv_window_loads_max']} | {r['cond_e2e_ms']:.2f} |")
        return '\n'.join(L) + '\n'


MODES = {'run': Run, 'search': Search, 'tune': Tune, 'bound': Bound, 'adversarial': Adversarial}


def point_rows(env, pts, info, rows):
    """점별 CSV 행: 점 번호·label·환경 값 전부·BRAM tile + mode 요약"""
    with open(TEMPLATE, 'rb') as f:
        keys = [k for k in tomllib.load(f) if k != 'sweep']
    by = {}
    for r in rows:
        by.setdefault(r['point'], []).append(r)
    out = []
    for i, (lb, e) in enumerate(pts):
        t, budget, ok = info[i]
        row = dict(point=i, label=lb, **{k: e[k] for k in keys}, tiles=t, budget=budget, feasible=ok)
        if e['membrane_place'] == 'split':
            row['on_chip_tracks'] = Setup(e).on_chip_tracks       # 남는 BRAM에 둔 membrane potential 트랙 수(나머지는 DDR3)
        row.update(MODES[env['sim_mode']].summary(by.get(i, [])))
        out.append(row)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('env', help='environment file (simulation/environment/*.toml)')
    ap.add_argument('--jobs', type=int, default=11)
    a = ap.parse_args()
    env = load(a.env)
    name = os.path.splitext(os.path.basename(a.env))[0]
    pts = points(env)
    info = []
    for _, e in pts:
        s = Setup(e)
        info.append((s.used_tiles, s.hw.tile_budget - e['bram_reserve_tiles'], s.feasible))
    mode = MODES[env['sim_mode']]
    jobs = mode.jobs(pts, info)
    print(f'{name}: {env["sim_mode"]}, {len(pts)} points, {len(jobs)} jobs', flush=True)
    t0 = time.time()
    with Pool(a.jobs) as p:
        rows = p.map(mode.one, jobs, chunksize=1)
    os.makedirs(OUT, exist_ok=True)
    stem = os.path.join(OUT, name)
    write_csv(stem + '.csv', point_rows(env, pts, info, rows))
    write_csv(stem + '_runs.csv.gz', mode.job_rows(rows))
    print(mode.table(env, pts, info, rows))
    print(f'{len(jobs)} jobs, {time.time() - t0:.0f} s → {os.path.relpath(stem, ROOT)}{{.csv,_runs.csv.gz}}')


if __name__ == '__main__':
    main()
