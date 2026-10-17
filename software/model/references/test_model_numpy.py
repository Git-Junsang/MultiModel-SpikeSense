"""SNN 동작 검증 — NumPy INT8 시뮬레이터.

export_weights.py로 만든 INT8 가중치를 로드해 RTL과 동일한 정수 연산으로
40->128->32->2 순전파를 수행한다. PyTorch 불필요, export_weights.py 실행이 선행되어야 한다.

사용법:
  python test_model_numpy.py              # 기본 동작 확인
  python test_model_numpy.py --golden     # 골든 벡터 생성 (RTL 테스트벤치용)
  python test_model_numpy.py --l1_shift 7 # Layer1 MAC 시프트 조정

정수 연산 스펙 (RTL 과 동일):
  L1 MAC : sum(mel_int8 × W1_int8) >> l1_shift  [INT32→INT16]
  L2 MAC : sum(spk_L1   × W2_int8)              [INT16]
  L3 MAC : sum(spk_L2   × W3_int8)              [INT16]
  PLIF   : decayed = (beta_q × mem) >> 8
           mem_new = decayed + current
           spike   = (mem_new >= vth_q)
           mem_out = mem_new - spike × vth_q    [Soft Reset]
  막전위  : INT16 (±32767 에서 포화)
"""
import numpy as np
import os, json, argparse

WEIGHTS_DIR = "../hardware/src/weights"


# 파일 로드

def _load_hex(path, dtype_uint, dtype_out, shape):
    with open(path) as f:
        vals = [int(v, 16) for v in f.read().split() if v]
    return np.array(vals, dtype=dtype_uint).astype(dtype_out).reshape(shape)

def load_int8_hex(path, shape):
    return _load_hex(path, np.uint8, np.int8, shape)

def load_uint8_hex(path, shape):
    return _load_hex(path, np.uint8, np.uint8, shape)

def load_int16_hex(path, shape):
    return _load_hex(path, np.uint16, np.int16, shape)

def load_vth(path, fmt, shape):
    if fmt == "int16":
        return load_int16_hex(path, shape)
    return load_int8_hex(path, shape)


# PLIF-T 뉴런 — RTL 정수 연산

def plif_step(current, membrane, beta_q, vth_q):
    """한 타임스텝 PLIF-T (RTL 정수 연산과 1:1 대응)."""
    decayed = (beta_q.astype(np.int32) * membrane.astype(np.int32)) >> 8
    mem_new = decayed + current.astype(np.int32)
    spikes  = (mem_new >= vth_q.astype(np.int32)).astype(np.int8)
    mem_out = mem_new - spikes.astype(np.int32) * vth_q.astype(np.int32)
    return spikes, np.clip(mem_out, -32768, 32767).astype(np.int16)


# 전체 순전파

def snn_forward(mel_int8, W1, W2, W3,
                beta_L1, beta_L2, beta_L3,
                vth_L1, vth_L2, vth_L3, l1_shift=7):
    """
    Args:
      mel_int8 [T, 40] int8  — RPi5 전송값, round(mel_float × 127), [0,127]
      W*   [out, in]   int8  — PyTorch weight 행렬 (행: 출력 뉴런)
      beta_* [N]      uint8  — Q0.8 감쇠율
      vth_*  [N]  int8/int16 — 발화 임계값
    Returns:
      spk_L3 [T,2], mem_L3 [T,2], spk_L1 [T,128], spk_L2 [T,32]
    """
    T = mel_int8.shape[0]
    mem_L1 = np.zeros(128, np.int16)
    mem_L2 = np.zeros(32,  np.int16)
    mem_L3 = np.zeros(2,   np.int16)

    spk_L1_r = np.zeros((T, 128), np.int8)
    spk_L2_r = np.zeros((T, 32),  np.int8)
    spk_L3_r = np.zeros((T, 2),   np.int8)
    mem_L3_r = np.zeros((T, 2),   np.int16)

    for t in range(T):
        # Layer 1: INT8 mel × INT8 W1 → INT32 → >> l1_shift → INT16
        mac1 = (mel_int8[t].astype(np.int32) @ W1.T.astype(np.int32)) >> l1_shift
        spk_L1, mem_L1 = plif_step(mac1.astype(np.int16), mem_L1, beta_L1, vth_L1)

        # Layer 2: binary spike × INT8 W2 → INT16
        mac2 = spk_L1.astype(np.int16) @ W2.T.astype(np.int16)
        spk_L2, mem_L2 = plif_step(mac2, mem_L2, beta_L2, vth_L2)

        # Layer 3: binary spike × INT8 W3 → INT16
        mac3 = spk_L2.astype(np.int16) @ W3.T.astype(np.int16)
        spk_L3, mem_L3 = plif_step(mac3, mem_L3, beta_L3, vth_L3)

        spk_L1_r[t] = spk_L1
        spk_L2_r[t] = spk_L2
        spk_L3_r[t] = spk_L3
        mem_L3_r[t] = mem_L3

    return spk_L3_r, mem_L3_r, spk_L1_r, spk_L2_r


def classify(mem_L3_r):
    """막전위 평균의 argmax → 0=정상, 1=이상 (snn_model.py 와 동일)"""
    mem_mean = mem_L3_r.mean(axis=0)
    return int(np.argmax(mem_mean)), mem_mean


# 골든 벡터 저장

def save_golden(tag, mel, spk_L3, mem_L3, out_dir):
    """RTL 테스트벤치용 골든 벡터 저장 (.npy + $readmemh hex)."""
    os.makedirs(out_dir, exist_ok=True)
    np.save(os.path.join(out_dir, f"{tag}_mel.npy"),     mel)
    np.save(os.path.join(out_dir, f"{tag}_spk_out.npy"), spk_L3)
    np.save(os.path.join(out_dir, f"{tag}_mem_out.npy"), mem_L3)
    # $readmemh 형식 (iverilog testbench 직접 로드용)
    np.savetxt(os.path.join(out_dir, f"{tag}_mel.hex"),
               mel.flatten().astype(np.uint8), fmt="%02x")
    np.savetxt(os.path.join(out_dir, f"{tag}_mem_out.hex"),
               mem_L3.flatten().astype(np.uint16), fmt="%04x")
    print(f"    저장: {out_dir}/{tag}_*.npy/.hex")


# 메인

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights_dir", default=WEIGHTS_DIR)
    ap.add_argument("--golden",      action="store_true", help="골든 벡터 생성")
    ap.add_argument("--l1_shift",    type=int, default=7, help="Layer1 MAC >>N")
    args = ap.parse_args()

    wdir = args.weights_dir
    print("=" * 55)
    print("SNN 순전파 검증 — INT8 NumPy 시뮬레이터")
    print("아키텍처: 40 → 128 → 32 → 2  (PLIF-T)")
    print("=" * 55)

    w1_path = os.path.join(wdir, "w1.hex")
    if not os.path.exists(w1_path):
        print(f"\n오류: 가중치 파일 없음 ({wdir})")
        print("      먼저 export_weights.py 를 실행하세요.")
        return

    # 가중치 로드
    print(f"\n[가중치 로드] {wdir}")
    W1 = load_int8_hex(os.path.join(wdir, "w1.hex"),   (128, 40))
    W2 = load_int8_hex(os.path.join(wdir, "w2.hex"),   (32, 128))
    W3 = load_int8_hex(os.path.join(wdir, "w3.hex"),   (2,   32))

    beta = load_uint8_hex(os.path.join(wdir, "beta.hex"), (162,))
    beta_L1, beta_L2, beta_L3 = beta[:128], beta[128:160], beta[160:]

    with open(os.path.join(wdir, "scales.json")) as f:
        scales = json.load(f)
    vth_fmt = scales.get("vth_format", "int8")
    vth = load_vth(os.path.join(wdir, "vth.hex"), vth_fmt, (162,))
    vth_L1, vth_L2, vth_L3 = vth[:128], vth[128:160], vth[160:]

    print(f"  W1:{W1.shape}  W2:{W2.shape}  W3:{W3.shape}")
    print(f"  β   L1:[{beta_L1.min()}~{beta_L1.max()}]  "
          f"L2:[{beta_L2.min()}~{beta_L2.max()}]  L3:[{beta_L3.min()}~{beta_L3.max()}]")
    print(f"  Vth({vth_fmt}) L1:[{vth_L1.min()}~{vth_L1.max()}]  "
          f"L2:[{vth_L2.min()}~{vth_L2.max()}]  L3:[{vth_L3.min()}~{vth_L3.max()}]")

    # 테스트 입력 생성
    np.random.seed(42)
    T = 31  # 31 타임스텝 (31 × 32ms = 992ms)

    # 정상: 저에너지 (mel [0,1] 정규화 기준 → 낮은 값 편향)
    mel_normal  = np.clip(
        np.random.beta(2, 8, (T, 40)) * 127, 0, 127
    ).astype(np.int8)
    # 이상: 고에너지 (높은 값 편향 + 넓은 분산)
    mel_anomaly = np.clip(
        np.random.beta(5, 2, (T, 40)) * 127, 0, 127
    ).astype(np.int8)

    # 순전파 실행
    for tag, mel_int8 in [("normal", mel_normal), ("anomaly", mel_anomaly)]:
        label = "정상" if tag == "normal" else "이상"
        print(f"\n── {label} 입력  (T={T}, l1_shift={args.l1_shift}) ──")
        print(f"  mel 범위: [{mel_int8.min()}~{mel_int8.max()}]  "
              f"평균={mel_int8.mean():.1f}")

        spk_L3, mem_L3, spk_L1, spk_L2 = snn_forward(
            mel_int8, W1, W2, W3,
            beta_L1, beta_L2, beta_L3,
            vth_L1,  vth_L2,  vth_L3,
            l1_shift=args.l1_shift
        )

        result, mem_mean = classify(mem_L3)
        result_str = "이상(1)" if result == 1 else "정상(0)"

        print(f"  스파이크율  L1:{spk_L1.mean():.3f}  "
              f"L2:{spk_L2.mean():.3f}  L3:{spk_L3.mean():.3f}")
        print(f"  막전위 평균 N={mem_mean[0]:.1f}  A={mem_mean[1]:.1f}")
        print(f"  ▶ 판정: {result_str}")

        if args.golden:
            save_golden(tag, mel_int8, spk_L3, mem_L3,
                        os.path.join(wdir, "golden"))

    if args.golden:
        print(f"\n  골든 벡터 경로: {wdir}/golden/")
    print("\n✅ 순전파 검증 완료")


if __name__ == "__main__":
    main()
