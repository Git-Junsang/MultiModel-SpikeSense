"""P4.3: engine.PNURTL 실행 하나의 도착·교체 기록을 tb_weight_cache.sv가 읽는 hex로 낸다.

환경 파일 p43_pnu_rtl에서 cache_policy = pnu_rtl인 점 하나를 시나리오·seed 하나로 돌린다.
출력 hardware/sim/weight_cache/t<번호>/
  n.hex     줄 1 = 설정 수, 줄 2 = 사건 수
  cfg.hex   설정 쓰기. 줄마다 {addr 16 bit, data 16 bit} (next_use_predictor.v 주소)
  ev.hex    사건. 줄마다 144 bit {kind 4, now 32, model 8, t_host 32, n_expect 16, exp 4, victim 8, q_ne 40}
            kind 1 = 도착, 2 = 교체 계획. exp 0 = hit, 1 = 빈 entry에 적재, 2 = 내보내고 적재

프로젝트 루트에서:
  python3 hardware/testbench/export_pnu_trace.py --id 0 --entries 4 --jitter 3.2 --scn U --seed 0
"""

import argparse
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "simulation" / "engine"))
import engine as E  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", type=int, required=True)
    ap.add_argument("--entries", type=int, default=4)
    ap.add_argument("--jitter", type=float, default=3.2)
    ap.add_argument("--scn", default="U")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    env = E.load(str(ROOT / "simulation/environment/p43_pnu_rtl.toml"))
    e = next(e for _, e in E.points(env)
             if e["cache_policy"] == "pnu_rtl" and e["cache_entries"] == a.entries and e["host_jitter_ms"] == a.jitter)
    s = E.Setup(e)
    st, q, c, models = s.cache, s.scheduler, s.compute, s.hw.models
    wl = s.workload(a.scn, a.seed)
    ev, cfg = [], []
    plan0 = st.plan

    def plan(m, queue, now):
        st.log = []
        before = list(st.loaded)
        r = plan0(m, queue, now)
        for ta, g, th, ne in st.log:
            ev.append((1, ta, int(st.group_model[g]), th, ne, 0, 0, 0))
        after = list(st.loaded)
        if m in before:
            kind, vic = 0, 0
        elif len(before) < st.entries:
            kind, vic = 1, 0
        else:
            kind, vic = 2, (set(before) - set(after)).pop()
        qne = sum(1 << x for x in range(models) if st.queue.by_model[x])
        ev.append((2, int(math.floor(st.now)), m, 0, 0, kind, vic, qne))
        return r

    st.plan = plan
    E.simulate(wl, st, q, c)

    # Host가 시작할 때 쓰는 설정: 모델별 offset 번호·등록 트랙 수, 표
    off = {int(m): int(o) // 800 for m, o in zip(st.group_model, st.offset_us)}
    reg = {int(m): int(n) for m, n in zip(st.group_model, st.group_tracks)}
    assert all(int(o) % 800 == 0 for o in st.offset_us) and len(off) == len(st.group_model), "모델마다 offset 하나여야 한다"
    for m in range(models):
        cfg += [(0x000 + m, off.get(m, 0)), (0x040 + m, reg.get(m, 0))]
    tb = st.tables
    cfg += [(0x080, tb["tau_g"]), (0x081, tb["tau_u"]), (0x082, tb["eg"])]
    cfg += [(0x100 + i, v) for i, v in enumerate(tb["lut_g"])]
    cfg += [(0x400 + (i << 3) + rb, v) for i, row in enumerate(tb["lut_u"]) for rb, v in enumerate(row)]
    assert all(0 <= v < 1 << 16 for _, v in cfg)

    out = ROOT / f"hardware/sim/weight_cache/t{a.id}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "n.hex").write_text(f"{len(cfg):08x}\n{len(ev):08x}\n")
    (out / "cfg.hex").write_text("".join(f"{ad:04x}{v:04x}\n" for ad, v in cfg))
    (out / "ev.hex").write_text("".join(
        f"{k:01x}{now & 0xFFFFFFFF:08x}{m:02x}{th & 0xFFFFFFFF:08x}{ne:04x}{x:01x}{vic:02x}{qne:010x}\n"
        for k, now, m, th, ne, x, vic, qne in ev))
    kinds = [x[5] for x in ev if x[0] == 2]
    print(f"t{a.id}: entry {a.entries}, J {a.jitter} ms, {a.scn} seed {a.seed}: 도착 {sum(x[0] == 1 for x in ev)}, "
          f"계획 {len(kinds)} (hit {kinds.count(0)}, 빈 entry {kinds.count(1)}, 내보냄 {kinds.count(2)}), "
          f"끝 시각 {ev[-1][1] / 1e6:.2f} s")


if __name__ == "__main__":
    main()
