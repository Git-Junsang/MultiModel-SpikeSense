#!/usr/bin/env bash
# compute_array testbench (xsim, Verilator) + Verilator lint. 저장소 루트에서 실행한다.
# $readmemh 경로가 저장소 루트 기준이라 simulation은 루트에서 돌리고 산출물은 $W에 둔다.
# Verilator의 make는 공백 있는 경로에서 build하지 못해 obj_dir는 ~/mmss_build에 둔다.
set -euo pipefail
W=hardware/sim/compute_array
M=$HOME/mmss_build/verilator_compute_array
SRC="hardware/src/plift_core.v hardware/src/plif_array.v hardware/src/mac_unit.v hardware/src/spike_list.v hardware/src/weight_entry.v hardware/src/compute_array.v"
TB=hardware/testbench/tb_compute_array.sv
mkdir -p "$W"
python3 hardware/testbench/export_compute_vectors.py
python3 hardware/testbench/export_compute_vectors.py --golden hardware/data/golden_l64_m12

verilator --lint-only -Wall -Wno-DECLFILENAME -Wno-UNUSEDSIGNAL --top-module compute_array $SRC
echo "LINT OK"

echo "== xsim"
( cd "$W" && xvlog --nolog -sv $(for f in $SRC $TB; do echo ../../../$f; done) > xvlog.log )
for B in 16 12; do
  ( cd "$W" && xelab --nolog -debug off tb_compute_array -generic_top "STORE_BITS=$B" -s tb_m$B > xelab_m$B.log )
  xsim --nolog --xsimdir "$W/xsim.dir" tb_m$B -R | tee "$W/xsim_m$B.log" | grep -E "^(run   |PASS|FAIL)"
done
rm -f xsim*.jou xvlog.pb xelab.pb

echo "== Verilator"
for B in 16 12; do
  verilator --binary --timing -j 4 -Wno-fatal -Wno-lint -Wno-style --top-module tb_compute_array -GSTORE_BITS=$B \
    --Mdir "$M""_m$B" $SRC $TB > "$W/verilator_build_m$B.log" 2>&1
  "$M""_m$B/Vtb_compute_array" | tee "$W/verilator_m$B.log" | grep -E "^(run   |PASS|FAIL)"
done
