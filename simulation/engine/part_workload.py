"""part_workload.py — 추론 요청열(Workload), 추론 요청 시나리오, 링크 지연 표본. 시각 열과 만드는 순서는 simulation_engine.md §4"""
import os
from dataclasses import dataclass

import numpy as np

from part_hardware import PERIOD_US, ROOT

PCIE_SAMPLE_DIR = os.path.join(ROOT, 'hardware', 'board_test', 'p3_meas', 'result', 'raw', 'pcie')
LINK_IN_FILE = 'p3_h2c_64_p62.5.txt'   # 링크 지연 표본: 64 B H2C, 62.5 µs 간격(16 kHz 추론 요청률)
LINK_OUT_FILE = 'p3_c2h_64.txt'        # 64 B C2H, 연속
PACKET_REQUESTS = 23                   # MTU 1,500 B packet 하나에 들어가는 64 B 추론 요청 수

SCENARIOS = {                           # 추론 요청 시나리오. Workload.make 인자로 넘긴다
    'U': dict(),                        # 균등 배정, 트랙마다 무작위 offset
    'K': dict(dist='zipf'),             # 편중 배정
    'S': dict(offset=0.0),              # 동시 시작
    'I': dict(p_req=0.25),              # 간헐 추론 요청: 주기마다 추론 요청 확률 0.25
    'SK': dict(offset=0.0, dist='zipf'),
    'R': dict(congestion=(0.25, 1.0)),  # 활성 트랙 변화: 주기마다 활성 비율을 0.25~1에서 무작위로
}


def link_samples(name):
    """PCIe 64 B 전송 지연 실측 표본 µs (P3.3)"""
    return np.loadtxt(os.path.join(PCIE_SAMPLE_DIR, name)) / 1000.0


def zipf_share(M):
    """편중 배정 비율. 모델 k의 트랙 비율 ∝ 1/(k+1)"""
    z = 1.0 / np.arange(1, M + 1)
    z /= z.sum()
    return z


@dataclass
class Workload:
    """추론 요청열 하나. 추론 요청별 배열은 FPGA 도착(t_arr) 순서다"""
    n_tracks: int
    seed: int
    track_model: np.ndarray     # 트랙 → 모델
    t_host: np.ndarray          # Host 도착(frame 마지막 샘플). deadline 기준
    t_arr: np.ndarray           # FPGA 도착
    model: np.ndarray
    d_out: np.ndarray           # 결과 C2H 지연
    w0: float                   # 측정 구간 [w0, w1)
    w1: float
    cost: np.ndarray = None     # 추론 요청별 연산 µs. None = 모두 dense_req_us
    track: np.ndarray = None    # 추론 요청별 트랙
    t_ready: np.ndarray = None  # Host 준비 완료
    t_send: np.ndarray = None   # Host 송신
    epoch: np.ndarray = None    # 추론 요청별 주기 번호 k (t_host = 트랙 offset + k × 주기)
    nominal: np.ndarray = None  # 트랙별 nominal offset µs (Host가 아는 값)
    jitter: object = None       # 추론 요청별 지연 분포(Jitter). PNU가 분포로만 쓴다
    group: object = None        # 모델 묶음 지연 분포(Jitter). None = 없음
    drop_busy: bool = False     # 같은 트랙의 이전 추론 요청이 끝나기 전에 온 추론 요청은 버린다(06 §4.3)
    hw: object = None           # 추론 요청열을 만든 하드웨어 조건(모델 수, 연산 비용)

    @staticmethod
    def draw_tracks(M, n, seed, dist):
        """(트랙 → 모델, 무작위 offset). make와 같은 순서로 같은 난수를 뽑는다"""
        rng = np.random.default_rng(seed)
        tm = rng.choice(M, n, p=zipf_share(M)) if dist == 'zipf' else rng.integers(0, M, n)
        return tm, rng.uniform(0, PERIOD_US, n)

    @classmethod
    def make(cls, hw, n_tracks=512, seed=0, warm=16, meas=64, d_in=None, d_out=None, offset=None, track_model=None,
             dist='uniform', p_req=1.0, congestion=None, spike=False, jit=None, jitter=None, group=None, drop_busy=False):
        """추론 요청열을 만든다. warm·meas는 주기 수, d_in·d_out은 None이면 링크 지연 실측 표본이고 수를 주면 그 상수, offset은
        None이면 트랙마다 무작위, spike면 추론 요청별 연산을 golden spike 수로. Host 처리 지연은 jit((트랙, 주기) µs)를 주면 그대로 쓰고,
        없으면 분포 jitter의 추론 요청별 지연 + 분포 group의 (모델, 주기) 묶음 지연이다. jitter·group은 PNU가 아는 분포로 남는다"""
        M = hw.models
        rng = np.random.default_rng(seed)
        if track_model is not None:
            tm = np.asarray(track_model)
        elif dist == 'zipf':
            tm = rng.choice(M, n_tracks, p=zipf_share(M))
        else:
            tm = rng.integers(0, M, n_tracks)
        offs = rng.uniform(0, PERIOD_US, n_tracks) if offset is None else np.broadcast_to(np.asarray(offset, float), (n_tracks,)).copy()
        K = warm + meas
        k = np.arange(K)
        t_host = (offs[:, None] + PERIOD_US * k[None, :]).ravel()
        model = np.repeat(tm, K)
        trk = np.repeat(np.arange(n_tracks), K)
        n = t_host.size
        di = rng.choice(link_samples(LINK_IN_FILE), n) if d_in is None else np.full(n, float(d_in))
        do = rng.choice(link_samples(LINK_OUT_FILE), n) if d_out is None else np.full(n, float(d_out))
        if jit is None and (jitter is not None or group is not None):
            jit = jitter.draw(seed, n_tracks, K) if jitter is not None else np.zeros((n_tracks, K))
            if group is not None:                          # 모델 묶음 지연을 더한다. Host는 트랙의 frame을 차례로 처리한다
                # shortcut: group은 재생(TraceJitter)만 쓴다. 분포 class를 넣으면 jitter와 같은 난수열을 쓰므로 그때 seed를 나눈다
                kP = PERIOD_US * k
                jit = np.maximum.accumulate(jit + group.draw(seed, M, K)[tm] + kP, 1) - kP
        t_ready = t_host if jit is None else t_host + np.asarray(jit, float).ravel()
        t_arr = t_ready + di
        cost = hw.spike_req_us(tm, k, seed) if spike else None
        keep = np.ones(n, bool)
        if p_req < 1.0:                                    # 간헐 추론 요청. 다른 난수열과 섞이지 않게 따로 뽑는다
            keep &= np.random.default_rng(seed + 7777).random(n) < p_req
        if congestion is not None:                         # 주기마다 활성 비율 c ~ U(lo, hi), 트랙마다 확률 c로 추론 요청
            r2 = np.random.default_rng(seed + 8888)
            c = r2.uniform(*congestion, K)
            keep &= r2.random(n) < np.tile(c, n_tracks)
        wl = cls(n_tracks, seed, tm, t_host, t_arr, model, do, warm * PERIOD_US, K * PERIOD_US, cost=cost, track=trk, t_ready=t_ready,
                 t_send=np.array(t_ready, float), epoch=np.tile(k, n_tracks), nominal=offs, jitter=jitter, group=group,
                 drop_busy=drop_busy, hw=hw)
        wl.filter(keep, order=np.argsort(t_arr, kind='stable'))
        return wl

    def gather(self, starts, wait_us):
        """모아 보내기: 모델·주기마다 다 준비되거나 starts[모델] + 주기 시작 + wait_us가 되면 한꺼번에 보낸다(t_send)"""
        s0 = starts[self.model]
        k = np.floor((self.t_host - s0) / PERIOD_US)
        _, g = np.unique(self.model * 1_000_000 + k.astype(np.int64), return_inverse=True)
        last = np.full(g.max() + 1, -np.inf)
        np.maximum.at(last, g, self.t_ready)
        send = np.maximum(self.t_ready, np.minimum(last[g], s0 + k * PERIOD_US + wait_us))
        self.t_arr = self.t_arr + (send - self.t_ready)
        self.t_send = send
        self.filter(np.ones(self.t_arr.size, bool), order=np.argsort(self.t_arr, kind='stable'))

    def packetize(self, gap_us):
        """packet 분할: 같은 모델·주기·송신 시각의 추론 요청을 PACKET_REQUESTS개씩 packet으로 묶고 j번째 packet을 j × gap_us 늦게 도착시킨다"""
        key = self.model.astype(np.int64) * 1_000_000 + self.epoch
        o = np.lexsort((self.track, self.t_send, key))
        k, t = key[o], self.t_send[o]
        new = np.r_[True, (k[1:] != k[:-1]) | (t[1:] != t[:-1])]       # 묶음의 첫 추론 요청
        i = np.arange(o.size)
        add = np.zeros(o.size)
        add[o] = ((i - np.maximum.accumulate(np.where(new, i, 0))) // PACKET_REQUESTS) * gap_us
        self.t_arr = self.t_arr + add
        self.filter(np.ones(self.t_arr.size, bool), order=np.argsort(self.t_arr, kind='stable'))

    def delay(self, us):
        """t_host 뒤 송신 전에 모든 추론 요청에 같은 지연 us를 더한다. 응답 시간에 들어간다"""
        self.t_arr = self.t_arr + us
        self.t_ready, self.t_send = self.t_ready + us, self.t_send + us

    def recv_time(self, fin, idx):
        """연산 완료 시각 fin인 추론 요청 idx의 결과가 Host에 도착하는 시각(t_recv)"""
        return fin + self.d_out[idx]

    def filter(self, keep, order=None):
        """추론 요청을 keep(bool)만 남긴다. order를 주면 그 순서로 다시 줄 세운다"""
        idx = np.flatnonzero(keep) if order is None else order[keep[order]]
        for f in ('t_host', 't_arr', 'model', 'd_out', 'cost', 'track', 't_ready', 't_send', 'epoch'):
            v = getattr(self, f)
            if v is not None:
                setattr(self, f, v[idx])
