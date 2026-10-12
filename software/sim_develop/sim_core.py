"""sim_core.py — P3.5 공통 시뮬레이터: 요청 도착(실측 PCIe 지연), 실측 비용 모델, 이벤트 루프, 지표

부품(저장 정책·스케줄러·연산 방식)은 policies.py에 있고, 이 파일은 부품이 무엇이든 같은 방식으로
요청을 만들고 시간을 진행하고 지표를 낸다. 시간 단위는 µs, 바이트/µs = MB/s.

진행 방식 (한 묶음 앞을 미리 정하는 1단 선행):
  1. 결정 시각 T에 스케줄러가 다음 모델 m을 고른다(pick).
  2. 저장 정책이 m에 필요한 그룹별 적재 바이트를 정한다(plan, 캐시 상태 갱신).
  3. 연산 방식이 DMA·연산 시각을 계산한다. 첫 그룹 연산이 시작되는 시각 s에 묶음 구성원을
     확정한다(members): T 이후 s까지 도착한 같은 모델 요청도 합류한다.
  4. 다음 결정 시각은 s다. 따라서 묶음 i가 연산하는 동안 묶음 i+1의 가중치를 가져온다.
"""
import heapq
import math
import os
import sys
from dataclasses import dataclass

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'software', 'analysis_develop'))
from bram_plan import tiles  # noqa: E402  P3.4 타일 계산식을 그대로 쓴다

# ---- 고정 조건 (SIM_PLAN §1) -------------------------------------------------
P = 32_000.0            # 주기 = 마감, µs
M = 40                  # 모델 수
T0 = 0.244              # DDR3 슬라이스 고정 비용 µs (P3.1 RBC 회귀)
BW = 3015.0             # DDR3 유효 대역폭 B/µs (3.015 GB/s)
CLK = 0.01              # 100 MHz 한 사이클 µs
OVH = 1.10              # 제어 오버헤드 10 % (가정)
ARCH_L = (40, 384, 256, 64, 2)   # 모델 L (P3.6 확정). configure(arch=...)로 바꾼다
PARAM_B = 1412          # β·vth 706 × 2 B (MODEL_MEMORY_LAYOUT). configure가 구조에 맞게 다시 정함
NEURONS = [(384, 40), (256, 384), (64, 256)]     # 은닉층 (뉴런 수, 입력 수). 출력층 = 2뉴런 × 64입력
XDMA_T = 20.5           # P3.2 실측
MEM_CAP = 64            # 막전위를 DDR3에 둘 때 한 줄씩 묶음의 막전위 버퍼 트랙 수(가정)
BW_W = 2768.0           # DDR3 순차 쓰기 B/µs (P3.1 rbc, 1 KiB 버스트). rev 2의 막전위 쓰기에 사용
IN_B = 64               # 요청 하나의 입력(mel 40 B + 트랙·순서 정보), P3.2 큐 항목 512 bit
H2C_BW, C2H_BW = 758.0, 566.0      # 호스트 DMA 처리량 B/µs (P3.3, 4 MiB)


def _pow2(n):
    return 1 << (n - 1).bit_length()


def configure(lanes=32, tracks=512, wbits=8, mem='auto', mem_cap=MEM_CAP, rev=1, arch=ARCH_L):
    """레인 수·트랙 수·막전위 위치에 따라 그룹·비용·타일 상수를 정한다. 기본(32, 512)이 SIM_PLAN §1 기준 환경.

    출력 고정 L레인: word = L × wbits bit, 뉴런 그룹 = L뉴런 × 입력 전체, 1 word/사이클.
    층의 뉴런 수가 L보다 적으면(128레인의 층 3) 그 그룹은 레인 일부만 쓴다. 층 4(2뉴런 × 64입력)는
    word에 묶어 2 × 64 / L word(최소 1)로 둔다.
    wbits = 6이면 DDR3에는 6 bit로 채워 저장하고 DMA가 256 → 192 bit로 바꾼다고 가정한다(P3.6).
    mem: 'onchip'이면 막전위(트랙당 706 × 2 B)를 BRAM에, 'ddr'이면 DDR3에 두고 요청마다 읽기·쓰기
    2,824 B를 DMA에 더한다. 'auto'는 BRAM에 들어가면 온칩. DDR3에 두면 막전위 준비 버퍼가 연산 방식마다
    다르다(한 번에: 트랙 2개분, 한 줄씩: 묶음 전체 = mem_cap 트랙분, 묶음도 mem_cap으로 제한).
    rev 2 (MODEL_SIZE_PLAN §4.2, 트랙이 많을 때의 가정 보강):
      - 한 줄씩은 막전위 위치와 상관없이 묶음 ≤ mem_cap. 입력·층간 스파이크 버퍼 mem_cap × 128 B를 BRAM에 둔다
        (입력 40 + 층1 48 + 층2 32 + 층3 8 B. 그룹 순서로 돌면 묶음 전체 트랙의 앞 층 스파이크를 들고 있어야 함)
      - 막전위 DDR3 쓰기는 순차 쓰기 실측 대역폭(BW_W)으로 계산
    rev 3 = rev 2 + 엔트리 깊이를 실제 word 수로(2의 거듭제곱으로 올리지 않음)
    rev 4 = rev 3 + 슬라이스 이중 버퍼 한 칸 = max(512, 가장 큰 뉴런 그룹 word 수). 한 줄씩은 묶음의 트랙마다 그룹 전체를
            다시 읽으므로 그룹이 한 칸에 다 들어가야 한다. L은 가장 큰 그룹이 384 word라 rev 3과 같고,
            XL 128·256레인은 층 2 그룹이 768 word라 칸이 커진다(256레인 57 → 85.5 타일)
    arch: 층 크기 (입력, 은닉…, 출력). 시뮬레이터는 크기(바이트·뉴런·사이클)만 쓰므로 학습된 가중치가 없어도 된다.
    예: XL = (40, 768, 512, 128, 2)"""
    g = globals()
    L = lanes
    word = L * wbits // 8                     # word 바이트: 32레인 INT8 = 32 B(256 bit), INT6 = 24 B(192 bit)
    hidden = list(zip(arch[1:-1], arch[:-2]))           # 은닉층 (뉴런 수, 입력 수)
    neu = sum(arch[1:])                                  # 뉴런 수 (L 706)
    param_b = 2 * neu                                    # β·vth (L 1,412 B)
    groups, g_bytes = [], []
    for li, (n, fan_in) in enumerate(hidden):
        for k in range(-(-n // L)):
            groups.append((f'L{li + 1}', fan_in))
            g_bytes.append(fan_in * min(L, n - k * L) * wbits // 8)
    n_o = arch[-1] * arch[-2]                            # 출력층 가중치 수 (L 2 × 64)
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
        # 엔트리(모델 1벌) = 가중치 + β·vth. rev ≤ 2는 깊이를 2의 거듭제곱으로 올림(L 32레인 4,068 → 4,096),
        # rev 3은 실제 word 수 그대로(주소 = 시작 + 오프셋이면 충분). 넓은 레인·큰 모델에서 차이가 크다(XL 256레인 229 → 143.5)
        ENTRY_T=tiles(words if rev >= 3 else _pow2(words), 8 * word) + tiles(neu, 16),   # 29 (L 32레인)
        SLICE_T=slice_t,                                                 # 슬라이스 이중 버퍼
        SLOT_WORDS=slot,                                                 # 이중 버퍼 한 칸의 word 수
        MEM_OFFCHIP=offchip,
        MEM_ONCHIP_T=mem_t,                                              # 온칩에 둘 때의 막전위 타일
        MEM_T=0.0 if offchip else mem_t,
        MEMBUF_TRACK_T=tiles(2 * neu, 16) if offchip else 0.0,           # 한 번에: 트랙 2개분 준비 버퍼
        MEMBUF_T=tiles(mem_cap * neu, 16) if offchip else 0.0,           # 한 줄씩: 묶음 막전위 버퍼
        MEM_B=2 * neu * 2 if offchip else 0,                             # 요청당 막전위 읽기 + 쓰기
        MEM_RD=neu * 2 if offchip else 0,
        WRATIO=BW_W / 3015.0 if rev >= 2 else 1.0,                       # 쓰기 대역폭 / 읽기 대역폭
        BATCH_CAP=mem_cap if (offchip or rev >= 2) else None,
        SPK_T=tiles(mem_cap * (arch[0] + sum(arch[1:-1]) // 8), 8) if rev >= 2 else 0.0,  # 한 줄씩 묶음 입력·스파이크 버퍼 (L 128 B)
        REV=rev,
    )
    # 가중치·β·vth·적재 버퍼·막전위 준비 버퍼 예산: 365 − XDMA − 온칩 막전위 (음수면 배치 불가)
    g['TILE_BUDGET'] = 365 - XDMA_T - g['MEM_T']
    g['ZERO'] = [0] * len(groups)
    g['FULL'] = [g_bytes[0] + param_b] + g_bytes[1:]                     # β·vth는 첫 그룹에 붙임
    g['L2L4'] = [0] * nl1 + g_bytes[nl1:]


configure()


def xfer_time(nbytes):
    """DMA 한 번(쉬던 DMA를 새로 시작)의 시간"""
    return T0 + nbytes / BW if nbytes else 0.0


def mem_time(k):
    """요청 k개의 막전위 읽기 + 쓰기 DMA 시간 µs (막전위 온칩이면 0)"""
    return k * (MEM_RD / BW + MEM_RD / (BW * WRATIO)) if MEM_RD else 0.0


# ---- 요청열 ------------------------------------------------------------------
PCIE_RAW = os.path.join(ROOT, 'software', 'analysis_develop', 'p3_meas', 'raw', 'pcie')
D_IN_FILE = 'p3_h2c_64_p62.5.txt'      # 64 B H2C, 62.5 µs 간격(= 16 kHz 요청률)
D_OUT_FILE = 'p3_c2h_64.txt'           # 64 B C2H, 연속
H_IN_FILE = 'p3_h2c_64_p1000.txt'      # 호스트 묶음 전송(host=W_h): 64 B H2C, 1 ms 간격
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
    out_w: float = 0.0          # 호스트 결과 읽기 주기 µs (0 = 요청마다 d_out)
    out_phi: float = 0.0        # 결과 읽기 시각 = out_phi + j × out_w
    out_lat: np.ndarray = None  # j번째 결과 읽기(C2H)의 지연 µs

    def done(self, fin, idx):
        """연산 완료 시각 fin인 요청 idx의 결과가 호스트에 도착하는 시각"""
        if not self.out_w:
            return fin + self.d_out[idx]
        j = np.ceil((fin - self.out_phi) / self.out_w).astype(np.int64)
        return self.out_phi + j * self.out_w + self.out_lat[np.minimum(j, self.out_lat.size - 1)]


ZIPF = 1.0 / np.arange(1, M + 1)
ZIPF /= ZIPF.sum()              # 모델 k의 트랙 비율 ∝ 1/(k+1): 상위 5모델 53.4 %, 1위 23.4 %


# 요청 시나리오 (MODEL_SIZE_PLAN §2.1). make_workload 인자로 넘긴다
SCENARIOS = {
    'U': dict(),                            # 균등: 모델 균등 배정, 트랙마다 위상 무작위
    'K': dict(dist='zipf'),                 # 편중: 몇 개 모델에 트랙이 몰림
    'S': dict(phase=0.0),                   # 동시: 모든 채널을 같은 클럭으로 샘플 → 512개 동시 도착
    'I': dict(p_req=0.25),                  # 띄엄띄엄: 주기마다 요청 확률 0.25 (가정)
    'SK': dict(phase=0.0, dist='zipf'),     # 동시 + 편중
    'R': dict(congestion=(0.25, 1.0)),      # 무작위 혼잡도: 주기마다 활성 비율을 0.25~1에서 무작위로 (MODEL_SIZE_PLAN §4.2)
}


def make_workload(n_tracks=512, seed=0, warm=16, meas=64, d_host=0.0,
                  d_in=None, d_out=None, phase=None, track_model=None, dist='uniform', p_req=1.0,
                  congestion=None, host=None):
    """warm·meas는 주기 수. d_in·d_out: None이면 실측 표본, 숫자면 상수.
    dist: 트랙→모델 배정. 'uniform' 균등 무작위, 'zipf' 편중(가정).
    phase: None이면 트랙별 무작위 위상, 숫자·배열이면 그 위상. p_req: 주기마다 요청을 낼 확률.
    congestion: (lo, hi)면 주기마다 활성 비율 c ~ U(lo, hi)를 정하고 트랙마다 확률 c로 요청.
    host: None이면 요청마다 DMA 1회(d_in·d_out). 숫자 W_h(µs)면 호스트가 W_h마다 그사이 생긴 입력을 모아
          H2C 1회(지연 = 1 ms 주기 실측 표본 + (크기 − 64 B) / H2C_BW)로 보내고, 결과도 W_h마다 C2H 1회로 읽는다."""
    rng = np.random.default_rng(seed)
    if track_model is not None:
        tm = np.asarray(track_model)
    elif dist == 'zipf':
        tm = rng.choice(M, n_tracks, p=ZIPF)
    else:
        tm = rng.integers(0, M, n_tracks)
    ph = rng.uniform(0, P, n_tracks) if phase is None else np.broadcast_to(np.asarray(phase, float), (n_tracks,)).copy()
    k = np.arange(warm + meas)
    t_gen = (ph[:, None] + P * k[None, :]).ravel()
    model = np.repeat(tm, warm + meas)
    n = t_gen.size
    di = rng.choice(load_samples(D_IN_FILE), n) if d_in is None else np.full(n, float(d_in))
    do = rng.choice(load_samples(D_OUT_FILE), n) if d_out is None else np.full(n, float(d_out))
    t_arr = t_gen + d_host + di
    if p_req < 1.0:                                   # 다른 난수열에 영향을 주지 않도록 별도 생성기
        keep = np.random.default_rng(seed + 7777).random(n) < p_req
        t_gen, t_arr, model, do = t_gen[keep], t_arr[keep], model[keep], do[keep]
    if congestion is not None:
        r2 = np.random.default_rng(seed + 8888)
        c = r2.uniform(*congestion, warm + meas)
        keep = r2.random(t_gen.size) < np.tile(c, n_tracks)
        t_gen, t_arr, model, do = t_gen[keep], t_arr[keep], model[keep], do[keep]
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
    return Workload(n_tracks, seed, tm, t_gen[o], t_arr[o], model[o], do[o], warm * P, (warm + meas) * P, **extra)


# ---- 준비된 요청 집합 ---------------------------------------------------------
class Ready:
    """도착했고 아직 묶음에 들어가지 않은 요청. 도착 순서·마감 순서·모델별 목록을 함께 유지"""

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
    """stop_on_miss: 측정 구간 요청이 하나라도 마감을 넘으면 즉시 {'miss': 1}을 돌려준다(최대 트랙 탐색용)
    detail: 연산 배열의 사이클 회계(연산·정지·유휴)와 응답 시간 분해를 지표에 더한다(cycle_stats)"""
    storage.reset(wl)
    scheduler.reset()
    compute.reset()
    compute.log = [] if detail else None
    rd = Ready(wl)
    finish = np.full(wl.t_arr.size, np.nan)
    bat_k, bat_s, bat_b, bat_hit, bat_x = [], [], [], [], []
    T = 0.0
    while True:
        rd.advance(T)
        if rd.count == 0:
            na = rd.next_arrival()
            if na is None:
                break
            T = max(T, na)
            rd.advance(T)
        if hasattr(scheduler, 'busy_until'):           # 점수2·3의 마감 가드: 진행 중인 묶음이 끝나는 시각
            scheduler.busy_until = getattr(compute, 'cmp_free', T)
        m, head = scheduler.pick(rd, T, storage)
        if m is None:                                   # 스케줄러가 일부러 기다림(점수3): head = 다시 고를 시각
            T = max(head, T)
            continue
        loads = storage.plan(m)
        taken = []

        def members(s, m=m, head=head):
            rd.advance(s)
            idx = scheduler.members(rd, m, head, s)
            cap = compute.max_batch()
            if cap and len(idx) > cap:                     # 막전위 버퍼 한도: 마감 순서로 자름
                idx = sorted(idx, key=lambda i: wl.t_gen[i])[:cap]
            rd.take(m, idx)
            taken.extend(idx)
            return len(idx)

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
        bat_x.append(compute.xfers(loads))             # 이 묶음의 가중치 DMA 횟수
        bat_hit.append(sum(loads) == 0)
        T = s
    res = metrics(wl, finish, np.array(bat_k), np.array(bat_s), np.array(bat_b), np.array(bat_hit),
                  compute, np.array(bat_x))
    if detail:
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
    """측정 구간의 연산 배열 사이클 회계(100 MHz)와 응답 시간 분해.
      연산 = 연산 배열이 묶음을 계산한 사이클(제어 오버헤드 10 % 포함)
      정지 = FPGA에 도착한 요청이 남아 있는데 연산 배열이 쉰 사이클(가중치·막전위 DMA 대기)
      유휴 = FPGA 안에 처리할 요청이 없는 사이클.  연산 + 정지 + 유휴 = 측정 구간
    응답 시간 = 입력(생성 → FPGA 도착: 호스트 묶음 대기 + H2C) + FPGA(도착 → 연산 완료: 큐 대기 + DMA 대기 + 연산)
              + 출력(연산 완료 → 결과가 호스트에 도착: 결과 읽기 대기 + C2H)"""
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
        'cyc_n': n_win,                                         # 측정 구간에 연산을 시작한 요청 수(요청당 사이클의 분모)
        'in_ms': float((wl.t_arr - wl.t_gen)[sel].mean() / 1000),
        'fpga_ms': float((finish - wl.t_arr)[sel].mean() / 1000),
        'out_ms': float((done - finish)[sel].mean() / 1000),
    }


def metrics(wl, finish, k, s, b, hit, compute, x=None):
    resp = wl.done(finish, np.arange(finish.size)) - wl.t_gen
    sel = wl.t_gen >= wl.w0
    r = resp[sel]
    win = (s >= wl.w0) & (s < wl.w1)
    span = wl.w1 - wl.w0
    return {
        'n_req': int(sel.sum()),
        'miss': int((r > P).sum()),
        'miss_rate': float((r > P).mean()),
        'mbps': float(b[win].sum() / span),                    # B/µs = MB/s
        'p50_ms': float(np.percentile(r, 50) / 1000),
        'p99_ms': float(np.percentile(r, 99) / 1000),
        'max_ms': float(r.max() / 1000),
        'mean_ms': float(r.mean() / 1000),
        # 측정 구간에 연산을 시작한 묶음 기준 DDR3 사용량 (에너지·접근 횟수 비교용)
        'req_win': int(k[win].sum()),
        'w_bytes': float(b[win].sum()),                        # 가중치 읽기 B
        'm_bytes': float(k[win].sum() * MEM_B),                # 막전위 읽기 + 쓰기 B
        'w_xfers': int(x[win].sum()) if x is not None else 0,  # 가중치 DMA 횟수
        'batch_mean': float(k[win].mean()),
        'hit_rate': float(hit[win].mean()),
        'dma_util': float((b[win].sum() / BW + mem_time(k[win].sum())) / span),
        'cmp_util': float(k[win].sum() * C_REQ / span),
        'resp': r,                                             # 실행기가 시드 합산 후 지운다
    }
