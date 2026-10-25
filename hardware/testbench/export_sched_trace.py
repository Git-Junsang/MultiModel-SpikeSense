"""P4.5: simulator(Grouping + PNU-count) 실행 하나를 tb_frontend.sv가 읽는 사건 기록으로 낸다.

p326_final_compare의 제안 구성(Model-Grouped Offset Assignment, Grouping, PNU-count, entry 4, Xeon CPU 고정·부하 없음 묶음 지연)에서
J·시나리오·seed·주기 수와 offset 배정(--offset model/global/none)만 바꿔 돌린다. global·none은 여러 모델이 함께 대기해
가장 오래된 추론 요청 고르기를 시험한다. 사건은 시각 순서이고 같은 시각이면 연산 완료 → 도착 → 연산 시작 순서다.
simulator 규칙과 같다: 완료 시각 ≤ 도착이면 drop이 아니고, 도착 ≤ batch 시작 s면 그 batch에 든다.

출력 hardware/sim/frontend/t<번호>/
  n.hex        줄 1 = 사건 수, 줄 2 = batch 수
  ev.hex       사건, 줄마다 256 bit. [255:254] 종류(0 완료, 1 도착, 2 시작), [253:222] 시각 µs(내림), [221:190] 추론 요청 번호,
               [189:180] 트랙, [179:174] 모델, [173:142] t_host µs(내림), [141:126] seq, [125] RESET_STATE, [124:109] n_expect,
               [108:93] batch 번호, [92] batch 첫 추론, [50] simulator가 버린 추론 요청, [49] 다음 사건과 시각이 정확히 같음
  batch.hex    batch마다 128 bit. [127:120] 모델, [119] hit, [118:103] 크기, [102:63] 계획할 때 모델별 queue 있음(40 bit)

프로젝트 루트에서:
  python3 hardware/testbench/export_sched_trace.py --id 0 --jitter 0.8 --scn U --seed 0
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "simulation" / "engine"))
import engine as E  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", type=int, required=True)
    ap.add_argument("--jitter", type=float, default=0.8)
    ap.add_argument("--scn", default="U")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--warm", type=int, default=8)
    ap.add_argument("--meas", type=int, default=16)
    ap.add_argument("--offset", default="model", choices=["model", "global", "none"])
    a = ap.parse_args()

    env = E.load(str(ROOT / "simulation/environment/p326_final_compare.toml"))
    e = next(e for _, e in E.points(env)
             if e["scheduler"] == "grouping" and e["cache_policy"] == "pnu_count" and e["host_offset"] == "model"
             and e["host_group_trace"].endswith("pin3_load0.csv.gz"))
    e = dict(e, host_jitter_ms=a.jitter, sim_warm_periods=a.warm, sim_meas_periods=a.meas, host_offset=a.offset)
    s = E.Setup(e)
    cache, sched, comp, M = s.cache, s.scheduler, s.compute, s.hw.models
    wl = s.workload(a.scn, a.seed)

    plans, mems, runs = [], [], []
    plan0, members0, run0 = cache.plan, sched.members, comp.run

    def plan(m, queue, now):
        qne = sum(1 << x for x in range(M) if queue.by_model[x])
        nb = plan0(m, queue, now)
        plans.append((m, nb == 0, qne))
        return nb

    def members(queue, m, head, t):
        idx = list(members0(queue, m, head, t))
        mems.append(idx)
        return idx

    def run(T, nbytes, mem):
        st, fin = run0(T, nbytes, mem)
        runs.append((st, np.array(fin, float)))
        return st, fin

    cache.plan, sched.members, comp.run = plan, members, run
    res = E.simulate(wl, cache, sched, comp)
    assert len(plans) == len(mems) == len(runs)

    n = wl.t_arr.size
    served = np.zeros(n, bool)
    for idx in mems:
        served[idx] = True
    ne = Counter(zip(wl.model.tolist(), wl.epoch.tolist()))

    ev = []                                                     # (시각, 순서, 줄)
    for i in range(n):
        tr, m, k = int(wl.track[i]), int(wl.model[i]), int(wl.epoch[i])
        line = (1 << 254) | (int(wl.t_arr[i]) << 222) | (i << 190) | (tr << 180) | (m << 174) | (int(wl.t_host[i]) << 142) \
            | ((k & 0xFFFF) << 126) | (int(k % 31 == 0) << 125) | (ne[(m, k)] << 109) | (int(not served[i]) << 50)
        ev.append((float(wl.t_arr[i]), 1, len(ev), line))
    for b, (idx, (st, fin)) in enumerate(zip(mems, runs)):
        for j, i in enumerate(idx):
            t0 = st if j == 0 else fin[j - 1]
            common = (i << 190) | (int(wl.track[i]) << 180) | (int(wl.model[i]) << 174) | (b << 93)
            ev.append((float(t0), 2, len(ev), (2 << 254) | (int(t0) << 222) | common | (int(j == 0) << 92)))
            ev.append((float(fin[j]), 0, len(ev), (0 << 254) | (int(fin[j]) << 222) | common))
    ev.sort()
    ev = [(x[0], x[1], x[2], x[3] | (int(k + 1 < len(ev) and ev[k + 1][0] == x[0]) << 49)) for k, x in enumerate(ev)]

    out = ROOT / f"hardware/sim/frontend/t{a.id}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "n.hex").write_text(f"{len(ev):08x}\n{len(mems):08x}\n")
    (out / "ev.hex").write_text("".join(f"{x[3]:064x}\n" for x in ev))
    (out / "batch.hex").write_text("".join(
        f"{(m << 120) | (int(hit) << 119) | (len(idx) << 103) | (qne << 63):032x}\n"
        for (m, hit, qne), idx in zip(plans, mems)))
    sizes = [len(x) for x in mems]
    print(f"t{a.id}: offset {a.offset}, J {a.jitter} ms, {a.scn} seed {a.seed}, {a.warm}+{a.meas} 주기: 추론 요청 {n}, drop {int((~served).sum())}, "
          f"batch {len(mems)}(평균 {np.mean(sizes):.1f}, 최대 {max(sizes)}), miss {sum(not p[1] for p in plans)}, "
          f"계획 때 여러 모델 대기 {sum(bin(p[2]).count('1') > 1 for p in plans)}, 사건 {len(ev)}, simulator 최대 응답 {res['max_ms']:.2f} ms")


if __name__ == "__main__":
    main()
