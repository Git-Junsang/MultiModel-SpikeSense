#!/usr/bin/env bash
# ============================================================
# p3_load.sh — JTAG로 bitstream을 올리고 PCIe 장치를 다시 붙인 뒤 XDMA 드라이버 적재 (FPGA Host)
# ============================================================
# Host를 재부팅하지 않고 설계를 바꾸는 절차다(QSPI 기록 + 재부팅은 flash_qspi.tcl).
#   1. xdma 드라이버를 내리고 10ee 장치를 PCI 트리에서 제거
#   2. program_fpga.tcl로 JTAG 다운로드
#   3. PCI 재스캔. 링크가 5 GT/s 미만이면 루트 포트에서 링크 재학습(Retrain Link)
#   4. xdma.ko 적재 (POLL=1이면 poll_mode=1)
# 사용: ./p3_load.sh <file.bit> [file.ltx]
#   환경 변수: DRV(xdma.ko 경로), POLL(0/1), RP(루트 포트 BDF, 기본 0000:00:1d.0), VIVADO
# ============================================================
set -euo pipefail
BIT=${1:?비트스트림 경로}
LTX=${2:-}
DRV=${DRV:-$HOME/dma_ip_drivers/XDMA/linux-kernel/xdma/xdma.ko}
POLL=${POLL:-0}
RP=${RP:-0000:00:1d.0}
VIVADO=${VIVADO:-/tools/Xilinx/2026.1/Vivado/bin/vivado}
HERE=$(cd "$(dirname "$0")" && pwd)

echo "== 1. 드라이버·장치 제거"
sudo rmmod xdma 2>/dev/null || true
for d in $(lspci -D -d 10ee: | awk '{print $1}'); do
    echo "remove $d"
    echo 1 | sudo tee "/sys/bus/pci/devices/$d/remove" > /dev/null
done

echo "== 2. JTAG 다운로드"
"$VIVADO" -mode batch -nojournal -nolog -source "$HERE/program_fpga.tcl" \
    -tclargs -bit "$BIT" ${LTX:+-ltx "$LTX"} | grep -E "INFO: (다운로드|DONE)|ERROR" || true
sleep 1

echo "== 3. PCI 재스캔"
echo 1 | sudo tee /sys/bus/pci/rescan > /dev/null
sleep 1
BDF=$(lspci -D -d 10ee: | awk 'NR==1{print $1}')
[ -n "$BDF" ] || { echo "FAIL: 재스캔 후 10ee 장치 없음"; exit 1; }
speed() { sudo lspci -s "$1" -vv | sed -n 's/.*LnkSta:\s*Speed \([0-9.]*\)GT\/s.*Width x\([0-9]*\).*/\1 x\2/p'; }
echo "장치 $BDF, 링크 $(speed "$BDF")"
if [ "$(speed "$BDF" | cut -d' ' -f1)" != "5" ]; then
    echo "링크 재학습 (루트 포트 $RP)"
    v=$(sudo setpci -s "$RP" CAP_EXP+0x10.w)
    sudo setpci -s "$RP" CAP_EXP+0x10.w=$(printf '%04x' $(( 0x$v | 0x20 )))
    sleep 1
    echo "링크 $(speed "$BDF")"
fi
sudo lspci -s "$BDF" -vv | grep -E "Region|LnkSta:"

echo "== 4. xdma.ko 적재 (poll_mode=$POLL)"
sudo insmod "$DRV" poll_mode="$POLL"
sleep 1
ls /dev/xdma0_* 2>/dev/null || { echo "FAIL: /dev/xdma0_* 없음"; sudo dmesg | tail -20; exit 1; }
echo "OK"
