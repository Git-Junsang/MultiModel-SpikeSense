# ============================================================
# build_p07.tcl — P0.7 PCIe Gen2 ×2 XDMA 시험 설계 빌드 (재생성 가능)
# ============================================================
# 실행 (저장소 루트에서):
#   vivado -mode batch -source hardware/board_test/p07_xdma/build_p07.tcl \
#       [-tclargs -proj_dir <ASCII 경로>] [-jobs N]
# 기본 프로젝트 위치: ~/mmss_build/p07_xdma (공백 없는 경로, build_p06.tcl 참고)
#
# 구성: 블록 디자인 p07_bd = XDMA(Gen2 ×2, AXI-MM 64 bit, 125 MHz, H2C 1·C2H 1)
#       + AXI BRAM 컨트롤러 + 64 KiB BRAM. 탑은 p07_top.v.
# ============================================================

set script_dir [file normalize [file dirname [info script]]]
set repo_root  [file normalize "$script_dir/../../.."]
set part       "xc7a200tfbg484-2"

set opt(proj_dir) "$::env(HOME)/mmss_build/p07_xdma"
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
    error "proj_dir에 공백이 없어야 한다: $opt(proj_dir)"
}
set pd $opt(proj_dir)

create_project p07_xdma $pd -part $part -force
set_property target_language Verilog [current_project]

# ---- 블록 디자인 ----
create_bd_design p07_bd
set xdma [create_bd_cell -type ip -vlnv xilinx.com:ip:xdma xdma_0]
set_property -dict [list \
    CONFIG.mode_selection            {Advanced} \
    CONFIG.pl_link_cap_max_link_width {X2} \
    CONFIG.pl_link_cap_max_link_speed {5.0_GT/s} \
    CONFIG.axi_data_width            {64_bit} \
    CONFIG.axisten_freq              {125} \
    CONFIG.pf0_device_id             {7022} \
    CONFIG.xdma_rnum_chnl            {1} \
    CONFIG.xdma_wnum_chnl            {1} \
    CONFIG.axilite_master_en         {false} \
    CONFIG.xdma_axi_intf_mm          {AXI_Memory_Mapped} \
    CONFIG.pciebar2axibar_xdma       {0x0000000000000000} \
] $xdma

set bc [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_bram_ctrl axi_bram_ctrl_0]
set_property -dict [list CONFIG.DATA_WIDTH {64} CONFIG.SINGLE_PORT_BRAM {1} CONFIG.ECC_TYPE {0}] $bc
set bm [create_bd_cell -type ip -vlnv xilinx.com:ip:blk_mem_gen blk_mem_0]

connect_bd_intf_net [get_bd_intf_pins xdma_0/M_AXI] [get_bd_intf_pins axi_bram_ctrl_0/S_AXI]
connect_bd_intf_net [get_bd_intf_pins axi_bram_ctrl_0/BRAM_PORTA] [get_bd_intf_pins blk_mem_0/BRAM_PORTA]
connect_bd_net [get_bd_pins xdma_0/axi_aclk]    [get_bd_pins axi_bram_ctrl_0/s_axi_aclk]
connect_bd_net [get_bd_pins xdma_0/axi_aresetn] [get_bd_pins axi_bram_ctrl_0/s_axi_aresetn]

make_bd_intf_pins_external -name pcie_mgt [get_bd_intf_pins xdma_0/pcie_mgt]
foreach p {sys_clk sys_rst_n user_lnk_up} {
    make_bd_pins_external -name $p [get_bd_pins xdma_0/$p]
}
# axi_aclk는 BRAM 컨트롤러에 이미 연결되어 있어 make_bd_pins_external이 포트를
# 만들지 않는다. 출력 포트를 직접 만들어 연결한다.
create_bd_port -dir O -type clk axi_aclk
connect_bd_net [get_bd_ports axi_aclk] [get_bd_pins xdma_0/axi_aclk]

assign_bd_address
set_property range  64K [get_bd_addr_segs {xdma_0/M_AXI/SEG_axi_bram_ctrl_0_Mem0}]
set_property offset 0x00000000 [get_bd_addr_segs {xdma_0/M_AXI/SEG_axi_bram_ctrl_0_Mem0}]
validate_bd_design
save_bd_design

set bdf [get_files p07_bd.bd]
generate_target all $bdf
add_files -norecurse [make_wrapper -files $bdf -top]

# ---- VIO ----
create_ip -name vio -vendor xilinx.com -library ip -module_name vio_p07
set_property -dict [list \
    CONFIG.C_NUM_PROBE_IN   {6} \
    CONFIG.C_PROBE_IN4_WIDTH {14} \
    CONFIG.C_PROBE_IN5_WIDTH {14} \
    CONFIG.C_NUM_PROBE_OUT  {2} \
    CONFIG.C_PROBE_OUT0_WIDTH {1} \
    CONFIG.C_PROBE_OUT0_INIT_VAL {0x0} \
    CONFIG.C_PROBE_OUT1_WIDTH {1} \
    CONFIG.C_PROBE_OUT1_INIT_VAL {0x0} \
    CONFIG.C_EN_PROBE_IN_ACTIVITY {0} \
    CONFIG.C_PROBE_IN0_WIDTH {1} \
    CONFIG.C_PROBE_IN1_WIDTH {1} \
    CONFIG.C_PROBE_IN2_WIDTH {14} \
    CONFIG.C_PROBE_IN3_WIDTH {32}] [get_ips vio_p07]
generate_target all [get_ips vio_p07]

# ---- 소스·제약 ----
add_files -norecurse [list "$script_dir/p07_top.v"]
foreach x {base io pcie} {
    add_files -fileset constrs_1 -norecurse [list "$repo_root/hardware/constraints/ax7a200b_$x.xdc"]
}
add_files -fileset constrs_1 -norecurse [list "$script_dir/p07.xdc"]
set_property top p07_top [current_fileset]
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
write_debug_probes -force "$pd/p07_top.ltx"
# GT 채널 배치 확인 (lane0 = X0Y7, lane1 = X0Y6 이어야 한다. ax7a200b_pcie.xdc 참고)
foreach c [get_cells -hierarchical -filter {REF_NAME == GTPE2_CHANNEL}] {
    puts "INFO: GT [get_property LOC $c] ← $c"
}
set wns [get_property SLACK [get_timing_paths -setup -max_paths 1 -nworst 1]]
set whs [get_property SLACK [get_timing_paths -hold  -max_paths 1 -nworst 1]]
puts "INFO: WNS = $wns ns, WHS = $whs ns"
puts "INFO: 비트스트림 → [glob $pd/p07_xdma.runs/impl_1/*.bit]"
