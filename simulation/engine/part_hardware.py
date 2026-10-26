"""part_hardware.py — hardware 조건(Hardware)과 부품 공통 class(Part). 값의 뜻은 simulation_engine.md §3"""
import functools
import json
import math
import os

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

PERIOD_US = 32_000.0                # 주기. Deadline = t_host + 주기
DMA_SETUP_US = 0.244                # DDR3 DMA 한 번의 고정 비용 (P3.1)
DDR3_READ_BANDWIDTH_MBPS, DDR3_WRITE_BANDWIDTH_MBPS = 3015.0, 2768.0     # DDR3 순차 읽기·쓰기 (P3.1). MB/s = B/µs
CLK = 0.01                          # 100 MHz 한 cycle µs
CTRL_OVERHEAD_CYC = 67              # 추론 요청 하나의 control overhead (P4.1 RTL)
BRAM_TILES, XDMA_TILES, MEMBRANE_PREP_TILES = 365, 20.5, 4.0   # XC7A200T BRAM, XDMA(P3.2), DDR3 트랙 membrane potential 준비 버퍼 등(04 §2)
MODEL_SIZES = {'L': (40, 384, 256, 64, 2), 'XL': (40, 768, 512, 128, 2)}   # 모델 구조 (입력, 은닉…, 출력)
GOLDEN_DIRS = {MODEL_SIZES['L']: 'golden_l64', MODEL_SIZES['XL']: 'golden_xl'}   # spike 수를 읽는 golden
RAMB36_SHAPES = [(512, 72), (1024, 36), (2048, 18), (4096, 9), (8192, 4), (16384, 2), (32768, 1)]   # (깊이, 폭)


def bram_tiles(depth, width):
    """depth × width bit 메모리의 최소 BRAM tile 수(RAMB18 = 0.5, P3.4)"""
    best = math.inf
    for d, w in RAMB36_SHAPES:
        cols, rem = divmod(width, w)
        if rem:
            cols += 0.5 if (d <= 16384 and rem <= w // 2) else 1
        best = min(best, cols * math.ceil(depth / d))
        if d <= 16384 and depth <= d and w >= 2:          # 깊이가 RAMB18 하나로 충분하면 RAMB18만으로(폭 w/2)
            best = min(best, 0.5 * math.ceil(width / (w // 2)))
    return best


class Hardware:
    """가속기 조건 하나. Compute array lane 수, 트랙 수, membrane potential 위치·저장 bit, 모델 구조, control overhead 배수,
    cycle당 spike 입력 수에서 뉴런 그룹, 적재 B, 추론 요청당 연산, BRAM tile을 정한다. 연산 cycle은 P4.1 RTL 식이다"""

    def __init__(self, lanes=64, tracks=1024, membrane_place='split', membrane_bits=12, arch=MODEL_SIZES['L'], ctrl_scale=1.0,
                 spikes_per_cycle=2, models=40, ddr3_bandwidth_mbps=DDR3_READ_BANDWIDTH_MBPS):
        L = lanes
        self.tracks, self.membrane_bits = tracks, membrane_bits
        self.models, self.ddr3_bandwidth_mbps, self.arch, self.spikes_per_cycle = models, ddr3_bandwidth_mbps, tuple(arch), spikes_per_cycle
        self.ctrl_cycles = CTRL_OVERHEAD_CYC * ctrl_scale
        hidden = list(zip(arch[1:-1], arch[:-2]))           # 은닉 layer (뉴런 수, 입력 수)
        neurons = sum(arch[1:])
        param_bytes = -(-2 * neurons // 64) * 64           # β·vth (64 B 단위)
        groups, group_bytes = [], []                       # 뉴런 그룹 = lane 수만큼의 뉴런 × 입력 전체, 1 word/cycle
        for li, (n, fan_in) in enumerate(hidden):
            for k in range(-(-n // L)):
                groups.append((f'L{li + 1}', fan_in))
                group_bytes.append(fan_in * min(L, n - k * L))
        n_out = arch[-1] * arch[-2]                        # 출력 layer는 word에 묶는다
        groups.append((f'L{len(hidden) + 1}', -(-n_out // L)))
        group_bytes.append(n_out)
        last = groups[-1][0]
        dense = sum(w if ly in ('L1', last) else -(-w // spikes_per_cycle) for ly, w in groups)   # 모든 입력이 spike일 때 word
        ddr3 = membrane_place != 'on_chip'                   # split·ddr3는 트랙 일부나 전부를 DDR3에 둔다
        self.groups = groups
        self.dense_req_us = (dense + self.ctrl_cycles) * CLK                 # 추론 요청당 연산(모든 입력이 spike)
        self.model_bytes = sum(group_bytes) + param_bytes                    # miss의 적재 B(β·vth 포함). 모델 하나를 DMA 한 번에
        self.entry_tiles = float(bram_tiles(sum(w for _, w in groups), 8 * L))   # weight entry 한 벌(β·vth는 LUTRAM)
        self.membrane_buf_tiles = MEMBRANE_PREP_TILES if ddr3 else 0.0          # split·ddr3: membrane potential 준비 버퍼 등
        self.membrane_bytes = -(-neurons * membrane_bits // 8) if ddr3 else 0   # 추론 요청당 membrane potential 읽기(= 쓰기) B
        self.membrane_rw_bytes = 2 * self.membrane_bytes                       # 읽기 + 쓰기. split은 split_membrane이 on-chip 몫을 뺀다
        self.write_ratio = DDR3_WRITE_BANDWIDTH_MBPS / DDR3_READ_BANDWIDTH_MBPS
        on_chip = 0.0 if ddr3 else sum(bram_tiles(tracks * n, membrane_bits) for n in arch[1:])
        self.tile_budget = BRAM_TILES - XDMA_TILES - on_chip    # weight entry·버퍼에 쓸 tile

    def load_us(self, nbytes):
        """쉬던 DMA로 nbytes를 읽는 시간"""
        return DMA_SETUP_US + nbytes / self.ddr3_bandwidth_mbps if nbytes else 0.0

    def membrane_us(self, k):
        """추론 요청 k개의 membrane potential 읽기 + 쓰기 DMA 시간"""
        b = self.membrane_bytes
        return k * (b / self.ddr3_bandwidth_mbps + b / (self.ddr3_bandwidth_mbps * self.write_ratio)) if b else 0.0

    def split_membrane(self, free_tiles):
        """split: free_tiles에 들어가는 트랙(16 단위)만 membrane potential을 on-chip에 두고 그 트랙 수를 낸다.
        나머지 DDR3 트랙의 읽기·쓰기 B는 추론 요청당 평균으로 줄인다"""
        k = max((k for k in range(0, self.tracks + 1, 16)
                 if sum(bram_tiles(k * n, self.membrane_bits) for n in self.arch[1:]) <= free_tiles), default=0)
        off, rw = 1 - k / self.tracks, self.membrane_bytes
        self.membrane_bytes, self.membrane_rw_bytes = off * rw, 2 * off * rw
        return k

    def spike_req_us(self, track_model, periods, seed):
        """추론 요청별 연산 µs(spike 0 건너뛰기). 트랙마다 golden 구간과 시작 위치를 무작위로 골라 주기마다 다음 timestep을 쓴다"""
        tab = golden_words(self.arch, tuple(self.groups), self.spikes_per_cycle, self.models)
        r = np.random.default_rng(seed + 5555)             # 다른 난수열과 섞이지 않게 따로 뽑는다
        seg, start = r.integers(0, 1 << 30, (2, track_model.size))
        w = np.stack([tab[m][s % len(tab[m]), (o + periods) % tab[m].shape[1]] for m, s, o in zip(track_model, seg, start)])
        return ((w + self.ctrl_cycles) * CLK).ravel()


@functools.lru_cache(maxsize=None)
def golden_words(arch, groups, per_cycle, n_models):
    """모델마다 (golden 구간, timestep)별 추론 요청 하나의 연산 word 수. L1과 출력 layer는 dense, 가운데 layer는 앞 layer
    spike 수 ÷ per_cycle(올림). 첫 timestep은 뺀다. golden이 없는 모델(41번째)은 40모델의 구간을 모은 표를 쓴다"""
    d = os.path.join(ROOT, 'hardware', 'data', GOLDEN_DIRS[tuple(arch)])
    with open(os.path.join(d, 'manifest.json')) as f:
        recs = json.load(f)['records']
    last = f'L{len(arch) - 1}'
    tab = [[] for _ in range(max(n_models, 1 + max(r['model_id'] for r in recs)))]
    for r in recs:
        z = np.load(os.path.join(d, r['unit'], f"{r['tag']}.npz"))
        w = sum(np.full(z['spk_l1'].shape[0], fan_in) if ly in ('L1', last) else np.ceil(z[f'spk_l{int(ly[1:]) - 1}'].sum(1) / per_cycle)
                for ly, fan_in in groups)
        tab[r['model_id']].append(w[1:])
    pool = [t for x in tab for t in x]
    return [np.array(t or pool, float) for t in tab[:n_models]]


class Part:
    """부품(cache 정책·scheduler·연산) 공통. hardware 조건 hw를 받고 키워드 인자로 class에 있는 속성만 바꾼다(환경의 *_attrs).
    simulate는 실행마다 reset(wl)을 먼저 부르고, 결정에 쓰는 queue와 시각은 method 인자로 넘긴다"""
    name = ''

    def __init__(self, hw, **attrs):
        self.hw = hw
        for k, v in attrs.items():
            if not hasattr(self, k):
                raise TypeError(f'{type(self).__name__} has no attribute {k!r}')
            setattr(self, k, v)

    def reset(self, wl):
        """추론 요청열 wl 하나를 시작할 때 상태를 비운다"""
