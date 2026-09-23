## ============================================================
## ax7a200b_base.xdc — AX7A200B 공통 제약: 시스템 클럭, 비트스트림 설정
## ============================================================
## 보드 : ALINX AX7A200B (코어보드 AC7A200), XC7A200T-2FBG484I
## 근거 : documents/manual/AX7A200_User_Manual.pdf (Rev 1.0)
##        Part 2.3.1 200 MHz 차동 클럭, Part 2.2 뱅크 전압
## 뱅크 전압: BANK34·35 = 1.5 V(DDR3), BANK0·13·14·15·16 = 3.3 V
##
## 모든 설계에 포함한다. 사용자 I/O는 ax7a200b_io.xdc,
## DDR3·PCIe는 각각 ax7a200b_ddr3.xdc·ax7a200b_pcie.xdc에 있다.
## ============================================================

## ---- 200 MHz 시스템 클럭 (SiT9102, BANK34 MRCC, Part 2.3.1) ----
## BANK34가 1.5 V이므로 DIFF_SSTL15를 쓴다.
## MIG를 쓰는 설계에서는 MIG가 이 핀을 sys_clk로 직접 받을 수 있다.
set_property -dict { PACKAGE_PIN R4  IOSTANDARD DIFF_SSTL15 } [get_ports sys_clk_p]
set_property -dict { PACKAGE_PIN T4  IOSTANDARD DIFF_SSTL15 } [get_ports sys_clk_n]
create_clock -name sys_clk -period 5.000 [get_ports sys_clk_p]

## ---- 구성(Configuration) ----
## BANK0 VCCO = 3.3 V (Part 2.2)
set_property CFGBVS VCCO        [current_design]
set_property CONFIG_VOLTAGE 3.3 [current_design]

## QSPI Flash N25Q128 (128 Mbit, Part 2.5) 부팅용 설정
set_property BITSTREAM.GENERAL.COMPRESS TRUE     [current_design]
set_property BITSTREAM.CONFIG.SPI_BUSWIDTH 4     [current_design]
set_property BITSTREAM.CONFIG.CONFIGRATE 50      [current_design]
set_property CONFIG_MODE SPIx4                   [current_design]

## 미사용 핀은 Vivado 기본값(Pulldown)을 유지한다.
## 팬 제어(FAN_PWM, BANK16)는 Low일 때 팬이 돈다(Part 3.16). 팬 핀 번호가
## 매뉴얼에 없어 제약하지 않았으며, 기본 풀다운 상태에서 팬이 도는지
## P0.5에서 보드로 확인한다.
