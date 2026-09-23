## ============================================================
## ax7a200b_io.xdc — AX7A200B 사용자 I/O: LED, 버튼
## ============================================================
## 근거 : documents/manual/AX7A200_User_Manual.pdf (Rev 1.0)
##        Part 2.6 코어보드 LED, Part 3.13 버튼, Part 3.14 LED
## USB-UART는 ax7a200b_uart.xdc로 분리했다(쓰지 않는 설계에서 Critical Warning 방지).
## 설계에서 쓰지 않는 포트는 이 파일에서 지우지 말고 주석 처리한다.
## (없는 포트를 제약하면 Vivado가 Critical Warning을 낸다.)
## ============================================================

## ---- 코어보드 사용자 LED (BANK34, 1.5 V, Active-High, Part 2.6) ----
set_property -dict { PACKAGE_PIN W5  IOSTANDARD LVCMOS15 } [get_ports led_core]

## ---- 캐리어보드 사용자 LED1~4 (BANK15, 3.3 V, Active-Low, Part 3.14) ----
## IO가 Low일 때 켜진다. led_n[0] = LED1.
set_property -dict { PACKAGE_PIN L13 IOSTANDARD LVCMOS33 } [get_ports {led_n[0]}]
set_property -dict { PACKAGE_PIN M13 IOSTANDARD LVCMOS33 } [get_ports {led_n[1]}]
set_property -dict { PACKAGE_PIN K14 IOSTANDARD LVCMOS33 } [get_ports {led_n[2]}]
set_property -dict { PACKAGE_PIN K13 IOSTANDARD LVCMOS33 } [get_ports {led_n[3]}]

## ---- 캐리어보드 버튼 (Active-Low, 누르면 Low, Part 3.13) ----
## RESET 버튼: BANK16 IO_0_16
set_property -dict { PACKAGE_PIN F15 IOSTANDARD LVCMOS33 } [get_ports rst_n]
## KEY1~4: BANK15. key_n[0] = KEY1.
set_property -dict { PACKAGE_PIN L19 IOSTANDARD LVCMOS33 } [get_ports {key_n[0]}]
set_property -dict { PACKAGE_PIN L20 IOSTANDARD LVCMOS33 } [get_ports {key_n[1]}]
set_property -dict { PACKAGE_PIN K17 IOSTANDARD LVCMOS33 } [get_ports {key_n[2]}]
set_property -dict { PACKAGE_PIN J17 IOSTANDARD LVCMOS33 } [get_ports {key_n[3]}]

## 버튼은 비동기 입력이므로 설계 내부에서 동기화한다.
set_false_path -from [get_ports -quiet {rst_n key_n[*]}]
