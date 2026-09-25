"""SNN 기반 음향 이상 감지 모델 (PLIF-T).

beta(감쇠율)와 threshold(발화 임계값)를 모두 학습 파라미터로 둔다.
"""

import torch
import torch.nn as nn
import numpy as np

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

# PLIF-T (Parametric LIF with Learnable Threshold) 뉴런

class PLIFLayer(nn.Module):
    def __init__(self, n_neurons, init_beta=0.8, init_threshold=1.0):
        super().__init__()
        self.n_neurons = n_neurons
        
        init_beta_clamped = np.clip(init_beta, 0.01, 0.99)
        init_w_beta = np.log(init_beta_clamped / (1.0 - init_beta_clamped))
        
        if isinstance(init_beta, (list, np.ndarray)):
            init_w_array = [np.log(np.clip(b, 0.01, 0.99) / (1.0 - np.clip(b, 0.01, 0.99))) for b in init_beta]
            self.w_beta = nn.Parameter(torch.tensor(init_w_array, dtype=torch.float32))
        else:
            self.w_beta = nn.Parameter(torch.full((n_neurons,), init_w_beta, dtype=torch.float32))

        # 학습 가능한 임계값
        self.w_thr = nn.Parameter(torch.full((n_neurons,), init_threshold, dtype=torch.float32))

    def forward(self, input_current, membrane):
        beta = torch.sigmoid(self.w_beta).to(input_current.device)
        
        # 임계값이 0 이하로 내려가지 않도록 최소 0.1로 클램프
        thr = torch.clamp(self.w_thr, min=0.1).to(input_current.device)

        membrane = beta * membrane + input_current
        spikes = spike_fn(membrane, thr)

        # Soft reset: 발화 시 임계값만큼 막전위 차감
        membrane = membrane - spikes * thr
        
        return spikes, membrane

    def init_membrane(self, batch_size, device='cpu'):
        return torch.zeros(batch_size, self.n_neurons, device=device)

# SNN 모델 구조

class AnomalySNN(nn.Module):
    def __init__(self, n_input=40):
        super().__init__()

        self.n_input   = n_input
        self.n_hidden1 = 128
        self.n_hidden2 = 32
        self.n_output  = 2

        self.fc1 = nn.Linear(self.n_input, self.n_hidden1, bias=False)
        self.fc2 = nn.Linear(self.n_hidden1, self.n_hidden2, bias=False)
        self.fc3 = nn.Linear(self.n_hidden2, self.n_output, bias=False)

        nn.init.xavier_normal_(self.fc1.weight, gain=5.0)
        nn.init.xavier_normal_(self.fc2.weight, gain=5.0)
        nn.init.xavier_normal_(self.fc3.weight, gain=5.0)

        init_beta_h1 = ([0.70]*32 + [0.80]*32 + [0.90]*32 + [0.95]*32)
        self.hidden1_lif = PLIFLayer(n_neurons=self.n_hidden1, init_beta=init_beta_h1, init_threshold=1.0)
        
        init_beta_h2 = ([0.75]*8 + [0.85]*8 + [0.90]*8 + [0.95]*8)
        self.hidden2_lif = PLIFLayer(n_neurons=self.n_hidden2, init_beta=init_beta_h2, init_threshold=1.0)
        
        self.output_lif = PLIFLayer(n_neurons=self.n_output, init_beta=0.85, init_threshold=1.0)

    def forward(self, spike_input):
        batch_size = spike_input.size(0)
        n_timesteps = spike_input.size(1)
        device = spike_input.device

        mem_h1 = self.hidden1_lif.init_membrane(batch_size, device)
        mem_h2 = self.hidden2_lif.init_membrane(batch_size, device)
        mem_out = self.output_lif.init_membrane(batch_size, device)

        output_spike_record, output_mem_record, hidden_spike_record = [], [], []

        for t in range(n_timesteps):
            x = spike_input[:, t, :]

            current_h1 = self.fc1(x)
            spk_h1, mem_h1 = self.hidden1_lif(current_h1, mem_h1)

            current_h2 = self.fc2(spk_h1)
            spk_h2, mem_h2 = self.hidden2_lif(current_h2, mem_h2)

            current_out = self.fc3(spk_h2)
            spk_out, mem_out = self.output_lif(current_out, mem_out)

            output_spike_record.append(spk_out)
            output_mem_record.append(mem_out.clone())
            hidden_spike_record.append(spk_h2)

        return torch.stack(output_spike_record, dim=1), torch.stack(output_mem_record, dim=1), torch.stack(hidden_spike_record, dim=1)
