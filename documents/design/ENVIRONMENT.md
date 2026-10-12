# 개발 환경

비밀번호와 비밀키는 이 문서에 적지 않는다. 버전이 바뀌면 다시 확인한다.

## 1. 머신

| 역할 | Host | 용도 |
|---|---|---|
| 개발 서버 | `Dev-Ubuntu` | 저장소, 학습, Vivado build, simulation |
| FPGA Host | `sdsl-llm` | JTAG, PCIe, board test |

FPGA Host는 공용 장비다. 재부팅과 system 설정 변경은 먼저 조율한다.

## 2. 개발 서버

| 항목 | 값 |
|---|---|
| OS | Ubuntu 24.04.4 LTS |
| CPU / RAM | Intel Core i5-14600K, 12 vCPU / 16 GiB, swap 4 GiB |
| GPU | RTX 3090 Ti, 24,564 MiB |
| Driver / CUDA | 610.57.04 / CUDA UMD 13.3, `nvcc` 없음 |
| Python / PyTorch | 3.12.3 / 2.13.0+cu130 |
| FPGA tool | Vivado 2026.1, xsim, Verilator 5.020 |
| NAS | `/mnt/nas/data` |

PyTorch CUDA와 4096×4096 FP32 matrix multiply를 확인했다. 학습 전에는 `nvidia-smi`로 다른 사용자의 GPU 점유를 확인한다.

### Vivado 주의점

- `/usr/local/bin/vivado` wrapper를 쓴다. 원본 실행 파일은 이 환경에서 libudev 오류가 났다.
- MIG·XDMA가 있는 설계는 공백 없는 `~/mmss_build/<name>`에서 build한다.
- IP가 여러 개면 `-jobs 1`을 쓴다. 16 GiB 환경에서 `-jobs 3`은 memory 부족으로 실패했다.
- RTL simulation은 `xvlog`, `xelab`, `xsim`을 쓴다. `iverilog`, `vvp`는 쓰지 않는다.

tool 확인 결과:

| 확인 | 결과 |
|---|---|
| `xc7a200tfbg484-2` synthesis | 통과 |
| xsim counter testbench | `PASS q=10` |
| Verilator `--lint-only -Wall` | warning 0 |

## 3. FPGA Host

| 항목 | 값 |
|---|---|
| OS | Ubuntu 24.04.5 LTS |
| CPU / RAM | Xeon W-2255 / 125 GiB |
| GPU | RTX 3090, 24,576 MiB |
| JTAG | FT232H, Digilent, `xc7a200t_0` 인식 |
| FPGA IDCODE | `0x13636093` |
| Vivado | 2026.1, Artix-7 설치 |
| PCIe slot | SLOT5, root port `00:1d.0`, 전기적 x4 |

보드는 PCIe slot 전원만 쓴다. Host 전원이 꺼지면 FPGA 구성도 사라진다.

## 4. 작업 흐름

1. 개발 서버에서 synthesis, implementation, bitstream 생성을 한다.
2. `.bit`, 필요하면 `.ltx`·`.mcs`를 Host `~/fpga_work/`로 보낸다.
3. Host의 local JTAG로 FPGA를 program한다.
4. PCIe test는 Host에서 한다.

network `hw_server`는 상시 열어 두지 않는다.

## 5. 보드 제약

| 파일 | 내용 |
|---|---|
| `ax7a200b_base.xdc` | 200 MHz system clock, config |
| `ax7a200b_io.xdc` | LED, key, reset, UART |
| `ax7a200b_ddr3.xdc` | DDR3 32 bit pin |
| `ax7a200b_pcie.xdc` | PCIe clock, lane, PERST# |

dummy top을 모든 XDC와 함께 배치했다. 87개 port의 `PACKAGE_PIN`이 XDC와 모두 같았다. DDR3 DQ/DQS는 Artix-7 HR bank에 맞춰 `SSTL15`와 `DIFF_SSTL15`를 쓴다.

PCIe PERST#는 보드 시험으로 L16을 찾았다. fan control pin과 UART 방향은 아직 확인하지 않았다.

project 생성 예:

```bash
vivado -mode batch -source hardware/vivado/create_project.tcl \
  -tclargs -name blink -top <top> -xdc base,io -run bit
```

## 6. 보드 시험 결과

### 6.1 LED·clock

| 항목 | 결과 |
|---|---|
| xsim / lint | PASS / warning 0 |
| 계산값 | `sum(i², 1..1000) = 0x13E5E51C`, 일치 |
| clock | JTAG counter로 약 200 MHz 확인 |
| LED logic | VIO 값 순환 확인 |

보드를 직접 보지 못해 물리 LED와 key 배선은 확인하지 않았다.

### 6.2 DDR3 MIG

| 항목 | 결과 |
|---|---|
| 구성 | MT41J256M16 ×2, 1 GiB, 800 MT/s, AXI 256 bit |
| calibration | `init_calib_complete = 1` |
| P1.6 test | 360초, compare error 0 |
| P3.1 full test | 1 GiB 전체, error 0 |

P1.6은 앞 16 MiB만 검사했다. P3.1에서 전체 범위를 다시 검사했다.

### 6.3 PCIe XDMA

| 항목 | 결과 |
|---|---|
| PERST# | L16 |
| link | 5 GT/s ×2 |
| device | `10ee:7022` |
| DMA | 64 KiB 왕복 10/10 일치 |
| driver | Xilinx XDMA 2025.2.0 |

FPGA는 Host boot 전에 구성돼야 BIOS가 안정적으로 열거한다. QSPI boot를 기본으로 쓴다.

## 7. P3 측정 설계 교체

`hardware/board_test/host/p3_load.sh` 순서:

1. XDMA driver를 내린다.
2. PCI device를 remove한다.
3. JTAG로 새 bitstream을 올린다.
4. PCI bus를 rescan한다.
5. 5 GT/s ×2를 확인한다.
6. XDMA driver를 다시 올린다.

Bitstream은 reboot 없이 교체할 수 있다. QSPI에는 P1.7 설계가 있으므로 reboot하면 P1.7로 돌아간다.

XDMA interrupt mode는 정상이다. `poll_mode=1`은 첫 H2C에서 timeout이 나므로 쓰지 않는다.

## 8. 관련 문서

- [P1.1~P1.4 보고서](<../reports/P1.1~1.4 Research Report.md>)
- [P1.5~P1.7 보고서](<../reports/P1.5~1.7 Research Report.md>)
- [P3.1~P3.4 보고서](<../reports/P3.1~3.4 Research Report.md>)
