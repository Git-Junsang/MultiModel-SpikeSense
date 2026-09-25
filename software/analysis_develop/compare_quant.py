"""P1.5 INT8 양자화 정확도 비교 (선행 `compare_quant.py` 확장).

1) 정수 규칙 확인: `snn_int8.forward`에 선행 SpikeSense-Edge의 INT8 가중치 HEX(`40→128→32→2`)를
   넣어 선행 골든 벡터(출력 막전위·스파이크)와 비트 단위로 비교한다. 선행 RTL과 같은 정수
   규칙인지 확인하는 용도다. 선행 골든은 넘침이 없어 포화 추가와 무관하게 같아야 한다.
2) 40대 비교: `model_weights/<장비>/last.pth`를 `snn_int8.quantize`로 변환해 DCASE test 평가 세트
   (train.prepare의 supervised 분할, 학습과 같은 seed)에서 FP32(`snn_numpy`)와 비교한다.
   지표: 파일 단위 AUC·pAUC, 균형 F1·정확도, 세그먼트 판정 일치율, 층별 스파이크 불일치율,
   층별 누산·막전위 |최대|와 16 bit 포화 횟수, 파라미터 범위.
   INT8 점수는 출력 막전위 평균 × 출력층 스케일에 softmax를 씌운 P(이상)이다(FP와 같은 식).

결과: analysis_develop/quant_int8/{results.csv, summary.txt, prior.txt}
사용법: python3 analysis_develop/compare_quant.py [--units fan_id01 ...]
"""

import os
import sys
import csv
import argparse
import importlib.util
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SOFTWARE = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(SOFTWARE, "model_develop"))

import torch
from sklearn.metrics import roc_auc_score, f1_score

import dcase_data as dd
import train
import snn_numpy as sn
import snn_int8 as si

PRIOR_WEIGHTS = "/mnt/nas/data/2026-CAU/서울대학교 학부인턴/Project/SpikeSense-Edge/hardware/src/weights"
OUT = os.path.join(HERE, "quant_int8")


def check_prior():
    spec = importlib.util.spec_from_file_location(
        "prior_test_model_numpy", os.path.join(SOFTWARE, "model_develop", "references", "test_model_numpy.py"))
    t = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(t)
    w = PRIOR_WEIGHTS
    b = t.load_uint8_hex(f"{w}/beta.hex", (162,))
    v = t.load_vth(f"{w}/vth.hex", "int8", (162,))
    q = [{"W": t.load_int8_hex(f"{w}/w1.hex", (128, 40)), "beta": b[:128], "vth": v[:128]},
         {"W": t.load_int8_hex(f"{w}/w2.hex", (32, 128)), "beta": b[128:160], "vth": v[128:160]},
         {"W": t.load_int8_hex(f"{w}/w3.hex", (2, 32)), "beta": b[160:], "vth": v[160:]}]
    lines, ok = [], True
    for tag in ("normal", "anomaly"):
        mel = np.load(f"{w}/golden/{tag}_mel.npy").astype(np.int64)
        st = {}
        mem = si.forward(q, mel[None], st)[0]
        g_mem = np.load(f"{w}/golden/{tag}_mem_out.npy")
        g_spk = np.load(f"{w}/golden/{tag}_spk_out.npy")
        r = (np.array_equal(mem, g_mem), np.array_equal(st["spk"][-1][0], g_spk))
        ok &= all(r)
        lines.append(f"{tag:8s} mel{mel.shape} mem={r[0]} spk={r[1]} 포화={st['sat']} 판정={si.predict(mem[None])[0]}")
    lines.append(f"선행 골든 비트 일치: {'PASS' if ok else 'FAIL'}")
    return ok, lines


def softmax_p1(logit):
    z = logit - logit.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e[:, 1] / e.sum(axis=1)


def metrics(logit, y, f, b):
    nf = f.max() + 1
    score = np.bincount(f, softmax_p1(logit), nf) / np.bincount(f, minlength=nf)
    cy = np.bincount(f, y, nf) / np.bincount(f, minlength=nf)
    pred = logit.argmax(1)
    return {"auc": roc_auc_score(cy, score), "pauc": roc_auc_score(cy, score, max_fpr=0.1),
            "f1_bal": f1_score(y[b], pred[b], zero_division=0),
            "acc_bal": float((pred[b] == y[b]).mean())}, pred


def run_unit(machine, mid):
    unit = dd.unit_name(machine, mid)
    pth = os.path.join(SOFTWARE, "model_weights", unit, "last.pth")
    a = torch.load(pth, map_location="cpu", weights_only=False)["args"]
    data = train.prepare(machine, mid, a["method"], a["val_frac"], a["seed"], "cpu", a.get("hop"))
    x = data["test_seg"].numpy()
    y, f, b = data["test_label"], data["test_file"], data["bal_idx"]

    layers = sn.load_params(pth)
    f_mem, f_spk = sn.forward(layers, x)
    q = si.quantize(layers)
    st = {}
    i_mem = si.forward(q, si.quantize_input(x), st)

    fm, f_pred = metrics(f_mem.mean(1), y, f, b)
    im, i_pred = metrics(si.dequant_logit(q, i_mem), y, f, b)
    assert np.array_equal(i_pred, si.predict(i_mem))   # 역양자화가 판정을 바꾸지 않는다

    row = {"unit": unit, "n_seg": len(x), "n_file": int(f.max() + 1)}
    for k in fm:
        row[f"fp_{k}"] = round(fm[k], 6)
        row[f"int8_{k}"] = round(im[k], 6)
        row[f"d_{k}"] = round(im[k] - fm[k], 6)
    row["pred_agree"] = round(float((f_pred == i_pred).mean()), 6)
    for i in range(len(q)):
        L = i + 1
        row[f"spk_mis_L{L}"] = round(float((f_spk[i] != st["spk"][i]).mean()), 6)
        row[f"acc_max_L{L}"] = st["acc"][i]
        row[f"mem_max_L{L}"] = st["mem"][i]
        row[f"sat_L{L}"] = st["sat"][i]
        row[f"vth_min_L{L}"] = int(q[i]["vth"].min())
        row[f"vth_max_L{L}"] = int(q[i]["vth"].max())
        row[f"beta_min_L{L}"] = int(q[i]["beta"].min())
        row[f"beta_max_L{L}"] = int(q[i]["beta"].max())
        row[f"scale_L{L}"] = q[i]["scale"]
    return row


def summarize(rows):
    n = len(rows)
    col = lambda k: np.array([r[k] for r in rows], dtype=np.float64)
    L = [c[len("sat_L"):] for c in rows[0] if c.startswith("sat_L")]
    out = [f"장비 {n}대, test 세그먼트 {int(col('n_seg').sum())}개, 파일 {int(col('n_file').sum())}개"]
    for k in ("auc", "pauc", "f1_bal", "acc_bal"):
        d = col(f"d_{k}")
        out.append(f"{k:8s} FP32 {col(f'fp_{k}').mean():.4f}  INT8 {col(f'int8_{k}').mean():.4f}  "
                   f"변화 평균 {d.mean():+.4f}  최소 {d.min():+.4f}({rows[int(d.argmin())]['unit']})  "
                   f"최대 {d.max():+.4f}({rows[int(d.argmax())]['unit']})")
    a = col("pred_agree")
    out.append(f"판정 일치 평균 {a.mean():.4f}  최저 {a.min():.4f}({rows[int(a.argmin())]['unit']})  "
               f"전체 {(a * col('n_seg')).sum() / col('n_seg').sum():.4f}")
    out.append(f"AUC 0.9 이상 INT8 {int((col('int8_auc') >= 0.9).sum())}대 / FP32 {int((col('fp_auc') >= 0.9).sum())}대, "
               f"INT8 최저 {col('int8_auc').min():.4f}({rows[int(col('int8_auc').argmin())]['unit']})")
    for l in L:
        out.append(f"L{l}: 스파이크 불일치 평균 {col(f'spk_mis_L{l}').mean():.4f}  누산 |최대| {int(col(f'acc_max_L{l}').max())}  "
                   f"막전위 |최대| {int(col(f'mem_max_L{l}').max())} ({col(f'mem_max_L{l}').max() / 32767 * 100:.1f}% of INT16)  "
                   f"포화 {int(col(f'sat_L{l}').sum())}회  vth_q {int(col(f'vth_min_L{l}').min())}~{int(col(f'vth_max_L{l}').max())}  "
                   f"beta_q {int(col(f'beta_min_L{l}').min())}~{int(col(f'beta_max_L{l}').max())}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--units", nargs="*", default=None, help="예: fan_id01 pump_id00 (기본: 40대)")
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    ok, lines = check_prior()
    print("\n".join(lines))
    with open(os.path.join(OUT, "prior.txt"), "w") as fp:
        fp.write("\n".join(lines) + "\n")
    if not ok:
        sys.exit("선행 골든과 정수 규칙이 다르다. 40대 비교를 중단한다.")

    units = [(m, i) for m, i in dd.UNITS if not args.units or dd.unit_name(m, i) in args.units]
    rows = []
    for m, i in units:
        r = run_unit(m, i)
        rows.append(r)
        print(f"{r['unit']:17s} seg={r['n_seg']:5d} AUC FP {r['fp_auc']:.4f} INT8 {r['int8_auc']:.4f} "
              f"({r['d_auc']:+.4f}) 일치 {r['pred_agree']:.4f} "
              f"mem_max {r['mem_max_L1']}/{r['mem_max_L2']}/{r['mem_max_L3']}/{r['mem_max_L4']} "
              f"sat {r['sat_L1']}/{r['sat_L2']}/{r['sat_L3']}/{r['sat_L4']}", flush=True)

    sub = "" if not args.units else "_subset"
    with open(os.path.join(OUT, f"results{sub}.csv"), "w", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    s = summarize(rows)
    print("\n".join(s))
    with open(os.path.join(OUT, f"summary{sub}.txt"), "w") as fp:
        fp.write("\n".join(s) + "\n")
    print(f"저장: {OUT}/")


if __name__ == "__main__":
    main()
