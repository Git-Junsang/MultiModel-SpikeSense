"""SNN 학습 루프.

체크포인트에 모델 가중치, best_f1, 옵티마이저·스케줄러 상태, 에포크를 함께 저장한다.
Resume 시 이전 최고 점수를 기억해 덮어쓰기를 막고, 가중치만 든 구버전 .pth는
로드 후 초기 평가로 best_f1을 복원한다.
"""

import os
import csv
import argparse
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    confusion_matrix,
    classification_report,
)
import librosa
import soundfile as sf

from snn_model import AnomalySNN

# Focal Loss

class FocalLoss(nn.Module):
    def __init__(self, weight=None, gamma=2.0):
        super(FocalLoss, self).__init__()
        self.gamma = gamma
        self.weight = weight

    def forward(self, inputs, targets):
        log_pt = nn.functional.log_softmax(inputs, dim=1)
        pt = torch.exp(log_pt)
        
        log_pt = log_pt.gather(1, targets.view(-1, 1)).view(-1)
        pt = pt.gather(1, targets.view(-1, 1)).view(-1)

        if self.weight is not None:
            at = self.weight.gather(0, targets)
            log_pt = log_pt * at

        loss = -1 * (1 - pt) ** self.gamma * log_pt
        return loss.mean()

# 전처리 및 Dataset

def extract_mel_spectrogram(filepath, sr=16000, n_mels=40, n_fft=1024, hop_length=512):
    data, file_sr = sf.read(filepath)
    if data.ndim > 1: data = data[:, 0]
    if file_sr != sr: data = librosa.resample(data, orig_sr=file_sr, target_sr=sr)
        
    data = data - np.mean(data)
    S = librosa.feature.melspectrogram(y=data, sr=sr, n_fft=n_fft, hop_length=hop_length, n_mels=n_mels)
    log_S = librosa.power_to_db(S, ref=np.max)
    log_S = log_S - np.min(log_S)
    
    max_val = np.max(log_S)
    if max_val > 1e-8: log_S = log_S / max_val
    return log_S.T.astype(np.float32)

def segment_features(mel_frames, segment_frames=31):
    segments = []
    for start in range(0, len(mel_frames) - segment_frames + 1, segment_frames):
        segments.append(mel_frames[start : start + segment_frames])
    return segments

class MelDataset(Dataset):
    def __init__(self, segments, labels, is_train=False):
        self.data = segments
        self.labels = labels
        self.is_train = is_train

    def __len__(self):
        return len(self.data)

    def __getitem__(self, idx):
        x = self.data[idx].copy()
        if self.is_train:
            if np.random.rand() < 0.5:
                freq_mask_param = int(x.shape[1] * 0.15)
                f0 = np.random.randint(0, x.shape[1] - freq_mask_param)
                x[:, f0 : f0 + freq_mask_param] = 0.0
            if np.random.rand() < 0.5:
                time_mask_param = int(x.shape[0] * 0.15)
                t0 = np.random.randint(0, x.shape[0] - time_mask_param)
                x[t0 : t0 + time_mask_param, :] = 0.0
        return torch.tensor(x, dtype=torch.float32), torch.tensor(int(self.labels[idx]), dtype=torch.long)

def load_mimii_data(data_dir, n_mels=40, segment_frames=31):
    cache_file = os.path.join(data_dir, f"cache_mel_{n_mels}mels_seg{segment_frames}.npz")
    if os.path.exists(cache_file):
        loaded = np.load(cache_file)
        return loaded['segments'], loaded['labels']

    all_segments, all_labels = [], []
    for label_names, label_value in [(["normal"], 0), (["anomaly", "abnormal"], 1)]:
        folder = next((os.path.join(data_dir, name) for name in label_names if os.path.exists(os.path.join(data_dir, name))), None)
        if folder is None: continue
        wav_files = sorted([f for f in os.listdir(folder) if f.endswith(".wav")])
        for i, fname in enumerate(wav_files):
            mel_frames = extract_mel_spectrogram(os.path.join(folder, fname), n_mels=n_mels)
            for seg in segment_features(mel_frames, segment_frames):
                all_segments.append(seg)
                all_labels.append(label_value)

    all_segments = np.array(all_segments, dtype=np.float32)
    all_labels = np.array(all_labels, dtype=np.int8)
    np.savez_compressed(cache_file, segments=all_segments, labels=all_labels)
    return all_segments, all_labels

# 학습 루프

def train_one_epoch(model, dataloader, optimizer, loss_fn, device, mixup_alpha=0.2):
    model.train()
    total_loss, all_preds, all_targets = 0.0, [], []
    
    for mel_input, targets in dataloader:
        mel_input, targets = mel_input.to(device), targets.to(device)
        optimizer.zero_grad()

        if np.random.rand() < 0.5:
            lam = np.random.beta(mixup_alpha, mixup_alpha)
            rand_index = torch.randperm(mel_input.size()[0]).to(device)
            
            mixed_input = lam * mel_input + (1 - lam) * mel_input[rand_index]
            targets_a, targets_b = targets, targets[rand_index]
            
            _, output_mem, _ = model(mixed_input)
            mem_mean = output_mem.mean(dim=1)
            
            loss = lam * loss_fn(mem_mean, targets_a) + (1 - lam) * loss_fn(mem_mean, targets_b)
        else:
            _, output_mem, _ = model(mel_input)
            mem_mean = output_mem.mean(dim=1)
            loss = loss_fn(mem_mean, targets)

        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
        optimizer.step()
        
        total_loss += loss.item()
        
        preds = mem_mean.argmax(dim=1)
        all_preds.extend(preds.cpu().numpy())
        all_targets.extend(targets.cpu().numpy())
        
    return total_loss / len(dataloader), accuracy_score(all_targets, all_preds)

def evaluate(model, dataloader, loss_fn, device):
    model.eval()
    total_loss, all_preds, all_targets = 0.0, [], []
    with torch.no_grad():
        for mel_input, targets in dataloader:
            mel_input, targets = mel_input.to(device), targets.to(device)
            _, output_mem, _ = model(mel_input)
            mem_mean = output_mem.mean(dim=1)
            loss = loss_fn(mem_mean, targets)
            
            total_loss += loss.item()
            preds = mem_mean.argmax(dim=1)
            all_preds.extend(preds.cpu().numpy())
            all_targets.extend(targets.cpu().numpy())
            
    f1 = f1_score(all_targets, all_preds, average="binary", zero_division=0)
    return total_loss / len(dataloader), accuracy_score(all_targets, all_preds), f1

# 메인 실행부

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data_dir", type=str, required=True)
    parser.add_argument("--model_name", type=str, default="best_model.pth")
    parser.add_argument("--epochs", type=int, default=150)
    parser.add_argument("--batch_size", type=int, default=256)
    parser.add_argument("--lr", type=float, default=0.002)
    parser.add_argument("--n_mels", type=int, default=40)
    parser.add_argument("--segment_ms", type=int, default=992)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--log_csv", type=str, default=None,
                        help="에포크별 학습곡선 기록 CSV 경로 (기본: <model_name>_history.csv)")
    args = parser.parse_args()

    # 학습 곡선 로그 경로 (미지정 시 모델명 기반)
    log_csv = args.log_csv or (os.path.splitext(args.model_name)[0] + "_history.csv")

    # 고정 seed — train/test split 재현 + evaluate_dcase.py에서 동일 held-out 사용
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    segment_frames = int(args.segment_ms / ((512 / 16000) * 1000))
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    segments, labels = load_mimii_data(args.data_dir, n_mels=args.n_mels, segment_frames=segment_frames)
    indices = np.random.permutation(len(segments))
    n_train = int(len(segments) * 0.8)
    test_indices = indices[n_train:]

    train_loader = DataLoader(MelDataset(segments[indices[:n_train]], labels[indices[:n_train]], is_train=True), batch_size=args.batch_size, shuffle=True, num_workers=4)
    test_loader = DataLoader(MelDataset(segments[indices[n_train:]], labels[indices[n_train:]], is_train=False), batch_size=args.batch_size, shuffle=False, num_workers=4)

    model = AnomalySNN(n_input=args.n_mels).to(device)
    
    n_train_normal = int((labels[indices[:n_train]] == 0).sum())
    n_train_anomaly = int((labels[indices[:n_train]] == 1).sum())
    class_weights = None
    if n_train_normal > 0 and n_train_anomaly > 0:
        class_weights = torch.tensor([n_train / (2.0 * n_train_normal), n_train / (2.0 * n_train_anomaly)], dtype=torch.float32).to(device)

    loss_fn = FocalLoss(weight=class_weights, gamma=2.0)
    optimizer = optim.Adam(model.parameters(), lr=args.lr, weight_decay=1e-5)
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)

    best_f1 = -1.0
    start_epoch = 1

    # Resume 처리
    if args.resume and os.path.exists(args.model_name):
        checkpoint = torch.load(args.model_name)

        # 신버전 체크포인트 형식
        if isinstance(checkpoint, dict) and 'model_state_dict' in checkpoint:
            model.load_state_dict(checkpoint['model_state_dict'])
            optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
            scheduler.load_state_dict(checkpoint['scheduler_state_dict'])
            best_f1 = checkpoint['best_f1']
            start_epoch = checkpoint['epoch'] + 1
            print(f"  📂 체크포인트 로드 완료: 이전 최고 F1 {best_f1:.4f}, 에포크 {start_epoch}부터 시작합니다.")
        
        # 구버전(가중치만 저장) 호환 처리
        else:
            model.load_state_dict(checkpoint)
            print(f"  📂 구버전 가중치 로드 완료. 정확한 최고 기록 보존을 위해 초기 평가를 진행합니다...")
            _, _, initial_f1 = evaluate(model, test_loader, loss_fn, device)
            best_f1 = initial_f1
            print(f"     -> 복원된 초기 최고 F1: {best_f1:.4f}")

    # 학습 곡선 CSV — resume면 이어쓰기, 새 학습이면 헤더부터
    append_log = args.resume and start_epoch > 1 and os.path.exists(log_csv)
    log_f = open(log_csv, "a" if append_log else "w", newline="")
    log_writer = csv.writer(log_f)
    if not append_log:
        log_writer.writerow(["epoch", "lr", "train_loss", "train_acc",
                             "test_loss", "test_acc", "test_f1"])
    print(f"  📈 학습 곡선 기록: {log_csv} ({'append' if append_log else 'new'})")

    print("=" * 60)
    print(f"  SNN 학습 루프 시작")
    print("=" * 60)

    for epoch in range(start_epoch, args.epochs + 1):
        train_loss, train_acc = train_one_epoch(model, train_loader, optimizer, loss_fn, device)
        test_loss, test_acc, test_f1 = evaluate(model, test_loader, loss_fn, device)

        cur_lr = optimizer.param_groups[0]['lr']
        log_writer.writerow([epoch, f"{cur_lr:.6f}", f"{train_loss:.6f}", f"{train_acc:.6f}",
                             f"{test_loss:.6f}", f"{test_acc:.6f}", f"{test_f1:.6f}"])
        log_f.flush()

        if epoch % 5 == 0 or test_f1 > best_f1:
            print(f"📘 에포크 {epoch:3d} | Train Acc: {train_acc:.2%} | Test Acc: {test_acc:.2%} | F1: {test_f1:.4f} | LR: {cur_lr:.6f}")

        # 체크포인트로 묶어서 저장
        if test_f1 > best_f1:
            best_f1 = test_f1
            checkpoint = {
                'epoch': epoch,
                'model_state_dict': model.state_dict(),
                'optimizer_state_dict': optimizer.state_dict(),
                'scheduler_state_dict': scheduler.state_dict(),
                'best_f1': best_f1,
                # held-out 재현용 split 메타 (evaluate_dcase.py가 사용)
                'split_seed': args.seed,
                'segment_frames': segment_frames,
                'n_mels': args.n_mels,
                'test_indices': test_indices,
            }
            torch.save(checkpoint, args.model_name)

        scheduler.step()

    log_f.close()
    print(f"  ✅ 학습 종료 — 곡선 CSV: {log_csv}")

if __name__ == "__main__":
    main()
