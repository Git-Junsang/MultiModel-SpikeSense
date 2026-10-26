// ============================================================
// p3_top.v — P3.1~P3.3 측정 설계 탑 (DDR3 bandwidth·지연, PCIe 지연, 자원)
// ============================================================
// 구성
//   mig_ddr3   : P1.6과 같은 MIG 설정(AXI 256 bit, UI 100 MHz). 주소 매핑은
//                build_p3.tcl의 -addr_map으로 고른다.
//   p3_bd      : XDMA(Gen2 ×2) + JTAG-AXI + SmartConnect + BRAM 64 KiB (p3_bd.tcl)
//   p3_core    : register(AXI-Lite) + traffic 생성기(ddr_tgen)
//   정적 MUX   : MIG AXI 포트를 traffic 생성기(ddr_sel=0) 또는 Host DMA(ddr_sel=1)에 연결.
//                전환은 양쪽이 모두 쉬고 있을 때만 한다(소프트웨어 규칙).
//                Traffic 생성기가 MIG에 직접 붙으므로 DDR3 측정에 인터커넥트 지연이 섞이지 않는다.
//
// 리셋: PCIe PERST#(L16)를 XDMA sys_rst_n에 그대로 연결한다(Xilinx 예제와 같다).
//       MIG sys_rst는 RESET 버튼(Active-Low).
//
// LED (캐리어 Active-Low): LED1 calib, LED2 user_lnk_up, LED3 traffic 생성기 동작, LED4 ui_clk 점멸
// VIO (ui_clk): calib, lnk_up(동기화), tg_busy, 하트비트 — PCIe·AXI 경로가 죽었을 때의 확인용
// ============================================================
`timescale 1ns / 1ps

module p3_top (
    input  wire        sys_clk_p,
    input  wire        sys_clk_n,
    input  wire        rst_n,
    input  wire [3:0]  key_n,
    // DDR3
    inout  wire [31:0] ddr3_dq,
    inout  wire [3:0]  ddr3_dqs_n,
    inout  wire [3:0]  ddr3_dqs_p,
    output wire [14:0] ddr3_addr,
    output wire [2:0]  ddr3_ba,
    output wire        ddr3_ras_n,
    output wire        ddr3_cas_n,
    output wire        ddr3_we_n,
    output wire        ddr3_reset_n,
    output wire [0:0]  ddr3_ck_p,
    output wire [0:0]  ddr3_ck_n,
    output wire [0:0]  ddr3_cke,
    output wire [0:0]  ddr3_cs_n,
    output wire [3:0]  ddr3_dm,
    output wire [0:0]  ddr3_odt,
    // PCIe
    input  wire        pcie_refclk_p,
    input  wire        pcie_refclk_n,
    input  wire [1:0]  pci_exp_rxp,
    input  wire [1:0]  pci_exp_rxn,
    output wire [1:0]  pci_exp_txp,
    output wire [1:0]  pci_exp_txn,
    input  wire        pcie_perst_n,
    // LED
    output wire        led_core,
    output wire [3:0]  led_n
);

    // ---------------- MIG ----------------
    wire ui_clk, ui_rst, calib, mmcm_locked;
    reg  mig_aresetn;
    always @(posedge ui_clk) mig_aresetn <= ~ui_rst;

    wire [29:0]  mi_awaddr, mi_araddr;
    wire [7:0]   mi_awlen, mi_arlen;
    wire [2:0]   mi_awsize, mi_arsize;
    wire [1:0]   mi_awburst, mi_arburst;
    wire         mi_awvalid, mi_awready, mi_arvalid, mi_arready;
    wire [255:0] mi_wdata, mi_rdata;
    wire [31:0]  mi_wstrb;
    wire         mi_wlast, mi_wvalid, mi_wready;
    wire [1:0]   mi_bresp, mi_rresp;
    wire         mi_bvalid, mi_bready, mi_rlast, mi_rvalid, mi_rready;

    mig_ddr3 u_mig (
        .ddr3_addr(ddr3_addr), .ddr3_ba(ddr3_ba), .ddr3_cas_n(ddr3_cas_n),
        .ddr3_ck_n(ddr3_ck_n), .ddr3_ck_p(ddr3_ck_p), .ddr3_cke(ddr3_cke),
        .ddr3_ras_n(ddr3_ras_n), .ddr3_reset_n(ddr3_reset_n), .ddr3_we_n(ddr3_we_n),
        .ddr3_dq(ddr3_dq), .ddr3_dqs_n(ddr3_dqs_n), .ddr3_dqs_p(ddr3_dqs_p),
        .ddr3_cs_n(ddr3_cs_n), .ddr3_dm(ddr3_dm), .ddr3_odt(ddr3_odt),
        .init_calib_complete(calib),
        .ui_clk(ui_clk), .ui_clk_sync_rst(ui_rst), .mmcm_locked(mmcm_locked),
        .aresetn(mig_aresetn),
        .app_sr_req(1'b0), .app_ref_req(1'b0), .app_zq_req(1'b0),
        .app_sr_active(), .app_ref_ack(), .app_zq_ack(),
        .s_axi_awid(4'd0), .s_axi_awaddr(mi_awaddr), .s_axi_awlen(mi_awlen),
        .s_axi_awsize(mi_awsize), .s_axi_awburst(mi_awburst), .s_axi_awlock(1'b0),
        .s_axi_awcache(4'b0011), .s_axi_awprot(3'b000), .s_axi_awqos(4'd0),
        .s_axi_awvalid(mi_awvalid), .s_axi_awready(mi_awready),
        .s_axi_wdata(mi_wdata), .s_axi_wstrb(mi_wstrb), .s_axi_wlast(mi_wlast),
        .s_axi_wvalid(mi_wvalid), .s_axi_wready(mi_wready),
        .s_axi_bid(), .s_axi_bresp(mi_bresp), .s_axi_bvalid(mi_bvalid), .s_axi_bready(mi_bready),
        .s_axi_arid(4'd0), .s_axi_araddr(mi_araddr), .s_axi_arlen(mi_arlen),
        .s_axi_arsize(mi_arsize), .s_axi_arburst(mi_arburst), .s_axi_arlock(1'b0),
        .s_axi_arcache(4'b0011), .s_axi_arprot(3'b000), .s_axi_arqos(4'd0),
        .s_axi_arvalid(mi_arvalid), .s_axi_arready(mi_arready),
        .s_axi_rid(), .s_axi_rdata(mi_rdata), .s_axi_rresp(mi_rresp), .s_axi_rlast(mi_rlast),
        .s_axi_rvalid(mi_rvalid), .s_axi_rready(mi_rready),
        .sys_clk_p(sys_clk_p), .sys_clk_n(sys_clk_n), .sys_rst(rst_n)
    );

    // ---------------- PCIe 클럭·리셋 ----------------
    wire refclk;
    IBUFDS_GTE2 u_ibufds_ref (
        .I(pcie_refclk_p), .IB(pcie_refclk_n), .CEB(1'b0), .O(refclk), .ODIV2()
    );
    wire perst_n_i;
    IBUF u_ibuf_perst (.I(pcie_perst_n), .O(perst_n_i));

    // ---------------- 블록 디자인 ----------------
    wire         lnk_up;
    // Host DDR3 포트 (ui_clk)
    wire [31:0]  h_awaddr, h_araddr;
    wire [7:0]   h_awlen, h_arlen;
    wire [2:0]   h_awsize, h_arsize;
    wire [1:0]   h_awburst, h_arburst;
    wire         h_awvalid, h_awready, h_arvalid, h_arready;
    wire [255:0] h_wdata, h_rdata;
    wire [31:0]  h_wstrb;
    wire         h_wlast, h_wvalid, h_wready;
    wire [1:0]   h_bresp, h_rresp;
    wire         h_bvalid, h_bready, h_rlast, h_rvalid, h_rready;
    // register 포트 (ui_clk)
    wire [31:0]  l_awaddr, l_araddr, l_wdata, l_rdata;
    wire         l_awvalid, l_awready, l_wvalid, l_wready, l_bvalid, l_bready;
    wire         l_arvalid, l_arready, l_rvalid, l_rready;
    wire [1:0]   l_bresp, l_rresp;

    p3_bd_wrapper u_bd (
        .pcie_mgt_rxn(pci_exp_rxn), .pcie_mgt_rxp(pci_exp_rxp),
        .pcie_mgt_txn(pci_exp_txn), .pcie_mgt_txp(pci_exp_txp),
        .sys_clk(refclk), .sys_rst_n(perst_n_i), .user_lnk_up(lnk_up),
        .ui_clk(ui_clk), .ui_rstn(mig_aresetn),
        .M_AXI_DDR_awaddr(h_awaddr), .M_AXI_DDR_awlen(h_awlen), .M_AXI_DDR_awsize(h_awsize),
        .M_AXI_DDR_awburst(h_awburst), .M_AXI_DDR_awcache(), .M_AXI_DDR_awlock(),
        .M_AXI_DDR_awprot(), .M_AXI_DDR_awqos(),
        .M_AXI_DDR_awvalid(h_awvalid), .M_AXI_DDR_awready(h_awready),
        .M_AXI_DDR_wdata(h_wdata), .M_AXI_DDR_wstrb(h_wstrb), .M_AXI_DDR_wlast(h_wlast),
        .M_AXI_DDR_wvalid(h_wvalid), .M_AXI_DDR_wready(h_wready),
        .M_AXI_DDR_bresp(h_bresp), .M_AXI_DDR_bvalid(h_bvalid), .M_AXI_DDR_bready(h_bready),
        .M_AXI_DDR_araddr(h_araddr), .M_AXI_DDR_arlen(h_arlen), .M_AXI_DDR_arsize(h_arsize),
        .M_AXI_DDR_arburst(h_arburst), .M_AXI_DDR_arcache(), .M_AXI_DDR_arlock(),
        .M_AXI_DDR_arprot(), .M_AXI_DDR_arqos(),
        .M_AXI_DDR_arvalid(h_arvalid), .M_AXI_DDR_arready(h_arready),
        .M_AXI_DDR_rdata(h_rdata), .M_AXI_DDR_rresp(h_rresp), .M_AXI_DDR_rlast(h_rlast),
        .M_AXI_DDR_rvalid(h_rvalid), .M_AXI_DDR_rready(h_rready),
        .M_AXIL_REG_awaddr(l_awaddr), .M_AXIL_REG_awprot(), .M_AXIL_REG_awvalid(l_awvalid),
        .M_AXIL_REG_awready(l_awready), .M_AXIL_REG_wdata(l_wdata), .M_AXIL_REG_wstrb(),
        .M_AXIL_REG_wvalid(l_wvalid), .M_AXIL_REG_wready(l_wready),
        .M_AXIL_REG_bresp(l_bresp), .M_AXIL_REG_bvalid(l_bvalid), .M_AXIL_REG_bready(l_bready),
        .M_AXIL_REG_araddr(l_araddr), .M_AXIL_REG_arprot(), .M_AXIL_REG_arvalid(l_arvalid),
        .M_AXIL_REG_arready(l_arready), .M_AXIL_REG_rdata(l_rdata), .M_AXIL_REG_rresp(l_rresp),
        .M_AXIL_REG_rvalid(l_rvalid), .M_AXIL_REG_rready(l_rready)
    );

    // ---------------- register + traffic 생성기 ----------------
    wire         ddr_sel, narrow_clr, tg_busy;
    reg          narrow_seen;
    wire [29:0]  t_awaddr, t_araddr;
    wire [7:0]   t_awlen, t_arlen;
    wire         t_awvalid, t_awready, t_arvalid, t_arready;
    wire [255:0] t_wdata, t_rdata;
    wire         t_wlast, t_wvalid, t_wready;
    wire [1:0]   t_bresp, t_rresp;
    wire         t_bvalid, t_bready, t_rlast, t_rvalid, t_rready;

`ifdef P3_FIT
    localparam integer CORE_LOG_AW = 4;     // fit 실험: 지연 기록을 분산 RAM 크기로 줄인다
`else
    localparam integer CORE_LOG_AW = 11;
`endif
    p3_core #(.LOG_AW(CORE_LOG_AW)) u_core (
        .clk(ui_clk), .rst(ui_rst),
        .calib_done(calib), .lnk_up(lnk_up),
        .narrow_seen(narrow_seen), .narrow_clr(narrow_clr), .ddr_sel(ddr_sel), .tg_busy(tg_busy),
        .s_awaddr(l_awaddr[15:0]), .s_awvalid(l_awvalid), .s_awready(l_awready),
        .s_wdata(l_wdata), .s_wvalid(l_wvalid), .s_wready(l_wready),
        .s_bresp(l_bresp), .s_bvalid(l_bvalid), .s_bready(l_bready),
        .s_araddr(l_araddr[15:0]), .s_arvalid(l_arvalid), .s_arready(l_arready),
        .s_rdata(l_rdata), .s_rresp(l_rresp), .s_rvalid(l_rvalid), .s_rready(l_rready),
        .m_awaddr(t_awaddr), .m_awlen(t_awlen), .m_awvalid(t_awvalid), .m_awready(t_awready),
        .m_wdata(t_wdata), .m_wlast(t_wlast), .m_wvalid(t_wvalid), .m_wready(t_wready),
        .m_bvalid(t_bvalid), .m_bready(t_bready), .m_bresp(t_bresp),
        .m_araddr(t_araddr), .m_arlen(t_arlen), .m_arvalid(t_arvalid), .m_arready(t_arready),
        .m_rdata(t_rdata), .m_rlast(t_rlast), .m_rvalid(t_rvalid), .m_rready(t_rready),
        .m_rresp(t_rresp)
    );

    // ---------------- 정적 MUX (sel: 0 = traffic 생성기, 1 = Host) ----------------
    wire s = ddr_sel;
    assign mi_awaddr  = s ? h_awaddr[29:0] : t_awaddr;
    assign mi_awlen   = s ? h_awlen   : t_awlen;
    assign mi_awsize  = s ? h_awsize  : 3'd5;
    assign mi_awburst = s ? h_awburst : 2'b01;
    assign mi_awvalid = s ? h_awvalid : t_awvalid;
    assign h_awready  = s & mi_awready;
    assign t_awready  = ~s & mi_awready;
    assign mi_wdata   = s ? h_wdata   : t_wdata;
    assign mi_wstrb   = s ? h_wstrb   : 32'hFFFF_FFFF;
    assign mi_wlast   = s ? h_wlast   : t_wlast;
    assign mi_wvalid  = s ? h_wvalid  : t_wvalid;
    assign h_wready   = s & mi_wready;
    assign t_wready   = ~s & mi_wready;
    assign mi_bready  = s ? h_bready  : t_bready;
    assign h_bvalid   = s & mi_bvalid;
    assign t_bvalid   = ~s & mi_bvalid;
    assign h_bresp    = mi_bresp;
    assign t_bresp    = mi_bresp;
    assign mi_araddr  = s ? h_araddr[29:0] : t_araddr;
    assign mi_arlen   = s ? h_arlen   : t_arlen;
    assign mi_arsize  = s ? h_arsize  : 3'd5;
    assign mi_arburst = s ? h_arburst : 2'b01;
    assign mi_arvalid = s ? h_arvalid : t_arvalid;
    assign h_arready  = s & mi_arready;
    assign t_arready  = ~s & mi_arready;
    assign mi_rready  = s ? h_rready  : t_rready;
    assign h_rvalid   = s & mi_rvalid;
    assign t_rvalid   = ~s & mi_rvalid;
    assign h_rdata    = mi_rdata;
    assign t_rdata    = mi_rdata;
    assign h_rlast    = mi_rlast;
    assign t_rlast    = mi_rlast;
    assign h_rresp    = mi_rresp;
    assign t_rresp    = mi_rresp;

    // Host 경로에서 32 B 미만 크기의 다중 beat 버스트(narrow burst)를 보면 표시한다.
    // MIG는 narrow burst 미지원(C_S_AXI_SUPPORTS_NARROW_BURST=0)으로 생성했다.
    always @(posedge ui_clk) begin
        if (ui_rst || narrow_clr) narrow_seen <= 1'b0;
        else if ((h_awvalid && h_awready && h_awsize != 3'd5 && h_awlen != 8'd0) ||
                 (h_arvalid && h_arready && h_arsize != 3'd5 && h_arlen != 8'd0))
            narrow_seen <= 1'b1;
    end

    // ---------------- 상태 표시 ----------------
    reg [26:0] hb;
    always @(posedge ui_clk) hb <= hb + 27'd1;
    reg [1:0] lnk_s;
    always @(posedge ui_clk) lnk_s <= {lnk_s[0], lnk_up};

    vio_p3 u_vio (
        .clk(ui_clk),
        .probe_in0(calib),
        .probe_in1(lnk_s[1]),
        .probe_in2(tg_busy),
        .probe_in3(hb[26:11])
    );

    assign led_n    = ~{hb[26], tg_busy, lnk_s[1], calib};

`ifdef P3_FIT
    // ---------------- BRAM 적합성 실험 (P3.2·P3.4, build_p3.tcl -fit) ----------------
    // Traffic 생성기의 DDR3 읽기 데이터를 weight cache 쓰기(fill)로 쓴다.
    wire [31:0] fit_sig;
    mem_fit #(.N_ENT(`FIT_N_ENT), .SLICE_BUF(`FIT_SLICE_BUF), .BV_ALL40(`FIT_BV_ALL40),
              .Q_BRAM(`FIT_Q_BRAM)) u_fit (
        .clk(ui_clk), .rst(ui_rst),
        .fill_data(mi_rdata), .fill_valid(mi_rvalid & mi_rready & ~ddr_sel),
        .sig(fit_sig)
    );
    assign led_core = ^fit_sig;
`else
    assign led_core = calib;
`endif

endmodule
