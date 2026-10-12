## ============================================================
## p3.xdc — P3 측정 설계 전용 제약
## ============================================================
## sys_clk(R4/T4)와 DDR3 핀은 MIG IP XDC가 넣으므로 ax7a200b_base.xdc를 쓰지 않고
## 구성 설정만 옮겨 적는다(p06.xdc와 같다). LED·버튼은 ax7a200b_io.xdc,
## PCIe 참조 클럭·PERST#는 ax7a200b_pcie.xdc를 쓴다.
## ============================================================
set_property CFGBVS VCCO                         [current_design]
set_property CONFIG_VOLTAGE 3.3                  [current_design]
set_property BITSTREAM.GENERAL.COMPRESS TRUE     [current_design]
set_property BITSTREAM.CONFIG.SPI_BUSWIDTH 4     [current_design]
set_property BITSTREAM.CONFIG.CONFIGRATE 50      [current_design]
set_property CONFIG_MODE SPIx4                   [current_design]

## MIG 클럭(sys_clk_p → ui_clk)과 PCIe 클럭(refclk → txoutclk → axi_aclk)은 비동기다.
## 두 도메인을 잇는 것은 SmartConnect의 클럭 변환기(비동기 FIFO)와 lnk_up 2단 동기화뿐이다.
set_clock_groups -asynchronous \
    -group [get_clocks -include_generated_clocks sys_clk_p] \
    -group [get_clocks -include_generated_clocks {pcie_refclk txoutclk_x0y0}]
