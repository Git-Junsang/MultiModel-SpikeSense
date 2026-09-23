# 개발 환경 기록 — Phase 0

작성일: 2026-09-23 | 개정: r3 | 관련 task: [TASKS.md](TASKS.md) P0.1~P0.4

이 문서는 2026-09-22에 실제로 명령을 실행해 확인한 값만 적는다. 버전이 바뀌면 다시 확인하고 개정 번호를 올린다.

## 1. 머신 구성

| 역할 | 호스트 | 접속 | 비고 |
|---|---|---|---|
| 개발·학습·합성 서버 | `Dev-Ubuntu` (Proxmox VM) | 로컬 | 저장소(NAS) 작업, Vivado 합성·시뮬레이션, 모델 학습 |
| FPGA Host PC | `sdsl-llm` | Tailscale `100.92.93.57:22`, 계정 `junsang` | 보드 JTAG(USB) 연결. 여러 사용자가 함께 쓰는 공용 호스트(접속자 8명 확인) |

접속 비밀번호는 저장소에 기록하지 않는다.

## 2. P0.1 개발·학습 서버 (`Dev-Ubuntu`)

| 항목 | 확인 값 | 확인 방법 |
|---|---|---|
| OS | Ubuntu 24.04.4 LTS, 커널 7.0.14-8-pve | `/etc/os-release`, `uname -a` |
| CPU / RAM | Intel Core i5-14600K, 12 vCPU / 16 GiB (+4 GiB swap) | `lscpu`, `nproc`, `free -g` |
| GPU | NVIDIA GeForce RTX 3090 Ti, 24,564 MiB | `nvidia-smi` |
| 드라이버 / CUDA | 드라이버 610.57.04, CUDA UMD 13.3. `nvcc`(CUDA Toolkit) 미설치 | `nvidia-smi`, `which nvcc` |
| PyTorch | 2.13.0+cu130, `torch.cuda.is_available() = True`, cuDNN 92000 | `python3 -c ...` |
| GPU 동작 확인 | 4096×4096 FP32 행렬곱 20회 정상 수행(약 17 TFLOPS), 여유 메모리 23.0 / 23.8 GiB | PyTorch 스크립트 |
| Python | 3.12.3 (`python3`) | `python3 --version` |
| 주요 패키지 | numpy 2.4.6, scipy 1.18.0, scikit-learn 1.9.0, librosa 0.11.0, soundfile 0.14.0, matplotlib 3.11.1. torchaudio 미설치 | `pip list` |
| 디스크 | `/` 246 GB 중 189 GB 여유 | `df -h` |
| NAS | `192.168.68.101:/volume1/data` → `/mnt/nas/data`, 7.0 TB 중 1.6 TB 여유 | `df -h` |

- **학습 GPU**: 이 서버의 RTX 3090 Ti를 쓴다. FPGA Host의 RTX 3090도 재부팅 후 쓸 수 있지만, 공용 호스트라 학습 기본값으로 두지 않는다.
- 처음 확인할 때 GPU 메모리 22,993 MiB가 사용 중이었다가 이후 365 MiB로 줄었다. 다른 VM이나 사용자가 GPU를 함께 쓰는 것으로 보이므로, 학습 시작 전에 `nvidia-smi`로 여유 메모리를 확인한다.

## 3. P0.2 툴체인

| 도구 | 버전·상태 | 확인 |
|---|---|---|
| Vivado | v2026.1 (SW Build 6511674), `/tools/Xilinx/2026.1` | `vivado -version` |
| 라이선스 | BASIC 라이선스, 2027-08-21 만료. `xc7a200t` 합성 라이선스 획득 확인 | 합성 로그 |
| 파트 | `xc7a200tfbg484-2` 지원 (XC7A200T-2FBG484I의 Vivado 파트명) | `get_parts` |
| xsim | `xvlog`·`xelab`·`xsim` 동작 | 카운터 testbench `PASS q=10` |
| Verilator | 5.020 | `verilator --lint-only -Wall` 통과 |
| iverilog / vvp | 사용하지 않음 | — |

검증 절차 (2026-09-22):

1. 8비트 카운터를 `synth_design -part xc7a200tfbg484-2`로 합성 → 성공
2. 같은 카운터의 testbench를 xsim으로 실행 → `PASS q=10`
3. `verilator --lint-only -Wall` → 경고 없음

**Vivado 실행 경로**: 개발 서버는 LXC 컨테이너라 원본 `/tools/Xilinx/2026.1/Vivado/bin/vivado`가 라이선스 확인 중 libudev 장치 스캔에서 `realloc(): invalid pointer`로 죽는다(2026-09-23 확인). `settings64.sh`를 source하지 말고 libudev를 LD_PRELOAD하는 래퍼 `/usr/local/bin/vivado`를 쓴다.

**공백 경로와 IP**: 저장소 경로의 공백(`중앙대학교 학부연구생`) 때문에 MIG가 `XML_INPUT_FILE`(prj)을 읽지 못한다(2026-09-23 확인). MIG·XDMA 시험 설계는 `~/mmss_build/<이름>`에서 빌드한다. Tcl에서 공백 경로를 `add_files`에 넘길 때는 `[list $f]`로 감싼다.

**한글 경로**: 선행 저장소(Windows, SMB)에서는 경로에 한글이 있으면 프로젝트 모드 `launch_runs` 합성이 크래시했다. 이 서버에서 한글이 들어간 저장소 경로에 프로젝트를 만들고 `launch_runs synth_1`을 돌렸을 때는 정상 완료됐다(합성만 확인). MIG·XDMA IP 생성에서 문제가 생기면 [create_project.tcl](../../hardware/vivado/create_project.tcl)의 `-proj_dir`로 ASCII 경로를 지정한다.

## 4. P0.3 보드 연결 (FPGA Host `sdsl-llm`)

| 항목 | 확인 값 |
|---|---|
| OS | Ubuntu 24.04.5 LTS, 커널 6.8.0-139-generic |
| CPU / RAM / 디스크 | Intel Xeon W-2255 (20 스레드) / 125 GiB / `/` 468 GB |
| GPU | RTX 3090, 24,576 MiB, 드라이버 595.91.07. 처음에는 커널 모듈(595.84)과 라이브러리(595.91) 버전이 달라 `nvidia-smi`가 실패했고, 2026-09-22 재부팅 후 정상 인식 |
| JTAG 케이블 | 보드 동봉 USB JTAG 다운로더. `0403:6014` FT232H, 제조사 문자열 `Digilent`, 시리얼 `210512180081`. Vivado에서 Digilent 케이블로 인식 |
| udev | `/etc/udev/rules.d/52-xilinx-digilent-usb.rules` 설치(Vivado 2026.1 동봉본) |
| JTAG 체인 | `xc7a200t_0`, IDCODE `0x13636093` 인식 |
| PCIe | 보드를 Host PCIe 슬롯에 장착, **슬롯 전원만 사용**(12 V 어댑터 없음). Host 전원이 꺼지면 FPGA 구성도 사라진다. 비트스트림을 올리기 전의 FPGA는 PCIe 장치로 열거되지 않으므로 `lspci`에는 아직 보이지 않는다 |

### FPGA Host Vivado 설치

| 항목 | 값 |
|---|---|
| 설치 파일 | `FPGAs_AdaptiveSoCs_Unified_SDI_2026.1_0616_1700.tar`(105,522,216,960 B). 압축 해제본을 `~/xilinx_install/`에 보관하고 tar는 삭제 |
| 설치 | 제품 Vivado, 디바이스 **Artix-7만**, `/tools/Xilinx/2026.1` (약 61 GB). 설정 파일 `~/xilinx_install/install_config.txt` |
| OS 패키지 | `Vivado/scripts/installLibs.sh`가 CRLF 줄바꿈이라 그대로는 실행되지 않는다. 줄바꿈을 고친 사본으로 실행했다. Ubuntu 24.04에 없는 `libtinfo5`·`libncurses5`·`libasound2` 3개는 설치되지 않았다 |
| 케이블 드라이버 | `data/xicom/cable_drivers/lin64/install_script/install_drivers/install_drivers` 실행, 성공 |
| 라이선스 | BASIC(`Vivado_Basic_Package`), 노드락 HOSTID `cc96e50a3ba4`(`eno1` MAC), 2027-09-22 만료. `/opt/xilinx-lic/Xilinx.lic`, `/etc/environment`에 `XILINXD_LICENSE_FILE` 설정. 2026-09-23 Host 로컬 JTAG로 `xc7a200t_0` 인식 확인. 구형 WebPACK 라이선스(`V_WebPACK`)로는 2026.1이 실행되지 않았다 |

### 작업 흐름 (2026-09-22 결정)

1. **합성·구현·비트스트림**: 개발 서버(Proxmox VM `Dev-Ubuntu`)에서 [create_project.tcl](../../hardware/vivado/create_project.tcl)로 만든다.
2. **전송**: `.bit`(필요하면 `.ltx`·`.mcs`)를 `scp`로 Host의 `~/fpga_work/`에 보낸다.
3. **다운로드·플래시·보드 시험**: Host의 Vivado Hardware Manager(로컬 JTAG)로 한다.

Host의 `hw_server`를 네트워크에 열어 두는 방식은 쓰지 않는다. `hw_server`는 JTAG 케이블을 다루는 Vivado 구성요소이며 파일 전송과는 관계가 없다. Host의 Vivado가 실행될 때 로컬에서 자동으로 띄운다.

### JTAG 인식 기록

2026-09-22, Host 라이선스가 없는 상태에서 Host의 `hw_server`를 Tailscale 주소로 띄우고 개발 서버의 Hardware Manager로 접속해 확인했다. 타깃 `xilinx_tcf/Digilent/210512180081`, 디바이스 `xc7a200t_0`, IDCODE `0x13636093`. 확인 후 원격 대기 `hw_server`는 종료했다.

처음에는 Host에 Vivado가 없어 개발 서버의 `hw_server`와 Digilent 라이브러리만 복사해 썼다. Vivado 래퍼(`loader`)가 설정하는 `DIGILENT_DATA_DIR`이 없으면 케이블이 보이지 않았다(`USBC::FInit() failed to get firmware image path`). 임시 파일은 정식 설치 뒤 지웠다.

## 5. P0.4 보드 제약과 프로젝트 스크립트

| 파일 | 내용 |
|---|---|
| [ax7a200b_base.xdc](../../hardware/constraints/ax7a200b_base.xdc) | 200 MHz 시스템 클럭(R4/T4, DIFF_SSTL15), CFGBVS·CONFIG_VOLTAGE, QSPI ×4 비트스트림 설정 |
| [ax7a200b_io.xdc](../../hardware/constraints/ax7a200b_io.xdc) | 코어보드 LED(W5, Active-High), 캐리어보드 LED1~4(Active-Low), RESET·KEY1~4(Active-Low), USB-UART |
| [ax7a200b_ddr3.xdc](../../hardware/constraints/ax7a200b_ddr3.xdc) | DDR3 32 bit 핀 전체(MIG 포트명). MIG 설정·결과 비교용 기준표 |
| [ax7a200b_pcie.xdc](../../hardware/constraints/ax7a200b_pcie.xdc) | PCIe 100 MHz 참조 클럭(F10/E10), 레인↔GTP 채널 대응, PERST# 미확인 |
| [create_project.tcl](../../hardware/vivado/create_project.tcl) | 프로젝트 생성·합성·구현·비트스트림 스크립트 |

프로젝트 생성 (저장소 루트에서):

```bash
vivado -mode batch -source hardware/vivado/create_project.tcl \
    -tclargs -name blink -top <탑모듈> -xdc base,io -run bit
```

생성 위치의 기본값은 `hardware/vivado/build/<이름>`이다. 이 폴더는 산출물이며 현재 `.gitignore`에 들어 있지 않다.

### 검증 (2026-09-22)

모든 XDC 포트를 쓰는 더미 탑(저장소 밖 스크래치 폴더)을 만들어 `-xdc base,io,ddr3,pcie -run bit`로 빌드했다.

- 합성·배치·배선·비트스트림 생성 완료. Critical Warning 0건, Error 0건
- DRC는 BUFC-1(입력 버퍼 미연결) 경고 9건뿐이며, 더미 설계가 일부 입력을 로직에 연결하지 않아서 생긴 것이다
- 배선이 끝난 설계에서 포트 87개의 `PACKAGE_PIN`을 읽어 XDC와 대조 → 불일치 0건
- 첫 빌드에서 DDR3 DQ/DQS에 `SSTL15_T_DCI`를 넣었다가 "파트가 지원하지 않는 I/O 표준" 경고가 났다. Artix-7은 HR 뱅크만 있어 DCI가 없으므로 `SSTL15`/`DIFF_SSTL15` + `IN_TERM UNTUNED_SPLIT_50`으로 고쳤다
- 이 비트스트림은 DDR3 핀을 임의로 구동하므로 보드에 올리지 않았다. 보드 동작은 P0.5 LED 점멸로 확인한다

이 검증은 핀 번호·I/O 표준·뱅크 전압이 디바이스 규칙에 맞는지를 확인한 것이다. 매뉴얼 표가 실제 보드 배선과 같은지는 P0.5(LED·버튼), P0.6(MIG), P0.7(PCIe)에서 보드로 확인한다.

### 매뉴얼로 확정하지 못한 항목

| 항목 | 상태 | 확인 시점 |
|---|---|---|
| PCIe PERST# 핀 | 매뉴얼 그림 3-4-1에 신호만 있고 핀 번호 없음 | P0.7 전. ALINX 예제 설계나 캐리어보드 회로도 필요 |
| 팬 제어(FAN_PWM) 핀 | BANK16이라는 것만 나오고 핀 번호 없음. Low일 때 팬이 돈다 | P0.5에서 미사용 핀 기본 풀다운 상태로 팬이 도는지 확인 |
| USB-UART 방향 | `UART1_RXD`(L14)/`UART1_TXD`(L15)가 FPGA 기준 이름인지 불명확 | UART를 처음 쓸 때 루프백으로 확인 |
| 보드 모델 표기 | 저장소 매뉴얼은 AX7A200 Rev 1.0(2019)이다. 실물 AX7A200B와 핀이 다르면 보드 시험에서 드러난다 | P0.5~P0.7 |
