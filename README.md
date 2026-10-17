# MultiModel-SpikeSense

**FPGA 하나로 SNN 모델 40개와 마이크 트랙 1,024개를 처리하는 다중 모델 실시간 추론 가속기**

---

## 1. 배경

회전 기계는 고장 전에 이상음을 낸다. 같은 기종이라도 장비와 설치 환경에 따라 정상 소리가 달라서 장비마다 SNN 모델을 따로 둔다. 이 연구는 모델 40개와 마이크 트랙 1,024개를 FPGA 하나로 처리한다. 트랙마다 32 ms에 추론 요청이 하나 생기고 Host는 frame 마지막 샘플을 수음한 시점부터 32 ms 안에 결과를 받아야 한다.

병목은 연산이 아니라 weight 전송이다. 모델 40개의 weight는 4.97 MiB라 BRAM(약 1.6 MiB)에 다 들어가지 않는다. weight를 재사용하지 않으면 DDR3에 4.17 GB/s가 필요해 보드의 읽기 대역폭 3.015 GB/s를 넘는다.

| 기법 | 하는 일 |
|---|---|
| Model-Grouped Offset Assignment | Host가 같은 모델을 쓰는 트랙에 같은 frame offset을 배정한다. 같은 모델의 요청이 FPGA에 함께 도착한다 |
| Grouping | FPGA가 추가 요청을 기다리지 않고 이미 도착한 같은 모델 요청을 batch로 묶는다 |
| offset-order weight cache | jitter로 나뉘어 온 요청을 entry 4개의 cache가 받아 낸다. 다음 사용 순서는 offset에서 얻는다 |
| 12 bit membrane storage | 남는 BRAM에 768트랙의 membrane potential을 12 bit로 둔다 |

---

## 2. 시스템 구성

![시스템 구조: Host의 offset 배정 → Gigabit Ethernet → FPGA의 request table, Grouping scheduler, weight cache, compute array, membrane bank → DDR3](analysis/figure/architecture/fig1_x-dataflow_y-block.png)

| 구성 | 역할 |
|---|---|
| Host (PC) | 특징 추출(mel 40개), offset 배정, 판정 |
| Gigabit Ethernet (UDP) | 추론 요청 64 B, 결과 32 B |
| FPGA (ALINX AX7A200B, XC7A200T) | request table, Grouping scheduler, DMA, weight cache entry 4개, membrane bank, 64-lane compute array |
| DDR3 1 GiB | 모델 40개의 weight, 256트랙의 membrane potential |

---

## 3. 모델과 가속기

### 3.1 모델: PLIF SNN

- 입력: 16 kHz 음성, FFT 1,024, hop 512에서 구한 mel 40개. frame은 64 ms이고 32 ms마다 하나씩 만든다
- 구조: `40→384→256→64→2`, 뉴런 706개, bias 없음. DCASE 2020 Task 2의 장비 ID 40개마다 한 모델
- 뉴런: PLIF. 뉴런마다 누설 계수와 threshold를 학습한다
- 판정: 31 frame(992 ms)의 출력 membrane potential 평균 중 큰 쪽(0 정상, 1 이상)
- 정수화: weight는 layer별 대칭 INT8(130,176 B), 누설 계수는 Q0.8. membrane potential은 16 bit 포화 연산, 저장은 12 bit
- 학습: focal loss, Adam(lr 0.002, cosine), batch 512, 60 epoch

| 형식 | 평균 ROC-AUC (40대) | AUC 0.9 이상 |
|---|---:|---:|
| FP32 | 0.9563 | 35대 |
| INT8, membrane potential 12 bit 저장 | 0.9554 | 35대 |

### 3.2 가속기

| 항목 | 값 |
|---|---|
| compute array | 64 lane output-stationary, 100 MHz 목표. layer 2·3은 spike 0 건너뛰기, cycle마다 spike input 2개 |
| 추론 1번 | 평균 676 cycle(6.8 µs), dense 2,237 cycle(22.4 µs). 제어 비용 203 cycle(가정) 포함 |
| BRAM 365 tile | weight cache entry 4개 116 tile, membrane potential 768트랙 199 tile, 링크·buffer 50 tile |
| weight 적재 | 모델 전체 131,648 B, 43.9 µs |
| deadline 보장 | worst case FPGA 처리 약 25 ms. 외부 지연에 약 7 ms가 남는다 |

RTL은 아직 없다. 숫자는 계산과 simulation이며 RTL과 보드로 확인해야 한다.

### 3.3 Simulation 결과

1,024트랙, 외부 지연 0, 같은 BRAM에서 비교했다. 보드 실측이 아니다.

| 방법 | DDR3 KiB/추론 | DDR3 MB/s | 평균 응답 시간 ms | 최대 응답 시간 ms |
|---|---:|---:|---:|---:|
| Dysta Method | 56.84 | 1,515 | 1.61 | 7.19 |
| DeepRT Method | 11.26 | 300 | 7.84 | 17.37 |
| 제안 | 6.36 | 169 | 0.18 | 1.08 |

세 방법 모두 deadline miss가 없었다. 비교군은 원 논문의 정책을 같은 FPGA 모델로 옮긴 것이다. 다른 실험은 [08_EVALUATION.md](documents/design_references/08_EVALUATION.md)에 있다.

---

## 4. 폴더 구조

```
MultiModel-SpikeSense/
├── documents/          # 설계 정본(design_references), 보고서, TASKS, 발표·논문 자료
├── software/
│   ├── dataset/        # DCASE data(git 제외)와 전처리·증강 code
│   ├── model/          # SNN 정의, 학습, FP32·INT8 reference, export, 평가(eval/)
│   ├── weights/        # checkpoint: <학습 이름>/<장비>/
│   └── train_result/   # 학습 기록과 평가 결과
├── simulation/
│   ├── engine/         # simulator(engine.py 한 파일)와 test_engine.py
│   ├── environment/    # 환경 파일. 파일 하나 = 실험 하나
│   └── result/         # 결과 CSV. 이름 = 환경 파일 이름
├── analysis/
│   ├── develop/        # 그림 code: <주제>/<그림 이름>.py
│   ├── figure/         # 그림: <주제>/<그림 이름>.png
│   └── discards/       # 값이 기준과 다르거나 폐기한 그림
└── hardware/
    ├── board_test/     # LED·MIG·XDMA 시험, DDR3·PCIe 측정 설계와 결과
    ├── data/           # INT8 모델 image, golden vector
    ├── src/, testbench/  # 가속기 RTL 작업 공간(비어 있음)
    └── constraints/, vivado/
```

### software

| 대상 | 규칙 |
|---|---|
| 장비 이름 | `<종류>_id<번호>`. 예: `fan_id01`, `ToyCar_id03` |
| import하는 모듈 | `<대상>_<구분>`: `snn_torch`(PyTorch 학습), `snn_fp32`, `snn_int8`, `model_format_v1`, `model_format_v2` |
| 실행 script | `<동사>_<대상>`: `train_unit`, `train_all`, `export_models`, `export_golden`, `verify_export`, `verify_reference` |
| `model/eval/` | 결과 폴더 `train_result/eval/<이름>/`과 같은 이름 |
| `model/references/` | 선행 저장소 code 사본. 고치지 않는다 |

학습 이름은 `<크기>_<용도>_<학습방법>`이다. 크기는 `XS`·`P`·`S`·`M`·`L`·`XL`(layer 구조는 `snn_torch.py`의 `ARCHS`), 용도는 `normal`·`mixed`(섞인 소리), 학습방법은 `noaug`·`aug`(겹침 증강)다.

| 학습 이름 | 장비 | 내용 | 옛 위치 |
|---|---:|---|---|
| `L_normal_noaug` | 40 | 지금 export한 모델(P2.4) | `model_weights/<장비>` |
| `XS`·`P`·`S`·`M_normal_noaug` | 40 | P3.6 크기 비교, 미채택 | `model_weights/_sweep/{XS,P,S,M}` |
| `XL_normal_noaug` | 40 | P3.6 크기 비교 | `model_weights/_sweep/XL` |
| `L_mixed_aug` | 40 | 겹침 증강 학습. 다음 export 후보 | `model_weights/_sweep/L_aug` |
| `XL_mixed_aug` | 40 | 겹침 증강 학습, P3.10 export | `model_weights/_sweep/XL_aug` |
| `L_mixed_aug-easy`, `-b300`, `-b1k`, `-b2k` | 6 | 쉬운 겹침 증강, mel 입력 대역 실험 | `model_weights/_sweep/L_aug_easy`, `L_easy_*` |

2026-10-15 이전 결과 파일에는 옛 이름과 경로가 남아 있다. 위 표로 옮겨 읽는다.

### simulation

| 대상 | 규칙 | 예 |
|---|---|---|
| 환경 파일 | `<결과 접두사>_<실험>.toml`. 접두사는 `p` + 작업 번호(+ 모델·lane) | `p321_compare.toml` |
| 점별 결과 | `<환경 이름>.csv`. 점마다 환경 값 전부, BRAM tile, 요약 지표 | `p321_compare.csv` |
| 실행별 결과 | `<환경 이름>_runs.csv.gz`. run은 점 × 시나리오 × seed마다 한 줄 | `p321_compare_runs.csv.gz` |

키 설명은 `environment/template.toml`, 열 이름은 `engine.py` 첫머리에 있다. 환경 파일을 고치면 결과 CSV를 다시 만든다. 결과 CSV만 따로 고치지 않는다. 옛 스크립트와 결과의 차이는 [P3.14 보고서](<documents/reports/P3.14 Research Report.md>)에 있다.

### analysis

그림 하나를 스크립트 하나가 그린다. 그림 이름은 `fig<번호>_x-<x축>_y-<y축>`이고 색으로 값을 보이면 `_c-<값>`을 붙인다. 주제는 그 실험으로 보려던 것이다. 원자료는 스크립트 첫머리에 적는다. 논문 그림은 `common.paper_style()`(영문 세리프 7 pt, 단 폭 3.5 in)로 그리고 `.pdf`도 만든다.

| 주제 | 그림 | 내용 | 원자료 |
|---|---|---|---|
| `accuracy` | `fig1_x-unit_y-auc` | 장비 40대의 파일 단위 ROC-AUC | `train_result/L_normal_noaug/results.csv` |
| `training` | `fig1_x-epoch_y-auc` | epoch별 test AUC, 40대 | `train_result/L_normal_noaug/<장비>/history.csv` |
| `membrane` | `fig1_x-layer_y-membrane-peak` | layer별 membrane potential 최대 \|값\|과 INT16 한계 | `train_result/eval/scores/membrane_headroom.csv` |
| `membrane` | `fig2_x-bits_y-auc` | layer별 membrane potential 저장 bit와 최저 ΔAUC | `train_result/eval/membrane_layer_bits/` |
| `membrane` | `fig3_x-layout_y-dma` | DDR3 membrane potential 배치별 DMA 횟수 | `p317_mem_place` |
| `normalization` | `fig1_x-method_y-auc` | 실시간 특징 정규화 방법별 ΔAUC | `train_result/eval/realtime_norm/results.csv` |
| `architecture` | `fig1_x-dataflow_y-block` | 시스템 구조도(논문 Fig. 1) | 없음 |
| `offset` | `fig2_x-jitter_y-latency-ddr` | 편중 배정에서 offset 간격별 응답 시간·DDR3 전송량 | `p317_offset_width` |
| `offset` | `fig5_x-time_y-track` | offset 배정 개념도(논문 Fig. 2) | 없음 |
| `arrival` | `fig1_x-ddr-latency_y-pattern` | 도착 패턴 7개(membrane potential 16 bit 전부 DDR3) | `p313_arrival` |
| `entry` | `fig1_x-entry_y-jitter_c-ddr` | entry 수 × membrane potential bit × jitter의 DDR3 전송량 | `p313_tradeoff` |
| `entry` | `fig2_x-entry_y-ddr` | 12 bit와 layer별 [9, 9, 9, 12] bit의 entry별 DDR3 전송량 | `p319_layer_bits` |
| `jitter` | `fig2_x-jitter_y-ddr` | jitter 0.8~32 ms × entry 수의 DDR3 전송량 | `p317_jitter_wide` |
| `gather` | `fig1_x-wait_y-ddr-latency` | offset 단위 모아 보내기 대기 D × jitter (entry 2) | `p317_gather` |
| `compare` | `fig1`~`fig8` | 방법 비교: 시나리오, DDR3 전송량·응답 시간, jitter, 트랙 수, DDR3 대역폭, 최대 트랙 수 | `p321_*` |
| `compare` | `fig9_x-ddr_y-latency` | DDR3 전송량과 평균 응답 시간(논문 Fig. 3) | `p321_compare`, `p321_compare_offset` |
| `compare` | `fig10_x-jitter_y-ddr` | jitter와 cache별 DDR3 전송량(논문 Fig. 4) | `p321_compare_jitter`, `p317_jitter_wide` |
| `compare` | `fig11_x-bw-tracks_y-latency` | DDR3 대역폭·트랙 수별 최대 응답 시간(논문 Fig. 5) | `p321_compare_ddrbw`, `p321_scale_run` |

시뮬레이션 원자료는 `simulation/result/<이름>.csv`, 모델 원자료는 `software/` 아래에 있다. 논문 그림의 사본은 `documents/papers/journal/image/DAC2027_draft/`에 논문 그림 번호로 둔다.

`discards/`의 스크립트는 그대로 돌지 않는다. 다시 쓰려면 `develop/`·`figure/`로 옮긴다.

### hardware

| 폴더 | 내용 |
|---|---|
| `board_test/` | LED·MIG·XDMA 시험과 DDR3·PCIe 측정. 원자료와 요약은 `p3_meas/result/`, 분석은 `host/analyze_p3.py` |
| `data/models_l64/`, `data/golden_l64/` | L INT8 모델 40개(slot v2, 64 lane)와 golden 82개. RTL 기준 |
| `data/models/`, `data/golden/` | slot v1(32 lane) |
| `data/models_xl/`, `data/golden_xl/` | `XL_mixed_aug`, slot v2 256 lane(모델 비교용) |

---

## 5. 시작하기

### 요구 사항

Ubuntu 24.04, Python 3.12, PyTorch 2.13(CUDA), Vivado 2026.1(xsim), Verilator 5.020. 세부는 [ENVIRONMENT.md](documents/manual/ENVIRONMENT.md)에 있다.

```bash
pip install torch numpy librosa soundfile scikit-learn matplotlib
```

### 데이터

[DCASE 2020 Task 2](https://dcase.community/challenge2020/task2-unsupervised-detection-of-anomalous-sounds)의 wav를 `software/dataset/dcase/<종류>/{train,test}/`에 둔다. mel cache와 증강 data는 `dataset/dcase_data.py`, `dataset/overlap_aug.py`가 만든다.

### 학습과 export

```bash
cd software/model
python3 train_all.py --name L_normal_noaug                     # 40대 학습
python3 export_models.py --format l64                           # INT8 모델과 DDR3 image
python3 export_golden.py --format l64                           # golden vector
python3 verify_export.py --format l64                           # export 검증
```

### Simulation

```bash
python3 simulation/engine/engine.py simulation/environment/p321_compare.toml --jobs 11
python3 simulation/engine/test_engine.py                        # 손계산·환경 파일·CSV 확인
```

오래 걸리는 실험은 계산 서버로 나눠 돌린다([COMPUTE_SERVERS.md](documents/manual/COMPUTE_SERVERS.md)).

### 그림

```bash
python3 analysis/develop/compare/fig9_x-ddr_y-latency.py
```

---

## 6. 개발 현황

| Phase | 내용 | 상태 |
|---|---|---|
| 1. 개발 환경과 보드 | 서버, Vivado, JTAG, MIG DDR3, PCIe XDMA 시험 | 완료 |
| 2. 모델 | 40모델 학습, INT8, export, golden | 완료. checkpoint 교체와 실시간 정규화 남음 |
| 3. 설계 검증 | DDR3 실측, architecture simulation, 비교군 비교, 외부 지연 | 대부분 완료. Host jitter 측정, Ethernet interface 설계 남음 |
| 4. RTL | compute array, membrane bank, weight cache, DMA, scheduler, Ethernet | 예정 |
| 5. 보드 통합 | synthesis·P&R, board test, end-to-end | 예정 |
| 6. 평가와 논문 | 비교 실험, simulation과 보드 대조, 전력 | 예정 |

작업별 상태는 [TASKS.md](documents/TASKS.md)에 있다.

---

## 7. 문서

| 문서 | 내용 |
|---|---|
| [design_references](documents/design_references/01_OVERVIEW.md) | 설계 정본. 기준 수치, 용어, 모델, 구조, 메모리, scheduling, Host interface, simulation, 평가, 선행연구 |
| [TASKS.md](documents/TASKS.md) | 진행 상황과 다음 작업 |
| [보고서](documents/reports/) | 단계별 실험과 결과 |
| [ENVIRONMENT.md](documents/manual/ENVIRONMENT.md) | 개발 서버, FPGA Host, 보드 시험 절차 |
| [COMPUTE_SERVERS.md](documents/manual/COMPUTE_SERVERS.md) | 계산 서버 사용법 |
| [STYLE_GUIDE.md](documents/STYLE_GUIDE.md) | 문서 형식과 문체 |

---

## 8. 참고 자료

- [DCASE 2020 Task 2](https://dcase.community/challenge2020/task2-unsupervised-detection-of-anomalous-sounds): Unsupervised Detection of Anomalous Sounds for Machine Condition Monitoring
- [PLIF](https://arxiv.org/abs/2011.09226): Incorporating Learnable Membrane Time Constant to Enhance Learning of Spiking Neural Networks
- [Sparse-DySta](https://doi.org/10.1145/3613424.3614263): Sparsity-Aware Dynamic and Static Scheduling for Sparse Multi-DNN Workloads (MICRO 2023)
- [DeepRT](https://doi.org/10.1145/3453142.3491278): A Soft Real Time Scheduler for Computer Vision Applications on the Edge (SEC 2021)
- 선행 프로젝트 [SpikeSense-Edge](https://github.com/Git-Junsang/SpikeSense-Edge): 단일 모델 SNN 이상음 탐지 FPGA
