"""part_simulator.py — simulator 본체. 추론 요청열 하나를 부품 셋(cache 정책·scheduler·연산)으로 끝까지 돌리고 지표를 낸다.
진행 규칙은 simulation_engine.md §5"""
import numpy as np

from part_hardware import CLK, PERIOD_US


class Queue:
    """FPGA에 도착했고 아직 batch에 들어가지 않은 추론 요청. 도착 순서와 모델별 목록을 함께 유지한다.
    drop_busy면 같은 트랙의 이전 추론 요청이 연산을 마치기 전에 온 추론 요청을 queue에 넣지 않고 버린다(dropped)"""

    def __init__(self, wl, finish=None):
        self.wl = wl
        self.n = wl.t_arr.size
        self.next_idx = 0                  # 아직 도착하지 않은 첫 추론 요청(= 지금까지 도착한 추론 요청 수)
        self.served = np.zeros(self.n, bool)
        self.head = 0                      # 도착 순서상 가장 오래된 미처리 추론 요청 후보
        self.by_model = [[] for _ in range(wl.hw.models)]
        self.count = 0
        self.finish = finish if wl.drop_busy else None     # 추론 요청별 연산 완료 시각(simulate가 채운다)
        self.last_req = np.full(wl.n_tracks, -1)           # 트랙별 마지막으로 받은 추론 요청
        self.dropped = []

    def advance(self, now):
        """now까지 도착한 추론 요청을 받는다"""
        wl = self.wl
        while self.next_idx < self.n and wl.t_arr[self.next_idx] <= now:
            i = self.next_idx
            self.next_idx += 1
            if self.finish is not None:
                j = self.last_req[wl.track[i]]
                if j >= 0 and not (self.served[j] and self.finish[j] <= wl.t_arr[i]):
                    self.served[i] = True                  # Queue에 넣지 않는다. oldest가 건너뛰지 않으면 빈 batch가 끝없이 돈다
                    self.dropped.append(i)
                    continue
                self.last_req[wl.track[i]] = i
            self.by_model[wl.model[i]].append(i)
            self.count += 1

    def next_arrival(self):
        return self.wl.t_arr[self.next_idx] if self.next_idx < self.n else None

    def oldest(self):
        """가장 오래 기다린 추론 요청"""
        while self.head < self.next_idx and self.served[self.head]:
            self.head += 1
        return self.head if self.head < self.next_idx else None

    def take(self, m, idx):
        """모델 m의 추론 요청 idx를 batch로 가져간다"""
        self.served[idx] = True
        lst, n = self.by_model[m], len(idx)
        if all(self.served[i] for i in lst[:n]):           # 앞쪽부터 가져간 경우가 대부분
            self.by_model[m] = lst[n:]
        else:
            self.by_model[m] = [i for i in lst if not self.served[i]]
        self.count -= n


def simulate(wl, cache, scheduler, compute, stop_on_miss=False, detail=False):
    """추론 요청열 wl을 부품 셋으로 끝까지 돌리고 지표 dict를 낸다. 결정 시각 T에 다음 batch의 모델과 적재를 정하고,
    그 batch의 첫 연산 시작 s가 다음 결정 시각이다(1단 선행). stop_on_miss면 측정 구간에서 deadline miss가 나는 즉시 멈춘다.
    detail이면 cycle 회계와 response time 분해를 더한다"""
    for part in (cache, scheduler, compute):
        part.reset(wl)
    compute.log = [] if detail else None
    finish = np.full(wl.t_arr.size, np.nan)
    queue = Queue(wl, finish)
    sizes, starts, loads_b, windows = [], [], [], []   # Batch마다 기록
    T = 0.0
    while True:
        queue.advance(T)
        if queue.count == 0:
            na = queue.next_arrival()
            if na is None:
                break
            T = max(T, na)
            queue.advance(T)
            if queue.count == 0:                       # 그 도착을 버렸다(drop 규칙). 다음 도착으로
                continue
        m, head = scheduler.pick(queue, T, cache, compute.compute_free_at)
        if m is None:                                  # Scheduler가 기다린다: head = 다시 고를 시각
            T = max(head, T)
            continue
        nbytes = cache.plan(m, queue, T)
        taken = []

        def members(s, m=m, head=head):
            queue.advance(s)
            idx = scheduler.members(queue, m, head, s)
            queue.take(m, idx)
            taken.extend(idx)
            return len(idx), (None if wl.cost is None else wl.cost[idx])

        s, fin = compute.run(T, nbytes, members)
        finish[taken] = fin
        if stop_on_miss:
            tk = np.asarray(taken)
            late = (wl.recv_time(fin, tk) - wl.t_host[tk] > PERIOD_US) & (wl.t_host[tk] >= wl.w0)
            if late.any():
                return {'miss': 1, 'early': True}
        sizes.append(len(taken))
        starts.append(s)
        loads_b.append(nbytes)
        windows.append((m, int(wl.period[head]) if wl.period is not None and head is not None else -1))   # 적재 window = (모델, 주기)
        T = s
    dr = np.array(queue.dropped, int)
    ok = (wl.t_host >= wl.w0) & np.isfinite(finish)     # Drop 전에 센다: 결과가 나온 추론 요청
    finish[dr] = wl.t_host[dr] + 2 * PERIOD_US          # drop: 결과가 없으므로 response time을 2주기로 적어 miss로 센다
    bs = np.array(starts)
    res = metrics(wl, finish, np.array(sizes), bs, np.array(loads_b), np.array(windows, np.int64).reshape(-1, 2))
    res['drop'] = int((wl.t_host[dr] >= wl.w0).sum())
    i = np.flatnonzero(ok)
    if i.size:                                         # 결과가 나온 추론 요청의 Host 처리 지연 최대, 준비 완료 뒤 최대, 송신 뒤 최대
        rcv = wl.recv_time(finish[i], i)
        res['host_max_ms'] = float((wl.t_ready[i] - wl.t_host[i]).max() / 1000)
        res['fpga_side_max_ms'] = float((rcv - wl.t_ready[i]).max() / 1000)
        res['send_side_max_ms'] = float((rcv - wl.t_send[i]).max() / 1000)
        if wl.drop_busy:                               # 결과가 나온 추론 요청만의 최대 response time
            res['max_done_ms'] = float((rcv - wl.t_host[i]).max() / 1000)
    if cache.entries:                                  # 같은 batch 순서의 offline 최소 적재 수
        res['belady_loads'] = belady([w[0] for w in windows], cache.entries, (bs >= wl.w0) & (bs < wl.w1))
    res.update(cache.stats())
    if detail:
        finish[dr] = wl.t_arr[dr]                      # cycle 회계에서 버린 추론 요청은 FPGA에 머문 시간 0
        res.update(cycle_stats(wl, finish, compute.log, res['req_win']))
    return res


def metrics(wl, finish, k, s, b, w):
    """Batch 기록(추론 요청 수 k, 첫 연산 시각 s, 적재 B b(0 = hit), (모델, 주기) w)과 추론 요청별 연산 완료 finish → 지표.
    추론 요청은 t_host ≥ w0, batch는 s가 [w0, w1)인 것을 센다. 열 이름은 결과 CSV 형식이라 바꾸지 않는다"""
    hw = wl.hw
    response_time = wl.recv_time(finish, np.arange(finish.size)) - wl.t_host
    sel = wl.t_host >= wl.w0
    r = response_time[sel]
    win = (s >= wl.w0) & (s < wl.w1)
    span = wl.w1 - wl.w0
    return {
        'n_req': int(sel.sum()),
        'miss': int((r > PERIOD_US).sum()),
        'miss_rate': float((r > PERIOD_US).mean()),
        'mbps': float(b[win].sum() / span),                    # B/µs = MB/s
        'p50_ms': float(np.percentile(r, 50) / 1000),
        'p99_ms': float(np.percentile(r, 99) / 1000),
        'max_ms': float(r.max() / 1000),
        'mean_ms': float(r.mean() / 1000),
        'req_win': int(k[win].sum()),
        'w_bytes': float(b[win].sum()),                        # weight 읽기 B
        'm_bytes': float(k[win].sum() * hw.membrane_rw_bytes),  # membrane potential 읽기 + 쓰기 B
        'batch_mean': float(k[win].mean()),
        'hit_rate': float((b[win] == 0).mean()),
        'dma_util': float((b[win].sum() / hw.ddr3_bandwidth_mbps + hw.membrane_us(k[win].sum())) / span),
        'cmp_util': float(k[win].sum() * hw.dense_req_us / span),
        'ddr3_used_bandwidth_mbps': float((b[win].sum() + k[win].sum() * hw.membrane_rw_bytes) / span),
        'min_deadline_margin_ms': float(PERIOD_US / 1000 - r.max() / 1000),
        'batch_max': int(k[win].max()) if win.any() else 0,
        **_load_stats(wl, sel, win & (b > 0), w),
        'response_time': r,                                             # 실행기가 히스토그램으로 바꾼 뒤 지운다
    }


def _load_stats(wl, sel, ld, w):
    """측정 구간의 weight 적재 수, 같은 (모델, 주기) 안의 재적재 수, 추론 요청이 있던 (모델, 주기) 수"""
    if wl.period is None or w.shape[0] != ld.size:
        return {}
    wm = w[ld]
    _, per = np.unique(wm[:, 0] * 1_000_000 + wm[:, 1], return_counts=True)
    return {'weight_loads': int(ld.sum()), 'window_reloads': int(ld.sum() - per.size), 'window_loads_max': int(per.max()) if per.size else 0,
            'model_periods': int(np.unique(wl.model[sel].astype(np.int64) * 1_000_000 + wl.period[sel]).size)}


def cycle_stats(wl, finish, busy, n_win):
    """측정 구간의 compute array cycle 회계(연산 + 정지 + 유휴 = 구간)와 response time 분해(입력 + FPGA + 결과).
    정지 = 도착한 추론 요청이 남았는데 compute array가 쉰 cycle, 유휴 = FPGA 안에 추론 요청이 없는 cycle"""
    w0, w1 = wl.w0, wl.w1
    b = np.asarray(busy, float).reshape(-1, 2)
    busy_t = float((np.clip(b[:, 1], w0, w1) - np.clip(b[:, 0], w0, w1)).sum())
    active = _union(np.clip(wl.t_arr, w0, w1), np.clip(finish, w0, w1))
    sel = wl.t_host >= w0
    done = wl.recv_time(finish, np.arange(finish.size))
    per_us = 1.0 / CLK
    return {
        'cyc_busy': busy_t * per_us,
        'cyc_stall': (active - busy_t) * per_us,
        'cyc_idle': (w1 - w0 - active) * per_us,
        'cyc_n': n_win,                                         # 측정 구간에 연산을 시작한 추론 요청 수(추론 요청당 cycle의 분모)
        'in_ms': float((wl.t_arr - wl.t_host)[sel].mean() / 1000),
        'fpga_ms': float((finish - wl.t_arr)[sel].mean() / 1000),
        'out_ms': float((done - finish)[sel].mean() / 1000),
    }


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


def belady(seq, entries, count):
    """Belady 하한: batch 모델 순서 seq 중 count가 참인 batch에 offline Belady MIN을 적용한 적재 수.
    구간 시작 entry는 무엇이든 될 수 있다고 보고, 둘째 batch부터 직전 batch의 모델(연산 중)은 내보내지 않는다"""
    w = [m for m, c in zip(seq, count) if c]
    n, last, first = len(w), {}, {}
    nxt = [n] * n
    for i in range(n - 1, -1, -1):
        nxt[i] = last.get(w[i], n)
        last[w[i]] = i
    for i, m in enumerate(w):
        first.setdefault(m, i)
    cache = dict(sorted(first.items(), key=lambda x: x[1])[:entries])   # 모델 → 다음 사용 위치
    loads = 0
    for i, m in enumerate(w):
        if m not in cache:
            if len(cache) >= entries:
                prev = w[i - 1] if i else None
                del cache[max((x for x in cache if x != prev), key=lambda x: cache[x])]
            loads += 1
        cache[m] = nxt[i]
    return loads
