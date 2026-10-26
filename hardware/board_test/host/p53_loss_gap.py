#!/usr/bin/env python3
"""p53_loss_gap.py — 결과 손실과 직전 송신 휴지의 관계 (P5.3 결과 손실 조사)

결과 CSV(mmss_host --log)의 t_done(FPGA µs)으로 FPGA가 결과를 보낸 시각을 잡는다. 빠진 결과의 시각은 같은 모델·frame
batch에서 트랙 순서로 이웃 시각을 선형 보간한다. 결과마다 바로 앞 결과와의 간격(송신을 쉰 시간)으로 나눠 손실 비율을 센다.
Batch 안 위치(처음·가운데·끝)별 사건 수도 낸다. 제어 응답(초당 약 5개)은 셈에서 뺀다.

    python3 p53_loss_gap.py <map.txt> <결과 CSV> [<결과 CSV> ...]
"""
import collections
import sys

import numpy as np

BINS = [0, 10, 20, 50, 100, 200, 500, 1000, 1e12]


def main():
    model_of = np.array([int(l.split()[0]) for l in open(sys.argv[1])])
    first = {m: int(np.flatnonzero(model_of == m)[0]) for m in set(model_of.tolist())}
    size = collections.Counter(model_of.tolist())
    tot, lost_n = np.zeros(len(BINS) - 1), np.zeros(len(BINS) - 1)
    pos, n_ev = collections.Counter(), 0
    for path in sys.argv[2:]:
        tr, k, td = np.loadtxt(path, delimiter=',', skiprows=1, usecols=(0, 2, 9), dtype=np.int64).T
        kmax = int(k.max())                              # 마지막 frame은 실행 끝이라 뺀다
        T = np.full((len(model_of), kmax + 1), -1, np.int64)
        T[tr, k] = td
        have = T >= 0
        for m in first:
            trs = np.flatnonzero(model_of == m)
            for kk in range(kmax):
                row = T[trs, kk]
                miss = row < 0
                if miss.any() and (~miss).sum() >= 2:
                    x = np.flatnonzero(~miss)
                    T[trs[miss], kk] = np.interp(np.flatnonzero(miss), x, row[x]).astype(np.int64)
                if miss.any():
                    n_ev += 1
                    p0, p1 = np.flatnonzero(miss)[[0, -1]]
                    pos['처음' if p0 == 0 else ('끝' if p1 == size[m] - 1 else '가운데')] += 1
        allt = np.sort(T[:, :kmax][T[:, :kmax] >= 0])
        lostt = np.sort(T[:, :kmax][~have[:, :kmax] & (T[:, :kmax] >= 0)])
        i = np.searchsorted(allt, lostt)
        tot += np.histogram(np.diff(allt), BINS)[0]
        lost_n += np.histogram(allt[i] - allt[np.maximum(i - 1, 0)], BINS)[0]
    print(f'사건 {n_ev}, batch 안 첫 손실 위치 {dict(pos)}')
    for a, b, n, l in zip(BINS[:-1], BINS[1:], tot, lost_n):
        hi = f'{b:.0f}' if b < 1e12 else ''
        print(f'앞 결과와 간격 {a:5.0f}~{hi:6s} µs: 결과 {int(n):9d}, 손실 {int(l):4d}, 100만 개당 {1e6 * l / max(n, 1):6.1f}')


if __name__ == '__main__':
    main()
