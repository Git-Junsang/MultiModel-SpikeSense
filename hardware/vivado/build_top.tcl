# ============================================================
# build_top.tcl — accel_top 전체 빌드 (MIG + accel_sys + Ethernet): 합성·배치·배선·bitstream (P4.10)
# ============================================================
# 실행 (저장소 root 또는 그 사본 root에서). 보드에 쓰지 않는다.
#   vivado -mode batch -nojournal -source hardware/vivado/build_top.tcl \
#       -tclargs [-proj_dir <공백 없는 경로>] [-jobs N] [-rx_idelay TAP] [-out <report 폴더>]
# 필요한 파일(사본도 같은 상대 경로): hardware/src/*.v, hardware/ip/verilog-ethernet/,
#   hardware/constraints/ax7a200b_{io,eth,top}.xdc, hardware/board_test/p06_mig/mig_ddr3.prj, 이 script.
# MIG: p06 설정 파일에서 주소 배치만 ROW_BANK_COLUMN으로 바꾼다(P3.1, build_p3.tcl과 같은 방식).
#   MIG 생성은 project 경로에 공백이 있으면 실패하므로 기본 project는 ~/mmss_build/top.
# -rx_idelay: eth_link RGMII 수신 IDELAYE2 tap(0 = 두지 않음, 1 tap ≈ 78 ps). 기본 8은 보드 실측과 STA 모델을 둘 다 만족한다(P5.2). 송신 위상 기본값은 accel_top.v TX_PS.
# 산출물: <out>/ (기본 hardware/vivado/build/top) timing·clock interaction·utilization·IO·DRC report, worst_paths.txt,
#   rx_idelay_sweep.txt(-rx_idelay > 0일 때 tap 0–31 수신 setup·hold 여유),
#   accel_top.bit, route.dcp
# ============================================================

set script_dir [file normalize [file dirname [info script]]]
set repo_root  [file normalize "$script_dir/../.."]
set part       "xc7a200tfbg484-2"

set opt(proj_dir)  "$::env(HOME)/mmss_build/top"
set opt(jobs)      8
set opt(rx_idelay) 8
set opt(out)       "$repo_root/hardware/vivado/build/top"
for {set i 0} {$i < [llength $argv]} {incr i 2} {
    set k [lindex $argv $i]; set v [lindex $argv [expr {$i+1}]]
    switch -- $k {
        -proj_dir  { set opt(proj_dir) [file normalize $v] }
        -jobs      { set opt(jobs) $v }
        -rx_idelay { set opt(rx_idelay) $v }
        -out       { set opt(out) [file normalize $v] }
        default    { error "알 수 없는 옵션: $k" }
    }
}
if { [string first " " $opt(proj_dir)] >= 0 } { error "proj_dir에 공백이 없어야 한다: $opt(proj_dir)" }
set pd $opt(proj_dir)
puts "INFO: proj_dir = $pd, rx_idelay = $opt(rx_idelay), out = $opt(out)"
set_param general.maxThreads $opt(jobs)

create_project accel_top $pd -part $part -force
set_property target_language Verilog [current_project]

# ---- MIG ----
create_ip -name mig_7series -vendor xilinx.com -library ip -module_name mig_ddr3
set ipdir [get_property IP_DIR [get_ips mig_ddr3]]
set fh [open "$repo_root/hardware/board_test/p06_mig/mig_ddr3.prj" r]; set prj [read $fh]; close $fh
set n [regsub {<UserMemoryAddressMap>[A-Z_]+</UserMemoryAddressMap>} $prj \
    "<UserMemoryAddressMap>ROW_BANK_COLUMN</UserMemoryAddressMap>" prj]
if { $n != 1 } { error "prj 주소 배치 치환 실패" }
set fh [open "$ipdir/mig_ddr3.prj" w]; puts -nonewline $fh $prj; close $fh
set_property -dict [list \
    CONFIG.XML_INPUT_FILE        {mig_ddr3.prj} \
    CONFIG.RESET_BOARD_INTERFACE {Custom} \
    CONFIG.MIG_DONT_TOUCH_PARAM  {Custom} \
    CONFIG.BOARD_MIG_PARAM       {Custom}] [get_ips mig_ddr3]
generate_target all [get_ips mig_ddr3]

# ---- source ----
set eth "$repo_root/hardware/ip/verilog-ethernet"
foreach f [concat [glob $repo_root/hardware/src/*.v] [glob $eth/rtl/*.v] [glob $eth/lib/axis/rtl/*.v]] {
    add_files -norecurse [list $f]
}
set_property top accel_top [current_fileset]
set_property generic "RX_IDELAY=$opt(rx_idelay)" [current_fileset]

# ---- 제약: 보드 XDC + verilog-ethernet clock 경계 script(원본 예제처럼 XDC 목록에 넣는다) ----
foreach x {io eth top} {
    add_files -fileset constrs_1 -norecurse [list "$repo_root/hardware/constraints/ax7a200b_$x.xdc"]
}
foreach t [list $eth/syn/vivado/eth_mac_1g_rgmii.tcl $eth/syn/vivado/eth_mac_fifo.tcl $eth/syn/vivado/rgmii_phy_if.tcl \
               $eth/lib/axis/syn/vivado/axis_async_fifo.tcl $eth/lib/axis/syn/vivado/sync_reset.tcl] {
    add_files -fileset constrs_1 -norecurse [list $t]
}
update_compile_order -fileset sources_1

# ---- 빌드 ----
set_property STEPS.PHYS_OPT_DESIGN.IS_ENABLED true [get_runs impl_1]
launch_runs synth_1 -jobs $opt(jobs)
wait_on_run synth_1
if { [get_property PROGRESS [get_runs synth_1]] ne "100%" } { error "합성 실패" }
launch_runs impl_1 -to_step write_bitstream -jobs $opt(jobs)
wait_on_run impl_1
if { [get_property PROGRESS [get_runs impl_1]] ne "100%" } { error "구현 실패" }

# ---- report ----
open_run impl_1
set rpt $opt(out)
file mkdir $rpt
report_timing_summary    -file "$rpt/timing_summary.rpt" -max_paths 10 -report_unconstrained
report_clock_interaction -file "$rpt/clock_interaction.rpt"
report_clock_utilization -file "$rpt/clock_utilization.rpt"
report_utilization       -file "$rpt/utilization.rpt"
report_utilization       -hierarchical -hierarchical_depth 3 -file "$rpt/utilization_hier.rpt"
report_io                -file "$rpt/io.rpt"
report_drc               -file "$rpt/drc.rpt"
report_methodology       -file "$rpt/methodology.rpt"
report_timing -delay_type min_max -max_paths 20 -sort_by group -input_pins \
    -from [get_ports {rgmii_rxd[*] rgmii_rx_ctl}] -file "$rpt/rgmii_rx.rpt"
report_timing -delay_type min_max -max_paths 20 -sort_by group -input_pins \
    -to [get_ports {rgmii_txd[*] rgmii_tx_ctl}] -file "$rpt/rgmii_tx.rpt"

# 가장 나쁜 setup 경로 10개: 시작, 끝, logic level, 경로 지연 중 배선 비율
set fh [open "$rpt/worst_paths.txt" w]
puts $fh "slack_ns\tlevels\tdelay_ns\troute_pct\tclock\tstart\tend"
foreach p [get_timing_paths -setup -max_paths 10 -nworst 1 -sort_by slack] {
    set d [get_property DATAPATH_DELAY $p]
    set r [get_property DATAPATH_NET_DELAY $p]
    set pct [expr {$d > 0 ? round(100.0 * $r / $d) : 0}]
    puts $fh [format "%s\t%s\t%s\t%d\t%s\t%s\t%s" [get_property SLACK $p] [get_property LOGIC_LEVELS $p] $d $pct \
        [get_property ENDPOINT_CLOCK $p] [get_property STARTPOINT_PIN $p] [get_property ENDPOINT_PIN $p]]
}
close $fh

# RX IDELAY tap별 수신 여유(배선 그대로 tap 값만 바꿔 STA). 보드에서 tap을 고를 때 본다. 끝나면 원래 값으로 되돌린다.
set dly [get_cells -hierarchical -filter {REF_NAME == IDELAYE2 && NAME =~ *u_eth*}]
if { [llength $dly] > 0 } {
    set rxp [get_ports {rgmii_rxd[*] rgmii_rx_ctl}]
    set fh [open "$rpt/rx_idelay_sweep.txt" w]
    puts $fh "tap\tsetup_ns\thold_ns"
    for {set t 0} {$t < 32} {incr t} {
        set_property IDELAY_VALUE $t $dly
        puts $fh [format "%d\t%s\t%s" $t [get_property SLACK [get_timing_paths -from $rxp -setup -max_paths 1 -nworst 1]] \
            [get_property SLACK [get_timing_paths -from $rxp -hold -max_paths 1 -nworst 1]]]
    }
    close $fh
    set_property IDELAY_VALUE $opt(rx_idelay) $dly
}

set wns [get_property SLACK [get_timing_paths -setup -max_paths 1 -nworst 1]]
set whs [get_property SLACK [get_timing_paths -hold  -max_paths 1 -nworst 1]]
puts "INFO: WNS = $wns ns, WHS = $whs ns (TNS는 timing_summary.rpt)"

write_checkpoint -force "$rpt/route.dcp"
set bit [lindex [glob $pd/accel_top.runs/impl_1/*.bit] 0]
file copy -force $bit "$rpt/accel_top.bit"
puts "INFO: bitstream → $rpt/accel_top.bit"
