"""PLIF-T `40→384→256→64→2` INT8 양자화와 정수 순전파 (P1.5).

양자화 규칙은 선행 SpikeSense-Edge `export_weights.py`와 같고, 막전위 포화만 새로 넣었다.
뉴런 갱신은 `plift_core.v`와 같은 순서다(누설 → 적분 → 발화 → soft reset).

  입력      x_q   = clip(round(mel × 127), 0, 127)            mel ∈ [0, 1], 0~127
  가중치    s_l   = max|W_l| / 127                             층별 대칭 (뉴런별 스케일 기각, P1.5 리포트 §3)
            W_q   = clip(round(W / s_l), -128, 127)            INT8
  누설      beta_q = clip(round(beta × 256), 0, 255)           Q0.8 uint8
  임계값    vth_q = round(thr / s_l)                            40대 범위 7~118 → uint8
  층 1 전류 cur   = (Σ x_q · W_q) >> 7                          누산 후 산술 시프트(내림)
  층 2~4    cur   = Σ spike · W_q                               스파이크 조건부 누산
  막전위    mem   = sat16(((beta_q · mem) >> 8) + cur)          누설 내림, 16 bit 포화 가산
            spike = mem >= vth_q ;  mem -= spike · vth_q
  판정      출력층 막전위 시간 평균의 argmax (0 = 정상, 1 = 이상)

선행 RTL은 16 bit에서 넘치면 값이 되감긴다(wrap). 층 2 누산의 이론 최대는 384 × 128 = 49,152로
INT16을 넘으므로 이 설계는 전류를 넓은 폭으로 더한 뒤 [-32768, 32767]로 포화시킨다.
누산기 폭: 층 1 이론 최대 |Σ| = 40 × 127 × 128 = 650,240 → 부호 포함 21 bit 이상.

행렬곱은 float64로 계산한다. 피연산자가 모두 정수이고 누산값이 2^53보다 훨씬 작아
정수 연산과 결과가 같다(BLAS 속도를 쓰기 위함). 나머지 원소 연산은 int64다.
"""

import numpy as np

IN_SCALE = 127          # mel [0, 1] → 0~127
IN_SHIFT = 7            # 층 1 누산 후 >> 7 (x_q의 127배를 되돌림)
BETA_SHIFT = 8          # beta Q0.8
MEM_MIN, MEM_MAX = -32768, 32767


def quantize_input(x):
    """mel float [..., 40] ∈ [0, 1] → int64 0~127"""
    return np.clip(np.rint(np.asarray(x, np.float64) * IN_SCALE), 0, IN_SCALE).astype(np.int64)


def quantize(layers):
    """snn_numpy.load_params 결과(층별 W·beta·thr, FP32) → 층별 정수 파라미터.

    반환 dict 목록: W [out, in] int8, beta uint8, vth uint8, scale(float, 역양자화용).
    """
    q = []
    for l in layers:
        W = l["W"].astype(np.float64)
        s = float(np.abs(W).max()) / 127.0
        W_q = np.clip(np.rint(W / s), -128, 127).astype(np.int8)
        beta_q = np.clip(np.rint(l["beta"].astype(np.float64) * (1 << BETA_SHIFT)), 0, 255).astype(np.uint8)
        vth = np.rint(l["thr"].astype(np.float64) / s)
        if vth.min() < 1 or vth.max() > 255:
            raise ValueError(f"vth_q 범위 [{vth.min():.0f}, {vth.max():.0f}]가 uint8(1~255) 밖")
        q.append({"W": W_q, "beta": beta_q, "vth": vth.astype(np.uint8), "scale": s})
    return q


def forward(q, x_q, stats=None):
    """x_q: int [B, T, 40] (0~127) → 출력 막전위 int64 [B, T, 2].

    stats에 dict를 넘기면 층별 누산 |최대|(acc), 포화 전 막전위 |최대|(mem),
    포화 횟수(sat), 층별 스파이크 기록(spk, int8 [B, T, N])을 채운다.
    """
    x_q = np.asarray(x_q)
    B, T, _ = x_q.shape
    Wt = [l["W"].astype(np.float64).T for l in q]
    beta = [l["beta"].astype(np.int64) for l in q]
    vth = [l["vth"].astype(np.int64) for l in q]
    mems = [np.zeros((B, l["W"].shape[0]), np.int64) for l in q]
    out = np.zeros((B, T, q[-1]["W"].shape[0]), np.int64)
    if stats is not None:
        n = len(q)
        stats.update(acc=[0] * n, mem=[0] * n, sat=[0] * n,
                     spk=[np.zeros((B, T, l["W"].shape[0]), np.int8) for l in q])

    for t in range(T):
        h = x_q[:, t, :].astype(np.float64)
        for i in range(len(q)):
            acc = np.rint(h @ Wt[i]).astype(np.int64)
            cur = acc >> IN_SHIFT if i == 0 else acc
            mem = ((beta[i] * mems[i]) >> BETA_SHIFT) + cur
            if stats is not None:
                stats["acc"][i] = max(stats["acc"][i], int(np.abs(acc).max()))
                stats["mem"][i] = max(stats["mem"][i], int(np.abs(mem).max()))
                stats["sat"][i] += int(((mem < MEM_MIN) | (mem > MEM_MAX)).sum())
            mem = np.clip(mem, MEM_MIN, MEM_MAX)
            spk = (mem >= vth[i]).astype(np.int64)
            mems[i] = mem - spk * vth[i]
            if stats is not None:
                stats["spk"][i][:, t] = spk
            h = spk.astype(np.float64)
        out[:, t] = mems[-1]
    return out


def predict(mem_out):
    """출력 막전위 시간 평균의 argmax → 클래스 인덱스 (정수 그대로 비교)"""
    return mem_out.mean(axis=1).argmax(axis=1)


def dequant_logit(q, mem_out):
    """출력 막전위 시간 평균을 FP 단위로 되돌린다. AUC용 softmax 점수는 Host에서 이 값으로 계산한다."""
    return mem_out.mean(axis=1) * q[-1]["scale"]
