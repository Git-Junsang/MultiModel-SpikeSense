#!/usr/bin/env python3
"""engine.py — simulation 엔진. 환경 파일 하나(simulation/environment/*.toml) = 실험 하나. 연구의 모든 조건은 환경 값으로 바꾼다

이 파일 하나에 다 있다: 1. BRAM tile 계산, 2. 시뮬레이터 본체(요청열, 비용, event loop, 지표),
3. 부품(저장 정책·연산 방식·scheduler), 4. 실행기(환경 파일 → 부품 조립 → mode 실행 → CSV).
실행기는 환경 값으로 부품과 요청열을 만들고 mode대로 돌린다.
  run     [sweep]의 점마다 시나리오 × seed를 끝까지 돌려 지표를 낸다. BRAM 예산을 넘는 점은 돌리지 않는다
  search  점마다 search_key를 search_values 순서로 바꿔 가며, 모든 시나리오·seed에서 miss 0인 마지막 값을 찾는다
          (최대 트랙, DDR 대역폭 하한). 통과가 값 순서에 대해 단조라고 가정하고 2배씩 넓혀 실패 지점을 찾은 뒤 이분 탐색한다
  tune    점마다 sched_attrs[tune_attr] 후보를 tune_conds × 시나리오 × seed에 돌려, 모든 실행이 miss 0인 값 중
          weight DRAM byte가 가장 작은 값을 고른다. 없으면 miss가 난 실행이 가장 적은 값. 고른 값은 다른 환경 파일에 옮겨 쓴다
결과(CSV, 이름 = 환경 파일 이름):
  simulation/result/<이름>.csv       점마다 한 줄: point, label, 그 점의 환경 값 전부, BRAM tile, mode별 요약
                                     (run: summarize 지표, search: found·capped, tune: passed·chosen·w_kib·fails)
  simulation/result/<이름>_runs.csv.gz  작업마다 한 줄(응답 시간 히스토그램이 커서 gzip). run: 점 × 시나리오 × seed의 simulate() 지표와 hist(응답 시간 히스토그램
                                     [칸, 개수], 칸 BIN ms), search: 점 × 시험한 값(passed), tune: 점 × 후보(fails, w_kib)
  칸 값: 문자열은 그대로, 숫자·참거짓·목록·표는 JSON. read_csv가 원래 값으로 되돌린다

본체(2절)는 조건을 전역 변수로 받는다. build가 실행마다 쓰는 전역 값을 모두 환경에서 다시 정하므로 앞 실행의 값이 남지 않는다.

    python3 simulation/engine/engine.py simulation/environment/<파일>.toml [--jobs 11]
"""
import argparse
import csv
import functools
import gzip
import heapq
import inspect
import io
import itertools
import json
import math
import os
import sys
import time
import tomllib
from collections import OrderedDict
from dataclasses import dataclass
from multiprocessing import Pool

import numpy as np

# 본체와 부품을 파일로 나눴을 때 쓰던 이름(sc.이름, pol.이름). 한 파일이 되어 둘 다 이 모듈을 가리킨다
sc = pol = sys.modules[__name__]
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


# ==== 1. BRAM tile 계산 (P3.4) ====================================================
CFG36 = [(512, 72), (1024, 36), (2048, 18), (4096, 9), (8192, 4), (16384, 2), (32768, 1)]


def tiles(depth, width):
    """depth × width bit 메모리의 최소 RAMB36 환산 타일 수 (RAMB18 = 0.5)"""
    best = math.inf
    for d, w in CFG36:
        cols, rem = divmod(width, w)
        if rem:
            cols += 0.5 if (d <= 16384 and rem <= w // 2) else 1
        best = min(best, cols * math.ceil(depth / d))
        # 깊이가 RAMB18 하나로 충분하면 RAMB18만으로 (폭 w/2) 구성
        if d <= 16384 and depth <= d and w >= 2:
            best = min(best, 0.5 * math.ceil(width / (w // 2)))
    return best


# ==== 2. 시뮬레이터 본체 ===========================================================
# 옛 sim_core.py. P3.5 공통 시뮬레이터: 요청 도착(실측 PCIe 지연), 실측 비용 모델, 이벤트 루프, 지표
#
# 부품(저장 정책·scheduler·연산 방식)은 3절에 있고, 본체는 부품이 무엇이든 같은 방식으로
# 요청을 만들고 시간을 진행하고 지표를 낸다. 시간 단위는 µs, 바이트/µs = MB/s.
#
# 진행 방식 (한 batch 앞을 미리 정하는 1단 선행):
#   1. 결정 시각 T에 scheduler가 다음 모델 m을 고른다(pick).
#   2. 저장 정책이 m에 필요한 그룹별 적재 바이트를 정한다(plan, cache 상태 갱신).
#   3. 연산 방식이 DMA·연산 시각을 계산한다. 첫 그룹 연산이 시작되는 시각 s에 batch 구성원을
#      확정한다(members): T 이후 s까지 도착한 같은 모델 요청도 합류한다.
#   4. 다음 결정 시각은 s다. 따라서 batch i가 연산하는 동안 batch i+1의 weight를 가져온다.

# ---- 고정 조건 (SIM_PLAN §1) -------------------------------------------------
P = 32_000.0            # 주기 = deadline, µs
M = 40                  # 모델 수
T0 = 0.244              # DDR3 슬라이스 고정 비용 µs (P3.1 RBC 회귀)
BW = 3015.0             # DDR3 유효 대역폭 B/µs (3.015 GB/s)
CLK = 0.01              # 100 MHz 한 cycle µs
OVH = 1.10              # 제어 비용 10 % (가정)
ARCH_L = (40, 384, 256, 64, 2)   # 모델 L (P3.6 확정). configure(arch=...)로 바꾼다
PARAM_B = 1412          # β·vth 706 × 2 B (MODEL_MEMORY_LAYOUT). configure가 구조에 맞게 다시 정함
NEURONS = [(384, 40), (256, 384), (64, 256)]     # 은닉 layer (뉴런 수, 입력 수). 출력 layer = 2뉴런 × 64입력
XDMA_T = 20.5           # P3.2 실측
SPK_PER_CYC = 1         # L2·L3에서 cycle마다 누산하는 spike 입력 수(2 = BRAM 두 번째 port + DSP pre-adder, P3.12 가정)
MEM_CAP = 64            # membrane potential을 DDR3에 둘 때 한 줄씩 batch의 membrane potential 버퍼 트랙 수(가정)
BW_W = 2768.0           # DDR3 순차 쓰기 B/µs (P3.1 rbc, 1 KiB 버스트). rev 2의 membrane potential 쓰기에 사용
IN_B = 64               # 요청 하나의 입력(mel 40 B + 트랙·순서 정보), P3.2 queue 항목 512 bit
H2C_BW, C2H_BW = 758.0, 566.0      # Host DMA 처리량 B/µs (P3.3, 4 MiB)


def _pow2(n):
    return 1 << (n - 1).bit_length()


def configure(lanes=32, tracks=512, wbits=8, mem='auto', mem_cap=MEM_CAP, rev=1, arch=ARCH_L):
    """레인 수·트랙 수·membrane potential 위치에 따라 그룹·비용·타일 상수를 정한다. 기본(32, 512)이 SIM_PLAN §1 기준 환경.

    출력 고정 L레인: word = L × wbits bit, 뉴런 그룹 = L뉴런 × 입력 전체, 1 word/cycle.
    layer의 뉴런 수가 L보다 적으면(128레인의 layer 3) 그 그룹은 레인 일부만 쓴다. layer 4(2뉴런 × 64입력)는
    word에 묶어 2 × 64 / L word(최소 1)로 둔다.
    wbits = 6이면 DDR3에는 6 bit로 채워 저장하고 DMA가 256 → 192 bit로 바꾼다고 가정한다(P3.6).
    mem: 'onchip'이면 membrane potential(트랙당 706 × 2 B)을 BRAM에, 'ddr'이면 DDR3에 두고 요청마다 읽기·쓰기
    2,824 B를 DMA에 더한다. 'auto'는 BRAM에 들어가면 on-chip. DDR3에 두면 membrane potential 준비 버퍼가 연산 방식마다
    다르다(한 번에: 트랙 2개분, 한 줄씩: batch 전체 = mem_cap 트랙분, batch도 mem_cap으로 제한).
    rev 2 (MODEL_SIZE_PLAN §4.2, 트랙이 많을 때의 가정 보강):
      - 한 줄씩은 membrane potential 위치와 상관없이 batch ≤ mem_cap. 입력·layer 간 spike 버퍼 mem_cap × 128 B를 BRAM에 둔다
        (입력 40 + layer1 48 + layer2 32 + layer3 8 B. 그룹 순서로 돌면 batch 전체 트랙의 앞 layer spike를 들고 있어야 함)
      - membrane potential DDR3 쓰기는 순차 쓰기 실측 대역폭(BW_W)으로 계산
    rev 3 = rev 2 + entry 깊이를 실제 word 수로(2의 거듭제곱으로 올리지 않음)
    rev 4 = rev 3 + 슬라이스 이중 버퍼 한 칸 = max(512, 가장 큰 뉴런 그룹 word 수). 한 줄씩은 batch의 트랙마다 그룹 전체를
            다시 읽으므로 그룹이 한 칸에 다 들어가야 한다. L은 가장 큰 그룹이 384 word라 rev 3과 같고,
            XL 128·256레인은 layer 2 그룹이 768 word라 칸이 커진다(256레인 57 → 85.5 타일)
    rev 5 = rev 4 + β·vth와 membrane potential DMA를 ARCH_SPEC 크기(64 B 단위로 올림, XL 2,880 B)로 계산
    arch: layer 크기 (입력, 은닉…, 출력). 시뮬레이터는 크기(바이트·뉴런·cycle)만 쓰므로 학습된 weight가 없어도 된다.
    예: XL = (40, 768, 512, 128, 2)"""
    g = globals()
    L = lanes
    word = L * wbits // 8                     # word 바이트: 32레인 INT8 = 32 B(256 bit), INT6 = 24 B(192 bit)
    hidden = list(zip(arch[1:-1], arch[:-2]))           # 은닉 layer (뉴런 수, 입력 수)
    neu = sum(arch[1:])                                  # 뉴런 수 (L 706)
    pad = (lambda b: -(-b // 64) * 64) if rev >= 5 else (lambda b: b)   # rev 5: ARCH_SPEC §6.3·6.5 DMA 크기(64 B 단위)
    param_b = pad(2 * neu)                               # β·vth (L 1,412 B, rev 5 XL 2,880 B)
    state_b = pad(2 * neu)                               # 요청당 membrane potential 읽기 또는 쓰기 byte
    groups, g_bytes = [], []
    for li, (n, fan_in) in enumerate(hidden):
        for k in range(-(-n // L)):
            groups.append((f'L{li + 1}', fan_in))
            g_bytes.append(fan_in * min(L, n - k * L) * wbits // 8)
    n_o = arch[-1] * arch[-2]                            # 출력 layer weight 수 (L 2 × 64)
    groups.append((f'L{len(hidden) + 1}', max(1, n_o // L)))
    g_bytes.append(n_o * wbits // 8)
    nl1 = -(-arch[1] // L)
    words = sum(w for _, w in groups)
    mem_t = sum(tiles(tracks * n, 16) for n in arch[1:])
    slot = max(512, max(w for _, w in groups)) if rev >= 4 else 512
    slice_t = tiles(2 * slot, 8 * word)
    if mem == 'auto':
        mem = 'onchip' if 365 - XDMA_T - mem_t >= slice_t else 'ddr'
    offchip = mem == 'ddr'
    g.update(
        ARCH=tuple(arch), NEU=neu, PARAM_B=param_b, NEURONS=hidden,
        LANES=L, TRACKS=tracks, WBITS=wbits, WORD=word, GROUPS=groups, G_BYTES=g_bytes,
        G_CYC=[w * OVH * CLK for _, w in groups], N_L1=nl1, WORDS=words,
        C_REQ=words * OVH * CLK,                                         # 32레인 44.748 µs
        MODEL_B=sum(g_bytes) + param_b,                                  # 131,588 B
        L2L4_B=sum(g_bytes[nl1:]),                                       # 114,816 B
        L1_WORDS=sum(w for _, w in groups[:nl1]),
        L2L4_WORDS=sum(w for _, w in groups[nl1:]),
        # entry(모델 1벌) = weight + β·vth. rev ≤ 2는 깊이를 2의 거듭제곱으로 올림(L 32레인 4,068 → 4,096),
        # rev 3은 실제 word 수 그대로(주소 = 시작 + offset이면 충분). 넓은 레인·큰 모델에서 차이가 크다(XL 256레인 229 → 143.5)
        ENTRY_T=tiles(words if rev >= 3 else _pow2(words), 8 * word) + tiles(neu, 16),   # 29 (L 32레인)
        SLICE_T=slice_t,                                                 # 슬라이스 이중 버퍼
        SLOT_WORDS=slot,                                                 # 이중 버퍼 한 칸의 word 수
        MEM_OFFCHIP=offchip,
        MEM_ONCHIP_T=mem_t,                                              # on-chip에 둘 때의 membrane potential 타일
        MEM_T=0.0 if offchip else mem_t,
        MEMBUF_TRACK_T=tiles(2 * neu, 16) if offchip else 0.0,           # 한 번에: 트랙 2개분 준비 버퍼
        MEMBUF_T=tiles(mem_cap * neu, 16) if offchip else 0.0,           # 한 줄씩: batch membrane potential 버퍼
        MEM_B=2 * state_b if offchip else 0,                             # 요청당 membrane potential 읽기 + 쓰기
        MEM_RD=state_b if offchip else 0,
        WRATIO=BW_W / 3015.0 if rev >= 2 else 1.0,                       # 쓰기 대역폭 / 읽기 대역폭
        BATCH_CAP=mem_cap if (offchip or rev >= 2) else None,
        SPK_T=tiles(mem_cap * (arch[0] + sum(arch[1:-1]) // 8), 8) if rev >= 2 else 0.0,  # 한 줄씩 batch 입력·spike 버퍼 (L 128 B)
        REV=rev,
    )
    # weight·β·vth·적재 버퍼·membrane potential 준비 버퍼 예산: 365 − XDMA − on-chip membrane potential (음수면 배치 불가)
    g['TILE_BUDGET'] = 365 - XDMA_T - g['MEM_T']
    g['ZERO'] = [0] * len(groups)
    g['FULL'] = [g_bytes[0] + param_b] + g_bytes[1:]                     # β·vth는 첫 그룹에 붙임
    g['L2L4'] = [0] * nl1 + g_bytes[nl1:]


configure()


def xfer_time(nbytes):
    """DMA 한 번(쉬던 DMA를 새로 시작)의 시간"""
    return T0 + nbytes / BW if nbytes else 0.0


def mem_time(k):
    """요청 k개의 membrane potential 읽기 + 쓰기 DMA 시간 µs (membrane potential on-chip이면 0)"""
    return k * (MEM_RD / BW + MEM_RD / (BW * WRATIO)) if MEM_RD else 0.0


# ---- 요청열 ------------------------------------------------------------------
PCIE_RAW = os.path.join(ROOT, 'hardware', 'board_test', 'p3_meas', 'result', 'raw', 'pcie')
D_IN_FILE = 'p3_h2c_64_p62.5.txt'      # 64 B H2C, 62.5 µs 간격(= 16 kHz 요청률)
D_OUT_FILE = 'p3_c2h_64.txt'           # 64 B C2H, 연속
H_IN_FILE = 'p3_h2c_64_p1000.txt'      # Host batch 전송(host=W_h): 64 B H2C, 1 ms 간격
H_OUT_FILE = 'p3_c2h_64_p1000.txt'     # 64 B C2H, 1 ms 간격


def load_samples(name):
    return np.loadtxt(os.path.join(PCIE_RAW, name)) / 1000.0           # ns → µs


@dataclass
class Workload:
    n_tracks: int
    seed: int
    track_model: np.ndarray     # 트랙 → 모델
    t_gen: np.ndarray           # 요청별, t_arr 오름차순 정렬
    t_arr: np.ndarray
    model: np.ndarray
    d_out: np.ndarray
    w0: float                   # 측정 구간 [w0, w1)
    w1: float
    out_w: float = 0.0          # Host 결과 읽기 주기 µs (0 = 요청마다 d_out)
    out_phi: float = 0.0        # 결과 읽기 시각 = out_phi + j × out_w
    out_lat: np.ndarray = None  # j번째 결과 읽기(C2H)의 지연 µs
    cost: np.ndarray = None     # 요청별 연산 µs (spike 0 건너뛰기). None = 모든 요청 C_REQ(dense)
    track: np.ndarray = None    # 요청별 트랙 번호
    mem_addr: np.ndarray = None # 트랙별 membrane potential DDR3 자리(−1 = on-chip). None = on-chip 비율만큼 요청당 평균으로 뺌
    pre: float = 0.0            # 모든 요청 도착에 같이 더한 지연 µs(외부 지연, 꼬리). offset 예측이 도착 시각으로 옮겨 쓴다

    def done(self, fin, idx):
        """연산 완료 시각 fin인 요청 idx의 결과가 Host에 도착하는 시각"""
        if not self.out_w:
            return fin + self.d_out[idx]
        j = np.ceil((fin - self.out_phi) / self.out_w).astype(np.int64)
        return self.out_phi + j * self.out_w + self.out_lat[np.minimum(j, self.out_lat.size - 1)]


ZIPF = 1.0 / np.arange(1, M + 1)
ZIPF /= ZIPF.sum()              # 모델 k의 트랙 비율 ∝ 1/(k+1): 상위 5모델 53.4 %, 1위 23.4 %


# 요청 시나리오 (MODEL_SIZE_PLAN §2.1). make_workload 인자로 넘긴다
SCENARIOS = {
    'U': dict(),                            # 균등: 모델 균등 배정, 트랙마다 offset 무작위
    'K': dict(dist='zipf'),                 # 편중: 몇 개 모델에 트랙이 몰림
    'S': dict(offset=0.0),                  # 동시: 모든 채널을 같은 클럭으로 샘플 → 512개 동시 도착
    'I': dict(p_req=0.25),                  # 띄엄띄엄: 주기마다 요청 확률 0.25 (가정)
    'SK': dict(offset=0.0, dist='zipf'),    # 동시 + 편중
    'R': dict(congestion=(0.25, 1.0)),      # 무작위 혼잡도: 주기마다 활성 비율을 0.25~1에서 무작위로 (MODEL_SIZE_PLAN §4.2)
}


GOLDEN = {(40, 384, 256, 64, 2): 'golden_l64', (40, 768, 512, 128, 2): 'golden_xl'}


@functools.lru_cache(maxsize=None)
def spike_words(arch, lanes, per=1):
    """모델마다 (golden 구간, timestep)별 요청 하나의 연산 word 수. ARCH_SPEC §5.2: L2~L4는 spike가 0인 입력을 건너뛰므로
    가운데 layer 그룹은 앞 layer spike 수 ÷ per(올림)만큼, L1(mel 입력)과 출력 layer(reduction)는 dense. 첫 timestep(membrane potential 0에서 시작)은 뺀다"""
    d = os.path.join(ROOT, 'hardware', 'data', GOLDEN[tuple(arch)])
    with open(os.path.join(d, 'manifest.json')) as f:
        recs = json.load(f)['records']
    last = f'L{len(arch) - 1}'
    tab = [[] for _ in range(M)]
    for r in recs:
        z = np.load(os.path.join(d, r['unit'], f"{r['tag']}.npz"))
        w = sum(np.full(z['spk_l1'].shape[0], fan_in) if ly in ('L1', last) else np.ceil(z[f'spk_l{int(ly[1:]) - 1}'].sum(1) / per)
                for ly, fan_in in GROUPS)
        tab[r['model_id']].append(w[1:])
    return [np.array(t, float) for t in tab]


def spike_cost(tm, k, seed):
    """트랙 tm(모델), 주기 k(트랙마다 같은 배열)의 요청별 연산 µs. 트랙마다 golden 구간 하나와 시작 위치를 무작위로 골라
    주기마다 다음 timestep을 쓴다. 제어 비용은 dense와 같은 절대 cycle((OVH − 1) × WORDS)로 둔다(가정)"""
    tab = spike_words(ARCH, LANES, SPK_PER_CYC)
    r = np.random.default_rng(seed + 5555)             # 다른 난수열에 영향을 주지 않도록 별도 생성기
    seg, off = r.integers(0, 1 << 30, (2, tm.size))
    w = np.stack([tab[m][s % len(tab[m]), (o + k) % tab[m].shape[1]] for m, s, o in zip(tm, seg, off)])
    return ((w + (OVH - 1) * WORDS) * CLK).ravel()


def make_workload(n_tracks=512, seed=0, warm=16, meas=64, d_host=0.0,
                  d_in=None, d_out=None, offset=None, track_model=None, dist='uniform', p_req=1.0,
                  congestion=None, host=None, spike=False):
    """warm·meas는 주기 수. d_in·d_out: None이면 실측 표본, 숫자면 상수.
    dist: 트랙→모델 배정. 'uniform' 균등 무작위, 'zipf' 편중(가정).
    offset: None이면 트랙별 무작위 offset, 숫자·배열이면 그 offset. p_req: 주기마다 요청을 낼 확률.
    congestion: (lo, hi)면 주기마다 활성 비율 c ~ U(lo, hi)를 정하고 트랙마다 확률 c로 요청.
    host: None이면 요청마다 DMA 1회(d_in·d_out). 숫자 W_h(µs)면 Host가 W_h마다 그사이 생긴 입력을 모아
          H2C 1회(지연 = 1 ms 주기 실측 표본 + (크기 − 64 B) / H2C_BW)로 보내고, 결과도 W_h마다 C2H 1회로 읽는다.
    spike: True면 요청별 연산 시간을 golden spike 수로 정한다(spike_cost). configure 뒤에 불러야 한다."""
    rng = np.random.default_rng(seed)
    if track_model is not None:
        tm = np.asarray(track_model)
    elif dist == 'zipf':
        tm = rng.choice(M, n_tracks, p=ZIPF)
    else:
        tm = rng.integers(0, M, n_tracks)
    offs = rng.uniform(0, P, n_tracks) if offset is None else np.broadcast_to(np.asarray(offset, float), (n_tracks,)).copy()
    k = np.arange(warm + meas)
    t_gen = (offs[:, None] + P * k[None, :]).ravel()
    model = np.repeat(tm, warm + meas)
    trk = np.repeat(np.arange(n_tracks), warm + meas)
    n = t_gen.size
    di = rng.choice(load_samples(D_IN_FILE), n) if d_in is None else np.full(n, float(d_in))
    do = rng.choice(load_samples(D_OUT_FILE), n) if d_out is None else np.full(n, float(d_out))
    t_arr = t_gen + d_host + di
    cost = spike_cost(tm, k, seed) if spike else None
    if p_req < 1.0:                                   # 다른 난수열에 영향을 주지 않도록 별도 생성기
        keep = np.random.default_rng(seed + 7777).random(n) < p_req
        t_gen, t_arr, model, do, trk = t_gen[keep], t_arr[keep], model[keep], do[keep], trk[keep]
        cost = None if cost is None else cost[keep]
    if congestion is not None:
        r2 = np.random.default_rng(seed + 8888)
        c = r2.uniform(*congestion, warm + meas)
        keep = r2.random(t_gen.size) < np.tile(c, n_tracks)
        t_gen, t_arr, model, do, trk = t_gen[keep], t_arr[keep], model[keep], do[keep], trk[keep]
        cost = None if cost is None else cost[keep]
    extra = {}
    if host:
        r3 = np.random.default_rng(seed + 9999)
        phi_in, phi_out = r3.uniform(0, host, 2)
        tick = np.ceil((t_gen - phi_in) / host)
        u, inv, cnt = np.unique(tick, return_inverse=True, return_counts=True)
        lat = r3.choice(load_samples(H_IN_FILE), u.size) + np.maximum(0, cnt * IN_B - 64) / H2C_BW
        t_arr = phi_in + tick * host + d_host + lat[inv]
        n_out = int((warm + meas + 4) * P / host) + 2
        extra = dict(out_w=float(host), out_phi=float(phi_out),
                     out_lat=r3.choice(load_samples(H_OUT_FILE), n_out))
    o = np.argsort(t_arr, kind='stable')
    return Workload(n_tracks, seed, tm, t_gen[o], t_arr[o], model[o], do[o], warm * P, (warm + meas) * P, **extra,
                    cost=None if cost is None else cost[o], track=trk[o])


# ---- 준비된 요청 집합 ---------------------------------------------------------
class Ready:
    """도착했고 아직 batch에 들어가지 않은 요청. 도착 순서·deadline 순서·모델별 목록을 함께 유지"""

    def __init__(self, wl):
        self.wl = wl
        self.n = wl.t_arr.size
        self.nxt = 0                       # 아직 도착하지 않은 첫 요청
        self.served = np.zeros(self.n, bool)
        self.head = 0                      # 도착 순서상 가장 오래된 미처리 요청 후보
        self.heap = []                     # (t_gen, idx)
        self.by_model = [[] for _ in range(M)]
        self.count = 0

    def advance(self, now):
        wl = self.wl
        while self.nxt < self.n and wl.t_arr[self.nxt] <= now:
            i = self.nxt
            heapq.heappush(self.heap, (wl.t_gen[i], i))
            self.by_model[wl.model[i]].append(i)
            self.count += 1
            self.nxt += 1

    def next_arrival(self):
        return self.wl.t_arr[self.nxt] if self.nxt < self.n else None

    def oldest(self):
        while self.head < self.nxt and self.served[self.head]:
            self.head += 1
        return self.head if self.head < self.nxt else None

    def earliest(self):
        while self.heap and self.served[self.heap[0][1]]:
            heapq.heappop(self.heap)
        return self.heap[0][1] if self.heap else None

    def take(self, m, idx):
        self.served[idx] = True
        lst, n = self.by_model[m], len(idx)
        if all(self.served[i] for i in lst[:n]):           # 앞쪽부터 가져간 경우가 대부분
            self.by_model[m] = lst[n:]
        else:
            self.by_model[m] = [i for i in lst if not self.served[i]]
        self.count -= n


# ---- 실행 --------------------------------------------------------------------
def simulate(wl, storage, scheduler, compute, stop_on_miss=False, detail=False):
    """stop_on_miss: 측정 구간 요청이 하나라도 deadline을 넘으면 즉시 {'miss': 1}을 돌려준다(최대 트랙 탐색용)
    detail: compute array의 cycle 회계(연산·정지·유휴)와 응답 시간 분해를 지표에 더한다(cycle_stats)"""
    storage.reset(wl)
    scheduler.reset()
    compute.reset()
    compute.log = [] if detail else None
    rd = Ready(wl)
    finish = np.full(wl.t_arr.size, np.nan)
    bat_k, bat_s, bat_b, bat_hit, bat_x, bat_m = [], [], [], [], [], []
    compute.mem = None
    dropped = []
    T = 0.0
    while True:
        rd.advance(T)
        if rd.count == 0:
            na = rd.next_arrival()
            if na is None:
                break
            T = max(T, na)
            rd.advance(T)
        if hasattr(scheduler, 'busy_until'):           # 점수2·3의 deadline guard: 진행 중인 batch가 끝나는 시각
            scheduler.busy_until = getattr(compute, 'cmp_free', T)
        m, head = scheduler.pick(rd, T, storage)
        if getattr(scheduler, 'drops', None):          # 원문이 버리는 정책(P3.11): pick이 queue에서 뺀 요청. 결과 없음 = miss
            dropped += scheduler.drops
            if stop_on_miss and (wl.t_gen[scheduler.drops] >= wl.w0).any():
                return {'miss': 1, 'early': True}
            scheduler.drops = []
        if m is None:                                   # scheduler가 일부러 기다림(점수3): head = 다시 고를 시각
            T = max(head, T)
            continue
        if hasattr(storage, 'rd'):                     # 다음 사용 기준 교체(P3.11)가 대기열과 시각을 본다
            storage.rd, storage.now = rd, T
        loads = storage.plan(m)
        taken = []

        def members(s, m=m, head=head):
            rd.advance(s)
            idx = scheduler.members(rd, m, head, s)
            cap = compute.max_batch()
            if cap and len(idx) > cap:                     # membrane potential 버퍼 한도: deadline 순서로 자름
                idx = sorted(idx, key=lambda i: wl.t_gen[i])[:cap]
            rd.take(m, idx)
            taken.extend(idx)
            if wl.mem_addr is not None:                    # 트랙별 membrane potential: DDR3 트랙 수, DMA 횟수(자리가 이어진 트랙은 읽기·쓰기 한 번씩)
                a = np.sort(wl.mem_addr[wl.track[idx]])
                a = a[a >= 0]
                compute.mem = (a.size, 2 * (1 + int((np.diff(a) != 1).sum())) if a.size else 0)
            return len(idx), (None if wl.cost is None else wl.cost[idx])

        s, fin = compute.run(T, loads, storage.uses_entry, members)
        finish[taken] = fin
        if stop_on_miss:
            tk = np.asarray(taken)
            late = (wl.done(fin, tk) - wl.t_gen[tk] > P) & (wl.t_gen[tk] >= wl.w0)
            if late.any():
                return {'miss': 1, 'early': True}
        bat_k.append(len(taken))
        bat_s.append(s)
        bat_b.append(sum(loads))
        bat_x.append(compute.xfers(loads))             # 이 batch의 weight DMA 횟수
        bat_m.append(compute.mem or (len(taken), 0))   # (membrane potential을 DDR3에서 읽고 쓴 요청 수, membrane potential DMA 횟수)
        bat_hit.append(sum(loads) == 0)
        T = s
    dr = np.array(dropped, int)
    finish[dr] = wl.t_gen[dr] + 2 * P                  # drop: 결과가 오지 않으므로 응답 시간 2주기로 적어 miss로 센다
    res = metrics(wl, finish, np.array(bat_k), np.array(bat_s), np.array(bat_b), np.array(bat_hit),
                  compute, np.array(bat_x), np.array(bat_m).reshape(-1, 2))
    res['drop'] = int((wl.t_gen[dr] >= wl.w0).sum())
    if detail:
        finish[dr] = wl.t_arr[dr]                      # cycle 회계에서는 FPGA에 머문 시간 0
        win = (np.array(bat_s) >= wl.w0) & (np.array(bat_s) < wl.w1)
        res.update(cycle_stats(wl, finish, compute.log, int(np.array(bat_k)[win].sum())))
    return res


def _union(s, e):
    """구간 [s_i, e_i)들의 합집합 길이"""
    keep = e > s
    s, e = s[keep], e[keep]
    if not s.size:
        return 0.0
    o = np.argsort(s, kind='stable')
    s, e = s[o], e[o]
    cm = np.maximum.accumulate(e)
    idx = np.flatnonzero(np.r_[True, s[1:] > cm[:-1]])        # 앞 구간들과 겹치지 않고 새로 시작하는 구간
    ends = np.r_[cm[idx[1:] - 1], cm[-1]]
    return float((ends - s[idx]).sum())


def cycle_stats(wl, finish, busy, n_win):
    """측정 구간의 compute array cycle 회계(100 MHz)와 응답 시간 분해.
      연산 = compute array가 batch를 계산한 cycle(제어 비용 10 % 포함)
      정지 = FPGA에 도착한 요청이 남아 있는데 compute array가 쉰 cycle(weight·membrane potential DMA 대기)
      유휴 = FPGA 안에 처리할 요청이 없는 cycle.  연산 + 정지 + 유휴 = 측정 구간
    응답 시간 = 입력(생성 → FPGA 도착: Host batch 대기 + H2C) + FPGA(도착 → 연산 완료: queue 대기 + DMA 대기 + 연산)
              + 출력(연산 완료 → 결과가 Host에 도착: 결과 읽기 대기 + C2H)"""
    w0, w1 = wl.w0, wl.w1
    b = np.asarray(busy, float).reshape(-1, 2)
    busy_t = float((np.clip(b[:, 1], w0, w1) - np.clip(b[:, 0], w0, w1)).sum())
    active = _union(np.clip(wl.t_arr, w0, w1), np.clip(finish, w0, w1))
    sel = wl.t_gen >= w0
    done = wl.done(finish, np.arange(finish.size))
    per_us = 1.0 / CLK
    return {
        'cyc_busy': busy_t * per_us,
        'cyc_stall': (active - busy_t) * per_us,
        'cyc_idle': (w1 - w0 - active) * per_us,
        'cyc_n': n_win,                                         # 측정 구간에 연산을 시작한 요청 수(요청당 cycle의 분모)
        'in_ms': float((wl.t_arr - wl.t_gen)[sel].mean() / 1000),
        'fpga_ms': float((finish - wl.t_arr)[sel].mean() / 1000),
        'out_ms': float((done - finish)[sel].mean() / 1000),
    }


def metrics(wl, finish, k, s, b, hit, compute, x=None, mem=None):
    resp = wl.done(finish, np.arange(finish.size)) - wl.t_gen
    sel = wl.t_gen >= wl.w0
    r = resp[sel]
    win = (s >= wl.w0) & (s < wl.w1)
    span = wl.w1 - wl.w0
    mk, mx = (k, 0 * k) if mem is None else (mem[:, 0], mem[:, 1])     # membrane potential을 DDR3에서 읽고 쓴 요청 수, membrane potential DMA 횟수
    return {
        'n_req': int(sel.sum()),
        'miss': int((r > P).sum()),
        'miss_rate': float((r > P).mean()),
        'mbps': float(b[win].sum() / span),                    # B/µs = MB/s
        'p50_ms': float(np.percentile(r, 50) / 1000),
        'p99_ms': float(np.percentile(r, 99) / 1000),
        'max_ms': float(r.max() / 1000),
        'mean_ms': float(r.mean() / 1000),
        # 측정 구간에 연산을 시작한 batch 기준 DDR3 사용량 (에너지·접근 횟수 비교용)
        'req_win': int(k[win].sum()),
        'w_bytes': float(b[win].sum()),                        # weight 읽기 B
        'm_bytes': float(mk[win].sum() * MEM_B),               # membrane potential 읽기 + 쓰기 B
        'w_xfers': int(x[win].sum()) if x is not None else 0,  # weight DMA 횟수
        'm_xfers': int(mx[win].sum()),                         # membrane potential DMA 횟수(트랙별 membrane potential일 때만 셈)
        'batch_mean': float(k[win].mean()),
        'hit_rate': float(hit[win].mean()),
        'dma_util': float((b[win].sum() / BW + mem_time(mk[win].sum()) + mx[win].sum() * T0) / span),
        'cmp_util': float(k[win].sum() * C_REQ / span),
        'resp': r,                                             # 실행기가 seed 합산 후 지운다
    }


# ==== 3. 부품: 저장 정책·연산 방식·scheduler ========================================
# 옛 policies.py. P3.6~P3.8 후보 부품 9개 (저장 정책 3, scheduler 4, 연산 방식 2)
#
# 같은 종류의 부품은 같은 질문에 답하는 같은 메서드를 가진다. simulate()는 부품 종류만
# 알고 구체적인 후보는 모른다. 후보를 늘리려면 클래스 하나를 만들어 아래 목록에 넣는다.
#
#   저장 정책  plan(m)  → 뉴런 그룹마다 DDR3에서 가져올 바이트 (0 = on-chip에 있음), cache 상태 갱신
#              peek(m)  → plan과 같은 총 바이트, 상태는 바꾸지 않음 (점수 scheduler용)
#              tiles()  → on-chip BRAM 타일
#   scheduler  pick(rd, T, storage)     → (다음 모델, 기준 요청)
#              members(rd, m, head, s)  → 연산 시작 시각 s에 batch에 넣을 요청 목록
#   연산 방식  run(T, loads, uses_entry, members) → (첫 연산 시작 시각, 요청별 연산 완료 시각)
#              extra_tiles(storage) → 적재 버퍼 타일, max_batch() → batch 한도(None = 없음)
#
# 레인 수·트랙 수에 따라 바뀌는 상수(그룹, 타일 등)는 configure()가 정하므로 sc.이름(sc = 이 모듈)으로 읽는다.

# ---- 저장 정책 ----------------------------------------------------------------
class _LRU:
    def __init__(self, n):
        self.n, self.d = n, OrderedDict()

    def hit(self, m):
        return m in self.d

    def use(self, m):
        """m을 넣거나 갱신. 진행 중인 batch의 모델은 항상 가장 최근이므로 교체 대상이 되지 않는다"""
        if m in self.d:
            self.d.move_to_end(m)
            return True
        if len(self.d) >= self.n:
            self.d.popitem(last=False)
        self.d[m] = True
        return False


class FullCache:
    """A. 모델 entry E벌(weight + β·vth), LRU. miss면 모델 전체를 가져와 entry에 저장.
    E 기본값은 예산에 들어가는 최대값(기준 환경 5벌)"""
    name, uses_entry = 'A.전체cache', True

    buf_words, buf_extra = 0, 0.0

    def __init__(self, entries=None, budget=None, compute=None):
        budget = sc.TILE_BUDGET - sc.MEMBUF_T if budget is None else budget
        self.E = entries or max(0, int(budget // sc.ENTRY_T))

    def tiles(self):
        return self.E * sc.ENTRY_T

    def reset(self, wl):
        self.lru = _LRU(self.E)

    def peek(self, m):
        return 0 if self.lru.hit(m) else sum(sc.FULL)

    def plan(self, m):
        return sc.ZERO if self.lru.use(m) else sc.FULL


class PinLRU(FullCache):
    """E. 인기 고정(P3.11 비교): Ogden 외(ACSOS'21)의 utility 교체를 크기·적재 시간이 같은 모델에 적용하면 인기(트랙 수)가 낮은
    모델부터 내보내는 규칙이 된다. entry E벌 중 E − 2벌은 트랙이 가장 많은 모델에 고정하고 2벌은 LRU로 돌린다(적재·연산 겹침).
    고정 모델의 첫 적재는 warm-up에 들어간다고 보고 뺀다. guard는 회전 entry hit를 믿지 않는다(peek은 고정 모델만 0)"""
    name = 'E.인기고정'

    def reset(self, wl):
        order = np.argsort(-np.bincount(wl.track_model, minlength=M), kind='stable')
        self.pin = set(order[:self.E - 2].tolist())
        self.rot = _LRU(2)

    def peek(self, m):
        return 0 if m in self.pin else sum(sc.FULL)

    def plan(self, m):
        if m in self.pin:
            return sc.ZERO
        return sc.ZERO if self.rot.use(m) else sc.FULL


class FurthestNext(FullCache):
    """F. 다음 사용 기준 교체(P3.11 비교): RT-Swap(RTAS'24 §V-C)의 '다음 job 방출이 가장 늦은 task부터 내보냄'을 모델 entry에
    옮긴 것. miss면 지금 연산 중인 모델(가장 최근)을 뺀 entry 중 다음 사용이 가장 늦은 모델을 내보낸다.
    다음 사용 = 그 모델의 아직 처리하지 않은 요청(대기 중이거나 아직 오지 않은) 중 가장 이른 생성 시각.
    트랙 주기와 offset은 Host가 알므로 예측할 수 있다고 본다(가정). guard는 hit를 믿지 않는다(peek = 전체 적재)"""
    name = 'F.다음사용'
    rd = now = None                  # simulate가 plan 직전에 넣는다

    def reset(self, wl):
        self.wl, self.d = wl, OrderedDict()                 # 적재된 모델, 뒤 = 가장 최근
        self.fut = [(wl.t_arr[i], wl.t_gen[i]) for i in (np.flatnonzero(wl.model == m) for m in range(M))]

    def peek(self, m):
        return sum(sc.FULL)

    def _next(self, e):
        tg = self.wl.t_gen
        a, g = self.fut[e]
        j = np.searchsorted(a, self.now, side='right')
        return min(min((tg[i] for i in self.rd.by_model[e]), default=float('inf')), g[j] if j < a.size else float('inf'))

    def plan(self, m):
        if m in self.d:
            self.d.move_to_end(m)
            return sc.ZERO
        if len(self.d) >= self.E:
            cur = next(reversed(self.d))
            del self.d[max((e for e in self.d if e != cur), key=self._next)]
        self.d[m] = True
        return sc.FULL


class OffsetNext(FurthestNext):
    """G. offset 예측 다음 사용(P3.12): F.다음사용과 같은 교체 규칙이지만 아직 오지 않은 요청은 트랙 offset(주기 P)으로만 예측한다.
    어떤 트랙이 이번 주기를 건너뛸지(I·R)는 모른다. 적재된 모델은 peek = 0(scheduler가 hit를 본다)"""
    name = 'G.offset-order'

    def reset(self, wl):
        super().reset(wl)
        # 모델별 트랙 offset. 외부 지연만큼 옮겨 도착 시각으로 예측한다(HW offset 순서 표는 이 지연과 무관)
        self.offs = [np.unique(np.round((wl.t_gen[wl.model == m] + wl.pre) % P, 6)) for m in range(M)]

    def peek(self, m):
        return 0 if m in self.d else sum(sc.FULL)

    def _next(self, e):
        lst = self.rd.by_model[e]
        if lst:
            return min(self.wl.t_gen[i] for i in lst)
        offs = self.offs[e]
        if not offs.size:
            return float('inf')
        j = np.searchsorted(offs, self.now % P, side='right')
        return self.now - self.now % P + (offs[j] if j < offs.size else offs[0] + P)


class L1Resident:
    """B. 40모델의 L1 weight와 β·vth 상주. 매 batch마다 L2~L4를 가져온다(보관하지 않음)"""
    name, uses_entry = 'B.L1상주', False
    buf_extra = 0.0                    # β·vth는 40모델분 상주

    def __init__(self, budget=None):
        self.buf_words = sc.L2L4_WORDS

    def tiles(self):
        return tiles(M * sc.L1_WORDS, 8 * sc.WORD) + tiles(M * sc.NEU, 16)

    def reset(self, wl):
        pass

    def peek(self, m):
        return sum(sc.L2L4)

    def plan(self, m):
        return sc.L2L4


class Hybrid:
    """C. entry E벌(LRU) + 트랙이 많은 R개 모델의 L1·β·vth 상주. E 기본값은 A의 절반(올림, 기준 환경 3벌),
    R은 남은 예산에 들어가는 최대값. miss면 L1 상주 모델은 L2~L4만, 나머지는 전체를 가져와 entry에 저장"""
    name, uses_entry = 'C.혼합', True

    buf_words, buf_extra = 0, 0.0

    def __init__(self, entries=None, n_l1=None, budget=None):
        budget = sc.TILE_BUDGET - sc.MEMBUF_T if budget is None else budget
        self.E = entries or -(-max(0, int(budget // sc.ENTRY_T)) // 2)
        if n_l1 is None:
            room = budget - self.E * sc.ENTRY_T                   # entry 적재라 별도 버퍼 없음
            n_l1 = max([r for r in range(M + 1) if self._l1_tiles(r) <= room], default=0)
        self.R = n_l1

    @staticmethod
    def _l1_tiles(r):
        return tiles(r * sc.L1_WORDS, 8 * sc.WORD) + tiles(r * sc.NEU, 16) if r else 0

    def tiles(self):
        return self.E * sc.ENTRY_T + self._l1_tiles(self.R)

    def reset(self, wl):
        self.lru = _LRU(self.E)
        cnt = np.bincount(wl.track_model, minlength=M)
        self.l1 = set(np.argsort(-cnt, kind='stable')[:self.R].tolist())

    def peek(self, m):
        if self.lru.hit(m):
            return 0
        return sum(sc.L2L4) if m in self.l1 else sum(sc.FULL)

    def plan(self, m):
        if self.lru.use(m):
            return sc.ZERO
        return sc.L2L4 if m in self.l1 else sc.FULL


class Stream:
    """D. weight를 on-chip에 보관하지 않고 매 batch 모델 전체를 DDR3에서 흘려 받는다.
    weight BRAM을 최소로 써서 membrane potential(트랙) 자리를 최대로 남기는 메모리 접근 방식"""
    name, uses_entry = 'D.스트림', False

    def __init__(self, budget=None, compute=None):
        self.buf_words = sc.WORDS
        self.buf_extra = tiles(sc.NEU, 16)   # batch 동안 쓸 β·vth (L 706 × 16 bit = 0.5 타일)

    def tiles(self):
        return 0.0

    def reset(self, wl):
        pass

    def peek(self, m):
        return sum(sc.FULL)

    def plan(self, m):
        return sc.FULL


def _fits(st, compute, limit=None):
    return st.tiles() + compute.extra_tiles(st) <= (sc.TILE_BUDGET if limit is None else limit)


def _limit(budget, compute):
    """B·C 크기를 정할 BRAM 한도. build가 넘긴 budget(예약분·membrane potential 버퍼를 뺀 값)이 있으면 그것을 쓴다(P3.11)"""
    return None if budget is None else budget + compute.mem_tiles()


class PartialAll:
    """B(예산 맞춤). 40모델 모두의 앞쪽 뉴런 그룹 k개를 상주시키고 나머지 그룹은 매 batch 가져온다(보관하지 않음).
    k는 연산 방식의 적재 버퍼까지 넣어 예산에 들어가는 최대값이다. 남는 예산에 40모델 β·vth가 들어가면 상주시키고,
    아니면 모델과 함께 가져온다. L 32레인 기준 환경에서는 k = layer 1 전체(12그룹) + β·vth 상주라 B.L1상주와 같다.
    XL 256레인에서는 layer 1 전체(3그룹)가 들어가지 않아(418~457 타일) k가 더 작아진다"""
    name, uses_entry = 'B.부분상주', False

    def __init__(self, budget=None, compute=None):
        lim = _limit(budget, compute)
        for k in range(sc.N_L1, -1, -1):
            for bv in (True, False):
                self._set(k, bv)
                if _fits(self, compute, lim):
                    return

    def _set(self, k, bv):
        self.k, self.bv = k, bv
        self.res_words = sum(w for _, w in sc.GROUPS[:k])
        self.buf_words = sc.WORDS - self.res_words              # 한 번에: 상주하지 않는 부분의 적재 버퍼
        self.buf_extra = 0.0 if bv else tiles(sc.NEU, 16)       # β·vth를 가져오면 모델 1개분 버퍼
        loads = [0] * k + list(sc.G_BYTES[k:])
        if not bv:
            loads[k] += sc.PARAM_B                              # β·vth는 첫 적재 그룹에 붙임
        self.loads = loads

    def tiles(self):
        return ((tiles(M * self.res_words, 8 * sc.WORD) if self.res_words else 0.0)
                + (tiles(M * sc.NEU, 16) if self.bv else 0.0))

    def reset(self, wl):
        pass

    def peek(self, m):
        return sum(self.loads)

    def plan(self, m):
        return self.loads


class PinnedHybrid:
    """C(예산 맞춤). 혼합 = weight cache + 부분 상주. 트랙이 가장 많은 E개 모델을 entry에 고정하고(교체 없음),
    다음으로 트랙이 많은 R개 모델의 layer 1·β·vth를 상주시킨다. 나머지 모델은 매 batch 전체를 가져온다(보관하지 않음).
    E = A entry 수의 절반(올림), R = 남은 예산 최대(C.혼합과 같은 규칙).
    C.혼합은 entry를 LRU로 교체하고 miss를 entry에 적재한다. XL 256레인에서는 E = 1이라 교체하면 연산 중인 entry에
    적재할 수 없다(dse.build가 배치 불가로 보던 이유). 그래서 entry를 고정하고, 나머지는 스트림 경로(한 번에: 모델 1개
    적재 버퍼, 한 줄씩: 슬라이스 이중 버퍼)로 받는다"""
    name, uses_entry = 'C.고정혼합', False

    def __init__(self, budget=None, compute=None):
        self.lim = _limit(budget, compute)
        e_a = int(((sc.TILE_BUDGET if self.lim is None else self.lim) - compute.mem_tiles()) // sc.ENTRY_T)
        self.E = -(-e_a // 2)
        self.buf_words, self.buf_extra = sc.WORDS, tiles(sc.NEU, 16)
        while True:
            fit = [r for r in range(M - self.E + 1) if self._try(r, compute)]
            if fit or self.E == 0:
                self.R = max(fit, default=0)
                return
            self.E -= 1

    def _try(self, r, compute):
        self.R = r
        return _fits(self, compute, self.lim)

    @staticmethod
    def _l1_tiles(r):
        return tiles(r * sc.L1_WORDS, 8 * sc.WORD) + tiles(r * sc.NEU, 16) if r else 0.0

    def tiles(self):
        return self.E * sc.ENTRY_T + self._l1_tiles(self.R)

    def reset(self, wl):
        order = np.argsort(-np.bincount(wl.track_model, minlength=M), kind='stable').tolist()
        self.pinned = set(order[:self.E])
        self.l1 = set(order[self.E:self.E + self.R])

    def plan(self, m):
        if m in self.pinned:
            return sc.ZERO
        return sc.L2L4 if m in self.l1 else sc.FULL

    def peek(self, m):
        return sum(self.plan(m))


# ---- scheduler ------------------------------------------------------------------
class FCFS:
    """도착 순서. 가장 오래된 요청과 그 뒤로 이어지는 같은 모델 요청을 묶는다"""
    name = 'FCFS'

    def reset(self):
        pass

    def pick(self, rd, T, st):
        h = rd.oldest()
        return int(rd.wl.model[h]), h

    def members(self, rd, m, head, s):
        model, out, i = rd.wl.model, [], head
        while i < rd.nxt:
            if not rd.served[i]:
                if model[i] != m:
                    break
                out.append(i)
            i += 1
        return out


class EDF:
    """deadline 순서. deadline이 가장 이른 요청과 deadline 순서로 이어지는 같은 모델 요청을 묶는다"""
    name = 'EDF'

    def reset(self):
        pass

    def pick(self, rd, T, st):
        e = rd.earliest()
        return int(rd.wl.model[e]), e

    def members(self, rd, m, head, s):
        model, key0 = rd.wl.model, (rd.wl.t_gen[head], head)
        out, back = [], []
        while rd.heap:
            item = heapq.heappop(rd.heap)
            i = item[1]
            if rd.served[i]:
                continue
            if model[i] == m:
                out.append(i)
            elif item < key0:              # 기준 요청보다 deadline이 이른 다른 모델(선택 뒤 도착) → 건너뜀
                back.append(item)
            else:
                back.append(item)
                break
        for item in back:
            heapq.heappush(rd.heap, item)
        return out


class Grouping:
    """가장 오래 기다린 요청의 모델을 골라 그 모델의 준비된 요청을 모두 묶는다"""
    name = '그룹핑'

    def reset(self):
        pass

    def pick(self, rd, T, st):
        h = rd.oldest()
        return int(rd.wl.model[h]), h

    def members(self, rd, m, head, s):
        return list(rd.by_model[m])


class Score:
    """deadline 여유 < T_urgent인 요청이 있으면 그 요청의 모델. 아니면
    점수 = n ÷ (남은 전송 시간 + n × 요청당 연산), n = min(준비된 요청 수, K) 최대 모델.
    batch는 그 모델의 요청을 deadline 순서로 최대 K개"""
    name = '점수'

    def __init__(self, t_urgent=4000.0, k=16):
        self.tu, self.K = t_urgent, k

    def reset(self):
        pass

    def pick(self, rd, T, st):
        e = rd.earliest()
        tg = rd.wl.t_gen
        if tg[e] + P - T < self.tu:
            return int(rd.wl.model[e]), e
        best = None
        for m in range(M):
            lst = rd.by_model[m]
            if not lst:
                continue
            n = min(len(lst), self.K)
            score = round(n / (xfer_time(st.peek(m)) + n * sc.C_REQ), 12)
            key = (score, n, -tg[lst[0]])
            if best is None or key > best[0]:
                best = (key, m, lst[0])
        return best[1], best[2]

    def members(self, rd, m, head, s):
        tg = rd.wl.t_gen
        return sorted(rd.by_model[m], key=lambda i: tg[i])[:self.K]


class ScoreNoCap(Score):
    """비교용: 점수 초안에서 batch 상한 K만 없앤 것(긴급 기준 4 ms는 그대로)"""
    name = '점수(상한 없음)'

    def __init__(self, t_urgent=4000.0):
        super().__init__(t_urgent, k=10 ** 9)


class ScoreGuard:
    """점수2: 효율이 가장 큰 모델을 먼저 처리하되, deadline guard를 통과할 때만 고른다.
      효율 = n ÷ batch 시간, n = 그 모델의 준비된 요청 수(상한 없음, 하드웨어 한도는 연산 방식이 자른다)
      batch 시간 = 남은 weight 전송 + membrane potential DMA + n × 요청당 연산(직렬 합, 보수적). batch 한도를 넘으면 적재를 그만큼 더한다.
                  overlap=True(겹친다고 보고 max)는 조정 seed에서 K·R 시나리오 deadline miss가 나서 기본으로 쓰지 않는다
      deadline guard = compute array가 비는 시각(busy_until, 진행 중인 batch의 끝)부터 그 모델을 먼저, 나머지 모델을 deadline 순서(EDF)로
                  처리한다고 할 때 모든 모델의 가장 이른 deadline이 '완료 + 결과 회수 여유(margin)' 안에 드는가.
                  들지 않으면 deadline이 가장 이른 모델을 고른다(그룹핑과 같아짐).
    wait(점수3, Channel Window): EDF 순서로 처리해도 되는 가장 늦은 시작 시각 LS를 구해, LS − slack까지 여유가 있으면
      다음 도착(또는 LS − slack)까지 일부러 기다려 같은 모델 요청을 더 모은다. 기다리는 동안 새 요청이 오면 다시 판단한다.
    전송 비용은 batch 시간에 한 번만 들어간다(별도 벌점 없음). 미래 도착은 모른다."""
    name = '점수2'
    busy_until = 0.0                 # simulate가 결정마다 compute array가 비는 시각을 넣는다
    cap = None                       # 연산 방식의 batch 한도(target_exp.build가 넣음)

    order = 'eff'                    # 'eff' 효율 우선(guard), 'edf' 항상 deadline이 가장 이른 모델
    max_wait = None                  # 시간제한 batch: 가장 오래된 요청이 이만큼(µs) 기다리면 더 기다리지 않음
    next_arr = None                  # HW 대기 규칙(ARCH_SPEC §7.3): 숫자면 다음 도착 대신 T + next_arr(µs)로 판단
    slack_ratio = 0.0                # guard 비례 여유 α: 남은 일 예상 시간 × (1 + α). guard가 모르는 비용 오차를 덮는다
    cache_aware = False              # True면 guard가 LRU 교체를 따라가며 적재 시간을 정한다(_cache_walk, 전체 cache만)
    robust = False                   # True면 target_exp.build가 결과 회수 여유에 PCIe 실측 worst case를 넣는다

    def __init__(self, margin=1150.0, overlap=False, wait=False, slack=4000.0):
        self.margin, self.overlap, self.wait, self.slack = margin, overlap, wait, slack

    def reset(self):
        self.busy_until = 0.0

    def _bt(self, x, n):
        k = -(-n // self.cap) if self.cap else 1         # batch 한도(한 줄씩 64)를 넘으면 모델을 그만큼 다시 적재
        dma, cmp_ = k * x + mem_time(n), n * sc.C_REQ
        return max(dma, cmp_) if self.overlap else dma + cmp_

    def pick(self, rd, T, st):
        tg = rd.wl.t_gen
        cand = []                                          # (가장 이른 deadline, 모델, n, 남은 전송 시간)
        for m in range(M):
            lst = rd.by_model[m]
            if lst:
                cand.append((min(tg[i] for i in lst) + P, m, len(lst), xfer_time(st.peek(m))))
        cand.sort()
        if self.cache_aware and hasattr(st, 'lru'):
            cand = self._cache_walk(cand, st)
        t0 = max(T, self.busy_until)
        if self.wait:                                      # 다음 도착 뒤에 시작해도 LS까지 slack 이상 남으면 기다린다
            until = rd.next_arrival()
            if self.max_wait is not None:                  # 시간제한: 가장 오래된 요청이 max_wait에 닿으면 그만 기다림
                rel = cand[0][0] - P + self.max_wait
                until = None if T >= rel else (rel if until is None else min(until, rel))
            if self.next_arr is not None:                  # HW 규칙: 다음 도착 시각을 모르므로 T + next_arr로 본다
                ls = self._latest_start(cand) - self.slack - self.next_arr
                if T < ls:
                    return None, ls if until is None else min(until, ls)
            elif until is not None and until < self._latest_start(cand) - self.slack:
                return None, until
        if self.order == 'edf':
            m = cand[0][1]
            return m, rd.by_model[m][0]
        best = max(cand, key=lambda c: (round(c[2] / self._bt(c[3], c[2]), 12), c[2], -c[0]))
        m = best[1] if best[1] != cand[0][1] and self._safe(best, cand, t0) else cand[0][1]
        return m, rd.by_model[m][0]

    @staticmethod
    def _cache_walk(cand, st):
        """deadline 순서로 처리한다고 보고 LRU를 따라가며 모델마다 남은 전송 시간을 다시 정한다.
        앞 모델의 적재가 뒤 모델을 밀어내면 뒤 모델도 전체 전송으로 본다(ARCH_SPEC §7.4)"""
        lru, full, out = list(st.lru.d), xfer_time(sum(sc.FULL)), []    # lru 앞 = 가장 오래 안 쓴 모델
        for d, m, n, x in cand:
            if m in lru:
                lru.remove(m)
                x = 0.0
            else:
                x = full
                if len(lru) >= st.lru.n:
                    lru.pop(0)
            lru.append(m)
            out.append((d, m, n, x))
        return out

    def _latest_start(self, cand):
        """EDF 순서로 이어서 처리할 때 모든 deadline을 지키는 가장 늦은 시작 시각"""
        t, ls = 0.0, float('inf')
        for d, m, n, x in cand:
            t += self._bt(x, n)
            ls = min(ls, d - self.margin - t * (1 + self.slack_ratio))
        return ls

    def _safe(self, first, cand, t0):
        t = t0 + self._bt(first[3], first[2])
        if t + self.margin > first[0]:
            return False
        for d, m, n, x in cand:
            if m != first[1]:
                t += self._bt(x, n)
                if t + self.margin > d:
                    return False
        return True

    def members(self, rd, m, head, s):
        tg = rd.wl.t_gen
        return sorted(rd.by_model[m], key=lambda i: tg[i])


class ScoreWait(ScoreGuard):
    """점수3 = 점수2 + deadline 여유 안에서 일부러 기다리기(Channel Window)"""
    name = '점수3'

    def __init__(self, margin=1150.0, overlap=False, slack=4000.0):
        super().__init__(margin, overlap, wait=True, slack=slack)


class LazyGroup(ScoreGuard):
    """지연 그룹핑: 처리 순서는 그룹핑처럼 deadline 순서(EDF) 그대로 두고, deadline guard가 허락하는 만큼만 기다려
    같은 모델 요청을 더 모은다. 점수3과 달리 효율 때문에 순서를 바꾸지 않는다.
    slack 안에서 일부러 기다리는 점은 Symphony·DeepRT와 같은 계열이다. LazyBatching(HPCA'21)은 기다리지 않는다(P3.11 정정)"""
    name = '지연 그룹핑'
    order = 'edf'

    def __init__(self, margin=1150.0, overlap=False, slack=4000.0):
        super().__init__(margin, overlap, wait=True, slack=slack)


class LazyGroupSimple(LazyGroup):
    """지연 그룹핑(간이 guard): 가장 늦은 시작 시각을 deadline 순 누적합 대신 합계 하나로 보수적으로 잡는다.
      LS = 가장 이른 deadline − 회수 여유 − (대기 중인 모든 모델의 batch 시간 합)
    deadline 순 누적합 guard의 모든 항보다 작거나 같으므로 더 일찍 기다림을 멈춘다(안전 쪽). 하드웨어는 대기 요청 수·대기 모델 수·
    남은 전송량의 누계와 가장 이른 deadline만 있으면 되어 정렬이 필요 없다"""
    name = '지연 그룹핑(간이 guard)'

    def _latest_start(self, cand):
        return cand[0][0] - self.margin - sum(self._bt(x, n) for d, m, n, x in cand) * (1 + self.slack_ratio)


class TimeoutBatch(LazyGroup):
    """시간제한 batch(Triton·Clipper의 동적 batching 대기 상한): 지연 그룹핑과 같되, 가장 오래된 요청이 max_wait(기본 8 ms)
    기다리면 더 기다리지 않는다. deadline 직전까지 끌지 않으므로 여유가 남는다. 몰림에서는 guard가 바로 처리시킨다"""
    name = '시간제한 batch 8'

    def __init__(self, margin=1150.0, overlap=False, slack=4000.0, max_wait=8000.0):
        super().__init__(margin, overlap, slack)
        self.max_wait = max_wait


class Dysta(ScoreGuard):
    """Dysta Method 점수(B03 Sparse-DySta의 정적 점수를 batch에 맞춤): 모델마다
      점수 = 요청당 잔여 처리 시간(batch 시간 ÷ n) + η × deadline 여유(가장 이른 deadline − 지금 − batch 시간 − 회수 여유)
    가 가장 작은 모델의 요청 전부. 첫 항은 짧고 전송을 나눠 쓰는 batch(cache hit, 큰 batch)를, 둘째 항은 급한 모델을 앞당긴다.
    η는 두 항의 비중이다. guard·대기 없음(원 논문도 점수만으로 순서를 정함). 선점 억제 항은 선점이 없으므로 뺐다"""
    name = 'Dysta Method'
    order = 'eff'

    def __init__(self, margin=1150.0, overlap=False, eta=0.01):
        super().__init__(margin, overlap)
        self.eta = eta

    def pick(self, rd, T, st):
        tg = rd.wl.t_gen
        t0 = max(T, self.busy_until)
        best = None
        for m in range(M):
            lst = rd.by_model[m]
            if lst:
                n, d = len(lst), min(tg[i] for i in lst) + P
                bt = self._bt(xfer_time(st.peek(m)), n)
                key = (bt / n + self.eta * (d - t0 - bt - self.margin), d)
                if best is None or key < best[0]:
                    best = (key, m)
        m = best[1]
        return m, rd.by_model[m][0]


class DystaReq(Dysta):
    """Dysta Method(요청 단위, P3.11 참고용): 원 논문(B03 Algorithm 2)처럼 요청 하나씩 점수를 매겨 하나만 처리한다. batch 없음.
      점수 = 남은 처리 시간 + η × (deadline 여유 + 벌점), 남은 처리 시간 = 남은 weight 전송 + membrane potential DMA + 요청당 연산,
      벌점 = 대기 시간 ÷ 단독 처리 시간 ÷ 대기 요청 수(원문 line 10). 선점·sparsity 예측은 없다.
    같은 모델 안에서는 남은 처리 시간이 같으므로 deadline이 가장 이른 요청만 본다(벌점 차이는 µs 단위 여유에 비해 무시)"""
    name = 'Dysta Method(요청 단위)'
    w = 1.0                          # 벌점 가중. 1e6이면 공식 코드(초 단위로 계산)와 같은 비중

    @property
    def cfg(self):
        return [self.eta, self.w]

    @cfg.setter
    def cfg(self, v):
        self.eta, self.w = v

    def pick(self, rd, T, st):
        tg, ta = rd.wl.t_gen, rd.wl.t_arr
        t0 = max(T, self.busy_until)
        iso = self._bt(xfer_time(sum(sc.FULL)), 1)
        best = None
        for m in range(M):
            lst = rd.by_model[m]
            if lst:
                i = min(lst, key=lambda j: tg[j])
                rem = self._bt(xfer_time(st.peek(m)), 1)
                key = (rem + self.eta * (tg[i] + P - t0 - rem - self.margin + self.w * (t0 - ta[i]) / iso / rd.count), tg[i])
                if best is None or key < best[0]:
                    best = (key, m, i)
        return best[1], best[2]

    def members(self, rd, m, head, s):
        return [head]


class _Serving(ScoreGuard):
    """P3.11 서빙 scheduler 공통(Clockwork·Symphony·Shepherd Method). 원문처럼 못 맞출 요청은 버린다(drop):
    지금 혼자 시작해도 deadline(회수 여유 포함)을 넘는 요청. simulate가 drops를 miss로 센다.
    batch는 맨 앞 요청 deadline을 지키는 가장 큰 batch(원문 GetBatch·BatchGen). batch 시간은 선형이라 k를 바로 구한다"""
    drops = ()

    def _u(self):
        return mem_time(1) + sc.C_REQ                     # 요청 하나를 더할 때 늘어나는 시간

    def _drop(self, rd, st, t0):
        tg, out = rd.wl.t_gen, []
        for m in range(M):
            if rd.by_model[m]:
                cut = t0 + self._bt(xfer_time(st.peek(m)), 1) + self.margin - P
                out += [i for i in rd.by_model[m] if tg[i] < cut]
        for i in out:
            rd.take(int(rd.wl.model[i]), [i])
        self.drops = out

    def _cands(self, rd, st, t0):
        """모델마다 (맨 앞 deadline − 회수 여유, batch k, 대기 n, 남은 적재 µs, 모델)"""
        tg, out = rd.wl.t_gen, []
        for m in range(M):
            lst = rd.by_model[m]
            if lst:
                d, x = min(tg[i] for i in lst) + P - self.margin, xfer_time(st.peek(m))
                k = max(1, min(len(lst), self.cap or len(lst), int((d - t0 - x) // self._u())))
                out.append((d, k, len(lst), x, m))
        return out

    def members(self, rd, m, head, s):
        q = sorted(rd.by_model[m], key=rd.wl.t_gen.__getitem__)
        d = rd.wl.t_gen[q[0]] + P - self.margin
        return q[:max(1, int((d - s) // self._u()))]      # 적재가 끝난 s에서 다시 정한다(Dispatch 때 UpdateCandidate)


class Clockwork(_Serving):
    """Clockwork Method(OSDI'20 §4.1·§5.3, P3.11): 못 맞출 요청은 버리고, batch의 가장 늦은 시작
    latest = 맨 앞 deadline − 회수 여유 − batch 시간이 가장 이른 모델을 바로 처리한다. 기다리지 않는다.
    variant 'A' = 원문처럼 적재된 모델만 INFER하고, 적재된 모델에 요청이 없으면 대기 일이 가장 많은 모델을 적재(LOAD 우선순위).
    'B' = 적재 시간을 batch 시간에 넣고 전체에서 latest 최소. 원문의 따로 도는 LOAD executor·batch 크기 집합 {1,2,4,8,16}은 없다"""
    name = 'Clockwork Method'
    variant = 'A'

    def pick(self, rd, T, st):
        t0 = max(T, self.busy_until)
        self._drop(rd, st, t0)
        c = [(d - self._bt(x, k), x == 0, n, m) for d, k, n, x, m in self._cands(rd, st, t0)]
        if not c:
            na = rd.next_arrival()
            return None, T if na is None else na
        hit = [a for a in c if a[1]]
        if self.variant == 'A':
            m = min(hit)[3] if hit else max(c, key=lambda a: (a[2], -a[0]))[3]
        else:
            m = min(c)[3]
        return m, rd.by_model[m][0]


class Symphony(_Serving):
    """Symphony Method(deferred batching, arXiv 2308.07470 Algorithm 1, P3.11): 모델마다 batch 후보의 시작 창을 둔다.
      latest = 맨 앞 deadline − 회수 여유 − batch 시간(k), exec(frontrun) = latest − 요청 하나 시간(하나 더 넣으면 못 맞춤)
    compute array가 비는 시각 t0에 exec ≤ t0인 후보 중 latest가 가장 이른 모델을 보낸다. 없으면 가장 이른 exec나 다음 도착까지
    기다린다. 원문은 GPU 여러 대의 엇갈린 실행으로 다른 모델을 보호한다. 가속기가 하나라 그 보호가 없다.
    slack(µs)은 exec를 그만큼 앞당기는 고정 여유다(원문 0, 공통 조정 대상)"""
    name = 'Symphony Method'

    def __init__(self, margin=1150.0, overlap=False, slack=0.0):
        super().__init__(margin, overlap, slack=slack)

    def pick(self, rd, T, st):
        t0 = max(T, self.busy_until)
        self._drop(rd, st, t0)
        ok, ex = None, float('inf')
        for d, k, n, x, m in self._cands(rd, st, t0):
            lt = d - self._bt(x, k)
            e = lt - self._u() - self.slack if k == n and k < (self.cap or n + 1) else -float('inf')
            if e <= t0:
                ok = min(ok or (lt, m), (lt, m))
            else:
                ex = min(ex, e)
        if ok:
            return ok[1], rd.by_model[ok[1]][0]
        na = rd.next_arrival()
        if ex == float('inf'):
            return None, T if na is None else na
        return None, ex if na is None else min(ex, na)


class ShepherdNP(_Serving):
    """Shepherd-NP Method(NSDI'23 Algorithm 2 BatchGen, 선점 없는 변형, P3.11): 모델마다 맨 앞 deadline을 지키는 가장 큰 batch를 만들고
    그중 가장 큰 batch의 모델을 바로 처리한다. 동률이면 맨 앞 deadline이 이른 모델. 기다리지 않는다. 선점(FLEX, λ)은 없다"""
    name = 'Shepherd Method'

    def pick(self, rd, T, st):
        t0 = max(T, self.busy_until)
        self._drop(rd, st, t0)
        c = self._cands(rd, st, t0)
        if not c:
            na = rd.next_arrival()
            return None, T if na is None else na
        m = max(c, key=lambda a: (a[1], -a[0]))[4]
        return m, rd.by_model[m][0]


class DeepRT(ScoreGuard):
    """DeepRT Method(DisBatcher + EDF, SEC'21 §3.2·§3.3·§4.3, P3.11): 모델마다 길이 W의 window를 둔다(offset m·W/M로 엇갈림, 가정).
    window가 끝나면 그동안 도착한 요청을 job 하나로 만들고, job deadline(window 끝 + W) 순서(EDF)로 처리한다.
    flush(§4.3)면 compute array가 놀 때 window가 안 끝난 요청도 바로 묶는다. 원문 W = 상대 deadline의 절반(약 14.9 ms).
    cfg = (W µs, flush)는 공통 조정 대상. admission·해상도 조정은 없다"""
    name = 'DeepRT Method'
    cfg = (14900.0, True)

    def _end(self, m, t):
        W = self.cfg[0]
        w_off = m * W / M
        return w_off + math.ceil((t - w_off) / W) * W

    def pick(self, rd, T, st):
        ta = rd.wl.t_arr
        jobs, nxt = [], float('inf')
        for m in range(M):
            if rd.by_model[m]:
                J = self._end(m, ta[rd.by_model[m][0]])
                if J <= T:
                    jobs.append((J, m))
                else:
                    nxt = min(nxt, J)
        if jobs:
            J, m = min(jobs)
            self.J = J
            return m, rd.by_model[m][0]
        if self.cfg[1] and T >= self.busy_until:           # compute array가 놂: window 끝을 기다리지 않고 보냄
            J, m = min((self._end(m, ta[rd.by_model[m][0]]), m) for m in range(M) if rd.by_model[m])
            self.J = float('inf')
            return m, rd.by_model[m][0]
        na = rd.next_arrival()
        t = min(nxt, self.busy_until if self.cfg[1] else nxt)
        return None, t if na is None else min(t, na)

    def members(self, rd, m, head, s):
        ta = rd.wl.t_arr
        return [i for i in rd.by_model[m] if ta[i] <= self.J]


class TimeoutBatch16(TimeoutBatch):
    """시간제한 batch, W = 16 ms"""
    name = '시간제한 batch 16'

    def __init__(self, margin=1150.0, overlap=False, slack=4000.0):
        super().__init__(margin, overlap, slack, max_wait=16000.0)


class Timeout:
    """Timeout (선행연구: 동적 batching의 대기 상한, Triton max queue delay·Clipper류. 수집 문헌 밖): 가장 오래 기다린 요청이
    FPGA에 도착한 지 W가 될 때까지 시작하지 않는다. 그 뒤로는 그룹핑과 같다(가장 오래된 요청의 모델, 쌓인 요청 전부).
    deadline guard가 없으므로 W는 동시 도착 몰림에서도 deadline을 지키는 값으로 정해야 한다(target_exp.FINAL_TIMEOUT_W)"""
    name = 'Timeout'

    def __init__(self, max_wait=4000.0):
        self.W = max_wait

    def reset(self):
        pass

    def pick(self, rd, T, st):
        h = rd.oldest()
        rel = rd.wl.t_arr[h] + self.W
        if T < rel:
            return None, rel                               # 가장 오래된 요청이 W를 채울 때까지 기다림
        return int(rd.wl.model[h]), h

    def members(self, rd, m, head, s):
        return list(rd.by_model[m])


class SlackBatch(LazyGroup):
    """SlackBatch (구현 대상): deadline 순서는 그룹핑 그대로 두고, 모델별 남은 weight 전송·연산 시간과 deadline 여유로
    '늦어도 언제 시작해야 하는가'를 deadline 순 누적합으로 계산해, 그때까지 기다려 같은 모델 요청을 더 모은다(= 지연 그룹핑)"""
    name = 'SlackBatch'


class SlackBatchLite(LazyGroupSimple):
    """SlackBatch-Lite: SlackBatch와 같되, 가장 늦은 시작 시각을 합계 하나로 보수적으로 계산한다(= 지연 그룹핑(간이 guard))"""
    name = 'SlackBatch-Lite'


class SlackBatchHW(SlackBatch):
    """SlackBatch HW 규칙: 다음 도착 시각 대신 Host 주기 1 ms 뒤에 다음 요청이 온다고 보고 기다림을 판단한다"""
    name, next_arr = 'SlackBatch(HW)', 1000.0


class SlackBatchLiteHW(SlackBatchLite):
    """SlackBatch-Lite HW 규칙 (SlackBatchHW와 같은 대기 규칙)"""
    name, next_arr = 'SlackBatch-Lite(HW)', 1000.0


class WSPT(ScoreGuard):
    """WSPT (P3.12, 평균 응답 시간 최소화): Smith 규칙. 모델마다 (드러나는 적재 대기 + n × 모델 평균 연산) ÷ n이 가장 작은 모델의
    대기 요청 전부를 묶는다. 적재 대기 = 지금 적재를 시작할 때 compute array가 비는 시각보다 늦게 끝나는 만큼(hit면 0).
    모델 평균 연산은 Host가 profile해 register에 쓴다고 본다(가정, simulation은 workload의 모델별 평균).
    deadline guard는 점수2와 같다(_safe, dense 연산으로 보수적). 기다리지 않는다"""
    name = 'WSPT'

    def pick(self, rd, T, st):
        wl, tg = rd.wl, rd.wl.t_gen
        if getattr(self, '_wl', None) is not wl:
            self._wl = wl
            c = wl.cost if wl.cost is not None else np.full(wl.model.size, sc.C_REQ)
            self.pred = np.bincount(wl.model, c, M) / np.maximum(1, np.bincount(wl.model, minlength=M))
        t0 = max(T, self.busy_until)
        cand, best = [], None
        for m in range(M):
            lst = rd.by_model[m]
            if lst:
                n, x = len(lst), xfer_time(st.peek(m))
                c4 = (min(tg[i] for i in lst) + P, m, n, x)
                cand.append(c4)
                key = ((max(0.0, T + x - t0) + n * self.pred[m]) / n, c4[0])
                if best is None or key < best[0]:
                    best = (key, c4)
        cand.sort()
        m = best[1][1] if best[1][1] == cand[0][1] or self._safe(best[1], cand, t0) else cand[0][1]
        return m, rd.by_model[m][0]


def robust(cls):
    """결과 회수 여유에 PCIe 실측 worst case(795 µs)를 넣는 변형(이름에 '(강건)')"""
    return type(cls.__name__ + 'Robust', (cls,), {'name': cls.name + '(강건)', 'robust': True})


# ---- 연산 방식 -----------------------------------------------------------------
# DMA는 하나. 요청을 미리 내 두면 앞 전송과 겹쳐 고정 비용 T0이 숨는다(P3.1 pipelined 실측):
#   데이터 도착 완료 = max(요청 시각 + T0, 앞 전송 완료) + 크기 / BW
# membrane potential이 DDR3에 있으면(sc.MEM_B > 0) 두 방식 모두 batch의 weight 전송 뒤에 k × 2,824 B(읽기 + 쓰기)를
# DMA 시간으로 더한다(다음 batch의 적재가 그만큼 늦어짐). membrane potential 읽기 지연(트랙당 약 0.7 µs)은 숨긴다고 가정한다.
def _membrane(cm, s, k):
    if sc.MEM_B:
        k, n = cm.mem or (k, 0)                        # 트랙별 membrane potential이면 (DDR3 요청 수, DMA 횟수). DMA마다 T0
        cm.dma_free = max(cm.dma_free, s) + mem_time(k) + n * sc.T0
class AllAtOnce:
    """한 번에: 필요한 weight가 모두 들어온 뒤 batch 연산. 트랙을 하나씩 모델 전체로 연산.
    entry가 있는 저장 정책은 빈(교체될) entry에 바로 적재하고, B는 L2~L4 적재 버퍼 1벌이 필요"""
    name = '한번에'
    log = None                         # simulate(detail=True)가 []로 바꾸면 연산 구간 (시작, 끝)을 기록

    def mem_tiles(self):
        return sc.MEMBUF_TRACK_T       # membrane potential이 DDR3면 트랙 2개분 준비 버퍼

    def extra_tiles(self, st):
        buf = 0 if st.uses_entry else tiles(st.buf_words, 8 * sc.WORD) + st.buf_extra
        return self.mem_tiles() + buf

    def max_batch(self):
        return None                    # 트랙 단위로 연산하므로 membrane potential 버퍼 2트랙분이면 된다

    @staticmethod
    def xfers(loads):
        return int(sum(loads) > 0)     # 필요한 weight를 DMA 한 번으로 가져온다

    def reset(self):
        self.dma_free = self.cmp_free = self.buf_free = 0.0

    def run(self, T, loads, uses_entry, members):
        total = sum(loads)
        ready = T
        if total:
            issue = T if uses_entry else max(T, self.buf_free)
            ready = max(issue + sc.T0, self.dma_free) + total / sc.BW
            self.dma_free = ready
        s = max(ready, self.cmp_free)
        k, c = members(s)
        _membrane(self, s, k)
        fin = s + (sc.C_REQ * np.arange(1, k + 1) if c is None else np.cumsum(c))
        self.cmp_free = fin[-1] if k else s
        if self.log is not None:
            self.log.append((s, self.cmp_free))
        if total and not uses_entry:
            self.buf_free = self.cmp_free
        return s, fin


class RowByRow:
    """한 줄씩: 뉴런 그룹(레인 수만큼의 뉴런 × 입력 전체)이 도착하는 대로 batch의 트랙들이 차례로 연산.
    entry가 있는 저장 정책은 교체될 entry에 바로 적재하며 그룹별 도착만 확인한다(버퍼 불필요).
    B는 슬라이스 이중 버퍼 2칸을 batch 경계와 상관없이 번갈아 쓴다.
    그룹마다 batch의 모든 트랙을 돌므로, membrane potential이 DDR3에 있으면 batch 전체의 membrane potential 버퍼가 필요하다.
    rev 2에서는 batch 전체의 입력·layer 간 spike 버퍼(SPK_T)도 필요하고 batch는 항상 BATCH_CAP 이하다"""
    name = '한줄씩'
    log = None

    def mem_tiles(self):
        return sc.MEMBUF_T + sc.SPK_T  # membrane potential이 DDR3면 batch 전체(BATCH_CAP 트랙) 버퍼 + rev 2 spike 버퍼

    def extra_tiles(self, st):
        return self.mem_tiles() + (0 if st.uses_entry else sc.SLICE_T + st.buf_extra)

    def max_batch(self):
        return sc.BATCH_CAP

    @staticmethod
    def xfers(loads):
        return sum(1 for b in loads if b)   # 뉴런 그룹(슬라이스)마다 DMA 한 번

    def reset(self):
        self.dma_free = self.cmp_free = 0.0
        self.slot = [0.0, 0.0]
        self.si = 0

    def run(self, T, loads, uses_entry, members):
        t, k, s = self.cmp_free, None, None
        for g, b in enumerate(loads):
            ready = T
            if b:
                j, self.si = self.si, self.si ^ 1
                issue = T if uses_entry else max(T, self.slot[j])
                ready = max(issue + sc.T0, self.dma_free) + b / sc.BW
                self.dma_free = ready
            start = max(ready, t)
            if k is None:
                s, (k, c) = start, members(start)
                # shortcut: spike 0 건너뛰기면 모든 그룹을 요청별 연산 비율로 늘이고 줄인다(L1·출력 layer도). 한 줄씩을 다시 비교할 때 그룹별로 바꾼다
                w = k if c is None else c.sum() / sc.C_REQ
            t = start + w * sc.G_CYC[g]
            if self.log is not None:
                self.log.append((start, t))
            if b:
                self.slot[j] = t
        _membrane(self, s, k)
        self.cmp_free = t
        return s, start + sc.G_CYC[-1] * np.arange(1, k + 1)


STORAGES = [FullCache, L1Resident, Hybrid]
STORAGES_ALL = [FullCache, L1Resident, Hybrid, Stream]      # 설계 공간 탐색(P3.8)용
STORAGES_FIT = [FullCache, PartialAll, PinnedHybrid, Stream]  # 목표 트랙 실험(target_exp.py): B·C를 예산에 맞춤
SCHEDULERS = [FCFS, EDF, Grouping, Score]
COMPUTES = [AllAtOnce, RowByRow]


# ---- P3.12 실험 부품 (latency_exp·replicate_exp에 있던 것을 옮김. simulation/engine도 같은 정의를 쓴다) ----------
class NoLoad(FullCache):
    """하한: weight 적재가 없다(모든 모델 hit)"""
    name = '적재 0'

    def peek(self, m):
        return 0

    def plan(self, m):
        return sc.ZERO


class OffsetPrefetch(OffsetNext):
    """참고: G.offset-order + 도착 예측 prefetch. batch 적재를 낸 뒤 연산이 끝나기 전에 DMA가 비고 기다리는 미적재 모델이 없으면,
    다음 사용이 가장 이른 미적재 모델을 다음 사용이 가장 늦은 entry(연산 중·다음 batch 제외)에 미리 받는다. 결정마다 1개.
    PrefetchCompute와 함께 쓴다"""
    name = 'G.offset-order+prefetch'

    def reset(self, wl):
        super().reset(wl)
        self.ready, self.last_ready, self.pf_b = {}, 0.0, 0.0

    def plan(self, m):
        self.last_ready = self.ready.pop(m, 0.0)          # 아직 받는 중인 prefetch면 그 완료 시각
        return super().plan(m)

    def prefetch(self, T, c):
        if c.dma_free > c.cmp_free or any(self.rd.by_model[x] for x in range(M) if x not in self.d):
            return
        nxt = min(((self._next(e), e) for e in range(M) if e not in self.d), default=(float('inf'), None))
        keep = list(self.d)[-2:]
        vict = max((x for x in self.d if x not in keep), key=self._next, default=None)
        if nxt[1] is None or nxt[0] == float('inf') or vict is None or self._next(vict) <= nxt[0]:
            return
        c.dma_free = max(T + sc.T0, c.dma_free) + sum(sc.FULL) / sc.BW
        if self.wl.w0 <= T < self.wl.w1:                   # 측정 구간 weight byte에 prefetch도 넣는다(실행기가 w_bytes에 더함)
            self.pf_b += sum(sc.FULL)
        del self.d[vict]
        self.ready.pop(vict, None)
        self.d[nxt[1]] = True
        self.d.move_to_end(nxt[1], last=False)
        self.ready[nxt[1]] = c.dma_free


class PrefetchCompute(AllAtOnce):
    """한 번에 + OffsetPrefetch의 prefetch 호출. 실행기가 c.st에 저장 정책을 넣는다"""
    def run(self, T, loads, uses_entry, members):
        st = self.st
        s, fin = super().run(max(T, st.last_ready) if not sum(loads) else T, loads, uses_entry, members)
        st.prefetch(T, self)
        return s, fin


class WSPTFix(WSPT):
    """WSPT + 적재 대기 = max(적재 시작 가능 시각 + T0, DMA가 비는 시각) + 전송 − compute array가 비는 시각.
    적재 시작 가능 시각: entry 저장이면 지금, 한 번에 + 버퍼면 버퍼가 비는 시각, 한 줄씩이면 다음 slot이 비는 시각.
    WSPT는 다음 모델을 지금 연산과 겹쳐 받을 수 있다고 보는데, B·C·D는 적재 버퍼가 하나라 겹치지 않는다(제안, 미채택)"""
    name = 'WSPT(수정)'
    c = None                                            # 실행기가 연산 방식을 넣는다

    def _cost(self, wl):
        c = wl.cost if wl.cost is not None else np.full(wl.model.size, sc.C_REQ)
        return c[:, 0] if c.ndim == 2 else c

    def pick(self, rd, T, st):
        c, wl, tg = self.c, rd.wl, rd.wl.t_gen
        if getattr(self, '_wl', None) is not wl:
            self._wl = wl
            self.pred = np.bincount(wl.model, self._cost(wl), M) / np.maximum(1, np.bincount(wl.model, minlength=M))
        pred = self._pred(rd, st)
        t0 = max(T, self.busy_until)
        issue = T if st.uses_entry else max(T, c.slot[c.si] if hasattr(c, 'slot') else c.buf_free)
        cand, best = [], None
        for m in range(M):
            lst = rd.by_model[m]
            if lst:
                n, b = len(lst), st.peek(m)
                stall = max(0.0, max(issue + sc.T0, c.dma_free) + b / sc.BW - t0) if b else 0.0
                c4 = (min(tg[i] for i in lst) + sc.P, m, n, sc.xfer_time(b))
                cand.append(c4)
                key = ((stall + n * pred[m]) / n, c4[0])
                if best is None or key < best[0]:
                    best = (key, c4)
        cand.sort()
        m = best[1][1] if best[1][1] == cand[0][1] or self._safe(best[1], cand, t0) else cand[0][1]
        return m, rd.by_model[m][0]

    def _pred(self, rd, st):
        return self.pred


class RepCache(OffsetNext):
    """R.복제 (제안, 미채택): 대기 요청이 THR개 이상인 모델을 연산 중인 모델이 쓰지 않는 entry r개(≤ R)에 DMA 한 번으로
    동시에 쓴다(broadcast). 그 밖에는 G.offset-order와 같다. 복사본이 2개 이상 남은 모델은 hit여도 넓게 읽는다(rep_now).
    WideCompute와 함께 쓴다"""
    name = 'R.복제'
    R, THR = 5, 8                                       # 복사본 수 상한, 복제를 시작하는 대기 요청 수

    def reset(self, wl):
        super().reset(wl)
        self.copies, self.cur, self.rep_now = {}, None, False

    def _used(self):
        return sum(self.copies.get(x, 1) for x in self.d)

    def _evict(self, need, keep):
        while self._used() + need > self.E:
            v = max((x for x in self.d if x not in keep), key=self._next)
            del self.d[v]
            self.copies.pop(v, None)

    def _rep(self, m):
        return self.rd is not None and len(self.rd.by_model[m]) >= self.THR   # 첫 결정 전에는 대기열이 없다

    def plan(self, m):
        prev, self.cur = self.cur, m
        r = min(self.R, self.E - (self.copies.get(prev, 1) if (prev in self.d and prev != m) else 0))
        if m in self.d and (self.copies.get(m, 1) >= r or not self._rep(m)):
            self.d.move_to_end(m)
            self.rep_now = self.copies.get(m, 1) > 1
            return sc.ZERO
        k = r if self._rep(m) and r > 1 else 1          # 이미 1벌 있어도 복제하려면 다시 받는다
        self.d.pop(m, None)
        self.copies.pop(m, None)
        self._evict(k, {prev})
        self.d[m], self.copies[m], self.rep_now = True, k, k > 1
        return sc.FULL

    def peek(self, m):
        return 0 if m in self.d and (self.copies.get(m, 1) > 1 or not self._rep(m)) else sum(sc.FULL)


class WideCompute(AllAtOnce):
    """넓게 읽기 (제안, 미채택): 복사본 r개의 BRAM 두 port를 함께 읽어 L2·L3에서 cycle마다 spike 입력 2r개를 누산한다.
    복제 batch면 요청별 연산 시간의 둘째 열(spike 2R개/cycle)을 쓴다. 실행기가 c.st에 RepCache를 넣는다"""
    name = '넓게'

    def run(self, T, loads, uses_entry, members):
        col = 1 if self.st.rep_now else 0

        def pick_col(s):
            k, c = members(s)
            return k, (None if c is None else c[:, col])
        return super().run(T, loads, uses_entry, pick_col)


class WSPTRep(WSPTFix):
    """WSPTFix + 복제할 모델은 복제 연산 시간으로 본다(RepCache와 함께 쓴다)"""
    name = 'WSPT-R'

    def _pred(self, rd, st):
        wl = rd.wl
        if getattr(self, '_wl2', None) is not wl:
            self._wl2 = wl
            self.pred_r = np.bincount(wl.model, wl.cost[:, 1], M) / np.maximum(1, np.bincount(wl.model, minlength=M))
        return np.array([self.pred_r[m] if (len(rd.by_model[m]) >= st.THR or st.copies.get(m, 1) > 1) else self.pred[m]
                         for m in range(M)])


# ==== 4. 실행기: 환경 파일 → 부품 조립 → mode 실행 → CSV ============================
ENV_DIR = os.path.join(ROOT, 'simulation', 'environment')
TEMPLATE = os.path.join(ENV_DIR, 'template.toml')
OUT = os.path.join(ROOT, 'simulation', 'result')

ARCHS = {'L': (40, 384, 256, 64, 2), 'XL': (40, 768, 512, 128, 2)}
BRAM_TOTAL, XDMA, PREP = 365, 20.5, 4.0               # XC7A200T BRAM36, XDMA(P3.2 실측), membrane potential 준비 버퍼 등
PCIE_WORST = 795.3                                     # µs, H2C 64 B 관측 최대(P3.3 §4). robust scheduler의 결과 회수 여유
BIN, NBIN = 0.05, 1400                                 # 응답 시간 히스토그램 0.05 ms 간격, 70 ms 이상은 마지막 칸(합산 p99용)

STORAGE = {'A': pol.FullCache, 'B': pol.PartialAll, 'B_l1': pol.L1Resident, 'C': pol.PinnedHybrid, 'C_lru': pol.Hybrid,
           'D': pol.Stream, 'E': pol.PinLRU, 'F': pol.FurthestNext, 'G': pol.OffsetNext, 'G_prefetch': pol.OffsetPrefetch,
           'R': pol.RepCache, 'noload': pol.NoLoad}
COMPUTE = {'all': pol.AllAtOnce, 'row': pol.RowByRow, 'prefetch': pol.PrefetchCompute, 'wide': pol.WideCompute}
PAIRED = {'prefetch': 'G_prefetch', 'wide': 'R'}      # 이 연산 방식은 이 저장 정책과만 함께 동작한다


def _frozen(cls, **attrs):
    return type(cls.__name__ + 'Frozen', (cls,), attrs)


SCHED = {
    'fcfs': pol.FCFS, 'edf': pol.EDF, 'grouping': pol.Grouping, 'score': pol.Score, 'score_nocap': pol.ScoreNoCap,
    'score2': pol.ScoreGuard, 'score3': pol.ScoreWait, 'lazy': pol.LazyGroup, 'lazys': pol.LazyGroupSimple,
    'timeout_batch': pol.TimeoutBatch, 'timeout_batch16': pol.TimeoutBatch16, 'timeout': pol.Timeout,
    'dysta': pol.Dysta, 'dysta_req': pol.DystaReq, 'clockwork': pol.Clockwork, 'symphony': pol.Symphony,
    'shepherd': pol.ShepherdNP, 'deeprt': pol.DeepRT, 'wspt': pol.WSPT, 'wspt_fix': pol.WSPTFix, 'wspt_rep': pol.WSPTRep,
    'slackbatch_v0': pol.SlackBatch, 'slackbatch_lite_v0': pol.SlackBatchLite,
    'slackbatch_hw': pol.SlackBatchHW, 'slackbatch_lite_hw': pol.SlackBatchLiteHW,
    # P3.9 동결 정의: HW 대기 규칙 + cache 교체 반영 guard + 비례 여유 α = 51/256 (ARCH_SPEC §7.2)
    'slackbatch': _frozen(pol.SlackBatchHW, cache_aware=True, slack_ratio=51 / 256),
    'slackbatch_lite': _frozen(pol.SlackBatchLiteHW, cache_aware=True, slack_ratio=51 / 256),
}


# ---- 환경 파일 --------------------------------------------------------------------
def load(path):
    """환경 파일을 읽고 모든 점을 확인한다. 키가 템플릿과 다르거나 값이 틀리면 돌리기 전에 멈춘다"""
    with open(path, 'rb') as f:
        env = tomllib.load(f)
    with open(TEMPLATE, 'rb') as f:
        keys = set(tomllib.load(f))
    if set(env) != keys:
        raise SystemExit(f'{path}: 템플릿에 없는 키 {sorted(set(env) - keys)}, 빠진 키 {sorted(keys - set(env))}')
    for lb, e in points(env):
        check(lb, e)
    return env


def merge(e, over, where):
    """표 over의 키들로 e를 덮어쓴 사본. label은 이름으로만 쓴다"""
    bad = set(over) - set(e) - {'label'}
    if bad:
        raise SystemExit(f'{where}: 템플릿에 없는 키 {sorted(bad)}')
    return {**e, **{k: v for k, v in over.items() if k != 'label'}}


def points(env):
    """[sweep] 축의 곱. 축 이름이 환경 키면 그 키 값을 바꾸고, 아니면 축의 값(표)이 여러 키를 한꺼번에 바꾼다"""
    base = {k: v for k, v in env.items() if k != 'sweep'}
    axes = list(env['sweep'].items())
    out = []
    for combo in itertools.product(*(vals for _, vals in axes)):
        e, tag = base, []
        for (ax, _), v in zip(axes, combo):
            if ax in base:
                if isinstance(v, dict) and not isinstance(base[ax], dict):
                    raise SystemExit(f'[sweep] {ax}: 환경 키 이름의 축에는 그 키의 값만 넣는다. 표로 여러 키를 바꾸려면 축 이름을 바꾼다')
                e = {**e, ax: v}
                tag.append(f'{ax}={v}')
            elif isinstance(v, dict):
                e = merge(e, v, f'[sweep] {ax}')
                tag.append(v.get('label') or ', '.join(f'{k}={x}' for k, x in v.items()))
            else:
                raise SystemExit(f'[sweep] {ax}: 환경 키가 아니면 값은 표여야 한다')
        out.append((' · '.join(tag) or '기준', e))
    return out


def check(lb, e):
    inv = {v: k for k, v in PAIRED.items()}
    q = SCHED.get(e['sched'], object)()
    rules = [('mode', e['mode'] in ('run', 'search', 'tune')), ('model', e['model'] in ARCHS),
             ('storage', e['storage'] in STORAGE), ('compute', e['compute'] in COMPUTE), ('sched', e['sched'] in SCHED),
             ('mem', e['mem'] in ('ddr', 'onchip', 'auto')), ('offset', e['offset'] in ('none', 'model', 'model_w', 'scatter')),
             ('bits', isinstance(e['bits'], int) or (isinstance(e['bits'], list) and len(e['bits']) == len(ARCHS.get(e['model'], ())) - 1)),
             ('mem_place', e['mem_place'] in ('avg', 'id', 'offset') and (e['mem_place'] == 'avg' or bool(e['bits']))),
             ('gather_ms', e['gather_ms'] >= 0 and (not e['gather_ms'] or e['offset'] in ('model', 'model_w'))),
             ('pre_us', e['pre_us'] >= 0),
             ('perturb', e['perturb'] in ('', 'shift') or e['perturb'].startswith('strag')),
             ('scenarios', bool(e['scenarios']) and set(e['scenarios']) <= set(sc.SCENARIOS)),
             ('compute', PAIRED.get(e['compute'], e['storage']) == e['storage'] and inv.get(e['storage'], e['compute']) == e['compute']),
             ('sched_attrs', all(hasattr(q, k) for k in e['sched_attrs'])),
             ('storage_attrs', all(hasattr(STORAGE.get(e['storage'], object), k) for k in e['storage_attrs'])),
             ('search_key', e['mode'] != 'search' or (e['search_key'] in e and (e['search_values'] or e['search_key'] == 'tracks'))),
             ('tune_attr', e['mode'] != 'tune' or (hasattr(q, e['tune_attr']) and bool(e['tune_values'])))]
    bad = [f'{k}={e[k]!r}' for k, ok in rules if not ok]
    if bad:
        raise SystemExit(f'{lb}: 잘못된 값 {", ".join(bad)}')
    for cond in e['tune_conds']:
        merge(e, cond, f'{lb}: tune_conds')


def seeds(e):
    return range(e['seed0'], e['seed0'] + e['seeds'])


# ---- 부품과 요청열 ------------------------------------------------------------------
def layer_bits(e):
    """layer별 membrane potential 저장 bit. bits가 수 하나면 모든 layer가 같다"""
    b = e['bits']
    return list(b) if isinstance(b, list) else [b] * (len(ARCHS[e['model']]) - 1)


def onchip_tracks(e):
    """weight entry를 뺀 남은 BRAM에 membrane potential(bits)을 둘 수 있는 트랙 수(16 단위)"""
    free = BRAM_TOTAL - XDMA - e['reserve'] - PREP - e['entries'] * sc.ENTRY_T
    lay = list(zip(ARCHS[e['model']][1:], layer_bits(e)))
    fit = [k for k in range(0, e['tracks'] + 1, 16) if sum(tiles(k * m, b) for m, b in lay) <= free]
    return max(fit, default=0)


def build(e):
    """본체 조건(configure)을 정하고 (저장 정책, scheduler, 연산 방식, BRAM tile, 배치 가능)을 만든다.
    OVH는 configure 전에(요청당 연산에 반영), DDR 대역폭은 부품을 만든 뒤에 넣는다(부품 크기는 공칭 3,015 MB/s 기준)"""
    arch = ARCHS[e['model']]
    sc.OVH, sc.BW, sc.SPK_PER_CYC = e['ovh'], 3015.0, max(1, e['spk'])
    sc.configure(e['lanes'], e['tracks'], mem=e['mem'], rev=e['rev'], arch=arch)
    c = COMPUTE[e['compute']]()
    S = STORAGE[e['storage']]
    kw = dict(budget=sc.TILE_BUDGET - e['reserve'] - c.mem_tiles(), compute=c, entries=e['entries'] or None)
    st = S(**{k: v for k, v in kw.items() if k in inspect.signature(S).parameters})
    for k, v in e['storage_attrs'].items():
        setattr(st, k, v)
    c.st = st
    t = st.tiles() + c.extra_tiles(st)
    ok = t <= sc.TILE_BUDGET - e['reserve'] and (not st.uses_entry or st.E >= 2)   # entry 저장은 2벌 이상이어야 적재·연산이 겹침
    if e['bits']:                                      # 일부 트랙 membrane potential on-chip, 나머지는 bits로 DDR3에 저장
        rw = -(-sum(n * b for n, b in zip(arch[1:], layer_bits(e))) // 8)   # membrane potential 읽기 또는 쓰기 byte(뉴런 수 × bits)
        off = 1 - onchip_tracks(e) / e['tracks'] if e['mem_place'] == 'avg' else 1   # 트랙별이면 요청마다 따로 셈
        sc.MEM_RD, sc.MEM_B = off * rw, 2 * off * rw
    q = SCHED[e['sched']]()
    if isinstance(q, pol.ScoreGuard):
        q.cap = c.max_batch()
    for k, v in e['sched_attrs'].items():
        setattr(q, k, v)
    if isinstance(q, pol.ScoreGuard) and 'margin' not in e['sched_attrs']:
        if e['host_ms'] and not e['result_push']:      # 결과 회수 여유: Host 읽기 주기 + C2H 최대 + 20 µs. 꼬리 지연은 모른다
            worst = PCIE_WORST if q.robust else sc.load_samples(sc.H_OUT_FILE).max()
            q.margin = e['host_ms'] * 1000.0 + worst + 20.0
        else:                                          # 결과 즉시 전송: C2H 연속 표본 최대 + 20 µs
            q.margin = sc.load_samples(sc.D_OUT_FILE).max() + 20.0
    if hasattr(q, 'c'):
        q.c = c
    sc.BW = e['bw_mbps']
    return st, q, c, t, ok


def _offsets(seed, n, kw):
    """make_workload와 같은 순서로 난수를 뽑아 트랙→모델과 무작위 offset을 얻는다"""
    rng = np.random.default_rng(seed)
    tm = rng.choice(M, n, p=sc.ZIPF) if kw.get('dist') == 'zipf' else rng.integers(0, M, n)
    return tm, rng.uniform(0, P, n)


def workload(e, scn, seed):
    """요청열. build 뒤에 부른다(spike 연산 시간이 configure 값을 씀)"""
    n, kw = e['tracks'], dict(sc.SCENARIOS[scn])
    tm, offs = _offsets(seed, n, kw)
    if 'offset' in kw:                                 # 동시 도착(S·SK): offset 0
        offs = np.zeros(n)
    model_off = np.arange(M) * (P / M)                 # 모델별 offset 시작
    if e['offset'] == 'model_w':                       # offset 간격을 모델의 트랙 수에 비례하게
        model_off = np.r_[0, np.cumsum(np.bincount(tm, minlength=M))[:-1]] * (P / n)
    if e['offset'] != 'none':                          # none이면 offset을 넘기지 않는다(make_workload가 같은 값을 뽑음)
        if e['offset'] in ('model', 'model_w'):        # offset 배정: 모델 m의 트랙은 offset + jitter
            offs = model_off[tm] + np.random.default_rng(seed + 4242).uniform(0, e['jitter_ms'] * 1000.0, n)
        else:                                          # 고르게 나눈 offset(CAN offset 배정 방식): 모델과 무관하게 트랙을 주기에 고르게
            offs = np.random.default_rng(seed + 4343).permutation(n) * (P / n)
        kw.pop('offset', None)
        kw.update(offset=offs, track_model=tm)
    args = dict(warm=e['warm'], meas=e['meas'], host=e['host_ms'] * 1000.0 or None, spike=e['spk'] > 0, **kw)
    wl = sc.make_workload(n, seed, **args)
    if e['compute'] == 'wide':                        # 둘째 열 = 복제 batch의 연산 시간(spike 2R개/cycle)
        if wl.cost is None:
            wl.cost = np.full((wl.t_arr.size, 2), sc.C_REQ)
        else:
            sc.SPK_PER_CYC = 2 * e['storage_attrs'].get('R', pol.RepCache.R)
            wl.cost = np.stack([wl.cost, sc.make_workload(n, seed, **args).cost], 1)
            sc.SPK_PER_CYC = max(1, e['spk'])
    if e['gather_ms']:                                 # Host offset 단위 모아 보내기: 모델·주기마다 다 준비되거나 offset + D가 되면 한꺼번에.
        s0 = model_off[wl.model]                       # 그 뒤에 준비된 요청은 준비되는 대로 보낸다
        k = np.floor((wl.t_gen - s0) / P)
        _, g = np.unique(wl.model * 1_000_000 + k.astype(np.int64), return_inverse=True)
        last = np.full(g.max() + 1, -np.inf)
        np.maximum.at(last, g, wl.t_gen)
        send = np.maximum(wl.t_gen, np.minimum(last[g], s0 + k * P + e['gather_ms'] * 1000.0))
        wl.t_arr = wl.t_arr + (send - wl.t_gen)
        _filter(wl, np.ones(wl.t_arr.size, bool), order=np.argsort(wl.t_arr, kind='stable'))
    if e['mem_place'] != 'avg':                        # 트랙별 membrane potential: track_id < on-chip 트랙 수면 BRAM, 나머지는 DDR3에 id 순서로 붙여 둔다
        tid = np.arange(n) if e['mem_place'] == 'id' else np.lexsort((offs, tm)).argsort()   # offset: Host가 모델 offset·트랙 offset 순서로 id를 매김
        on = onchip_tracks(e)
        wl.mem_addr = np.where(tid < on, -1, tid - on)
    if e['result_push']:
        wl.out_w = 0.0                                 # 결과는 연산이 끝나면 바로 C2H(d_out)
    pert = e['perturb']
    if pert == 'shift':                                # 교대: 트랙 30 %는 측정 중간에 들어오고, 다른 30 %는 나간다
        order = np.argsort(offs)                       # offset이 가장 가까운 트랙(부동소수 오차 허용)
        pos = np.clip(np.searchsorted(offs[order], wl.t_gen % P), 1, n - 1)
        lo, hi = order[pos - 1], order[pos]
        trk = np.where(np.abs(offs[lo] - wl.t_gen % P) <= np.abs(offs[hi] - wl.t_gen % P), lo, hi)
        k = np.round((wl.t_gen - offs[trk]) / P).astype(int)
        grp = np.random.default_rng(seed + 5151).choice(3, n, p=[0.3, 0.3, 0.4])   # 0 = 늦게 합류, 1 = 중간에 이탈, 2 = 계속
        mid = e['warm'] + e['meas'] // 2
        _filter(wl, ~((grp[trk] == 0) & (k < mid)) & ~((grp[trk] == 1) & (k >= mid)))
    elif pert.startswith('strag'):                    # 늦는 요청 x %: 도착이 0~16 ms 늦는다(생성·deadline은 그대로)
        r = np.random.default_rng(seed + 6161)
        sel = r.random(wl.t_arr.size) < float(pert[5:]) / 100
        wl.t_arr = wl.t_arr.copy()
        wl.t_arr[sel] += r.uniform(0, P / 2, sel.sum())
        _filter(wl, np.ones(wl.t_arr.size, bool), order=np.argsort(wl.t_arr, kind='stable'))
    if e['tail_us']:                                   # 모든 H2C·C2H 전송에 꼬리 지연
        wl.t_arr = wl.t_arr + e['tail_us']
        wl.pre = wl.pre + e['tail_us']
        wl.d_out = wl.d_out + e['tail_us']
        if wl.out_lat is not None:
            wl.out_lat = wl.out_lat + e['tail_us']
    if e['pre_us']:                                    # 외부 지연(오디오·전처리). t_gen은 수음 시각이라 deadline 여유에서 빠진다
        wl.t_arr = wl.t_arr + e['pre_us']
        wl.pre = wl.pre + e['pre_us']
    return wl


def _filter(wl, keep, order=None):
    idx = np.flatnonzero(keep) if order is None else order[keep[order]]
    for f in ('t_gen', 't_arr', 'model', 'd_out', 'cost', 'track'):
        v = getattr(wl, f)
        if v is not None:
            setattr(wl, f, v[idx])


# ---- mode ---------------------------------------------------------------------------
def simulate_point(e, scn, seed):
    """실행 하나의 simulate() 결과 그대로(test_engine이 환경 파일마다 한 번 돌린다)"""
    st, q, c, _, _ = build(e)
    r = sc.simulate(workload(e, scn, seed), st, q, c, detail=True)
    r['w_bytes'] += getattr(st, 'pf_b', 0.0)           # prefetch도 측정 구간 weight byte에 넣는다
    return r


def run_one(job):
    i, lb, e, scn, seed = job
    r = simulate_point(e, scn, seed)
    resp = r.pop('resp') / 1000
    h = np.bincount(np.minimum((resp / BIN).astype(int), NBIN))
    return dict(point=i, label=lb, scn=scn, seed=seed, **r, c_req=sc.C_REQ, hist=[[int(j), int(h[j])] for j in np.flatnonzero(h)])


def passes(e):
    st, q, c, _, ok = build(e)
    return ok and not any(sc.simulate(workload(e, s, sd), st, q, c, stop_on_miss=True)['miss']
                          for s in e['scenarios'] for sd in seeds(e))


def activity(scn):
    """주기마다 요청을 내는 트랙의 평균 비율 (I: p_req, R: 혼잡도 범위의 평균, 나머지 1)"""
    kw = sc.SCENARIOS[scn]
    return kw.get('p_req', sum(kw['congestion']) / 2 if 'congestion' in kw else 1.0)


def track_values(e):
    """tracks 탐색 후보: search_step 단위로, 평균 연산 가동률 ≤ 100 %인 가장 큰 값까지(넘으면 queue가 끝없이 쌓인다).
    연산 시간은 dense 기준이라 spike 연산이면 상한이 보수적이다(상한에 닿으면 capped)"""
    build(e)
    step = e['search_step']
    cap = min(int(P / (sc.C_REQ * activity(s))) // step * step for s in e['scenarios'])
    return list(range(step, cap + 1, step))


def search_one(job):
    i, lb, e = job
    key, vals, tested = e['search_key'], e['search_values'] or track_values(e), []

    def ok(j):                                         # j = 후보 번호(1부터)
        r = passes({**e, key: vals[j - 1]})
        tested.append([vals[j - 1], r])
        return r
    lo, j, fail = 0, 1, None
    while True:
        if ok(j):
            lo = j
            if j == len(vals):
                break
            j = min(2 * j, len(vals))
        else:
            fail = j
            break
    if fail is not None:
        a, b = lo, fail - 1
        while a < b:
            mid = (a + b + 1) // 2
            if ok(mid):
                a = mid
            else:
                b = mid - 1
        lo = a
    return dict(point=i, label=lb, key=key, found=vals[lo - 1] if lo else None, capped=lo == len(vals), tested=tested)


def tune_one(job):
    i, lb, e, v = job
    fails, wb, req = 0, 0.0, 0
    for cond in e['tune_conds'] or [{}]:
        x = merge(e, cond, lb)
        x['sched_attrs'] = {**x['sched_attrs'], e['tune_attr']: v}
        st, q, c, _, ok = build(x)
        for s in x['scenarios']:
            for sd in seeds(x):
                r = sc.simulate(workload(x, s, sd), st, q, c, stop_on_miss=True) if ok else {'miss': 1}
                if r['miss']:
                    fails += 1
                else:
                    wb += r['w_bytes']
                    req += r['req_win']
    return dict(point=i, label=lb, attr=e['tune_attr'], value=v, fails=fails, w_kib=wb / req / 1024 if req else None)


# ---- 요약 ---------------------------------------------------------------------------
def summarize(rs):
    """실행 여러 개 합산. 비율·요청당 값은 합을 나눠 낸다. p99는 히스토그램을 합쳐 구한다(칸 위 경계)"""
    n = sum(r['n_req'] for r in rs)
    h = np.zeros(NBIN + 1)
    for r in rs:
        for j, k in r['hist']:
            h[j] += k
    cum = np.cumsum(h)
    rw = sum(r['req_win'] for r in rs)
    span = sum(r['cyc_busy'] + r['cyc_stall'] + r['cyc_idle'] for r in rs) * sc.CLK       # 측정 구간 합 µs
    wavg = lambda k: sum(r['n_req'] * r[k] for r in rs) / n
    return dict(runs=len(rs), n_req=n, miss=sum(r['miss'] for r in rs), drop=sum(r['drop'] for r in rs),
                mean_ms=wavg('mean_ms'), p99_ms=float(np.searchsorted(cum, 0.99 * cum[-1]) + 1) * BIN,
                max_ms=max(r['max_ms'] for r in rs), in_ms=wavg('in_ms'), fpga_ms=wavg('fpga_ms'), out_ms=wavg('out_ms'),
                w_kib=sum(r['w_bytes'] for r in rs) / rw / 1024, dram_kib=sum(r['w_bytes'] + r['m_bytes'] for r in rs) / rw / 1024,
                ddr_mbps=sum(r['w_bytes'] + r['m_bytes'] for r in rs) / span,
                mdma=sum(r.get('m_xfers', 0) for r in rs) / rw,                  # 추론당 membrane potential DMA 횟수(트랙별 membrane potential일 때만)
                batch=rw / sum(r['req_win'] / r['batch_mean'] for r in rs if r['batch_mean']),
                hit=float(np.mean([r['hit_rate'] for r in rs])))


def table(env, pts, info, rows):
    mode = env['mode']
    if mode == 'run':
        by = {}
        for r in rows:
            by.setdefault(r['point'], []).append(r)
        L = ['| 점 | 실행 | miss | 평균 ms | p99 ms | 최대 ms | 입력 · FPGA · 결과 ms | weight KiB/요청 | DRAM KiB/요청 | DDR MB/s | 평균 batch | hit rate |',
             '|---|' + '---:|' * 11]
        for i, (lb, _) in enumerate(pts):
            t, budget, ok = info[i]
            if not ok:
                L.append(f'| {lb} | BRAM {t:g} / {budget:g} tile 초과, 돌리지 않음 |' + ' |' * 10)
                continue
            a = summarize(by[i])
            L.append(f"| {lb} | {a['runs']} | {a['miss']:,} | {a['mean_ms']:.3f} | {a['p99_ms']:.2f}{'+' if a['p99_ms'] > 70 else ''} | "
                     f"{a['max_ms']:.2f} | {a['in_ms']:.2f} · {a['fpga_ms']:.2f} · {a['out_ms']:.2f} | {a['w_kib']:.1f} | "
                     f"{a['dram_kib']:.1f} | {a['ddr_mbps']:.0f} | {a['batch']:.1f} | {a['hit']:.2f} |")
    elif mode == 'search':
        L = [f"| 점 | {env['search_key']} 찾은 값 | 상한 도달 | 시험 (값: 통과) |", '|---|---:|---|---|']
        for r in rows:
            L.append(f"| {r['label']} | {'없음' if r['found'] is None else r['found']} | {'예' if r['capped'] else ''} | "
                     + ', '.join(f"{v}: {'O' if ok else 'X'}" for v, ok in r['tested']) + ' |')
    else:
        L = ['| 점 | 조절값 | 통과한 값 | 선택 | weight KiB/요청 | miss 난 실행 |', '|---|---|---|---:|---:|---:|']
        for i, (lb, _) in enumerate(pts):
            good, best = tune_pick([r for r in rows if r['point'] == i])
            L.append(f"| {lb} | {best['attr']} | {', '.join(str(r['value']) for r in good) or '없음'} | {best['value']} | "
                     f"{'–' if best['w_kib'] is None else f'{best['w_kib']:.1f}'} | {best['fails']} |")
    return '\n'.join(L) + '\n'


def tune_pick(rs):
    """tune 후보 중 모든 실행이 miss 0인 값들과, 그중 weight byte가 가장 작은 값(없으면 miss 난 실행이 가장 적은 값)"""
    good = [r for r in rs if r['fails'] == 0]
    return good, (min(good, key=lambda r: r['w_kib']) if good else min(rs, key=lambda r: r['fails']))


# ---- CSV ----------------------------------------------------------------------------
def point_rows(env, pts, info, rows):
    with open(TEMPLATE, 'rb') as f:
        keys = [k for k in tomllib.load(f) if k != 'sweep']
    by = {}
    for r in rows:
        by.setdefault(r['point'], []).append(r)
    out = []
    for i, (lb, e) in enumerate(pts):
        t, budget, ok = info[i]
        row = dict(point=i, label=lb, **{k: e[k] for k in keys}, tiles=t, budget=budget, feasible=ok)
        rs = by.get(i, [])
        if env['mode'] == 'run' and rs:
            row.update(summarize(rs))
        elif env['mode'] == 'search':
            row.update(found=rs[0]['found'], capped=rs[0]['capped'])
        elif env['mode'] == 'tune':
            good, best = tune_pick(rs)
            row.update(passed=[r['value'] for r in good], chosen=best['value'], w_kib=best['w_kib'], fails=best['fails'])
        out.append(row)
    return out


def job_rows(env, rows):
    if env['mode'] == 'search':
        return [dict(point=r['point'], label=r['label'], key=r['key'], value=v, passed=ok) for r in rows for v, ok in r['tested']]
    return rows


def cell(v):
    if isinstance(v, str):
        try:
            json.loads(v)                              # 숫자·참거짓처럼 읽히는 문자열만 따옴표를 붙인다
        except ValueError:
            return v
    return json.dumps(v, ensure_ascii=False, default=lambda o: o.item())   # numpy 수는 Python 수로


def _open(path, mode):
    """.gz면 gzip(시각을 넣지 않아 같은 내용이면 같은 byte), 아니면 그냥 연다"""
    if not path.endswith('.gz'):
        return open(path, mode, newline='', encoding='utf-8')
    return io.TextIOWrapper(gzip.GzipFile(path, mode + 'b', mtime=0), newline='', encoding='utf-8')


def write_csv(path, rows):
    cols = list(dict.fromkeys(k for r in rows for k in r))
    with _open(path, 'w') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows({k: cell(v) for k, v in r.items()} for r in rows)


def read_csv(path):
    """engine CSV → dict 목록. 칸마다 JSON으로 읽고, 안 되면 문자열 그대로(빈 칸 = 값 없음)"""
    def val(s):
        try:
            return json.loads(s)
        except ValueError:
            return s
    with _open(path, 'r') as f:
        return [{k: val(v) for k, v in r.items()} for r in csv.DictReader(f)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('env', help='환경 파일 (simulation/environment/*.toml)')
    ap.add_argument('--jobs', type=int, default=11)
    a = ap.parse_args()
    env = load(a.env)
    name = os.path.splitext(os.path.basename(a.env))[0]
    pts = points(env)
    info = []
    for _, e in pts:
        _, _, _, t, ok = build(e)
        info.append((t, sc.TILE_BUDGET - e['reserve'], ok))
    if env['mode'] == 'run':
        jobs, fn = [(i, lb, e, s, sd) for i, (lb, e) in enumerate(pts) if info[i][2] for s in e['scenarios'] for sd in seeds(e)], run_one
    elif env['mode'] == 'search':
        jobs, fn = [(i, lb, e) for i, (lb, e) in enumerate(pts)], search_one
    else:
        jobs, fn = [(i, lb, e, v) for i, (lb, e) in enumerate(pts) for v in e['tune_values']], tune_one
    print(f'{name}: {env["mode"]}, 점 {len(pts)}개, 작업 {len(jobs)}개', flush=True)
    t0 = time.time()
    with Pool(a.jobs) as p:
        rows = p.map(fn, jobs, chunksize=1)
    os.makedirs(OUT, exist_ok=True)
    stem = os.path.join(OUT, name)
    write_csv(stem + '.csv', point_rows(env, pts, info, rows))
    write_csv(stem + '_runs.csv.gz', job_rows(env, rows))
    print(table(env, pts, info, rows))
    print(f'{len(jobs)}개, {time.time() - t0:.0f} s → {os.path.relpath(stem, ROOT)}{{.csv,_runs.csv.gz}}')


if __name__ == '__main__':
    main()
