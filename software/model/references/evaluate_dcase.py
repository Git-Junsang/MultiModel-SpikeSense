"""SNN 평가 데이터 추출 (1단계: 원시 점수 -> CSV).

학습된 체크포인트(best_model_dcase_*.pth)를 로드해 held-out 테스트셋을 추론하고,
세그먼트별 원시 점수를 CSV로 저장한다. ROC/F1 곡선(2단계)은 이 CSV를 입력으로
plot_metrics.py에서 그린다.

분류 점수 정의 (snn_model / train.py와 동일 흐름):
  - 모델 출력 mem_record[:, :, 2] → 시간평균 mem_mean[:, 2]
  - score_anomaly = softmax(mem_mean)[:, 1]   # P(이상), ROC/AUC용 연속 점수
  - pred_label    = argmax(mem_mean)          # 0=정상, 1=이상

사용 예:
  python3 evaluate_dcase.py --data_dir data_dcase \
      --model best_model_dcase_v2-1.pth --out eval_dcase.csv
  # split 메타가 없는 구버전 체크포인트면 --seed 로 동일 분할 재현(--split all 가능)
"""

import os
import csv
import argparse
import numpy as np
import torch
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score, confusion_matrix

from snn_model import AnomalySNN
from train import load_mimii_data


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--data_dir", type=str, default="data_dcase")
    p.add_argument("--model", type=str, default="best_model_dcase_v2-1.pth")
    p.add_argument("--out", type=str, default="eval_dcase.csv")
    p.add_argument("--split", type=str, default="test",
                   choices=["test", "train", "all"],
                   help="평가 대상 분할 (기본: held-out test)")
    p.add_argument("--seed", type=int, default=42,
                   help="체크포인트에 split 메타가 없을 때 분할 재현용 seed")
    p.add_argument("--batch_size", type=int, default=256)
    p.add_argument("--n_mels", type=int, default=40)
    p.add_argument("--segment_ms", type=int, default=992)
    return p.parse_args()


def resolve_indices(ckpt, n_total, split, seed, segment_frames, n_mels):
    """평가에 사용할 세그먼트 인덱스를 결정한다.

    우선순위: 체크포인트 저장 test_indices > seed 기반 재현 분할.
    """
    saved = ckpt.get("test_indices") if isinstance(ckpt, dict) else None

    if saved is not None and len(saved) > 0:
        saved = np.asarray(saved)
        # 메타 정합성 경고 (전처리 파라미터가 다르면 인덱스가 어긋남)
        if ckpt.get("segment_frames") not in (None, segment_frames):
            print(f"  ⚠️  segment_frames 불일치: ckpt={ckpt.get('segment_frames')} vs 현재={segment_frames}")
        if ckpt.get("n_mels") not in (None, n_mels):
            print(f"  ⚠️  n_mels 불일치: ckpt={ckpt.get('n_mels')} vs 현재={n_mels}")
        test_idx = saved
        src = "checkpoint.test_indices"
    else:
        s = ckpt.get("split_seed", seed) if isinstance(ckpt, dict) else seed
        print(f"  ℹ️  저장된 test_indices 없음 → seed={s} 로 80/20 분할 재현")
        rng = np.random.RandomState(s)
        perm = rng.permutation(n_total)
        # 주의: 구버전 train.py는 np.random.seed 전역을 썼다. 동일 모델의
        # 정확한 held-out 재현은 보장되지 않으므로 메트릭은 참고용.
        n_train = int(n_total * 0.8)
        test_idx = perm[n_train:]
        src = f"seed={s} 재현 분할"

    all_idx = np.arange(n_total)
    if split == "test":
        sel = test_idx
    elif split == "train":
        sel = np.setdiff1d(all_idx, test_idx, assume_unique=False)
    else:  # all
        sel = all_idx
    return np.asarray(sel), src


@torch.no_grad()
def run_inference(model, segments, batch_size, device):
    """세그먼트 배치 추론 → (mem_normal, mem_anomaly, score_anomaly, pred)."""
    model.eval()
    mems, scores, preds = [], [], []
    for start in range(0, len(segments), batch_size):
        x = torch.tensor(segments[start:start + batch_size], dtype=torch.float32, device=device)
        _, mem_record, _ = model(x)          # [B, T, 2]
        mem_mean = mem_record.mean(dim=1)    # [B, 2]
        prob = torch.softmax(mem_mean, dim=1)
        mems.append(mem_mean.cpu().numpy())
        scores.append(prob[:, 1].cpu().numpy())
        preds.append(mem_mean.argmax(dim=1).cpu().numpy())
    return (np.concatenate(mems), np.concatenate(scores), np.concatenate(preds))


def main():
    args = parse_args()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    segment_frames = int(args.segment_ms / ((512 / 16000) * 1000))

    # 1) 데이터 로드 (train.py와 동일 캐시/순서)
    segments, labels = load_mimii_data(args.data_dir, n_mels=args.n_mels, segment_frames=segment_frames)
    labels = np.asarray(labels).astype(int)
    print(f"  전체 세그먼트: {len(segments)} (정상 {int((labels==0).sum())} / 이상 {int((labels==1).sum())})")

    # 2) 체크포인트 로드
    ckpt = torch.load(args.model, map_location=device)
    model = AnomalySNN(n_input=args.n_mels).to(device)
    state = ckpt["model_state_dict"] if (isinstance(ckpt, dict) and "model_state_dict" in ckpt) else ckpt
    model.load_state_dict(state)

    # 3) 평가 대상 인덱스 결정
    sel, src = resolve_indices(ckpt, len(segments), args.split, args.seed, segment_frames, args.n_mels)
    sel_segments = segments[sel]
    sel_labels = labels[sel]
    print(f"  평가 분할: {args.split} | 세그먼트 {len(sel)}개 | 인덱스 출처: {src}")

    # 4) 추론
    mem_mean, score_anomaly, pred = run_inference(model, sel_segments, args.batch_size, device)

    # 5) CSV 저장 (per-segment 원시 데이터)
    with open(args.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["seg_index", "true_label", "pred_label",
                    "mem_normal", "mem_anomaly", "score_anomaly", "correct"])
        for i in range(len(sel)):
            w.writerow([int(sel[i]), int(sel_labels[i]), int(pred[i]),
                        f"{mem_mean[i,0]:.6f}", f"{mem_mean[i,1]:.6f}",
                        f"{score_anomaly[i]:.6f}", int(pred[i] == sel_labels[i])])
    print(f"  💾 CSV 저장: {args.out} ({len(sel)} rows)")

    # 6) 요약 메트릭 (검증용)
    acc = accuracy_score(sel_labels, pred)
    f1 = f1_score(sel_labels, pred, average="binary", zero_division=0)
    cm = confusion_matrix(sel_labels, pred)
    auc = roc_auc_score(sel_labels, score_anomaly) if len(np.unique(sel_labels)) == 2 else float("nan")
    print("=" * 50)
    print(f"  Accuracy : {acc:.4f}")
    print(f"  F1 (이상): {f1:.4f}")
    print(f"  ROC-AUC  : {auc:.4f}")
    print(f"  Confusion Matrix [[TN FP][FN TP]]:\n{cm}")
    print("=" * 50)


if __name__ == "__main__":
    main()
