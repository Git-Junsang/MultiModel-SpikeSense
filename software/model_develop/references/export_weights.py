"""가중치·파라미터 추출 스크립트.

학습된 .pth(예: best_model_mimii_v2-1.pth)를 INT8로 양자화해 $readmemh 호환 hex로 저장한다.

양자화 방식:
  가중치 W1/W2/W3 : 레이어별 대칭 INT8
      scale_W = max(|W|) / 127
      W_q = clip(round(W / scale_W), -128, 127)

  β : Q0.8 unsigned 8-bit  (src_old lif_core.v 와 동일)
      beta_q = clip(round(sigmoid(w_beta) × 256), 0, 255)
      HW 복원: decayed = (beta_q × mem) >> 8

  V_th : 레이어별 INT8 (W 단위계와 통일)
      vth_q = round(V_th / scale_W)
      → 학습값 범위가 INT8을 벗어나면 INT16으로 자동 전환 (경고 출력)

  Layer 1 MAC 시프트 (L1_SHIFT=7):
      mel_int8 = round(mel_float × 127)  [RPi5 전송, 범위 [0,127]]
      MAC = sum(mel × W1) >> 7
      → L2/L3 (binary spike × W) 와 동일 단위계가 됨

출력 (hardware/src/weights/):
  w1.hex     5120개  INT8  2-char
  w2.hex     4096개  INT8  2-char
  w3.hex       64개  INT8  2-char
  beta.hex    162개  uint8 Q0.8  2-char
  vth.hex     162개  INT8(2-char) 또는 INT16(4-char)
  scales.json 역양자화 스케일 및 메타정보
"""
import sys, os, json, argparse
import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from snn_model import AnomalySNN

MODEL_PATH = "best_model_mimii_v2-1.pth"
OUT_DIR    = "../hardware/src/weights"
L1_SHIFT   = 7


def quant_weights(W, name):
    scale = float(np.max(np.abs(W))) / 127.0
    W_q = np.clip(np.round(W / scale), -128, 127).astype(np.int8)
    err = np.abs(W - W_q.astype(np.float32) * scale)
    print(f"  {name}: max={np.max(np.abs(W)):.4f}  scale={scale:.6f}"
          f"  err_max={err.max():.4e}")
    return W_q, scale


def quant_beta(beta_f, name):
    beta_q = np.clip(np.round(beta_f * 256), 0, 255).astype(np.uint8)
    print(f"  {name}: float=[{beta_f.min():.4f},{beta_f.max():.4f}]"
          f"  uint8=[{beta_q.min()},{beta_q.max()}]")
    return beta_q


def quant_vth(vth_f, scale_W, name):
    raw = np.round(vth_f / scale_W)
    if raw.max() > 127 or raw.min() < 0:
        print(f"  ⚠  {name}: vth_q 범위 [{raw.min():.0f},{raw.max():.0f}]"
              f" → INT16 사용")
        return np.clip(raw, -32768, 32767).astype(np.int16), "int16"
    vth_q = raw.astype(np.int8)
    print(f"  {name}: float=[{vth_f.min():.4f},{vth_f.max():.4f}]"
          f"  int8=[{vth_q.min()},{vth_q.max()}]")
    return vth_q, "int8"


def save_hex(arr, path, bits):
    """배열을 $readmemh 형식 hex 파일로 저장 (한 줄에 값 하나)."""
    if bits == 8:
        lines = [f"{v:02x}" for v in arr.astype(np.uint8)]
    else:
        lines = [f"{v:04x}" for v in arr.astype(np.uint16)]
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"  → {path}  ({len(lines)}개, {bits}-bit)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=MODEL_PATH)
    ap.add_argument("--out",   default=OUT_DIR)
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)

    # 모델 로드
    print(f"\n[1] 모델 로드: {args.model}")
    ckpt  = torch.load(args.model, map_location="cpu", weights_only=False)
    state = ckpt.get("model_state_dict", ckpt)
    model = AnomalySNN()
    model.load_state_dict(state)
    model.eval()
    print("  ✓ 로드 완료")

    with torch.no_grad():
        W1 = model.fc1.weight.numpy()   # [128, 40]
        W2 = model.fc2.weight.numpy()   # [32, 128]
        W3 = model.fc3.weight.numpy()   # [2,   32]
        bL1 = torch.sigmoid(model.hidden1_lif.w_beta).numpy()      # [128]
        bL2 = torch.sigmoid(model.hidden2_lif.w_beta).numpy()      # [32]
        bL3 = torch.sigmoid(model.output_lif.w_beta).numpy()       # [2]
        vL1 = torch.clamp(model.hidden1_lif.w_thr, 0.1).numpy()   # [128]
        vL2 = torch.clamp(model.hidden2_lif.w_thr, 0.1).numpy()   # [32]
        vL3 = torch.clamp(model.output_lif.w_thr, 0.1).numpy()    # [2]

    # 양자화
    print("\n[2] 가중치 양자화 (INT8, 레이어별)")
    W1_q, sc1 = quant_weights(W1, "W1")
    W2_q, sc2 = quant_weights(W2, "W2")
    W3_q, sc3 = quant_weights(W3, "W3")

    print("\n[3] β 양자화 (Q0.8 uint8)")
    bL1_q = quant_beta(bL1, "L1-β")
    bL2_q = quant_beta(bL2, "L2-β")
    bL3_q = quant_beta(bL3, "L3-β")

    print(f"\n[4] V_th 양자화 (L1_SHIFT={L1_SHIFT})")
    vL1_q, fmt1 = quant_vth(vL1, sc1, "L1-Vth")
    vL2_q, fmt2 = quant_vth(vL2, sc2, "L2-Vth")
    vL3_q, fmt3 = quant_vth(vL3, sc3, "L3-Vth")
    vth_fmt = "int16" if any(f == "int16" for f in [fmt1, fmt2, fmt3]) else "int8"
    vth_all = np.concatenate([vL1_q.astype(np.int16 if vth_fmt == "int16" else np.int8),
                               vL2_q.astype(np.int16 if vth_fmt == "int16" else np.int8),
                               vL3_q.astype(np.int16 if vth_fmt == "int16" else np.int8)])

    # hex 저장
    print("\n[5] hex 파일 저장")
    # W: 행 우선 flatten (PyTorch Linear weight [out,in] → RTL neuron-major 순서)
    save_hex(W1_q.flatten(), os.path.join(args.out, "w1.hex"), 8)
    save_hex(W2_q.flatten(), os.path.join(args.out, "w2.hex"), 8)
    save_hex(W3_q.flatten(), os.path.join(args.out, "w3.hex"), 8)
    save_hex(np.concatenate([bL1_q, bL2_q, bL3_q]),
             os.path.join(args.out, "beta.hex"), 8)
    save_hex(vth_all, os.path.join(args.out, "vth.hex"),
             16 if vth_fmt == "int16" else 8)

    # scales.json
    scales = {
        "l1_shift": L1_SHIFT,
        "mel_quantization": "mel_int8 = round(mel_float * 127), range [0,127]",
        "weight_scales": {"W1": sc1, "W2": sc2, "W3": sc3},
        "beta_format": "Q0.8 uint8. float_beta = beta_q / 256. HW: (beta_q*mem)>>8",
        "vth_format": vth_fmt,
        "vth_formula": "vth_q = round(vth_float / scale_W). HW cmp: mem_q >= vth_q",
        "vth_scales": {"L1": sc1, "L2": sc2, "L3": sc3},
        "float_ranges": {
            "W1":     [float(W1.min()),  float(W1.max())],
            "W2":     [float(W2.min()),  float(W2.max())],
            "W3":     [float(W3.min()),  float(W3.max())],
            "beta_L1":[float(bL1.min()), float(bL1.max())],
            "beta_L2":[float(bL2.min()), float(bL2.max())],
            "beta_L3":[float(bL3.min()), float(bL3.max())],
            "vth_L1": [float(vL1.min()), float(vL1.max())],
            "vth_L2": [float(vL2.min()), float(vL2.max())],
            "vth_L3": [float(vL3.min()), float(vL3.max())]
        }
    }
    jpath = os.path.join(args.out, "scales.json")
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(scales, f, indent=2, ensure_ascii=False)
    print(f"  → {jpath}")

    total_w = W1_q.size + W2_q.size + W3_q.size
    print(f"\n✅ Phase 1 완료")
    print(f"   가중치 {total_w}개  (W1:{W1_q.size}  W2:{W2_q.size}  W3:{W3_q.size})")
    print(f"   파라미터 β:{len(bL1_q)+len(bL2_q)+len(bL3_q)}개  "
          f"Vth:{len(vth_all)}개 ({vth_fmt})")
    print(f"   출력 디렉토리: {os.path.abspath(args.out)}")


if __name__ == "__main__":
    main()
