"""part_deadline.py — deadline 분석: 조건부 응답 시간 식과 adversarial search의 지연 꼴. 식의 뜻은 05_SCHEDULING.md §6,
mode는 simulation_engine.md §7.3"""
import functools
import os

import numpy as np

from part_hardware import DMA_SETUP_US, PERIOD_US, ROOT
from part_workload import LINK_IN_FILE, LINK_OUT_FILE, PACKET_REQUESTS, link_samples


@functools.lru_cache(maxsize=None)
def group_stats(path):
    """모델 묶음 지연 표 전체 → (G 최소, G 최대, G p99.9, 주기 사이 가장 큰 감소 max(G_k − G_(k+1))) µs. 표가 없으면 모두 0"""
    if not path:
        return 0.0, 0.0, 0.0, 0.0
    a = np.loadtxt(os.path.join(ROOT, path), delimiter=',', skiprows=1)
    ep, m = a[:, 0].astype(int), a[:, 1].astype(int)
    g = np.full((ep.max() - ep.min() + 1, m.max() + 1), np.nan)
    g[ep - ep.min(), m] = a[:, 2]
    return float(np.nanmin(g)), float(np.nanmax(g)), float(np.nanpercentile(g, 99.9)), float(np.nanmax(g[:-1] - g[1:]))


def host_max_us(e):
    """Host 처리 지연 최대 H = 모델 묶음 지연 표의 최대 + J µs"""
    return group_stats(e['host_group_trace'])[1] + e['host_jitter_ms'] * 1000.0


def bound(s):
    """Setup s 점의 조건부 응답 시간(05 §6.1). R_single = N·C_dense + M·L_weight + N_DDR·C_state(모델·주기마다 단일 적재 가정),
    R_cond = H + d_in,max + R_single + d_out,max. 링크 지연은 표본 최대다. 같은 트랙 추론 요청 사이 최소 간격 S는 즉시 송신이면
    32 ms − (G_max − G_min) − J다. 모아 보내기도 대기 뒤에 준비된 추론 요청은 바로 보내므로 32 ms − (H − G_min)으로 같은 값이다.
    R_single < S가 단일 적재의 필요조건이다"""
    e, hw = s.e, s.hw
    gmin, gmax, g999, drop = group_stats(e['host_group_trace'])
    J, H = e['host_jitter_ms'] * 1000.0, host_max_us(e)
    D = H if e['host_gather_to_max'] else e['host_gather_ms'] * 1000.0
    N, M = e['track_count'], e['model_count']
    cd, lw = hw.dense_req_us, hw.load_us(hw.model_bytes)
    rw = -(-sum(hw.arch[1:]) * hw.membrane_bits // 8)                # DDR3 트랙 하나의 membrane potential B
    cs = 2 * DMA_SETUP_US + rw / hw.ddr_mbps + rw / (hw.ddr_mbps * hw.write_ratio)   # 읽기 + 쓰기 DMA
    din, dout = float(link_samples(LINK_IN_FILE).max()), float(link_samples(LINK_OUT_FILE).max())
    n_ddr = N - s.onchip_tracks
    single, allmiss = N * cd + M * lw + n_ddr * cs, N * cd + N * lw + n_ddr * cs
    cond = H + din + single + dout
    gap = PERIOD_US - (H - gmin) if D else PERIOD_US - (gmax - gmin) - J
    return dict(G_min_ms=gmin / 1000, G_max_ms=gmax / 1000, G_p999_ms=g999 / 1000, host_max_ms=H / 1000, gather_wait_ms=D / 1000,
                C_dense_us=cd, L_weight_us=lw, C_state_us=cs, n_ddr=n_ddr, din_max_us=din, dout_max_us=dout,
                single_fpga_ms=single / 1000, allmiss_fpga_ms=allmiss / 1000, cond_e2e_ms=cond / 1000, min_gap_ms=gap / 1000,
                min_gap_obs_ms=float('nan') if D else (PERIOD_US - drop - J) / 1000,
                cond_gap_ok=bool(single < gap), cond_e2e_ok=bool(cond <= PERIOD_US))


class DelayPattern:
    """adversarial search의 지연 꼴 하나. 모델마다 묶음 지연 꼴(GROUP, 범위 [0, G))과 추론 요청별 지연 꼴(REQUEST, 범위 [0, J))을 고른다.
    묶음: g0 0 | gmax G | galt 주기마다 G와 0을 번갈아(같은 트랙 간격이 32 ms − G로 준다) | galign 모델 offset을 G 간격 경계까지
    늦춰 여러 모델이 한꺼번에 온다 | grand U(0, G). 추론 요청별: early 0 | late J | spread 트랙 순서대로 0~J | alt 트랙·주기마다 0과 J를
    번갈아 | rand U(0, J) | pkt 모델의 앞 packet 하나(23트랙)는 0, 나머지는 J"""
    GROUP = ('g0', 'gmax', 'galt', 'galign', 'grand')
    REQUEST = ('early', 'late', 'spread', 'alt', 'rand', 'pkt')

    def __init__(self, group, request):
        self.group, self.request = np.asarray(group), np.asarray(request)

    def delays(self, tm, K, G, J):
        """(트랙, 주기) Host 처리 지연 µs = 묶음 지연 꼴[트랙의 모델] + 추론 요청별 지연 꼴. 난수는 꼴마다 고정 seed"""
        return self._group(K, G)[tm] + self._request(tm, K, J)

    def mutated(self, rng, n):
        """모델 n개의 두 꼴을 무작위로 바꾼 사본"""
        g, u = self.group.copy(), self.request.copy()
        m = rng.choice(g.size, n, replace=False)
        g[m], u[m] = rng.integers(0, len(self.GROUP), n), rng.integers(0, len(self.REQUEST), n)
        return DelayPattern(g, u)

    def codes(self):
        """결과 CSV에 남길 꼴 이름(모델마다 한 글자)"""
        return ''.join('0mtar'[k] for k in self.group), ''.join('elsarp'[k] for k in self.request)

    def _group(self, K, G):
        r, top, M = np.random.default_rng(77), np.nextafter(G, 0), self.group.size
        out = np.zeros((M, K))
        for m, k in enumerate(self.group):
            p = self.GROUP[k]
            if p == 'gmax':
                out[m] = top
            elif p == 'galt':
                out[m] = (np.arange(K) % 2 == 0) * top
            elif p == 'galign' and G > 0:
                o = m * PERIOD_US / M
                out[m] = min(top, np.ceil(o / G) * G - o)
            elif p == 'grand':
                out[m] = r.uniform(0, G, K)
        return out

    def _request(self, tm, K, J):
        r, top = np.random.default_rng(99), np.nextafter(J, 0)
        out = np.zeros((tm.size, K))
        for m, k in enumerate(self.request):
            idx = np.flatnonzero(tm == m)
            if not idx.size:
                continue
            p = self.REQUEST[k]
            if p == 'late':
                out[idx] = top
            elif p == 'spread':
                out[idx] = np.repeat((np.arange(idx.size) / max(1, idx.size - 1) * top)[:, None], K, 1)
            elif p == 'alt':
                out[idx] = ((np.arange(idx.size)[:, None] + np.arange(K)[None, :]) % 2) * top
            elif p == 'rand':
                out[idx] = r.uniform(0, J, (idx.size, K))
            elif p == 'pkt':
                out[idx[PACKET_REQUESTS:]] = top
        return out
