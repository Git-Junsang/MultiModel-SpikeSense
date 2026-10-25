"""P1.7: 내보낸 모델만 읽어 INT8 RTL 대조용 golden vector를 만든다.

모델당 test 세트의 첫 정상·이상 세그먼트를 사용한다. 각 NPZ는 입력과 모든 layer의
전류, 포화 후/발화 전 membrane potential, spike, soft reset 후 membrane potential을 담는다.
fan_id01 정상 벡터는 $readmemh용 HEX로도 생성한다.

프로젝트 루트에서:
  python3 software/model/export_golden.py                # 1lane, L
  python3 software/model/export_golden.py --format l64   # L, 64 lane → hardware/data/golden_l64
  python3 software/model/export_golden.py --format l64 --mem-bits 12   # 12 bit 저장 → golden_l64_m12
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dataset"))  # dcase_data는 software/dataset
import dcase_data as dd  # noqa: E402
import model_format_1lane
import model_format_64lane
import snn_int8 as si

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE = ROOT / "software" / "dataset" / "mel_dcase"
FORMATS = {"1lane": model_format_1lane, "l64": model_format_64lane.L64, "xl": model_format_64lane.XL}
mf = model_format_1lane                   # main()이 --format으로 바꾼다
mem_bits = 16                          # main()이 --mem-bits로 바꾼다


def trace_arrays(x_q, q):
    stats, trace = {}, {}
    out = si.forward(q, x_q[None], stats=stats, trace=trace, store_bits=mem_bits)[0]
    arrays = {"input": x_q.astype(np.uint8), "output_mem": out.astype(np.int16)}
    for i in range(len(q)):
        arrays[f"cur_l{i + 1}"] = trace["cur"][i][0]
        arrays[f"mem_pre_l{i + 1}"] = trace["mem_pre"][i][0]
        arrays[f"spk_l{i + 1}"] = trace["spk"][i][0]
        arrays[f"mem_l{i + 1}"] = trace["mem"][i][0]
    return arrays, stats


def save_hex(path, array, bits):
    mask = (1 << bits) - 1
    width = bits // 4
    values = np.asarray(array).reshape(-1).astype(np.int64)
    path.write_text("".join(f"{int(value) & mask:0{width}x}\n" for value in values), encoding="ascii")


def save_rtl_hex(out_dir, arrays):
    out_dir.mkdir(parents=True, exist_ok=True)
    save_hex(out_dir / "input.hex", arrays["input"], 8)
    save_hex(out_dir / "output_mem.hex", arrays["output_mem"], 16)
    for i in range(1, 5):
        save_hex(out_dir / f"l{i}_cur.hex", arrays[f"cur_l{i}"], 32)
        save_hex(out_dir / f"l{i}_mem_pre.hex", arrays[f"mem_pre_l{i}"], 16)
        save_hex(out_dir / f"l{i}_spk.hex", arrays[f"spk_l{i}"], 8)
        save_hex(out_dir / f"l{i}_mem.hex", arrays[f"mem_l{i}"], 16)


def real_vectors(models_dir, cache_dir, out_dir, hex_unit):
    records = []
    for model_id, (machine, mid) in enumerate(dd.UNITS):
        unit = dd.unit_name(machine, mid)
        q = mf.q_from_slot(models_dir / unit / "model.slot.bin")
        cache_path = cache_dir / f"{unit}_test_seg31.npz"
        with np.load(cache_path) as data:
            for tag, label in (("normal", 0), ("anomaly", 1)):
                hits = np.flatnonzero(data["label"] == label)
                if not len(hits):
                    raise RuntimeError(f"{unit}: {tag} 세그먼트가 없음")
                index = int(hits[0])
                x_q = si.quantize_input(data["seg"][index])
                arrays, stats = trace_arrays(x_q, q)
                unit_dir = out_dir / unit
                unit_dir.mkdir(parents=True, exist_ok=True)
                np.savez_compressed(unit_dir / f"{tag}.npz", **arrays)
                record = {
                    "model_id": model_id, "unit": unit, "tag": tag, "label": label,
                    "cache": str(cache_path.relative_to(ROOT)), "segment_index": index,
                    "timesteps": int(x_q.shape[0]), "prediction": int(si.predict(arrays["output_mem"][None])[0]),
                    "saturation_counts": stats["sat"], "store_clip_counts": stats["clip"],
                }
                records.append(record)
                if unit == hex_unit and tag == "normal":
                    save_rtl_hex(out_dir / "rtl_hex" / f"{unit}_{tag}", arrays)
        print(f"[{model_id:02d}] {unit:17s} normal/anomaly")
    return records


def stress_vectors(out_dir):
    records = []
    for tag, weight in (("positive", 127), ("negative", -128)):
        q = []
        for shape in mf.WEIGHT_SHAPES:
            q.append({"W": np.full(shape, weight, np.int8),
                      "beta": np.full(shape[0], 255, np.uint8),
                      "vth": np.full(shape[0], 255, np.uint8)})
        x_q = np.full((31, mf.LAYER_SIZES[0]), 127, np.int64)
        arrays, stats = trace_arrays(x_q, q)
        if sum(stats["sat"]) + sum(stats["clip"]) == 0:   # 12 bit 저장이면 negative는 16 bit 포화 대신 저장 포화만 탄다
            raise RuntimeError(f"stress_{tag}가 포화 경로를 실행하지 않음")
        target = out_dir / "stress" / tag
        target.mkdir(parents=True, exist_ok=True)
        (target / "model.slot.bin").write_bytes(mf.slot_bytes(q))
        np.savez_compressed(target / "vector.npz", **arrays)
        save_rtl_hex(target / "rtl_hex", arrays)
        records.append({"tag": f"stress_{tag}", "timesteps": 31,
                        "saturation_counts": stats["sat"], "store_clip_counts": stats["clip"]})
        print(f"stress_{tag}: saturation={stats['sat']}")
    return records


def main():
    global mf, mem_bits
    ap = argparse.ArgumentParser()
    ap.add_argument("--format", choices=FORMATS, default="1lane")
    ap.add_argument("--models", type=Path, help="모델 폴더 (기본: 형식별)")
    ap.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    ap.add_argument("--out", type=Path, help="출력 폴더 (기본: 형식별)")
    ap.add_argument("--hex-unit", default="fan_id01")
    ap.add_argument("--mem-bits", type=int, default=16, help="다음 timestep으로 넘기는 membrane potential 저장 bit")
    args = ap.parse_args()
    mf, mem_bits = FORMATS[args.format], args.mem_bits
    args.models = args.models or ROOT / mf.MODELS_DIR
    args.out = args.out or ROOT / (mf.GOLDEN_DIR + (f"_m{mem_bits}" if mem_bits != 16 else ""))
    args.out.mkdir(parents=True, exist_ok=True)
    records = real_vectors(args.models, args.cache, args.out, args.hex_unit)
    stress = stress_vectors(args.out)
    manifest = {"format_version": 1, "integer_reference": "software/model/snn_int8.py", "mem_store_bits": mem_bits,
                "real_vector_count": len(records), "records": records, "stress": stress}
    (args.out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"실데이터 golden {len(records)}개 + 포화 stress {len(stress)}개 -> {args.out}")


if __name__ == "__main__":
    main()
