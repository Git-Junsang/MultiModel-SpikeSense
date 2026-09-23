"""장비 1대(모델 1개) 학습 — 정상/이상 2진 분류.

선행 train.py의 학습 흐름(FocalLoss, 출력 막전위 시간평균, Adam, grad clip,
SpecAugment 마스킹)을 따른다. 이상 샘플의 출처를 세 가지 중에서 고른다:

  other_id : 같은 기종의 다른 ID 정상 소리를 이상으로 쓴다.
  mix      : 대상 ID 정상 세그먼트의 일부 시간·주파수 영역(패치 마스크)에
             같은 기종 다른 ID 소리를 전력 합으로 섞는다.

  supervised : [기본] test 이상 파일의 절반을 학습에 쓰고, 나머지 절반과 test 정상
             전체로 평가한다. 정상만으로 학습하는 DCASE 원래 조건과 다르므로 공식
             순위표와 직접 비교하지 않는다. 선행 SpikeSense-Edge와 같은 지도학습 조건이며,
             other_id·mix로는 실제 이상을 탐지하지 못한 결과가 이 선택의 근거다
             (runs/fan_id00/REPORT.md).

모든 방법에서 학습 배치 전체(정상·이상)에 선행과 같은 시간·주파수 마스킹을 적용한다.
출력층은 2뉴런이며 0 = 정상, 1 = 이상이다.

검증(val): 대상 ID train 정상 중 10% 파일 + 같은 방법으로 만든 학습용 이상. 체크포인트 선택 기준.
평가(test): 대상 ID의 DCASE test(실제 정상·이상). 파일 단위 AUC·pAUC(FPR ≤ 0.1).
test 지표는 기록만 하고 모델 선택에 쓰지 않는다.
"""

import os
import csv
import json
import time
import argparse
import numpy as np
import torch
import torch.nn as nn
from sklearn.metrics import roc_auc_score, f1_score

import dcase_data as dd
from snn_model import AnomalySNN

N_CLASS = 2          # 출력 0 = 정상, 1 = 이상


class FocalLoss(nn.Module):
    def __init__(self, gamma=2.0):
        super().__init__()
        self.gamma = gamma

    def forward(self, logits, targets):
        log_pt = torch.log_softmax(logits, dim=1).gather(1, targets.view(-1, 1)).view(-1)
        pt = log_pt.exp()
        return (-(1 - pt) ** self.gamma * log_pt).mean()


# ── 마스킹·학습용 이상 생성 (GPU 배치 연산) ──

def spec_mask(x, gen, p=0.5, frac=0.15):
    """선행 MelDataset과 같은 마스킹: 확률 p로 주파수 6 mel, 시간 4 프레임 폭을 0으로."""
    B, T, F = x.shape
    x = x.clone()
    fw, tw = int(F * frac), int(T * frac)
    dev = x.device
    f0 = torch.randint(0, F - fw, (B, 1), generator=gen, device=dev)
    t0 = torch.randint(0, T - tw, (B, 1), generator=gen, device=dev)
    fon = torch.rand(B, 1, generator=gen, device=dev) < p
    ton = torch.rand(B, 1, generator=gen, device=dev) < p
    fi = torch.arange(F, device=dev).view(1, F)
    ti = torch.arange(T, device=dev).view(1, T)
    fm = fon & (fi >= f0) & (fi < f0 + fw)          # [B, F]
    tm = ton & (ti >= t0) & (ti < t0 + tw)          # [B, T]
    keep = ~(fm.unsqueeze(1) | tm.unsqueeze(2))
    return x * keep


def mix_patch(base, other, gen, min_t=8, min_f=8, gain_db=(-6.0, 3.0)):
    """base의 임의 시간·주파수 패치에 other를 전력 합으로 더한다.

    특징값 v ∈ [0, 1]은 파일 최대 기준 dB를 80 dB 폭으로 정규화한 값이므로
    전력 ∝ 10^(8v)로 되돌려 더한다: v' = log10(10^(8 v_b) + g · 10^(8 v_o)) / 8.
    """
    B, T, F = base.shape
    dev = base.device
    tl = torch.randint(min_t, T + 1, (B, 1), generator=gen, device=dev)
    fl = torch.randint(min_f, F + 1, (B, 1), generator=gen, device=dev)
    t0 = (torch.rand(B, 1, generator=gen, device=dev) * (T - tl + 1)).long()
    f0 = (torch.rand(B, 1, generator=gen, device=dev) * (F - fl + 1)).long()
    ti = torch.arange(T, device=dev).view(1, T)
    fi = torch.arange(F, device=dev).view(1, F)
    patch = (((ti >= t0) & (ti < t0 + tl)).unsqueeze(2)
             & ((fi >= f0) & (fi < f0 + fl)).unsqueeze(1))
    g = gain_db[0] + (gain_db[1] - gain_db[0]) * torch.rand(B, 1, 1, generator=gen, device=dev)
    k = dd.TOP_DB / 10.0
    mixed = torch.log10(10 ** (k * base) + 10 ** (g / 10.0 + k * other)) / k
    return torch.where(patch, mixed.clamp(0.0, 1.0), base)


def make_anomaly(method, normal_pool, other_pool, n, gen):
    dev = other_pool.device
    oi = torch.randint(0, len(other_pool), (n,), generator=gen, device=dev)
    if method in ("other_id", "supervised"):
        return other_pool[oi]
    bi = torch.randint(0, len(normal_pool), (n,), generator=gen, device=dev)
    return mix_patch(normal_pool[bi], other_pool[oi], gen)


# ── 데이터 준비 ──

def split_by_file(d, frac, rng):
    files = np.unique(d["file_idx"])
    val_files = rng.choice(files, max(1, int(round(len(files) * frac))), replace=False)
    is_val = np.isin(d["file_idx"], val_files)
    return d["seg"][~is_val], d["seg"][is_val]


def prepare(machine, mid, method, val_frac, seed, device):
    rng = np.random.RandomState(seed)
    tgt = dd.load_unit(machine, mid, "train")
    tr_n, va_n = split_by_file(tgt, val_frac, rng)
    te = dd.load_unit(machine, mid, "test")
    te_seg, te_lab, te_file = te["seg"], te["label"].astype(int), te["file_idx"]

    if method == "supervised":
        # 이상 파일을 학습 50% / 평가 50%로 나누고, 학습 쪽의 10%는 val로 뗀다
        anom_files = np.unique(te_file[te_lab == 1])
        rng.shuffle(anom_files)
        half = len(anom_files) // 2
        fit_files, eval_anom = anom_files[:half], anom_files[half:]
        n_val = max(1, int(round(len(fit_files) * val_frac)))
        tr_o = [te_seg[np.isin(te_file, fit_files[n_val:])]]
        va_o = [te_seg[np.isin(te_file, fit_files[:n_val])]]
        keep = (te_lab == 0) | np.isin(te_file, eval_anom)
        te_seg, te_lab = te_seg[keep], te_lab[keep]
        _, te_file = np.unique(te_file[keep], return_inverse=True)
    else:
        tr_o, va_o = [], []
        for oid in dd.MACHINE_IDS[machine]:
            if oid == mid:
                continue
            a, b = split_by_file(dd.load_unit(machine, oid, "train"), val_frac, rng)
            tr_o.append(a); va_o.append(b)

    T = lambda a: torch.tensor(np.asarray(a), dtype=torch.float32, device=device)
    return {
        "train_normal": T(tr_n), "val_normal": T(va_n),
        "train_other": T(np.concatenate(tr_o)), "val_other": T(np.concatenate(va_o)),
        "test_seg": T(te_seg), "test_label": te_lab, "test_file": te_file,
        "bal_idx": balanced_idx(te_lab, rng),
    }


def balanced_idx(y, rng):
    """정상과 이상 세그먼트 수를 맞춘 인덱스. F1을 선행 연구(균형 데이터)와 비교하기 위함."""
    n0, n1 = np.flatnonzero(y == 0), np.flatnonzero(y == 1)
    k = min(len(n0), len(n1))
    return np.sort(np.concatenate([rng.choice(n0, k, replace=False), rng.choice(n1, k, replace=False)]))


# ── 학습·평가 ──

@torch.no_grad()
def infer(model, x, bs=1024):
    model.eval()
    out = []
    for s in range(0, len(x), bs):
        _, mem, _ = model(x[s:s + bs])
        out.append(mem.mean(dim=1)[:, :N_CLASS])
    return torch.cat(out)


def evaluate(model, data, val_x, val_y, loss_fn):
    r = {}
    lg = infer(model, val_x)
    r["val_loss"] = loss_fn(lg, val_y).item()
    r["val_acc"] = (lg.argmax(1) == val_y).float().mean().item()
    r["val_auc"] = roc_auc_score(val_y.cpu().numpy(), torch.softmax(lg, 1)[:, 1].cpu().numpy())

    lg = infer(model, data["test_seg"])
    prob = torch.softmax(lg, 1)[:, 1].cpu().numpy()
    pred = lg.argmax(1).cpu().numpy()
    y, f = data["test_label"], data["test_file"]
    r["test_seg_acc"] = float((pred == y).mean())
    r["test_seg_f1"] = f1_score(y, pred, zero_division=0)
    b = data["bal_idx"]
    r["test_f1_bal"] = f1_score(y[b], pred[b], zero_division=0)
    r["test_acc_bal"] = float((pred[b] == y[b]).mean())
    # 파일 단위 점수 = 세그먼트 P(이상) 평균 (DCASE는 파일 단위 AUC)
    nf = f.max() + 1
    clip_score = np.bincount(f, prob, nf) / np.bincount(f, minlength=nf)
    clip_y = np.bincount(f, y, nf) / np.bincount(f, minlength=nf)
    r["test_auc"] = roc_auc_score(clip_y, clip_score)
    r["test_pauc"] = roc_auc_score(clip_y, clip_score, max_fpr=0.1)
    return r


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--machine", default="fan")
    ap.add_argument("--mid", default="00")
    ap.add_argument("--method", choices=["supervised", "other_id", "mix"], default="supervised")
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--batch_size", type=int, default=256)
    ap.add_argument("--lr", type=float, default=0.002)
    ap.add_argument("--sched", choices=["cosine", "const"], default="cosine")
    ap.add_argument("--mask_p", type=float, default=0.5)
    ap.add_argument("--val_frac", type=float, default=0.1)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out_dir", default=None)
    args = ap.parse_args(argv)

    name = dd.unit_name(args.machine, args.mid)
    out_dir = args.out_dir or os.path.join(dd.SOFTWARE_DIR, "runs", name,
                                           f"{args.method}_bs{args.batch_size}_{args.sched}_e{args.epochs}")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "args.json"), "w") as f:
        json.dump(vars(args), f, indent=2)

    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    gen = torch.Generator(device=device).manual_seed(args.seed)

    data = prepare(args.machine, args.mid, args.method, args.val_frac, args.seed, device)
    n_norm = len(data["train_normal"])

    # 고정 val 세트: val 정상 + 같은 수의 학습용 이상(고정 seed로 1회 생성)
    vgen = torch.Generator(device=device).manual_seed(args.seed + 1)
    nv = len(data["val_normal"])
    val_x = torch.cat([data["val_normal"],
                       make_anomaly(args.method, data["val_normal"], data["val_other"], nv, vgen)])
    val_y = torch.cat([torch.zeros(nv), torch.ones(nv)]).long().to(device)

    print(f"[{name}] method={args.method} bs={args.batch_size} epochs={args.epochs} sched={args.sched}")
    print(f"  train 정상 {n_norm} seg, 다른 ID 풀 {len(data['train_other'])} seg, "
          f"val {len(val_x)} seg, test {len(data['test_seg'])} seg")

    model = AnomalySNN().to(device)
    loss_fn = FocalLoss(gamma=2.0)
    opt = torch.optim.Adam(model.parameters(), lr=args.lr, weight_decay=1e-5)
    sched = (torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=args.epochs)
             if args.sched == "cosine" else None)

    log_path = os.path.join(out_dir, "history.csv")
    cols = ["epoch", "lr", "train_loss", "train_acc", "val_loss", "val_acc", "val_auc",
            "test_seg_acc", "test_seg_f1", "test_acc_bal", "test_f1_bal",
            "test_auc", "test_pauc", "epoch_sec"]
    log_f = open(log_path, "w", newline="")
    log_w = csv.DictWriter(log_f, fieldnames=cols)
    log_w.writeheader()

    best_val, best_metrics = float("inf"), None
    for epoch in range(1, args.epochs + 1):
        t0 = time.time()
        model.train()
        # 에포크마다 정상 전체 + 같은 수의 학습용 이상을 새로 생성
        anom = make_anomaly(args.method, data["train_normal"], data["train_other"], n_norm, gen)
        x_all = torch.cat([data["train_normal"], anom])
        y_all = torch.cat([torch.zeros(n_norm), torch.ones(n_norm)]).long().to(device)
        perm = torch.randperm(len(x_all), generator=gen, device=device)

        tot_loss, tot_correct = 0.0, 0
        for s in range(0, len(perm), args.batch_size):
            idx = perm[s:s + args.batch_size]
            x = spec_mask(x_all[idx], gen, p=args.mask_p)
            y = y_all[idx]
            _, mem, _ = model(x)
            logits = mem.mean(dim=1)[:, :N_CLASS]
            loss = loss_fn(logits, y)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            opt.step()
            tot_loss += loss.item() * len(idx)
            tot_correct += (logits.argmax(1) == y).sum().item()

        lr = opt.param_groups[0]["lr"]
        if sched:
            sched.step()
        r = evaluate(model, data, val_x, val_y, loss_fn)
        r.update(epoch=epoch, lr=lr, train_loss=tot_loss / len(perm),
                 train_acc=tot_correct / len(perm), epoch_sec=time.time() - t0)
        log_w.writerow({k: (f"{v:.6f}" if isinstance(v, float) else v) for k, v in r.items()})
        log_f.flush()

        if r["val_loss"] < best_val:
            best_val, best_metrics = r["val_loss"], dict(r)
            torch.save({"epoch": epoch, "model_state_dict": model.state_dict(),
                        "args": vars(args), "metrics": r}, os.path.join(out_dir, "best_val.pth"))
        if epoch % 10 == 0 or epoch == 1:
            print(f"  ep {epoch:3d} | train {r['train_loss']:.4f}/{r['train_acc']:.3f} "
                  f"| val {r['val_loss']:.4f}/{r['val_acc']:.3f} auc {r['val_auc']:.3f} "
                  f"| test AUC {r['test_auc']:.3f} pAUC {r['test_pauc']:.3f} | {r['epoch_sec']:.1f}s",
                  flush=True)

    torch.save({"epoch": args.epochs, "model_state_dict": model.state_dict(), "args": vars(args)},
               os.path.join(out_dir, "last.pth"))
    log_f.close()
    print(f"  완료 → {out_dir}")
    return {"unit": name, "out_dir": out_dir, "best": best_metrics, "last": r}


if __name__ == "__main__":
    main()
