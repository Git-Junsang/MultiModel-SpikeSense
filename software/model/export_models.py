"""P1.6: 40개 INT8 모델을 바이너리·HEX와 DDR3 이미지로 내보낸다.

프로젝트 루트에서:
  python3 software/model_develop/export_models.py
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

import dcase_data as dd
import model_format as mf
import snn_int8 as si
import snn_numpy as sn

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WEIGHTS = ROOT / "software" / "model_weights"
DEFAULT_OUT = ROOT / "hardware" / "data" / "models"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def write_hex(path, data):
    path.write_text("".join(f"{value:02x}\n" for value in data), encoding="ascii")


def equal_q(a, b):
    return all(np.array_equal(x[k], y[k]) for x, y in zip(a, b) for k in ("W", "beta", "vth"))


def export_one(model_id, unit, checkpoint, out_dir, ddr_base):
    layers = sn.load_params(checkpoint)
    q = si.quantize(layers)
    weights = mf.weights_bytes(q)
    params = mf.params_bytes(q)
    slot = mf.slot_bytes(q)
    if not equal_q(q, mf.q_from_slot(slot)):
        raise RuntimeError(f"{unit}: 슬롯 재로드 검증 실패")
    if not equal_q(q, mf.q_from_files_bytes(weights, params)):
        raise RuntimeError(f"{unit}: 패딩 파일 재로드 검증 실패")

    unit_dir = out_dir / unit
    unit_dir.mkdir(parents=True, exist_ok=True)
    (unit_dir / "weights.bin").write_bytes(weights)
    write_hex(unit_dir / "weights.hex", weights)
    (unit_dir / "params.bin").write_bytes(params)
    write_hex(unit_dir / "params.hex", params)
    (unit_dir / "model.slot.bin").write_bytes(slot)

    scales = [float(layer["scale"]) for layer in q]
    try:
        checkpoint_name = str(checkpoint.relative_to(ROOT))
    except ValueError:
        checkpoint_name = str(checkpoint)
    meta = {
        "format_version": 1,
        "model_id": model_id,
        "unit": unit,
        "checkpoint": checkpoint_name,
        "layer_sizes": list(mf.LAYER_SIZES),
        "weight_scales": scales,
        "weights_bytes": len(weights),
        "params_bytes": len(params),
        "slot_bytes": len(slot),
        "slot_offset": model_id * mf.SLOT_SIZE,
        "slot_offset_hex": f"0x{model_id * mf.SLOT_SIZE:08X}",
        "ddr_address": ddr_base + model_id * mf.SLOT_SIZE,
        "ddr_address_hex": f"0x{ddr_base + model_id * mf.SLOT_SIZE:08X}",
        "sha256": {"weights.bin": sha256(weights), "params.bin": sha256(params),
                   "model.slot.bin": sha256(slot)},
    }
    (unit_dir / "metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return meta, slot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--ddr-base", type=lambda x: int(x, 0), default=0,
                    help="DDR3 모델 영역 기준 주소(기본 0, 0x 표기 가능)")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    entries, slots = [], []
    for model_id, (machine, mid) in enumerate(dd.UNITS):
        unit = dd.unit_name(machine, mid)
        checkpoint = args.weights / unit / "last.pth"
        if not checkpoint.is_file():
            raise FileNotFoundError(checkpoint)
        meta, slot = export_one(model_id, unit, checkpoint.resolve(), args.out, args.ddr_base)
        entries.append(meta)
        slots.append(slot)
        print(f"[{model_id:02d}] {unit:17s} weights={meta['weights_bytes']:,} B "
              f"slot={meta['slot_offset_hex']}")

    ddr = b"".join(slots)
    (args.out / "models.ddr.bin").write_bytes(ddr)
    manifest = {
        "format_version": 1,
        "model_count": len(entries),
        "ddr_base": args.ddr_base,
        "ddr_base_hex": f"0x{args.ddr_base:08X}",
        "slot_size": mf.SLOT_SIZE,
        "slot_size_hex": f"0x{mf.SLOT_SIZE:X}",
        "alignment": mf.ALIGN,
        "weight_offsets": list(mf.WEIGHT_OFFSETS),
        "beta_offset": mf.BETA_OFFSET,
        "vth_offset": mf.VTH_OFFSET,
        "weights_bytes_per_model": mf.WEIGHT_BYTES,
        "params_bytes_per_model": mf.PARAM_BYTES,
        "ddr_image_bytes": len(ddr),
        "ddr_image_sha256": sha256(ddr),
        "models": entries,
    }
    (args.out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"40개 모델, DDR3 이미지 {len(ddr):,} B -> {args.out}")


if __name__ == "__main__":
    main()
