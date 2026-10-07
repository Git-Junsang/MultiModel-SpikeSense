"""P1.6/P1.7 INT8 모델 바이너리 형식과 DDR3 슬롯 레이아웃.

모든 오프셋은 모델 슬롯 시작을 기준으로 한다. 가중치는 PyTorch Linear의
``[out, in]`` 행 우선(뉴런 우선) 순서다. 모델 ID 순서는 ``dcase_data.UNITS``다.
"""

from pathlib import Path

import numpy as np

LAYER_SIZES = (40, 384, 256, 64, 2)
WEIGHT_SHAPES = tuple((n_out, n_in) for n_in, n_out in zip(LAYER_SIZES[:-1], LAYER_SIZES[1:]))
NEURON_COUNTS = LAYER_SIZES[1:]

ALIGN = 128
SLOT_SIZE = 0x21000                 # 135,168 B = 132 KiB
WEIGHT_OFFSETS = (0x00000, 0x03C00, 0x1BC00, 0x1FC00)
BETA_OFFSET = 0x1FC80
VTH_OFFSET = 0x1FF80
WEIGHT_BYTES = 130_176
PARAM_BYTES = 1_412
USED_END = 0x20242

assert all(offset % ALIGN == 0 for offset in (*WEIGHT_OFFSETS, BETA_OFFSET, VTH_OFFSET))
assert sum(a * b for a, b in WEIGHT_SHAPES) == WEIGHT_BYTES
assert 2 * sum(NEURON_COUNTS) == PARAM_BYTES
assert USED_END <= SLOT_SIZE


def _check_q(q):
    if len(q) != len(WEIGHT_SHAPES):
        raise ValueError(f"층 수 {len(q)} != {len(WEIGHT_SHAPES)}")
    for i, (layer, shape) in enumerate(zip(q, WEIGHT_SHAPES), 1):
        if layer["W"].shape != shape:
            raise ValueError(f"L{i} W 형상 {layer['W'].shape} != {shape}")
        if layer["beta"].shape != (shape[0],) or layer["vth"].shape != (shape[0],):
            raise ValueError(f"L{i} beta/vth 형상이 뉴런 수 {shape[0]}와 다름")


def weights_bytes(q):
    """층별 W를 붙인 정확히 130,176 B의 INT8 가중치 바이너리."""
    _check_q(q)
    raw = b"".join(np.asarray(layer["W"], dtype=np.int8).reshape(-1).tobytes() for layer in q)
    assert len(raw) == WEIGHT_BYTES
    return raw


def params_bytes(q):
    """층 순서로 붙인 beta 706 B 뒤에 vth 706 B를 두는 1,412 B 바이너리."""
    _check_q(q)
    beta = np.concatenate([np.asarray(layer["beta"], dtype=np.uint8) for layer in q]).tobytes()
    vth = np.concatenate([np.asarray(layer["vth"], dtype=np.uint8) for layer in q]).tobytes()
    raw = beta + vth
    assert len(raw) == PARAM_BYTES
    return raw


def slot_bytes(q):
    """128 B 정렬 섹션을 가진 132 KiB DDR3 모델 슬롯 이미지."""
    _check_q(q)
    image = bytearray(SLOT_SIZE)
    for offset, layer in zip(WEIGHT_OFFSETS, q):
        raw = np.asarray(layer["W"], dtype=np.int8).reshape(-1).tobytes()
        image[offset:offset + len(raw)] = raw
    beta = np.concatenate([np.asarray(layer["beta"], dtype=np.uint8) for layer in q]).tobytes()
    vth = np.concatenate([np.asarray(layer["vth"], dtype=np.uint8) for layer in q]).tobytes()
    image[BETA_OFFSET:BETA_OFFSET + len(beta)] = beta
    image[VTH_OFFSET:VTH_OFFSET + len(vth)] = vth
    return bytes(image)


def q_from_slot(data, scales=None):
    """슬롯 이미지만으로 INT8 순전파 파라미터를 복원한다."""
    if isinstance(data, (str, Path)):
        data = Path(data).read_bytes()
    if len(data) != SLOT_SIZE:
        raise ValueError(f"슬롯 크기 {len(data):,} B != {SLOT_SIZE:,} B")
    scales = [None] * len(WEIGHT_SHAPES) if scales is None else list(scales)
    if len(scales) != len(WEIGHT_SHAPES):
        raise ValueError("스케일 수가 층 수와 다름")
    beta_all = np.frombuffer(data, np.uint8, sum(NEURON_COUNTS), BETA_OFFSET).copy()
    vth_all = np.frombuffer(data, np.uint8, sum(NEURON_COUNTS), VTH_OFFSET).copy()
    q, neuron_at = [], 0
    for offset, shape, scale in zip(WEIGHT_OFFSETS, WEIGHT_SHAPES, scales):
        count = shape[0] * shape[1]
        w = np.frombuffer(data, np.int8, count, offset).copy().reshape(shape)
        stop = neuron_at + shape[0]
        q.append({"W": w, "beta": beta_all[neuron_at:stop],
                  "vth": vth_all[neuron_at:stop], "scale": scale})
        neuron_at = stop
    return q


def q_from_files(weights_path, params_path, scales=None):
    """패딩 없는 weights.bin과 params.bin에서 파라미터를 복원한다."""
    weights = Path(weights_path).read_bytes()
    params = Path(params_path).read_bytes()
    return q_from_files_bytes(weights, params, scales)


def q_from_files_bytes(weights, params, scales=None):
    """패딩 없는 weights/params bytes에서 파라미터를 복원한다."""
    if len(weights) != WEIGHT_BYTES or len(params) != PARAM_BYTES:
        raise ValueError(f"파일 크기 불일치: weights={len(weights):,}, params={len(params):,}")
    q, w_at, n_at = [], 0, 0
    beta_all = np.frombuffer(params[:sum(NEURON_COUNTS)], np.uint8)
    vth_all = np.frombuffer(params[sum(NEURON_COUNTS):], np.uint8)
    scales = [None] * len(WEIGHT_SHAPES) if scales is None else list(scales)
    if len(scales) != len(WEIGHT_SHAPES):
        raise ValueError("스케일 수가 층 수와 다름")
    for shape, scale in zip(WEIGHT_SHAPES, scales):
        count = shape[0] * shape[1]
        w = np.frombuffer(weights, np.int8, count, w_at).copy().reshape(shape)
        stop = n_at + shape[0]
        q.append({"W": w, "beta": beta_all[n_at:stop].copy(),
                  "vth": vth_all[n_at:stop].copy(), "scale": scale})
        w_at += count
        n_at = stop
    return q
