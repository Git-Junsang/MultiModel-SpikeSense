"""P4.1: golden 82개(golden_l64 또는 12 bit 저장 golden_l64_m12)를 tb_compute_array.sv가 읽는 hex로 바꾼다.

모델은 slot image(model.slot.bin)에서 바로 entry 형식을 만든다. 실데이터 모델은 entry.hex와 같은지 확인한다.

출력 (기본 hardware/sim/compute_array/vec/, 저장 bit가 16이 아니면 vec_m<bit>/)
  index.hex       vector마다 모델 번호
  mMM_w.hex       word 2,034줄 × 512 bit, lane j = bit [8j+7:8j]
  mMM_p.hex       params row 46줄 × 256 bit = slot params section의 32 B beat
  vVV_x.hex       31줄 × 320 bit, byte i = mel input i
  vVV_e.hex       31 × 45줄, row마다 {spk 16, mem 16×16, mem_sat 16×16, cur 16×24} (912 bit). mem은 저장한 값
  vVV_o.hex       31줄 × 32 bit, {out1, out0} = 판정용 출력(저장 전 layer 4 membrane potential)

프로젝트 루트에서:
  python3 hardware/testbench/export_compute_vectors.py
  python3 hardware/testbench/export_compute_vectors.py --golden hardware/data/golden_l64_m12
"""

import argparse
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "hardware/data/models_l64"
LAYERS = (384, 256, 64, 2)
ROWS = 45                 # 706뉴런 / 16
WORDS, PARAM_ROWS, PARAM_BYTES = 2034, 46, 1472


def hex_lines(rows):
    """uint8 [N, B] (byte 0 = LSB) → hex 줄"""
    return "".join(r[::-1].tobytes().hex() + "\n" for r in rows)


def write_model(slot_path, out, m):
    slot = np.frombuffer(slot_path.read_bytes(), np.uint8)
    params = slot[:PARAM_BYTES].reshape(PARAM_ROWS, 32)
    words = slot[PARAM_BYTES:PARAM_BYTES + WORDS * 64].reshape(WORDS, 64)
    w_hex = hex_lines(words)
    entry = slot_path.parent / "entry.hex"
    if entry.exists() and entry.read_text().lower() != w_hex:
        raise RuntimeError(f"{entry}: slot에서 만든 word와 다름")
    (out / f"m{m:02d}_w.hex").write_text(w_hex)
    (out / f"m{m:02d}_p.hex").write_text(hex_lines(params))


def lanes(values, bits):
    """int [T, 16] → 16 lane을 bits씩 묶은 정수 (lane 0 = LSB)"""
    mask = (1 << bits) - 1
    out = []
    for row in values:
        v = 0
        for k in range(15, -1, -1):
            v = (v << bits) | (int(row[k]) & mask)
        out.append(v)
    return out


def write_vector(npz_path, out, v):
    d = np.load(npz_path)
    T = d["input"].shape[0]
    x = d["input"].astype(np.uint8)
    (out / f"v{v:02d}_x.hex").write_text(hex_lines(x))

    # 뉴런 706개를 row 45개 × 16 lane으로 편다(layer 4 lane 2~15는 0)
    def rows(key):
        a = np.concatenate([d[f"{key}_l{l + 1}"] for l in range(4)], axis=1).astype(np.int64)
        a = np.concatenate([a, np.zeros((T, ROWS * 16 - a.shape[1]), np.int64)], axis=1)
        return a.reshape(T * ROWS, 16)

    cur, ms, mem, spk = rows("cur"), rows("mem_pre"), rows("mem"), rows("spk")
    cur_v, ms_v, mem_v, spk_v = lanes(cur, 24), lanes(ms, 16), lanes(mem, 16), lanes(spk, 1)
    lines = []
    for c, s, m, k in zip(cur_v, ms_v, mem_v, spk_v):
        lines.append(f"{(k << 896) | (m << 640) | (s << 384) | c:0228x}\n")
    (out / f"v{v:02d}_e.hex").write_text("".join(lines))
    (out / f"v{v:02d}_o.hex").write_text("".join(f"{v:08x}\n" for v in lanes(np.pad(d["output_mem"], ((0, 0), (0, 14))), 16)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", type=Path, default=ROOT / "hardware/data/golden_l64")
    ap.add_argument("--out", type=Path, help="기본: hardware/sim/compute_array/vec[_m<저장 bit>]")
    args = ap.parse_args()
    golden = args.golden.resolve()
    manifest = json.loads((golden / "manifest.json").read_text())
    bits = manifest.get("mem_store_bits", 16)
    args.out = args.out or ROOT / ("hardware/sim/compute_array/vec" + (f"_m{bits}" if bits != 16 else ""))
    args.out.mkdir(parents=True, exist_ok=True)

    index, models = [], {}
    vectors = [(golden / r["unit"] / f"{r['tag']}.npz", MODELS / r["unit"] / "model.slot.bin")
               for r in manifest["records"]]
    vectors += [(golden / "stress" / s["tag"].removeprefix("stress_") / "vector.npz",
                 golden / "stress" / s["tag"].removeprefix("stress_") / "model.slot.bin")
                for s in manifest["stress"]]
    for v, (npz, slot) in enumerate(vectors):
        if slot not in models:
            models[slot] = len(models)
            write_model(slot, args.out, models[slot])
        index.append(models[slot])
        write_vector(npz, args.out, v)
    (args.out / "index.hex").write_text("".join(f"{m:02x}\n" for m in index))
    print(f"vector {len(vectors)}개, 모델 {len(models)}개, 저장 {bits} bit → {args.out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
