## ============================================================
## ax7a200b_pcie.xdc — AX7A200B PCIe Gen2 ×2 (GTP BANK216)
## ============================================================
## 근거 : documents/manual/AX7A200_User_Manual.pdf (Rev 1.0) Part 3.4
##        커넥터는 ×4 크기, 전기적으로 ×2. 참조 클럭 100 MHz는 Host 슬롯에서 받는다.
## 레인 ↔ GTP 채널 대응 (Vivado 2026.1 get_package_pins로 확인):
##   lane0: TX D7/C7, RX D9/C9  = MGTPTX/RX3_216 = GTPE2_CHANNEL_X0Y7
##   lane1: TX B6/A6, RX B10/A10 = MGTPTX/RX2_216 = GTPE2_CHANNEL_X0Y6
##   REFCLK: F10/E10 = MGTREFCLK1_216 (125 MHz 수정은 MGTREFCLK0_216 F6/E6, SFP용)
##
## 포트명은 200 MHz 시스템 클럭(sys_clk_p/n)과 겹치지 않도록 pcie_* 접두어를 쓴다.
## XDMA 예제 설계(sys_clk_p/n, sys_rst_n)를 그대로 쓸 때는 탑 모듈에서 이름을 맞춘다.
## GT 직렬 핀(pci_exp_txp/rxp)은 IP가 GT 채널 LOC로 배치하므로 PACKAGE_PIN을
## 직접 주지 않는다. IP 설정(P0.7)에서 lane0 = X0Y7이 되도록 맞추고, IP가 만든
## LOC가 아래 대응과 같은지 확인한다.
## ============================================================

## ---- 참조 클럭 100 MHz (MGTREFCLK1_216) ----
## IBUFDS_GTE2로 받는다. GT 전용 핀이라 IOSTANDARD를 지정하지 않는다.
set_property PACKAGE_PIN F10 [get_ports pcie_refclk_p]
set_property PACKAGE_PIN E10 [get_ports pcie_refclk_n]
create_clock -name pcie_refclk -period 10.000 [get_ports pcie_refclk_p]

## ---- GT 채널 위치 ----
## 7 Series PCIe IP 예제 XDC 형식. 셀 경로는 IP 버전·설정에 따라 다르므로
## P0.7에서 생성된 계층 경로로 바꿔 적용한다.
# set_property LOC GTPE2_CHANNEL_X0Y7 [get_cells -hierarchical -filter {NAME =~ *gtp_channel.gtpe2_channel_i && NAME =~ *pipe_lane[0]*}]
# set_property LOC GTPE2_CHANNEL_X0Y6 [get_cells -hierarchical -filter {NAME =~ *gtp_channel.gtpe2_channel_i && NAME =~ *pipe_lane[1]*}]

## ---- PERST# (Host 슬롯 리셋, Active-Low) ----
## 매뉴얼 Figure 3-4-1에 PCIE_PERST 신호는 있으나 FPGA 핀 번호가 표에 없다.
## [미확인] ALINX 예제 설계 또는 캐리어보드 회로도로 핀을 확인한 뒤 채운다(P0.7).
# set_property -dict { PACKAGE_PIN ??? IOSTANDARD LVCMOS33 PULLUP true } [get_ports pcie_perst_n]
# set_false_path -from [get_ports pcie_perst_n]
