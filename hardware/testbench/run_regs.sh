#!/usr/bin/env bash
# regs testbench (xsim, Verilator) + Verilator lint. 저장소 루트에서 실행한다.
# RTL 경로를 바꾸려면 SRC=... (고장 사본 시험용). Verilator obj_dir는 공백 없는 ~/mmss_build에 둔다.
set -euo pipefail
W=${W:-hardware/sim/regs}
M=${M:-$HOME/mmss_build/regs}
SRC=$(realpath "${SRC:-hardware/src/regs.v}")
TB=$(realpath hardware/testbench/tb_regs.sv)
mkdir -p "$W"

verilator --lint-only -Wall -Wno-DECLFILENAME -Wno-UNUSEDSIGNAL --top-module regs "$SRC"
echo "LINT OK"

echo "== xsim"
( cd "$W" && xvlog --nolog -sv "$SRC" "$TB" > xvlog.log && xelab --nolog -debug off tb_regs -s tb_regs > xelab.log )
( cd "$W" && xsim --nolog tb_regs -R ) | tee "$W/xsim.log" | grep -E "^(run   |PASS|FAIL)"
rm -f "$W"/*.jou "$W"/*.pb

echo "== Verilator"
verilator --binary --timing -j 4 -Wno-fatal -Wno-lint -Wno-style --top-module tb_regs \
  --Mdir "$M" "$SRC" "$TB" > "$W/verilator_build.log" 2>&1 || { tail -30 "$W/verilator_build.log"; exit 1; }
"$M/Vtb_regs" | tee "$W/verilator.log" | grep -E "^(run   |PASS|FAIL)"
