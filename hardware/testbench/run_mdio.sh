#!/usr/bin/env bash
# mdio_master.v testbench (xsim) + Verilator lint. 저장소 루트에서 실행한다. PASS가 없으면 0이 아닌 값으로 끝난다.
# Verilator 5.020은 testbench의 양방향 MDIO(tri1 + 두 구동자)를 다루지 못해 xsim으로만 돌린다.
set -euo pipefail
W=hardware/sim/mdio
mkdir -p "$W"
verilator --lint-only -Wall -Wno-DECLFILENAME --top-module mdio_master hardware/src/mdio_master.v
echo "LINT OK"
( cd "$W" && xvlog --nolog -sv ../../../hardware/src/mdio_master.v ../../../hardware/testbench/tb_mdio.sv > xvlog.log \
  && xelab --nolog -debug off tb_mdio -s tb_mdio > xelab.log )
( ulimit -v 4000000; xsim --nolog --xsimdir "$W/xsim.dir" tb_mdio -R ) > "$W/xsim.log" 2>&1 || true
grep -aE "^(run   |PASS|FAIL|ERROR)" "$W/xsim.log" | head -20
rm -f xsim*.jou xvlog.pb xelab.pb
grep -aq "^PASS" "$W/xsim.log"
