"""P1.6/P1.7·P3.10 산출물의 크기·레이아웃·비트 일치를 전수 검증한다.

  python3 software/model/verify_export.py                # v1, L
  python3 software/model/verify_export.py --format l64   # L, 64 lane (xl: XL_mixed_aug, 256 lane)
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dataset"))  # dcase_data는 software/dataset
import dcase_data as dd  # noqa: E402
import model_format_v1
import model_format_v2
import snn_int8 as si
import snn_fp32 as sn

ROOT = Path(__file__).resolve().parents[2]
FORMATS = {"v1": model_format_v1, "l64": model_format_v2.L64, "xl": model_format_v2.XL}
mf = model_format_v1                   # main()이 --format으로 바꾼다


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
        assert len(weights) == mf.WEIGHT_BYTES
        assert len(params) == mf.PARAM_BYTES
        assert len(slot) == mf.SLOT_SIZE
        assert slot == ddr[model_id * mf.SLOT_SIZE:(model_id + 1) * mf.SLOT_SIZE]
        for name, data in (("weights.bin", weights), ("params.bin", params), ("model.slot.bin", slot)):
            assert digest(data) == entry["sha256"][name]
        for name, text in mf.hex_files(weights, params).items():
            assert (target / name).read_text(encoding="ascii") == text, name

        direct = si.quantize(sn.load_params(weights_dir / unit / "last.pth"))
        assert same_q(direct, mf.q_from_files(target / "weights.bin", target / "params.bin"))
        assert same_q(direct, mf.q_from_slot(slot))
    return manifest


# design_references/02_MODEL.md §6에 적은 값. model_format_v2가 계산한 값과 따로 둔다
SPEC_V2 = {"l64": dict(lanes=64, offs=(0x005C0, 0x041C0, 0x1C1C0, 0x201C0), words=2034),
           "xl": dict(lanes=256, offs=(0x00B40, 0x08340, 0x68340, 0x78340), words=2169)}


def verify_v2_layout(fmt, models_dir, weights_dir, unit="fan_id01"):
    """02_MODEL.md §6 주소식으로 byte를 직접 찾아 checkpoint 양자화 값과 비교한다(model_format_v2 변환과 독립)."""
    spec = SPEC_V2[fmt]
    lanes = spec["lanes"]
    q = si.quantize(sn.load_params(weights_dir / unit / "last.pth"))
    ws = [layer["W"] for layer in q]
    slot = np.frombuffer((models_dir / unit / "model.slot.bin").read_bytes(), np.int8)
    for w, off in zip(ws[:-1], spec["offs"]):
        n, k = w.shape
        if n >= lanes:
            g, i, j = np.meshgrid(range(n // lanes), range(k), range(lanes), indexing="ij")
            assert np.array_equal(slot[off + (g * k + i) * lanes + j], w[lanes * g + j, i])
        else:
            i, j = np.meshgrid(range(k), range(n), indexing="ij")
            assert np.array_equal(slot[off + i * n + j], w[j, i])
    w = ws[-1]
    j = np.arange(w.size)
    assert np.array_equal(slot[spec["offs"][-1] + j], w[j // w.shape[1], j % w.shape[1]])
    beta = np.concatenate([layer["beta"] for layer in q])
    vth = np.concatenate([layer["vth"] for layer in q])
    n = np.arange(beta.size)
    assert np.array_equal(slot.view(np.uint8)[2 * n], beta) and np.array_equal(slot.view(np.uint8)[2 * n + 1], vth)

    lines = (models_dir / unit / "entry.hex").read_text(encoding="ascii").splitlines()
    assert len(lines) == spec["words"] and all(len(line) == 2 * lanes for line in lines)
    word = lambda k: np.frombuffer(bytes.fromhex(lines[k])[::-1], np.int8)     # lane 0 = 최하위 byte
    at = 0
    for w in ws[:-1]:                                     # layer마다 첫 word = 첫 그룹의 입력 0
        n = min(w.shape[0], lanes)
        assert np.array_equal(word(at)[:n], w[:n, 0]) and not word(at)[n:].any()
        at += -(-w.shape[0] // lanes) * w.shape[1]
    assert np.array_equal(np.concatenate([word(k) for k in range(at, spec["words"])]), ws[-1].reshape(-1))
    params = (models_dir / unit / "params.hex").read_text(encoding="ascii").splitlines()
    assert [int(x, 16) for x in params] == [(int(v) << 8) | int(b) for b, v in zip(beta, vth)]


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
    global mf
    ap = argparse.ArgumentParser()
    ap.add_argument("--format", choices=FORMATS, default="v1")
    ap.add_argument("--models", type=Path, help="기본: 형식별")
    ap.add_argument("--golden", type=Path, help="기본: 형식별")
    ap.add_argument("--weights", type=Path, help="기본: 형식별")
    args = ap.parse_args()
    mf = FORMATS[args.format]
    args.models = args.models or ROOT / mf.MODELS_DIR
    args.golden = args.golden or ROOT / mf.GOLDEN_DIR
    args.weights = args.weights or ROOT / mf.WEIGHTS_DIR
    verify_models(args.models, args.weights)
    if args.format in SPEC_V2:
        verify_v2_layout(args.format, args.models, args.weights)
    golden = verify_golden(args.models, args.golden)
    verify_integer_matmul(args.models, args.golden)
    saturation = [item["saturation_counts"] for item in golden["stress"]]
    print(f"PASS {args.format}: 모델 40개, 실데이터 벡터 80개, stress 2개, 포화={saturation}")


if __name__ == "__main__":
    main()
