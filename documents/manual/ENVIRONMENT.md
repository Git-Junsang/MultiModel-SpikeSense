# 개발 환경

비밀번호와 비밀키는 이 문서에 적지 않는다. 버전이 바뀌면 다시 확인한다.

## 1. 머신

| 역할 | Host | 용도 |
|---|---|---|
| 개발 서버 | `Dev-Ubuntu` | 저장소, 학습, Vivado build, simulation |
| FPGA Host | `sdsl-llm` (sub1, `sdsl-fpga`) | JTAG, Ethernet·PCIe, 보드 test, 메모리가 큰 Vivado build |
| 최종 Host | `sdsl-rpi` (라즈베리파이 5) | Host software 실행 |

FPGA Host는 공용 장비다. 재부팅과 system 설정 변경은 먼저 조율한다. 최종 Host는 라즈베리파이 5이고 sub1은 임시 Host다.

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
- MIG·XDMA가 있는 설계는 공백 없는 `~/mmss_build/<name>`에서 build한다. `hardware/testbench/run_*.sh`의 Verilator obj_dir도 여기에 둔다. 이 폴더가 없으면 Verilator가 쓰지 못하므로 지운 뒤에는 `mkdir -p ~/mmss_build`로 다시 만든다.
- IP가 여러 개면 `-jobs 1`을 쓴다. 16 GiB 환경에서 `-jobs 3`은 메모리 부족으로 실패했다.
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
| Vivado | 2026.1, Artix 7 설치 |
| PCIe slot | SLOT5, root port `00:1d.0`, 전기적 x4 |

보드 전원은 PCIe slot이나 DC 12 V 어댑터(매뉴얼 Part 3.15)로 넣는다. 2026-11-16에 QSPI에 `accel_top`(`hardware/vivado/build/top/accel_top.bit`, P5.2 최종)을 써서, 전원을 넣으면 가속기 설계로 부팅한다. `accel_top`은 PCIe를 쓰지 않으므로 보드를 slot에서 떼어 12 V 어댑터와 Ethernet만으로 쓸 수 있다. 전원을 다시 넣으면 DDR3의 모델 image는 사라지므로 `mmss_host setup`을 다시 한다.

Vivado는 `/tools/Xilinx/2026.1/Vivado`에 있고 PATH에 없다. `settings64.sh`를 먼저 읽는다. xsim은 있고 Verilator는 없다.

### 3.1 network

| 항목 | 값 |
|---|---|
| 외부 망 | USB Wi-Fi `wlan0`(TP-Link Archer TX10UB Nano, RTL8851BU), DHCP 192.168.0.183. 접속은 Tailscale `ssh sdsl-fpga` |
| Wi-Fi 설정 | `/etc/netplan/60-wifi.yaml`, `/etc/systemd/network/10-usb-wifi.link`(장치 이름 wlan0 고정), `/etc/udev/rules.d/99-usb-wifi-wpa.rules` |
| Wi-Fi driver | 커널 6.8에 없다. `~/rtw89`(morrownr) DKMS `rtw89/7.3`, 모듈 `rtw89_8851bu_git` |
| 보드 직결 | 내장 포트 `eno1`(Intel I219, e1000e). Host 192.168.10.1, FPGA 192.168.10.2. 2026-11-12부터 보드 Ethernet은 라즈베리파이 `eth0`(§4.1)에 연결했고 `eno1`은 LAN(192.168.0.200)에 있다 |
| 보드 PHY | MDIO 주소 1, ID 0x937C·0x4032(JL2101 계열). KSZ9031이 아니다 |

- 새 커널로 부팅하면 Wi-Fi driver가 없어 망이 끊길 수 있다. 사용자에게 랜선을 부탁해 들어간 뒤 `dkms status | grep rtw89`에 `uname -r`이 있는지 본다. 없으면 `sudo dkms autoinstall -k $(uname -r)`.
- netplan `50-cloud-init.yaml`에 eno1 = 192.168.0.200/24와 기본 경로(metric 0)가 남아 있다. 보드 링크가 올라오면 이 경로가 wlan0(metric 600)보다 앞서 인터넷과 Tailscale이 끊길 수 있다. 보드를 쓰기 전에 `/run/systemd/network/05-fpga-eno1.network`(Address=192.168.10.1/24, 경로 없음, ConfigureWithoutCarrier=yes)를 넣고 `networkctl reload && networkctl reconfigure eno1`을 실행한다. 재부팅하면 사라진다. netplan 영구 수정은 사용자 확인 뒤에만 한다.
- JTAG로 PCIe 설계를 program하기 전에 옛 PCIe 장치(`lspci -d 10ee:`)를 sysfs remove로 뗀다. 2026-11-16부터 QSPI에는 PCIe가 없는 `accel_top`이 있다.
- eno1은 1 Gb/s에서 링크가 50 µs 넘게 조용하면 절전에 들어가 결과 frame을 100만 개당 약 8개 잃는다. 손실 0이 필요하면 Host가 작은 UDP를 계속 보내거나(BG=1) 100 Mb/s로 쓴다. e1000e는 ethtool master-slave 설정과 MII 쓰기를 지원하지 않는다. 자세한 것은 [P5.3 결과 손실 보고서](<../reports/P5.3 Result Loss Research Report.md>)에 있다.

## 4. 최종 Host

| 항목 | 값 |
|---|---|
| 보드 | Raspberry Pi 5 Model B Rev 1.1 |
| OS / 커널 | Debian 13 (trixie) / 6.18.50+rpt-rpi-2712 |
| CPU / RAM | Cortex-A76 4코어 2.4 GHz / 7.9 GiB |
| 저장 장치 | microSD 29 GiB |
| Python / gcc | 3.13.5 / 14.2.0 |

### 4.1 network

| 항목 | 값 |
|---|---|
| 외부 망 | 내장 Wi-Fi `wlan0`. NetworkManager 자동 연결 순서는 iPhone 핫스팟 `iphone0`·`iphone1`(150, SSID 따옴표 `’`·`'` 두 가지) → `SDSL5G`(100). 둘 다 끊겨도 계속 다시 시도하고 Wi-Fi 절전을 껐다. `Smart-CAU`·`Smart-CAU_2.4G`(802.1X PEAP)는 MSCHAPv2까지 통과한 뒤 실패해(서버 PEAP 버전 1, 원인 미확인) 자동 연결을 껐다. sub1과 다른 망 |
| Tailscale | 1.104.6, 100.83.81.11. 접속은 `ssh sdsl-rpi`(키 인증) |
| 보드 직결 | `eth0`(macb, 1000 Mb/s, EEE 비활성, 수신 interrupt coalescing 49 µs, interrupt는 CPU 0). Pi 192.168.10.1, FPGA 192.168.10.2 |

`eth0`는 NetworkManager profile `netplan-eth0`에 고정 주소 192.168.10.1/24(gateway 없음)를 저장했다(2026-11-16). 재부팅해도 남는다. NetworkManager 설정을 바꾸려면 sudo가 필요하다. 측정용으로 tcpdump와 ethtool(`/usr/sbin/ethtool`)을 설치했다(2026-11-12). sudo는 비밀번호를 묻는다.

계정은 sub1과 같다. sub1과 다른 망이라 접속은 Tailscale(`ssh sdsl-rpi`)로만 한다.

### 4.2 오디오

| 항목 | 값 |
|---|---|
| USB mic | Generalplus MUSIC-BOOST USB Microphone(`1b3f:2019`) 2개. USB full speed, 서로 다른 USB bus |
| ALSA 장치 | `hw:CARD=Microphone`, `hw:CARD=Microphone_1`(card 번호는 바뀔 수 있다) |
| 형식 | S16_LE mono, 44.1·48 kHz만. 16 kHz는 지원하지 않는다 |
| 소리 출력 | 내장은 HDMI뿐이다. demo 스피커(2026-11-16)는 Bluetooth 2대: Anker PowerConf(`90:BF:D9:64:44:13`, `Microphone` 옆, 트랙 0)와 ABKO BSL110(`DE:0D:A5:2C:78:37`, `Microphone_1` 옆, 트랙 1). PipeWire 출력 음량 1.0. BSL110을 먼저 연결해야 둘 다 붙는다(A2DP 통로가 하나라 나중에 붙는 Anker는 통화용 HFP·mSBC 16 kHz로 붙는다). USB 겸용 스피커(JMTek `0c76:1607`)는 데이터는 가는데 소리가 나지 않았다 |
| clock | 시각은 systemd-timesyncd로 NTP 동기. 두 mic는 Pi clock보다 약 59 ppm 느리다([P3.16 보고서](<../reports/P3.16 Research Report.md>) §3.7) |

PortAudio(`libportaudio2`)와 ALSA 개발 header는 없다. 측정은 `libasound.so.2`를 ctypes로 직접 연다(`hardware/board_test/host/p316_alsa_rec.py`). `mmss_host run --mic Microphone,Microphone_1`은 ALSA 커널 interface(`/dev/snd/pcmC<card>D0c`)를 ioctl로 열어 libasound 없이 정적 링크로 돈다.

## 5. 작업 흐름

1. 개발 서버 또는 sub1에서 synthesis, implementation, bitstream 생성을 한다. 개발 서버는 14 GiB를 모든 세션이 나눠 쓰므로 메모리가 큰 build는 sub1에서 한다. sub1에서는 보드 시험 중에 build하지 않는다.
2. `.bit`, 필요하면 `.ltx`·`.mcs`를 Host `~/fpga_work/`로 보낸다.
3. Host의 local JTAG로 FPGA를 program한다.
4. PCIe test는 Host에서 한다.

network `hw_server`는 상시 열어 두지 않는다.

## 6. 보드 제약

| 파일 | 내용 |
|---|---|
| `ax7a200b_base.xdc` | 200 MHz system clock, config |
| `ax7a200b_io.xdc` | LED, key, reset, UART |
| `ax7a200b_ddr3.xdc` | DDR3 32 bit pin |
| `ax7a200b_pcie.xdc` | PCIe clock, lane, PERST# |

dummy top을 모든 XDC와 함께 배치했다. 87개 port의 `PACKAGE_PIN`이 XDC와 모두 같았다. DDR3 DQ/DQS는 Artix 7 HR bank에 맞춰 `SSTL15`와 `DIFF_SSTL15`를 쓴다.

PCIe PERST#는 보드 시험으로 L16을 찾았다. fan control pin과 UART 방향은 아직 확인하지 않았다.

project 생성 예:

```bash
vivado -mode batch -source hardware/vivado/create_project.tcl \
  -tclargs -name blink -top <top> -xdc base,io -run bit
```

## 7. 보드 시험 결과

### 7.1 LED·clock

| 항목 | 결과 |
|---|---|
| xsim / lint | PASS / warning 0 |
| 계산값 | `sum(i², 1..1000) = 0x13E5E51C`, 일치 |
| clock | JTAG counter로 약 200 MHz 확인 |
| LED logic | VIO 값 순환 확인 |

보드를 직접 보지 못해 물리 LED와 key 배선은 확인하지 않았다.

### 7.2 DDR3 MIG

| 항목 | 결과 |
|---|---|
| 구성 | MT41J256M16 ×2, 1 GiB, 800 MT/s, AXI 256 bit |
| calibration | `init_calib_complete = 1` |
| P1.6 test | 360초, compare error 0 |
| P3.1 full test | 1 GiB 전체, error 0 |

P1.6은 앞 16 MiB만 검사했다. P3.1에서 전체 범위를 다시 검사했다.

### 7.3 PCIe XDMA

| 항목 | 결과 |
|---|---|
| PERST# | L16 |
| link | 5 GT/s ×2 |
| device | `10ee:7022` |
| DMA | 64 KiB 왕복 10/10 일치 |
| driver | Xilinx XDMA 2025.2.0 |

FPGA는 Host boot 전에 구성돼야 BIOS가 안정적으로 열거한다. QSPI boot를 기본으로 쓴다.

## 8. P3 측정 설계 교체

`hardware/board_test/host/p3_load.sh` 순서:

1. XDMA driver를 내린다.
2. PCI device를 remove한다.
3. JTAG로 새 bitstream을 올린다.
4. PCI bus를 rescan한다.
5. 5 GT/s ×2를 확인한다.
6. XDMA driver를 다시 올린다.

Bitstream은 reboot 없이 교체할 수 있다. QSPI에는 `accel_top`이 있으므로(2026-11-16, 그 전에는 P1.7) reboot하면 `accel_top`으로 돌아간다. P3 측정 설계를 다시 쓰려면 이 순서로 JTAG로 올린다.

XDMA interrupt mode는 정상이다. `poll_mode=1`은 첫 H2C에서 timeout이 나므로 쓰지 않는다.

## 9. 관련 문서

- [P1.1~P1.4 보고서](<../reports/P1.1~1.4 Research Report.md>)
- [P1.5~P1.7 보고서](<../reports/P1.5~1.7 Research Report.md>)
- [P3.1~P3.4 보고서](<../reports/P3.1~3.4 Research Report.md>)
