## ============================================================
## p06.xdc — P0.6 MIG 시험 설계 전용 제약
## ============================================================
## sys_clk(R4/T4)와 DDR3 핀은 MIG IP XDC가 넣으므로 ax7a200b_base.xdc를 쓰지 않고
## base.xdc의 구성 설정만 옮겨 적는다. LED·버튼은 ax7a200b_io.xdc를 쓴다.
## ============================================================
set_property CFGBVS VCCO                         [current_design]
set_property CONFIG_VOLTAGE 3.3                  [current_design]
set_property BITSTREAM.GENERAL.COMPRESS TRUE     [current_design]
set_property BITSTREAM.CONFIG.SPI_BUSWIDTH 4     [current_design]
set_property BITSTREAM.CONFIG.CONFIGRATE 50      [current_design]
set_property CONFIG_MODE SPIx4                   [current_design]
