"""다중 모델 SNN 가속기용 PLIF-T 모델 (`40→384→256→64→2`).

선행 SpikeSense-Edge `snn_model.py`(`40→128→32→2`)를 확장했다.
- 가중치 층 4개(bias 없음), INT8 기준 130,176 B = 127.125 KiB
- PLIF-T 뉴런 706개(384 + 256 + 64 + 2), 뉴런별 beta·threshold 학습
- 뉴런 갱신 규칙(누설 → 적분 → 발화 → soft reset)과 surrogate gradient는 선행과 같다.
  RTL `plift_core`와 INT8 골든 참조(P1.7)가 이 규칙을 따른다.
"""

import torch
import torch.nn as nn
import numpy as np

# 모델 구조 (PROPOSAL.md §3, 중간보고 기준)
LAYER_SIZES = (40, 384, 256, 64, 2)
N_WEIGHTS = sum(a * b for a, b in zip(LAYER_SIZES[:-1], LAYER_SIZES[1:]))  # 130,176
N_NEURONS = sum(LAYER_SIZES[1:])                                            # 706


class FastSigmoidSurrogate(torch.autograd.Function):
    @staticmethod
    def forward(ctx, membrane, threshold):
        ctx.save_for_backward(membrane, threshold)
        return (membrane >= threshold).float()

    @staticmethod
    def backward(ctx, grad_output):
        membrane, threshold = ctx.saved_tensors
        x = membrane - threshold
        grad = 1.0 / (2.0 * (1.0 + torch.abs(x)) ** 2)
        return grad * grad_output, None


def spike_fn(membrane, threshold):
    return FastSigmoidSurrogate.apply(membrane, threshold)


def _logit(beta):
    beta = np.clip(np.asarray(beta, dtype=np.float64), 0.01, 0.99)
    return np.log(beta / (1.0 - beta))


def grouped_beta(n_neurons, betas):
    """뉴런을 len(betas)개 그룹으로 균등 분할해 그룹별 초기 beta를 준다.

    선행 모델의 다중 시간상수 초기화(예: 128 = 32 × [0.70, 0.80, 0.90, 0.95])를
    임의 뉴런 수로 일반화한다. 나머지는 마지막 그룹에 붙는다.
    """
    per = n_neurons // len(betas)
    out = []
    for i, b in enumerate(betas):
        cnt = per if i < len(betas) - 1 else n_neurons - per * (len(betas) - 1)
        out += [b] * cnt
    return out


# PLIF-T (Parametric LIF with Learnable Threshold) 뉴런

class PLIFLayer(nn.Module):
    def __init__(self, n_neurons, init_beta=0.8, init_threshold=1.0):
        super().__init__()
        self.n_neurons = n_neurons

        # 스칼라면 전 뉴런 동일, 리스트면 뉴런별 초기값
        w_beta = np.broadcast_to(_logit(init_beta), (n_neurons,))
        self.w_beta = nn.Parameter(torch.tensor(w_beta, dtype=torch.float32))

        # 학습 가능한 임계값
        self.w_thr = nn.Parameter(torch.full((n_neurons,), init_threshold, dtype=torch.float32))

    def beta(self):
        return torch.sigmoid(self.w_beta)

    def threshold(self):
        # 임계값이 0 이하로 내려가지 않도록 최소 0.1로 클램프
        return torch.clamp(self.w_thr, min=0.1)

    def forward(self, input_current, membrane):
        beta = self.beta()
        thr = self.threshold()

        membrane = beta * membrane + input_current
        spikes = spike_fn(membrane, thr)

        # Soft reset: 발화 시 임계값만큼 막전위 차감
        membrane = membrane - spikes * thr

        return spikes, membrane

    def init_membrane(self, batch_size, device='cpu'):
        return torch.zeros(batch_size, self.n_neurons, device=device)


# SNN 모델 구조

# 층별 초기 beta 그룹. 은닉층 1·2는 선행 hidden1·hidden2 값을 그대로 쓰고,
# 추가된 은닉층 3은 hidden2 값을 따른다. 출력층은 선행과 같이 0.85 단일값.
INIT_BETAS = (
    (0.70, 0.80, 0.90, 0.95),
    (0.75, 0.85, 0.90, 0.95),
    (0.75, 0.85, 0.90, 0.95),
    0.85,
)


class AnomalySNN(nn.Module):
    """`40→384→256→64→2` PLIF-T SNN.

    출력 2개는 0 = 정상, 1 = 이상(2026-09-23 확정). 결함 종류 분류는 DCASE 데이터에
    해당 라벨이 없어 채택하지 않았다.
    판정은 선행과 같이 출력층 막전위의 시간 평균 argmax를 쓴다.
    """

    def __init__(self, layer_sizes=LAYER_SIZES, init_betas=INIT_BETAS, init_threshold=1.0):
        super().__init__()
        assert len(init_betas) == len(layer_sizes) - 1

        self.layer_sizes = tuple(layer_sizes)
        self.n_input = layer_sizes[0]
        self.n_output = layer_sizes[-1]

        self.fcs = nn.ModuleList()
        self.lifs = nn.ModuleList()
        for n_in, n_out, betas in zip(layer_sizes[:-1], layer_sizes[1:], init_betas):
            fc = nn.Linear(n_in, n_out, bias=False)
            nn.init.xavier_normal_(fc.weight, gain=5.0)
            self.fcs.append(fc)

            init_beta = grouped_beta(n_out, betas) if isinstance(betas, (tuple, list)) else betas
            self.lifs.append(PLIFLayer(n_out, init_beta=init_beta, init_threshold=init_threshold))

    def forward(self, spike_input):
        """spike_input: [batch, T, n_input].

        반환: (출력 스파이크 [B, T, 2], 출력 막전위 [B, T, 2], 마지막 은닉층 스파이크 [B, T, 64])
        """
        batch_size, n_timesteps = spike_input.shape[:2]
        device = spike_input.device

        mems = [lif.init_membrane(batch_size, device) for lif in self.lifs]

        output_spike_record, output_mem_record, hidden_spike_record = [], [], []

        for t in range(n_timesteps):
            x = spike_input[:, t, :]
            spikes = []
            for i, (fc, lif) in enumerate(zip(self.fcs, self.lifs)):
                x, mems[i] = lif(fc(x), mems[i])
                spikes.append(x)

            output_spike_record.append(spikes[-1])
            output_mem_record.append(mems[-1].clone())
            hidden_spike_record.append(spikes[-2])

        return (torch.stack(output_spike_record, dim=1),
                torch.stack(output_mem_record, dim=1),
                torch.stack(hidden_spike_record, dim=1))

    @staticmethod
    def predict(output_mem):
        """출력 막전위 시간 평균의 argmax → 클래스 인덱스"""
        return output_mem.mean(dim=1).argmax(dim=1)

    def weight_count(self):
        return sum(fc.weight.numel() for fc in self.fcs)

    def neuron_count(self):
        return sum(lif.n_neurons for lif in self.lifs)


if __name__ == "__main__":
    model = AnomalySNN()
    n_w, n_n = model.weight_count(), model.neuron_count()
    print(f"구조        : {'→'.join(map(str, model.layer_sizes))}")
    for i, fc in enumerate(model.fcs, 1):
        print(f"  L{i} weight : {tuple(fc.weight.shape)} = {fc.weight.numel():,} B (INT8)")
    print(f"가중치 수   : {n_w:,} ({n_w / 1024:.1f} KiB INT8)")
    print(f"뉴런 수     : {n_n}")
    print(f"PLIF 파라미터: {sum(p.numel() for l in model.lifs for p in l.parameters()):,} (beta·thr, 뉴런당 2개)")
    assert n_w == N_WEIGHTS == 130_176
    assert n_n == N_NEURONS == 706

    x = (torch.rand(4, 10, model.n_input) < 0.3).float()
    spk, mem, hid = model(x)
    loss = mem.mean(dim=1).sum()
    loss.backward()
    assert all(p.grad is not None for p in model.parameters())
    print(f"순전파      : out_spk {tuple(spk.shape)}, out_mem {tuple(mem.shape)}, hidden {tuple(hid.shape)}")
    print("검증 통과")
