# ============================================================
# build_p05.tcl — P0.5 LED 점멸 + VIO 원격 확인 설계 빌드
# ============================================================
# 실행 (저장소 루트에서):
#   vivado -mode batch -source hardware/board_test/p05_blink/build_p05.tcl [-tclargs -proj_dir <경로>]
# 기본 위치: hardware/vivado/build/p05_blink (IP가 VIO뿐이라 공백 경로에서도 동작)
# ============================================================
set script_dir [file normalize [file dirname [info script]]]
set repo_root  [file normalize "$script_dir/../../.."]
set pd "$repo_root/hardware/vivado/build/p05_blink"
if { [lindex $argv 0] eq "-proj_dir" } { set pd [file normalize [lindex $argv 1]] }

create_project p05_blink $pd -part xc7a200tfbg484-2 -force
set_property target_language Verilog [current_project]
add_files -norecurse [list "$script_dir/blink_top.v"]
create_ip -name vio -vendor xilinx.com -library ip -module_name vio_p05
set_property -dict [list CONFIG.C_NUM_PROBE_IN {5} CONFIG.C_NUM_PROBE_OUT {0} \
    CONFIG.C_EN_PROBE_IN_ACTIVITY {0} \
    CONFIG.C_PROBE_IN0_WIDTH {32} CONFIG.C_PROBE_IN1_WIDTH {32} CONFIG.C_PROBE_IN2_WIDTH {1} \
    CONFIG.C_PROBE_IN3_WIDTH {5} CONFIG.C_PROBE_IN4_WIDTH {5}] [get_ips vio_p05]
generate_target all [get_ips vio_p05]
foreach x {base io} {
    add_files -fileset constrs_1 -norecurse [list "$repo_root/hardware/constraints/ax7a200b_$x.xdc"]
}
set_property top blink_top [current_fileset]

launch_runs synth_1 -jobs 8
wait_on_run synth_1
if { [get_property PROGRESS [get_runs synth_1]] ne "100%" } { error "합성 실패" }
launch_runs impl_1 -to_step write_bitstream -jobs 8
wait_on_run impl_1
if { [get_property PROGRESS [get_runs impl_1]] ne "100%" } { error "구현 실패" }
open_run impl_1
file mkdir "$pd/reports"
report_timing_summary -file "$pd/reports/timing_summary.rpt" -max_paths 10
report_drc            -file "$pd/reports/drc.rpt"
write_debug_probes -force "$pd/blink_top.ltx"
puts "INFO: WNS = [get_property SLACK [get_timing_paths -setup -max_paths 1 -nworst 1]] ns"
puts "INFO: 비트스트림 → [glob $pd/p05_blink.runs/impl_1/*.bit]"
