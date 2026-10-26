#!/usr/bin/env bash
# accel_core(DMA 포함) testbench (xsim, Verilator) + Verilator lint. 저장소 루트에서 실행한다.
# slave 모델 MODE 0(멈춤 없음), 1(무작위 backpressure·ID 섞기), 2(1 + 오류 응답)를 차례로 돌린다.
# vector는 run_compute_array.sh와 같은 vec_m12/를 쓴다. Verilator obj_dir는 공백 없는 ~/mmss_build에 둔다.
set -euo pipefail
W=hardware/sim/dma
M=$HOME/mmss_build/verilator_dma
SRC="hardware/src/plift_core.v hardware/src/plif_array.v hardware/src/mac_unit.v hardware/src/spike_list.v hardware/src/weight_entry.v hardware/src/compute_array.v hardware/src/membrane_bank.v hardware/src/membrane_buf.v hardware/src/membrane_storage.v hardware/src/next_use_predictor.v hardware/src/weight_cache.v hardware/src/dma.v hardware/src/accel_core.v"
TB=hardware/testbench/tb_dma.sv
MODES="${MODES:-0 1 2}"
mkdir -p "$W"
python3 hardware/testbench/export_compute_vectors.py --golden hardware/data/golden_l64_m12

verilator --lint-only -Wall -Wno-DECLFILENAME -Wno-UNUSEDSIGNAL -Wno-PINCONNECTEMPTY --top-module accel_core $SRC
echo "LINT OK"

echo "== xsim"
( cd "$W" && xvlog --nolog -sv $(for f in $SRC $TB; do echo ../../../$f; done) > xvlog.log )
for md in $MODES; do
  ( cd "$W" && xelab --nolog -debug off tb_dma -generic_top "MODE=$md" -s tb_m$md > xelab_m$md.log )
  xsim --nolog --xsimdir "$W/xsim.dir" tb_m$md -R | tee "$W/xsim_m$md.log" | grep -E "^(run   |PASS|FAIL)"
done
rm -f xsim*.jou xvlog.pb xelab.pb

echo "== Verilator"
for md in $MODES; do
  verilator --binary --timing -j 4 -Wno-fatal -Wno-lint -Wno-style --top-module tb_dma -GMODE=$md \
    --Mdir "$M""_m$md" $SRC $TB > "$W/verilator_build_m$md.log" 2>&1
  "$M""_m$md/Vtb_dma" | tee "$W/verilator_m$md.log" | grep -E "^(run   |PASS|FAIL)"
done
