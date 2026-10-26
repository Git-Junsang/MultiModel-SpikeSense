#!/usr/bin/env python3
"""test_engine.py — engine 확인. 모두 약 15초. 인자로 부를 고르면 그 부만 돈다(core p325 p326 env csv)

  1. core, 본체 손계산: 트랙 1–512개의 response time, DDR3 traffic·bandwidth, cycle 회계, 비교군 scheduler의 동작, 모아 보내기,
     membrane potential DMA를 식으로 계산한 값과 비교한다
  2. p325: 추론 요청 시각 분리, 교체 정책, 미래 정보 누출, 연산 cycle, 결과 CSV 재현, BRAM 배분
     p326: 모델 그룹 지연, drop 규칙, deadline 분석(packet 분할, 조건부 response time, adversarial 지연 꼴과 탐색)
  3. env, 환경 파일: simulation/environment의 모든 파일을 읽고 BRAM에 들어가는 첫 점을 한 번 돌린다
  4. csv, 결과 CSV: 쓰고 읽으면 값이 그대로다

    python3 simulation/engine/test_engine.py              # 모두
    python3 simulation/engine/test_engine.py p326 env     # 고른 부만
"""
import copy
import glob
import itertools
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine  # noqa: E402
from part_cache import LRU, PNU, OffsetOnly, OracleMIN, PNUTimeout  # noqa: E402
from part_compute import Compute  # noqa: E402
from part_deadline import DelayPattern, bound  # noqa: E402
from part_hardware import CLK, DMA_SETUP_US, PERIOD_US, ROOT, Hardware, bram_tiles, golden_words  # noqa: E402
from part_jitter import Jitter, TraceJitter  # noqa: E402
from part_result import read_csv, write_csv  # noqa: E402
from part_scheduler import DeepRTMethod, DystaMethod, Grouping  # noqa: E402
from part_simulator import Queue, belady, simulate  # noqa: E402
from part_workload import Workload  # noqa: E402

P, T0, W = PERIOD_US, DMA_SETUP_US, Workload.make
HERE = os.path.dirname(os.path.abspath(__file__))
BASE = dict(host_model_group_delay_trace='', fpga_drop_busy=False, sim_seeds=20)   # 손계산 기준: 모델 그룹 지연·drop 규칙 없음


class Check:
    """손계산 비교 하나씩 출력하고, 하나라도 틀리면 ok가 False"""

    def __init__(self):
        self.ok = True

    def __call__(self, name, got, exp, tol):
        good = bool(abs(got - exp) <= tol)
        self.ok &= good
        print(f'{"PASS" if good else "FAIL"}  {name}: sim {got:.6f}, expected {exp:.6f}')


def template(**over):
    """template 첫 점에 BASE와 over를 덮은 점"""
    return {**engine.points(engine.load(engine.TEMPLATE))[0][1], **BASE, **over}


def same_until(wl, t_cut, runs):
    """t_cut 뒤 도착만 0–8 ms 늦춘 사본을 만들어 runs(추론 요청열)의 결과를 둘 다 낸다"""
    wl2 = copy.copy(wl)
    t = wl.t_arr.copy()
    fut = t > t_cut
    t[fut] += np.random.default_rng(1).uniform(0, 8000.0, fut.sum())
    wl2.t_arr = t
    wl2.filter(np.ones(t.size, bool), order=np.argsort(t, kind='stable'))
    return [runs(w) for w in (wl, wl2)]


def recorder(cls):
    """plan마다 (시각, 모델, entry 상태)를 log에 남기는 cache 정책"""
    class Rec(cls):
        def reset(self, wl):
            super().reset(wl)
            self.log = []

        def plan(self, m, queue, now):
            out = super().plan(m, queue, now)
            self.log.append((round(now, 6), m, tuple(self.loaded)))
            return out
    return Rec


# ---- 1. 본체 손계산 ----
def selftest():
    check = Check()
    hw = Hardware(tracks=512, membrane_place='on_chip', membrane_bits=16)    # Membrane potential을 모두 BRAM에(DMA 0)
    BANDWIDTH, C_REQ, MODEL_B = hw.ddr3_bandwidth_mbps, hw.dense_req_us, hw.model_bytes
    one = dict(warmup=0, meas=4, d_in=27.0, d_out=25.0, offset=100.0, track_model=[0])

    # 1. 트랙 1개: response time = 입력 링크 + 적재 + 연산 + 결과 링크, 두 번째 추론 요청부터는 cache hit라 적재 0
    wl = W(hw, 1, **one)
    r = simulate(wl, LRU(hw), Grouping(hw), Compute(hw))['response_time']
    check('1a first request, 1 track µs', r[0], 27 + T0 + MODEL_B / BANDWIDTH + C_REQ + 25, 1e-6)
    check('1c hit request µs', r[1:].max(), 27 + C_REQ + 25, 1e-6)
    # 2. 모든 트랙 동시 시작 + Grouping + 기본 entry 수: 주기마다 사용 모델 수 × 모델 적재 B
    wl = W(hw, 512, seed=1, d_in=0.0, d_out=0.0, offset=0.0)
    used = len(set(wl.track_model.tolist()))
    res = simulate(wl, LRU(hw), Grouping(hw), Compute(hw))
    check('2 full Grouping DDR3 rate MB/s', res['mbps'], used * MODEL_B / P, 1e-6)
    # 3. Entry가 40모델을 모두 담으면 예열 뒤 적재 0
    res = simulate(wl, LRU(hw, entries=40), Grouping(hw), Compute(hw))
    check('3 40 entries DDR3 rate MB/s', res['mbps'], 0.0, 0)
    # 4. 연산 가동률 = N × 추론 요청당 연산 / 주기 (실측 링크 지연 표본, offset 무작위)
    res = simulate(W(hw, 512, seed=2), LRU(hw), Grouping(hw), Compute(hw))
    check('4 compute utilization', res['cmp_util'], 512 * C_REQ / P, 0.005)
    # 6. Membrane potential DDR3 비용: 읽기 B / 3,015 + 쓰기 B / 2,768 (16 bit 1,412 B, 12 bit 1,059 B)
    for bits, b in ((16, 1412), (12, 1059)):
        check(f'6 membrane potential round-trip DMA µs/request ({bits} bit)',
              Hardware(membrane_place='ddr3', membrane_bits=bits).membrane_us(1), b / 3015 + b / 2768, 1e-9)
    # 8. cycle 회계: 트랙 1개, 첫 추론 요청만 miss. 연산 = 4 × 추론 요청당 연산, 정지 = 첫 적재, 유휴 = 나머지
    wl = W(hw, 1, **one)
    res = simulate(wl, LRU(hw), Grouping(hw), Compute(hw), detail=True)
    ld = T0 + MODEL_B / BANDWIDTH
    check('8a compute cycles', res['cyc_busy'], 4 * C_REQ * 100, 1e-6)
    check('8b stall cycles = first model load', res['cyc_stall'], ld * 100, 1e-6)
    check('8c compute + stall + idle = measurement window', res['cyc_busy'] + res['cyc_stall'] + res['cyc_idle'], 4 * P * 100, 1e-3)
    check('8d response split in + FPGA + out = mean response ms', res['in_ms'] + res['fpga_ms'] + res['out_ms'], res['mean_ms'], 1e-9)
    check('8e mean FPGA residence ms', res['fpga_ms'], (ld + 4 * C_REQ) / 4 / 1000, 1e-9)
    # 9. 실측 링크 지연·무작위 offset: 연산 ≤ FPGA 체류 구간, 연산 cycle ≈ 가동률 × 구간
    wl = W(hw, 512, seed=2)
    res = simulate(wl, LRU(hw), Grouping(hw), Compute(hw), detail=True)
    span = (wl.w1 - wl.w0) * 100
    check('9a compute + stall + idle = measurement window', res['cyc_busy'] + res['cyc_stall'] + res['cyc_idle'], span, 1e-3)
    check('9b stall >= 0', float(res['cyc_stall'] >= 0), 1.0, 0)
    check('9c compute cycles / window ~ compute utilization', res['cyc_busy'] / span, res['cmp_util'], 0.002)
    # 18. Dysta Method는 기다리지 않는다: 트랙 1개 첫 추론 요청 = 1a
    wl = W(hw, 1, **one)
    r = simulate(wl, LRU(hw), DystaMethod(hw, margin=0.0), Compute(hw))['response_time']
    check('18 Dysta Method first request, 1 track µs', r[0], 27 + T0 + MODEL_B / BANDWIDTH + C_REQ + 25, 1e-6)
    # 24. DeepRT Method: flush 없으면 window 끝(10 ms)에 처리, flush면 compute array가 놀 때 바로 처리(= 1a)
    x = hw.load_us(MODEL_B)
    q = DeepRTMethod(hw, window=(10000.0, False))
    r = simulate(wl, LRU(hw), q, Compute(hw))['response_time']
    check('24a DeepRT Method window 10 ms first request µs', r[0], 10000 - 100 + x + C_REQ + 25, 1e-6)
    q.window = (10000.0, True)
    r = simulate(wl, LRU(hw), q, Compute(hw))['response_time']
    check('24b DeepRT Method flush first request µs', r[0], 27 + x + C_REQ + 25, 1e-6)

    e = template(track_count=80, sim_warmup_periods=0, sim_meas_periods=4)
    # 30. 모아 보내기 D ≥ jitter: 추론 요청마다 늦어진 도착 = (모델·주기의 마지막 준비 시각) − 준비 시각
    w0, wg = (engine.Setup({**e, 'host_jitter_ms': 3.2, 'host_gather_ms': g}).workload('uniform', 0) for g in (0.0, 3.2))
    o0, og = np.lexsort((w0.t_host, w0.track)), np.lexsort((wg.t_host, wg.track))
    k = np.floor((w0.t_host[o0] - w0.model[o0] * P / 40) / P)
    last = {}
    for m, kk, t in zip(w0.model[o0], k, w0.t_ready[o0]):
        last[m, kk] = max(last.get((m, kk), -1.0), t)
    exp = np.array([last[m, kk] for m, kk in zip(w0.model[o0], k)]) - w0.t_ready[o0]
    check('30 gather: added arrival max error µs', float(np.abs(wg.t_arr[og] - w0.t_arr[o0] - exp).max()), 0.0, 1e-6)
    # 33. 송신 전 고정 지연: 도착만 그만큼 늦고 t_host(deadline 기준)는 그대로
    w0, wp = (engine.Setup({**e, 'host_fixed_delay_us': d}).workload('uniform', 0) for d in (0.0, 5000.0))
    check('33a fixed Host delay: arrival max error µs', float(np.abs(wp.t_arr - w0.t_arr - 5000.0).max()), 0.0, 1e-6)
    check('33b fixed Host delay: t_host max error µs', float(np.abs(wp.t_host - w0.t_host).max()), 0.0, 0)
    return check.ok


# ---- 2. P3.25 ----
def selftest_p325():
    """추론 요청 시각 분리, 교체 정책, 연산 cycle, 미래 정보 누출, 결과 CSV 재현"""
    check = Check()
    base = template(host_jitter_ms=3.2, track_count=256, sim_warmup_periods=4, sim_meas_periods=16)
    s = engine.Setup(base)
    hw = s.hw

    # 1·2. 미래 추론 요청의 지연만 바꾼다: PNU의 결정은 그대로, Oracle MIN은 바뀔 수 있다
    wl = s.workload('uniform', 0)
    t_cut = wl.w0 + 4 * P
    for cls, same in ((PNU, True), (PNUTimeout, True), (OracleMIN, False)):
        def runs(w):
            st = recorder(cls)(hw, entries=base['cache_entries'])
            st.pred, st.tau_q = 'exact', 1.0
            simulate(w, st, s.scheduler, s.compute)
            return [x for x in st.log if x[0] < t_cut]
        a, b = same_until(wl, t_cut, runs)
        check(f'{"1" if same else "2"} decisions equal after changing future delays ({cls.name})', float(a == b), float(same), 0)
    # 3. 같은 트랙의 지연이 주기마다 다르다(uniform). static은 같다. cd는 같은 주기 안 퍼짐 ≤ J/2
    for dist, exp in (('uniform', 1.0), ('static', 0.0)):
        w = engine.Setup({**base, 'host_jitter_dist': dist}).workload('uniform', 0)
        d = w.t_ready - w.t_host
        diff = [np.unique(np.round(d[w.track == j], 6)).size > 1 for j in range(8)]
        check(f'3 track delay differs by period ({dist})', float(all(diff)), exp, 0)
    w = engine.Setup({**base, 'host_jitter_dist': 'cd'}).workload('uniform', 0)
    d = w.t_ready - w.t_host
    spread = max(np.ptp(d[w.period == k]) for k in range(4))
    check('3c cd spread within a period <= J/2 µs', float(spread <= 1600.0 + 1e-6), 1.0, 0)

    # 4·5. Queue에 추론 요청이 있는 모델과 연산 중 entry는 내보내지 않는다. 적재 대상도 후보가 아니다
    wl4 = W(hw, 4, warmup=0, meas=1, d_in=0.0, d_out=0.0, offset=[100.0, 200.0, 30000.0, 400.0], track_model=[0, 1, 2, 3])
    wl4.jitter = Jitter.of('uniform', 800.0)
    for cls in (PNU, OffsetOnly, OracleMIN):
        st = cls(hw, entries=3)
        st.reset(wl4)
        q4 = Queue(wl4)
        for m in (0, 1, 2):                                # Entry = [0, 1, 2], 2가 연산 중(가장 최근)
            st.plan(m, q4, 0.0)
        q4.advance(150.0)                                  # 모델 0 추론 요청이 queue에 있다. 모델 2는 다음 사용이 가장 늦지만 연산 중
        st.plan(3, q4, 150.0)
        check(f'4·5 queued and computing entries kept ({cls.name})', float(sorted(st.loaded) == [0, 2, 3]), 1.0, 0)

    # 6. 주기의 예상 추론 요청이 모두 오면 다음 사용이 다음 주기로 넘어간다
    wl6 = W(hw, 3, warmup=0, meas=2, d_in=0.0, d_out=0.0, offset=[0.0, 0.0, 5000.0], track_model=[0, 0, 1],
            jit=[[100.0, 100.0], [300.0, 300.0], [0.0, 0.0]])
    wl6.jitter = Jitter.of('uniform', 2000.0)
    st = PNU(hw, entries=2)
    st.reset(wl6)
    queue = Queue(wl6)
    st.queue = queue
    g0 = int(st.groups_of_model[0][0])
    for now, exp in ((200.0, 200.0 + (2000.0 - 200.0) / 2), (400.0, P + 2000.0 / 3)):
        queue.advance(now)
        queue.take(0, list(queue.by_model[0]))
        st.now = now
        st._count_arrivals()
        check(f'6 PNU-Count next use now={now:.0f} µs', st._next_use(g0, now), exp, 1e-6)

    # 7. 추론 요청이 빠지는 I·R에서도 count·timeout이 멈추지 않는다(모든 추론 요청이 끝난다)
    for scn in ('intermittent', 'fluctuating'):
        for name in ('pnu_count', 'pnu_timeout'):
            r = engine.Setup({**base, 'cache_policy': name}).run(scn, 0)
            check(f'7 {scn} {name} all requests processed', float(np.isfinite(r['response_time']).all() and r['n_req'] > 0), 1.0, 0)

    # 8. 32 ms 경계: 모델 0 offset 31.2 ms(추론 요청 아직 안 옴), 모델 1 offset 0.4 ms(이미 옴)
    wl8 = W(hw, 4, warmup=0, meas=2, d_in=0.0, d_out=0.0, offset=[31200.0, 400.0, 10000.0, 20000.0], track_model=[0, 1, 2, 3],
            jit=[[1500.0, 1500.0], [0.0, 0.0], [0.0, 0.0], [0.0, 0.0]])
    wl8.jitter = Jitter.of('uniform', 1600.0)
    for now, e0, e1 in ((31900.0, 31900.0 + 900.0 / 2, P + 400.0 + 800.0), (32300.0, 32300.0 + 500.0 / 2, P + 400.0 + 800.0)):
        queue = Queue(wl8)
        queue.advance(now)
        for m in (0, 1, 2, 3):
            queue.take(m, list(queue.by_model[m]))
        st = PNU(hw, entries=3)
        st.reset(wl8)
        st.queue, st.now = queue, now
        t = st.predict([0, 1])
        check(f'8 PNU next use across the 32 ms boundary now={now:.0f}', abs(t[0] - e0) + abs(t[1] - e1), 0.0, 1e-6)
        oo = OffsetOnly(hw, entries=3)
        oo.reset(wl8)
        oo.queue, oo.now = queue, now
        check(f'8 offset-only across the 32 ms boundary now={now:.0f}', float(oo.predict([0, 1]) == [31200.0 + P, 400.0 + P]), 1.0, 0)

    # 9. 점수가 모두 같으면 가장 오래 안 쓴 모델(같은 결과를 반복)
    wl9 = W(hw, 4, warmup=0, meas=1, d_in=0.0, d_out=0.0, offset=[0.0] * 4, track_model=[0, 1, 2, 3])
    wl9.jitter = Jitter.of('none')
    vic = []
    for _ in range(2):
        st = OffsetOnly(hw, entries=3)
        st.reset(wl9)
        q9 = Queue(wl9)
        for m in (2, 0, 1, 3):
            st.plan(m, q9, 10.0)
        vic.append(tuple(st.loaded))
    check('9 equal scores evict the least recently used model (2), repeatable', float(vic[0] == vic[1] == (0, 1, 3)), 1.0, 0)

    # 10. 지금 결과 CSV를 다시 낸다(p326_final_compare의 Dysta Method·DeepRT Method·제안, CPU 고정·부하 없음, J = 0.8 ms, U, seed 0)
    name = 'p326_final_compare'
    env = engine.points(engine.load(os.path.join(engine.ENV_DIR, name + '.toml')))
    pts = [i for i, (lb, e) in enumerate(env) if lb.split(' · ')[0] in ('Dysta Method (unaligned, LRU)', 'DeepRT Method (unaligned, LRU)',
           'Model-Grouped Offset Assignment + Grouping + PNU-Count (제안)') and 'M3 CPU 고정·부하 없음' in lb and e['host_jitter_ms'] == 0.8]
    old = {r['point']: r for r in read_csv(os.path.join(engine.OUT, name + '_runs.csv.gz')) if r['point'] in pts and r['scn'] == 'uniform' and r['seed'] == 0}
    for pt in pts:
        new = engine.Setup(env[pt][1]).run('uniform', 0, detail=True)
        check(f'10 reproduce {name} point {pt} weight B · max response', abs(new['w_bytes'] - old[pt]['w_bytes'])
              + abs(new['max_ms'] - old[pt]['max_ms']), 0.0, 1e-9)

    # 11. 연산 cycle(P4.1): 추론 요청 = 240 + 4⌈n1/2⌉ + ⌈n2/2⌉ + 2 + 67, 모든 입력 spike 1,205, entry 28.5 tile, 적재 131,648 B
    check('11a dense cycles', hw.dense_req_us / CLK, 1205.0, 1e-6)
    check('11b entry tiles', hw.entry_tiles, 28.5, 0)
    check('11c weight load B', float(hw.model_bytes), 131648.0, 0)
    d = os.path.join(ROOT, 'hardware', 'data', 'golden_l64')
    tab = golden_words(hw.arch, tuple(hw.groups), hw.spikes_per_cycle, hw.models)
    with open(os.path.join(d, 'manifest.json')) as f:
        recs = json.load(f)['records']
    z = np.load(os.path.join(d, recs[0]['unit'], recs[0]['tag'] + '.npz'))
    n1, n2 = z['spk_l1'].sum(1)[1:], z['spk_l2'].sum(1)[1:]
    check('11d request cycles = P4.1 formula',
          float(np.abs(tab[0][0] + 67 - (240 + 4 * np.ceil(n1 / 2) + np.ceil(n2 / 2) + 2 + 67)).max()), 0.0, 0)
    w = s.workload('uniform', 0)
    check('11e max request cycles <= 1,205', float((w.cost / CLK).max() <= 1205 + 1e-6), 1.0, 0)
    check('11f output layer words with 48 lanes = ceil(128 / 48)', float(Hardware(lanes=48).groups[-1][1]), 3.0, 0)

    # 12. δ: uniform 수치 적분 = (J − e)/(r + 1), cd·tail의 δ(0, 1) = 평균
    ju = Jitter.of('uniform', 3200.0)
    err = max(abs(ju.delta(e, r, closed=False) - (3200.0 - e) / (r + 1)) for e in (0.0, 700.0, 2500.0) for r in (1, 3, 25))
    check('12a uniform δ numeric = closed form µs', err, 0.0, 0.5)
    check('12b cd δ(0, 1) = J/2 µs', Jitter.of('cd', 3200.0).delta(0.0, 1), 1600.0, 1.0)
    check('12c tail δ(0, 1) = mean µs', Jitter.of('tail', 3200.0).delta(0.0, 1), 0.95 * 400.0 + 0.05 * 2000.0, 1.0)
    check('12d tail J <= 0.8 ms mean µs', Jitter.of('tail', 400.0).delta(0.0, 1), 0.95 * 200.0 + 0.05 * 400.0, 1.0)

    # 13. offline Belady = 전수 탐색 최소(시작 entry는 무엇이든, 둘째 batch부터 연산 중 entry 보호), 그리고 정책의 적재 수 이하
    def brute(seq, E):
        best = {frozenset(c): 0 for c in itertools.combinations(range(5), E)}
        for i, m in enumerate(seq):
            nxt = {}
            for cache, cost in best.items():
                opts = [cache] if m in cache else ([cache | {m}] if len(cache) < E else
                                                   [cache - {v} | {m} for v in cache if not (i and v == seq[i - 1])])
                for c2 in opts:
                    c = cost + (m not in cache)
                    if nxt.get(c2, 1 << 30) > c:
                        nxt[c2] = c
            best = nxt
        return min(best.values())
    rng = np.random.default_rng(7)
    bad = 0
    for _ in range(300):
        E = int(rng.integers(2, 4))
        seq = rng.integers(0, 5, int(rng.integers(3, 12))).tolist()
        seq = [x for i, x in enumerate(seq) if i == 0 or x != seq[i - 1]]   # 같은 모델 batch가 이어지면 hit
        bad += belady(seq, E, [1] * len(seq)) != brute(seq, E)
    check('13a Belady = exhaustive minimum (300 cases)', float(bad), 0.0, 0)
    for name in ('lru', 'pnu_count', 'oracle_min'):
        r = engine.Setup({**base, 'cache_policy': name}).run('uniform', 0, detail=True)
        check(f'13b Belady <= loads ({name})', float(r['belady_loads'] <= r['weight_loads']), 1.0, 0)

    # 15. trace: 앞 절반 주기는 분포 추정, 뒤 절반을 재생
    tp = os.path.join(HERE, '__trace_check.csv')
    rows = [dict(period=k, track_id=j, model_id=0, t_host_us=1000.0 * k, t_ready_us=1000.0 * k + 100 * j + 10 * k) for k in range(4) for j in range(3)]
    write_csv(tp, rows)
    jt = TraceJitter(tp)
    os.remove(tp)
    exp = np.array([[100 * j + 10 * k for k in (2, 3)] for j in range(3)], float)
    check('15a trace replay = second half', float(np.abs(jt.draw(0, 3, 2) - exp).max()), 0.0, 1e-9)
    check('15b trace distribution max = first-half max', jt.max_us, 210.0, 1e-9)
    # 16. window 안 재적재: entry 2, 같은 주기에 모델 0 → 1 → 2 → 0이면 모델 0을 두 번 적재
    w16 = W(hw, 4, warmup=0, meas=1, d_in=0.0, d_out=0.0, offset=[0.0] * 4, track_model=[0, 1, 2, 0],
            jit=[[100.0], [200.0], [300.0], [400.0]])
    r = simulate(w16, LRU(hw, entries=2), Grouping(hw), Compute(hw))
    check('16 4 loads, 1 window reload, 3 (model, period) pairs',
          abs(r['weight_loads'] - 4) + abs(r['window_reloads'] - 1) + abs(r['model_periods'] - 3), 0.0, 0)
    # 17·18. Global alignment는 nominal offset 0. 모델 41개면 offset 간격 32/41 ms
    w = engine.Setup({**base, 'host_offset': 'global_alignment'}).workload('uniform', 0)
    check('17 Global alignment nominal offset', float(np.abs(w.nominal).max() + np.abs(w.t_host % P).max()), 0.0, 0)
    w = engine.Setup({**base, 'model_count': 41}).workload('uniform', 0)
    m40 = w.model == 40
    check('18 41 models: offset gap (model 40) µs', float(np.unique(w.t_host[m40] % P)[0]) if m40.any() else -1.0, 40 * P / 41, 1e-6)
    # 19. BRAM: entry + 준비 버퍼 + on-chip membrane potential ≤ 예산. Entry 4면 768트랙(04 §2), entry 0(예산에 들어가는 최대)은
    #     실제 entry 수로 남는 tile을 센다
    for ent, exp in ((4, 768), (0, None)):
        x = engine.Setup(template(cache_entries=ent))
        mem = sum(bram_tiles(x.on_chip_tracks * n, x.hw.membrane_bits) for n in x.hw.arch[1:])
        check(f'19 BRAM entry + buffer + on-chip membrane <= budget (cache_entries {ent}, entry {x.cache.entries})',
              float(x.used_tiles + mem <= x.hw.tile_budget - x.e['bram_reserve_tiles']), 1.0, 0)
        if exp is not None:
            check('19 on-chip tracks with 4 entries', float(x.on_chip_tracks), float(exp), 0)
    return check.ok


# ---- 2. P3.26 ----
def selftest_p326():
    """모델·주기 모델 그룹 지연(host_model_group_delay_trace), 모델 그룹 지연을 아는 PNU, 같은 트랙 drop 규칙(06 §4.3 ERR_CODE 5),
    deadline 분석(packet 분할, 조건부 response time, 지연 꼴, adversarial search)"""
    check = Check()
    base = template(host_jitter_dist='none', host_jitter_ms=0.0, track_count=256, sim_warmup_periods=4, sim_meas_periods=16,
                    cache_policy='pnu_count', fpga_drop_busy=True,
                    host_model_group_delay_trace='hardware/board_test/p325_meas/result/m3_group_pin3_load0.csv.gz')
    hw = engine.Setup(base).hw
    # 1. 모델 그룹 지연 표: 행 = 모델, 앞 절반 주기 = 분포, 뒤 절반을 seed마다 다른 주기부터 재생(seed 1, 주기 3개 → 뒤 절반의 4번째 주기부터)
    tp = os.path.join(HERE, '__group_check.csv')
    write_csv(tp, [dict(period=k, model_id=m, delay_us=100.0 * m + k) for k in range(8) for m in range(2)])
    gt = TraceJitter(tp)
    os.remove(tp)
    exp = np.array([[100.0 * (m % 2) + 4 + (3 + k) % 4 for k in range(3)] for m in range(3)])
    check('1a group table replay (rows = models, different periods per seed)', float(np.abs(gt.draw(1, 3, 3) - exp).max()), 0.0, 1e-9)
    check('1b group table distribution max = first-half max', gt.max_us, 103.0, 1e-9)
    # 2. 같은 모델·주기 추론 요청은 같은 모델 그룹 지연을 받고(추론 요청별 지연 0이면 퍼짐 0), 주기마다 다르며, 트랙의 준비 순서는 그대로다
    for dist, J, lim in (('none', 0.0, 0.0), ('uniform', 0.8, 800.0)):
        w = engine.Setup({**base, 'host_jitter_dist': dist, 'host_jitter_ms': J}).workload('uniform', 0)
        d = w.t_ready - w.t_host
        key = w.model * 1000 + w.period
        check(f'2a spread within a model and period <= {lim:g} µs ({dist})',
              float(max(np.ptp(d[key == k]) for k in np.unique(key)) <= lim + 1e-9), 1.0, 0)
    check('2b group delay differs by period', float(np.unique(np.round(d[w.track == w.track[0]], 3)).size > 1), 1.0, 0)
    o = np.lexsort((w.period, w.track))
    check('2c ready order kept per track', float((np.diff(w.t_ready[o])[np.diff(w.track[o]) == 0] >= 0).all()), 1.0, 0)
    # 3. Drop 규칙: 트랙 1개. 주기 0 추론 요청이 31.99 ms에 준비되어 끝나기 전에 주기 1 추론 요청(32 ms)이 오면 버린다.
    #    버린 추론 요청의 앞 추론 요청은 이미 늦다(다음 추론 요청 도착 ≥ 앞 추론 요청 t_host + 32 ms). 31 ms면 앞 추론 요청이 끝난 뒤라 버리지 않는다
    res = {}
    for j0, drop, exp_drop, exp_miss in ((31990.0, True, 1, 2), (31990.0, False, 0, 1), (31000.0, True, 0, 0)):
        w3 = W(hw, 1, warmup=0, meas=2, d_in=0.0, d_out=0.0, offset=[0.0], track_model=[0], jit=[[j0, 0.0]], drop_busy=drop)
        res[j0, drop] = r = simulate(w3, LRU(hw, entries=2), Grouping(hw), Compute(hw))
        check(f'3 drop rule ({j0:.0f} µs, {"on" if drop else "off"}) drop · miss', abs(r['drop'] - exp_drop) + abs(r['miss'] - exp_miss), 0.0, 0)
    load = hw.load_us(hw.model_bytes)
    check('3d max response of requests with a result = period-0 request µs', res[31990.0, True]['max_done_ms'] * 1000,
          31990.0 + load + hw.dense_req_us, 1e-6)
    r = res[31990.0, True]
    check('3e max Host processing delay · max after ready (load + compute) µs', abs(r['host_max_ms'] * 1000 - 31990.0)
          + abs(r['fpga_side_max_ms'] * 1000 - load - hw.dense_req_us), 0.0, 1e-6)
    # 3f. 버린 추론 요청 뒤에 다른 모델 추론 요청(32.1 ms)이 오면 Grouping이 버린 추론 요청을 건너뛰고 끝까지 처리한다(멈추면 이 시험이 끝나지 않는다)
    w3 = W(hw, 2, warmup=0, meas=2, d_in=0.0, d_out=0.0, offset=[0.0, 100.0], track_model=[0, 1], jit=[[31990.0, 0.0], [0.0, 0.0]],
           drop_busy=True)
    r = simulate(w3, LRU(hw, entries=2), Grouping(hw), Compute(hw))
    check('3f processing after a drop: drop · processed requests', abs(r['drop'] - 1) + abs(r['req_win'] - 3), 0.0, 0)
    # 3g. Queue가 빈 채로 다음 도착까지 넘겼는데 그 도착이 버린 추론 요청인 경우: 트랙 0 주기 0(31.995 ms, weight 적재됨)이 연산 중일 때
    #     주기 1(32 ms)이 온다. 다음 추론 요청(트랙 1, 33 ms)까지 넘어가 끝까지 처리한다
    w3 = W(hw, 2, warmup=0, meas=2, d_in=0.0, d_out=0.0, offset=[0.0, 1000.0], track_model=[0, 0], jit=[[31995.0, 0.0], [0.0, 0.0]],
           drop_busy=True)
    r = simulate(w3, LRU(hw, entries=2), Grouping(hw), Compute(hw))
    check('3g dropped arrival after an empty queue: drop · miss · processed requests',
          abs(r['drop'] - 1) + abs(r['miss'] - 2) + abs(r['req_win'] - 3), 0.0, 0)
    # 4. 모델 그룹 지연 PNU 손계산: 모델 0 트랙 2개(offset 0)가 주기 0에 3.0·3.3 ms에 준비. G ~ U(0, 4 ms), 추론 요청별 U(0, 0.8 ms)
    #    첫 추론 요청 전(2 ms): 2 + δ_G(2, 1) = 3 ms. 첫 추론 요청(3 ms) 뒤 3.1 ms: 3.1 + δ(0.1, 1). 다 오면 다음 주기 32 + E[G] + δ(0, 2)
    w4 = W(hw, 3, warmup=0, meas=2, d_in=0.0, d_out=0.0, offset=[0.0, 0.0, 10000.0], track_model=[0, 0, 1],
           jit=[[3000.0, 3000.0], [3300.0, 3300.0], [0.0, 0.0]])
    w4.jitter, w4.model_group_delay = Jitter.of('uniform', 800.0), Jitter.of('uniform', 4000.0)
    for cls, cases in ((PNU, ((2000.0, 3000.0), (3100.0, 3450.0), (3400.0, P + 2000.0 + 800.0 / 3))),
                       (PNUTimeout, ((2000.0, 3000.0), (3100.0, 3450.0), (3400.0, 3600.0)))):
        st = cls(hw, entries=2)
        st.reset(w4)
        st.queue = queue = Queue(w4)
        for now, exp in cases:
            queue.advance(now)
            queue.take(0, list(queue.by_model[0]))
            st.now = now
            st._count_arrivals()
            check(f'4 {cls.name} next use with group delay now={now:.0f} µs', st._next_use(int(st.groups_of_model[0][0]), now), exp, 1e-6)
    st = PNU(hw, entries=2, model_group_delay_aware=False)
    st.reset(w4)
    st.queue, st.now = Queue(w4), 2000.0
    st.queue.advance(2000.0)
    st._count_arrivals()
    check('4c model_group_delay_aware off (P3.25 formula): a late group counts as done for this period',
          st._next_use(int(st.groups_of_model[0][0]), 2000.0), P + 800.0 / 3, 1e-6)
    # 5. 미래 추론 요청의 도착만 바꿔도 그 전 시각의 모델 그룹 지연 PNU-Count 결정은 같다
    s = engine.Setup({**base, 'host_jitter_dist': 'uniform', 'host_jitter_ms': 0.8})
    wl = s.workload('uniform', 0)
    t_cut = wl.w0 + 4 * P

    def runs(w):
        st = recorder(PNU)(s.hw, entries=4)
        simulate(w, st, s.scheduler, s.compute)
        return [x for x in st.log if x[0] < t_cut]
    a, b = same_until(wl, t_cut, runs)
    check('5 decisions equal after changing future arrivals (PNU-Count with group delay)', float(a == b and len(a) > 0), 1.0, 0)

    # 6. packet 분할: 같은 모델·주기·송신 시각 추론 요청 50개 → 23개씩 packet, 도착 +0 × 23, +1 ms × 23, +2 ms × 4
    w6 = W(hw, 50, warmup=0, meas=1, d_in=0.0, d_out=0.0, offset=0.0, track_model=[0] * 50)
    w6.packetize(1000.0)
    check('6 packet split arrivals µs', float(np.abs(np.sort(w6.t_arr) - np.repeat([0.0, 1000.0, 2000.0], [23, 23, 4])).max()), 0.0, 0)
    # 7. 조건부 response time(05 §6.1): CPU 고정·부하 없음, J = 0.8 ms, entry 4에서 R_single ≈ 14.41 ms, R_cond ≈ 24.22 ms.
    #    R_single = N·C_dense + M·L_weight + N_DDR3·C_state(N_DDR3 = 1,024 − on-chip 768)
    s7 = engine.Setup(engine.points(engine.load(engine.TEMPLATE))[0][1])
    b7 = bound(s7)
    rw = -(-706 * 12 // 8)
    single = 1024 * s7.hw.dense_req_us + 40 * s7.hw.load_us(131648) + 256 * (2 * DMA_SETUP_US + rw / 3015 + rw / 2768)
    check('7a R_single = hand formula ms', b7['single_fpga_ms'], single / 1000, 1e-9)
    check('7b R_single ms (05 §6.1)', b7['single_fpga_ms'], 14.41, 0.005)
    check('7c R_cond ms (05 §6.1)', b7['cond_e2e_ms'], 24.22, 0.005)
    # 8. adversarial 지연 꼴: 모델 0(트랙 2개) = gmax + late, 모델 1(트랙 24개) = g0 + pkt(앞 23트랙은 0, 24번째는 J 직전).
    #    값은 범위 [0, G)·[0, J) 안의 최대
    tm8 = np.array([0, 0] + [1] * 24)
    d8 = DelayPattern([1, 0], [1, 5]).delays(tm8, 2, 1000.0, 500.0)
    exp8 = np.array([[np.nextafter(1000.0, 0) + np.nextafter(500.0, 0)] * 2] * 2 + [[0.0, 0.0]] * 23 + [[np.nextafter(500.0, 0)] * 2])
    check('8 delay pattern gmax + late, g0 + pkt µs', float(np.abs(d8 - exp8).max()), 0.0, 0)
    # 9. adversarial search가 끝까지 돈다(트랙 80개, 2주기): 시작점 38개 + 언덕 오르기 24번, 고른 꼴이 시험한 꼴 중 가장 나쁘다
    e9 = template(track_count=80, sim_warmup_periods=0, sim_meas_periods=2, sim_scenarios=['uniform'], compute_input='dense')
    r9 = engine.Adversarial.one((0, 'small', e9, 0))
    check('9 adversarial evaluations · worst = max of tested', abs(r9['evals'] - 62)
          + abs(r9['adv_send_max_ms'] - max(t['send_max_ms'] for t in r9['tested'])), 0.0, 0)
    return check.ok


# ---- 3. 환경 파일: 모두 읽히고 첫 점이 돈다 ----
def env_files():
    for p in sorted(glob.glob(os.path.join(engine.ENV_DIR, '*.toml'))):
        pts = engine.points(engine.load(p))
        lb, e = next(((lb, e) for lb, e in pts if engine.Setup(e).feasible), pts[0])   # BRAM에 들어가는 첫 점(engine은 넘치는 점을 돌리지 않는다)
        r = engine.Setup(e).run(e['sim_scenarios'][0], e['sim_seed0'], detail=True)
        print('ok env', os.path.basename(p), f'{len(pts)} points', lb, r['n_req'])
    return True


# ---- 4. 결과 CSV: 쓰고 읽으면 값이 그대로다(µ처럼 ASCII 밖 문자도) ----
def csv_round_trip():
    rows = [dict(point=0, label='base · µs', s='', num_like='1', b=True, n=None, f=0.1 + 0.2, i=3, li=[[1, 2]], d={'W': 5000.0}, np_i=np.int64(7)),
            dict(point=1, label='0 base: Dysta Method, dense', s='ddr3', num_like='true', b=False, n=None, f=float('inf'), i=-1, li=[], d={},
                 np_i=np.int64(0))]
    p = os.path.join(HERE, '__csv_check.csv.gz')
    write_csv(p, rows)
    back = read_csv(p)
    os.remove(p)
    assert back == [{k: (int(v) if isinstance(v, np.integer) else v) for k, v in r.items()} for r in rows], back
    print('ok result CSV round trip')
    return True


PARTS = {'core': selftest, 'p325': selftest_p325, 'p326': selftest_p326, 'env': env_files, 'csv': csv_round_trip}
names = sys.argv[1:] or list(PARTS)
assert set(names) <= set(PARTS), f'unknown part {sorted(set(names) - set(PARTS))}, choose from {list(PARTS)}'
for name in names:
    assert PARTS[name](), f'{name} checks failed'
