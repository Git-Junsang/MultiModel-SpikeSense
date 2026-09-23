"""DCASE 2020 Task2 데이터 목록·특징 추출·캐시.

모델 1개 = 장비 1대(기종 + ID). 전체 41대 중 slider id_06을 제외한 40대를 쓴다.
제외한 장비의 파일은 `data_dcase/unused/`로 옮겨 두었다.

특징은 선행 train.py와 같다: 16 kHz, n_fft 1024, hop 512(32 ms), 40 mel,
파일 단위 power_to_db(ref=max, top_db 80) → [0, 1] 정규화, 31프레임(992 ms) 세그먼트.
"""

import os
import csv
import numpy as np
import soundfile as sf
import librosa
from multiprocessing import Pool

SOFTWARE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(SOFTWARE_DIR, "data_dcase")
CACHE_DIR = os.path.join(SOFTWARE_DIR, "datasets", "cache_mel")

SR, N_FFT, HOP, N_MELS = 16000, 1024, 512, 40
SEG_FRAMES = 31          # 31 × 32 ms = 992 ms
TOP_DB = 80.0            # power_to_db 기본 top_db. 정규화 1.0 ≈ 80 dB 폭

MACHINE_IDS = {
    "fan":         ["00", "01", "02", "03", "04", "05", "06"],
    "pump":        ["00", "01", "02", "03", "04", "05", "06"],
    "slider":      ["00", "01", "02", "03", "04", "05"],        # id_06 제외(unused)
    "valve":       ["00", "01", "02", "03", "04", "05", "06"],
    "ToyCar":      ["01", "02", "03", "04", "05", "06", "07"],
    "ToyConveyor": ["01", "02", "03", "04", "05", "06"],
}
UNUSED = [("slider", "06")]
UNITS = [(m, i) for m, ids in MACHINE_IDS.items() for i in ids]   # 40대
assert len(UNITS) == 40


def unit_name(machine, mid):
    return f"{machine}_id{mid}"


def _wavs(folder, prefix):
    return sorted(f for f in os.listdir(folder)
                  if f.startswith(prefix) and f.endswith(".wav")
                  and os.path.isfile(os.path.join(folder, f)))


def _eval_labels():
    """eval_data_list.csv → {(machine, filename): label}. 평가용 ID의 test 라벨."""
    labels, machine = {}, None
    with open(os.path.join(DATA_DIR, "eval_data_list.csv")) as f:
        for row in csv.reader(f):
            if len(row) == 1:
                machine = row[0]
            elif len(row) == 3:
                labels[(machine, row[0])] = int(row[2])
    return labels


def list_files(machine, mid, split):
    """(경로 목록, 라벨 목록). train은 정상만(라벨 0), test는 정상 0 / 이상 1."""
    folder = os.path.join(DATA_DIR, machine, split)
    if split == "train":
        files = _wavs(folder, f"normal_id_{mid}_")
        return [os.path.join(folder, f) for f in files], [0] * len(files)

    # 개발용 ID: 파일명에 라벨, 평가용 ID: eval_data_list.csv
    paths, labels = [], []
    for prefix, lab in ((f"normal_id_{mid}_", 0), (f"anomaly_id_{mid}_", 1)):
        for f in _wavs(folder, prefix):
            paths.append(os.path.join(folder, f)); labels.append(lab)
    if not paths:
        table = _eval_labels()
        for f in _wavs(folder, f"id_{mid}_"):
            paths.append(os.path.join(folder, f)); labels.append(table[(machine, f)])
    return paths, labels


def extract_mel(path):
    """선행 extract_mel_spectrogram과 같은 처리. 반환 [frames, 40] float32, 범위 [0, 1]"""
    data, sr = sf.read(path)
    if data.ndim > 1:
        data = data[:, 0]
    if sr != SR:
        data = librosa.resample(data, orig_sr=sr, target_sr=SR)
    data = data - np.mean(data)
    S = librosa.feature.melspectrogram(y=data, sr=SR, n_fft=N_FFT, hop_length=HOP, n_mels=N_MELS)
    log_S = librosa.power_to_db(S, ref=np.max)
    log_S = log_S - np.min(log_S)
    mx = np.max(log_S)
    if mx > 1e-8:
        log_S = log_S / mx
    return log_S.T.astype(np.float32)


def _segments(mel):
    n = len(mel) // SEG_FRAMES
    return mel[:n * SEG_FRAMES].reshape(n, SEG_FRAMES, N_MELS)


def load_unit(machine, mid, split, workers=10):
    """장비 1대의 세그먼트 캐시를 읽거나 만든다.

    반환 dict: seg [S, 31, 40] float32, label [S], file_idx [S](파일 번호), files [F]
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache = os.path.join(CACHE_DIR, f"{machine}_id{mid}_{split}_seg{SEG_FRAMES}.npz")
    if os.path.exists(cache):
        d = np.load(cache)
        return {k: d[k] for k in d.files}

    paths, labels = list_files(machine, mid, split)
    with Pool(workers) as p:
        mels = p.map(extract_mel, paths, chunksize=16)
    segs, lab, fidx = [], [], []
    for i, (m, l) in enumerate(zip(mels, labels)):
        s = _segments(m)
        segs.append(s); lab += [l] * len(s); fidx += [i] * len(s)
    out = {
        "seg": np.concatenate(segs).astype(np.float32),
        "label": np.asarray(lab, dtype=np.int8),
        "file_idx": np.asarray(fidx, dtype=np.int32),
        "files": np.asarray([os.path.basename(p) for p in paths]),
    }
    np.savez(cache, **out)
    return out


if __name__ == "__main__":
    # 40대의 파일 수 확인 (특징 추출 없음)
    total = 0
    for m, i in UNITS:
        tr, _ = list_files(m, i, "train")
        te, tl = list_files(m, i, "test")
        total += 1
        print(f"{unit_name(m, i):18s} train {len(tr):4d} | test 정상 {tl.count(0):4d} 이상 {tl.count(1):4d}")
    print(f"장비 {total}대, 제외: {UNUSED}")
