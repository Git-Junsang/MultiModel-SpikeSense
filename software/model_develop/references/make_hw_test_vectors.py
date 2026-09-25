"""하드웨어 통합 테스트용 Mel 벡터 생성.

HW의 이상 판정(anomaly_judge_mult)은 L3 스파이크 Leaky Counter(cnt_a > cnt_n)로
LED를 켠다. 이는 SW 분류(막전위 평균 argmax)와 규칙이 달라서, 합성 골든 벡터는
anomaly 스파이크가 normal보다 적어 LED를 켜지 못한다.

따라서 RPi->FPGA SPI 링크를 LED로 검증하려면 cnt_a > cnt_n 를 확실히 만드는
입력이 필요하다. 이 스크립트는 MIMII에서:
  - 이상: (cnt_a - cnt_n) 최대 세그먼트  → LED ON 보장
  - 정상: (cnt_a - cnt_n) 최소 세그먼트  → LED OFF 보장
를 골라 hardware/src/weights/golden/hw_{anomaly,normal}_mel.npy ([31,40] int8) 로 저장.

사용:  cd software && python3 make_hw_test_vectors.py
"""
import os, sys, glob
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "rpi"))
from train import extract_mel_spectrogram, segment_features
from snn_infer import SnnInfer

DATA = "data_mimii"
OUT  = "../hardware/src/weights/golden"
SCAN_PER_CLASS = 60   # 클래스당 스캔할 wav 수


def main():
    inf = SnnInfer("../hardware/src/weights")

    def spike_counts(seg):
        q = np.clip(np.rint(seg * 127), 0, 127).astype(np.int8)
        _, spk = inf.forward(q)
        return int(spk[:, 0].sum()), int(spk[:, 1].sum())   # (cnt_n, cnt_a)

    best_a = None   # (delta, n, a, seg, file)  delta=a-n  최대
    best_n = None   # delta 최소
    for sub, lbl in [("abnormal", 1), ("normal", 0)]:
        for f in sorted(glob.glob(os.path.join(DATA, sub, "*.wav")))[:SCAN_PER_CLASS]:
            for seg in segment_features(extract_mel_spectrogram(f), 31):
                n, a = spike_counts(seg)
                d = a - n
                if lbl == 1 and (best_a is None or d > best_a[0]):
                    best_a = (d, n, a, seg.copy(), os.path.basename(f))
                if lbl == 0 and (best_n is None or d < best_n[0]):
                    best_n = (d, n, a, seg.copy(), os.path.basename(f))

    os.makedirs(OUT, exist_ok=True)
    for tag, best in [("anomaly", best_a), ("normal", best_n)]:
        d, n, a, seg, fname = best
        vec = np.clip(np.rint(seg * 127), 0, 127).astype(np.int8)
        np.save(os.path.join(OUT, f"hw_{tag}_mel.npy"), vec)
        led = "ON" if a > n else "OFF"
        print(f"  hw_{tag}_mel.npy ← {fname}  cnt_n={n} cnt_a={a} → LED {led}")
    print(f"\n저장 위치: {os.path.abspath(OUT)}")
    print("  (anomaly=cnt_a>cnt_n→LED ON, normal=cnt_n≥cnt_a→LED OFF)")


if __name__ == "__main__":
    main()
