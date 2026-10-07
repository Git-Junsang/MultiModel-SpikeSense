"""P1.6/P1.7 산출물의 크기·레이아웃·비트 일치를 전수 검증한다."""

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


def digest(data):
    return hashlib.sha256(data).hexdigest()


def same_q(a, b):
    return all(np.array_equal(x[k], y[k]) for x, y in zip(a, b) for k in ("W", "beta", "vth"))


def verify_models(models_dir, weights_dir):
    manifest = json.loads((models_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["model_count"] == len(dd.UNITS) == 40
    assert manifest["slot_size"] == mf.SLOT_SIZE
    ddr = (models_dir / "models.ddr.bin").read_bytes()
    assert len(ddr) == 40 * mf.SLOT_SIZE
    assert digest(ddr) == manifest["ddr_image_sha256"]

    for model_id, ((machine, mid), entry) in enumerate(zip(dd.UNITS, manifest["models"])):
        unit = dd.unit_name(machine, mid)
        assert entry["model_id"] == model_id and entry["unit"] == unit
        target = models_dir / unit
        weights = (target / "weights.bin").read_bytes()
        params = (target / "params.bin").read_bytes()
        slot = (target / "model.slot.bin").read_bytes()
        assert len(weights) == mf.WEIGHT_BYTES == 130_176
        assert len(params) == mf.PARAM_BYTES == 1_412
        assert len(slot) == mf.SLOT_SIZE
        assert slot == ddr[model_id * mf.SLOT_SIZE:(model_id + 1) * mf.SLOT_SIZE]
        for name, data in (("weights.bin", weights), ("params.bin", params), ("model.slot.bin", slot)):
            assert digest(data) == entry["sha256"][name]
        hex_weights = bytes(int(line, 16) for line in (target / "weights.hex").read_text().splitlines())
        hex_params = bytes(int(line, 16) for line in (target / "params.hex").read_text().splitlines())
        assert hex_weights == weights and hex_params == params

        direct = si.quantize(sn.load_params(weights_dir / unit / "last.pth"))
        assert same_q(direct, mf.q_from_files(target / "weights.bin", target / "params.bin"))
        assert same_q(direct, mf.q_from_slot(slot))
    return manifest


def load_arrays(path):
    with np.load(path) as data:
        return {key: data[key] for key in data.files}


def compare_arrays(expected, actual):
    assert expected.keys() == actual.keys()
    for key in expected:
        assert expected[key].dtype == actual[key].dtype, key
        assert np.array_equal(expected[key], actual[key]), key


def verify_golden(models_dir, golden_dir):
    manifest = json.loads((golden_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["real_vector_count"] == 80
    for record in manifest["records"]:
        q = mf.q_from_slot(models_dir / record["unit"] / "model.slot.bin")
        path = golden_dir / record["unit"] / f"{record['tag']}.npz"
        saved = load_arrays(path)
        current, stats = trace_from_saved_input(saved["input"], q)
        compare_arrays(saved, current)
        assert stats["sat"] == record["saturation_counts"]
        assert np.array_equal(saved["output_mem"], saved["mem_l4"])

    for record in manifest["stress"]:
        tag = record["tag"].removeprefix("stress_")
        target = golden_dir / "stress" / tag
        q = mf.q_from_slot(target / "model.slot.bin")
        saved = load_arrays(target / "vector.npz")
        current, stats = trace_from_saved_input(saved["input"], q)
        compare_arrays(saved, current)
        assert stats["sat"] == record["saturation_counts"]
        assert sum(stats["sat"]) > 0
    return manifest


def trace_from_saved_input(x_q, q):
    stats, trace = {}, {}
    out = si.forward(q, np.asarray(x_q, np.int64)[None], stats=stats, trace=trace)[0]
    arrays = {"input": np.asarray(x_q, np.uint8), "output_mem": out.astype(np.int16)}
    for i in range(4):
        arrays[f"cur_l{i + 1}"] = trace["cur"][i][0]
        arrays[f"mem_pre_l{i + 1}"] = trace["mem_pre"][i][0]
        arrays[f"spk_l{i + 1}"] = trace["spk"][i][0]
        arrays[f"mem_l{i + 1}"] = trace["mem"][i][0]
    return arrays, stats


def verify_integer_matmul(models_dir, golden_dir):
    """float64 BLAS 누산과 직접 int64 행렬곱이 대표 벡터에서 같은지 확인한다."""
    q = mf.q_from_slot(models_dir / "fan_id01" / "model.slot.bin")
    x = load_arrays(golden_dir / "fan_id01" / "normal.npz")["input"].astype(np.int64)
    reference = load_arrays(golden_dir / "fan_id01" / "normal.npz")
    mems = [np.zeros(layer["W"].shape[0], np.int64) for layer in q]
    got = {key: [] for key in reference if key != "input"}
    for sample in x:
        h = sample
        for i, layer in enumerate(q):
            acc = h.astype(np.int64) @ layer["W"].astype(np.int64).T
            cur = acc >> si.IN_SHIFT if i == 0 else acc
            mem = ((layer["beta"].astype(np.int64) * mems[i]) >> si.BETA_SHIFT) + cur
            mem = np.clip(mem, si.MEM_MIN, si.MEM_MAX)
            spk = (mem >= layer["vth"].astype(np.int64)).astype(np.int64)
            mems[i] = mem - spk * layer["vth"].astype(np.int64)
            got[f"cur_l{i + 1}"].append(cur.astype(np.int32))
            got[f"mem_pre_l{i + 1}"].append(mem.astype(np.int16))
            got[f"spk_l{i + 1}"].append(spk.astype(np.uint8))
            got[f"mem_l{i + 1}"].append(mems[i].astype(np.int16))
            h = spk
        got["output_mem"].append(mems[-1].astype(np.int16))
    for key, rows in got.items():
        assert np.array_equal(np.asarray(rows), reference[key]), key


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", type=Path, default=ROOT / "hardware" / "data" / "models")
    ap.add_argument("--golden", type=Path, default=ROOT / "hardware" / "data" / "golden")
    ap.add_argument("--weights", type=Path, default=ROOT / "software" / "model_weights")
    args = ap.parse_args()
    verify_models(args.models, args.weights)
    golden = verify_golden(args.models, args.golden)
    verify_integer_matmul(args.models, args.golden)
    saturation = [item["saturation_counts"] for item in golden["stress"]]
    print(f"PASS: 모델 40개, 실데이터 벡터 80개, stress 2개, 포화={saturation}")


if __name__ == "__main__":
    main()
