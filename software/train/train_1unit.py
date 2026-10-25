"""장비 1대(모델 1개) 학습 — 정상/이상 2진 분류.

선행 train.py의 학습 흐름(FocalLoss, 출력 membrane potential 시간평균, Adam, grad clip,
SpecAugment 마스킹)을 따른다. 이상 샘플의 출처를 세 가지 중에서 고른다:

  other_id : 같은 기종의 다른 ID 정상 소리를 이상으로 쓴다.
  mix      : 대상 ID 정상 세그먼트의 일부 시간·주파수 영역(패치 마스크)에
             같은 기종 다른 ID 소리를 전력 합으로 섞는다.

  supervised : [기본] test 이상 파일의 절반을 학습에 쓰고, 나머지 절반과 test 정상
             전체로 평가한다. 정상만으로 학습하는 DCASE 원래 조건과 다르므로 공식
             순위표와 직접 비교하지 않는다. 선행 SpikeSense-Edge와 같은 지도학습 조건이며,
             other_id·mix로는 실제 이상을 탐지하지 못한 결과가 이 선택의 근거다
             (train_result/L_normal_noaug/REPORT.md).

모든 방법에서 학습 batch 전체(정상·이상)에 선행과 같은 시간·주파수 마스킹을 적용한다.
출력 layer는 2뉴런이며 0 = 정상, 1 = 이상이다.

검증(val): 대상 ID train 정상 중 10% 파일 + 같은 방법으로 만든 학습용 이상. 체크포인트 선택 기준.
평가(test): 대상 ID의 DCASE test(실제 정상·이상). 파일 단위 AUC·pAUC(FPR ≤ 0.1).
test 지표는 기록만 하고 모델 선택에 쓰지 않는다.
"""

import os
import sys
import csv
import json
import time
import argparse
import numpy as np
import torch
import torch.nn as nn
from sklearn.metrics import roc_auc_score, f1_score

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dataset"))  # dcase_data는 software/dataset
import dcase_data as dd  # noqa: E402
from snn_torch import AnomalySNN, LAYER_SIZES, default_betas

N_CLASS = 2          # 출력 0 = 정상, 1 = 이상


class FocalLoss(nn.Module):
    def __init__(self, gamma=2.0):
        super().__init__()
        self.gamma = gamma

    def forward(self, logits, targets):
        log_pt = torch.log_softmax(logits, dim=1).gather(1, targets.view(-1, 1)).view(-1)
        pt = log_pt.exp()
        return (-(1 - pt) ** self.gamma * log_pt).mean()


# ── 마스킹·학습용 이상 생성 (GPU batch 연산) ──

def spec_mask(x, gen, p=0.5, frac=0.15):
    """선행 MelDataset과 같은 마스킹: 확률 p로 주파수 6 mel, 시간 4 frame 폭을 0으로."""
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


def split_by_file_idx(d, val_files):
    is_val = np.isin(d["file_idx"], val_files)
    return (d["seg"][~is_val], d["file_idx"][~is_val]), (d["seg"][is_val], d["file_idx"][is_val])


def _aug_segments(mel, off, files, hop):
    """증강 mel [K, ΣT, 40](파일마다 off 구간)에서 files 순서로 hop 간격 세그먼트를 잘라 [K, S, 31, 40] float16"""
    return np.stack([np.concatenate([dd._segments(mel[k, off[f]:off[f + 1]].astype(np.float32), hop)
                                     for f in files]).astype(np.float16) for k in range(mel.shape[0])])


def prepare(machine, mid, method, val_frac, seed, device, hop=None, aug=None):
    """hop을 주면 학습용 풀만 구간을 겹쳐 자른다. val·test는 항상 기본 분할이다.
    aug(dcase_augmented 경로)를 주면 학습 풀과 같은 순서의 겹침 증강 세그먼트 train_pool_aug [K, S, 31, 40]를
    함께 만든다(supervised만). val·test는 깨끗한 원본 그대로다."""
    rng = np.random.RandomState(seed)
    tgt = dd.load_unit(machine, mid, "train")
    val_files = rng.choice(np.unique(tgt["file_idx"]),
                           max(1, int(round(len(np.unique(tgt["file_idx"])) * val_frac))), replace=False)
    (tr_n, tr_nf), (va_n, _) = split_by_file_idx(tgt, val_files)
    if hop:
        tgt_h = dd.load_unit(machine, mid, "train", hop=hop)
        (tr_n, tr_nf), _ = split_by_file_idx(tgt_h, val_files)
    te = dd.load_unit(machine, mid, "test")
    te_seg, te_lab, te_file = te["seg"], te["label"].astype(int), te["file_idx"]
    keep = np.ones(len(te_seg), bool)
    h = hop or dd.SEG_FRAMES
    aug_pool = None
    if aug:
        assert method == "supervised", "겹침 증강은 supervised 학습만 지원"
        a = np.load(dd.aug_path(aug, dd.unit_name(machine, mid), "train.npz"))
        vset = set(val_files.tolist())
        aug_pool = [_aug_segments(a["mel"], a["off"], [f for f in np.unique(tgt["file_idx"]) if f not in vset], h)]
        assert aug_pool[0].shape[1] == len(tr_n)

    if method == "supervised":
        # 이상 파일을 학습 50% / 평가 50%로 나누고, 학습 쪽의 10%는 val로 뗀다
        anom_files = np.unique(te_file[te_lab == 1])
        rng.shuffle(anom_files)
        half = len(anom_files) // 2
        fit_files, eval_anom = anom_files[:half], anom_files[half:]
        n_val = max(1, int(round(len(fit_files) * val_frac)))
        src = dd.load_unit(machine, mid, "test", hop=hop) if hop else te
        fit_mask = np.isin(src["file_idx"], fit_files[n_val:])
        tr_o, tr_of = [src["seg"][fit_mask]], [src["file_idx"][fit_mask]]
        if aug:
            b = np.load(dd.aug_path(aug, dd.unit_name(machine, mid), "test.npz"))
            pos = {int(f): j for j, f in enumerate(b["fit_files"])}         # 이상 파일만 담겨 있음
            fo = np.concatenate([[0], np.cumsum(np.diff(b["fit_off"]))])
            fsel = sorted(int(f) for f in fit_files[n_val:])
            seg = [np.concatenate([dd._segments(b["fit"][k, fo[pos[f]]:fo[pos[f] + 1]].astype(np.float32), h)
                                   for f in fsel]).astype(np.float16) for k in range(b["fit"].shape[0])]
            aug_pool.append(np.stack(seg))
            assert aug_pool[1].shape[1] == len(tr_o[0])
        va_o = [te_seg[np.isin(te_file, fit_files[:n_val])]]
        keep = (te_lab == 0) | np.isin(te_file, eval_anom)
        te_seg, te_lab = te_seg[keep], te_lab[keep]
        _, te_file = np.unique(te_file[keep], return_inverse=True)
    else:
        tr_o, tr_of, va_o = [], [], []
        for oid in dd.MACHINE_IDS[machine]:
            o = dd.load_unit(machine, oid, "train")
            if oid == mid:
                continue
            vf = rng.choice(np.unique(o["file_idx"]),
                            max(1, int(round(len(np.unique(o["file_idx"])) * val_frac))), replace=False)
            (a, af), (b, _) = split_by_file_idx(o, vf)
            tr_o.append(a); tr_of.append(af + 100000 * int(oid)); va_o.append(b)

    T = lambda a: torch.tensor(np.asarray(a), dtype=torch.float32, device=device)
    return {
        "train_normal": T(tr_n), "val_normal": T(va_n),
        "train_normal_file": tr_nf,
        "train_other": T(np.concatenate(tr_o)), "val_other": T(np.concatenate(va_o)),
        "train_other_file": np.concatenate(tr_of),
        "test_seg": T(te_seg), "test_label": te_lab, "test_file": te_file,
        "bal_idx": balanced_idx(te_lab, rng),
        "test_keep": keep,                     # 전체 test 세그먼트(기본 분할) 중 평가에 쓰는 것
        **({"train_pool_aug": torch.tensor(np.concatenate(aug_pool, axis=1), dtype=torch.float16, device=device)}
           if aug else {}),
    }


def balanced_idx(y, rng):
    """정상과 이상 세그먼트 수를 맞춘 인덱스. F1을 선행 연구(균형 데이터)와 비교하기 위함."""
    n0, n1 = np.flatnonzero(y == 0), np.flatnonzero(y == 1)
    k = min(len(n0), len(n1))
    return np.sort(np.concatenate([rng.choice(n0, k, replace=False), rng.choice(n1, k, replace=False)]))


def group_by_file(file_idx):
    """파일 번호 배열 → 파일별 세그먼트 인덱스 목록"""
    order = np.argsort(file_idx, kind="stable")
    bounds = np.flatnonzero(np.diff(file_idx[order])) + 1
    return np.split(order, bounds)


def clip_batches(groups, data, method, batch_size, gen):
    """파일 단위 batch. 정상 파일 전체 + 같은 수의 이상 파일을 섞어 내보낸다."""
    g_norm, g_anom = groups
    dev = data["train_normal"].device
    n = len(g_norm)
    pick = np.random.default_rng(int(torch.randint(0, 2**31, (1,), generator=gen, device=dev).item()))
    sel = [(g_norm[i], 0) for i in range(n)] + \
          [(g_anom[i], 1) for i in pick.integers(0, len(g_anom), n)]
    pick.shuffle(sel)
    per_clip = max(1, int(np.median([len(s) for s, _ in sel])))
    n_clip = max(1, batch_size // per_clip)
    for s in range(0, len(sel), n_clip):
        chunk = sel[s:s + n_clip]
        idx, cid, y = [], [], []
        for j, (segs, lab) in enumerate(chunk):
            idx.append(segs); cid.append(np.full(len(segs), j)); y.append(lab)
        # 정상·이상 풀을 이어 붙인 텐서에서 한 번에 모은다(파일마다 복사하던 것과 순서·값 동일)
        off = len(data["train_normal"])
        gidx = np.concatenate([segs if lab == 0 else segs + off for segs, lab in chunk])
        gi = torch.as_tensor(gidx, device=dev)
        cid_t = torch.tensor(np.concatenate(cid), dtype=torch.long, device=dev)
        x = data["train_pool"][gi]
        if "train_pool_aug" in data:
            # 겹침 증강: 파일마다 확률 aug_p로 K가지 섞음 중 하나로 바꾼다(파일 안 세그먼트는 같은 섞음)
            A = data["train_pool_aug"]
            use = torch.rand(len(chunk), generator=gen, device=dev) < data["aug_p"]
            kk = torch.randint(0, A.shape[0], (len(chunk),), generator=gen, device=dev)
            m = use[cid_t]
            x[m] = A[kk[cid_t][m], gi[m]].float()
        yield x, torch.tensor(y, dtype=torch.long, device=dev), cid_t


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
    ap.add_argument("--clip_loss", action="store_true",
                    help="파일 단위 손실: 한 파일의 세그먼트 출력을 평균해 손실을 계산한다(추론과 같은 합치기)")
    ap.add_argument("--hop", type=int, default=None,
                    help="학습 구간을 겹쳐 자를 때의 frame 간격(예: 16). val·test는 겹치지 않는다")
    ap.add_argument("--val_frac", type=float, default=0.1)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out_dir", default=None, help="학습 기록(history.csv, args.json) 위치")
    ap.add_argument("--weight_dir", default=None, help="체크포인트(best_val.pth, last.pth) 위치")
    ap.add_argument("--layers", default=",".join(map(str, LAYER_SIZES)),
                    help="layer 크기(쉼표 구분). 기본 40,384,256,64,2. P3.6 모델 크기 검증용")
    ap.add_argument("--aug", default=None, help="겹침 증강 dataset 경로(software/dataset/dcase_augmented 또는 dcase_augmented_easy). clip_loss 필요")
    ap.add_argument("--aug_p", type=float, default=0.5, help="파일마다 섞은 버전으로 바꿀 확률")
    ap.add_argument("--bands", default=None,
                    help="mel 대역 lo:hi만 입력으로 쓴다(주파수 대역 고르기, 예: 13:40 = 중심 1 kHz 이상). 입력 layer 크기 = hi − lo")
    args = ap.parse_args(argv)
    if args.aug and not args.clip_loss:
        ap.error("--aug는 --clip_loss와 함께 쓴다")
    layer_sizes = tuple(int(v) for v in args.layers.split(","))
    if args.bands:
        b_lo, b_hi = (int(v) for v in args.bands.split(":"))
        layer_sizes = (b_hi - b_lo,) + layer_sizes[1:]

    name = dd.unit_name(args.machine, args.mid)
    tag = f"{args.method}_bs{args.batch_size}_{args.sched}_e{args.epochs}"
    out_dir = args.out_dir or os.path.join(dd.SOFTWARE_DIR, "train_result", "train_runs", name, tag)
    w_dir = args.weight_dir or os.path.join(dd.SOFTWARE_DIR, "weights", "train_runs", name, tag)
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(w_dir, exist_ok=True)
    with open(os.path.join(out_dir, "args.json"), "w") as f:
        json.dump(vars(args), f, indent=2)

    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    gen = torch.Generator(device=device).manual_seed(args.seed)

    data = prepare(args.machine, args.mid, args.method, args.val_frac, args.seed, device, args.hop, args.aug)
    data["aug_p"] = args.aug_p
    if args.bands:                             # 모든 입력(학습·증강·val·test)에서 같은 대역만 남긴다
        for k in ("train_normal", "val_normal", "train_other", "val_other", "test_seg", "train_pool_aug"):
            if k in data:
                data[k] = data[k][..., b_lo:b_hi].contiguous()
    n_norm = len(data["train_normal"])

    # 고정 val 세트: val 정상 + 같은 수의 학습용 이상(고정 seed로 1회 생성)
    vgen = torch.Generator(device=device).manual_seed(args.seed + 1)
    nv = len(data["val_normal"])
    val_x = torch.cat([data["val_normal"],
                       make_anomaly(args.method, data["val_normal"], data["val_other"], nv, vgen)])
    val_y = torch.cat([torch.zeros(nv), torch.ones(nv)]).long().to(device)

    aug_note = f" aug(p={args.aug_p}, K={len(data['train_pool_aug'])})" if args.aug else ""
    print(f"[{name}] method={args.method} bs={args.batch_size} epochs={args.epochs} sched={args.sched}"
          f"{' clip_loss' if args.clip_loss else ''}{f' hop={args.hop}' if args.hop else ''}{aug_note}")
    print(f"  train 정상 {n_norm} seg, 다른 ID 풀 {len(data['train_other'])} seg, "
          f"val {len(val_x)} seg, test {len(data['test_seg'])} seg")

    model = AnomalySNN(layer_sizes, default_betas(layer_sizes)).to(device)
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

    clip_groups = None
    if args.clip_loss:
        clip_groups = (group_by_file(data["train_normal_file"]), group_by_file(data["train_other_file"]))
        data["train_pool"] = torch.cat([data["train_normal"], data["train_other"]])
        print(f"  파일 단위 손실: 정상 {len(clip_groups[0])}파일, 이상 {len(clip_groups[1])}파일")

    best_val, best_metrics = float("inf"), None
    for epoch in range(1, args.epochs + 1):
        t0 = time.time()
        model.train()
        if args.clip_loss:
            batches = clip_batches(clip_groups, data, args.method, args.batch_size, gen)
        else:
            # 에포크마다 정상 전체 + 같은 수의 학습용 이상을 새로 생성
            anom = make_anomaly(args.method, data["train_normal"], data["train_other"], n_norm, gen)
            x_all = torch.cat([data["train_normal"], anom])
            y_all = torch.cat([torch.zeros(n_norm), torch.ones(n_norm)]).long().to(device)
            perm = torch.randperm(len(x_all), generator=gen, device=device)
            batches = ((x_all[perm[s:s + args.batch_size]], y_all[perm[s:s + args.batch_size]], None)
                       for s in range(0, len(perm), args.batch_size))

        tot_loss, tot_correct, tot_n = 0.0, 0, 0
        for x, y, clip_id in batches:
            x = spec_mask(x, gen, p=args.mask_p)
            _, mem, _ = model(x)
            logits = mem.mean(dim=1)[:, :N_CLASS]
            if clip_id is not None:
                # 파일 안 세그먼트 출력을 평균 → 파일 하나가 표본 하나 (파일 수 = len(y), GPU 대기 없음)
                logits = torch.zeros(len(y), N_CLASS, device=device).index_add_(
                    0, clip_id, logits) / torch.bincount(clip_id).unsqueeze(1)
            loss = loss_fn(logits, y)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            opt.step()
            tot_loss = tot_loss + loss.detach().double() * len(y)   # .item()을 스텝마다 부르지 않는다
            tot_correct = tot_correct + (logits.argmax(1) == y).sum()
            tot_n += len(y)
        tot_loss, tot_correct = float(tot_loss), int(tot_correct)

        lr = opt.param_groups[0]["lr"]
        if sched:
            sched.step()
        r = evaluate(model, data, val_x, val_y, loss_fn)
        r.update(epoch=epoch, lr=lr, train_loss=tot_loss / tot_n,
                 train_acc=tot_correct / tot_n, epoch_sec=time.time() - t0)
        log_w.writerow({k: (f"{v:.6f}" if isinstance(v, float) else v) for k, v in r.items()})
        log_f.flush()

        if r["val_loss"] < best_val:
            best_val, best_metrics = r["val_loss"], dict(r)
            torch.save({"epoch": epoch, "model_state_dict": model.state_dict(),
                        "args": vars(args), "metrics": r}, os.path.join(w_dir, "best_val.pth"))
        if epoch % 10 == 0 or epoch == 1:
            print(f"  ep {epoch:3d} | train {r['train_loss']:.4f}/{r['train_acc']:.3f} "
                  f"| val {r['val_loss']:.4f}/{r['val_acc']:.3f} auc {r['val_auc']:.3f} "
                  f"| test AUC {r['test_auc']:.3f} pAUC {r['test_pauc']:.3f} | {r['epoch_sec']:.1f}s",
                  flush=True)

    torch.save({"epoch": args.epochs, "model_state_dict": model.state_dict(), "args": vars(args)},
               os.path.join(w_dir, "last.pth"))
    log_f.close()
    print(f"  완료 → {out_dir}")
    return {"unit": name, "out_dir": out_dir, "weight_dir": w_dir, "best": best_metrics, "last": r}


if __name__ == "__main__":
    main()
