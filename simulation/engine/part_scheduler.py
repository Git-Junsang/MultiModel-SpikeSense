"""part_scheduler.py — scheduler: 다음 batch의 모델과 구성원을 고른다. 식은 simulation_engine.md §6.2"""
import math

from part_hardware import PERIOD_US, Part
from part_workload import LINK_OUT_FILE, link_samples


class Scheduler(Part):
    """Scheduler 공통. pick(queue, T, cache, busy_until) → (다음 모델, 기준 추론 요청) 또는 (None, 다시 고를 시각),
    members(queue, m, head, s) → 연산 시작 시각 s에 batch에 넣을 추론 요청. busy_until = compute array가 비는 시각(진행 중인 batch의 끝)"""

    def pick(self, queue, T, cache, busy_until):
        raise NotImplementedError

    def members(self, queue, m, head, s):
        raise NotImplementedError


class Grouping(Scheduler):
    """Grouping: 가장 오래 기다린 추론 요청의 모델을 고르고 그 모델의 준비된 추론 요청을 모두 묶는다(제안)"""
    name = 'Grouping'

    def pick(self, queue, T, cache, busy_until):
        h = queue.oldest()
        return int(queue.wl.model[h]), h

    def members(self, queue, m, head, s):
        return list(queue.by_model[m])


class DystaMethod(Scheduler):
    """Dysta Method: 점수 = 추론 요청당 남은 처리 시간 + η × deadline 여유가 가장 작은 모델의 추론 요청 전부. 기다리지 않는다.
    Sparse-DySta의 점수를 모델별 batch에 맞춘 것이다"""
    name = 'Dysta Method'
    eta = 1e-4                       # Deadline 여유 항의 비중 η(p325_dysta_method_tune에서 고른 값)
    margin = None                    # 결과 회수 여유 µs. None = 결과 C2H 지연 표본 최대 + 20 µs

    def __init__(self, hw, **attrs):
        super().__init__(hw, **attrs)
        if self.margin is None:
            self.margin = link_samples(LINK_OUT_FILE).max() + 20.0

    def pick(self, queue, T, cache, busy_until):
        t_host = queue.wl.t_host
        t0 = max(T, busy_until)
        best = None
        for m in range(self.hw.models):
            lst = queue.by_model[m]
            if lst:
                n, d = len(lst), min(t_host[i] for i in lst) + PERIOD_US
                bt = self._batch_us(self.hw.load_us(cache.peek(m)), n)
                key = (bt / n + self.eta * (d - t0 - bt - self.margin), d)
                if best is None or key < best[0]:
                    best = (key, m)
        m = best[1]
        return m, queue.by_model[m][0]

    def members(self, queue, m, head, s):
        t_host = queue.wl.t_host
        return sorted(queue.by_model[m], key=lambda i: t_host[i])

    def _batch_us(self, load, n):
        """Batch 시간 = 남은 적재 + membrane potential DMA + n × 추론 요청당 연산"""
        return load + self.hw.membrane_us(n) + n * self.hw.dense_req_us


class DeepRTMethod(Scheduler):
    """DeepRT Method(DisBatcher + EDF): 모델마다 길이 W의 window를 m·W/M씩 다르게 두고, window가 끝나면 그동안 온 추론 요청을
    job 하나로 묶어 job deadline 순서로 처리한다. flush면 compute array가 놀 때 window 끝을 기다리지 않는다"""
    name = 'DeepRT Method'
    window = (14900.0, False)        # (window W µs, flush). p325_deeprt_method_tune에서 고른 값

    def pick(self, queue, T, cache, busy_until):
        t_arr = queue.wl.t_arr
        jobs, nxt = [], float('inf')
        for m in range(self.hw.models):
            if queue.by_model[m]:
                end = self._window_end(m, t_arr[queue.by_model[m][0]])
                if end <= T:
                    jobs.append((end, m))
                else:
                    nxt = min(nxt, end)
        if jobs:
            end, m = min(jobs)
            self.job_end = end
            return m, queue.by_model[m][0]
        if self.window[1] and T >= busy_until:             # Compute array가 놂: window 끝을 기다리지 않고 보낸다
            end, m = min((self._window_end(m, t_arr[queue.by_model[m][0]]), m) for m in range(self.hw.models) if queue.by_model[m])
            self.job_end = float('inf')
            return m, queue.by_model[m][0]
        na = queue.next_arrival()
        t = min(nxt, busy_until if self.window[1] else nxt)
        return None, t if na is None else min(t, na)

    def members(self, queue, m, head, s):
        t_arr = queue.wl.t_arr
        return [i for i in queue.by_model[m] if t_arr[i] <= self.job_end]

    def _window_end(self, m, t):
        """모델 m의 window 중 시각 t를 담은 window의 끝"""
        W = self.window[0]
        w_off = m * W / self.hw.models
        return w_off + math.ceil((t - w_off) / W) * W
