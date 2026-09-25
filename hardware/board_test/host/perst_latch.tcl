# ============================================================
# perst_latch.tcl — PERST# 후보 핀 래치 초기화 / 읽기 (P0.7)
# ============================================================
#   vivado -mode batch -source perst_latch.tcl -tclargs -ltx <ltx> -act clear|read
# clear: ever_high/ever_low 래치를 지운다(Host 재부팅 직전에 실행).
# read : 래치와 현재값을 출력한다(재부팅 후 실행).
# ============================================================
set opt(ltx) ""; set opt(act) "read"
for {set i 0} {$i < [llength $argv]} {incr i 2} { set opt([string range [lindex $argv $i] 1 end]) [lindex $argv [expr {$i+1}]] }
open_hw_manager
connect_hw_server -url localhost:3121
open_hw_target [lindex [get_hw_targets] 0]
set dev [lindex [get_hw_devices xc7a200t*] 0]
current_hw_device $dev
set_property PROBES.FILE $opt(ltx) $dev
refresh_hw_device $dev
set vio [lindex [get_hw_vios -of_objects $dev] 0]
if { $opt(act) eq "clear" } {
    set clr [lindex [get_hw_probes -of_objects $vio -filter {TYPE == vio_output && NAME.SHORT =~ *lat_clr*}] 0]
    set_property OUTPUT_VALUE 1 $clr; commit_hw_vio $clr
    after 300
    set_property OUTPUT_VALUE 0 $clr; commit_hw_vio $clr
    after 300
    puts "INFO: 래치 초기화 완료"
}
refresh_hw_vio $vio
foreach p [get_hw_probes -of_objects $vio -filter {TYPE == vio_input}] {
    puts "VIO [get_property NAME.SHORT $p] = [get_property INPUT_VALUE $p]"
}
close_hw_target; disconnect_hw_server; close_hw_manager
