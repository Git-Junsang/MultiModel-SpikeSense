## ============================================================
## ax7a200b_top.xdc — accel_top 전용 제약 (구성 설정, LED)
## ============================================================
## sys_clk(R4/T4)와 DDR3 핀은 MIG IP XDC가 넣으므로 ax7a200b_base.xdc를 쓰지 않고 구성 설정만 옮겨 적는다(p3.xdc와 같다).
## LED·버튼 핀은 ax7a200b_io.xdc, Ethernet은 ax7a200b_eth.xdc.
## clock 경계: ui_clk ↔ gtx_clk(125 MHz) ↔ rgmii_rx_clk 사이는 verilog-ethernet의 async FIFO와 동기화 FF뿐이고
##   그 제약(set_max_delay -datapath_only, ASYNC_REG)은 hardware/ip/verilog-ethernet/**/syn/vivado/*.tcl이 건다.
##   set_clock_groups -asynchronous는 그 set_max_delay보다 우선해 Gray pointer 지연 제한을 없애므로 쓰지 않는다.
## ============================================================
set_property CFGBVS VCCO                         [current_design]
set_property CONFIG_VOLTAGE 3.3                  [current_design]
set_property BITSTREAM.GENERAL.COMPRESS TRUE     [current_design]
set_property BITSTREAM.CONFIG.SPI_BUSWIDTH 4     [current_design]
set_property BITSTREAM.CONFIG.CONFIGRATE 50      [current_design]
set_property CONFIG_MODE SPIx4                   [current_design]

## LED는 사람이 보는 상태 표시다.
set_false_path -to [get_ports {led_core led_n[*]}]
