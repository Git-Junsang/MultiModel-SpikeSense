"""PLIF-T `40→384→256→64→2` FP32 NumPy 순전파 (PyTorch 없이).

`snn_model.AnomalySNN`의 추론 경로를 프레임워크 없이 한 줄씩 다시 쓴 것이다.
P1.7 INT8 골든 참조의 뼈대이며, FP 단계에서 PyTorch와 출력이 같은지 먼저 확인한다
(P0.8, 검증 스크립트 `analysis_develop/check_numpy_fp.py`).

뉴런 규칙 (snn_model.PLIFLayer와 같다):
  beta    = sigmoid(w_beta)
  thr     = max(w_thr, 0.1)
  mem     = beta · mem + W · x          # 누설 → 적분 (bias 없음)
  spike   = (mem >= thr)
  mem     = mem - spike · thr           # soft reset
타임스텝마다 층 1 → 4 순서로 갱신하고, 막전위 초기값은 0이다.
층 1 입력은 mel 특징값(연속값 [0, 1])이고, 층 2~4 입력은 앞 층 스파이크(0/1)다.
판정: 출력층 막전위의 시간 평균 argmax (0 = 정상, 1 = 이상).
"""

import numpy as np

DTYPE = np.float32


def load_params(pth_path):
    """체크포인트(`model_weights/<장비>/last.pth`) → 층별 (W, beta, thr) NumPy 배열.

    torch는 파일 읽기에만 쓴다. 반환값은 모두 float32 NumPy 배열이다.
    """
    import torch
    ckpt = torch.load(pth_path, map_location="cpu", weights_only=False)
    sd = ckpt.get("model_state_dict", ckpt)
    layers = []
    i = 0
    while f"fcs.{i}.weight" in sd:
        w = sd[f"fcs.{i}.weight"].numpy().astype(DTYPE)                  # [out, in]
        w_beta = sd[f"lifs.{i}.w_beta"].numpy().astype(DTYPE)
        w_thr = sd[f"lifs.{i}.w_thr"].numpy().astype(DTYPE)
        beta = (DTYPE(1) / (DTYPE(1) + np.exp(-w_beta))).astype(DTYPE)
        thr = np.maximum(w_thr, DTYPE(0.1)).astype(DTYPE)
        layers.append({"W": w, "beta": beta, "thr": thr})
        i += 1
    return layers


def forward(layers, x):
    """x: [B, T, 40] → (출력 막전위 [B, T, 2], 층별 스파이크 목록 [B, T, N_l])."""
    x = np.asarray(x, dtype=DTYPE)
    B, T, _ = x.shape
    mems = [np.zeros((B, l["W"].shape[0]), DTYPE) for l in layers]
    spk_rec = [np.zeros((B, T, l["W"].shape[0]), DTYPE) for l in layers]
    mem_out = np.zeros((B, T, layers[-1]["W"].shape[0]), DTYPE)

    for t in range(T):
        h = x[:, t, :]
        for i, l in enumerate(layers):
            cur = h @ l["W"].T
            mem = l["beta"] * mems[i] + cur
            spk = (mem >= l["thr"]).astype(DTYPE)
            mems[i] = mem - spk * l["thr"]
            spk_rec[i][:, t] = spk
            h = spk
        mem_out[:, t] = mems[-1]
    return mem_out, spk_rec


def predict(mem_out):
    """출력 막전위 시간 평균의 argmax → 클래스 인덱스"""
    return mem_out.mean(axis=1).argmax(axis=1)
