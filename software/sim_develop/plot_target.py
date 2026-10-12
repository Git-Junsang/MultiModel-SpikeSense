#!/usr/bin/env python3
"""plot_target.py — target_exp.py(P3.8 마무리 실험) 결과 그림

  그림 14  최대 트랙: (가) 시나리오별 최고 설계의 보장값과 묶지 않는 스케줄러, (나) 설계별 전 시나리오 최대 트랙
  그림 15  목표 트랙 N에서 설계 32개의 위반율·평균 처리 시간·오프칩 접근·오프칩 바이트·사이클
  그림 16  스케줄러 비교(그룹핑·점수·점수2·점수3): 지연 대 전송, 시나리오별 전송 (입력 p38s_fixed_n{N}.jsonl)
  그림 17  스케줄러 후보 비교(문헌 기반 후보 포함): 지연 대 전송, 민감도 위반 여부 (입력 p38t·p38t2)
  (그림 14~17은 최종 비교 대상 정리 전 그림이라 --old로만 figures/discarded/에 그린다)
  그림 18  최종 비교: FCFS·EDF·Grouping·Dysta·Timeout·SlackBatch-Lite·SlackBatch × 지표 6개 (입력 p38f_*)
  그림 19  최종 비교 상세: 시나리오별·설계별 전송, 외란 조건별 최대 응답

    python3 software/sim_develop/plot_target.py --n 1024          # 그림 18·19
    python3 software/sim_develop/plot_target.py --n 1024 --old    # 그림 14~17 → figures/discarded/
입력: sim_result/p38_cap.jsonl, p38_verify.jsonl, p38_fixed_n{N}.jsonl → sim_result/figures/fig14_p38_capacity.png, fig15_p38_fixed_n{N}.png
"""
import argparse
import json
import os
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import target_exp as te  # noqa: E402

RES = te.OUT
FIG = os.path.join(RES, 'figures')
FIG_OLD = os.path.join(FIG, 'discarded')      # 그림 14~17(최종 비교 대상 정리 전, --old로만 다시 그림)
plt.rcParams.update({'font.family': 'Pretendard', 'axes.unicode_minus': False, 'font.size': 9,
                     'axes.edgecolor': '#c3c2b7', 'axes.linewidth': 0.8, 'axes.grid': True,
                     'grid.color': '#e6e5e0', 'grid.linewidth': 0.8, 'axes.axisbelow': True,
                     'xtick.color': '#52514e', 'ytick.color': '#52514e', 'axes.labelcolor': '#52514e',
                     'axes.titleweight': 'bold', 'axes.titlesize': 10, 'figure.facecolor': '#fcfcfb',
                     'axes.facecolor': '#fcfcfb'})
INK, MUTED, GRAY = '#0b0b0b', '#52514e', '#b4b2a9'
SERIES = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100']      # 범주 1~4 (검증: 인접 CVD ΔE ≥ 9.1)
SCH = [s.name for s in te.SCH]
STO = [s.name for s in te.STO]
CMP = [c.name for c in te.CMP]


def load(name):
    with open(os.path.join(RES, name)) as f:
        return [json.loads(x) for x in f]


def short(s):
    return s.split('.')[-1]


def bar_labels(ax, bars, fmt):
    for b in bars:
        w = b.get_width()
        ax.text(w, b.get_y() + b.get_height() / 2, ' ' + fmt(w), va='center', ha='left', fontsize=8, color=INK)


# ---- 그림 14 -------------------------------------------------------------------------
def fig14(target):
    cap = load('p38_cap.jsonl')
    ver = load('p38_verify.jsonl')
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(14, 5.2), gridspec_kw=dict(width_ratios=[1, 1.25]),
                                 constrained_layout=True)
    # (가) 시나리오별: 최고 설계 보장값(시드 20 + S·SK 해석 상한) vs 묶지 않는 스케줄러(FCFS·EDF) 최고
    xmax = 2000
    y = np.arange(len(te.SCEN))[::-1]
    best = {r['scenarios']: r for r in ver if r['kind'] == 'scenario'}
    g = [best[s]['guaranteed'] for s in te.SCEN]
    nb = [max(r['capacity'] for r in cap if r['scenario'] == s and r['scheduler'] in ('FCFS', 'EDF')) for s in te.SCEN]
    h = 0.36
    b1 = a1.barh(y + h / 2, np.minimum(g, xmax), h, color=SERIES[0], label='최고 설계 (보장값)')
    b2 = a1.barh(y - h / 2, nb, h, color=GRAY, label='묶지 않는 스케줄러 (FCFS·EDF) 최고')
    for b, v, s in zip(b1, g, te.SCEN):
        r = best[s]
        note = ''
        if r['s_bound'] is not None and v == r['s_bound']:
            note = ' (동시 도착 해석 상한)'
        elif v >= te.stable_cap(s):
            note = ' (가동률 100 % 상한)'
        if v > xmax:
            a1.text(xmax - 20, b.get_y() + b.get_height() / 2,
                    f'{v:,} (축 밖). 큐·메타를 분산 RAM에 두면 {te.lutram_cap():,}트랙에서 분산 RAM이 다 참 ▶',
                    va='center', ha='right', fontsize=8, color='white')
        else:
            a1.text(v, b.get_y() + b.get_height() / 2, f' {v:,}{note}', va='center', ha='left', fontsize=8, color=INK)
    bar_labels(a1, b2, lambda w: f'{w:,.0f}')
    a1.axvline(target, color=INK, lw=1.2)
    a1.text(target, len(te.SCEN) - 0.45, f' 합성 목표 {target:,}', fontsize=8.5, color=INK, va='bottom')
    a1.set_yticks(y, [f'{s}' for s in te.SCEN])
    a1.set_xlim(0, xmax)
    a1.set_ylim(-0.7, len(te.SCEN) - 0.2)
    a1.set_xlabel('마감 위반 0인 최대 트랙 수')
    a1.set_title('(가) 시나리오별 최대 트랙 — 최고 설계 vs 묶지 않는 스케줄러')
    a1.legend(loc='lower right', frameon=False, fontsize=8)
    a1.grid(axis='y', visible=False)

    # (나) 설계별 전 시나리오 최대 트랙: 저장 4 × (묶는 스케줄러 2 × 연산 2)
    allmin = {}
    for r in cap:
        k = (r['storage'], r['scheduler'], r['compute'])
        allmin[k] = min(allmin.get(k, 10 ** 9), r['capacity'])
    combos = [(q, c) for q in ('그룹핑', '점수') for c in CMP]
    x = np.arange(len(STO))
    w = 0.19
    for i, (q, c) in enumerate(combos):
        vals = [allmin[(s, q, c)] for s in STO]
        bars = a2.bar(x + (i - 1.5) * w, vals, w * 0.92, color=SERIES[i], label=f'{q} · {c}')
        for b, v in zip(bars, vals):
            a2.text(b.get_x() + b.get_width() / 2, v + 12, f'{v:,}', ha='center', va='bottom', fontsize=7, color=INK,
                    rotation=90)
    fc = [max(allmin[(s, q, c)] for q in ('FCFS', 'EDF') for c in CMP) for s in STO]
    a2.scatter(x, fc, marker='_', s=900, color=MUTED, linewidths=2, zorder=3, label='FCFS·EDF 최고 (묶지 않음)')
    for xi, v in zip(x, fc):
        a2.text(xi + 0.42, v, f'{v}', va='center', ha='left', fontsize=7.5, color=MUTED)
    a2.axhline(target, color=INK, lw=1.2)
    a2.set_xlim(-0.6, len(STO) - 0.4 + 0.75)
    a2.text(len(STO) - 0.4 + 0.72, target + 8, f'합성 목표\n{target:,}', ha='right', va='bottom', fontsize=8.5, color=INK)
    a2.set_xticks(x, [f'{s}\n(참고)' if s not in te.MAIN else s for s in STO])
    a2.set_ylim(0, 1500)
    a2.set_ylabel('전 시나리오 위반 0인 최대 트랙 수 (1단계, 시드 3)')
    a2.set_title('(나) 설계별 전 시나리오 최대 트랙 — 저장 × 스케줄러 × 연산')
    a2.legend(loc='upper right', ncol=3, frameon=False, fontsize=8, bbox_to_anchor=(1.0, 1.0))
    a2.grid(axis='x', visible=False)
    fig.suptitle(f'XL INT8 · {te.LANES}레인 · 막전위 DDR3 (시뮬레이션, rev {te.REV})', fontsize=10, color=MUTED)
    out = os.path.join(FIG_OLD, 'fig14_p38_capacity.png')
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(out)


# ---- 그림 15 -------------------------------------------------------------------------
def fig15(n):
    rows = load(f'p38_fixed_n{n}.jsonl')
    ix = {(r['storage'], r['scheduler'], r['compute']): r for r in rows}
    groups = [(s, c) for s in STO for c in CMP]
    x = np.arange(len(groups))
    w = 0.2
    te.sc.configure(te.LANES, n, mem=te.MEM, rev=te.REV, arch=te.ARCH)
    cyc_cmp = te.sc.WORDS * te.sc.OVH
    feas = [r for r in rows if r['feasible']]

    def rng(f, cond):
        v = [f(r) for r in feas if cond(r)]
        return f'{min(v):,.0f}~{max(v):,.0f}'
    nob = lambda r: r['scheduler'] in ('FCFS', 'EDF')                       # noqa: E731
    sat = lambda r: r['scheduler'] == '점수' and r['compute'] == '한번에' and r['miss_rate'] > 0.01   # noqa: E731
    panels = [('(가) 위반율 % (시나리오 6 합산)', lambda r: r['miss_rate'] * 100, None, None),
              ('(나) 평균 처리 시간 ms (생성 → 결과 도착)', lambda r: r['mean_ms'], 40,
               f"축 밖: FCFS·EDF {rng(lambda r: r['mean_ms'] / 1000, nob)} s, 점수·한번에 B·C·D {rng(lambda r: r['mean_ms'], sat)} ms"),
              ('(다) 오프칩 접근 횟수 / 요청 (DMA: 가중치 + 막전위 2)', lambda r: r['acc_req'], None, None),
              ('(라) 오프칩 전송 KB / 요청', lambda r: r['kb_req'], None, None),
              ('(마) DMA 사이클 / 요청 (DDR3 데이터 이동)', te.dma_cyc, 4000,
               f"축 밖: FCFS·EDF {rng(te.dma_cyc, nob)}"),
              ('(바) 동시 도착(S) 몰림 처리 사이클 / 요청 (연산 + 정지)', lambda r: r['per']['S']['cyc_req'], 4000,
               f"축 밖: FCFS·EDF {rng(lambda r: r['per']['S']['cyc_req'], nob)}")]
    fig, axes = plt.subplots(3, 2, figsize=(14, 11.5), constrained_layout=True)
    for ax, (title, f, top, note) in zip(axes.ravel(), panels):
        for i, q in enumerate(SCH):
            vals = np.array([f(ix[(s, q, c)]) if ix[(s, q, c)]['feasible'] else np.nan for s, c in groups])
            shown = vals if top is None else np.minimum(vals, top)
            ax.bar(x + (i - 1.5) * w, shown, w * 0.92, color=SERIES[i], label=q)
            if title.startswith('(가)'):                         # 위반 0인 막대는 높이가 없으므로 0을 적는다
                for xi, v in zip(x + (i - 1.5) * w, vals):
                    if v < 3:                                   # 0과 막대가 보이지 않는 작은 값
                        ax.text(xi, 0.8, '0' if v == 0 else f'{v:.2f}', ha='center', va='bottom', fontsize=7,
                                color=MUTED, rotation=0 if v == 0 else 90)
        if top is not None:
            ax.set_ylim(0, top)
        ax.set_title(title + ('' if note is None else f'\n{note}'), loc='left')
        ax.set_xticks(x, [f'{s.split(".")[0]} {short(s)}{"" if s in te.MAIN else " (참고)"}\n{c}' for s, c in groups],
                      fontsize=8)
        ax.axvspan(len(groups) - 2.5, len(groups) - 0.5, color='#f0efec', zorder=0)
        ax.grid(axis='x', visible=False)
        if '처리 시간' in title:
            ax.axhline(32, color=INK, lw=1.2)
            ax.text(-0.45, 32.4, '마감 32 ms', va='bottom', fontsize=8, color=INK)
        if '사이클' in title:
            ax.axhline(cyc_cmp, color=INK, lw=1.2)
            ax.text(-0.45, cyc_cmp + 40, f'요청당 연산 {cyc_cmp:,.0f}', va='bottom', fontsize=8, color=INK)
    h, lab = axes[0, 0].get_legend_handles_labels()
    fig.legend(h, [f'스케줄러 {x}' for x in lab], loc='outside lower center', ncol=4, frameon=False, fontsize=9)
    fig.suptitle(f'목표 {n:,}트랙에서 3축 조합별 지표 — XL INT8 · {te.LANES}레인 · 막전위 DDR3 '
                 f'(시뮬레이션, 시나리오 6 × 시드 {te.SEEDS_VERIFY}개)', fontsize=10, color=MUTED)
    out = os.path.join(FIG_OLD, f'fig15_p38_fixed_n{n}.png')
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(out)


# ---- 그림 16 -------------------------------------------------------------------------
def fig16(n):
    """스케줄러 비교(p38s): (가) 평균 처리 시간 대 오프칩 전송, (나) 시나리오별 오프칩 전송(A · 한 줄씩)"""
    rows = load(f'p38s_fixed_n{n}.jsonl')
    ix = {(r['storage'], r['scheduler'], r['compute']): r for r in rows}
    sch = [('그룹핑', SERIES[0]), ('점수', GRAY), ('점수2', SERIES[1]), ('점수3', SERIES[2])]
    des = [('A.전체캐시', '한번에', 'o'), ('A.전체캐시', '한줄씩', 's'), ('B.부분상주', '한줄씩', '^'),
           ('C.고정혼합', '한줄씩', 'D'), ('D.스트림', '한줄씩', 'v')]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(14, 5.4), gridspec_kw=dict(width_ratios=[1, 1.15]),
                                 constrained_layout=True)
    for q, col in sch:
        for sto, cmp_, mk in des:
            r = ix[(sto, q, cmp_)]
            ok = r['miss_rate'] == 0
            a1.scatter(r['mean_ms'], r['kb_req'], s=70, marker=mk, color=col if ok else 'none',
                       edgecolors=col, linewidths=1.6, zorder=3)
    for q, col in sch:
        a1.scatter([], [], s=70, marker='o', color=col, label=f'스케줄러 {q}')
    for sto, cmp_, mk in des:
        a1.scatter([], [], s=70, marker=mk, color=MUTED, label=f'{sto.split(".")[0]} {short(sto)} · {cmp_}')
    a1.scatter([], [], s=70, marker='o', color='none', edgecolors=MUTED, linewidths=1.6, label='속이 빈 점 = 위반 있음')
    a1.set_xlabel('평균 처리 시간 ms (생성 → 결과 도착)')
    a1.set_ylabel('오프칩 전송 KB / 요청 (가중치 + 막전위)')
    a1.set_ylim(0, 95)
    a1.set_xlim(6, 14)
    a1.set_title('(가) 지연 대 전송 — 점수3은 마감 여유를 써서 전송을 절반으로', loc='left')
    a1.legend(loc='lower left', fontsize=7.5, frameon=False, ncol=2)
    # (나) 시나리오별
    x = np.arange(len(te.SCEN))
    w = 0.2
    for i, (q, col) in enumerate(sch):
        r = ix[('A.전체캐시', q, '한줄씩')]
        a2.bar(x + (i - 1.5) * w, [r['per'][sc_]['kb_req'] for sc_ in te.SCEN], w * 0.92, color=col, label=f'스케줄러 {q}')
    a2.set_xticks(x, te.SCEN)
    a2.set_ylabel('오프칩 전송 KB / 요청')
    a2.set_title('(나) 시나리오별 전송 — A 전체 캐시 · 한 줄씩. 동시 도착(S·SK)은 모두 같음', loc='left')
    a2.legend(loc='upper right', frameon=False, fontsize=8)
    a2.grid(axis='x', visible=False)
    fig.suptitle(f'목표 {n:,}트랙에서 스케줄러 비교 — XL INT8 · {te.LANES}레인 · 막전위 DDR3 '
                 f'(시뮬레이션, 시나리오 6 × 시드 {te.SEEDS_VERIFY}개)', fontsize=10, color=MUTED)
    out = os.path.join(FIG_OLD, f'fig16_p38s_scheduler_n{n}.png')
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(out)


# ---- 그림 17 -------------------------------------------------------------------------
def fig17(n):
    """스케줄러 후보 비교(p38t, p38t2): 설계별 평균 처리 시간 대 오프칩 전송, 민감도 5조건 위반 여부, 시나리오별 전송"""
    rows = load(f'p38t_fixed_n{n}.jsonl') + [r for r in load(f'p38t2_fixed_n{n}.jsonl') if r['scheduler'] != '그룹핑']
    mar = load(f'p38t_margin_n{n}.jsonl') + [r for r in load(f'p38t2_margin_n{n}.jsonl') if r['scheduler'] != '그룹핑']
    bad = {(r['storage'], r['scheduler'], r['compute']) for r in mar if r['miss']}
    ix = {(r['storage'], r['scheduler'], r['compute']): r for r in rows}
    sch = ['그룹핑', 'Dysta식', '점수2', '점수3', '점수3(강건)', '시간제한 묶음 8', '시간제한 묶음 16',
           '지연 그룹핑(간이 가드)', '지연 그룹핑']
    OFF = {'그룹핑': (10, -12, 'left'), 'Dysta식': (34, 6, 'left'), '점수2': (34, 22, 'left'),
           '점수3': (16, -24, 'left'), '점수3(강건)': (-14, -26, 'right'), '시간제한 묶음 8': (9, 0, 'left'),
           '시간제한 묶음 16': (16, 26, 'left'), '지연 그룹핑(간이 가드)': (-14, 26, 'right'), '지연 그룹핑': (9, 0, 'left')}
    fig, axes = plt.subplots(1, 3, figsize=(17, 5.6), gridspec_kw=dict(width_ratios=[1, 1, 1.1]), constrained_layout=True)
    for ax, (sto, cmp_) in zip(axes[:2], (('A.전체캐시', '한번에'), ('D.스트림', '한줄씩'))):
        for q in sch:
            r = ix[(sto, q, cmp_)]
            ok = (sto, q, cmp_) not in bad and r['miss_rate'] == 0
            col = SERIES[0] if q == '그룹핑' else (SERIES[2] if ok else SERIES[1])
            ax.scatter(r['mean_ms'], r['kb_req'], s=80, color=col if ok else 'none', edgecolors=col, linewidths=1.8,
                       zorder=3)
            dx, dy, ha = OFF[q]
            ax.annotate(q, (r['mean_ms'], r['kb_req']), xytext=(dx, dy), textcoords='offset points', fontsize=7.5,
                        color=INK, ha=ha, va='center',
                        arrowprops=dict(arrowstyle='-', color=MUTED, lw=0.6) if abs(dx) + abs(dy) > 20 else None)
        ax.set_xlim(7, 17.5)
        ax.set_ylim(0, 95)
        ax.set_xlabel('평균 처리 시간 ms (생성 → 결과 도착)')
        ax.set_ylabel('오프칩 전송 KB / 요청')
        ax.set_title(f"{'(가)' if sto[0] == 'A' else '(나)'} {sto.split('.')[0]} {short(sto)} · {cmp_}", loc='left')
    for col, lab, fill in ((SERIES[0], '그룹핑(기준)', True), (SERIES[2], '민감도 5조건 모두 위반 0', True),
                           (SERIES[1], '민감도 조건 중 위반 있음(속이 빈 점)', False)):
        axes[0].scatter([], [], s=80, color=col if fill else 'none', edgecolors=col, linewidths=1.8, label=lab)
    axes[0].legend(loc='lower left', frameon=False, fontsize=8)
    x = np.arange(len(te.SCEN))
    w = 0.27
    for i, (q, col) in enumerate((('그룹핑', SERIES[0]), ('지연 그룹핑(간이 가드)', SERIES[3]), ('지연 그룹핑', SERIES[2]))):
        r = ix[('A.전체캐시', q, '한번에')]
        axes[2].bar(x + (i - 1) * w, [r['per'][s_]['kb_req'] for s_ in te.SCEN], w * 0.92, color=col, label=q)
    axes[2].set_xticks(x, te.SCEN)
    axes[2].set_ylabel('오프칩 전송 KB / 요청')
    axes[2].set_title('(다) 시나리오별 전송 — A 전체 캐시 · 한 번에', loc='left')
    axes[2].legend(loc='upper right', frameon=False, fontsize=8)
    axes[2].grid(axis='x', visible=False)
    fig.suptitle(f'목표 {n:,}트랙에서 스케줄러 후보 비교 (시뮬레이션, 시나리오 6 × 시드 {te.SEEDS_VERIFY}개, 모두 기준 조건 위반 0)',
                 fontsize=10, color=MUTED)
    out = os.path.join(FIG_OLD, f'fig17_p38t_scheduler_n{n}.png')
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(out)


# ---- 최종 비교 그림 (MODEL_SIZE_PLAN §5.12) --------------------------------------------------
FINAL = ['FCFS', 'EDF', 'Grouping', 'Dysta', 'Timeout', 'SlackBatch-Lite', 'SlackBatch']
CAT = {'FCFS': '기존', 'EDF': '기존', 'Grouping': '기존', 'Dysta': '선행연구', 'Timeout': '선행연구',
       'SlackBatch-Lite': '제안', 'SlackBatch': '제안'}
# 알고리즘 = 색(두 그림 공통). FCFS·EDF는 회색, 나머지 5색은 검증기 통과 순서(인접 CVD ΔE ≥ 8, 정상 시각 ≥ 15)
COL = {'FCFS': GRAY, 'EDF': GRAY, 'Grouping': '#2a78d6', 'Dysta': '#eb6834', 'Timeout': '#6250d6',
       'SlackBatch-Lite': '#eda100', 'SlackBatch': '#1baf7a'}
MAIN_DES = ('A.전체캐시', '한번에')


def _final():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import fixedn
    rows = load('p38f_fixed_n1024.jsonl')
    ix = {(r['storage'], r['scheduler'], r['compute']): r for r in rows}
    mar = load('p38f_margin_n1024.jsonl')
    worst = {}
    for r in mar:
        k = (r['storage'], r['scheduler'], r['compute'])
        w, m = worst.get(k, (0.0, 0))
        worst[k] = (max(w, r['worst_ms']), m + r['miss'])
    cap = load('p38f_cap.jsonl')
    allmin = {}
    for r in cap:
        k = (r['storage'], r['scheduler'], r['compute'])
        allmin[k] = min(allmin.get(k, 10 ** 9), r['capacity'])
    energy = {}
    for k, r in ix.items():
        w = r['w_kb_req'] * 1024
        energy[k] = sum(fixedn.energy_per_req(w, r['kb_req'] * 1024 - w, te.ARCH)) / 1000      # µJ
    return ix, worst, allmin, energy


def _cat_axis(ax, xs):
    """알고리즘 이름 + 범주 경계(기존 | 선행연구 | 제안) 세로선"""
    ax.set_xticks(xs, [q.replace('-Lite', '-\nLite') for q in FINAL], fontsize=8)
    for xb in (2.5, 4.5):
        ax.axvline(xb, color='#d9d8d2', lw=1.0, zorder=0)
    for t in ax.get_xticklabels():
        if t.get_text() == 'SlackBatch':
            t.set_fontweight('bold')


def fig18(n):
    """최종 비교: 7개 알고리즘 × 지표 6개 (A 전체 캐시 · 한 번에)"""
    ix, worst, allmin, energy = _final()
    xs = np.arange(len(FINAL))
    key = lambda q: (MAIN_DES[0], q, MAIN_DES[1])       # noqa: E731
    panels = [('(가) 마감 위반율 %', lambda q: ix[key(q)]['miss_rate'] * 100, None, '%.0f'),
              ('(나) 평균 처리 시간 ms (생성 → 결과 도착)', lambda q: ix[key(q)]['mean_ms'], 20, '%.1f'),
              ('(다) 최대 응답 ms (외란 5조건 중 최악)', lambda q: worst[key(q)][0], 40, '%.1f'),
              ('(라) 오프칩 전송 KB / 요청', lambda q: ix[key(q)]['kb_req'], 100, '%.0f'),
              ('(마) 요청당 동적 에너지 µJ (추정)', lambda q: energy[key(q)], 16, '%.1f'),
              ('(바) 전 시나리오 최대 트랙 (위반 0, 시드 3)', lambda q: allmin[key(q)], 1500, '%.0f')]
    fig, axes = plt.subplots(2, 3, figsize=(16, 9.2), constrained_layout=True)
    for ax, (title, f, top, fmt) in zip(axes.ravel(), panels):
        vals = [f(q) for q in FINAL]
        shown = [min(v, top) if top else v for v in vals]
        ax.bar(xs, shown, 0.62, color=[COL[q] for q in FINAL])
        ymax = top or max(vals) * 1.15
        ax.set_ylim(0, ymax)
        for x_, v, sv in zip(xs, vals, shown):
            if top and v > top:                         # 축 밖: 막대 안쪽 위에 흰 글씨로 실제 값
                lab = f'{v / 1000:.1f} s' if ('시간' in title or '응답' in title) else (fmt % v)
                ax.text(x_, sv - ymax * 0.02, lab + '\n▲', ha='center', va='top', fontsize=7.5, color='white')
                continue
            if '트랙' in title:
                lab = f'{v:,.0f}'
            elif '위반' in title:
                lab = '0' if v == 0 else (f'{v:.2f}' if v < 1 else f'{v:.0f}')
            else:
                lab = fmt % v
            ax.text(x_, sv + ymax * 0.01, lab, ha='center', va='bottom', fontsize=7.5, color=INK)
        if ('시간' in title or '응답' in title) and ymax > 32:
            ax.axhline(32, color=INK, lw=1.1)
            ax.text(-0.45, 32.3, '마감 32 ms', ha='left', va='bottom', fontsize=7.5, color=INK)
        if '트랙' in title:
            ax.axhline(n, color=INK, lw=1.1)
            ax.text(-0.45, n + 15, f'합성 목표 {n:,}', ha='left', va='bottom', fontsize=7.5, color=INK)
        ax.set_title(title, loc='left')
        ax.grid(axis='x', visible=False)
        _cat_axis(ax, xs)
    fig.suptitle(f'최종 비교 — {n:,}트랙, XL INT8 · {te.LANES}레인 · 막전위 DDR3 · A 전체 캐시 · 한 번에 '
                 f'(시뮬레이션, 시나리오 6 × 시드 {te.SEEDS_VERIFY}개. ▲ = 축 밖)\n'
                 '기존: FCFS · EDF · Grouping   |   선행연구: Dysta · Timeout   |   제안: SlackBatch-Lite · SlackBatch',
                 fontsize=10, color=MUTED)
    out = os.path.join(FIG, f'fig18_final_compare_n{n}.png')
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(out)


def fig19(n):
    """최종 비교 상세: FCFS·EDF를 뺀 5개. 시나리오별·설계별 전송, 외란 조건별 최대 응답"""
    ix, worst, allmin, energy = _final()
    algs = FINAL[2:]
    mar = load('p38f_margin_n1024.jsonl')
    conds = list(dict.fromkeys(r['cond'] for r in mar))
    fig, axes = plt.subplots(1, 3, figsize=(17, 5.4), gridspec_kw=dict(width_ratios=[1.15, 0.85, 1.15]),
                             constrained_layout=True)
    w = 0.16
    x = np.arange(len(te.SCEN))
    for i, q in enumerate(algs):
        r = ix[(MAIN_DES[0], q, MAIN_DES[1])]
        axes[0].bar(x + (i - 2) * w, [r['per'][s_]['kb_req'] for s_ in te.SCEN], w * 0.92, color=COL[q], label=q)
    axes[0].set_xticks(x, te.SCEN)
    axes[0].set_ylabel('오프칩 전송 KB / 요청')
    axes[0].set_title('(가) 시나리오별 전송 — A 전체 캐시 · 한 번에', loc='left')
    axes[0].legend(loc='upper right', frameon=False, fontsize=8)
    des = [('A.전체캐시', '한번에'), ('A.전체캐시', '한줄씩'), ('D.스트림', '한줄씩')]
    x = np.arange(len(des))
    for i, q in enumerate(algs):
        axes[1].bar(x + (i - 2) * w, [ix[(s_, q, c_)]['kb_req'] for s_, c_ in des], w * 0.92, color=COL[q], label=q)
    axes[1].set_xticks(x, [f'{s_.split(".")[0]} {short(s_)}\n{c_}' for s_, c_ in des])
    axes[1].set_ylabel('오프칩 전송 KB / 요청')
    axes[1].set_title('(나) 설계별 전송 (시나리오 6 합산)', loc='left')
    x = np.arange(len(conds))
    for i, q in enumerate(algs):
        vals, bad = [], []
        for cn in conds:
            r = next(r for r in mar if (r['storage'], r['scheduler'], r['compute']) == (MAIN_DES[0], q, MAIN_DES[1])
                     and r['cond'] == cn)
            vals.append(r['worst_ms'])
            bad.append(r['miss'] > 0)
        axes[2].bar(x + (i - 2) * w, vals, w * 0.92, color=COL[q], label=q)
        for xi, v, b in zip(x + (i - 2) * w, vals, bad):
            if b:
                axes[2].text(xi, v + 0.2, '위반', ha='center', va='bottom', fontsize=7, color=INK, rotation=90)
    axes[2].axhline(32, color=INK, lw=1.1)
    axes[2].text(len(conds) - 0.5, 32.1, '마감 32 ms', ha='right', va='bottom', fontsize=7.5, color=INK)
    axes[2].set_ylim(20, 36)
    axes[2].set_xticks(x, [c.replace(' (', '\n(') for c in conds], fontsize=7.5)
    axes[2].set_ylabel('최대 응답 ms')
    axes[2].set_title('(다) 외란 조건별 최대 응답 — A 전체 캐시 · 한 번에', loc='left')
    for ax in axes:
        ax.grid(axis='x', visible=False)
    fig.suptitle(f'최종 비교 상세 — {n:,}트랙 (시뮬레이션, 시나리오 6 × 시드 {te.SEEDS_VERIFY}개. FCFS·EDF는 위반 100 %라 제외)',
                 fontsize=10, color=MUTED)
    out = os.path.join(FIG, f'fig19_final_detail_n{n}.png')
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=1024)
    ap.add_argument('--old', action='store_true', help='최종 정리 전 그림 14~17을 figures/discarded/에 다시 그림')
    a = ap.parse_args()
    os.makedirs(FIG_OLD, exist_ok=True)
    if a.old:
        fig14(a.n)
        for nm, f in (('p38', fig15), ('p38s', fig16), ('p38t2', fig17)):
            if os.path.exists(os.path.join(RES, f'{nm}_fixed_n{a.n}.jsonl')):
                f(a.n)
        return
    fig18(a.n)
    fig19(a.n)


if __name__ == '__main__':
    main()
