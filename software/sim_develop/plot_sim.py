#!/usr/bin/env python3
"""plot_sim.py — 대역폭 단계 실행 결과(sweep_*.jsonl) → 그림 4장

    python3 software/sim_develop/plot_sim.py

입력: sim_result/sweep_n512_{uniform,zipf}.jsonl (기준: 32레인·512트랙, 막전위 온칩)
      sim_result/sweep_n1024_l64_{uniform,zipf}.jsonl (확장: 64레인·1,024트랙, 막전위 DDR3)
출력: sim_result/figures/fig{1..4}_*.png
"""
import collections
import json
import os
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sim_core  # noqa: E402

RES = os.path.join(os.path.dirname(HERE), 'sim_result')
FIG = os.path.join(RES, 'figures')
plt.rcParams.update({'font.family': 'UnDotum', 'axes.unicode_minus': False, 'font.size': 9,
                     'axes.titlesize': 10, 'legend.fontsize': 8})

ENVS = [('n512', 32, 512, '기준: 32레인 · 512트랙'), ('n1024_l64', 64, 1024, '확장: 64레인 · 1,024트랙')]
STO = ['A.전체캐시', 'B.L1상주', 'C.혼합']
SCH = ['FCFS', 'EDF', '그룹핑', '점수']
CMP = ['한번에', '한줄씩']
MEAS = 3.015


def load(tag, dist):
    """(저장, 스케줄러, 연산, bw) → 시드 합산 지표"""
    g = collections.defaultdict(list)
    for line in open(os.path.join(RES, f'sweep_{tag}_{dist}.jsonl')):
        r = json.loads(line)
        g[(r['storage'], r['scheduler'], r['compute'], r['bw'])].append(r)
    out = {}
    for k, rs in g.items():
        out[k] = dict(miss=sum(r['miss'] for r in rs) / sum(r['n_req'] for r in rs),
                      p99=np.mean([r['p99_ms'] for r in rs]), worst=max(r['max_ms'] for r in rs),
                      mbps=np.mean([r['mbps'] for r in rs]), tiles=rs[0]['tiles'],
                      skipped=rs[0].get('skipped', False))
    bws = sorted({k[3] for k in out}, reverse=True)
    return out, bws


def min_pass(d, bws, key):
    low = None
    for b in bws:
        if d[(*key, b)]['miss'] > 0:
            break
        low = b
    return low


def budget(lanes, tracks):
    sim_core.configure(lanes, tracks)
    return sim_core.TILE_BUDGET


def fig1(data):
    """스케줄러별 위반율 vs 대역폭 (A 전체 캐시 · 한 줄씩, 균등)"""
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.4), sharey=True)
    for ax, (tag, _, _, title) in zip(axes, ENVS):
        d, bws = data[(tag, 'uniform')]
        for q, mk in zip(SCH, 'osD^'):
            ax.plot(bws, [d[('A.전체캐시', q, '한줄씩', b)]['miss'] * 100 for b in bws], marker=mk, label=q)
        ax.axvline(MEAS, color='gray', ls=':', lw=1)
        ax.text(MEAS, 50, ' 실측', color='gray', fontsize=8)
        ax.set_xscale('log')
        ax.invert_xaxis()
        ax.set_xticks(bws)
        ax.set_xticklabels([f'{b:g}' for b in bws], rotation=45)
        ax.minorticks_off()
        ax.set_xlabel('DDR3 대역폭 (GB/s, 오른쪽으로 갈수록 느림)')
        ax.set_title(title)
        ax.grid(alpha=0.3)
    axes[0].set_ylabel('마감 위반율 (%)')
    axes[0].legend(title='스케줄러')
    fig.suptitle('그림 1. 스케줄러별 마감 위반율 (저장 A 전체 캐시, 연산 한 줄씩, 모델 균등)', fontsize=10)
    fig.tight_layout()
    return fig


def fig2(data):
    """조합별 최저 통과 대역폭 히트맵 (환경 × 분포)"""
    fig, axes = plt.subplots(2, 2, figsize=(10, 6.4))
    rows = [(s, c) for s in STO for c in CMP]
    for i, (tag, lanes, tracks, title) in enumerate(ENVS):
        bud = budget(lanes, tracks)
        for j, dist in enumerate(['uniform', 'zipf']):
            ax = axes[i, j]
            d, bws = data[(tag, dist)]
            val = np.full((len(rows), len(SCH)), np.nan)
            for r, (s, c) in enumerate(rows):
                for q_i, q in enumerate(SCH):
                    low = min_pass(d, bws, (s, q, c))
                    val[r, q_i] = np.log10(low) if low else np.log10(5)
            ax.imshow(val, cmap='RdYlGn_r', vmin=np.log10(0.1), vmax=np.log10(5), aspect='auto')
            for r, (s, c) in enumerate(rows):
                over = d[(s, SCH[0], c, bws[0])]['tiles'] > bud
                for q_i, q in enumerate(SCH):
                    low = min_pass(d, bws, (s, q, c))
                    txt = '실패' if low is None else f'{low:g}'
                    ax.text(q_i, r, txt + ('\n(BRAM 초과)' if over else ''), ha='center', va='center',
                            fontsize=7.5 if over else 9, color='black')
            ax.set_xticks(range(len(SCH)))
            ax.set_xticklabels(SCH)
            ax.set_yticks(range(len(rows)))
            ax.set_yticklabels([f'{s} · {c}' for s, c in rows], fontsize=8)
            ax.set_title(f'{title} · 모델 {"균등" if dist == "uniform" else "편중"}')
    fig.suptitle('그림 2. 마감 위반 0을 유지하는 최저 DDR3 대역폭 (GB/s, 낮을수록 좋음. 실측 3.015)', fontsize=10)
    fig.tight_layout()
    return fig


def fig3(data):
    """저장 정책별 p99 응답 vs 대역폭 (한 줄씩, 균등). 위반이 생긴 점은 그리지 않음"""
    fig, axes = plt.subplots(2, 2, figsize=(9, 6), sharey=True)
    for i, (tag, _, _, title) in enumerate(ENVS):
        d, bws = data[(tag, 'uniform')]
        for j, q in enumerate(['그룹핑', '점수']):
            ax = axes[i, j]
            for s, mk in zip(STO, 'osD'):
                xs = [b for b in bws if d[(s, q, '한줄씩', b)]['miss'] == 0]
                ax.plot(xs, [d[(s, q, '한줄씩', b)]['p99'] for b in xs], marker=mk, label=s)
            ax.axhline(32, color='red', ls='--', lw=1)
            ax.text(bws[0], 32.5, '마감 32 ms', color='red', fontsize=8)
            ax.set_xscale('log')
            ax.invert_xaxis()
            ax.set_xticks(bws)
            ax.set_xticklabels([f'{b:g}' for b in bws], rotation=45, fontsize=7)
            ax.minorticks_off()
            ax.set_ylim(0, 36)
            ax.set_title(f'{title} · {q}')
            ax.grid(alpha=0.3)
            if j == 0:
                ax.set_ylabel('응답 시간 p99 (ms)')
            if i == 1:
                ax.set_xlabel('DDR3 대역폭 (GB/s)')
    axes[0, 0].legend(title='저장 정책')
    fig.suptitle('그림 3. 저장 정책별 응답 시간 p99 (연산 한 줄씩, 모델 균등, 위반이 생긴 대역폭은 생략)', fontsize=10)
    fig.tight_layout()
    return fig


def fig4(data):
    """실측 대역폭에서 요청당 가중치 전송량 (확장 환경, 그룹핑·점수)"""
    fig, axes = plt.subplots(1, 2, figsize=(9.5, 3.6), sharey=True)
    tag, lanes, tracks, title = ENVS[1]
    rate = tracks / 32.0                                    # 요청/ms
    full = sim_core.MODEL_B / 1024
    for ax, dist in zip(axes, ['uniform', 'zipf']):
        d, bws = data[(tag, dist)]
        labels, vals, colors = [], [], []
        for q in ['그룹핑', '점수']:
            for c in CMP:
                for s, col in zip(STO, ['C0', 'C1', 'C2']):
                    r = d[(s, q, c, MEAS)]
                    labels.append(f'{q}\n{c}')
                    vals.append(r['mbps'] * 1e3 / rate / 1024 if r['miss'] == 0 else np.nan)
                    colors.append(col)
        x = np.arange(len(vals)) + np.repeat(np.arange(4), 3) * 0.6
        ax.bar(x, vals, color=colors, width=0.9)
        ax.axhline(full, color='gray', ls=':', lw=1)
        ax.text(x[-1], full + 1, '모델 전체 128.5 KB', ha='right', fontsize=7, color='gray')
        ax.set_ylim(0, 150)
        ax.set_xticks(x[1::3])
        ax.set_xticklabels(labels[1::3], fontsize=8)
        ax.set_title(f'모델 {"균등" if dist == "uniform" else "편중"}')
        ax.grid(axis='y', alpha=0.3)
    axes[0].set_ylabel('요청당 가중치 전송 (KB)')
    axes[1].legend(handles=[plt.Rectangle((0, 0), 1, 1, color=f'C{i}') for i in range(3)], labels=STO,
                   title='저장 정책', loc='upper left', ncol=3)
    fig.suptitle(f'그림 4. 요청당 가중치 전송량 ({title}, 실측 3.015 GB/s, 위반 0 조합)', fontsize=10)
    fig.tight_layout()
    return fig


def main():
    os.makedirs(FIG, exist_ok=True)
    data = {(tag, dist): load(tag, dist) for tag, *_ in ENVS for dist in ('uniform', 'zipf')}
    for name, f in [('fig1_scheduler_miss', fig1), ('fig2_min_bw', fig2), ('fig3_storage_p99', fig3),
                    ('fig4_bytes_per_request', fig4)]:
        fig = f(data)
        fig.savefig(os.path.join(FIG, name + '.png'), dpi=150)
        plt.close(fig)
        print(os.path.join(FIG, name + '.png'))


if __name__ == '__main__':
    main()
