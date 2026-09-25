# ============================================================
# pcie_reset_vio.tcl — VIO probe_out0으로 PCIe 코어를 리셋하고 상태를 읽는다 (P0.7)
# ============================================================
#   vivado -mode batch -source pcie_reset_vio.tcl -tclargs -ltx <file.ltx> [-bit <file.bit>]
# 비트스트림을 주면 먼저 다운로드한다. 리셋을 0.5초 걸었다 풀고 2초 뒤 상태를 읽는다.
# ============================================================
set opt(ltx) ""; set opt(bit) ""
for {set i 0} {$i < [llength $argv]} {incr i 2} { set opt([string range [lindex $argv $i] 1 end]) [lindex $argv [expr {$i+1}]] }
open_hw_manager
connect_hw_server -url localhost:3121
open_hw_target [lindex [get_hw_targets] 0]
set dev [lindex [get_hw_devices xc7a200t*] 0]
current_hw_device $dev
if { $opt(bit) ne "" } { set_property PROGRAM.FILE $opt(bit) $dev }
set_property PROBES.FILE $opt(ltx) $dev
if { $opt(bit) ne "" } { program_hw_devices $dev }
refresh_hw_device $dev
set vio [lindex [get_hw_vios -of_objects $dev] 0]
proc show {vio tag} {
    refresh_hw_vio $vio
    set out ""
    foreach p [get_hw_probes -of_objects $vio] {
        if { [get_property TYPE $p] eq "vio_input" } { append out "[get_property NAME.SHORT $p]=[get_property INPUT_VALUE $p] " }
    }
    puts "VIOSTATE $tag: $out"
}
show $vio "before"
set rst [lindex [get_hw_probes -of_objects $vio -filter {TYPE == vio_output}] 0]
set_property OUTPUT_VALUE 1 $rst; commit_hw_vio $rst
after 500
set_property OUTPUT_VALUE 0 $rst; commit_hw_vio $rst
after 2000
show $vio "after"
close_hw_target; disconnect_hw_server; close_hw_manager
