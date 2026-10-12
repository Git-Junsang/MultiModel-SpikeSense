#!/usr/bin/env python3
"""plot_max_tracks.py — MODEL_SIZE_PLAN §4 최대 트랙 실험(rev 2) 결과를 고정 변수별 그림으로

  그림 7   전수 결과 히트맵           고정: 레인·막전위(패널마다), 칸 = 저장·연산 × 스케줄러
  그림 8   한 축만 바꾸기             고정: 나머지 두 축 = (레인, 막전위)별 최고 설계
  그림 9   레인 수에 따른 최대 트랙    고정: (레인, 막전위)별 최고 설계, 계산 한계와 비교
  그림 10  트랙 수에 따른 응답        고정: 기준 레인(온칩 최고 레인), 설계 4개 (추가 실행, sim_result/dse2[_tag]_resp_vs_n.jsonl)
  그림 11  BRAM 사용 분해             고정: 기준 레인 · 막전위 온칩 · 온칩 최고 설계의 스케줄러·연산, 저장 4종 각자의 N*
  그림 12  한 축씩 고르기 경로        고정: 기준안 출발, 온칩 상위 두 레인과 기준 레인 DDR3
  그림 13  민감도                    고정: (레인, 막전위)별 최고 설계

입력: sim_result/dse2[_tag]_{capacity,verify,sens}.jsonl (dse.py --rev 2 [--arch … --tag …] [--verify|--sens])
    python3 software/sim_develop/plot_max_tracks.py [--jobs 11] [--rerun]
    python3 software/sim_develop/plot_max_tracks.py --arch 40,768,512,128,2 --tag xl    # 모델 XL(크기만) → fig*_dse2_xl_*.png
"""
import argparse
import itertools
import json
import os
import sys
from multiprocessing import Pool

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dse  # noqa: E402
import sim_core as sc  # noqa: E402

RES = dse.OUT
FIG = os.path.join(RES, 'figures')
plt.rcParams.update({'font.family': 'UnDotum', 'axes.unicode_minus': False, 'font.size': 9})
CFG = dse.REV[2]
LANES = CFG['lanes']
MEMS = dse.MEMS
STO = [s.name for s in dse.STO]
SCH = [s.name for s in CFG['sch']]
CMP = [c.name for c in dse.CMP]
MEMK = {'onchip': '막전위 온칩', 'ddr': '막전위 DDR3'}
LCOL = {32: '#8c8c8c', 64: 'C0', 128: 'C2', 256: 'C3'}
TARGET = 512
TAG = ''        # 결과·그림 파일 접미사 (main에서 정함)
MT = ''         # 그림 제목에 붙일 모델 표시
FOCUS = 64      # 그림 10·11·12의 기준 레인 = 막전위 온칩 최고 설계의 레인 (main에서 정함)


def short(s):
    return s.split('.')[-1] if '.' in s else s


def save(fig, name):
    out = os.path.join(FIG, name.replace('dse2', 'dse2' + TAG, 1))
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(out)


def load_rows():
    rows = dse.load(CFG)
    return rows, {dse.key(r): r['capacity'] for r in rows}


# ---- 그림 7 ----------------------------------------------------------------------
def fig7(rows, cap):
    fig, axes = plt.subplots(2, 4, figsize=(17, 9), constrained_layout=True)
    ylab = [f'{s[0]}·{c}' for s in STO for c in CMP]
    for i, mem in enumerate(MEMS):
        vmax = max(r['capacity'] for r in rows if r['mem'] == mem)
        for j, L in enumerate(LANES):
            ax = axes[i, j]
            M = np.array([[cap[(L, mem, s, q, c)] for q in SCH] for s in STO for c in CMP])
            im = ax.imshow(M, cmap='viridis', vmin=0, vmax=vmax, aspect='auto')
            best = M.max()
            for (y, x), v in np.ndenumerate(M):
                ax.text(x, y, f'{v:,}', ha='center', va='center', fontsize=8,
                        color='white' if v < 0.6 * vmax else 'black', fontweight='bold' if v == best else None)
                if v == best:
                    ax.add_patch(Rectangle((x - 0.5, y - 0.5), 1, 1, fill=False, ec='red', lw=2))
            ax.set_xticks(range(len(SCH)), SCH)
            ax.set_yticks(range(len(ylab)), ylab)
            ax.set_title(f'{L}레인 · {MEMK[mem]}  (최고 {best:,})')
        fig.colorbar(im, ax=axes[i, :], shrink=0.9, label='최대 트랙 수 (위반 0)')
    fig.suptitle('그림 7. 전수 탐색 결과 — 고정: 레인·막전위 위치(패널), 칸 = 저장·연산 방식(행) × 스케줄러(열). '
                 '빨간 칸 = 패널 최고. 시나리오 U·K·S·I·SK·R × 시드 3, 16트랙 단위 (A 전체 캐시, B L1 상주, C 혼합, D 스트림)' + MT,
                 fontsize=10)
    save(fig, 'fig7_dse2_heatmap.png')


# ---- 그림 8 ----------------------------------------------------------------------
def fig8(rows, cap):
    best = {(r['lanes'], r['mem']): r for r in dse.best_per_group(rows)}
    axes_def = [('스케줄러', 1, SCH), ('저장', 0, STO), ('연산 방식', 2, CMP)]
    fig, axes = plt.subplots(2, 3, figsize=(15, 8.5), gridspec_kw={'width_ratios': [4, 4, 2.4]})
    for i, mem in enumerate(MEMS):
        for j, (axname, ax_i, vals) in enumerate(axes_def):
            ax = axes[i, j]
            x = np.arange(len(vals))
            w = 0.8 / len(LANES)
            for k, L in enumerate(LANES):
                b = best[(L, mem)]
                fixed = [b['storage'], b['scheduler'], b['compute']]
                ys = []
                for v in vals:
                    t = list(fixed)
                    t[ax_i] = v
                    ys.append(cap[(L, mem, *t)])
                bars = ax.bar(x + (k - (len(LANES) - 1) / 2) * w, ys, w, color=LCOL[L],
                              label=f'{L}레인 (최고 {short(fixed[0])}·{fixed[1]}·{fixed[2]})')
                for bx, by in zip(bars, ys):
                    ax.text(bx.get_x() + bx.get_width() / 2, by, f'{by:,}', ha='center', va='bottom',
                            fontsize=6, rotation=90)
            ax.axhline(TARGET, color='black', ls=':', lw=1)
            ax.set_xticks(x, [short(v) if ax_i == 0 else v for v in vals])
            ax.set_title(f'{MEMK[mem]} — {axname}만 바꿈')
            ax.grid(axis='y', alpha=0.3)
            ax.set_ylim(0, max(r['capacity'] for r in rows if r['mem'] == mem) * 1.18)
            if j == 0:
                ax.set_ylabel('최대 트랙 수 (위반 0)')
            if j == 2:
                ax.legend(fontsize=7, loc='upper left', bbox_to_anchor=(1.02, 1.0))
    fig.suptitle('그림 8. 한 축만 바꿨을 때 — 고정: 나머지 두 축은 (레인, 막전위)별 최고 설계(범례)의 값 그대로. 점선 = 현재 목표 512' + MT,
                 fontsize=10)
    fig.tight_layout()
    save(fig, 'fig8_dse2_one_axis.png')


# ---- 그림 9 ----------------------------------------------------------------------
def bram_limit(L):
    """막전위 온칩에서 BRAM에 들어가는 최대 트랙 수(D 스트림, 두 연산 방식 중 큰 값). 계산값"""
    out = 0
    for ci in range(len(dse.CMP)):
        n = 0
        while dse.build((L, 'onchip', 3, 2, ci), n + 16, CFG)[4]:
            n += 16
        out = max(out, n)
    return out


def verify_summary():
    v = [json.loads(x) for x in open(os.path.join(RES, f"{CFG['prefix']}_verify.jsonl"))]
    out = {}
    for r in v:
        g = (r['lanes'], r['mem'])
        if r['ok']:
            out.setdefault(g, dict(pass_n=0, worst=None, s_bound=None))
            if r['n'] > out[g]['pass_n']:
                out[g].update(pass_n=r['n'], worst=r['worst_ms'])
        if r['s_bound'] not in ('–', None):
            out.setdefault(g, dict(pass_n=0, worst=None, s_bound=None))['s_bound'] = int(str(r['s_bound']).replace(',', ''))
    for g, o in out.items():
        o['guar'] = min(o['pass_n'], o['s_bound']) if o['s_bound'] else o['pass_n']
    return out


def fig9(rows, cap):
    vs = verify_summary()
    comp, bram = [], []
    for L in LANES:
        sc.configure(L, 512, arch=CFG.get('arch', sc.ARCH_L))
        comp.append(int(sc.P / sc.C_REQ))
        noreuse = int(sc.P / (sc.T0 + sc.MODEL_B / sc.BW))
        bram.append(bram_limit(L))
    on = [vs[(L, 'onchip')]['guar'] for L in LANES]
    dd = [vs[(L, 'ddr')]['guar'] for L in LANES]
    fig, ax = plt.subplots(figsize=(9, 5.5))
    x = np.arange(len(LANES))
    ax.plot(x, comp, 'r--', marker='o', mfc='none', label='연산 한계 (계산) = 32 ms ÷ 요청당 연산')
    ax.plot(x, bram, color='#7b3294', ls='--', marker='s', mfc='none', label='막전위 온칩 BRAM 한계 (계산, D 스트림)')
    ax.axhline(noreuse, color='#9e9e9e', ls='-.', lw=1)
    ax.text(1.5, noreuse, f'묶지 않을 때 DDR3 한계 {noreuse}', va='top', ha='center', fontsize=8, color='#555')
    ax.axhline(TARGET, color='black', ls=':', lw=1)
    ax.text(1.5, TARGET, '현재 목표 512', va='top', ha='center', fontsize=8)
    ax.plot(x, dd, color='C1', marker='o', lw=2, label='막전위 DDR3 최고 설계 (보장값)')
    ax.plot(x, on, color='C0', marker='o', lw=2, label='막전위 온칩 최고 설계 (시드 20 통과)')
    for xi, a, b, cl in zip(x, on, dd, comp):
        ax.annotate(f'{a:,}', (xi, a), textcoords='offset points', xytext=(10, 6), ha='left', color='C0', fontsize=9)
        if xi:
            ax.annotate(f'{b:,}', (xi, b), textcoords='offset points', xytext=(10, -12), ha='left', color='C1', fontsize=9)
        ax.annotate(f'{cl:,}', (xi, cl), textcoords='offset points', xytext=(-10, 4), ha='right', color='red', fontsize=8)
    ax.set_xticks(x, [f'{L}레인' for L in LANES])
    ax.set_xlim(-0.3, len(LANES) - 0.6)
    ax.set_ylabel('최대 트랙 수 (위반 0)')
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc='upper left')
    ax.set_title('그림 9. 레인 수에 따른 최대 트랙 — 고정: (레인, 막전위)별 최고 설계' + MT, fontsize=10)
    fig.tight_layout()
    save(fig, 'fig9_dse2_lanes.png')


# ---- 그림 10 ---------------------------------------------------------------------
F10_SEEDS = 5


def f10_designs(rows):
    """기준 레인의 기준안·캐시+묶음·온칩 최고·DDR3 최고. 온칩 최고는 굵은 반투명 선(다른 선과 겹칠 수 있음)"""
    best = {(r['lanes'], r['mem']): r for r in dse.best_per_group(rows)}
    lab = lambda r: f"{short(r['storage'])}·{r['scheduler']}·{r['compute']}"
    on, dd = best[(FOCUS, 'onchip')], best[(FOCUS, 'ddr')]
    return [((FOCUS, 'onchip', 0, 0, 0), '온칩 · A·FCFS·한번에 (기준안)', '#9e9e9e', 1.5),
            ((FOCUS, 'onchip', 0, 2, 1), '온칩 · A·그룹핑·한줄씩 (캐시 + 묶음)', 'C2', 1.5),
            (dse.index(on, CFG), f'온칩 · {lab(on)} (최고, 굵은 선)', 'C0', 6),
            (dse.index(dd, CFG), f'DDR3 · {lab(dd)} (최고)', 'C1', 1.5)]


def f10_range():
    sc.configure(FOCUS, 512, arch=CFG.get('arch', sc.ARCH_L))
    top = int(sc.P / sc.C_REQ * 1.03) // 16 * 16 + 16
    return list(range(max(16, top // 6 // 16 * 16), top + 1, 16))


def resp_one(job):
    d, n = job
    st, q, c, t, ok = dse.build(d, n, CFG)
    if not ok:
        return dict(design=list(d), n=n, ok=False)
    worst, miss, tot = 0.0, 0, 0
    for scn in CFG['scen']:
        for seed in range(F10_SEEDS):
            r = sc.simulate(dse.workload(n, seed, scn, CFG), st, q, c)
            worst = max(worst, r['max_ms'])
            miss += r['miss']
            tot += r['n_req']
    return dict(design=list(d), n=n, ok=True, worst_ms=worst, miss_rate=miss / tot)


def fig10(rows, jobs, rerun):
    F10, F10_N = f10_designs(rows), f10_range()
    path = os.path.join(RES, f"{CFG['prefix']}_resp_vs_n.jsonl")
    if rerun or not os.path.exists(path):
        todo = [(d, n) for d, _, _, _ in F10 for n in F10_N]
        with Pool(jobs) as p:
            res = p.map(resp_one, todo, chunksize=1)
        with open(path, 'w') as f:
            for r in res:
                f.write(json.dumps(r) + '\n')
    res = [json.loads(x) for x in open(path)]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(14, 5.2))
    for d, lab, col, lw in F10:
        pts = [r for r in res if tuple(r['design']) == d]
        ok = [r for r in pts if r['ok']]
        n = [r['n'] for r in ok]
        kw = dict(color=col, label=lab, lw=lw, alpha=0.45 if lw > 2 else 1.0, marker=None if lw > 2 else '.')
        a1.plot(n, [min(r['worst_ms'], 45) for r in ok], **kw)
        a2.plot(n, [max(r['miss_rate'] * 100, 1e-3) for r in ok], **kw)
        bad = [r['n'] for r in pts if not r['ok']]
        if bad and ok:
            edge = max(n)
            a1.axvline(edge, color=col, ls=':', lw=1)
            a1.text(edge, 38, f' BRAM 끝 {edge}', color=col, fontsize=7, rotation=90, va='top')
    a1.axhline(32, color='red', ls='--', lw=1)
    a1.text(F10_N[0], 32.3, '마감 32 ms', color='red', fontsize=8)
    a1.set_ylim(0, 46)
    a1.set_ylabel('최대 응답 ms (45 이상은 45로 표시)')
    a1.set_title('최대 응답 (생성 → 결과가 호스트에 도착)')
    a2.set_yscale('log')
    a2.set_ylim(5e-4, 150)
    a2.set_yticks([1e-3, 1e-2, 1e-1, 1, 10, 100], ['0', '0.01', '0.1', '1', '10', '100'])
    a2.set_ylabel('마감 위반율 % (0은 맨 아래)')
    a2.set_title('마감 위반율')
    for a in (a1, a2):
        a.axvline(TARGET, color='black', ls=':', lw=1)
        a.set_xlabel('트랙 수')
        a.grid(alpha=0.3)
    a1.legend(fontsize=8, loc='upper left')
    fig.suptitle(f'그림 10. 트랙 수에 따른 응답 — 고정: {FOCUS}레인, 설계 4개. 시나리오 U·K·S·I·SK·R × 시드 {F10_SEEDS} 중 최악. '
                 '선이 끊긴 곳 = BRAM 배치 불가' + MT, fontsize=10)
    fig.tight_layout()
    save(fig, 'fig10_dse2_resp_vs_n.png')


# ---- 그림 11 ---------------------------------------------------------------------
def fig11(rows, cap):
    on = next(r for r in dse.best_per_group(rows) if (r['lanes'], r['mem']) == (FOCUS, 'onchip'))
    L, _, _, qi, ci = dse.index(on, CFG)
    parts = []
    for si, s in enumerate(STO):
        n = cap[(L, 'onchip', s, SCH[qi], CMP[ci])]
        st, q, c, t, ok = dse.build((L, 'onchip', si, qi, ci), max(n, 16), CFG)
        w, buf = st.tiles(), c.extra_tiles(st)
        parts.append((s, n, sc.XDMA_T, sc.MEM_T, w, buf, 365 - sc.XDMA_T - sc.MEM_T - w - buf,
                      getattr(st, 'E', None), getattr(st, 'R', None)))
    fig, ax = plt.subplots(figsize=(11, 4.6))
    cols = ['#bdbdbd', 'C0', 'C3', 'C1', '#f0f0f0']
    labs = ['XDMA', '막전위 (트랙 수에 비례)', '가중치 보관 (엔트리·L1 상주)', '적재·묶음 버퍼', '남음']
    for y, (s, n, *v, E, R) in enumerate(parts):
        left = 0
        for k, (val, col) in enumerate(zip(v, cols)):
            ax.barh(y, val, left=left, color=col, ec='white', label=labs[k] if y == 0 else None)
            if val >= 12:
                ax.text(left + val / 2, y, f'{val:g}', ha='center', va='center', fontsize=8)
            left += val
        extra = f', 엔트리 {E}벌' if E else ''
        extra += f', L1 상주 {R}모델' if R else ''
        ax.text(367, y, (f'N* = {n:,}{extra}' if n else f'N* = 0 (16트랙도 초과, 막대는 16트랙 기준){extra}'),
                va='center', fontsize=9)
    ax.set_yticks(range(len(parts)), [p[0] for p in parts])
    ax.invert_yaxis()
    ax.set_xlim(0, 560)
    ax.axvline(365, color='black', lw=1)
    ax.set_xlabel('BRAM 타일 (XC7A200T 365)')
    ax.legend(fontsize=8, ncol=5, loc='upper center', bbox_to_anchor=(0.42, -0.16))
    ax.set_title(f'그림 11. 저장 방식별 BRAM 사용 — 고정: {L}레인 · 막전위 온칩 · {SCH[qi]} · {CMP[ci]}, 각 저장 방식의 N*에서'
                 + ('\n' + MT.strip() if MT else ''), fontsize=10)
    fig.tight_layout()
    save(fig, 'fig11_dse2_bram.png')


# ---- 그림 12 ---------------------------------------------------------------------
def fig12(rows, cap):
    on = sorted((r for r in dse.best_per_group(rows) if r['mem'] == 'onchip'), key=lambda r: -r['capacity'])
    panels = [(on[0]['lanes'], 'onchip'), (on[1]['lanes'], 'onchip'), (FOCUS, 'ddr')]
    axn = {0: '저장', 1: '스케줄러', 2: '연산'}
    fig, axes = plt.subplots(1, 3, figsize=(16, 6.6), sharey=False)
    for ax, (L, m) in zip(axes, panels):
        base = ['A.전체캐시', 'FCFS', '한번에']
        opt = max(cap[(L, m, a, b, c)] for a in STO for b in SCH for c in CMP)
        for oi, order in enumerate(itertools.permutations((1, 0, 2))):
            k = list(base)
            ys = [cap[(L, m, *k)]]
            for a in order:
                cur = cap[(L, m, *k)]
                for v in (STO, SCH, CMP)[a]:
                    t = list(k)
                    t[a] = v
                    if cap[(L, m, *t)] > cur:
                        k, cur = t, cap[(L, m, *t)]
                ys.append(cur)
            lab = ' → '.join(axn[a] for a in order) + f'  ⇒ {short(k[0])}·{k[1]}·{k[2]} {ys[-1]:,}'
            ax.plot(np.arange(4) + (oi - 2.5) * 0.04, ys, marker='o', label=lab)
        ax.axhline(opt, color='red', ls='--', lw=1.2)
        ax.text(3, opt, f'전수 최적 {opt:,}', color='red', ha='right', va='bottom', fontsize=8)
        ax.set_xticks(range(4), ['기준안\nA·FCFS·한번에', '1번째 축', '2번째 축', '3번째 축'])
        ax.set_title(f'{L}레인 · {MEMK[m]}')
        ax.set_ylabel('최대 트랙 수 (위반 0)')
        ax.grid(alpha=0.3)
        ax.legend(fontsize=7, loc='upper center', bbox_to_anchor=(0.5, -0.14))
    fig.suptitle('그림 12. 한 축씩 차례로 고르기 — 고정: 기준안에서 출발, 나머지 두 축을 고정한 채 한 축을 최선으로 바꿈(6가지 순서). '
                 '겹치는 선은 가로로 조금 띄워 그림(값은 그대로)' + MT, fontsize=10)
    fig.tight_layout()
    save(fig, 'fig12_dse2_greedy.png')


# ---- 그림 13 ---------------------------------------------------------------------
def fig13(rows, cap):
    sens = [json.loads(x) for x in open(os.path.join(RES, f"{CFG['prefix']}_sens.jsonl"))]
    best = dse.best_per_group(rows)
    conds = [s for s, _ in dse.SENS]
    fig, ax = plt.subplots(figsize=(13, 5.6))
    x = np.arange(len(best))
    w = 0.8 / len(conds)
    lo = 0.0
    for k, cnd in enumerate(conds):
        ys = []
        for b in best:
            v = next(r for r in sens if r['cond'] == cnd and dse.key(r) == dse.key(b))
            ys.append((v['capacity'] / b['capacity'] - 1) * 100)
        lo = min(lo, min(ys))
        bars = ax.bar(x + (k - (len(conds) - 1) / 2) * w, ys, w, label=cnd)
        for bx, by in zip(bars, ys):
            ax.text(bx.get_x() + bx.get_width() / 2, by + (0.15 if by >= 0 else -0.15), f'{by:+.1f}',
                    ha='center', va='bottom' if by >= 0 else 'top', fontsize=6.5)
    ax.axhline(0, color='black', lw=0.8)
    ax.set_xticks(x, [f"{b['lanes']}레인 {MEMK[b['mem']][4:]}\n{short(b['storage'])}·{b['scheduler']}·{b['compute']}\n"
                      f"기준 {b['capacity']:,}" for b in best], fontsize=8)
    ax.set_ylabel('최대 트랙 수 변화 % (기준 = W_h 1 ms, DDR3 3.015 GB/s)')
    ax.grid(axis='y', alpha=0.3)
    ax.set_ylim(min(-7, lo - 1.5), 3.2)
    ax.legend(fontsize=8, ncol=5, loc='upper center', bbox_to_anchor=(0.5, -0.2))
    ax.set_title('그림 13. 조건을 바꿨을 때 — 고정: (레인, 막전위)별 최고 설계 (1단계와 같은 시드 3)' + MT, fontsize=10)
    fig.tight_layout()
    save(fig, 'fig13_dse2_sens.png')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', type=int, default=11)
    ap.add_argument('--rerun', action='store_true', help='그림 10의 시뮬레이션을 다시 실행')
    ap.add_argument('--arch', help='dse.py --arch와 같은 값')
    ap.add_argument('--tag', help='dse.py --tag와 같은 값')
    a = ap.parse_args()
    global CFG, TAG, MT, FOCUS
    CFG = dict(CFG)
    if a.arch:
        CFG['arch'] = tuple(int(x) for x in a.arch.split(','))
        MT = f"  [모델 {'→'.join(a.arch.split(','))}, 크기만·더미 가중치]"
    if a.tag:
        TAG = '_' + a.tag
        CFG['prefix'] += TAG
    os.makedirs(FIG, exist_ok=True)
    rows, cap = load_rows()
    FOCUS = max((r for r in rows if r['mem'] == 'onchip'), key=lambda r: r['capacity'])['lanes']
    fig7(rows, cap)
    fig8(rows, cap)
    fig9(rows, cap)
    fig10(rows, a.jobs, a.rerun)
    fig11(rows, cap)
    fig12(rows, cap)
    fig13(rows, cap)


if __name__ == '__main__':
    main()
