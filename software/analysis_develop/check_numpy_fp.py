"""P0.8 NumPy 순전파 검증.

1) 선행 재현: 선행 SpikeSense-Edge `test_model_numpy.py`(INT8, `40→128→32→2`)를 선행
   저장소의 가중치 HEX로 돌려 선행 골든 벡터(막전위·스파이크)와 비트 단위로 비교한다.
   선행 저장소는 읽기만 한다.
2) FP 일치: 학습한 40대 모델(`model_weights/<장비>/last.pth`)마다 DCASE test 평가 세트
   (train.prepare의 supervised 분할, 학습과 같은 seed)를 PyTorch(CPU FP32)와
   `snn_numpy`(FP32)로 순전파해 층별 스파이크·출력 막전위·판정·파일 단위 AUC를 비교한다.
   스파이크가 다르면 처음 달라진 지점의 |mem - thr|를 기록해 반올림 차이인지 확인한다.

결과: analysis_develop/numpy_fp/{results.csv, prior.txt}
사용법: python3 analysis_develop/check_numpy_fp.py [--units fan_id01 ...]
"""

import os
import sys
import csv
import argparse
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SOFTWARE = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(SOFTWARE, "model_develop"))

import torch
from sklearn.metrics import roc_auc_score

import dcase_data as dd
import train
import snn_numpy as sn
from snn_model import AnomalySNN

PRIOR_WEIGHTS = "/mnt/nas/data/2026-CAU/서울대학교 학부인턴/Project/SpikeSense-Edge/hardware/src/weights"
OUT = os.path.join(HERE, "numpy_fp")


def check_prior():
    # references/에는 선행 train.py도 있어 sys.path에 넣지 않고 파일로 읽는다
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "prior_test_model_numpy", os.path.join(SOFTWARE, "model_develop", "references", "test_model_numpy.py"))
    t = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(t)
    w = PRIOR_WEIGHTS
    W1 = t.load_int8_hex(f"{w}/w1.hex", (128, 40))
    W2 = t.load_int8_hex(f"{w}/w2.hex", (32, 128))
    W3 = t.load_int8_hex(f"{w}/w3.hex", (2, 32))
    b = t.load_uint8_hex(f"{w}/beta.hex", (162,))
    v = t.load_vth(f"{w}/vth.hex", "int8", (162,))
    lines, ok = [], True
    for tag in ("normal", "anomaly"):
        mel = np.load(f"{w}/golden/{tag}_mel.npy")
        spk, mem, _, _ = t.snn_forward(mel, W1, W2, W3, b[:128], b[128:160], b[160:],
                                       v[:128], v[128:160], v[160:])
        g_mem = np.load(f"{w}/golden/{tag}_mem_out.npy")
        g_spk = np.load(f"{w}/golden/{tag}_spk_out.npy")
        g_hex = np.array([int(s, 16) for s in open(f"{w}/golden/{tag}_mem_out.hex").read().split()],
                         np.uint16).astype(np.int16)
        r = (np.array_equal(mem, g_mem), np.array_equal(spk, g_spk), np.array_equal(mem.ravel(), g_hex))
        ok &= all(r)
        lines.append(f"{tag:8s} mel{mel.shape} mem_npy={r[0]} spk_npy={r[1]} mem_hex={r[2]} "
                     f"판정={t.classify(mem)[0]}")
    lines.append(f"선행 재현: {'PASS' if ok else 'FAIL'}")
    return ok, lines


def clip_auc(prob, y, f):
    nf = f.max() + 1
    score = np.bincount(f, prob, nf) / np.bincount(f, minlength=nf)
    cy = np.bincount(f, y, nf) / np.bincount(f, minlength=nf)
    return roc_auc_score(cy, score)


def softmax_p1(mean_mem):
    z = mean_mem - mean_mem.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e[:, 1] / e.sum(axis=1)


def first_div_margin(layers, x, t_spk):
    """세그먼트별로 스파이크가 처음 달라진 지점에서 NumPy 막전위와 임계값의 차 |mem - thr|.

    반환: (분기 세그먼트 수, 최대 |mem - thr|). 반올림 차이라면 ~1e-6 이하다.
    """
    B, T, _ = x.shape
    mems = [np.zeros((B, l["W"].shape[0]), sn.DTYPE) for l in layers]
    first = {}
    for t in range(T):
        h = x[:, t, :]
        for k, l in enumerate(layers):
            mem = l["beta"] * mems[k] + h @ l["W"].T
            spk = (mem >= l["thr"]).astype(sn.DTYPE)
            for b, n in np.argwhere(spk != t_spk[k][:, t]):
                first.setdefault(int(b), float(abs(mem[b, n] - l["thr"][n])))
            mems[k] = mem - spk * l["thr"]
            h = spk
    return len(first), max(first.values(), default=0.0)


@torch.no_grad()
def check_unit(machine, mid, ref_auc):
    unit = dd.unit_name(machine, mid)
    pth = os.path.join(SOFTWARE, "model_weights", unit, "last.pth")
    ckpt = torch.load(pth, map_location="cpu", weights_only=False)
    a = ckpt["args"]
    data = train.prepare(machine, mid, a["method"], a["val_frac"], a["seed"], "cpu", a.get("hop"))
    x = data["test_seg"]
    y, f = data["test_label"], data["test_file"]

    model = AnomalySNN()
    model.load_state_dict(ckpt["model_state_dict"])
    model.eval()
    layers = sn.load_params(pth)

    # 층별 스파이크를 함께 받기 위해 PyTorch 쪽도 층 루프를 직접 돈다(모듈 호출은 그대로).
    B, T, _ = x.shape
    t_mems = [lif.init_membrane(B) for lif in model.lifs]
    t_spk = [[] for _ in model.lifs]
    t_mem_out = []
    for t in range(T):
        h = x[:, t, :]
        for i, (fc, lif) in enumerate(zip(model.fcs, model.lifs)):
            h, t_mems[i] = lif(fc(h), t_mems[i])
            t_spk[i].append(h)
        t_mem_out.append(t_mems[-1].clone())
    t_mem_out = torch.stack(t_mem_out, 1).numpy()
    t_spk = [torch.stack(s, 1).numpy() for s in t_spk]

    # 모델 forward와 같은지도 확인(위 루프가 모델 동작을 바꾸지 않았는지)
    _, m_mem, _ = model(x)
    assert np.array_equal(m_mem.numpy(), t_mem_out)

    n_mem, n_spk = sn.forward(layers, x.numpy())

    t_mean, n_mean = t_mem_out.mean(1), n_mem.mean(1)
    row = {"unit": unit, "n_seg": B, "T": T}
    for i, (ts, ns) in enumerate(zip(t_spk, n_spk), 1):
        row[f"spk_diff_L{i}"] = int((ts != ns).sum())
    row["spk_total"] = int(sum(s.size for s in t_spk))
    row["div_seg"], row["div_margin_max"] = first_div_margin(layers, x.numpy(), t_spk)
    row["mem_max_abs_diff"] = float(np.abs(t_mem_out - n_mem).max())
    row["mem_mean_max_abs_diff"] = float(np.abs(t_mean - n_mean).max())
    row["pred_diff"] = int((t_mean.argmax(1) != sn.predict(n_mem)).sum())
    row["auc_torch_cpu"] = round(clip_auc(softmax_p1(t_mean), y, f), 6)
    row["auc_numpy"] = round(clip_auc(softmax_p1(n_mean), y, f), 6)
    row["auc_results_csv"] = ref_auc
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--units", nargs="*", default=None, help="예: fan_id01 pump_id00 (기본: 40대)")
    ap.add_argument("--threads", type=int, default=12)
    args = ap.parse_args()
    torch.set_num_threads(args.threads)
    os.makedirs(OUT, exist_ok=True)

    ok, lines = check_prior()
    print("\n".join(lines))
    with open(os.path.join(OUT, "prior.txt"), "w") as fp:
        fp.write("\n".join(lines) + "\n")

    ref = {}
    with open(os.path.join(SOFTWARE, "analysis_data", "all40", "results.csv")) as fp:
        for r in csv.DictReader(fp):
            ref[r["unit"]] = float(r["test_auc"])

    units = [(m, i) for m, i in dd.UNITS if not args.units or dd.unit_name(m, i) in args.units]
    rows = []
    for m, i in units:
        r = check_unit(m, i, ref.get(dd.unit_name(m, i)))
        rows.append(r)
        print(f"{r['unit']:17s} seg={r['n_seg']:5d} spk_diff="
              f"{r['spk_diff_L1']}/{r['spk_diff_L2']}/{r['spk_diff_L3']}/{r['spk_diff_L4']} "
              f"div_seg={r['div_seg']} margin={r['div_margin_max']:.1e} "
              f"mem_max={r['mem_max_abs_diff']:.2e} pred_diff={r['pred_diff']} "
              f"AUC torch={r['auc_torch_cpu']:.4f} numpy={r['auc_numpy']:.4f} csv={r['auc_results_csv']}",
              flush=True)

    name = "results.csv" if not args.units else "results_subset.csv"
    with open(os.path.join(OUT, name), "w", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"저장: {OUT}/{name}")


if __name__ == "__main__":
    main()
