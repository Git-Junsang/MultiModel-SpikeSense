## ============================================================
## ax7a200b_uart.xdc — AX7A200B USB-UART (CP2102GM)
## ============================================================
## 근거 : documents/manual/AX7A200_User_Manual.pdf (Rev 1.0) Part 3.8
## UART를 쓰는 설계에서만 -xdc 목록에 넣는다.
## ============================================================

## ---- USB-UART (CP2102GM, BANK15, Part 3.8) ----
## 매뉴얼의 신호명(UART1_RXD/TXD)을 그대로 따른다. 이 이름이 FPGA 기준인지
## CP2102 기준인지 매뉴얼에 명시되어 있지 않다. 처음 사용할 때 루프백으로
## 방향을 확인하고 이 주석을 갱신한다.
set_property -dict { PACKAGE_PIN L14 IOSTANDARD LVCMOS33 } [get_ports uart_rxd]
set_property -dict { PACKAGE_PIN L15 IOSTANDARD LVCMOS33 } [get_ports uart_txd]

## UART 입력은 비동기이므로 설계 내부에서 동기화한다.
set_false_path -from [get_ports -quiet uart_rxd]
