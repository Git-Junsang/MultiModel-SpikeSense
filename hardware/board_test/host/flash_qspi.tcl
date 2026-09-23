# ============================================================
# flash_qspi.tcl — MCS 생성(개발 서버) / QSPI 기록(FPGA Host)
# ============================================================
# 보드 QSPI: N25Q128 3.3 V, 128 Mbit (매뉴얼 Part 2.5). 비트스트림은 SPIx4 설정.
#
# 1) MCS 생성 (개발 서버):
#    vivado -mode batch -source flash_qspi.tcl -tclargs -mode mcs -bit <file.bit> -mcs <out.mcs>
# 2) QSPI 기록·검증 (FPGA Host, 로컬 JTAG):
#    vivado -mode batch -source flash_qspi.tcl -tclargs -mode flash -mcs <file.mcs>
#    기록 후 FPGA를 플래시에서 다시 구성한다(boot_hw_device).
# ============================================================
set opt(mode) ""; set opt(bit) ""; set opt(mcs) ""
for {set i 0} {$i < [llength $argv]} {incr i 2} {
    set opt([string range [lindex $argv $i] 1 end]) [lindex $argv [expr {$i+1}]]
}
set cfgmem_part "mt25ql128-spi-x1_x2_x4"

if { $opt(mode) eq "mcs" } {
    write_cfgmem -force -format mcs -size 16 -interface SPIx4 \
        -loadbit [list up 0x00000000 $opt(bit)] -file $opt(mcs)
    puts "INFO: MCS → $opt(mcs)"
} elseif { $opt(mode) eq "flash" } {
    open_hw_manager
    connect_hw_server -url localhost:3121
    open_hw_target [lindex [get_hw_targets] 0]
    set dev [lindex [get_hw_devices xc7a200t*] 0]
    current_hw_device $dev
    set parts [get_cfgmem_parts $cfgmem_part]
    if { [llength $parts] == 0 } { set parts [get_cfgmem_parts {n25q128-3.3v-spi-x1_x2_x4}] }
    puts "INFO: cfgmem part = $parts"
    create_hw_cfgmem -hw_device $dev -mem_dev [lindex $parts 0]
    set cm [get_property PROGRAM.HW_CFGMEM $dev]
    set_property PROGRAM.FILES [list $opt(mcs)] $cm
    set_property PROGRAM.ADDRESS_RANGE {use_file} $cm
    set_property PROGRAM.BLANK_CHECK 0 $cm
    set_property PROGRAM.ERASE  1 $cm
    set_property PROGRAM.CFG_PROGRAM 1 $cm
    set_property PROGRAM.VERIFY 1 $cm
    create_hw_bitstream -hw_device $dev [get_property PROGRAM.HW_CFGMEM_BITFILE $dev]
    program_hw_devices $dev
    refresh_hw_device $dev
    program_hw_cfgmem -hw_cfgmem $cm
    puts "INFO: QSPI 기록·검증 완료 → $opt(mcs)"
    boot_hw_device $dev
    after 2000
    refresh_hw_device $dev
    puts "INFO: 플래시 부팅 DONE = [get_property REGISTER.CONFIG_STATUS.BIT14_DONE_PIN $dev]"
    close_hw_target; disconnect_hw_server; close_hw_manager
} else {
    error "-mode mcs | flash"
}
