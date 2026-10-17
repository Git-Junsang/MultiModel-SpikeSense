# ============================================================
# build_p3.tcl — P3.1~P3.3 측정 설계 빌드 (MIG + 트래픽 생성기 + XDMA + JTAG-AXI)
# ============================================================
# 실행 (저장소 루트에서):
#   vivado -mode batch -source hardware/board_test/p3_meas/build_p3.tcl \
#       -tclargs [-addr_map BANK_ROW_COLUMN|ROW_BANK_COLUMN] [-proj_dir <ASCII 경로>] [-jobs N]
#       [-fit N_ENT,SLICE_BUF,BV_ALL40,Q_BRAM]
#
# -fit: BRAM 적합성 실험(P3.2·P3.4). mem_fit.v의 on-chip 메모리 골격을 넣고, 측정용
#   BRAM 64 KiB·JTAG-AXI를 빼고, 지연 기록을 16개로 줄여 배치·배선까지만 한다
#   (비트스트림 없음). 예: -fit 4,1,1,1 → entry 4개, 슬라이스 버퍼, β·vth 40모델 상주, queue BRAM
#
# -addr_map: MIG 사용자 주소 → DDR3 (bank, 행, 열) 매핑. 기본값은 P1.6과 같은
#   BANK_ROW_COLUMN. ROW_BANK_COLUMN은 4 KiB(한 행)마다 bank가 바뀌어 순차 접근에서
#   다음 bank의 행을 미리 열 수 있다. 두 비트스트림의 측정값을 비교한다(P3.1).
# 기본 프로젝트 위치: ~/mmss_build/p3_<addr_map 소문자 약칭> (공백 없는 경로, build_p06.tcl 참고)
# 산출물: <proj_dir>/p3_top.bit·.ltx·.mcs, <proj_dir>/reports/*.rpt
# ============================================================

set script_dir [file normalize [file dirname [info script]]]
set repo_root  [file normalize "$script_dir/../../.."]
set part       "xc7a200tfbg484-2"

set opt(addr_map) "BANK_ROW_COLUMN"
set opt(proj_dir) ""
set opt(jobs)     8
set opt(fit)      ""
for {set i 0} {$i < [llength $argv]} {incr i 2} {
    set k [lindex $argv $i]; set v [lindex $argv [expr {$i+1}]]
    switch -- $k {
        -addr_map { set opt(addr_map) $v }
        -proj_dir { set opt(proj_dir) [file normalize $v] }
        -jobs     { set opt(jobs) $v }
        -fit      { set opt(fit) $v }
        default   { error "알 수 없는 옵션: $k" }
    }
}
if { $opt(addr_map) ni {BANK_ROW_COLUMN ROW_BANK_COLUMN} } { error "-addr_map 값: $opt(addr_map)" }
set tag [expr {$opt(addr_map) eq "BANK_ROW_COLUMN" ? "brc" : "rbc"}]
set p3_bd_fit [expr {$opt(fit) ne ""}]
if { $p3_bd_fit } {
    set fv [split $opt(fit) ,]
    if { [llength $fv] != 4 } { error "-fit N_ENT,SLICE_BUF,BV_ALL40,Q_BRAM" }
    set tag "fit[join $fv {}]"
}
if { $opt(proj_dir) eq "" } { set opt(proj_dir) "$::env(HOME)/mmss_build/p3_$tag" }
if { [string first " " $opt(proj_dir)] >= 0 } { error "proj_dir에 공백이 없어야 한다: $opt(proj_dir)" }
set pd $opt(proj_dir)
puts "INFO: proj_dir = $pd, addr_map = $opt(addr_map)"

create_project p3_meas $pd -part $part -force
set_property target_language Verilog [current_project]

# ---- MIG: P1.6 설정 파일에서 주소 매핑만 바꾼다 ----
create_ip -name mig_7series -vendor xilinx.com -library ip -module_name mig_ddr3
set ipdir [get_property IP_DIR [get_ips mig_ddr3]]
set fh [open "$repo_root/hardware/board_test/p06_mig/mig_ddr3.prj" r]; set prj [read $fh]; close $fh
set n [regsub {<UserMemoryAddressMap>[A-Z_]+</UserMemoryAddressMap>} $prj \
    "<UserMemoryAddressMap>$opt(addr_map)</UserMemoryAddressMap>" prj]
if { $n != 1 } { error "prj 주소 매핑 치환 실패" }
set fh [open "$ipdir/mig_ddr3.prj" w]; puts -nonewline $fh $prj; close $fh
set_property -dict [list \
    CONFIG.XML_INPUT_FILE        {mig_ddr3.prj} \
    CONFIG.RESET_BOARD_INTERFACE {Custom} \
    CONFIG.MIG_DONT_TOUCH_PARAM  {Custom} \
    CONFIG.BOARD_MIG_PARAM       {Custom}] [get_ips mig_ddr3]
generate_target all [get_ips mig_ddr3]

# ---- 블록 디자인 ----
source "$script_dir/p3_bd.tcl"
set bdf [get_files p3_bd.bd]
generate_target all $bdf
add_files -norecurse [make_wrapper -files $bdf -top]

# ---- VIO ----
create_ip -name vio -vendor xilinx.com -library ip -module_name vio_p3
set_property -dict [list \
    CONFIG.C_NUM_PROBE_IN  {4} \
    CONFIG.C_NUM_PROBE_OUT {0} \
    CONFIG.C_EN_PROBE_IN_ACTIVITY {0} \
    CONFIG.C_PROBE_IN0_WIDTH {1} \
    CONFIG.C_PROBE_IN1_WIDTH {1} \
    CONFIG.C_PROBE_IN2_WIDTH {1} \
    CONFIG.C_PROBE_IN3_WIDTH {16}] [get_ips vio_p3]
generate_target all [get_ips vio_p3]

# ---- 소스·제약 ----
foreach f {p3_top.v p3_core.v ddr_tgen.v} { add_files -norecurse [list "$script_dir/$f"] }
if { $p3_bd_fit } {
    add_files -norecurse [list "$script_dir/mem_fit.v"]
    lassign $fv ne sb bv qb
    set_property verilog_define [list P3_FIT FIT_N_ENT=$ne FIT_SLICE_BUF=$sb FIT_BV_ALL40=$bv FIT_Q_BRAM=$qb] \
        [get_filesets sources_1]
}
add_files -fileset constrs_1 -norecurse [list "$script_dir/p3.xdc"]
# PCIe 클럭(txoutclk)은 XDMA가 OOC로 합성되어 합성 단계에는 없다 → 구현에서만 쓴다
set_property USED_IN_SYNTHESIS false [get_files p3.xdc]
foreach x {io pcie} {
    add_files -fileset constrs_1 -norecurse [list "$repo_root/hardware/constraints/ax7a200b_$x.xdc"]
}
set_property top p3_top [current_fileset]
update_compile_order -fileset sources_1

# ---- 빌드 ----
launch_runs synth_1 -jobs $opt(jobs)
wait_on_run synth_1
if { [get_property PROGRESS [get_runs synth_1]] ne "100%" } { error "합성 실패" }
if { $p3_bd_fit } {
    launch_runs impl_1 -jobs $opt(jobs)
} else {
    launch_runs impl_1 -to_step write_bitstream -jobs $opt(jobs)
}
wait_on_run impl_1
if { [get_property PROGRESS [get_runs impl_1]] ne "100%" } { error "구현 실패" }

open_run impl_1
set rpt "$pd/reports"
file mkdir $rpt
report_utilization    -file "$rpt/utilization.rpt"
report_utilization    -hierarchical -hierarchical_depth 4 -file "$rpt/utilization_hier.rpt"
report_ram_utilization -file "$rpt/ram_utilization.rpt"
report_timing_summary -file "$rpt/timing_summary.rpt" -max_paths 10
report_clock_interaction -file "$rpt/clock_interaction.rpt"
report_drc            -file "$rpt/drc.rpt"
write_debug_probes -force "$pd/p3_top.ltx"
foreach c [get_cells -hierarchical -filter {REF_NAME == GTPE2_CHANNEL}] {
    puts "INFO: GT [get_property LOC $c] ← $c"
}
set wns [get_property SLACK [get_timing_paths -setup -max_paths 1 -nworst 1]]
set whs [get_property SLACK [get_timing_paths -hold  -max_paths 1 -nworst 1]]
puts "INFO: WNS = $wns ns, WHS = $whs ns"
if { $p3_bd_fit } { puts "INFO: fit 실험 — 비트스트림 생략"; return }
set bit [lindex [glob $pd/p3_meas.runs/impl_1/*.bit] 0]
file copy -force $bit "$pd/p3_top.bit"
write_cfgmem -force -format mcs -size 16 -interface SPIx4 \
    -loadbit [list up 0x00000000 "$pd/p3_top.bit"] -file "$pd/p3_top.mcs"
puts "INFO: 비트스트림 → $pd/p3_top.bit, MCS → $pd/p3_top.mcs"
