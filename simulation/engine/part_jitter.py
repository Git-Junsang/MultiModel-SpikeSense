"""part_jitter.py — Host 처리 지연 분포(Jitter). 분포마다 class 하나다. 분포의 꼴은 simulation_engine.md §4.2"""
import functools
import os

import numpy as np

from part_hardware import ROOT
from part_result import read_csv


class Jitter:
    """Host 처리 지연 분포 공통(Host 도착 → 준비, µs). 추론 요청열은 draw로 뽑고 PNU는 delta·quantile·max_us만 쓴다.
    분포 class는 _draw(난수, 트랙 n, 주기 K)와 _surv(x)를 정하고, 최대가 J와 다르면 max_us도 정한다. max_us가 0 이하면
    지연이 없다. trace는 기록을 재생하므로 draw와 _quantile을 직접 정한다"""
    TAIL_SHARE, TAIL_SPLIT_US = 0.05, 800.0   # tail·burst: 5 %, 추론 요청별 지연의 기본 폭 0.8 ms
    closed_form = False                       # δ에 닫힌 식 (J − e) / (r + 1)을 쓴다(균등 분포)

    def __init__(self, jitter_us=0.0):
        self.jitter_us, self._memo = float(jitter_us), {}
        self.max_us = self.jitter_us

    @staticmethod
    @functools.lru_cache(maxsize=None)
    def of(dist, jitter_us=0.0, trace=''):
        """환경 값(host_jitter_dist, J µs, trace CSV) → 분포. 같은 분포는 한 번만 만든다(trace 읽기와 δ 계산을 실행 사이에 같이 쓴다)"""
        return TraceJitter(trace) if dist == 'trace' else JITTERS[dist](jitter_us)

    def draw(self, seed, n, K):
        """(트랙 n, 주기 K) 지연 µs. 다른 난수열과 섞이지 않게 따로 뽑는다"""
        if self.max_us <= 0:
            return np.zeros((n, K))
        return self._draw(np.random.default_rng(seed + 4545), n, K)

    def surv(self, x):
        """S(x) = P(지연 > x)"""
        x = np.asarray(x, float)
        if self.max_us <= 0:
            return np.zeros_like(x)
        return np.clip(np.where(x >= self.max_us, 0.0, np.where(x < 0, 1.0, self._surv(x))), 0.0, 1.0)

    def delta(self, e, r, closed=True):
        """남은 추론 요청 r개가 모두 e 뒤에 온다고 할 때 그중 첫 추론 요청까지 남은 시간의 기대값 µs = ∫_e^max (S(x) / S(e))^r dx.
        closed_form 분포는 닫힌 식(closed = False면 수치 적분)"""
        e = max(0.0, float(e))
        if r <= 0 or e >= self.max_us:
            return 0.0
        if closed and self.closed_form:
            return (self.max_us - e) / (r + 1)
        key = (round(e / 5.0), r, closed)                  # e는 5 µs 단위로 묶어 둔다
        v = self._memo.get(key)
        if v is None:
            e0 = key[0] * 5.0
            s0 = float(self.surv(e0))
            if s0 <= 0 or e0 >= self.max_us:
                v = 0.0
            else:
                x = e0 + (self.max_us - e0) * np.linspace(0, 1, 4001) ** 3     # e 근처를 촘촘히
                y = (np.clip(self.surv(x) / s0, 0, 1)) ** r
                v = float(np.sum((y[1:] + y[:-1]) * np.diff(x)) / 2)
            self._memo[key] = v
        return v

    def quantile(self, q):
        """q 분위수 µs (q ≥ 1이면 최대)"""
        if self.max_us <= 0:
            return 0.0
        if q >= 1:
            return self.max_us
        return self._quantile(q)

    def _quantile(self, q):
        x = np.linspace(0, self.max_us, 20001)
        return float(x[np.searchsorted(-self.surv(x), -(1 - q))])

    def _draw(self, r, n, K):
        raise NotImplementedError

    def _surv(self, x):
        raise NotImplementedError


class NoJitter(Jitter):
    """none: 지연 없음"""

    def __init__(self, jitter_us=0.0):
        super().__init__(jitter_us)
        self.max_us = 0.0


class UniformJitter(Jitter):
    """uniform: 추론 요청·주기마다 U(0, J)"""
    closed_form = True

    def _draw(self, r, n, K):
        return r.uniform(0, self.jitter_us, (n, K))

    def _surv(self, x):
        return 1 - x / self.jitter_us


class StaticJitter(UniformJitter):
    """static: 트랙마다 U(0, J) 하나를 모든 주기에 쓴다(cache는 모른다). 분포는 uniform과 같다"""

    def _draw(self, r, n, K):
        return np.repeat(r.uniform(0, self.jitter_us, (n, 1)), K, 1)


class TailJitter(Jitter):
    """tail: (1 − share)는 U(0, b), share는 U(b, J). b = min(0.8 ms, J)"""
    share = Jitter.TAIL_SHARE

    def _draw(self, r, n, K):
        J = self.jitter_us
        b, p = min(self.TAIL_SPLIT_US, J), self.share
        u, lo, hi = r.random((n, K)), r.uniform(0, b, (n, K)), r.uniform(b, J, (n, K))
        return np.where(u < 1 - p, lo, hi)

    def _surv(self, x):
        J = self.jitter_us
        b, p = min(self.TAIL_SPLIT_US, J), self.share
        if J <= b:                                     # J ≤ 0.8 ms면 꼬리 몫이 정확히 J에 몰린다
            return np.where(x < J, (1 - p) * (1 - x / J) + p, 0.0)
        return np.where(x < b, (1 - p) * (1 - x / b) + p, p * (J - x) / (J - b))


class Tail1Jitter(TailJitter):
    """tail1: tail과 같은 꼴로 1 %"""
    share = 0.01


class BurstJitter(Jitter):
    """burst: 주기마다 확률 5 %로 모든 추론 요청에 공통 U(0, J), 그 위에 추론 요청마다 U(0, b). b = min(0.8 ms, J)"""

    def __init__(self, jitter_us=0.0):
        super().__init__(jitter_us)
        self.max_us = self.jitter_us + min(self.TAIL_SPLIT_US, self.jitter_us)

    def _draw(self, r, n, K):
        J = self.jitter_us
        on, c = r.random(K) < self.TAIL_SHARE, r.uniform(0, J, K)
        return np.where(on, c, 0.0)[None, :] + r.uniform(0, min(self.TAIL_SPLIT_US, J), (n, K))

    def _surv(self, x):                                # 95 % U(0, b), 5 % U(0, b) + U(0, J)
        J = self.jitter_us
        b, p = min(self.TAIL_SPLIT_US, J), self.TAIL_SHARE
        return (1 - p) * np.clip(1 - x / b, 0, 1) + p * (1 - sum_uniform_cdf(x, min(b, J), max(b, J)))


class CommonDelayJitter(Jitter):
    """cd: 주기 공통 U(0, J/2) + 추론 요청마다 U(0, J/2). 주기 k의 공통 지연은 nominal 시각이 [kP, (k+1)P)인 추론 요청이 같이 받는다"""

    def _draw(self, r, n, K):
        J = self.jitter_us
        return r.uniform(0, J / 2, K)[None, :] + r.uniform(0, J / 2, (n, K))

    def _surv(self, x):                                # U(0, J/2) + U(0, J/2): 삼각 분포
        return 1 - sum_uniform_cdf(x, self.jitter_us / 2, self.jitter_us / 2)


class TraceJitter(Jitter):
    """trace: 측정 기록 재생. 모델 묶음 지연 표(epoch, model_id, delay_us. 행 = 모델)나 추론 요청별 기록(epoch, track_id, t_gen_us,
    t_ready_us. 행 = 트랙)을 읽는다. 앞 절반 주기는 분포 추정(calib), 뒤 절반은 재생(replay). 빠진 칸은 그 행의 중앙값"""

    def __init__(self, trace):
        super().__init__(0.0)
        rows = read_csv(trace if os.path.isabs(trace) else os.path.join(ROOT, trace))
        self.by_model = 'track_id' not in rows[0]
        col = 'model_id' if self.by_model else 'track_id'
        trk = sorted({int(r[col]) for r in rows})
        eps = sorted({int(r['epoch']) for r in rows})
        ti, ei = {t: i for i, t in enumerate(trk)}, {k: i for i, k in enumerate(eps)}
        D = np.full((len(trk), len(eps)), np.nan)
        for r in rows:
            D[ti[int(r[col])], ei[int(r['epoch'])]] = (float(r['delay_us']) if self.by_model
                                                       else float(r['t_ready_us']) - float(r['t_gen_us']))
        if np.isnan(D).any():
            D = np.where(np.isnan(D), np.nanmedian(D, 1, keepdims=True), D)
        half = max(1, len(eps) // 2)
        self.calib, self.replay = np.sort(D[:, :half].ravel()), D[:, half:] if len(eps) > 1 else D
        self.max_us = float(self.calib.max())

    def draw(self, seed, n, K):
        """행·주기를 돌려 쓴다. 묶음 표는 seed마다 다른 주기부터. 난수는 쓰지 않는다"""
        T, E = self.replay.shape
        s = seed * K if self.by_model else 0
        return self.replay[np.arange(n)[:, None] % T, (s + np.arange(K))[None, :] % E]

    def _surv(self, x):
        return 1.0 - np.searchsorted(self.calib, x, side='right') / self.calib.size

    def _quantile(self, q):
        return float(np.quantile(self.calib, q))


def sum_uniform_cdf(x, a, c):
    """U(0, a) + U(0, c)의 CDF (a ≤ c)"""
    x = np.asarray(x, float)
    return np.select([x <= 0, x <= a, x <= c, x <= a + c],
                     [0.0, x ** 2 / (2 * a * c), (2 * x - a) / (2 * c), 1 - (a + c - x) ** 2 / (2 * a * c)], 1.0)


JITTERS = {'none': NoJitter, 'uniform': UniformJitter, 'tail': TailJitter, 'tail1': Tail1Jitter, 'burst': BurstJitter,
           'cd': CommonDelayJitter, 'static': StaticJitter, 'trace': TraceJitter}   # host_jitter_dist 값 → 분포
