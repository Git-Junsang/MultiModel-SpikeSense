#!/usr/bin/env bash
# ============================================================
# p3_pcie_bench.sh — P3.3 PCIe 지연·jitter 측정 묶음 (FPGA Host)
# ============================================================
# pcie_delay로 시험을 차례로 돌리고 결과를 <OUT>/<설계>_<시험>_<조건>.txt로 남긴다.
# 사용: ./p3_pcie_bench.sh <설계 태그> <OUT 폴더> [BRAM 주소] [DDR3 주소]
#   p07(P1.7 설계, BRAM @0x0, 사용자 BAR 없음):  ./p3_pcie_bench.sh p07 ~/fpga_work/p3/pcie 0x0
#   p3 (측정 설계, BRAM @0x10000, DDR3 @0x80000000, 사용자 BAR 있음):
#                                                ./p3_pcie_bench.sh p3 ~/fpga_work/p3/pcie 0x10000 0x80000000
# 환경 변수 TAG2를 주면 파일명 끝에 붙인다(예: 드라이버 poll 모드 구분).
# ============================================================
set -euo pipefail
D=${1:?설계 태그}
OUT=${2:?출력 폴더}
BRAM=${3:-0x0}
DDR=${4:-}
T2=${TAG2:+_$TAG2}
L=$(dirname "$0")/pcie_delay
mkdir -p "$OUT"
run() { local name=$1; shift; echo "== $name"; sudo "$L" "$@" -o "$OUT/${D}_${name}${T2}.txt"; }

run mmio_cfg              mmio_cfg -n 100000
run mmio_cfg_p1000        mmio_cfg -n 5000 -p 1000
if [ -e /dev/xdma0_user ]; then
    run mmio_rd           mmio_rd -n 100000
    run mmio_rd_p1000     mmio_rd -n 5000 -p 1000
    run mmio_wr12         mmio_wr -n 20000 -w 12
    run ts_sync           ts_sync -n 60000 -p 1000
fi
for s in 64 256 1024 4096 16384 65536; do
    n=20000; [ "$s" -ge 16384 ] && n=5000
    run h2c_${s}          h2c -s "$s" -n "$n" -a "$BRAM"
    run c2h_${s}          c2h -s "$s" -n "$n" -a "$BRAM"
done
run rt_64                 rt -s 64 -n 20000 -a "$BRAM"
run h2c_64_p62.5          h2c -s 64 -n 20000 -a "$BRAM" -p 62.5
run h2c_64_p1000          h2c -s 64 -n 5000 -a "$BRAM" -p 1000
run c2h_64_p1000          c2h -s 64 -n 5000 -a "$BRAM" -p 1000
run h2c_24576_p32000      h2c -s 24576 -n 300 -a "$BRAM" -p 32000
if [ -n "$DDR" ]; then
    # MIG 포트를 Host(XDMA) 쪽으로 돌리고, narrow burst 플래그를 지운 뒤 시험한다.
    R="sudo python3 $(dirname "$0")/p3_regs.py"
    $R wr 0x44 1
    $R wr 0x40 4
    for s in 65536 262144 1048576 4194304; do
        run ddr_h2c_${s}  h2c -s "$s" -n 200 -a "$DDR"
        run ddr_c2h_${s}  c2h -s "$s" -n 200 -a "$DDR"
    done
    run ddr_rt_64         rt -s 64 -n 2000 -a "$DDR"
    if [ -n "${MODEL_IMG:-}" ]; then
        echo "== 모델 이미지 적재 ($MODEL_IMG)"
        sudo "$L" load -f "$MODEL_IMG" -a "$DDR" -n 5 -o "$OUT/${D}_load_models${T2}.log"
        cat "$OUT/${D}_load_models${T2}.log"
    fi
    echo "STATUS = $($R rd 0x8)  (bit5 = narrow burst 감지)"
    $R wr 0x44 0
fi
echo "OK $OUT"
