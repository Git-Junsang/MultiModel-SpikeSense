#!/usr/bin/env bash
# p3_core testbench (xsim) + Verilator lint. 저장소 루트에서 실행한다.
set -euo pipefail
D=hardware/board_test/p3_meas
W=hardware/sim/p3_core
mkdir -p "$W"
( cd "$W" && xvlog --nolog -sv ../../../$D/ddr_tgen.v ../../../$D/p3_core.v ../../../$D/tb_p3_core.sv > xvlog.log \
  && xelab --nolog -debug off tb_p3_core -s tb_p3_core > xelab.log \
  && xsim --nolog tb_p3_core -R | tee xsim.log | grep -E "^(run|PASS|FAIL)" )
verilator --lint-only -Wall -Wno-DECLFILENAME -Wno-UNUSEDSIGNAL --top-module p3_core $D/p3_core.v $D/ddr_tgen.v
echo "LINT OK"
