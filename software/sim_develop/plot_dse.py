#!/usr/bin/env python3
"""plot_dse.py — dse.py 결과 → 설계별 최대 트랙 수 그림

    python3 plot_dse.py            # rev 1: sim_result/dse_capacity.jsonl → fig5_dse_capacity.png
    python3 plot_dse.py --rev 2    # rev 2: sim_result/dse2_capacity.jsonl → fig6_dse2_capacity.png
"""
import argparse
import json
import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(os.path.dirname(HERE), 'sim_result')
plt.rcParams.update({'font.family': 'UnDotum', 'axes.unicode_minus': False, 'font.size': 9})
STO = ['A.전체캐시', 'B.L1상주', 'C.혼합', 'D.스트림']
CMP = ['한번에', '한줄씩']
BOUND = {32: 715, 64: 1430, 128: 2540, 256: 4034}
CFG = {1: dict(src='dse_capacity.jsonl', out='fig5_dse_capacity.png', lanes=[32, 64, 128],
               sch=['FCFS', '그룹핑', '점수'], col=['#9e9e9e', 'C0', 'C2'],
               title='그림 5. 설계별 최대 트랙 수 — L INT8, DDR3 3.015 GB/s, 시나리오 U·K·S·I·SK 모두 위반 0 '),
       2: dict(src='dse2_capacity.jsonl', out='fig6_dse2_capacity.png', lanes=[32, 64, 128, 256],
               sch=['FCFS', 'EDF', '그룹핑', '점수'], col=['#9e9e9e', '#cfa15a', 'C0', 'C2'],
               title='그림 6. 설계별 최대 트랙 수 (rev 2: 호스트 1 ms 묶음 입출력) — 시나리오 U·K·S·I·SK·R 모두 위반 0 ')}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--rev', type=int, default=1, choices=[1, 2])
    cf = CFG[ap.parse_args().rev]
    SCH = cf['sch']
    rows = [json.loads(l) for l in open(os.path.join(RES, cf['src']))]
    cap = {(r['lanes'], r['mem'], r['storage'], r['compute'], r['scheduler']): r['capacity'] for r in rows}
    nl = len(cf['lanes'])
    fig, axes = plt.subplots(nl, 2, figsize=(11, 3.3 * nl), sharey='row')
    w = 0.8 / len(SCH)
    for i, lanes in enumerate(cf['lanes']):
        for j, mem in enumerate(['onchip', 'ddr']):
            ax = axes[i, j]
            groups = [(s, c) for s in STO for c in CMP]
            x = np.arange(len(groups))
            for k, (q, col) in enumerate(zip(SCH, cf['col'])):
                ax.bar(x + (k - (len(SCH) - 1) / 2) * w, [cap[(lanes, mem, s, c, q)] for s, c in groups], w,
                       color=col, label=q)
            ax.axhline(512, color='black', ls=':', lw=1)
            ax.axhline(BOUND[lanes], color='red', ls='--', lw=1)
            ax.text(len(groups) - 0.5, 512, ' 현재 목표 512', va='bottom', ha='right', fontsize=7)
            ax.text(len(groups) - 0.5, BOUND[lanes], ' 연산 한계', va='bottom', ha='right', fontsize=7, color='red')
            ax.set_xticks(x)
            ax.set_xticklabels([f'{s[0]}·{c}' for s, c in groups], fontsize=7.5)
            ax.set_title(f'{lanes}레인 · 막전위 {"온칩" if mem == "onchip" else "DDR3"}')
            ax.grid(axis='y', alpha=0.3)
            if j == 0:
                ax.set_ylabel('최대 트랙 수 (위반 0)')
    axes[1, 0].legend(title='스케줄러', fontsize=8, loc='upper left', ncol=len(SCH))
    fig.suptitle(cf['title'] + '(A 전체 캐시, B L1 상주, C 혼합, D 스트림)', fontsize=10)
    fig.tight_layout()
    out = os.path.join(RES, 'figures', cf['out'])
    fig.savefig(out, dpi=150)
    print(out)


if __name__ == '__main__':
    main()
