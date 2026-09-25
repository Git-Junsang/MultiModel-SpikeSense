## ============================================================
## p07b.xdc — P0.7 비교용: Xilinx XDMA 예제 설계(xilinx_dma_pcie_ep)를 AX7A200B 핀에 맞춘 제약
## ============================================================
## 예제 탑은 sys_clk_p/n(PCIe 100 MHz 참조 클럭)과 sys_rst_n만 받는다.
## sys_rst_n은 PERST# 핀을 모르므로 캐리어보드 RESET 버튼(F15, 평소 High)에 연결한다.
## ============================================================
set_property PACKAGE_PIN F10 [get_ports sys_clk_p]
set_property PACKAGE_PIN E10 [get_ports sys_clk_n]
create_clock -name sys_clk -period 10.000 [get_ports sys_clk_p]

set_property -dict { PACKAGE_PIN F15 IOSTANDARD LVCMOS33 PULLUP true } [get_ports sys_rst_n]
set_false_path -from [get_ports sys_rst_n]

set_property CFGBVS VCCO        [current_design]
set_property CONFIG_VOLTAGE 3.3 [current_design]
set_property BITSTREAM.GENERAL.COMPRESS TRUE [current_design]
