"""신규 AnomalySNN을 40→128→32→2로 설정해 선행 모델(references/snn_model.py)과
출력·기울기가 같은지 확인한다(P1.3 검증). 실행: python3 verify_reference.py"""
import sys, torch, numpy as np
import importlib.util
def load(name, path):
    sp = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(sp); sp.loader.exec_module(m); return m
new = load("new_snn", "snn_model.py")
ref = load("ref_snn", "references/snn_model.py")

torch.manual_seed(0)
r = ref.AnomalySNN(n_input=40)
n = new.AnomalySNN(layer_sizes=(40,128,32,2),
                   init_betas=((0.70,0.80,0.90,0.95),(0.75,0.85,0.90,0.95),0.85))
# 가중치·PLIF 파라미터를 선행에서 그대로 복사
n.fcs[0].weight.data.copy_(r.fc1.weight.data); n.fcs[1].weight.data.copy_(r.fc2.weight.data)
n.fcs[2].weight.data.copy_(r.fc3.weight.data)
for a, b in zip(n.lifs, [r.hidden1_lif, r.hidden2_lif, r.output_lif]):
    a.w_beta.data.copy_(b.w_beta.data); a.w_thr.data.copy_(b.w_thr.data)

# 초기화만으로도 beta 그룹이 같은지 확인(복사 전 값 비교)
n2 = new.AnomalySNN(layer_sizes=(40,128,32,2),
                    init_betas=((0.70,0.80,0.90,0.95),(0.75,0.85,0.90,0.95),0.85))
print("초기 beta 그룹 일치 L1:", torch.allclose(n2.lifs[0].w_beta, r.hidden1_lif.w_beta),
      "| L2:", torch.allclose(n2.lifs[1].w_beta, r.hidden2_lif.w_beta),
      "| L3:", torch.allclose(n2.lifs[2].w_beta, r.output_lif.w_beta))

x = (torch.rand(8, 31, 40) < 0.3).float()
with torch.no_grad():
    a = r(x); b = n(x)
for i, name in enumerate(["출력 스파이크", "출력 막전위", "은닉 스파이크"]):
    print(f"{name}: 최대 절대오차 {(a[i]-b[i]).abs().max().item():.3e}  동일 {torch.equal(a[i], b[i])}")

# 역전파 경로도 같은지
x2 = (torch.rand(4, 31, 40) < 0.3).float()
r.zero_grad(); n.zero_grad()
r(x2)[1].mean(1).sum().backward(); n(x2)[1].mean(1).sum().backward()
g = max((r.fc1.weight.grad - n.fcs[0].weight.grad).abs().max().item(),
        (r.hidden1_lif.w_thr.grad - n.lifs[0].w_thr.grad).abs().max().item())
print(f"기울기 최대 절대오차 {g:.3e}")

m = new.AnomalySNN()
print(f"확정 구조 가중치 {m.weight_count():,} | 뉴런 {m.neuron_count()} | "
      f"PLIF 파라미터 {sum(p.numel() for l in m.lifs for p in l.parameters()):,}")
