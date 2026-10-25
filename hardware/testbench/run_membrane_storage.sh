#!/usr/bin/env bash
# membrane_storage testbench (xsim, Verilator) + Verilator lint. 저장소 루트에서 실행한다.
# vector는 run_compute_array.sh와 같은 vec_m12/를 쓴다. Verilator obj_dir는 공백 없는 ~/mmss_build에 둔다.
set -euo pipefail
W=hardware/sim/membrane_storage
M=$HOME/mmss_build/verilator_membrane_storage
SRC="hardware/src/plift_core.v hardware/src/plif_array.v hardware/src/mac_unit.v hardware/src/spike_list.v hardware/src/weight_entry.v hardware/src/compute_array.v hardware/src/membrane_bank.v hardware/src/membrane_buf.v hardware/src/membrane_storage.v"
TB=hardware/testbench/tb_membrane_storage.sv
mkdir -p "$W"
python3 hardware/testbench/export_compute_vectors.py --golden hardware/data/golden_l64_m12

verilator --lint-only -Wall -Wno-DECLFILENAME -Wno-UNUSEDSIGNAL --top-module membrane_storage \
  hardware/src/membrane_storage.v hardware/src/membrane_bank.v hardware/src/membrane_buf.v
echo "LINT OK"

echo "== xsim"
( cd "$W" && xvlog --nolog -sv $(for f in $SRC $TB; do echo ../../../$f; done) > xvlog.log \
  && xelab --nolog -debug off tb_membrane_storage -s tb_membrane_storage > xelab.log )
xsim --nolog --xsimdir "$W/xsim.dir" tb_membrane_storage -R | tee "$W/xsim.log" | grep -E "^(run   |PASS|FAIL)"
rm -f xsim*.jou xvlog.pb xelab.pb

echo "== Verilator"
verilator --binary --timing -j 4 -Wno-fatal -Wno-lint -Wno-style --top-module tb_membrane_storage \
  --Mdir "$M" $SRC $TB > "$W/verilator_build.log" 2>&1
"$M/Vtb_membrane_storage" | tee "$W/verilator.log" | grep -E "^(run   |PASS|FAIL)"
