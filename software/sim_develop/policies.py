"""policies.py — P3.6~P3.8 후보 부품 9개 (저장 정책 3, 스케줄러 4, 연산 방식 2)

같은 종류의 부품은 같은 질문에 답하는 같은 메서드를 가진다. sim_core.simulate()는 부품 종류만
알고 구체적인 후보는 모른다. 후보를 늘리려면 클래스 하나를 만들어 아래 목록에 넣는다.

  저장 정책  plan(m)  → 뉴런 그룹마다 DDR3에서 가져올 바이트 (0 = 온칩에 있음), 캐시 상태 갱신
             peek(m)  → plan과 같은 총 바이트, 상태는 바꾸지 않음 (점수 스케줄러용)
             tiles()  → 온칩 BRAM 타일
  스케줄러   pick(rd, T, storage)     → (다음 모델, 기준 요청)
             members(rd, m, head, s)  → 연산 시작 시각 s에 묶음에 넣을 요청 목록
  연산 방식  run(T, loads, uses_entry, members) → (첫 연산 시작 시각, 요청별 연산 완료 시각)
             extra_tiles(storage) → 적재 버퍼 타일, max_batch() → 묶음 한도(None = 없음)

레인 수·트랙 수에 따라 바뀌는 상수(그룹, 타일 등)는 sim_core.configure()가 정하므로 sc.이름으로 읽는다.
"""
import heapq
from collections import OrderedDict

import numpy as np

import sim_core as sc
from sim_core import M, P, mem_time, tiles, xfer_time


# ---- 저장 정책 ----------------------------------------------------------------
class _LRU:
    def __init__(self, n):
        self.n, self.d = n, OrderedDict()

    def hit(self, m):
        return m in self.d

    def use(self, m):
        """m을 넣거나 갱신. 진행 중인 묶음의 모델은 항상 가장 최근이므로 교체 대상이 되지 않는다"""
        if m in self.d:
            self.d.move_to_end(m)
            return True
        if len(self.d) >= self.n:
            self.d.popitem(last=False)
        self.d[m] = True
        return False


class FullCache:
    """A. 모델 엔트리 E벌(가중치 + β·vth), LRU. 미스면 모델 전체를 가져와 엔트리에 저장.
    E 기본값은 예산에 들어가는 최대값(기준 환경 5벌)"""
    name, uses_entry = 'A.전체캐시', True

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


class L1Resident:
    """B. 40모델의 L1 가중치와 β·vth 상주. 매 묶음마다 L2~L4를 가져온다(보관하지 않음)"""
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
    """C. 엔트리 E벌(LRU) + 트랙이 많은 R개 모델의 L1·β·vth 상주. E 기본값은 A의 절반(올림, 기준 환경 3벌),
    R은 남은 예산에 들어가는 최대값. 미스면 L1 상주 모델은 L2~L4만, 나머지는 전체를 가져와 엔트리에 저장"""
    name, uses_entry = 'C.혼합', True

    buf_words, buf_extra = 0, 0.0

    def __init__(self, entries=None, n_l1=None, budget=None):
        budget = sc.TILE_BUDGET - sc.MEMBUF_T if budget is None else budget
        self.E = entries or -(-max(0, int(budget // sc.ENTRY_T)) // 2)
        if n_l1 is None:
            room = budget - self.E * sc.ENTRY_T                   # 엔트리 적재라 별도 버퍼 없음
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
    """D. 가중치를 온칩에 보관하지 않고 매 묶음 모델 전체를 DDR3에서 흘려 받는다.
    가중치 BRAM을 최소로 써서 막전위(트랙) 자리를 최대로 남기는 메모리 접근 방식"""
    name, uses_entry = 'D.스트림', False

    def __init__(self, budget=None, compute=None):
        self.buf_words = sc.WORDS
        self.buf_extra = tiles(sc.NEU, 16)   # 묶음 동안 쓸 β·vth (L 706 × 16 bit = 0.5 타일)

    def tiles(self):
        return 0.0

    def reset(self, wl):
        pass

    def peek(self, m):
        return sum(sc.FULL)

    def plan(self, m):
        return sc.FULL


def _fits(st, compute):
    return st.tiles() + compute.extra_tiles(st) <= sc.TILE_BUDGET


class PartialAll:
    """B(예산 맞춤). 40모델 모두의 앞쪽 뉴런 그룹 k개를 상주시키고 나머지 그룹은 매 묶음 가져온다(보관하지 않음).
    k는 연산 방식의 적재 버퍼까지 넣어 예산에 들어가는 최대값이다. 남는 예산에 40모델 β·vth가 들어가면 상주시키고,
    아니면 모델과 함께 가져온다. L 32레인 기준 환경에서는 k = 층 1 전체(12그룹) + β·vth 상주라 B.L1상주와 같다.
    XL 256레인에서는 층 1 전체(3그룹)가 들어가지 않아(418~457 타일) k가 더 작아진다"""
    name, uses_entry = 'B.부분상주', False

    def __init__(self, budget=None, compute=None):
        for k in range(sc.N_L1, -1, -1):
            for bv in (True, False):
                self._set(k, bv)
                if _fits(self, compute):
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
    """C(예산 맞춤). 혼합 = 가중치 캐시 + 부분 상주. 트랙이 가장 많은 E개 모델을 엔트리에 고정하고(교체 없음),
    다음으로 트랙이 많은 R개 모델의 층 1·β·vth를 상주시킨다. 나머지 모델은 매 묶음 전체를 가져온다(보관하지 않음).
    E = A 엔트리 수의 절반(올림), R = 남은 예산 최대(C.혼합과 같은 규칙).
    C.혼합은 엔트리를 LRU로 교체하고 미스를 엔트리에 적재한다. XL 256레인에서는 E = 1이라 교체하면 연산 중인 엔트리에
    적재할 수 없다(dse.build가 배치 불가로 보던 이유). 그래서 엔트리를 고정하고, 나머지는 스트림 경로(한 번에: 모델 1개
    적재 버퍼, 한 줄씩: 슬라이스 이중 버퍼)로 받는다"""
    name, uses_entry = 'C.고정혼합', False

    def __init__(self, budget=None, compute=None):
        e_a = int((sc.TILE_BUDGET - compute.mem_tiles()) // sc.ENTRY_T)
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
        return _fits(self, compute)

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


# ---- 스케줄러 ------------------------------------------------------------------
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
    """마감 순서. 마감이 가장 이른 요청과 마감 순서로 이어지는 같은 모델 요청을 묶는다"""
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
            elif item < key0:              # 기준 요청보다 마감이 이른 다른 모델(선택 뒤 도착) → 건너뜀
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
    """마감 여유 < T_urgent인 요청이 있으면 그 요청의 모델. 아니면
    점수 = n ÷ (남은 전송 시간 + n × 요청당 연산), n = min(준비된 요청 수, K) 최대 모델.
    묶음은 그 모델의 요청을 마감 순서로 최대 K개"""
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
    """비교용: 점수 초안에서 묶음 상한 K만 없앤 것(긴급 기준 4 ms는 그대로)"""
    name = '점수(상한 없음)'

    def __init__(self, t_urgent=4000.0):
        super().__init__(t_urgent, k=10 ** 9)


class ScoreGuard:
    """점수2: 효율이 가장 큰 모델을 먼저 처리하되, 마감 가드를 통과할 때만 고른다.
      효율 = n ÷ 묶음 시간, n = 그 모델의 준비된 요청 수(상한 없음, 하드웨어 한도는 연산 방식이 자른다)
      묶음 시간 = 남은 가중치 전송 + 막전위 DMA + n × 요청당 연산(직렬 합, 보수적). 묶음 한도를 넘으면 적재를 그만큼 더한다.
                  overlap=True(겹친다고 보고 max)는 조정 시드에서 K·R 시나리오 위반이 나서 기본으로 쓰지 않는다
      마감 가드 = 연산 배열이 비는 시각(busy_until, 진행 중인 묶음의 끝)부터 그 모델을 먼저, 나머지 모델을 마감 순서(EDF)로
                  처리한다고 할 때 모든 모델의 가장 이른 마감이 '완료 + 결과 회수 여유(margin)' 안에 드는가.
                  들지 않으면 마감이 가장 이른 모델을 고른다(그룹핑과 같아짐).
    wait(점수3, Channel Window): EDF 순서로 처리해도 되는 가장 늦은 시작 시각 LS를 구해, LS − slack까지 여유가 있으면
      다음 도착(또는 LS − slack)까지 일부러 기다려 같은 모델 요청을 더 모은다. 기다리는 동안 새 요청이 오면 다시 판단한다.
    전송 비용은 묶음 시간에 한 번만 들어간다(별도 벌점 없음). 미래 도착은 모른다."""
    name = '점수2'
    busy_until = 0.0                 # simulate가 결정마다 연산 배열이 비는 시각을 넣는다
    cap = None                       # 연산 방식의 묶음 한도(target_exp.build가 넣음)

    order = 'eff'                    # 'eff' 효율 우선(가드), 'edf' 항상 마감이 가장 이른 모델
    max_wait = None                  # 시간제한 묶음: 가장 오래된 요청이 이만큼(µs) 기다리면 더 기다리지 않음
    robust = False                   # True면 target_exp.build가 결과 회수 여유에 PCIe 실측 최악을 넣는다

    def __init__(self, margin=1150.0, overlap=False, wait=False, slack=4000.0):
        self.margin, self.overlap, self.wait, self.slack = margin, overlap, wait, slack

    def reset(self):
        self.busy_until = 0.0

    def _bt(self, x, n):
        k = -(-n // self.cap) if self.cap else 1         # 묶음 한도(한 줄씩 64)를 넘으면 모델을 그만큼 다시 적재
        dma, cmp_ = k * x + mem_time(n), n * sc.C_REQ
        return max(dma, cmp_) if self.overlap else dma + cmp_

    def pick(self, rd, T, st):
        tg = rd.wl.t_gen
        cand = []                                          # (가장 이른 마감, 모델, n, 남은 전송 시간)
        for m in range(M):
            lst = rd.by_model[m]
            if lst:
                cand.append((min(tg[i] for i in lst) + P, m, len(lst), xfer_time(st.peek(m))))
        cand.sort()
        t0 = max(T, self.busy_until)
        if self.wait:                                      # 다음 도착 뒤에 시작해도 LS까지 slack 이상 남으면 기다린다
            until = rd.next_arrival()
            if self.max_wait is not None:                  # 시간제한: 가장 오래된 요청이 max_wait에 닿으면 그만 기다림
                rel = cand[0][0] - P + self.max_wait
                until = None if T >= rel else (rel if until is None else min(until, rel))
            if until is not None and until < self._latest_start(cand) - self.slack:
                return None, until
        if self.order == 'edf':
            m = cand[0][1]
            return m, rd.by_model[m][0]
        best = max(cand, key=lambda c: (round(c[2] / self._bt(c[3], c[2]), 12), c[2], -c[0]))
        m = best[1] if best[1] != cand[0][1] and self._safe(best, cand, t0) else cand[0][1]
        return m, rd.by_model[m][0]

    def _latest_start(self, cand):
        """EDF 순서로 이어서 처리할 때 모든 마감을 지키는 가장 늦은 시작 시각"""
        t, ls = 0.0, float('inf')
        for d, m, n, x in cand:
            t += self._bt(x, n)
            ls = min(ls, d - self.margin - t)
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
    """점수3 = 점수2 + 마감 여유 안에서 일부러 기다리기(Channel Window)"""
    name = '점수3'

    def __init__(self, margin=1150.0, overlap=False, slack=4000.0):
        super().__init__(margin, overlap, wait=True, slack=slack)


class LazyGroup(ScoreGuard):
    """지연 그룹핑(LazyBatching류): 처리 순서는 그룹핑처럼 마감 순서(EDF) 그대로 두고, 마감 가드가 허락하는 만큼만 기다려
    같은 모델 요청을 더 모은다. 점수3과 달리 효율 때문에 순서를 바꾸지 않는다"""
    name = '지연 그룹핑'
    order = 'edf'

    def __init__(self, margin=1150.0, overlap=False, slack=4000.0):
        super().__init__(margin, overlap, wait=True, slack=slack)


class LazyGroupSimple(LazyGroup):
    """지연 그룹핑(간이 가드): 가장 늦은 시작 시각을 마감 순 누적합 대신 합계 하나로 보수적으로 잡는다.
      LS = 가장 이른 마감 − 회수 여유 − (대기 중인 모든 모델의 묶음 시간 합)
    마감 순 누적합 가드의 모든 항보다 작거나 같으므로 더 일찍 기다림을 멈춘다(안전 쪽). 하드웨어는 대기 요청 수·대기 모델 수·
    남은 전송량의 누계와 가장 이른 마감만 있으면 되어 정렬이 필요 없다"""
    name = '지연 그룹핑(간이 가드)'

    def _latest_start(self, cand):
        return cand[0][0] - self.margin - sum(self._bt(x, n) for d, m, n, x in cand)


class TimeoutBatch(LazyGroup):
    """시간제한 묶음(Triton·Clipper식 동적 배칭의 대기 상한): 지연 그룹핑과 같되, 가장 오래된 요청이 max_wait(기본 8 ms)
    기다리면 더 기다리지 않는다. 마감 직전까지 끌지 않으므로 여유가 남는다. 몰림에서는 가드가 바로 처리시킨다"""
    name = '시간제한 묶음 8'

    def __init__(self, margin=1150.0, overlap=False, slack=4000.0, max_wait=8000.0):
        super().__init__(margin, overlap, slack)
        self.max_wait = max_wait


class Dysta(ScoreGuard):
    """Dysta식 점수(B03 Sparse-DySta의 정적 점수를 묶음에 맞춤): 모델마다
      점수 = 요청당 잔여 처리 시간(묶음 시간 ÷ n) + η × 마감 여유(가장 이른 마감 − 지금 − 묶음 시간 − 회수 여유)
    가 가장 작은 모델의 요청 전부. 첫 항은 짧고 전송을 나눠 쓰는 묶음(캐시 적중, 큰 묶음)을, 둘째 항은 급한 모델을 앞당긴다.
    η는 두 항의 비중이다. 가드·대기 없음(원 논문도 점수만으로 순서를 정함). 선점 억제 항은 선점이 없으므로 뺐다"""
    name = 'Dysta식'
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


class TimeoutBatch16(TimeoutBatch):
    """시간제한 묶음, W = 16 ms"""
    name = '시간제한 묶음 16'

    def __init__(self, margin=1150.0, overlap=False, slack=4000.0):
        super().__init__(margin, overlap, slack, max_wait=16000.0)


class Timeout:
    """Timeout (선행연구: 동적 배칭의 대기 상한, Triton max queue delay·Clipper류. 수집 문헌 밖): 가장 오래 기다린 요청이
    FPGA에 도착한 지 W가 될 때까지 시작하지 않는다. 그 뒤로는 그룹핑과 같다(가장 오래된 요청의 모델, 쌓인 요청 전부).
    마감 가드가 없으므로 W는 동시 도착 몰림에서도 마감을 지키는 값으로 정해야 한다(target_exp.FINAL_TIMEOUT_W)"""
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
    """SlackBatch (구현 대상): 마감 순서는 그룹핑 그대로 두고, 모델별 남은 가중치 전송·연산 시간과 마감 여유로
    '늦어도 언제 시작해야 하는가'를 마감 순 누적합으로 계산해, 그때까지 기다려 같은 모델 요청을 더 모은다(= 지연 그룹핑)"""
    name = 'SlackBatch'


class SlackBatchLite(LazyGroupSimple):
    """SlackBatch-Lite: SlackBatch와 같되, 가장 늦은 시작 시각을 합계 하나로 보수적으로 계산한다(= 지연 그룹핑(간이 가드))"""
    name = 'SlackBatch-Lite'


def robust(cls):
    """결과 회수 여유에 PCIe 실측 최악(795 µs)을 넣는 변형(이름에 '(강건)')"""
    return type(cls.__name__ + 'Robust', (cls,), {'name': cls.name + '(강건)', 'robust': True})


# ---- 연산 방식 -----------------------------------------------------------------
# DMA는 하나. 요청을 미리 내 두면 앞 전송과 겹쳐 고정 비용 T0이 숨는다(P3.1 pipelined 실측):
#   데이터 도착 완료 = max(요청 시각 + T0, 앞 전송 완료) + 크기 / BW
# 막전위가 DDR3에 있으면(sc.MEM_B > 0) 두 방식 모두 묶음의 가중치 전송 뒤에 k × 2,824 B(읽기 + 쓰기)를
# DMA 시간으로 더한다(다음 묶음의 적재가 그만큼 늦어짐). 막전위 읽기 지연(트랙당 약 0.7 µs)은 숨긴다고 가정한다.
def _membrane(cm, s, k):
    if sc.MEM_B:
        cm.dma_free = max(cm.dma_free, s) + mem_time(k)
class AllAtOnce:
    """한 번에: 필요한 가중치가 모두 들어온 뒤 묶음 연산. 트랙을 하나씩 모델 전체로 연산.
    엔트리가 있는 저장 정책은 빈(교체될) 엔트리에 바로 적재하고, B는 L2~L4 적재 버퍼 1벌이 필요"""
    name = '한번에'
    log = None                         # simulate(detail=True)가 []로 바꾸면 연산 구간 (시작, 끝)을 기록

    def mem_tiles(self):
        return sc.MEMBUF_TRACK_T       # 막전위가 DDR3면 트랙 2개분 준비 버퍼

    def extra_tiles(self, st):
        buf = 0 if st.uses_entry else tiles(st.buf_words, 8 * sc.WORD) + st.buf_extra
        return self.mem_tiles() + buf

    def max_batch(self):
        return None                    # 트랙 단위로 연산하므로 막전위 버퍼 2트랙분이면 된다

    @staticmethod
    def xfers(loads):
        return int(sum(loads) > 0)     # 필요한 가중치를 DMA 한 번으로 가져온다

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
        k = members(s)
        _membrane(self, s, k)
        self.cmp_free = s + k * sc.C_REQ
        if self.log is not None:
            self.log.append((s, self.cmp_free))
        if total and not uses_entry:
            self.buf_free = self.cmp_free
        return s, s + sc.C_REQ * np.arange(1, k + 1)


class RowByRow:
    """한 줄씩: 뉴런 그룹(레인 수만큼의 뉴런 × 입력 전체)이 도착하는 대로 묶음의 트랙들이 차례로 연산.
    엔트리가 있는 저장 정책은 교체될 엔트리에 바로 적재하며 그룹별 도착만 확인한다(버퍼 불필요).
    B는 슬라이스 이중 버퍼 2칸을 묶음 경계와 상관없이 번갈아 쓴다.
    그룹마다 묶음의 모든 트랙을 돌므로, 막전위가 DDR3에 있으면 묶음 전체의 막전위 버퍼가 필요하다.
    rev 2에서는 묶음 전체의 입력·층간 스파이크 버퍼(SPK_T)도 필요하고 묶음은 항상 BATCH_CAP 이하다"""
    name = '한줄씩'
    log = None

    def mem_tiles(self):
        return sc.MEMBUF_T + sc.SPK_T  # 막전위가 DDR3면 묶음 전체(BATCH_CAP 트랙) 버퍼 + rev 2 스파이크 버퍼

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
                s, k = start, members(start)
            t = start + k * sc.G_CYC[g]
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
