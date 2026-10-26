#!/usr/bin/env bash
# frontend testbench (xsim, Verilator) + Verilator lint. 저장소 루트에서 실행한다.
# Simulator(Grouping + PNU-Count) 실행을 기록해 재생한다. 기록 = (번호, J ms, 시나리오, seed, 앞·뒤 주기, Offset Assignment).
# XSIM_TRACES로 xsim에서 돌릴 기록을 고른다(기본 모두).
set -euo pipefail
W=hardware/sim/frontend
M=$HOME/mmss_build/verilator_frontend
SRC="hardware/src/ingest.v hardware/src/req_table.v hardware/src/track_scheduler.v hardware/src/result.v hardware/src/frontend.v"
TB=hardware/testbench/tb_frontend.sv
TRACES="${TRACES:-0,0.8,uniform,0,8,16,offset_assignment 1,3.2,skewed,1,8,16,offset_assignment 2,0.0,skewed_synchronized,2,8,16,offset_assignment 3,1.6,fluctuating,3,8,16,offset_assignment 4,0.8,uniform,4,8,16,global_alignment 5,0.8,uniform,5,8,16,unaligned}"
XSIM_TRACES="${XSIM_TRACES:-0 1 2 3 4 5}"
mkdir -p "$W"
for t in $TRACES; do
  IFS=, read -r id j s sd wm ms off <<< "$t"
  python3 hardware/testbench/export_sched_trace.py --id "$id" --jitter "$j" --scn "$s" --seed "$sd" --warmup "$wm" --meas "$ms" --offset "$off"
done

verilator --lint-only -Wall -Wno-DECLFILENAME -Wno-UNUSEDSIGNAL --top-module frontend $SRC
echo "LINT OK"

echo "== Verilator"
verilator --binary --timing -j 4 -Wno-fatal -Wno-lint -Wno-style --top-module tb_frontend --Mdir "$M" $SRC $TB > "$W/verilator_build.log" 2>&1
for t in $TRACES; do
  IFS=, read -r id j s sd wm ms off <<< "$t"
  "$M/Vtb_frontend" +TID="$id" | tee "$W/verilator_t$id.log" | grep -E "^(run   |PASS|FAIL)"
done

echo "== xsim"
( cd "$W" && xvlog --nolog -sv $(for f in $SRC $TB; do echo ../../../$f; done) > xvlog.log \
  && xelab --nolog -debug off tb_frontend -s tb_frontend > xelab.log )
for id in $XSIM_TRACES; do
  xsim --nolog --xsimdir "$W/xsim.dir" tb_frontend -R -testplusarg TID="$id" | tee "$W/xsim_t$id.log" | grep -E "^(run   |PASS|FAIL)"
done
rm -f xsim*.jou xvlog.pb xelab.pb
