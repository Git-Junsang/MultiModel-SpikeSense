#!/usr/bin/env bash
# weight_cache testbench (xsim, Verilator) + Verilator lint. 저장소 루트에서 실행한다.
# simulator(engine.PNURTL) 실행 3개를 기록해 재생한다. 기록 = (번호, entry, J ms, 시나리오, seed).
set -euo pipefail
W=hardware/sim/weight_cache
M=$HOME/mmss_build/verilator_weight_cache
SRC="hardware/src/weight_entry.v hardware/src/next_use_predictor.v hardware/src/weight_cache.v"
TB=hardware/testbench/tb_weight_cache.sv
TRACES="0,4,3.2,U,0 1,4,0.8,SK,1 2,6,3.2,K,2"
mkdir -p "$W"
for t in $TRACES; do
  IFS=, read -r id e j s sd <<< "$t"
  python3 hardware/testbench/export_pnu_trace.py --id "$id" --entries "$e" --jitter "$j" --scn "$s" --seed "$sd"
done

verilator --lint-only -Wall -Wno-DECLFILENAME -Wno-UNUSEDSIGNAL --top-module weight_cache $SRC
echo "LINT OK"

echo "== xsim"
( cd "$W" && xvlog --nolog -sv $(for f in $SRC $TB; do echo ../../../$f; done) > xvlog.log )
for t in $TRACES; do
  IFS=, read -r id e j s sd <<< "$t"
  ( cd "$W" && xelab --nolog -debug off tb_weight_cache -generic_top "E=$e" -generic_top "TID=$id" -s tb_t$id > xelab_t$id.log )
  xsim --nolog --xsimdir "$W/xsim.dir" tb_t$id -R | tee "$W/xsim_t$id.log" | grep -E "^(run   |PASS|FAIL)"
done
rm -f xsim*.jou xvlog.pb xelab.pb

echo "== Verilator"
for t in $TRACES; do
  IFS=, read -r id e j s sd <<< "$t"
  verilator --binary --timing -j 4 -Wno-fatal -Wno-lint -Wno-style --top-module tb_weight_cache -GE=$e -GTID=$id \
    --Mdir "$M""_t$id" $SRC $TB > "$W/verilator_build_t$id.log" 2>&1
  "$M""_t$id/Vtb_weight_cache" | tee "$W/verilator_t$id.log" | grep -E "^(run   |PASS|FAIL)"
done
