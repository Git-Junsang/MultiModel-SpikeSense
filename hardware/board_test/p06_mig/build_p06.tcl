# ============================================================
# build_p06.tcl — P0.6 MIG DDR3 예제 설계 빌드 (재생성 가능)
# ============================================================
# 실행 (저장소 루트에서):
#   vivado -mode batch -source hardware/board_test/p06_mig/build_p06.tcl \
#       [-tclargs -proj_dir <ASCII 경로>] [-jobs N]
#
# 기본 프로젝트 위치: ~/mmss_build/p06_mig
#   MIG는 경로에 공백이 있으면 XML_INPUT_FILE(prj)을 읽지 못한다
#   (2026-09-23 확인: "File or Directory '학부연구생/...' does not exist").
#   저장소 경로에 공백이 있으므로 프로젝트는 공백 없는 경로에 만든다.
#
# 구성:
#   mig_ddr3  : mig_ddr3.prj (AXI 256 bit, 400 MHz, UI 100 MHz)
#   example_top: MIG 예제 설계 탑 + AXI4 트래픽 생성기. ui_clk_o 포트만 덧붙인다.
#   vio_p06   : 상태 읽기용 VIO
#   p06_top   : 탑(LED·버튼·VIO)
# ============================================================

set script_dir [file normalize [file dirname [info script]]]
set repo_root  [file normalize "$script_dir/../../.."]
set part       "xc7a200tfbg484-2"

set opt(proj_dir) "$::env(HOME)/mmss_build/p06_mig"
set opt(jobs)     8
for {set i 0} {$i < [llength $argv]} {incr i 2} {
    set k [lindex $argv $i]; set v [lindex $argv [expr {$i+1}]]
    switch -- $k {
        -proj_dir { set opt(proj_dir) [file normalize $v] }
        -jobs     { set opt(jobs) $v }
        default   { error "알 수 없는 옵션: $k" }
    }
}
if { [string first " " $opt(proj_dir)] >= 0 } {
    error "proj_dir에 공백이 있으면 MIG 생성이 실패한다: $opt(proj_dir)"
}
set pd $opt(proj_dir)
puts "INFO: proj_dir = $pd"

create_project p06_mig $pd -part $part -force
set_property target_language Verilog [current_project]

# ---- MIG ----
create_ip -name mig_7series -vendor xilinx.com -library ip -module_name mig_ddr3
set ipdir [get_property IP_DIR [get_ips mig_ddr3]]
file copy -force "$script_dir/mig_ddr3.prj" "$ipdir/mig_ddr3.prj"
set_property -dict [list \
    CONFIG.XML_INPUT_FILE        {mig_ddr3.prj} \
    CONFIG.RESET_BOARD_INTERFACE {Custom} \
    CONFIG.MIG_DONT_TOUCH_PARAM  {Custom} \
    CONFIG.BOARD_MIG_PARAM       {Custom}] [get_ips mig_ddr3]
generate_target all [get_ips mig_ddr3]

# ---- 예제 설계 소스 가져오기 ----
open_example_project -force -dir "$pd/ex" [get_ips mig_ddr3]
current_project p06_mig
set imp "$pd/ex/mig_ddr3_ex/imports"
set tg_files [glob "$imp/mig_7series_v4_2_*.v"]
add_files -norecurse $tg_files

# example_top.v에 ui_clk_o 출력 포트를 덧붙인 사본을 만든다.
set fh [open "$imp/example_top.v" r]; set src [read $fh]; close $fh
set n1 [regsub {(\n\s*input\s+sys_rst\s*\n\s*\);)} $src \
    "\n   input                                        sys_rst,\n   output                                       ui_clk_o\n   );" src]
set n2 [regsub {\nendmodule} $src "\n   assign ui_clk_o = clk;\n\nendmodule" src]
if { $n1 != 1 || $n2 != 1 } { error "example_top.v 패치 실패 (n1=$n1 n2=$n2)" }
file mkdir "$pd/patched"
set fh [open "$pd/patched/example_top.v" w]; puts -nonewline $fh $src; close $fh
add_files -norecurse "$pd/patched/example_top.v"
add_files -norecurse [list "$script_dir/p06_top.v"]

# ---- VIO ----
create_ip -name vio -vendor xilinx.com -library ip -module_name vio_p06
set_property -dict [list \
    CONFIG.C_NUM_PROBE_IN   {5} \
    CONFIG.C_NUM_PROBE_OUT  {0} \
    CONFIG.C_EN_PROBE_IN_ACTIVITY {0} \
    CONFIG.C_PROBE_IN0_WIDTH {1} \
    CONFIG.C_PROBE_IN1_WIDTH {1} \
    CONFIG.C_PROBE_IN2_WIDTH {1} \
    CONFIG.C_PROBE_IN3_WIDTH {32} \
    CONFIG.C_PROBE_IN4_WIDTH {32}] [get_ips vio_p06]
generate_target all [get_ips vio_p06]

# ---- 제약 ----
#   DDR3 핀·sys_clk는 MIG IP XDC가 넣는다. 구성 설정·LED·버튼은 저장소 XDC와
#   이 설계 전용 XDC(p06.xdc)로 넣는다.
add_files -fileset constrs_1 -norecurse "$imp/example_top.xdc"
add_files -fileset constrs_1 -norecurse [list "$script_dir/p06.xdc"]
add_files -fileset constrs_1 -norecurse [list "$repo_root/hardware/constraints/ax7a200b_io.xdc"]

set_property top p06_top [current_fileset]
update_compile_order -fileset sources_1

# ---- 빌드 ----
launch_runs synth_1 -jobs $opt(jobs)
wait_on_run synth_1
if { [get_property PROGRESS [get_runs synth_1]] ne "100%" } { error "합성 실패" }
launch_runs impl_1 -to_step write_bitstream -jobs $opt(jobs)
wait_on_run impl_1
if { [get_property PROGRESS [get_runs impl_1]] ne "100%" } { error "구현 실패" }

open_run impl_1
set rpt "$pd/reports"
file mkdir $rpt
report_utilization    -file "$rpt/utilization.rpt"
report_timing_summary -file "$rpt/timing_summary.rpt" -max_paths 10
report_drc            -file "$rpt/drc.rpt"
report_io             -file "$rpt/io.rpt"
write_debug_probes -force "$pd/p06_top.ltx"
set wns [get_property SLACK [get_timing_paths -setup -max_paths 1 -nworst 1]]
set whs [get_property SLACK [get_timing_paths -hold  -max_paths 1 -nworst 1]]
puts "INFO: WNS = $wns ns, WHS = $whs ns"
puts "INFO: 비트스트림 → [glob $pd/p06_mig.runs/impl_1/*.bit]"
puts "INFO: 프로브 → $pd/p06_top.ltx"
