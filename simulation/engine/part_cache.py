"""part_cache.py — weight cache 교체 정책. 모두 entry 여러 벌에 모델 weight를 두고 miss면 victim을 내보낸다.
규칙과 진단 값, PNU 식은 simulation_engine.md §6.1"""
import math
from collections import OrderedDict

import numpy as np

from part_hardware import PERIOD_US, Part
from part_jitter import Jitter
from part_result import PRED_ERR_BIN_US


class Cache(Part):
    """Cache 정책 공통: weight entry 여러 벌. hit면 적재 0, miss면 모델 전체를 빈 entry에 적재한다. Entry가 차면
    연산 중인 entry를 뺀 entry 중 다음 사용 점수(predict)가 가장 큰 모델을 내보낸다. 점수가 같으면 queue가 빈 모델,
    그다음 오래 안 쓴 모델. 측정 구간의 교체마다 실제 다음 사용과 비교해 진단 값을 센다(결정에는 쓰지 않는다)"""
    meta_tiles = 0.0                 # 예측 메타데이터 BRAM tile
    queue_first = True               # 점수가 같으면 대기 추론 요청이 있는 모델을 지킨다
    scored = True                    # predict가 다음 사용 시각을 낸다(예측 오차를 센다)
    queue = now = None               # plan이 받은 queue와 시각(predict와 진단이 쓴다)

    def __init__(self, hw, entries=None, budget=None, **attrs):
        super().__init__(hw, **attrs)
        budget = hw.tile_budget - hw.membrane_buf_tiles if budget is None else budget
        self.entries = entries or max(0, int((budget - self.meta_tiles) // hw.entry_tiles))   # 기본 = 예산에 들어가는 최대

    def tiles(self):
        return self.entries * self.hw.entry_tiles + self.meta_tiles

    def reset(self, wl):
        self.wl, self.loaded = wl, OrderedDict()                       # 적재된 모델, 앞 = 오래 안 쓴 모델
        self.arrivals = [wl.t_arr[wl.model == m] for m in range(self.hw.models)]   # 모델별 도착 시각. 진단·Oracle MIN 전용
        self.evictions = self.wrong_victims = 0
        self.pred_errors, self.lut_errors = [], []

    def peek(self, m):
        """plan과 같은 적재 B. 상태는 바꾸지 않는다"""
        return 0 if m in self.loaded else self.hw.model_bytes

    def plan(self, m, queue, now):
        """시각 now에 모델 m을 연산할 때 적재 B(0 = on-chip에 있음). Entry 상태를 바꾼다"""
        self.queue, self.now = queue, now
        if m in self.loaded:
            self.loaded.move_to_end(m)
            return 0
        if len(self.loaded) >= self.entries:
            cur = next(reversed(self.loaded))
            cand = [x for x in self.loaded if x != cur]
            t = self.predict(cand)
            nq = [not self.queue.by_model[x] or not self.queue_first for x in cand]
            v = max(range(len(cand)), key=lambda i: (t[i], nq[i], -i))
            if self.wl.w0 <= self.now < self.wl.w1:
                self._diagnose(cand, t, v)
            del self.loaded[cand[v]]
        self.loaded[m] = True
        return self.hw.model_bytes

    def predict(self, cand):
        """후보 모델마다 다음 사용 점수(클수록 먼저 내보낸다)"""
        raise NotImplementedError

    def stats(self):
        """측정 구간 교체의 진단 값"""
        err = np.asarray(self.pred_errors, float)
        h = np.bincount(np.minimum((err / PRED_ERR_BIN_US).astype(int), 1400)) if err.size else np.zeros(0, int)
        lut = np.asarray(self.lut_errors, float)
        return dict(evictions=self.evictions, wrong_victims=self.wrong_victims, pred_n=int(err.size), pred_abs_sum=float(err.sum()),
                    pred_hist=[[int(j), int(h[j])] for j in np.flatnonzero(h)], lut_n=int(lut.size), lut_abs_sum=float(lut.sum()))

    def _actual_next(self, m):
        """실제 다음 사용 = 대기 추론 요청이 있으면 지금, 없으면 아직 오지 않은 추론 요청 중 가장 이른 도착(미래 정보)"""
        if self.queue.by_model[m]:
            return self.now
        a = self.arrivals[m]
        j = np.searchsorted(a, self.now, side='right')
        return float(a[j]) if j < a.size else float('inf')

    def _diagnose(self, cand, t, v):
        act = [self._actual_next(x) for x in cand]
        self.evictions += 1
        self.wrong_victims += act[v] < max(act)            # Oracle MIN이 고를 수 있는 victim과 다르면
        if self.scored:
            self.pred_errors += [abs(t[i] - act[i]) for i, x in enumerate(cand)
                                 if not self.queue.by_model[x] and math.isfinite(t[i]) and math.isfinite(act[i])]


class LRU(Cache):
    """LRU: 가장 오래 안 쓴 모델을 내보낸다"""
    name, queue_first, scored = 'LRU', False, False

    def predict(self, cand):
        return [0.0] * len(cand)


class OracleMIN(Cache):
    """Oracle MIN: 실제 미래 도착으로 다음 사용이 가장 늦은 모델을 내보낸다. 구현할 수 없는 비교 기준이고,
    batch 순서가 cache 결정에 따라 바뀌므로 적재 수 하한은 아니다(하한은 belady)"""
    name = 'Oracle MIN'

    def predict(self, cand):
        return [self._actual_next(x) for x in cand]


class OffsetOnly(Cache):
    """Offset-only: 모델 그룹(모델, nominal offset)과 지금 queue만 안다. 대기 추론 요청이 없으면 다음 nominal offset을 다음 사용으로 본다"""
    name = 'offset-only'

    def reset(self, wl):
        super().reset(wl)
        key = np.round(np.asarray(wl.nominal, float) % PERIOD_US, 3)
        pairs, inv = np.unique(np.stack([wl.track_model.astype(float), key], 1), axis=0, return_inverse=True)
        inv = np.asarray(inv).ravel()
        self.group_model, self.group_offset = pairs[:, 0].astype(int), pairs[:, 1]
        self.groups_of_model = [np.flatnonzero(self.group_model == m) for m in range(self.hw.models)]
        self.track_group = inv                                       # 트랙 → 모델 그룹
        self.group_tracks = np.bincount(inv, minlength=len(pairs))   # 모델 그룹의 등록 트랙 수

    def predict(self, cand):
        out = []
        for x in cand:
            off = self.group_offset[self.groups_of_model[x]]
            if self.queue.by_model[x]:
                out.append(self.now)
            elif not off.size:
                out.append(float('inf'))
            else:
                out.append(float((off + PERIOD_US * (np.floor((self.now - off) / PERIOD_US) + 1)).min()))
        return out


class PNU(OffsetOnly):
    """PNU-Count: 모델 그룹마다 지금 주기에 남은 추론 요청 수와 nominal offset(또는 첫 도착) 뒤 경과 시간으로 다음 사용을 예측한다.
    예상 추론 요청 수는 Host가 packet에 싣는 값이고 받은 수는 FPGA가 센다. 미래 도착·난수는 읽지 않는다"""
    name = 'PNU-count'
    count = True                     # False면 PNU-Timeout(예상 추론 요청 수를 모른다)
    pred = 'exact'                   # δ 계산: exact(조건부 기대값) | lut(bin_us 칸 × 남은 수 6칸 표)
    bin_us = 200.0
    tau_q = 1.0                      # τ = 추론 요청별 지연 분포의 이 분위수
    meta_tiles = 0.5
    model_group_delay_aware = True               # 모델 그룹 지연 분포를 쓴다(False = P3.25 식)
    REMAIN_EDGES = (1, 2, 3, 5, 9, 17)                     # 남은 추론 요청 수 칸 아래 끝: 1, 2, 3–4, 5–8, 9–16, 17 이상
    REMAIN_VALUES = (1.0, 2.0, 3.5, 6.5, 12.5, 24.0)       # 칸 대표값(17 이상은 모델당 평균 트랙 수 약 25)

    def reset(self, wl):
        super().reset(wl)
        self.jitter = wl.jitter if wl.jitter is not None else Jitter.of('none')
        self.tau_us = self.jitter.quantile(self.tau_q)
        self.req_group, self.req_period = self.track_group[wl.track], np.asarray(wl.period)    # 추론 요청 → 모델 그룹, 주기
        K = int(self.req_period.max()) + 1 if self.req_period.size else 1
        self.expected = np.zeros((self.group_offset.size, K), np.int64)
        np.add.at(self.expected, (self.req_group, self.req_period), 1)   # Host가 packet에 싣는 주기별 추론 요청 수(seen이 된 칸만 읽는다)
        self.received = np.zeros_like(self.expected)
        self.seen = np.zeros(self.expected.shape, bool)
        self.last_expected, self.last_period = self.group_tracks.copy(), np.full(self.group_offset.size, -1)
        self.n_counted = 0
        self.model_group_delay = wl.model_group_delay if self.model_group_delay_aware and wl.model_group_delay is not None and wl.model_group_delay.max_us > 0 else None
        if self.model_group_delay is not None:
            self.model_group_delay_tau_us, self.model_group_delay_mean_us = self.model_group_delay.quantile(self.tau_q), self.model_group_delay.delta(0.0, 1)
            self.first_arrival = np.full(self.expected.shape, np.nan)   # (모델 그룹, 주기) 첫 도착 시각
        if self.pred == 'lut':
            nb = max(1, math.ceil(self.jitter.max_us / self.bin_us))
            self.lut = np.array([[self.jitter.delta((i + 0.5) * self.bin_us, r) for r in self.REMAIN_VALUES] for i in range(nb)])

    def predict(self, cand):
        self._count_arrivals()
        out = []
        for x in cand:
            if self.queue.by_model[x]:
                out.append(self.now)
            else:
                out.append(min((self._next_use(g, self.now) for g in self.groups_of_model[x]), default=float('inf')))
        return out

    def _count_arrivals(self):
        """지금까지 도착한 추론 요청만 센다"""
        q = self.queue.next_idx
        if q > self.n_counted:
            g, k = self.req_group[self.n_counted:q], self.req_period[self.n_counted:q]
            np.add.at(self.received, (g, k), 1)
            self.seen[g, k] = True
            if self.model_group_delay is not None:
                np.fmin.at(self.first_arrival, (g, k), self.wl.t_arr[self.n_counted:q])
            for gg, kk in zip(g.tolist(), k.tolist()):
                if kk > self.last_period[gg]:
                    self.last_period[gg], self.last_expected[gg] = kk, self.expected[gg, kk]
            self.n_counted = q

    def _delta(self, el, r):
        """남은 추론 요청 r개 중 첫 추론 요청까지의 기대 시간(경과 el)"""
        if self.pred != 'lut':
            return self.jitter.delta(el, r)
        v = self.lut[min(int(el // self.bin_us), self.lut.shape[0] - 1), int(np.searchsorted(self.REMAIN_EDGES, r, 'right')) - 1]
        if self.wl.w0 <= self.now < self.wl.w1:
            self.lut_errors.append(abs(v - self.jitter.delta(el, r)))
        return v

    def _next_use(self, g, now):
        """모델 그룹 g의 다음 사용 시각"""
        off, kn, n_next, r = self._period(g, now)
        if self.model_group_delay is not None:
            return self._next_use_grouped(g, now, off, kn, n_next, r)
        if kn < 0:
            return off + self._delta(0.0, n_next)
        el = now - off - kn * PERIOD_US
        if r > 0 and el < self.tau_us:
            return max(now, off + kn * PERIOD_US + el + self._delta(el, r))
        return off + (kn + 1) * PERIOD_US + self._delta(0.0, n_next)

    def _period(self, g, now):
        """모델 그룹 g의 (nominal offset, offset이 지난 마지막 주기 kn, 다음 주기 예상 수, 이번 주기 남은 추론 요청 수 r).
        PNU-Timeout은 예상 수를 몰라 r = 1"""
        off, K = self.group_offset[g], self.expected.shape[1]
        kn = math.floor((now - off) / PERIOD_US)
        n_next = max(1, int(self.last_expected[g])) if self.count else 1
        if kn < 0 or not self.count:
            return off, kn, n_next, 1
        n = self.expected[g, kn] if kn < K and self.seen[g, kn] else self.last_expected[g]
        return off, kn, n_next, int(n - (self.received[g, kn] if kn < K else 0))

    def _next_use_grouped(self, g, now, off, kn, n_next, r):
        """모델 그룹 지연이 있을 때의 다음 사용(P3.26). 첫 도착 전에는 모델 그룹 지연 분포, 뒤에는 추론 요청별 지연 분포로 본다"""
        nxt = off + (kn + 1) * PERIOD_US + self.model_group_delay_mean_us + self._delta(0.0, n_next)
        if kn < 0:
            return nxt
        a = self.first_arrival[g, kn] if kn < self.expected.shape[1] else np.nan
        if np.isnan(a):                                    # 이번 주기 첫 추론 요청 전: 모델 그룹이 늦어지는 중일 수 있다
            el = now - off - kn * PERIOD_US
            if r > 0 and el < self.model_group_delay_tau_us:
                return now + self.model_group_delay.delta(el, 1)
        elif r > 0 and now - a < self.tau_us:              # 첫 추론 요청 뒤: 그 시각을 모델 그룹 시작으로
            return now + self._delta(now - a, r)
        return nxt


class PNUTimeout(PNU):
    """PNU-Timeout: 예상 추론 요청 수 없이 nominal offset 뒤 τ 동안은 추론 요청이 더 온다고 본다(r = 1)"""
    name, count = 'PNU-timeout', False


class PNURTL(PNU):
    """next_use_predictor.v(P4.3)와 같은 PNU-Count. 시각은 µs 정수로 내리고 δ를 LUT_BIN_US 칸 표로 읽는다. 모델 그룹마다
    가장 최근 주기 하나의 (예상 수, 도착 수, 첫 도착)만 둔다. 추론 요청의 주기는 RTL처럼 도착 시각과 t_host로 정한다"""
    name, pred = 'PNU-count RTL', 'rtl'
    LUT_BIN_US, LUT_BINS = 256, 128
    log = None                       # list면 도착을 (도착 µs, 모델 그룹, t_host µs, 예상 수)로 남긴다

    def reset(self, wl):
        super().reset(wl)
        self.tables = self._tables()
        n = self.group_offset.size
        self.offset_us = np.rint(self.group_offset).astype(np.int64)
        self.valid, self.period_tag = np.zeros(n, bool), np.zeros(n, np.int64)
        self.n_expected, self.n_received, self.first_us = np.zeros(n, np.int64), np.zeros(n, np.int64), np.zeros(n, np.int64)

    def plan(self, m, queue, now):
        self.queue = queue
        self._count_arrivals()                             # 도착은 교체가 없어도 순서대로 센다(RTL ingest와 같다)
        return super().plan(m, queue, now)

    def predict(self, cand):
        self._count_arrivals()
        now = int(math.floor(self.now))
        return [now if self.queue.by_model[x] else
                min((now + self._next_delay(g, now) for g in self.groups_of_model[x]), default=float('inf')) for x in cand]

    def _tables(self):
        """Host가 next_use_predictor.v에 쓰는 정수 µs 표. δ는 칸 가운데 값(lut와 같은 규칙), τ는 올림"""
        jt, gt, B, NB = self.jitter, self.model_group_delay, self.LUT_BIN_US, self.LUT_BINS
        return dict(lut_u=[[int(round(jt.delta((i + 0.5) * B, r))) for r in self.REMAIN_VALUES] for i in range(NB)],
                    lut_g=[int(round(gt.delta((i + 0.5) * B, 1))) if gt is not None else 0 for i in range(NB)],
                    tau_u=int(math.ceil(jt.quantile(1.0))), tau_g=int(math.ceil(gt.quantile(1.0))) if gt is not None else 0,
                    eg=int(round(gt.delta(0.0, 1))) if gt is not None else 0)

    def _phase(self, g, now):
        """(지금 주기 kn, 그 주기 nominal offset 뒤 경과 el), 정수 µs"""
        Pi, off = int(PERIOD_US), int(self.offset_us[g])
        ph, ep = now % Pi, now // Pi
        return (ep - 1, ph - off + Pi) if ph < off else (ep, ph - off)

    def _count_arrivals(self):
        q = self.queue.next_idx
        for i in range(self.n_counted, q):
            g, ta, th = int(self.req_group[i]), int(math.floor(self.wl.t_arr[i])), int(round(self.wl.t_host[i]))
            n_exp = int(self.expected[g, self.req_period[i]])
            kn, el = self._phase(g, ta)
            k = kn if el - (ta - th) >= -int(PERIOD_US) // 2 else kn - 1   # t_host가 반 주기 넘게 앞서면 앞 주기
            if not self.valid[g] or k > self.period_tag[g]:
                self.valid[g], self.period_tag[g], self.n_expected[g], self.n_received[g], self.first_us[g] = True, k, n_exp, 1, ta
            elif k == self.period_tag[g]:
                self.n_received[g] += 1
            if self.log is not None:
                self.log.append((ta, g, th, n_exp))
        self.n_counted = q

    def _remain_bin(self, r):
        return int(np.searchsorted(self.REMAIN_EDGES, r, 'right')) - 1

    def _next_delay(self, g, now):
        """모델 그룹 g의 다음 사용까지 남은 µs(정수 표)"""
        tb, Pi = self.tables, int(PERIOD_US)
        kn, el = self._phase(g, now)
        est = int(self.n_expected[g]) if self.valid[g] else int(self.group_tracks[g])
        nxt = (Pi - el) + tb['eg'] + tb['lut_u'][0][self._remain_bin(max(1, est))]
        if kn < 0:
            return nxt
        seen = bool(self.valid[g]) and self.period_tag[g] == kn
        r = est - (int(self.n_received[g]) if seen else 0)
        if not seen:
            if r > 0 and el < tb['tau_g']:
                return tb['lut_g'][min(el // self.LUT_BIN_US, self.LUT_BINS - 1)]
        else:
            x = now - int(self.first_us[g])
            if r > 0 and x < tb['tau_u']:
                return tb['lut_u'][min(x // self.LUT_BIN_US, self.LUT_BINS - 1)][self._remain_bin(r)]
        return nxt
