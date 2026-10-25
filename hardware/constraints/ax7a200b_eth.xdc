## ============================================================
## ax7a200b_eth.xdc — AX7A200B Gigabit Ethernet (KSZ9031RNX, RGMII)
## ============================================================
## 근거 : documents/manual/AX7A200_User_Manual.pdf (Rev 1.0) Part 3.2 핀, Part 2.2 뱅크 전압
##        모든 핀이 BANK14(3.3 V) → LVCMOS33. RXC(V18)는 clock 입력 가능 핀(BUFIO·BUFR).
## 포트명은 accel_top(hardware/src/accel_top.v)을 따른다.
## 수신: MDIO를 쓰지 않아 KSZ9031 pad skew가 기본값이다. 이때 PHY 안에서 RXC를 약 1.2 ns 늦춰 낸다
##       (RGMII_IDRX 1.2 ns, IDTX 0 ns: Linux drivers/net/phy/micrel.c). 핀에서 data는 RXC edge보다 1.2 ns 먼저 바뀐다.
##       PHY 송신 skew ±0.5 ns를 더해 data 변화 = 앞 edge 뒤 4.0 - 1.2 ± 0.5 ns(-max 3.3 / -min 2.3, 두 edge 모두).
##       기판 배선 차는 모른다(0으로 둔다). 이 조건에서 hold 쪽이 좁아 data에 IDELAY(RX_IDELAY)를 두어 가운데로 옮긴다.
## 송신: FPGA가 TXC를 gtx_clk90(90° = 2 ns 늦게)으로 ODDR에서 낸다. PHY 쪽 setup·hold 1.0 ns(RGMII v1.3)를 건다.
## ============================================================

## ---- 핀 (Part 3.2) ----
set_property -dict { PACKAGE_PIN P15 IOSTANDARD LVCMOS33 SLEW FAST DRIVE 16 } [get_ports rgmii_tx_clk]
set_property -dict { PACKAGE_PIN N14 IOSTANDARD LVCMOS33 SLEW FAST DRIVE 16 } [get_ports {rgmii_txd[0]}]
set_property -dict { PACKAGE_PIN P16 IOSTANDARD LVCMOS33 SLEW FAST DRIVE 16 } [get_ports {rgmii_txd[1]}]
set_property -dict { PACKAGE_PIN R17 IOSTANDARD LVCMOS33 SLEW FAST DRIVE 16 } [get_ports {rgmii_txd[2]}]
set_property -dict { PACKAGE_PIN R16 IOSTANDARD LVCMOS33 SLEW FAST DRIVE 16 } [get_ports {rgmii_txd[3]}]
set_property -dict { PACKAGE_PIN N17 IOSTANDARD LVCMOS33 SLEW FAST DRIVE 16 } [get_ports rgmii_tx_ctl]
set_property -dict { PACKAGE_PIN V18 IOSTANDARD LVCMOS33 } [get_ports rgmii_rx_clk]
set_property -dict { PACKAGE_PIN P19 IOSTANDARD LVCMOS33 } [get_ports {rgmii_rxd[0]}]
set_property -dict { PACKAGE_PIN U18 IOSTANDARD LVCMOS33 } [get_ports {rgmii_rxd[1]}]
set_property -dict { PACKAGE_PIN U17 IOSTANDARD LVCMOS33 } [get_ports {rgmii_rxd[2]}]
set_property -dict { PACKAGE_PIN P17 IOSTANDARD LVCMOS33 } [get_ports {rgmii_rxd[3]}]
set_property -dict { PACKAGE_PIN R19 IOSTANDARD LVCMOS33 } [get_ports rgmii_rx_ctl]
set_property -dict { PACKAGE_PIN N13 IOSTANDARD LVCMOS33 SLEW SLOW DRIVE 8 } [get_ports phy_mdc]
set_property -dict { PACKAGE_PIN P14 IOSTANDARD LVCMOS33 SLEW SLOW DRIVE 8 } [get_ports phy_mdio]
set_property -dict { PACKAGE_PIN R14 IOSTANDARD LVCMOS33 SLEW SLOW DRIVE 8 } [get_ports phy_reset_n]

## ---- 수신 (RXC 125 MHz, PHY 안에서 RXC 1.2 ns 지연) ----
create_clock -name rgmii_rx_clk -period 8.000 [get_ports rgmii_rx_clk]
set_input_delay -clock rgmii_rx_clk -max 3.300 [get_ports {rgmii_rxd[*] rgmii_rx_ctl}]
set_input_delay -clock rgmii_rx_clk -min 2.300 [get_ports {rgmii_rxd[*] rgmii_rx_ctl}]
set_input_delay -clock rgmii_rx_clk -clock_fall -max 3.300 -add_delay [get_ports {rgmii_rxd[*] rgmii_rx_ctl}]
set_input_delay -clock rgmii_rx_clk -clock_fall -min 2.300 -add_delay [get_ports {rgmii_rxd[*] rgmii_rx_ctl}]

## ---- 송신 (TXC = gtx_clk90을 ODDR로 내보냄) ----
create_generated_clock -name rgmii_tx_clk -multiply_by 1 \
    -source [get_pins -of_objects [get_cells -hierarchical -filter {NAME =~ *rgmii_phy_if_inst/clk_oddr_inst/* && REF_NAME == ODDR}] -filter {REF_PIN_NAME == C}] \
    [get_ports rgmii_tx_clk]
set_output_delay -clock rgmii_tx_clk -max  1.000 [get_ports {rgmii_txd[*] rgmii_tx_ctl}]
set_output_delay -clock rgmii_tx_clk -min -1.000 [get_ports {rgmii_txd[*] rgmii_tx_ctl}]
set_output_delay -clock rgmii_tx_clk -clock_fall -max  1.000 -add_delay [get_ports {rgmii_txd[*] rgmii_tx_ctl}]
set_output_delay -clock rgmii_tx_clk -clock_fall -min -1.000 -add_delay [get_ports {rgmii_txd[*] rgmii_tx_ctl}]

## ---- 느린 신호 ----
## PHY reset은 ms 단위, MDC 0·MDIO Z는 고정값이다.
set_false_path -to [get_ports {phy_reset_n phy_mdc phy_mdio}]
set_false_path -from [get_ports phy_mdio]
