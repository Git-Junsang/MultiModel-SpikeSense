"""논문 그림의 원자료를 모은다(GPU 필요).

평가 분할은 train_1unit.prepare와 동일하다(학습에 쓴 이상 파일 절반 제외). 따라서 여기서
계산한 AUC는 train_result/L_normal_noaug/results.csv의 test_auc와 같아야 한다.

학습된 40대 모델로 test segment를 추론해
  1) 파일 단위 이상 점수·정답  → train_result/eval/scores/scores.npz
  2) layer별 membrane potential 최대치(hardware 정수 단위) → train_result/eval/scores/membrane_headroom.csv
를 저장한다. 그림 생성(analysis/develop)은 GPU 없이 이 파일들만 읽는다.

사용: python3 scores.py
"""

import os
import sys
import csv
import numpy as np
import torch

SW = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(SW, "model"))
sys.path.insert(0, os.path.join(SW, "train"))
sys.path.insert(0, os.path.join(SW, "dataset"))
import dcase_data as dd
import snn_torch as sm
import train_1unit as tr

OUT = os.path.join(SW, "train_result", "eval", "scores")
DEV = "cuda" if torch.cuda.is_available() else "cpu"


@torch.no_grad()
def run_unit(unit):
    machine, mid = unit.rsplit("_id", 1)
    ck = torch.load(os.path.join(SW, "weights", "L_normal_noaug", unit, "last.pth"), map_location=DEV)
    model = sm.AnomalySNN().to(DEV)
    model.load_state_dict(ck["model_state_dict"])
    model.eval()

    # 보고된 결과와 같은 평가 분할을 쓴다(학습에 쓴 이상 파일 절반은 제외)
    d = tr.prepare(machine, mid, "supervised", 0.1, 42, DEV)
    x = d["test_seg"]
    y, f = d["test_label"].astype(int), d["test_file"].astype(int)

    # weight 스케일(선행 export_weights.py): membrane potential 정수 단위 = V_float / scale_W
    scale = [float(fc.weight.abs().max()) / 127.0 for fc in model.fcs]

    prob, vmax = [], [0.0] * len(model.lifs)
    for s in range(0, len(x), 1024):
        b = x[s:s + 1024]
        mem = [l.init_membrane(len(b), DEV) for l in model.lifs]
        out_mem = []
        for t in range(b.shape[1]):
            v = b[:, t, :]
            for k, (fc, lif) in enumerate(zip(model.fcs, model.lifs)):
                v, mem[k] = lif(fc(v), mem[k])
                vmax[k] = max(vmax[k], float(mem[k].abs().max()))
            out_mem.append(mem[-1])
        lg = torch.stack(out_mem, 1).mean(1)
        prob.append(torch.softmax(lg, 1)[:, 1].cpu().numpy())
    prob = np.concatenate(prob)

    nf = f.max() + 1
    clip_score = np.bincount(f, prob, nf) / np.bincount(f, minlength=nf)
    clip_y = (np.bincount(f, y, nf) / np.bincount(f, minlength=nf)).astype(int)
    head = [vmax[k] / scale[k] for k in range(len(scale))]
    return clip_score, clip_y, head


def main():
    os.makedirs(OUT, exist_ok=True)
    units = [dd.unit_name(m, i) for m, i in dd.UNITS]
    scores, labels, rows = {}, {}, []
    for n, u in enumerate(units, 1):
        s, y, head = run_unit(u)
        scores[u], labels[u] = s, y
        rows.append({"unit": u, **{f"L{k+1}": round(v) for k, v in enumerate(head)}})
        print(f"[{n}/{len(units)}] {u:18s} 파일 {len(s):4d} (이상 {y.sum():4d}) "
              f"| membrane potential 정수 최대 {[round(v) for v in head]}", flush=True)

    np.savez(os.path.join(OUT, "scores.npz"),
             **{f"score__{u}": v for u, v in scores.items()},
             **{f"label__{u}": v for u, v in labels.items()})
    with open(os.path.join(OUT, "membrane_headroom.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"\n저장 → {OUT}/scores.npz, membrane_headroom.csv")


if __name__ == "__main__":
    main()
