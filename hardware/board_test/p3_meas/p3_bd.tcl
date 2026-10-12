# ============================================================
# p3_bd.tcl — P3 측정 설계의 블록 디자인 p3_bd (build_p3.tcl이 source)
# ============================================================
# XDMA(Gen2 ×2, AXI-MM 64 bit @125 MHz, H2C 1·C2H 1, AXI-Lite 마스터 64 KiB)
# JTAG-to-AXI(보조 경로: PCIe 없이 레지스터 접근)
# SmartConnect 3×3, 클럭 2개(axi_aclk 125 MHz, ui_clk 100 MHz)
#
# 주소 (SmartConnect 하나에 마스터가 셋이므로 주소 지도를 하나로 맞춘다):
#   0x0000_0000  레지스터 64 KiB (외부 포트 M_AXIL_REG → p3_regs, ui_clk)
#                XDMA M_AXI_LITE(BAR0 64 KiB)와 JTAG-AXI만 접근
#   0x0001_0000  BRAM 64 KiB (axi_aclk, PCIe DMA 지연 시험용)
#   0x8000_0000  DDR3 1 GiB  (외부 포트 M_AXI_DDR → p3_top의 정적 MUX → MIG)
#                BRAM·DDR3는 XDMA M_AXI(H2C/C2H 오프셋)와 JTAG-AXI가 접근
# ============================================================

create_bd_design p3_bd

set xdma [create_bd_cell -type ip -vlnv xilinx.com:ip:xdma xdma_0]
set_property -dict [list \
    CONFIG.mode_selection              {Advanced} \
    CONFIG.pl_link_cap_max_link_width  {X2} \
    CONFIG.pl_link_cap_max_link_speed  {5.0_GT/s} \
    CONFIG.axi_data_width              {64_bit} \
    CONFIG.axisten_freq                {125} \
    CONFIG.pf0_device_id               {7022} \
    CONFIG.xdma_rnum_chnl              {1} \
    CONFIG.xdma_wnum_chnl              {1} \
    CONFIG.xdma_axi_intf_mm            {AXI_Memory_Mapped} \
    CONFIG.axilite_master_en           {true} \
    CONFIG.axilite_master_scale        {Kilobytes} \
    CONFIG.axilite_master_size         {64} \
    CONFIG.pciebar2axibar_axil_master  {0x00000000} \
    CONFIG.pciebar2axibar_xdma         {0x0000000000000000} \
] $xdma

# fit 변형(build_p3.tcl -fit): 측정용 BRAM 64 KiB와 JTAG-AXI를 빼고 최종 시스템에
# 남을 경로(XDMA → DDR3, XDMA → 레지스터)만 둔다.
if { ![info exists p3_bd_fit] } { set p3_bd_fit 0 }

set sc [create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect smartconnect_0]
if { $p3_bd_fit } {
    set_property -dict [list CONFIG.NUM_SI {2} CONFIG.NUM_MI {2} CONFIG.NUM_CLKS {2}] $sc
} else {
    set jtag [create_bd_cell -type ip -vlnv xilinx.com:ip:jtag_axi jtag_axi_0]
    set_property -dict [list CONFIG.NUM_SI {3} CONFIG.NUM_MI {3} CONFIG.NUM_CLKS {2}] $sc
    set bc [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_bram_ctrl axi_bram_ctrl_0]
    set_property -dict [list CONFIG.DATA_WIDTH {64} CONFIG.SINGLE_PORT_BRAM {1} CONFIG.ECC_TYPE {0}] $bc
    set bm [create_bd_cell -type ip -vlnv xilinx.com:ip:blk_mem_gen blk_mem_0]
}

# ---- 외부 포트 (ui_clk 도메인) ----
create_bd_port -dir I -type clk -freq_hz 100000000 ui_clk
create_bd_port -dir I -type rst ui_rstn
set_property CONFIG.POLARITY ACTIVE_LOW [get_bd_ports ui_rstn]

create_bd_intf_port -mode Master -vlnv xilinx.com:interface:aximm_rtl:1.0 M_AXI_DDR
set_property -dict [list CONFIG.PROTOCOL {AXI4} CONFIG.DATA_WIDTH {256} CONFIG.ADDR_WIDTH {32} \
    CONFIG.HAS_REGION {0} CONFIG.HAS_QOS {0} CONFIG.HAS_LOCK {0} CONFIG.HAS_CACHE {0} CONFIG.HAS_PROT {0}] \
    [get_bd_intf_ports M_AXI_DDR]
create_bd_intf_port -mode Master -vlnv xilinx.com:interface:aximm_rtl:1.0 M_AXIL_REG
set_property -dict [list CONFIG.PROTOCOL {AXI4LITE} CONFIG.DATA_WIDTH {32} CONFIG.ADDR_WIDTH {32}] \
    [get_bd_intf_ports M_AXIL_REG]
set_property CONFIG.ASSOCIATED_BUSIF {M_AXI_DDR:M_AXIL_REG} [get_bd_ports ui_clk]
set_property CONFIG.ASSOCIATED_RESET {ui_rstn} [get_bd_ports ui_clk]

# ---- 연결 ----
connect_bd_intf_net [get_bd_intf_pins xdma_0/M_AXI]      [get_bd_intf_pins smartconnect_0/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins xdma_0/M_AXI_LITE] [get_bd_intf_pins smartconnect_0/S01_AXI]
set aclk [get_bd_pins xdma_0/axi_aclk]
set arst [get_bd_pins xdma_0/axi_aresetn]
if { $p3_bd_fit } {
    connect_bd_intf_net [get_bd_intf_pins smartconnect_0/M00_AXI] [get_bd_intf_ports M_AXI_DDR]
    connect_bd_intf_net [get_bd_intf_pins smartconnect_0/M01_AXI] [get_bd_intf_ports M_AXIL_REG]
    connect_bd_net $aclk [get_bd_pins smartconnect_0/aclk]
    connect_bd_net $arst [get_bd_pins smartconnect_0/aresetn]
} else {
    connect_bd_intf_net [get_bd_intf_pins jtag_axi_0/M_AXI]  [get_bd_intf_pins smartconnect_0/S02_AXI]
    connect_bd_intf_net [get_bd_intf_pins smartconnect_0/M00_AXI] [get_bd_intf_pins axi_bram_ctrl_0/S_AXI]
    connect_bd_intf_net [get_bd_intf_pins smartconnect_0/M01_AXI] [get_bd_intf_ports M_AXI_DDR]
    connect_bd_intf_net [get_bd_intf_pins smartconnect_0/M02_AXI] [get_bd_intf_ports M_AXIL_REG]
    connect_bd_intf_net [get_bd_intf_pins axi_bram_ctrl_0/BRAM_PORTA] [get_bd_intf_pins blk_mem_0/BRAM_PORTA]
    connect_bd_net $aclk [get_bd_pins smartconnect_0/aclk] [get_bd_pins jtag_axi_0/aclk] [get_bd_pins axi_bram_ctrl_0/s_axi_aclk]
    connect_bd_net $arst [get_bd_pins smartconnect_0/aresetn] [get_bd_pins jtag_axi_0/aresetn] [get_bd_pins axi_bram_ctrl_0/s_axi_aresetn]
}
connect_bd_net [get_bd_ports ui_clk] [get_bd_pins smartconnect_0/aclk1]

make_bd_intf_pins_external -name pcie_mgt [get_bd_intf_pins xdma_0/pcie_mgt]
foreach p {sys_clk sys_rst_n user_lnk_up} {
    make_bd_pins_external -name $p [get_bd_pins xdma_0/$p]
}

# ---- 주소 ----
assign_bd_address
proc seg_set {space pat off rng} {
    set s [get_bd_addr_segs -quiet -of_objects [get_bd_addr_spaces $space] -filter "NAME =~ $pat"]
    if { [llength $s] != 1 } { error "주소 세그먼트를 찾지 못함: $space $pat → $s" }
    set_property offset $off $s
    set_property range $rng $s
}
proc seg_drop {space pat} {
    foreach s [get_bd_addr_segs -quiet -of_objects [get_bd_addr_spaces $space] -filter "NAME =~ $pat"] {
        exclude_bd_addr_seg $s
    }
}
seg_set  xdma_0/M_AXI      *DDR*  0x80000000 1G
seg_drop xdma_0/M_AXI      *REG*
seg_set  xdma_0/M_AXI_LITE *REG*  0x00000000 64K
seg_drop xdma_0/M_AXI_LITE *DDR*
if { !$p3_bd_fit } {
    seg_set  xdma_0/M_AXI      *bram* 0x00010000 64K
    seg_drop xdma_0/M_AXI_LITE *bram*
    seg_set  jtag_axi_0/Data   *REG*  0x00000000 64K
    seg_set  jtag_axi_0/Data   *bram* 0x00010000 64K
    seg_set  jtag_axi_0/Data   *DDR*  0x80000000 1G
}

validate_bd_design
save_bd_design
