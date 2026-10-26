#!/usr/bin/env bash
# eth_link + ctrl testbench (xsim, Verilator) + Verilator lint. 저장소 루트에서 실행한다.
# verilog-ethernet 파일은 고치지 않으므로 lint 경고를 그 파일들에서만 끈다(hardware/sim/eth/vendor.vlt).
# Verilator obj_dir는 공백 없는 ~/mmss_build에 둔다. SIMS="xsim verilator"로 고를 수 있다. FAIL이면 0이 아닌 값으로 끝난다.
set -euo pipefail
W=hardware/sim/eth
M=$HOME/mmss_build/verilator_eth
IP=hardware/ip/verilog-ethernet
VEN="$(ls $IP/rtl/*.v $IP/lib/axis/rtl/*.v)"
SRC="hardware/src/mdio_master.v hardware/src/eth_link.v hardware/src/ctrl.v"
TB=hardware/testbench/tb_eth.sv
SIMS="${SIMS:-xsim verilator}"
mkdir -p "$W"
printf '`verilator_config\nlint_off -file "*/verilog-ethernet/*"\nlint_off -rule SELRANGE -file "*/verilog-ethernet/*"\nlint_off -rule MULTIDRIVEN -file "*/verilog-ethernet/*"\n' > "$W/vendor.vlt"

L="verilator --lint-only -Wall -Wno-DECLFILENAME -Wno-UNUSEDSIGNAL"
$L --top-module ctrl hardware/src/ctrl.v
$L -Wno-PINCONNECTEMPTY --top-module eth_link "$W/vendor.vlt" hardware/src/mdio_master.v hardware/src/eth_link.v $VEN
echo "LINT OK"

for s in $SIMS; do
  if [ "$s" = xsim ]; then
    echo "== xsim"
    ( cd "$W" && xvlog --nolog -sv $(for f in $VEN $SRC $TB; do echo ../../../$f; done) > xvlog.log \
      && xelab --nolog -debug off tb_eth -s tb_eth > xelab.log )
    xsim --nolog --xsimdir "$W/xsim.dir" tb_eth -R | tee "$W/xsim.log" | grep -aE "^(run   |PASS|FAIL|ERROR)"
    rm -f xsim*.jou xvlog.pb xelab.pb
    grep -aq "^PASS" "$W/xsim.log"
  else
    echo "== Verilator"
    verilator --binary --timing -j 4 -Wno-fatal -Wno-lint -Wno-style --top-module tb_eth \
      --Mdir "$M" $VEN $SRC $TB > "$W/verilator_build.log" 2>&1
    "$M/Vtb_eth" | tee "$W/verilator.log" | grep -aE "^(run   |PASS|FAIL|ERROR)"
    grep -aq "^PASS" "$W/verilator.log"
  fi
done
