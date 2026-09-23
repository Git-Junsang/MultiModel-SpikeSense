#!/usr/bin/env bash
# ============================================================
# xdma_roundtrip.sh — P0.7 PCIe 링크 확인과 XDMA 데이터 왕복 시험 (FPGA Host)
# ============================================================
# 전제:
#   - p07_top 비트스트림이 올라가 있고 Host가 장치를 열거했다
#     (JTAG 다운로드 후 PCI 재스캔, 또는 QSPI 플래시 후 Host 재부팅).
#   - Xilinx dma_ip_drivers의 XDMA 드라이버(xdma.ko)가 적재되어 /dev/xdma0_h2c_0,
#     /dev/xdma0_c2h_0이 있다. 도구 dma_to_device·dma_from_device 경로를 TOOLS로 준다.
#
# 사용: TOOLS=~/dma_ip_drivers/XDMA/linux-kernel/tools ./xdma_roundtrip.sh [크기 B] [반복]
#   크기 기본 65536(BRAM 64 KiB 전체), 반복 기본 10.
# 판정: lspci 링크 폭·속도 출력, 매 반복 cmp 일치 여부. 하나라도 다르면 종료 코드 1.
# ============================================================
set -euo pipefail

SIZE=${1:-65536}
ITER=${2:-10}
TOOLS=${TOOLS:-$HOME/dma_ip_drivers/XDMA/linux-kernel/tools}
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

echo "== lspci (Xilinx 10ee)"
BDF=$(lspci -d 10ee: -D | awk 'NR==1{print $1}')
if [ -z "$BDF" ]; then
    echo "FAIL: 10ee 장치가 없다"; exit 1
fi
lspci -s "$BDF" -nn
sudo lspci -s "$BDF" -vv | grep -E "LnkCap:|LnkSta:" || true

for dev in /dev/xdma0_h2c_0 /dev/xdma0_c2h_0; do
    [ -e "$dev" ] || { echo "FAIL: $dev 없음 (xdma.ko 적재 확인)"; exit 1; }
done

fail=0
for i in $(seq 1 "$ITER"); do
    head -c "$SIZE" /dev/urandom > "$WORK/tx.bin"
    sudo "$TOOLS/dma_to_device"   -d /dev/xdma0_h2c_0 -a 0 -s "$SIZE" -c 1 -f "$WORK/tx.bin" > "$WORK/h2c.log"
    sudo "$TOOLS/dma_from_device" -d /dev/xdma0_c2h_0 -a 0 -s "$SIZE" -c 1 -f "$WORK/rx.bin" > "$WORK/c2h.log"
    if cmp -s "$WORK/tx.bin" "$WORK/rx.bin"; then
        echo "iter $i: PASS ($SIZE B)"
    else
        echo "iter $i: FAIL ($(cmp -l "$WORK/tx.bin" "$WORK/rx.bin" | wc -l) B 불일치)"
        fail=1
    fi
done
[ "$fail" -eq 0 ] && echo "RESULT: PASS $ITER/$ITER" || { echo "RESULT: FAIL"; exit 1; }
