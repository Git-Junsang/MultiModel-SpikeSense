"""소리 겹침 증강 데이터 생성 (MODEL_SIZE_PLAN §1.6).

대상 장비 녹음에 다른 장비들의 정상음을 **파형 단계에서** 더한 뒤, 기존과 같은 특징 추출
(dcase_data.mel_from_wave)을 거친다. 라벨은 대상 장비 기준 그대로다.

섞음 규칙 (결과를 보기 전에 정함)
  겹치는 장비 수      N ~ round(정규(4, 1.5)), 1~8
  그중 강한 겹침 수   K ~ round(정규(1.5, 0.5)), 1~2 (K ≤ N), 나머지는 약한 겹침
  겹침 수준(SNR, dB) = 10·log10(대상 전력 / 겹친 소리 전력), 녹음 전체 기준
                      강함 ~ 정규(0, 3), −9~9 / 약함 ~ 정규(15, 3), 6~24
  종류 ~ 균일(6종), ID ~ 균일(그 종류에서 대상 장비 제외), 녹음 ~ 균일(뱅크), 시작 위치 ~ 균일(원형 이동)
  겹치는 소리는 **정상음만** 쓴다(이상음을 섞으면 대상 라벨이 오염된다).
  배경 소음: 원본 녹음에 이미 들어 있다. 배경 소음만 따로 녹음한 파일은 없어, 약한 겹침 여러 대가 넓게 깔린
  배경 역할을 한다(합성 소음은 넣지 않음).

학습과 평가의 겹침 소리는 서로 다른 녹음이다.
  학습 뱅크 = 장비마다 train 폴더 정상 녹음 50개, 평가 뱅크 = 장비마다 test 폴더 정상 녹음 50개.

출력 software/data/dataset_augmented/
  bank_train.json, bank_test.json          뱅크 녹음 목록
  <장비>_train.npz  mel [K, ΣT, 40] float16, off [F+1]     train 폴더 파일(list_files 순서)마다 K가지 섞음
  <장비>_test.npz   fit [K, ΣT_a, 40], fit_files [A], fit_off [A+1]
                        test 이상 파일의 K가지 섞음(학습 뱅크) — supervised 학습에 쓰는 이상 파일용
                    eval [4, ΣT, 40], off [F+1]  test 전체 파일의 평가 조건(평가 뱅크)
                        T1 = 학습과 같은 분포, T2_p6 / T2_0 / T2_m6 = 강한 1대 SNR +6 / 0 / −6 dB + 약한 3대
  <장비>_recipes.jsonl                      섞음마다 사용한 소리·위치·SNR

    python3 overlap_aug.py --selftest
    python3 overlap_aug.py [--workers 11]
    python3 overlap_aug.py --samples slider_id00:normal_id_00_00000001.wav …   # 들어 볼 wav → dataset_augmented/samples/
"""
import argparse
import json
import os
import time
from multiprocessing import Pool

# 작업 프로세스 여러 개가 각자 스레드를 띄우면 CPU를 두고 다툰다(부하 100 이상 관측) → 프로세스당 1개
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMBA_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import numpy as np  # noqa: E402

import dcase_data as dd  # noqa: E402

OUT = os.path.join(dd.SOFTWARE_DIR, "data", "dataset_augmented")
SEED = 2026
K_TRAIN = 4                      # 학습용 녹음마다 만드는 섞음 수
BANK_PER_UNIT = 50
TYPES = list(dd.MACHINE_IDS)
N_TOTAL = (4.0, 1.5, 1, 8)       # 평균, 표준편차, 최소, 최대
N_STRONG = (1.5, 0.5, 1, 2)
SNR_STRONG = (0.0, 3.0, -9.0, 9.0)
SNR_WEAK = (15.0, 3.0, 6.0, 24.0)
# 난이도 설정. easy(2026-10-11, 결과 보기 전 결정): 강한 겹침을 MIMII의 가장 쉬운 조건(+6 dB)에 맞추고 약한 겹침도 3 dB 낮춤.
# 개수·종류·위치와 난수 순서는 같아서, 같은 소리가 같은 자리에 더 작게 섞인다(SNR = hard + 6 / + 3 dB, 범위만 다름).
PRESETS = {"hard": dict(SNR_STRONG=(0.0, 3.0, -9.0, 9.0), SNR_WEAK=(15.0, 3.0, 6.0, 24.0), sub=""),
           "easy": dict(SNR_STRONG=(6.0, 3.0, 0.0, 12.0), SNR_WEAK=(18.0, 3.0, 9.0, 27.0), sub="easy")}


def apply_preset(name):
    global SNR_STRONG, SNR_WEAK, OUT
    p = PRESETS[name]
    SNR_STRONG, SNR_WEAK = p["SNR_STRONG"], p["SNR_WEAK"]
    OUT = os.path.join(dd.SOFTWARE_DIR, "data", "dataset_augmented", p["sub"])
EVAL_CONDS = ["T1", "T2_p6", "T2_0", "T2_m6"]
T2_SNR = {"T2_p6": 6.0, "T2_0": 0.0, "T2_m6": -6.0}
UNITS_BY_TYPE = {t: [dd.unit_name(t, i) for i in ids] for t, ids in dd.MACHINE_IDS.items()}
BANK = {}                        # split → {장비: [파형, …]}, 작업 프로세스는 fork로 공유


def _normal(rng, mu, sd, lo, hi):
    return float(np.clip(rng.normal(mu, sd), lo, hi))


def _count(rng, mu, sd, lo, hi):
    return int(np.clip(np.rint(rng.normal(mu, sd)), lo, hi))


def sample_recipe(rng, target, cond="T1"):
    """대상 장비에 섞을 소리 목록 [(장비, 뱅크 번호, 시작 비율, SNR dB, 강함 여부)]"""
    if cond == "T1":
        n = _count(rng, *N_TOTAL)
        k = min(n, _count(rng, *N_STRONG))
        levels = [(_normal(rng, *SNR_STRONG), True) for _ in range(k)] + \
                 [(_normal(rng, *SNR_WEAK), False) for _ in range(n - k)]
    else:
        levels = [(T2_SNR[cond], True)] + [(_normal(rng, *SNR_WEAK), False) for _ in range(3)]
    out = []
    for snr, strong in levels:
        cands = [u for u in UNITS_BY_TYPE[TYPES[rng.integers(len(TYPES))]] if u != target]
        out.append((cands[rng.integers(len(cands))], int(rng.integers(BANK_PER_UNIT)),
                    float(rng.random()), round(snr, 3), strong))
    return out


def mix(s, recipe, bank):
    """대상 파형 s에 recipe의 소리를 SNR에 맞춘 배율로 더한다. 전력은 평균을 뺀 녹음 전체 기준"""
    ps = np.mean((s - s.mean()) ** 2)
    x = s.astype(np.float64).copy()
    for u, bi, start, snr, _ in recipe:
        n = bank[u][bi]
        n = np.resize(np.roll(n, int(start * len(n))), len(s))      # 길이가 다르면 반복해 맞춤
        n = n - n.mean()
        pn = np.mean(n ** 2)
        if pn > 0:
            x += np.sqrt(ps / (pn * 10 ** (snr / 10))) * n
    return x


def load_bank(split):
    """장비마다 정상 녹음 BANK_PER_UNIT개(고정 시드)를 메모리에 올린다"""
    names, waves = {}, {}
    for ui, (m, i) in enumerate(dd.UNITS):
        paths, labels = dd.list_files(m, i, split)
        normal = [p for p, l in zip(paths, labels) if l == 0]
        rng = np.random.default_rng([SEED, 99, ui, 0 if split == "train" else 1])
        pick = sorted(rng.choice(len(normal), BANK_PER_UNIT, replace=False))
        u = dd.unit_name(m, i)
        names[u] = [os.path.basename(normal[j]) for j in pick]
        waves[u] = [dd.read_wave(normal[j]).astype(np.float32) for j in pick]
    return names, waves


def _pack(mels):
    off = np.concatenate([[0], np.cumsum([len(m) for m in mels])]).astype(np.int64)
    return np.concatenate(mels).astype(np.float16), off


def build_unit(ui):
    m, i = dd.UNITS[ui]
    unit = dd.unit_name(m, i)
    names = {s: {u: BANK_NAMES[s][u] for u in BANK_NAMES[s]} for s in BANK_NAMES}
    recs = []

    def rec(split, fname, kind, r):
        recs.append({"split": split, "file": fname, "kind": kind,
                     "mix": [[u, names["train" if kind.startswith("fit") or split == "train" else "test"][u][bi],
                              st, snr, int(strong)] for u, bi, st, snr, strong in r]})

    # train 폴더: 파일마다 K가지 (학습 뱅크)
    paths, _ = dd.list_files(m, i, "train")
    mels = [[] for _ in range(K_TRAIN)]
    for f, p in enumerate(paths):
        s = dd.read_wave(p)
        for k in range(K_TRAIN):
            r = sample_recipe(np.random.default_rng([SEED, ui, 0, f, k]), unit)
            mels[k].append(dd.mel_from_wave(mix(s, r, BANK["train"])))
            rec("train", os.path.basename(p), f"k{k}", r)
    packed = [_pack(x) for x in mels]
    np.savez(os.path.join(OUT, f"{unit}_train.npz"), mel=np.stack([a for a, _ in packed]), off=packed[0][1])

    # test 폴더: 이상 파일은 학습용 K가지(학습 뱅크), 전체 파일은 평가 조건 4가지(평가 뱅크)
    paths, labels = dd.list_files(m, i, "test")
    fit = [[] for _ in range(K_TRAIN)]
    ev = [[] for _ in EVAL_CONDS]
    fit_files = []
    for f, (p, lab) in enumerate(zip(paths, labels)):
        s = dd.read_wave(p)
        if lab == 1:
            fit_files.append(f)
            for k in range(K_TRAIN):
                r = sample_recipe(np.random.default_rng([SEED, ui, 1, f, k]), unit)
                fit[k].append(dd.mel_from_wave(mix(s, r, BANK["train"])))
                rec("test", os.path.basename(p), f"fit_k{k}", r)
        for c, cond in enumerate(EVAL_CONDS):
            r = sample_recipe(np.random.default_rng([SEED, ui, 2, f, c]), unit, cond)
            ev[c].append(dd.mel_from_wave(mix(s, r, BANK["test"])))
            rec("test", os.path.basename(p), cond, r)
    fp = [_pack(x) for x in fit]
    ep = [_pack(x) for x in ev]
    np.savez(os.path.join(OUT, f"{unit}_test.npz"),
             fit=np.stack([a for a, _ in fp]), fit_off=fp[0][1], fit_files=np.asarray(fit_files, np.int32),
             eval=np.stack([a for a, _ in ep]), off=ep[0][1], conds=np.asarray(EVAL_CONDS))
    with open(os.path.join(OUT, f"{unit}_recipes.jsonl"), "w") as fo:
        for r in recs:
            fo.write(json.dumps(r, ensure_ascii=False) + "\n")
    return unit, len(paths), len(fit_files)


def selftest():
    ok = True

    def check(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print(f"{'PASS' if cond else 'FAIL'}  {name}")

    # 1. 섞을 소리가 없으면 기존 특징과 비트 단위로 같다
    p, _ = dd.list_files("valve", "00", "train")
    s = dd.read_wave(p[0])
    check("섞음 없음 = 기존 특징", np.array_equal(dd.mel_from_wave(mix(s, [], {})), dd.extract_mel(p[0])))
    # 2. 겹친 소리 1개의 실제 SNR이 지정값과 같다
    q, _ = dd.list_files("fan", "01", "train")
    n = dd.read_wave(q[0])
    for snr in (-6.0, 0.0, 15.0):
        x = mix(s, [("fan_id01", 0, 0.3, snr, True)], {"fan_id01": [n]})
        d = x - s
        meas = 10 * np.log10(np.mean((s - s.mean()) ** 2) / np.mean(d ** 2))
        check(f"SNR {snr:+.0f} dB → 측정 {meas:+.4f} dB", abs(meas - snr) < 1e-6)
    # 3. 분포: 강한 겹침 1~2개, 개수 평균 ≈ 4, 종류 균일, 대상 장비 제외
    rng = np.random.default_rng(0)
    rs = [sample_recipe(rng, "valve_id00") for _ in range(20000)]
    cnt = np.array([len(r) for r in rs])
    strong = np.array([sum(x[4] for x in r) for r in rs])
    typ = np.array([TYPES.index(x[0].split("_id")[0]) for r in rs for x in r])
    frac = np.bincount(typ, minlength=len(TYPES)) / len(typ)
    check(f"개수 평균 {cnt.mean():.2f} (목표 약 4), 범위 {cnt.min()}~{cnt.max()}", 3.8 < cnt.mean() < 4.2 and cnt.min() >= 1 and cnt.max() <= 8)
    check(f"강한 겹침 수 {sorted(set(strong.tolist()))}", set(strong.tolist()) <= {1, 2})
    check(f"종류 비율 {np.round(frac, 3).tolist()} (균일 0.167)", np.abs(frac - 1 / len(TYPES)).max() < 0.01)
    check("대상 장비 자신은 섞지 않음", all(x[0] != "valve_id00" for r in rs for x in r))
    t2 = sample_recipe(np.random.default_rng(1), "valve_id00", "T2_m6")
    check(f"T2_m6 = 강한 1대 −6 dB + 약한 3대: {[(x[3], x[4]) for x in t2]}",
          len(t2) == 4 and t2[0][3] == -6.0 and t2[0][4] and not any(x[4] for x in t2[1:]))
    return ok


def export_samples(specs):
    """recipes.jsonl의 기록대로 섞은 소리를 다시 만들어 wav로 쓴다. 대상 파일마다 원본, T1, T2 3가지, 강한 겹침만.
    같은 대상의 파일들은 같은 배율로 정규화해 상대 음량을 유지한다"""
    import soundfile as sf
    out = os.path.join(OUT, "samples")
    os.makedirs(out, exist_ok=True)
    notes = []
    for spec in specs:
        unit, fname = spec.split(":")
        machine, mid = unit.rsplit("_id", 1)
        split = "test"                        # 평가 조건(T1·T2) 기록은 test 파일에만 있다
        recs = {r["kind"]: r["mix"] for r in map(json.loads, open(os.path.join(OUT, f"{unit}_recipes.jsonl")))
                if r["file"] == fname and r["split"] == split}
        s = dd.read_wave(os.path.join(dd.DATA_DIR, machine, split, fname))
        waves = {"orig": s}
        for kind in EVAL_CONDS:
            mix_rec = recs[kind]
            bank = {}
            for u, bf, *_ in mix_rec:
                m2, _ = u.rsplit("_id", 1)
                bank.setdefault(u, []).append(dd.read_wave(os.path.join(dd.DATA_DIR, m2, "test", bf)))
            idx = {}
            rr = []
            for u, bf, st, snr, strong in mix_rec:
                rr.append((u, idx.get(u, 0), st, snr, strong))
                idx[u] = idx.get(u, 0) + 1
            waves[kind] = mix(s, rr, bank)
            if kind == "T2_0":
                waves["T2_0_strong_only"] = mix(s, rr[:1], bank) - s      # 강한 겹침 1대만(대상 제외)
            notes.append(f"{unit} {fname} [{kind}] " + ", ".join(
                f"{'강' if strong else '약'} {u} {snr:+.1f} dB" for u, _, _, snr, strong in mix_rec))
        g = 0.9 / max(np.abs(w).max() for w in waves.values())
        stem = f"{unit}__{fname[:-4]}"
        for kind, w in waves.items():
            sf.write(os.path.join(out, f"{stem}__{kind}.wav"), (w * g).astype(np.float32), dd.SR, subtype="PCM_16")
    with open(os.path.join(out, "README.txt"), "a") as fo:
        fo.write("\n".join(notes) + "\n")
    print("\n".join(notes))
    print(f"→ {out}")


BANK_NAMES = {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=11)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--samples", nargs="+", help="장비:test파일명. 섞음 기록대로 wav를 다시 만든다")
    ap.add_argument("--preset", choices=list(PRESETS), default="hard", help="easy → dataset_augmented/easy/")
    ap.add_argument("--units", nargs="+", help="이 장비만 만든다(예: valve_id00). 겹침 뱅크는 40대 전체")
    a = ap.parse_args()
    apply_preset(a.preset)
    if a.selftest:
        raise SystemExit(0 if selftest() else 1)
    if a.samples:
        return export_samples(a.samples)
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    for split in ("train", "test"):
        BANK_NAMES[split], BANK[split] = load_bank(split)
        with open(os.path.join(OUT, f"bank_{split}.json"), "w") as f:
            json.dump(BANK_NAMES[split], f, ensure_ascii=False, indent=1)
    print(f"뱅크 적재 {time.time() - t0:.0f} s", flush=True)
    order = sorted(range(len(dd.UNITS)), key=lambda u: -len(dd.list_files(*dd.UNITS[u], "test")[0]))
    if a.units:
        order = [u for u in order if dd.unit_name(*dd.UNITS[u]) in a.units]
    with Pool(a.workers) as p:
        for unit, nf, na in p.imap_unordered(build_unit, order):
            print(f"{time.strftime('%T')} {unit}: test {nf}파일(이상 {na})", flush=True)
    print(f"완료 {time.time() - t0:.0f} s → {OUT}")


if __name__ == "__main__":
    main()
