"""float32(PyTorch) vs INT8(양자화) 정확도 비교.

같은 데이터셋(data_mimii)으로 두 모델을 돌려 양자화 오차에 따른 정확도 변화를 측정한다.

  float : best_model_mimii_v2-1.pth (PyTorch, float32 가중치, mel_float[0,1] 입력)
  int8  : rpi/snn_infer (INT8 가중치, mel_int8=round(mel*127) 입력, 정수 연산=RTL)

분류 기준은 둘 다 동일: 막전위 평균(mem_mean)의 argmax → 0=정상, 1=이상.
정답: data_mimii/normal=0, data_mimii/abnormal=1.
"""
import os, sys, glob, argparse
import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "rpi"))
from snn_model import AnomalySNN
from train import extract_mel_spectrogram, segment_features
from snn_infer import SnnInfer

SEG = 31


def load_segments(data_dir, limit=None):
    """wav → (segments[N,31,40] float, labels[N]). limit=클래스당 최대 파일 수."""
    X, y = [], []
    for label, sub in [(0, "normal"), (1, "abnormal")]:
        files = sorted(glob.glob(os.path.join(data_dir, sub, "*.wav")))
        if limit:
            files = files[:limit]
        for f in files:
            mel = extract_mel_spectrogram(f)          # [T,40] float[0,1] (학습과 동일)
            for seg in segment_features(mel, SEG):
                X.append(seg); y.append(label)
    return np.array(X, np.float32), np.array(y, np.int64)


def float_predict(model, X):
    """PyTorch float 추론 → 라벨 [N]."""
    preds = []
    with torch.no_grad():
        for i in range(0, len(X), 256):
            xb = torch.from_numpy(X[i:i+256])         # [b,31,40]
            _, mem, _ = model(xb)                      # mem [b,31,2]
            preds.append(mem.mean(dim=1).argmax(dim=1).numpy())
    return np.concatenate(preds)


def int8_predict(infer, X):
    """INT8 양자화 추론 (입력도 round(mel*127)) → 라벨 [N]."""
    preds = []
    for seg in X:
        mel_int8 = np.clip(np.rint(seg * 127.0), 0, 127).astype(np.int8)
        label, _ = infer.predict(mel_int8)
        preds.append(label)
    return np.array(preds)


def report(name, y, pred):
    acc = (pred == y).mean()
    tp = int(((pred == 1) & (y == 1)).sum()); fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum()); tn = int(((pred == 0) & (y == 0)).sum())
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec  = tp / (tp + fn) if tp + fn else 0.0
    f1   = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    print(f"  [{name:5s}] acc={acc*100:5.2f}%  P={prec*100:5.2f}%  "
          f"R={rec*100:5.2f}%  F1={f1*100:5.2f}%  (TP{tp} FP{fp} FN{fn} TN{tn})")
    return acc, f1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data_mimii")
    ap.add_argument("--model", default="best_model_mimii_v2-1.pth")
    ap.add_argument("--weights-dir", default="../hardware/src/weights",
                    help="해당 모델에서 추출한 INT8 hex 경로")
    ap.add_argument("--limit", type=int, default=None, help="클래스당 최대 wav 수")
    args = ap.parse_args()

    print(f"데이터 로드 + Mel 추출 ... ({args.data}, limit={args.limit})")
    X, y = load_segments(args.data, args.limit)
    print(f"  세그먼트 {len(X)}개  (정상 {int((y==0).sum())} / 이상 {int((y==1).sum())})")

    print(f"\nfloat32 모델 로드 ... ({args.model})")
    ckpt = torch.load(args.model, map_location="cpu", weights_only=False)
    model = AnomalySNN(); model.load_state_dict(ckpt.get("model_state_dict", ckpt)); model.eval()

    pred_f = float_predict(model, X)
    pred_q = int8_predict(SnnInfer(args.weights_dir), X)

    print("\n결과:")
    acc_f, f1_f = report("float", y, pred_f)
    acc_q, f1_q = report("int8",  y, pred_q)

    agree = (pred_f == pred_q).mean()
    print(f"\n  float vs int8 예측 일치율: {agree*100:.2f}%")
    print(f"  정확도 변화: {(acc_q-acc_f)*100:+.2f}%p   F1 변화: {(f1_q-f1_f)*100:+.2f}%p")


if __name__ == "__main__":
    main()
