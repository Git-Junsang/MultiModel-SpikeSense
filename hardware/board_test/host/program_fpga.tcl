# ============================================================
# program_fpga.tcl — FPGA Host에서 JTAG로 비트스트림 다운로드, VIO 읽기
# ============================================================
# FPGA Host(sdsl-llm)의 로컬 JTAG에서 실행한다 (ENVIRONMENT.md §4 작업 흐름).
#
#   vivado -mode batch -nojournal -nolog -source program_fpga.tcl -tclargs \
#       -bit <file.bit> [-ltx <file.ltx>] [-wait <초>] [-reads <횟수>] [-period <초>]
#   vivado -mode batch ... -tclargs -ltx <file.ltx> -reads 3   (다운로드 없이 VIO만 읽기)
#
# -ltx가 있으면 다운로드 후 -wait 초 기다린 뒤 모든 VIO 입력 probe 값을
# -period 초 간격으로 -reads번 출력한다. 출력 형식: "VIO <probe> = <값>".
# ============================================================

set opt(bit)    ""
set opt(ltx)    ""
set opt(wait)   2
set opt(reads)  1
set opt(period) 1
for {set i 0} {$i < [llength $argv]} {incr i 2} {
    set k [string range [lindex $argv $i] 1 end]
    if { ![info exists opt($k)] } { error "알 수 없는 옵션: [lindex $argv $i]" }
    set opt($k) [lindex $argv [expr {$i+1}]]
}

open_hw_manager
connect_hw_server -url localhost:3121
set tgt [lindex [get_hw_targets] 0]
open_hw_target $tgt
set dev [lindex [get_hw_devices xc7a200t*] 0]
current_hw_device $dev
puts "INFO: target = $tgt, device = $dev"

if { $opt(bit) ne "" } {
    set_property PROGRAM.FILE $opt(bit) $dev
    if { $opt(ltx) ne "" } { set_property PROBES.FILE $opt(ltx) $dev }
    program_hw_devices $dev
    puts "INFO: 다운로드 완료 → $opt(bit)"
} elseif { $opt(ltx) ne "" } {
    set_property PROBES.FILE $opt(ltx) $dev
}
refresh_hw_device $dev
puts "INFO: DONE = [get_property REGISTER.CONFIG_STATUS.BIT14_DONE_PIN $dev]"

if { $opt(ltx) ne "" } {
    after [expr {int($opt(wait) * 1000)}]
    set vios [get_hw_vios -of_objects $dev]
    for {set r 0} {$r < $opt(reads)} {incr r} {
        if { $r > 0 } { after [expr {int($opt(period) * 1000)}] }
        puts "INFO: read $r ([clock format [clock seconds] -format %H:%M:%S])"
        foreach v $vios {
            refresh_hw_vio $v
            foreach p [get_hw_probes -of_objects $v] {
                puts "VIO $p = [get_property INPUT_VALUE $p]"
            }
        }
    }
}

close_hw_target
disconnect_hw_server
close_hw_manager
