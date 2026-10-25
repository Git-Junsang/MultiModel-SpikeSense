# ============================================================
# ooc_timing.tcl — RTL wrapper의 100 MHz out-of-context 합성·배치·배선
# ============================================================
# 실행 (저장소 루트에서). 인자는 wrapper 이름 앞부분: p41(compute array), p42(+ membrane storage)
#   vivado -mode batch -nojournal -nolog -source hardware/vivado/ooc_timing.tcl -tclargs p42
# 두 번째 인자로 hardware/src의 module을 top으로 줄 수 있다(wrapper 없이): -tclargs p44 accel_core
# wrapper: hardware/vivado/<인자>_timing_top.v, RTL: hardware/src/*.v 전부
# 산출물: hardware/vivado/build/<인자>_timing/ (timing·utilization report, checkpoint)
# ============================================================

set root  [file normalize [file dirname [info script]]/../..]
# 저장소 경로에 공백이 있어 파일 인자는 [list ...]로 넘긴다
set name  [lindex $argv 0]
set top   [expr {[llength $argv] > 1 ? [lindex $argv 1] : "${name}_timing_top"}]
set out   $root/hardware/vivado/build/${name}_timing
file mkdir $out
cd $out                    ;# place_design이 cwd에 clockInfo.txt를 남긴다

foreach f [glob $root/hardware/src/*.v] {
    read_verilog [list $f]
}
if {[llength $argv] == 1} {
    read_verilog [list $root/hardware/vivado/${name}_timing_top.v]
}
set xdc [open $out/clk.xdc w]
puts $xdc "create_clock -name clk -period 10.000 \[get_ports clk\]"
close $xdc
read_xdc -mode out_of_context [list $out/clk.xdc]

synth_design -top $top -part xc7a200tfbg484-2 -mode out_of_context
report_utilization -hierarchical -hierarchical_depth 2 -file $out/synth_util.rpt
report_timing_summary -file $out/synth_timing.rpt

opt_design
place_design
phys_opt_design
route_design
report_timing_summary -max_paths 10 -file $out/route_timing.rpt
report_utilization -file $out/route_util.rpt
report_utilization -hierarchical -hierarchical_depth 3 -file $out/route_util_hier.rpt
set dsp [get_cells -hier -filter {REF_NAME == DSP48E1}]
set f [open $out/route_dsp.txt w]
puts $f "DSP48E1 [llength $dsp], USE_DPORT [llength [filter $dsp {USE_DPORT == TRUE}]]"
close $f
write_checkpoint -force $out/route.dcp
