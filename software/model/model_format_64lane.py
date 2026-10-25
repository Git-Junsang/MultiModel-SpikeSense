"""P3.10 lane-interleaved INT8 모델 slot (64lane). 기준: documents/design_references/02_MODEL.md §6, 04_MEMORY.md §3.

word = LANES × INT8. 은닉 layer는 뉴런 그룹 g(LANES개)마다 입력 i 순서로 word를 둔다. Lane j는 출력 뉴런 LANES·g + j다.

  params      뉴런별 {β u8, vth u8}, L1 → 출력 layer 뉴런 순서, 64 B 단위로 올림
  은닉 layer  (g × fan_in + i) × LANES + j = W[LANES·g + j][i]      뉴런 수 ≥ LANES
              i × n + j                    = W[j][i]                뉴런 수 n < LANES (lane 0~n−1만)
  출력 layer  [out, in] row-major. on-chip word로는 LANES byte씩 자른다

두 형식을 둔다. 함수 이름과 반환 형식은 model_format_1lane.py와 같다.
  L64   L `40→384→256→64→2`, 64 lane, slot 256 KiB  (P3.9 구현 기준)
  XL    XL `40→768→512→128→2`, 256 lane, slot 512 KiB (모델 비교용)
"""

from pathlib import Path

import numpy as np

FORMAT_VERSION = 2


class LaneFormat:
    def __init__(self, layer_sizes, lanes, slot_size, weights_dir, models_dir, golden_dir):
        self.FORMAT_VERSION = FORMAT_VERSION
        self.WEIGHTS_DIR, self.MODELS_DIR, self.GOLDEN_DIR = weights_dir, models_dir, golden_dir
        self.LAYER_SIZES, self.LANES, self.SLOT_SIZE = tuple(layer_sizes), lanes, slot_size
        self.WEIGHT_SHAPES = tuple((o, i) for i, o in zip(layer_sizes[:-1], layer_sizes[1:]))
        self.NEURON_COUNTS = self.LAYER_SIZES[1:]
        self.WEIGHT_BYTES = sum(a * b for a, b in self.WEIGHT_SHAPES)
        self.PARAM_BYTES = 2 * sum(self.NEURON_COUNTS)
        self.PARAM_OFFSET = 0
        self.PARAM_SECTION = -(-self.PARAM_BYTES // 64) * 64
        offs = np.cumsum([self.PARAM_SECTION] + [a * b for a, b in self.WEIGHT_SHAPES])
        self.WEIGHT_OFFSETS = tuple(int(x) for x in offs[:-1])
        self.USED_END = int(offs[-1])                       # DMA 한 번에 읽는 유효 구간
        n_out, n_in = self.WEIGHT_SHAPES[-1]
        self.ENTRY_WORDS = sum(-(-n // lanes) * k for n, k in self.WEIGHT_SHAPES[:-1]) + n_out * n_in // lanes
        assert all(n % lanes == 0 for n, _ in self.WEIGHT_SHAPES[:-1] if n >= lanes)
        assert (n_out * n_in) % lanes == 0
        assert all(x % 32 == 0 for x in (*self.WEIGHT_OFFSETS, self.USED_END))   # 32 B AXI beat 정렬
        assert self.USED_END <= slot_size

    def layout(self):
        """manifest에 적는 형식 정보"""
        return {"lanes": self.LANES, "param_offset": self.PARAM_OFFSET, "param_section_bytes": self.PARAM_SECTION,
                "weight_offsets": list(self.WEIGHT_OFFSETS), "used_bytes": self.USED_END,
                "entry_words": self.ENTRY_WORDS}

    def _check_q(self, q):
        if len(q) != len(self.WEIGHT_SHAPES):
            raise ValueError(f"layer 수 {len(q)} != {len(self.WEIGHT_SHAPES)}")
        for i, (layer, shape) in enumerate(zip(q, self.WEIGHT_SHAPES), 1):
            if layer["W"].shape != shape:
                raise ValueError(f"L{i} W 형상 {layer['W'].shape} != {shape}")
            if layer["beta"].shape != (shape[0],) or layer["vth"].shape != (shape[0],):
                raise ValueError(f"L{i} beta/vth 형상이 뉴런 수 {shape[0]}와 다름")

    def _last(self, i):
        return i == len(self.WEIGHT_SHAPES) - 1

    def _to_lane(self, w, last):
        n, k = w.shape
        if last:
            return w.reshape(-1)
        if n < self.LANES:
            return w.T.reshape(-1)
        return w.reshape(n // self.LANES, self.LANES, k).transpose(0, 2, 1).reshape(-1)

    def _from_lane(self, flat, shape, last):
        n, k = shape
        if last:
            return flat.reshape(n, k)
        if n < self.LANES:
            return flat.reshape(k, n).T
        return flat.reshape(n // self.LANES, k, self.LANES).transpose(0, 2, 1).reshape(n, k)

    def weights_bytes(self, q):
        self._check_q(q)
        raw = b"".join(self._to_lane(np.asarray(l["W"], np.int8), self._last(i)).tobytes() for i, l in enumerate(q))
        assert len(raw) == self.WEIGHT_BYTES
        return raw

    def params_bytes(self, q):
        """뉴런별 {β, vth}"""
        self._check_q(q)
        beta = np.concatenate([np.asarray(l["beta"], np.uint8) for l in q])
        vth = np.concatenate([np.asarray(l["vth"], np.uint8) for l in q])
        raw = np.stack([beta, vth], 1).tobytes()
        assert len(raw) == self.PARAM_BYTES
        return raw

    def slot_bytes(self, q):
        image = bytearray(self.SLOT_SIZE)
        params = self.params_bytes(q)
        image[self.PARAM_OFFSET:self.PARAM_OFFSET + len(params)] = params
        image[self.WEIGHT_OFFSETS[0]:self.USED_END] = self.weights_bytes(q)    # section이 이어져 있다
        return bytes(image)

    def q_from_files_bytes(self, weights, params, scales=None):
        if len(weights) != self.WEIGHT_BYTES or len(params) != self.PARAM_BYTES:
            raise ValueError(f"파일 크기 불일치: weights={len(weights):,}, params={len(params):,}")
        scales = [None] * len(self.WEIGHT_SHAPES) if scales is None else list(scales)
        if len(scales) != len(self.WEIGHT_SHAPES):
            raise ValueError("스케일 수가 layer 수와 다름")
        bv = np.frombuffer(params, np.uint8).reshape(-1, 2)
        q, w_at, n_at = [], 0, 0
        for i, (shape, scale) in enumerate(zip(self.WEIGHT_SHAPES, scales)):
            count = shape[0] * shape[1]
            w = self._from_lane(np.frombuffer(weights, np.int8, count, w_at), shape, self._last(i)).copy()
            stop = n_at + shape[0]
            q.append({"W": w, "beta": bv[n_at:stop, 0].copy(), "vth": bv[n_at:stop, 1].copy(), "scale": scale})
            w_at, n_at = w_at + count, stop
        return q

    def q_from_files(self, weights_path, params_path, scales=None):
        return self.q_from_files_bytes(Path(weights_path).read_bytes(), Path(params_path).read_bytes(), scales)

    def q_from_slot(self, data, scales=None):
        if isinstance(data, (str, Path)):
            data = Path(data).read_bytes()
        if len(data) != self.SLOT_SIZE:
            raise ValueError(f"슬롯 크기 {len(data):,} B != {self.SLOT_SIZE:,} B")
        if any(data[self.PARAM_OFFSET + self.PARAM_BYTES:self.WEIGHT_OFFSETS[0]]) or any(data[self.USED_END:]):
            raise ValueError("padding이 0이 아님")
        return self.q_from_files_bytes(data[self.WEIGHT_OFFSETS[0]:self.USED_END],
                                       data[self.PARAM_OFFSET:self.PARAM_OFFSET + self.PARAM_BYTES], scales)

    def entry_words(self, weights):
        """64lane weights → on-chip entry image uint8 [ENTRY_WORDS, LANES]. 뉴런 수 < LANES인 layer는 위쪽 lane을 0으로 채운다"""
        w = np.frombuffer(weights, np.uint8)
        out, at = [], 0
        for i, (n, k) in enumerate(self.WEIGHT_SHAPES):
            sec = w[at:at + n * k]
            at += n * k
            if n < self.LANES and not self._last(i):
                pad = np.zeros((k, self.LANES), np.uint8)
                pad[:, :n] = sec.reshape(k, n)
                out.append(pad)
            else:
                out.append(sec.reshape(-1, self.LANES))
        words = np.concatenate(out)
        assert words.shape == (self.ENTRY_WORDS, self.LANES)
        return words

    def hex_files(self, weights, params):
        """$readmemh용 HEX. entry.hex: 한 줄 = LANES × 8 bit word, lane j = bit [8j+7:8j].
        params.hex: 한 줄 = 뉴런 1개 16 bit = {vth, β}"""
        words = self.entry_words(weights)
        bv = np.frombuffer(params, np.uint8).reshape(-1, 2).astype(np.int64)
        return {"entry.hex": "".join(row[::-1].tobytes().hex() + "\n" for row in words),
                "params.hex": "".join(f"{(v << 8) | b:04x}\n" for b, v in bv)}


L64 = LaneFormat((40, 384, 256, 64, 2), 64, 0x40000,
                 "software/weights/L_normal_noaug", "hardware/data/models_l64", "hardware/data/golden_l64")
XL = LaneFormat((40, 768, 512, 128, 2), 256, 0x80000,
                "software/weights/XL_mixed_aug", "hardware/data/models_xl", "hardware/data/golden_xl")
assert (XL.WEIGHT_OFFSETS, XL.USED_END, XL.ENTRY_WORDS) == ((0x00B40, 0x08340, 0x68340, 0x78340), 0x78440, 2169)
assert (L64.WEIGHT_OFFSETS, L64.USED_END, L64.ENTRY_WORDS) == ((0x005C0, 0x041C0, 0x1C1C0, 0x201C0), 0x20240, 2034)
