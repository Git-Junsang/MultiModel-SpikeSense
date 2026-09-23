## ============================================================
## p07.xdc — P0.7 XDMA 시험 설계 전용 제약
## ============================================================
## 공통 제약은 ax7a200b_base.xdc(200 MHz·구성), ax7a200b_io.xdc(LED·버튼),
## ax7a200b_pcie.xdc(PCIe 참조 클럭)를 함께 쓴다. GT 채널 위치는 XDMA IP XDC를 따른다.
##
## PERST# 후보: 매뉴얼 Part 2.9 보드 간 커넥터 표의 3.3 V 핀 중 캐리어보드
## 주변장치 표(Part 3.x)에 나오지 않는 핀. 풀다운 입력으로 두고 VIO로 읽는다.
## 순서는 perst_cand[0..13].
## ============================================================
set_property -dict { PACKAGE_PIN V15 IOSTANDARD LVCMOS33 PULLDOWN true } [get_ports {perst_cand[0]}]
set_property -dict { PACKAGE_PIN P20 IOSTANDARD LVCMOS33 PULLDOWN true } [get_ports {perst_cand[1]}]
set_property -dict { PACKAGE_PIN N15 IOSTANDARD LVCMOS33 PULLDOWN true } [get_ports {perst_cand[2]}]
set_property -dict { PACKAGE_PIN L18 IOSTANDARD LVCMOS33 PULLDOWN true } [get_ports {perst_cand[3]}]
set_property -dict { PACKAGE_PIN K16 IOSTANDARD LVCMOS33 PULLDOWN true } [get_ports {perst_cand[4]}]
set_property -dict { PACKAGE_PIN L16 IOSTANDARD LVCMOS33 PULLDOWN true } [get_ports {perst_cand[5]}]
set_property -dict { PACKAGE_PIN F21 IOSTANDARD LVCMOS33 PULLDOWN true } [get_ports {perst_cand[6]}]
set_property -dict { PACKAGE_PIN A21 IOSTANDARD LVCMOS33 PULLDOWN true } [get_ports {perst_cand[7]}]
set_property -dict { PACKAGE_PIN B21 IOSTANDARD LVCMOS33 PULLDOWN true } [get_ports {perst_cand[8]}]
set_property -dict { PACKAGE_PIN D22 IOSTANDARD LVCMOS33 PULLDOWN true } [get_ports {perst_cand[9]}]
set_property -dict { PACKAGE_PIN E22 IOSTANDARD LVCMOS33 PULLDOWN true } [get_ports {perst_cand[10]}]
set_property -dict { PACKAGE_PIN D21 IOSTANDARD LVCMOS33 PULLDOWN true } [get_ports {perst_cand[11]}]
set_property -dict { PACKAGE_PIN E21 IOSTANDARD LVCMOS33 PULLDOWN true } [get_ports {perst_cand[12]}]
set_property -dict { PACKAGE_PIN B13 IOSTANDARD LVCMOS33 PULLDOWN true } [get_ports {perst_cand[13]}]
set_false_path -from [get_ports {perst_cand[*]}]

## 200 MHz 시스템 클럭과 PCIe 클럭은 비동기다. VIO로 넘기는 상태 신호만 교차한다.
## PCIe 사용자 클럭(userclk1, axi_aclk)은 참조 클럭이 아니라 IP XDC가 GT TXOUTCLK에
## 만든 txoutclk_x0y0에서 파생되므로 둘 다 그룹에 넣는다.
set_clock_groups -asynchronous -group [get_clocks sys_clk] \
    -group [get_clocks -include_generated_clocks {pcie_refclk txoutclk_x0y0}]
