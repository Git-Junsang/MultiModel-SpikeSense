#!/usr/bin/env python3
"""test_engine.py — engine 확인. 약 15초

  1. 본체 손계산: 트랙 1~512개의 응답 시간, DDR3 전송량·전송률, cycle, 비교군 정책의 동작, P3.17·P3.19 환경 키(모아 보내기, offset 간격, 트랙별 membrane potential, layer별 bit)를 식으로 계산한 값과 비교한다(56항목)
  2. 환경 파일: simulation/environment의 모든 파일을 읽고, BRAM에 들어가는 첫 점을 한 번 돌린다
  3. 결과 CSV: 쓰고 읽으면 값이 그대로다

engine이 옛 실험 스크립트(P3.5~P3.13)와 같은 결과를 내는 것은 2026-10-15에 실행마다 비교해 확인했다(P3.14 보고서).

    python3 simulation/engine/test_engine.py
"""
import glob
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine  # noqa: E402

# ---- 1. 본체 손계산 (옛 run_sim.py selftest) ----
# 아래 함수는 기본 구성(32 lane, 512트랙)의 상수를 import 시점 값으로 썼다. 같은 이름으로 넘긴다
sim_core = sc = engine
engine.configure()
BW, C_REQ, MODEL_B, P, T0 = engine.BW, engine.C_REQ, engine.MODEL_B, engine.P, engine.T0
make_workload, simulate, xfer_time = engine.make_workload, engine.simulate, engine.xfer_time
(FullCache, L1Resident, PartialAll, PinnedHybrid, Stream, AllAtOnce, RowByRow, FCFS, Grouping, Dysta, Timeout,
 ScoreGuard, ScoreWait, LazyGroup, TimeoutBatch, SlackBatchHW, Clockwork, DeepRT, FurthestNext, PinLRU, ShepherdNP,
 Symphony) = (getattr(engine, n) for n in (
    'FullCache', 'L1Resident', 'PartialAll', 'PinnedHybrid', 'Stream', 'AllAtOnce', 'RowByRow', 'FCFS', 'Grouping',
    'Dysta', 'Timeout', 'ScoreGuard', 'ScoreWait', 'LazyGroup', 'TimeoutBatch', 'SlackBatchHW', 'Clockwork', 'DeepRT',
    'FurthestNext', 'PinLRU', 'ShepherdNP', 'Symphony'))


def selftest():
    ok = True

    def check(name, got, exp, tol):
        nonlocal ok
        good = abs(got - exp) <= tol
        ok &= good
        print(f'{"PASS" if good else "FAIL"}  {name}: 시뮬 {got:.6f}, 기대 {exp:.6f}')

    # 1. 트랙 1개: 응답 시간 = d_in + 전송 + 연산 + d_out, 두 번째 요청부터는 cache hit라 전송 0
    wl = make_workload(1, warm=0, meas=4, d_in=27.0, d_out=25.0, offset=100.0, track_model=[0])
    for C in (AllAtOnce, RowByRow):
        r = simulate(wl, FullCache(), FCFS(), C())['resp']
        if C is AllAtOnce:
            check('1a 트랙 1개 첫 요청(한번에) µs', r[0], 27 + T0 + MODEL_B / BW + C_REQ + 25, 1e-6)
        else:   # 한 줄씩은 전송·연산이 겹치므로 max(전송, 연산) ≤ 시간 ≤ 전송 + 연산
            lo, hi = 52 + max(T0 + MODEL_B / BW, C_REQ), 52 + T0 + MODEL_B / BW + C_REQ
            check('1b 트랙 1개 첫 요청(한줄씩) 범위 안', float(lo <= r[0] <= hi), 1.0, 0)
        check(f'1c hit 요청({C.name}) µs', r[1:].max(), 27 + C_REQ + 25, 1e-6)

    # 2. 모든 트랙 동시 도착 + 그룹핑 + cache 5벌: 주기마다 사용 모델 수 × 131,588 B
    wl = make_workload(512, seed=1, d_in=0.0, d_out=0.0, offset=0.0)
    used = len(set(wl.track_model.tolist()))
    for C in (AllAtOnce, RowByRow):
        res = simulate(wl, FullCache(), Grouping(), C())
        check(f'2 완전 그룹핑 전송률({C.name}) MB/s', res['mbps'], used * MODEL_B / P, 1e-6)

    # 3. cache가 40모델을 모두 담으면 워밍업 뒤 전송 0
    res = simulate(wl, FullCache(entries=40), Grouping(), RowByRow())
    check('3 cache 40벌 전송률 MB/s', res['mbps'], 0.0, 0)

    # 4. 연산 가동률 = N × 요청당 연산 / 주기 (실측 지연 표본, offset 무작위)
    wl = make_workload(512, seed=2)
    res = simulate(wl, L1Resident(), Grouping(), RowByRow())
    check('4 연산 가동률', res['cmp_util'], 512 * C_REQ / P, 0.005)

    # ---- rev 2 (MODEL_SIZE_PLAN §4.2) ----
    # 5. Host batch 전송: 트랙 1개, cache hit 요청의 응답 시간 = 결과 읽기 시각 + C2H 지연 − 생성 시각
    wl = make_workload(1, warm=0, meas=6, offset=100.0, track_model=[0], host=1000.0)
    r = simulate(wl, FullCache(), FCFS(), AllAtOnce())['resp']
    fin = wl.t_arr[1:] + C_REQ
    j = np.ceil((fin - wl.out_phi) / 1000.0)
    exp = wl.out_phi + j * 1000.0 + wl.out_lat[j.astype(int)] - wl.t_gen[1:]
    check('5a Host batch 응답 시간(hit) 최대 오차 µs', float(np.abs(r[1:] - exp).max()), 0.0, 1e-6)
    wait = wl.t_arr - wl.t_gen
    check('5b 입력 대기 + H2C ≤ W_h + 실측 최대', float(wait.max() <= 1000.0 + 120.3), 1.0, 0)
    # 동시 도착 512개는 H2C 1회(32 KiB): 지연 = 표본 + (512 × 64 − 64) / 758
    wl = make_workload(512, seed=3, offset=0.0, host=1000.0)
    w = wl.t_arr[wl.t_gen == wl.t_gen.min()] - wl.t_gen.min()
    lo = sim_core.load_samples(sim_core.H_IN_FILE).min() + (512 * 64 - 64) / 758.0
    hi = 1000.0 + sim_core.load_samples(sim_core.H_IN_FILE).max() + (512 * 64 - 64) / 758.0
    check('5c 동시 도착 512개 지연이 [표본 최소 + 크기 항, W_h + 표본 최대 + 크기 항] 안', float(lo <= w[0] <= hi), 1.0, 0)
    check('5d 동시 도착은 한 번에 도착(같은 시각)', float(np.ptp(w)), 0.0, 1e-9)

    # 6. membrane potential DDR3 비용(rev 2): 읽기 1,412 / 3,015 + 쓰기 1,412 / 2,768 B/µs
    sim_core.configure(64, 1024, mem='ddr', rev=2)
    check('6 membrane potential 왕복 DMA µs/요청', sim_core.mem_time(1), 1412 / 3015 + 1412 / 2768, 1e-9)

    # 7. 한 줄씩 batch ≤ 64 (rev 2, membrane potential on-chip): 같은 모델 512트랙 동시 도착 → 주기마다 batch 8개 × 64
    sim_core.configure(32, 512, mem='onchip', rev=2)
    wl = make_workload(512, seed=1, d_in=0.0, d_out=0.0, offset=0.0, track_model=[0] * 512)
    res = simulate(wl, FullCache(), Grouping(), RowByRow())
    check('7 한 줄씩 batch 평균(상한 64)', res['batch_mean'], 64.0, 1e-9)

    # ---- 목표 트랙 실험 (target_exp.py) ----
    # 8. cycle 회계: 트랙 1개, 첫 요청만 miss. 연산 = 4 × 요청당 연산, 정지 = 첫 적재, 유휴 = 나머지
    sim_core.configure()
    wl = make_workload(1, warm=0, meas=4, d_in=27.0, d_out=25.0, offset=100.0, track_model=[0])
    res = simulate(wl, FullCache(), FCFS(), AllAtOnce(), detail=True)
    ld = sim_core.T0 + sim_core.MODEL_B / sim_core.BW
    check('8a 연산 cycle', res['cyc_busy'], 4 * sim_core.C_REQ * 100, 1e-6)
    check('8b 정지 cycle = 첫 모델 적재', res['cyc_stall'], ld * 100, 1e-6)
    check('8c 연산 + 정지 + 유휴 = 측정 구간', res['cyc_busy'] + res['cyc_stall'] + res['cyc_idle'], 4 * P * 100, 1e-3)
    check('8d 응답 시간 분해 입력 + FPGA + 출력 = 평균 응답 시간 ms', res['in_ms'] + res['fpga_ms'] + res['out_ms'], res['mean_ms'], 1e-9)
    check('8e FPGA 체류 평균 ms', res['fpga_ms'], (ld + 4 * sim_core.C_REQ) / 4 / 1000, 1e-9)
    # 9. 실측 지연 표본·무작위 offset(한 줄씩): 연산 ≤ FPGA 체류 구간, 연산 cycle ≈ 가동률 × 구간
    wl = make_workload(512, seed=2)
    res = simulate(wl, FullCache(), Grouping(), RowByRow(), detail=True)
    span = (wl.w1 - wl.w0) * 100
    check('9a 연산 + 정지 + 유휴 = 측정 구간', res['cyc_busy'] + res['cyc_stall'] + res['cyc_idle'], span, 1e-3)
    check('9b 정지 ≥ 0', float(res['cyc_stall'] >= 0), 1.0, 0)
    check('9c 연산 cycle / 구간 ≈ 연산 가동률', res['cyc_busy'] / span, res['cmp_util'], 0.002)
    # 10. 예산 맞춤 B는 L 32레인 기준 환경에서 B.L1상주와 같다(layer 1 전체 + β·vth 상주)
    c = RowByRow()
    b, b0 = PartialAll(compute=c), L1Resident()
    check('10 B.부분상주 = B.L1상주 (L 32레인)', float(b.k == sim_core.N_L1 and b.bv and b.loads == sim_core.L2L4
                                                    and b.tiles() + c.extra_tiles(b) == b0.tiles() + c.extra_tiles(b0)), 1.0, 0)
    # 11. 고정 혼합: 고정 모델만 쓰는 트랙은 첫 요청부터 전송 없이 연산
    wl = make_workload(1, warm=0, meas=4, d_in=27.0, d_out=25.0, offset=100.0, track_model=[0])
    for C in (AllAtOnce, RowByRow):
        res = simulate(wl, PinnedHybrid(compute=C()), FCFS(), C())
        check(f'11 고정 모델 응답 시간({C.name}) µs', res['resp'].max(), 27 + C_REQ + 25, 1e-6)
    # 12. rev 4 슬라이스 칸: XL 256레인은 layer 2 그룹 768 word, L 32레인은 rev 3과 같음
    sim_core.configure(256, 1024, mem='ddr', rev=4, arch=(40, 768, 512, 128, 2))
    check('12a XL 256레인 칸 word', sim_core.SLOT_WORDS, 768, 0)
    check('12b XL 256레인 이중 버퍼 타일', sim_core.SLICE_T, 85.5, 0)
    sim_core.configure(32, 512, rev=4)
    check('12c L 32레인 이중 버퍼 타일(rev 3과 같음)', sim_core.SLICE_T, 7.5, 0)
    sim_core.configure()

    # ---- 점수 방식 개선 (점수2·3) ----
    # 13. deadline guard 손계산(L 32레인, membrane potential on-chip이라 membrane potential DMA 0): 후보 (deadline, 모델, n, 남은 전송)
    g = ScoreGuard(margin=0.0)
    cand = [(500.0, 0, 1, 100.0), (20000.0, 1, 10, 0.0)]
    check('13a 가장 늦은 시작 = min(500 − (100 + C), 20,000 − (100 + 11C))', g._latest_start(cand),
          min(500 - (100 + C_REQ), 20000 - (100 + 11 * C_REQ)), 1e-9)
    check('13b 모델 1을 먼저 하면 모델 0이 늦음 → 불가', float(g._safe(cand[1], cand, 0.0)), 0.0, 0)
    cand[0] = (10000.0, 0, 1, 100.0)
    check('13c 모델 0 deadline이 넉넉하면 → 가능', float(g._safe(cand[1], cand, 0.0)), 1.0, 0)
    # 14. 점수3: 트랙 1개는 다음 요청이 32 ms 뒤라 기다리지 않는다 → 1a와 같은 응답
    wl = make_workload(1, warm=0, meas=4, d_in=27.0, d_out=25.0, offset=100.0, track_model=[0])
    r = simulate(wl, FullCache(), ScoreWait(margin=0.0), AllAtOnce())['resp']
    check('14 점수3 트랙 1개 첫 요청 µs (기다리지 않음)', r[0], 27 + T0 + MODEL_B / BW + C_REQ + 25, 1e-6)
    # 15. 점수3: 같은 모델 트랙 2개(offset 0, 1 ms)는 두 번째 요청을 기다려 한 batch → 주기마다 모델 1번 적재(스트림)
    wl = make_workload(2, warm=0, meas=4, d_in=27.0, d_out=25.0, offset=[0.0, 1000.0], track_model=[0, 0])
    for Q, per in ((Grouping, 2), (ScoreWait, 1)):
        res = simulate(wl, Stream(), Q(margin=0.0) if Q is ScoreWait else Q(), AllAtOnce())
        check(f'15 {Q.name} 요청당 weight B (주기마다 적재 {per}번)', res['w_bytes'] / res['req_win'], MODEL_B * per / 2, 1e-6)
    # 16. 시간제한 batch: 같은 모델 트랙 2개가 10 ms 간격이면 W = 8 ms는 따로(적재 2번), W = 16 ms는 함께(1번)
    wl = make_workload(2, warm=0, meas=4, d_in=27.0, d_out=25.0, offset=[0.0, 10000.0], track_model=[0, 0])
    for W, per in ((8000.0, 2), (16000.0, 1)):
        res = simulate(wl, Stream(), TimeoutBatch(margin=0.0, max_wait=W), AllAtOnce())
        check(f'16 시간제한 W = {W / 1000:.0f} ms 요청당 weight B (적재 {per}번)', res['w_bytes'] / res['req_win'],
              MODEL_B * per / 2, 1e-6)
    # 17. 지연 그룹핑도 deadline 여유 안이면 두 번째 요청을 기다려 한 batch(적재 1번), 첫 요청 응답 시간 = 10 ms 대기 + 전송 + 연산 2개
    res = simulate(wl, Stream(), LazyGroup(margin=0.0), AllAtOnce())
    check('17a 지연 그룹핑 요청당 weight B (적재 1번)', res['w_bytes'] / res['req_win'], MODEL_B / 2, 1e-6)
    check('17b 지연 그룹핑 첫 요청 응답 시간 µs', res['resp'][0], 10000 + 27 + T0 + MODEL_B / BW + C_REQ + 25, 1e-6)
    # 18. Dysta Method는 기다리지 않는다: 트랙 1개 첫 요청 = 1a
    wl = make_workload(1, warm=0, meas=4, d_in=27.0, d_out=25.0, offset=100.0, track_model=[0])
    r = simulate(wl, FullCache(), Dysta(margin=0.0), AllAtOnce())['resp']
    check('18 Dysta Method 트랙 1개 첫 요청 µs', r[0], 27 + T0 + MODEL_B / BW + C_REQ + 25, 1e-6)
    # 19. Timeout(guard 없음): 트랙 1개 첫 요청은 도착 뒤 W를 기다린 다음 처리
    r = simulate(wl, FullCache(), Timeout(max_wait=3000.0), AllAtOnce())['resp']
    check('19 Timeout W = 3 ms 트랙 1개 첫 요청 µs', r[0], 27 + 3000 + T0 + MODEL_B / BW + C_REQ + 25, 1e-6)
    # 20. SlackBatch(HW)는 다음 도착을 모르므로 LS − slack − next_arr까지 기다린다: 응답 시간 = 32 ms − 4 ms − 1 ms + C2H
    q = SlackBatchHW(margin=0.0)
    r = simulate(wl, FullCache(), q, AllAtOnce())['resp']
    check('20 SlackBatch(HW) 트랙 1개 첫 요청 µs', r[0], P - q.slack - q.next_arr + 25, 1e-6)
    # 21. cache 교체 반영 guard: entry 2벌 [0(오래됨), 1]에서 deadline 순서가 2 → 0 → 1이면 2가 0을, 0이 1을 밀어내 셋 다 전체 전송
    st = FullCache(entries=2)
    st.reset(None)
    st.lru.use(0), st.lru.use(1)
    full = xfer_time(sum(sc.FULL))
    xs = [c[3] for c in ScoreGuard._cache_walk([(1.0, 2, 1, full), (2.0, 0, 1, 0.0), (3.0, 1, 1, 0.0)], st)]
    check('21a 교체 반영: 밀려난 모델의 전송 µs 합', sum(xs), 3 * full, 1e-9)
    xs = [c[3] for c in ScoreGuard._cache_walk([(1.0, 1, 1, 0.0), (2.0, 0, 1, 0.0)], st)]
    check('21b 교체 반영: 둘 다 hit면 전송 0', sum(xs), 0.0, 1e-9)
    # 22. 비례 여유 α: 가장 늦은 시작 = deadline − margin − (1 + α) × batch 시간
    q = SlackBatchHW(margin=100.0)
    q.slack_ratio = 0.2
    bt = q._bt(full, 3)
    check('22 비례 여유 α 0.2 가장 늦은 시작 µs', q._latest_start([(P, 0, 3, full)]), P - 100.0 - 1.2 * bt, 1e-9)
    # 23~28: P3.11 비교군. membrane potential on-chip(기본 구성)이라 요청 하나를 더하는 시간 = C_REQ
    wl = make_workload(1, warm=0, meas=4, d_in=27.0, d_out=25.0, offset=100.0, track_model=[0])
    x = xfer_time(MODEL_B)
    # 23. Symphony Method: 하나 더 넣으면 못 맞추는 시각(deadline − 적재 − 연산 2개)까지 미룬다 → 응답 시간 = 32 ms − C_REQ + C2H
    r = simulate(wl, FullCache(), Symphony(margin=0.0), AllAtOnce())['resp']
    check('23 Symphony Method 트랙 1개 첫 요청 µs', r[0], P - C_REQ + 25, 1e-6)
    # 24. DeepRT Method: flush 없으면 window 끝(10 ms)에 처리, flush면 compute array가 놀 때 바로 처리(= 1a)
    q = DeepRT(margin=0.0)
    q.cfg = (10000.0, False)
    r = simulate(wl, FullCache(), q, AllAtOnce())['resp']
    check('24a DeepRT Method W 10 ms 첫 요청 µs', r[0], 10000 - 100 + x + C_REQ + 25, 1e-6)
    q.cfg = (10000.0, True)
    r = simulate(wl, FullCache(), q, AllAtOnce())['resp']
    check('24b DeepRT Method flush 첫 요청 µs', r[0], 27 + x + C_REQ + 25, 1e-6)
    # 25. drop: 회수 여유가 주기만큼이면 모든 요청을 못 맞춤 → 전부 drop, 모두 miss
    res = simulate(wl, FullCache(), Clockwork(margin=P), AllAtOnce())
    check('25 Clockwork Method drop 수 = miss 수 = 요청 수', float(res['drop'] == res['miss'] == res['n_req'] == 4), 1.0, 0)
    # 26. Shepherd Method: 모두 맞출 수 있으면 대기 요청이 많은 모델(0: 2개)을 고른다
    wl3 = make_workload(3, warm=0, meas=1, d_in=27.0, d_out=25.0, offset=0.0, track_model=[1, 0, 0])
    rd, st = sim_core.Ready(wl3), FullCache()
    st.reset(wl3)
    rd.advance(27.0)
    check('26 Shepherd Method 가장 큰 batch의 모델', float(ShepherdNP(margin=0.0).pick(rd, 27.0, st)[0]), 0.0, 0)
    # 27. F.다음사용: entry 3벌 [0, 1, 2(연산 중)]에 3이 오면 다음 사용이 가장 늦은 1(200 µs)을 내보낸다(0은 100 µs)
    wl4 = make_workload(4, warm=0, meas=1, d_in=27.0, d_out=25.0, offset=[100.0, 200.0, 300.0, 400.0], track_model=[0, 1, 2, 3])
    st = FurthestNext(entries=3)
    st.reset(wl4)
    st.rd, st.now = sim_core.Ready(wl4), 0.0
    for m in range(4):
        st.plan(m)
    check('27 F.다음사용 교체 대상', float(sorted(st.d) == [0, 2, 3]), 1.0, 0)
    # 28. E.인기고정: 트랙이 가장 많은 모델(0)은 entry 3벌 중 고정 1벌에 있어 적재가 없다
    st = PinLRU(entries=3)
    st.reset(wl3)
    check('28 E.인기고정 고정 모델 적재 B', float(sum(st.plan(0)) + sum(st.plan(0))), 0.0, 0)

    # ---- P3.17·P3.19 환경 키 ----
    # 29. 트랙별 membrane potential: 같은 모델 4트랙 동시 도착, 자리 [on-chip, 0, 1, 3] → 주기마다 DDR3 3트랙, DMA (0~1, 3) × 읽기·쓰기 = 4번
    sim_core.configure(64, 1024, mem='ddr', rev=4)
    wl = make_workload(4, warm=0, meas=4, d_in=0.0, d_out=0.0, offset=100.0, track_model=[0] * 4)
    wl.mem_addr = np.array([-1, 0, 1, 3])
    res = simulate(wl, FullCache(), Grouping(), AllAtOnce())
    check('29a 트랙별 membrane potential B', res['m_bytes'], 4 * 3 * sim_core.MEM_B, 1e-9)
    check('29b 트랙별 membrane potential DMA 횟수', res['m_xfers'], 4 * 4, 0)
    sim_core.configure()
    env = engine.load(engine.TEMPLATE)
    e = {**engine.points(env)[0][1], 'tracks': 80, 'warm': 0, 'meas': 4}
    engine.build(e)
    # 30. 모아 보내기 D ≥ jitter: 요청마다 늘어난 도착 = (모델·주기의 마지막 준비 시각) − 생성 시각
    w0, wg = (engine.workload({**e, 'jitter_ms': 3.2, 'gather_ms': g}, 'U', 0) for g in (0.0, 3.2))
    o0, og = np.lexsort((w0.t_gen, w0.track)), np.lexsort((wg.t_gen, wg.track))
    k = np.floor((w0.t_gen[o0] - w0.model[o0] * P / 40) / P)
    last = {}
    for m, kk, t in zip(w0.model[o0], k, w0.t_gen[o0]):
        last[m, kk] = max(last.get((m, kk), -1.0), t)
    exp = np.array([last[m, kk] for m, kk in zip(w0.model[o0], k)]) - w0.t_gen[o0]
    check('30 모아 보내기 늘어난 도착 최대 오차 µs', float(np.abs(wg.t_arr[og] - w0.t_arr[o0] - exp).max()), 0.0, 1e-6)
    # 31. offset 간격 ∝ 트랙 수(jitter 0): 모델 m+1의 offset − 모델 m의 offset = 모델 m 트랙 수 × P / 트랙 수
    wl = engine.workload({**e, 'offset': 'model_w', 'jitter_ms': 0.0}, 'K', 0)
    cnt = np.bincount(wl.track_model, minlength=40)
    offs = np.array([wl.t_gen[wl.model == m].min() if cnt[m] else np.nan for m in range(40)])
    used = np.flatnonzero(cnt)
    gap = np.diff(offs[used]) - np.add.reduceat(cnt, used)[:-1] * P / 80
    check('31 offset 간격 비례 최대 오차 µs', float(np.abs(gap).max()), 0.0, 1e-6)
    # 32. layer별 bit: 목록 [12, 12, 12, 12]은 12와 같은 on-chip 트랙 수
    check('32 layer별 bit 목록 = 같은 bit', float(engine.onchip_tracks({**e, 'tracks': 1024, 'bits': [12] * 4})
                                               == engine.onchip_tracks({**e, 'tracks': 1024, 'bits': 12})), 1.0, 0)
    # 33. 외부 지연: 도착만 pre_us만큼 늦고 생성 시각(deadline 기준)은 그대로
    w0, wp = (engine.workload({**e, 'pre_us': d}, 'U', 0) for d in (0.0, 5000.0))
    check('33a 외부 지연 도착 최대 오차 µs', float(np.abs(wp.t_arr - w0.t_arr - 5000.0).max()), 0.0, 1e-6)
    check('33b 외부 지연 생성 시각 최대 오차 µs', float(np.abs(wp.t_gen - w0.t_gen).max()), 0.0, 0)
    # 33c. 일정한 외부 지연은 G 교체를 바꾸지 않는다: weight byte 차이는 측정 구간 경계의 적재 2번 이내
    wb = [engine.simulate_point({**e, 'pre_us': d}, 'K', 0)['w_bytes'] for d in (0.0, 5000.0)]
    check('33c 외부 지연 weight byte 차이(적재 횟수)', abs(wb[1] - wb[0]) / sum(sim_core.FULL), 0.0, 2.0)
    sim_core.configure()
    return ok



assert selftest(), '본체 손계산 실패'

# ---- 환경 파일: 모두 읽히고 첫 점이 돈다 ----
for p in sorted(glob.glob(os.path.join(engine.ENV_DIR, '*.toml'))):
    env = engine.load(p)
    pts = engine.points(env)
    lb, e = next(((lb, e) for lb, e in pts if engine.build(e)[4]), pts[0])   # BRAM에 들어가는 첫 점(engine은 넘치는 점을 돌리지 않음)
    r = engine.simulate_point(e, e['scenarios'][0], e['seed0'])
    print('ok 환경', os.path.basename(p), f'점 {len(pts)}개', lb, r['n_req'])


# ---- 결과 CSV: 쓰고 읽으면 값이 그대로다 ----
rows = [dict(point=0, label='기준', s='', num_like='1', b=True, n=None, f=0.1 + 0.2, i=3, li=[[1, 2]], d={'W': 5000.0}, np_i=np.int64(7)),
        dict(point=1, label='0 기준: Clockwork Method, dense', s='ddr', num_like='true', b=False, n=None, f=float('inf'), i=-1, li=[], d={}, np_i=np.int64(0))]
p = os.path.join(os.path.dirname(os.path.abspath(__file__)), '__csv_check.csv.gz')
engine.write_csv(p, rows)
back = engine.read_csv(p)
os.remove(p)
assert back == [{k: (int(v) if isinstance(v, np.integer) else v) for k, v in r.items()} for r in rows], back
print('ok 결과 CSV 왕복')
