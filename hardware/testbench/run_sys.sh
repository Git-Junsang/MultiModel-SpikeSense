#!/usr/bin/env bash
# accel_sys 통합 testbench (Verilator, xsim) + Verilator lint. 저장소 루트에서 실행한다.
# Host는 verilog-ethernet stack, DDR3는 AXI4 slave 모델. golden vector는 run_dma.sh와 같은 vec_m12/를 쓴다(없으면 만든다).
# 환경 변수: SIMS="verilator xsim"(기본 둘 다), PLUS="+FULL=1" 같은 plusarg(둘 다에), VPLUS·XPLUS(Verilator·xsim 따로),
#   SRCDIR = RTL 폴더(고장 사본 시험용, 기본 hardware/src), M = Verilator obj_dir, W = 산출물 폴더, LINT=0이면 lint 건너뜀.
# 메모리: simulation은 ulimit -v 8000000(약 7.6 GiB) 안에서 돌리고 Verilator 빌드는 -j 2. PASS가 없으면 0이 아닌 값으로 끝난다.
set -euo pipefail
W=${W:-hardware/sim/sys}
M=${M:-$HOME/mmss_build/verilator_sys}
SRCDIR=$(realpath "${SRCDIR:-hardware/src}")
SIMS="${SIMS:-verilator xsim}"
PLUS="${PLUS:-}"
mkdir -p "$W"
W=$(realpath "$W")

IP=$(realpath hardware/ip/verilog-ethernet)
FILES=()
for f in "$IP"/rtl/*.v "$IP"/lib/axis/rtl/*.v; do FILES+=("$f"); done
for f in plift_core plif_array mac_unit spike_list weight_entry compute_array membrane_bank membrane_buf membrane_storage \
         next_use_predictor weight_cache dma accel_core ingest req_table track_scheduler result frontend regs ctrl mdio_master eth_link accel_sys; do
  FILES+=("$SRCDIR/$f.v")
done
TB=$(realpath "${TB:-hardware/testbench/tb_sys.sv}")
printf '`verilator_config\nlint_off -file "*/verilog-ethernet/*"\nlint_off -rule SELRANGE -file "*/verilog-ethernet/*"\nlint_off -rule MULTIDRIVEN -file "*/verilog-ethernet/*"\n' > "$W/vendor.vlt"
[ -f hardware/sim/compute_array/vec_m12/index.hex ] || python3 hardware/testbench/export_compute_vectors.py --golden hardware/data/golden_l64_m12

if [ "${LINT:-1}" = 1 ]; then
  verilator --lint-only -Wall -Wno-DECLFILENAME -Wno-UNUSEDSIGNAL -Wno-PINCONNECTEMPTY -Wno-TIMESCALEMOD \
    --top-module accel_sys "$W/vendor.vlt" "${FILES[@]}"
  echo "LINT OK"
fi

rc=0
for s in $SIMS; do
  if [ "$s" = xsim ]; then
    echo "== xsim"
    t0=$(date +%s)
    ( cd "$W" && xvlog --nolog -sv "${FILES[@]}" "$TB" > xvlog.log && xelab --nolog -debug off tb_sys -s tb_sys > xelab.log )
    t1=$(date +%s)
    XP=""; for p in $PLUS ${XPLUS:-}; do XP="$XP -testplusarg ${p#+}"; done
    XD=$(realpath --relative-to=. "$W/xsim.dir")   # xsim은 공백이 든 절대 경로를 나눠 읽는다
    ( ulimit -v 8000000; xsim --nolog --xsimdir "$XD" tb_sys -R $XP ) > "$W/xsim.log" 2>&1 || true
    t2=$(date +%s)
    grep -aE "^(run   |PASS|FAIL|ERROR)" "$W/xsim.log" || tail -5 "$W/xsim.log"
    rm -f xsim*.jou xvlog.pb xelab.pb "$W"/*.jou "$W"/*.pb
    echo "time  xsim: 빌드 $((t1 - t0)) s, 실행 $((t2 - t1)) s"
    grep -aq "^PASS" "$W/xsim.log" || rc=1
  else
    echo "== Verilator"
    t0=$(date +%s)
    verilator --binary --timing -j 2 -Wno-fatal -Wno-lint -Wno-style --top-module tb_sys \
      --Mdir "$M" "${FILES[@]}" "$TB" > "$W/verilator_build.log" 2>&1 || { tail -30 "$W/verilator_build.log"; exit 1; }
    t1=$(date +%s)
    ( ulimit -v 8000000; "$M/Vtb_sys" $PLUS ${VPLUS:-} ) > "$W/verilator.log" 2>&1 || true
    t2=$(date +%s)
    grep -aE "^(run   |PASS|FAIL|ERROR)" "$W/verilator.log" || tail -5 "$W/verilator.log"
    echo "time  Verilator: 빌드 $((t1 - t0)) s, 실행 $((t2 - t1)) s"
    grep -aq "^PASS" "$W/verilator.log" || rc=1
  fi
done
exit $rc
