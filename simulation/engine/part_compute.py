"""part_compute.py — DMA와 compute array의 시각. 규칙은 simulation_engine.md §6.3"""
import numpy as np

from part_hardware import DMA_SETUP_US, Part


class Compute(Part):
    """DMA 하나와 compute array 하나. 필요한 weight가 모두 교체될 entry에 들어온 뒤 batch의 트랙을 하나씩 모델 전체로 연산한다.
    run(T, nbytes, members) → (첫 연산 시작, 추론 요청별 연산 완료). members(s)는 시작 시각 s에 batch 구성원을 확정한다"""
    log = None                       # simulate(detail=True)가 []로 바꾸면 연산 구간 (시작, 끝)을 남긴다

    def tiles(self):
        """BRAM tile: membrane potential 준비 버퍼 등(membrane_place가 split·ddr일 때)"""
        return self.hw.membrane_buf_tiles

    def reset(self, wl):
        self.dma_free_at = self.compute_free_at = 0.0

    def run(self, T, nbytes, members):
        ready = self._load(T, nbytes) if nbytes else T
        s = max(ready, self.compute_free_at)
        k, cost = members(s)
        self._membrane(s, k)
        fin = s + (self.hw.dense_req_us * np.arange(1, k + 1) if cost is None else np.cumsum(cost))
        self.compute_free_at = fin[-1] if k else s
        if self.log is not None:
            self.log.append((s, self.compute_free_at))
        return s, fin

    def _load(self, T, nbytes):
        """시각 T에 nbytes 적재를 낸다. 앞 전송과 겹쳐 고정 비용이 숨는다: 완료 = max(T + 고정 비용, 앞 전송 완료) + 크기 / bandwidth"""
        self.dma_free_at = max(T + DMA_SETUP_US, self.dma_free_at) + nbytes / self.hw.ddr3_bandwidth_mbps
        return self.dma_free_at

    def _membrane(self, s, k):
        """Membrane potential이 DDR3에 있으면 batch의 weight 전송 뒤에 추론 요청 k개의 읽기·쓰기 DMA를 더한다(다음 적재가 늦어진다)"""
        if self.hw.membrane_rw_bytes:
            self.dma_free_at = max(self.dma_free_at, s) + self.hw.membrane_us(k)
