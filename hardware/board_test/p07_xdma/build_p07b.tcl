# ============================================================
# build_p07b.tcl — P0.7 비교용 Xilinx XDMA 예제 설계 빌드
# ============================================================
# 자체 블록 디자인(build_p07.tcl)에서 BAR 레지스터가 모두 0xffffffff로 읽히는
# 문제를 가르기 위해, Xilinx가 제공하는 예제 탑을 그대로 쓰고 핀만 보드에 맞춘다.
#   vivado -mode batch -source hardware/board_test/p07_xdma/build_p07b.tcl
# ============================================================
set script_dir [file normalize [file dirname [info script]]]
set pd "$::env(HOME)/mmss_build/p07b"
create_project p07b $pd -part xc7a200tfbg484-2 -force
set_property target_language Verilog [current_project]

create_ip -name xdma -vendor xilinx.com -library ip -module_name xdma_0
set_property -dict [list CONFIG.mode_selection {Advanced} CONFIG.pl_link_cap_max_link_width {X2} \
    CONFIG.pl_link_cap_max_link_speed {5.0_GT/s} CONFIG.axi_data_width {64_bit} \
    CONFIG.axisten_freq {125} CONFIG.xdma_rnum_chnl {1} CONFIG.xdma_wnum_chnl {1}] [get_ips xdma_0]
generate_target all [get_ips xdma_0]
open_example_project -force -dir "$pd/ex" [get_ips xdma_0]
current_project p07b
set imp "$pd/ex/xdma_0_ex/imports"
add_files -norecurse [list "$imp/xilinx_dma_pcie_ep.sv" "$imp/xdma_app.v"]
# 예제가 쓰는 BRAM IP를 그대로 가져온다.
import_ip -files "$pd/ex/xdma_0_ex/xdma_0_ex.srcs/sources_1/ip/blk_mem_gen_1/blk_mem_gen_1.xci"
generate_target all [get_ips blk_mem_gen_1]
add_files -fileset constrs_1 -norecurse [list "$script_dir/p07b.xdc"]
set_property top xilinx_dma_pcie_ep [current_fileset]
set_property -name {xsim.compile.xvlog.more_options} -value {} -objects [get_filesets sim_1]
update_compile_order -fileset sources_1

launch_runs synth_1 -jobs 8
wait_on_run synth_1
if { [get_property PROGRESS [get_runs synth_1]] ne "100%" } { error "합성 실패" }
launch_runs impl_1 -to_step write_bitstream -jobs 8
wait_on_run impl_1
if { [get_property PROGRESS [get_runs impl_1]] ne "100%" } { error "구현 실패" }
open_run impl_1
puts "INFO: WNS = [get_property SLACK [get_timing_paths -setup -max_paths 1 -nworst 1]] ns"
puts "INFO: 비트스트림 → [glob $pd/p07b.runs/impl_1/*.bit]"
