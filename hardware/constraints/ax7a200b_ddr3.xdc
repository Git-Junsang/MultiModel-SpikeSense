## ============================================================
## ax7a200b_ddr3.xdc — AX7A200B DDR3 핀 (MIG 7 Series 포트명 기준)
## ============================================================
## 근거 : documents/manual/AX7A200_User_Manual.pdf (Rev 1.0) Part 2.4
##        MT41J256M16HA-125 ×2 (각 4 Gbit, ×16) → 32 bit 데이터 버스, 1 GiB
##        BANK35 = DQ·DQS·DM, BANK34 = 주소·명령·클럭, 두 뱅크 모두 1.5 V
##        매뉴얼 기준 최대 400 MHz (800 MT/s)
##
## 용도 : MIG IP가 자체 XDC를 생성하므로 MIG 설계에서는 이 파일을 넣지 않는다.
##        P0.6에서 MIG 핀 배치를 설정·검토할 때 기준표로 쓰고, MIG가 만든 XDC와
##        이 파일의 핀이 같은지 비교한다. 포트명은 MIG 기본값(ddr3_*)을 따른다.
##        DDR3_S0(칩 선택)은 ddr3_cs_n[0]에 대응한다.
##        Artix-7은 HR 뱅크만 있어 DCI(*_T_DCI)를 지원하지 않는다. DQ·DQS는
##        SSTL15/DIFF_SSTL15에 내부 종단 IN_TERM UNTUNED_SPLIT_50을 쓴다.
##        최종 IOSTANDARD·종단·슬루는 MIG 생성 결과를 따른다.
## ============================================================

## ---- 데이터: DQ[31:0] (BANK35) ----
set_property -dict { PACKAGE_PIN C2  IOSTANDARD SSTL15 IN_TERM UNTUNED_SPLIT_50 } [get_ports {ddr3_dq[0]}]
set_property -dict { PACKAGE_PIN G1  IOSTANDARD SSTL15 IN_TERM UNTUNED_SPLIT_50 } [get_ports {ddr3_dq[1]}]
set_property -dict { PACKAGE_PIN A1  IOSTANDARD SSTL15 IN_TERM UNTUNED_SPLIT_50 } [get_ports {ddr3_dq[2]}]
set_property -dict { PACKAGE_PIN F3  IOSTANDARD SSTL15 IN_TERM UNTUNED_SPLIT_50 } [get_ports {ddr3_dq[3]}]
set_property -dict { PACKAGE_PIN B2  IOSTANDARD SSTL15 IN_TERM UNTUNED_SPLIT_50 } [get_ports {ddr3_dq[4]}]
set_property -dict { PACKAGE_PIN F1  IOSTANDARD SSTL15 IN_TERM UNTUNED_SPLIT_50 } [get_ports {ddr3_dq[5]}]
set_property -dict { PACKAGE_PIN B1  IOSTANDARD SSTL15 IN_TERM UNTUNED_SPLIT_50 } [get_ports {ddr3_dq[6]}]
set_property -dict { PACKAGE_PIN E2  IOSTANDARD SSTL15 IN_TERM UNTUNED_SPLIT_50 } [get_ports {ddr3_dq[7]}]
set_property -dict { PACKAGE_PIN H3  IOSTANDARD SSTL15 IN_TERM UNTUNED_SPLIT_50 } [get_ports {ddr3_dq[8]}]
set_property -dict { PACKAGE_PIN G3  IOSTANDARD SSTL15 IN_TERM UNTUNED_SPLIT_50 } [get_ports {ddr3_dq[9]}]
set_property -dict { PACKAGE_PIN H2  IOSTANDARD SSTL15 IN_TERM UNTUNED_SPLIT_50 } [get_ports {ddr3_dq[10]}]
set_property -dict { PACKAGE_PIN H5  IOSTANDARD SSTL15 IN_TERM UNTUNED_SPLIT_50 } [get_ports {ddr3_dq[11]}]
set_property -dict { PACKAGE_PIN J1  IOSTANDARD SSTL15 IN_TERM UNTUNED_SPLIT_50 } [get_ports {ddr3_dq[12]}]
set_property -dict { PACKAGE_PIN J5  IOSTANDARD SSTL15 IN_TERM UNTUNED_SPLIT_50 } [get_ports {ddr3_dq[13]}]
set_property -dict { PACKAGE_PIN K1  IOSTANDARD SSTL15 IN_TERM UNTUNED_SPLIT_50 } [get_ports {ddr3_dq[14]}]
set_property -dict { PACKAGE_PIN H4  IOSTANDARD SSTL15 IN_TERM UNTUNED_SPLIT_50 } [get_ports {ddr3_dq[15]}]
set_property -dict { PACKAGE_PIN L4  IOSTANDARD SSTL15 IN_TERM UNTUNED_SPLIT_50 } [get_ports {ddr3_dq[16]}]
set_property -dict { PACKAGE_PIN M3  IOSTANDARD SSTL15 IN_TERM UNTUNED_SPLIT_50 } [get_ports {ddr3_dq[17]}]
set_property -dict { PACKAGE_PIN L3  IOSTANDARD SSTL15 IN_TERM UNTUNED_SPLIT_50 } [get_ports {ddr3_dq[18]}]
set_property -dict { PACKAGE_PIN J6  IOSTANDARD SSTL15 IN_TERM UNTUNED_SPLIT_50 } [get_ports {ddr3_dq[19]}]
set_property -dict { PACKAGE_PIN K3  IOSTANDARD SSTL15 IN_TERM UNTUNED_SPLIT_50 } [get_ports {ddr3_dq[20]}]
set_property -dict { PACKAGE_PIN K6  IOSTANDARD SSTL15 IN_TERM UNTUNED_SPLIT_50 } [get_ports {ddr3_dq[21]}]
set_property -dict { PACKAGE_PIN J4  IOSTANDARD SSTL15 IN_TERM UNTUNED_SPLIT_50 } [get_ports {ddr3_dq[22]}]
set_property -dict { PACKAGE_PIN L5  IOSTANDARD SSTL15 IN_TERM UNTUNED_SPLIT_50 } [get_ports {ddr3_dq[23]}]
set_property -dict { PACKAGE_PIN P1  IOSTANDARD SSTL15 IN_TERM UNTUNED_SPLIT_50 } [get_ports {ddr3_dq[24]}]
set_property -dict { PACKAGE_PIN N4  IOSTANDARD SSTL15 IN_TERM UNTUNED_SPLIT_50 } [get_ports {ddr3_dq[25]}]
set_property -dict { PACKAGE_PIN R1  IOSTANDARD SSTL15 IN_TERM UNTUNED_SPLIT_50 } [get_ports {ddr3_dq[26]}]
set_property -dict { PACKAGE_PIN N2  IOSTANDARD SSTL15 IN_TERM UNTUNED_SPLIT_50 } [get_ports {ddr3_dq[27]}]
set_property -dict { PACKAGE_PIN M6  IOSTANDARD SSTL15 IN_TERM UNTUNED_SPLIT_50 } [get_ports {ddr3_dq[28]}]
set_property -dict { PACKAGE_PIN N5  IOSTANDARD SSTL15 IN_TERM UNTUNED_SPLIT_50 } [get_ports {ddr3_dq[29]}]
set_property -dict { PACKAGE_PIN P6  IOSTANDARD SSTL15 IN_TERM UNTUNED_SPLIT_50 } [get_ports {ddr3_dq[30]}]
set_property -dict { PACKAGE_PIN P2  IOSTANDARD SSTL15 IN_TERM UNTUNED_SPLIT_50 } [get_ports {ddr3_dq[31]}]

## ---- 데이터 스트로브: DQS[3:0] (BANK35) ----
set_property -dict { PACKAGE_PIN E1  IOSTANDARD DIFF_SSTL15 IN_TERM UNTUNED_SPLIT_50 } [get_ports {ddr3_dqs_p[0]}]
set_property -dict { PACKAGE_PIN D1  IOSTANDARD DIFF_SSTL15 IN_TERM UNTUNED_SPLIT_50 } [get_ports {ddr3_dqs_n[0]}]
set_property -dict { PACKAGE_PIN K2  IOSTANDARD DIFF_SSTL15 IN_TERM UNTUNED_SPLIT_50 } [get_ports {ddr3_dqs_p[1]}]
set_property -dict { PACKAGE_PIN J2  IOSTANDARD DIFF_SSTL15 IN_TERM UNTUNED_SPLIT_50 } [get_ports {ddr3_dqs_n[1]}]
set_property -dict { PACKAGE_PIN M1  IOSTANDARD DIFF_SSTL15 IN_TERM UNTUNED_SPLIT_50 } [get_ports {ddr3_dqs_p[2]}]
set_property -dict { PACKAGE_PIN L1  IOSTANDARD DIFF_SSTL15 IN_TERM UNTUNED_SPLIT_50 } [get_ports {ddr3_dqs_n[2]}]
set_property -dict { PACKAGE_PIN P5  IOSTANDARD DIFF_SSTL15 IN_TERM UNTUNED_SPLIT_50 } [get_ports {ddr3_dqs_p[3]}]
set_property -dict { PACKAGE_PIN P4  IOSTANDARD DIFF_SSTL15 IN_TERM UNTUNED_SPLIT_50 } [get_ports {ddr3_dqs_n[3]}]

## ---- 데이터 마스크: DM[3:0] (BANK35) ----
set_property -dict { PACKAGE_PIN D2  IOSTANDARD SSTL15 } [get_ports {ddr3_dm[0]}]
set_property -dict { PACKAGE_PIN G2  IOSTANDARD SSTL15 } [get_ports {ddr3_dm[1]}]
set_property -dict { PACKAGE_PIN M2  IOSTANDARD SSTL15 } [get_ports {ddr3_dm[2]}]
set_property -dict { PACKAGE_PIN M5  IOSTANDARD SSTL15 } [get_ports {ddr3_dm[3]}]

## ---- 주소: A[14:0] (BANK34) ----
set_property -dict { PACKAGE_PIN AA4 IOSTANDARD SSTL15 } [get_ports {ddr3_addr[0]}]
set_property -dict { PACKAGE_PIN AB2 IOSTANDARD SSTL15 } [get_ports {ddr3_addr[1]}]
set_property -dict { PACKAGE_PIN AA5 IOSTANDARD SSTL15 } [get_ports {ddr3_addr[2]}]
set_property -dict { PACKAGE_PIN AB5 IOSTANDARD SSTL15 } [get_ports {ddr3_addr[3]}]
set_property -dict { PACKAGE_PIN AB1 IOSTANDARD SSTL15 } [get_ports {ddr3_addr[4]}]
set_property -dict { PACKAGE_PIN U3  IOSTANDARD SSTL15 } [get_ports {ddr3_addr[5]}]
set_property -dict { PACKAGE_PIN W1  IOSTANDARD SSTL15 } [get_ports {ddr3_addr[6]}]
set_property -dict { PACKAGE_PIN T1  IOSTANDARD SSTL15 } [get_ports {ddr3_addr[7]}]
set_property -dict { PACKAGE_PIN V2  IOSTANDARD SSTL15 } [get_ports {ddr3_addr[8]}]
set_property -dict { PACKAGE_PIN U2  IOSTANDARD SSTL15 } [get_ports {ddr3_addr[9]}]
set_property -dict { PACKAGE_PIN Y1  IOSTANDARD SSTL15 } [get_ports {ddr3_addr[10]}]
set_property -dict { PACKAGE_PIN W2  IOSTANDARD SSTL15 } [get_ports {ddr3_addr[11]}]
set_property -dict { PACKAGE_PIN Y2  IOSTANDARD SSTL15 } [get_ports {ddr3_addr[12]}]
set_property -dict { PACKAGE_PIN U1  IOSTANDARD SSTL15 } [get_ports {ddr3_addr[13]}]
set_property -dict { PACKAGE_PIN V3  IOSTANDARD SSTL15 } [get_ports {ddr3_addr[14]}]

## ---- 뱅크 주소: BA[2:0] (BANK34) ----
set_property -dict { PACKAGE_PIN AA3 IOSTANDARD SSTL15 } [get_ports {ddr3_ba[0]}]
set_property -dict { PACKAGE_PIN Y3  IOSTANDARD SSTL15 } [get_ports {ddr3_ba[1]}]
set_property -dict { PACKAGE_PIN Y4  IOSTANDARD SSTL15 } [get_ports {ddr3_ba[2]}]

## ---- 명령·제어 (BANK34) ----
set_property -dict { PACKAGE_PIN AB3 IOSTANDARD SSTL15 } [get_ports {ddr3_cs_n[0]}]
set_property -dict { PACKAGE_PIN V4  IOSTANDARD SSTL15 } [get_ports {ddr3_ras_n}]
set_property -dict { PACKAGE_PIN W4  IOSTANDARD SSTL15 } [get_ports {ddr3_cas_n}]
set_property -dict { PACKAGE_PIN AA1 IOSTANDARD SSTL15 } [get_ports {ddr3_we_n}]
set_property -dict { PACKAGE_PIN U5  IOSTANDARD SSTL15 } [get_ports {ddr3_odt[0]}]
set_property -dict { PACKAGE_PIN T5  IOSTANDARD SSTL15 } [get_ports {ddr3_cke[0]}]
set_property -dict { PACKAGE_PIN W6  IOSTANDARD LVCMOS15 } [get_ports {ddr3_reset_n}]

## ---- 메모리 클럭 (BANK34) ----
set_property -dict { PACKAGE_PIN R3  IOSTANDARD DIFF_SSTL15 } [get_ports {ddr3_ck_p[0]}]
set_property -dict { PACKAGE_PIN R2  IOSTANDARD DIFF_SSTL15 } [get_ports {ddr3_ck_n[0]}]

## ---- 내부 VREF (SSTL15, VREF = VCCO/2 = 0.75 V) ----
set_property INTERNAL_VREF 0.750 [get_iobanks 34]
set_property INTERNAL_VREF 0.750 [get_iobanks 35]
