// accel_top.v — AX7A200B 보드 top: MIG DDR3, Ethernet clock, reset, LED와 accel_sys (03_ARCHITECTURE.md §2, 06_HOST_INTERFACE.md §3)
//
// clock: sys_clk 200 MHz 차동(R4/T4) → MIG → ui_clk 100 MHz(accel_sys 전체).
//        ui_clk → MMCME2_ADV(VCO 1,000 MHz) → gtx_clk 125 MHz, gtx_clk90 125 MHz 90°, ref_clk 200 MHz(IDELAYCTRL, RX_IDELAY > 0일 때만).
//        gtx_clk90(RGMII 송신 clock)은 LINK_TUNE bit[31:16](tx_ps, 부호 있음)만큼 미세 위상 이동한다. 1단계 = VCO 주기/56 = 17.9 ps.
//        1 Gb/s에서 gtx_clk → gtx_clk90 경로(rgmii_phy_if의 clock ODDR 입력)는 상수 1·0이라 위상을 옮겨도 된다.
// reset: RESET 버튼(rst_n, 누르면 0) → MIG sys_rst(ACTIVE LOW). accel_sys rst = MIG ui_clk_sync_rst 또는 Ethernet MMCM 미잠김,
//        ui_clk에 sync_reset으로 맞추고 FF 하나를 더 거친다. gtx_clk·RGMII 수신 clock 쪽 reset은 eth_link·rgmii_phy_if 안에서 맞춘다.
// MIG AXI: ID 4 bit 중 위 3 bit는 0. dma는 읽기 data를 ID bit 0으로 나누므로 rid bit 0을 돌려준다.
//          size 32 B, INCR, wstrb 전부 1. 주소는 아래 30 bit(1 GiB). aresetn은 ui_clk_sync_rst를 한 번 잡아 쓴다.
// RX_IDELAY·TX_PS: reset 때 LINK_TUNE 값. 보드(sub1 직결)에서 frame 손실을 재어 정했다(P5.2, p52_link.py).
//   송신 위상은 −144~−24단계(90°에서 2.57~0.43 ns 앞)에서 손실 0이라 가운데 −80(−1.43 ns). 90° 그대로면 KSZ9031 안쪽
//   TXC 지연(약 1.2 ns)이 더해져 PHY가 다음 nibble을 잡았다(하강 edge의 TXD[1]·TXD[3]).
//   수신 tap은 0~28에서 손실 0, 30 근처가 가장자리다. ax7a200b_eth.xdc의 STA 모델은 이보다 좁아 tap 11부터 setup이 음수라,
//   둘 다 만족하는 8(STA setup 0.23 ns, 보드 가장자리까지 1.68 ns)을 쓴다.
// LED(캐리어, 0이면 켜짐): LED1 MIG 보정 끝, LED2 RUN, LED3 IDLE, LED4 ui_clk 점멸. 코어보드 LED: Ethernet MMCM 잠김.

`timescale 1ns / 1ps

module accel_top #(
    parameter        RX_IDELAY = 8,
    parameter [15:0] TX_PS     = -16'sd80,
    parameter        E         = 4
)(
    input  wire        sys_clk_p,
    input  wire        sys_clk_n,
    input  wire        rst_n,
    input  wire [3:0]  key_n,           // 쓰지 않는다. 공용 ax7a200b_io.xdc를 그대로 쓰려고 둔다
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
    // RGMII PHY (KSZ9031RNX)
    input  wire        rgmii_rx_clk,
    input  wire [3:0]  rgmii_rxd,
    input  wire        rgmii_rx_ctl,
    output wire        rgmii_tx_clk,
    output wire [3:0]  rgmii_txd,
    output wire        rgmii_tx_ctl,
    output wire        phy_reset_n,
    output wire        phy_mdc,
    inout  wire        phy_mdio,
    // LED
    output wire        led_core,
    output wire [3:0]  led_n
);

    // ---------------- MIG ----------------
    wire ui_clk, ui_rst, calib, mig_locked;
    reg  mig_aresetn;
    always @(posedge ui_clk) mig_aresetn <= ~ui_rst;

    wire [31:0]  m_araddr, m_awaddr;
    wire [7:0]   m_arlen, m_awlen;
    wire         m_arid, m_arvalid, m_arready, m_rid, m_rlast, m_rvalid, m_rready;
    wire         m_awvalid, m_awready, m_wlast, m_wvalid, m_wready, m_bvalid, m_bready;
    wire [255:0] m_rdata, m_wdata;
    wire [1:0]   m_rresp, m_bresp;
    wire [3:0]   s_rid;
    assign m_rid = s_rid[0];

    mig_ddr3 u_mig (
        .ddr3_addr(ddr3_addr), .ddr3_ba(ddr3_ba), .ddr3_cas_n(ddr3_cas_n),
        .ddr3_ck_n(ddr3_ck_n), .ddr3_ck_p(ddr3_ck_p), .ddr3_cke(ddr3_cke),
        .ddr3_ras_n(ddr3_ras_n), .ddr3_reset_n(ddr3_reset_n), .ddr3_we_n(ddr3_we_n),
        .ddr3_dq(ddr3_dq), .ddr3_dqs_n(ddr3_dqs_n), .ddr3_dqs_p(ddr3_dqs_p),
        .ddr3_cs_n(ddr3_cs_n), .ddr3_dm(ddr3_dm), .ddr3_odt(ddr3_odt),
        .init_calib_complete(calib), .device_temp(),
        .ui_clk(ui_clk), .ui_clk_sync_rst(ui_rst), .mmcm_locked(mig_locked),
        .aresetn(mig_aresetn),
        .app_sr_req(1'b0), .app_ref_req(1'b0), .app_zq_req(1'b0),
        .app_sr_active(), .app_ref_ack(), .app_zq_ack(),
        .s_axi_awid(4'd0), .s_axi_awaddr(m_awaddr[29:0]), .s_axi_awlen(m_awlen),
        .s_axi_awsize(3'd5), .s_axi_awburst(2'b01), .s_axi_awlock(1'b0),
        .s_axi_awcache(4'b0011), .s_axi_awprot(3'b000), .s_axi_awqos(4'd0),
        .s_axi_awvalid(m_awvalid), .s_axi_awready(m_awready),
        .s_axi_wdata(m_wdata), .s_axi_wstrb({32{1'b1}}), .s_axi_wlast(m_wlast),
        .s_axi_wvalid(m_wvalid), .s_axi_wready(m_wready),
        .s_axi_bid(), .s_axi_bresp(m_bresp), .s_axi_bvalid(m_bvalid), .s_axi_bready(m_bready),
        .s_axi_arid({3'b000, m_arid}), .s_axi_araddr(m_araddr[29:0]), .s_axi_arlen(m_arlen),
        .s_axi_arsize(3'd5), .s_axi_arburst(2'b01), .s_axi_arlock(1'b0),
        .s_axi_arcache(4'b0011), .s_axi_arprot(3'b000), .s_axi_arqos(4'd0),
        .s_axi_arvalid(m_arvalid), .s_axi_arready(m_arready),
        .s_axi_rid(s_rid), .s_axi_rdata(m_rdata), .s_axi_rresp(m_rresp), .s_axi_rlast(m_rlast),
        .s_axi_rvalid(m_rvalid), .s_axi_rready(m_rready),
        .sys_clk_p(sys_clk_p), .sys_clk_n(sys_clk_n), .sys_rst(rst_n)
    );

    // ---------------- Ethernet clock ----------------
    wire fb, fb_buf, gtx_clk_u, gtx_clk90_u, ref_clk_u, eth_locked;
    wire gtx_clk, gtx_clk90;

    wire              ps_done;
    wire [15:0]       tx_ps;
    reg signed [15:0] ps_cur = 16'sd0;
    reg               ps_en = 1'b0, ps_inc = 1'b0, ps_busy = 1'b0;
    MMCME2_ADV #(
        .CLKIN1_PERIOD(10.0), .DIVCLK_DIVIDE(1), .CLKFBOUT_MULT_F(10.0),
        .CLKOUT0_DIVIDE_F(8.0), .CLKOUT0_PHASE(0.0),
        .CLKOUT1_DIVIDE(8),     .CLKOUT1_PHASE(90.0), .CLKOUT1_USE_FINE_PS("TRUE"),
        .CLKOUT2_DIVIDE(5),     .CLKOUT2_PHASE(0.0)
    ) u_mmcm (
        .CLKIN1(ui_clk), .CLKIN2(1'b0), .CLKINSEL(1'b1), .RST(ui_rst), .PWRDWN(1'b0), .LOCKED(eth_locked),
        .CLKFBIN(fb_buf), .CLKFBOUT(fb), .CLKFBOUTB(),
        .CLKOUT0(gtx_clk_u), .CLKOUT0B(), .CLKOUT1(gtx_clk90_u), .CLKOUT1B(),
        .CLKOUT2(ref_clk_u), .CLKOUT2B(), .CLKOUT3(), .CLKOUT3B(), .CLKOUT4(), .CLKOUT5(), .CLKOUT6(),
        .PSCLK(ui_clk), .PSEN(ps_en), .PSINCDEC(ps_inc), .PSDONE(ps_done),
        .DCLK(1'b0), .DEN(1'b0), .DWE(1'b0), .DADDR(7'd0), .DI(16'd0), .DO(), .DRDY(),
        .CLKINSTOPPED(), .CLKFBSTOPPED()
    );
    // 미세 위상: 지금 단계(ps_cur)가 tx_ps와 다르면 한 단계씩 옮기고 PSDONE을 기다린다. MMCM이 다시 잠기면 처음(90°)부터
    always @(posedge ui_clk) begin
        ps_en <= 1'b0;
        if (!eth_locked) begin
            ps_cur  <= 16'sd0;
            ps_busy <= 1'b0;
        end else if (ps_busy) begin
            if (ps_done) ps_busy <= 1'b0;
        end else if (ps_cur != $signed(tx_ps)) begin
            ps_en   <= 1'b1;
            ps_inc  <= ps_cur < $signed(tx_ps);
            ps_cur  <= (ps_cur < $signed(tx_ps)) ? ps_cur + 16'sd1 : ps_cur - 16'sd1;
            ps_busy <= 1'b1;
        end
    end
    BUFG u_fb_bufg    (.I(fb),          .O(fb_buf));
    BUFG u_gtx_bufg   (.I(gtx_clk_u),   .O(gtx_clk));
    BUFG u_gtx90_bufg (.I(gtx_clk90_u), .O(gtx_clk90));

    // ---------------- reset ----------------
    // sync_reset 출력은 비동기로 올라간다. BRAM 주소·제어로 가므로 FF 하나를 더 두어 동기 reset으로 만든다(DRC REQP-1840).
    wire sys_rst_a;
    (* max_fanout = 64 *) reg sys_rst = 1'b1;    // 퍼짐이 커 reset 배선만 9 ns가 걸렸다
    sync_reset #(.N(4)) u_sys_rst (.clk(ui_clk), .rst(ui_rst || !eth_locked), .out(sys_rst_a));
    always @(posedge ui_clk) sys_rst <= sys_rst_a;

    generate
        if (RX_IDELAY != 0) begin : g_idelayctrl
            wire ref_clk, ref_rst;
            BUFG u_ref_bufg (.I(ref_clk_u), .O(ref_clk));
            sync_reset #(.N(4)) u_ref_rst (.clk(ref_clk), .rst(!eth_locked), .out(ref_rst));
            IDELAYCTRL u_idelayctrl (.REFCLK(ref_clk), .RST(ref_rst), .RDY());
        end
    endgenerate

    // ---------------- accel_sys ----------------
    wire run, sys_idle;

    accel_sys #(.TARGET("XILINX"), .RX_IDELAY(RX_IDELAY), .TX_PS(TX_PS), .E(E)) u_sys (
        .clk(ui_clk), .rst(sys_rst), .mig_calib(calib), .gtx_clk(gtx_clk), .gtx_clk90(gtx_clk90),
        .rgmii_rx_clk(rgmii_rx_clk), .rgmii_rxd(rgmii_rxd), .rgmii_rx_ctl(rgmii_rx_ctl),
        .rgmii_tx_clk(rgmii_tx_clk), .rgmii_txd(rgmii_txd), .rgmii_tx_ctl(rgmii_tx_ctl),
        .phy_reset_n(phy_reset_n), .phy_mdc(phy_mdc), .phy_mdio(phy_mdio),
        .m_axi_araddr(m_araddr), .m_axi_arlen(m_arlen), .m_axi_arid(m_arid), .m_axi_arvalid(m_arvalid),
        .m_axi_arready(m_arready), .m_axi_rdata(m_rdata), .m_axi_rid(m_rid), .m_axi_rresp(m_rresp),
        .m_axi_rlast(m_rlast), .m_axi_rvalid(m_rvalid), .m_axi_rready(m_rready),
        .m_axi_awaddr(m_awaddr), .m_axi_awlen(m_awlen), .m_axi_awvalid(m_awvalid), .m_axi_awready(m_awready),
        .m_axi_wdata(m_wdata), .m_axi_wlast(m_wlast), .m_axi_wvalid(m_wvalid), .m_axi_wready(m_wready),
        .m_axi_bresp(m_bresp), .m_axi_bvalid(m_bvalid), .m_axi_bready(m_bready),
        .tx_ps(tx_ps), .run(run), .sys_idle(sys_idle)
    );

    // ---------------- LED ----------------
    reg [26:0] hb = 27'd0;
    always @(posedge ui_clk) hb <= hb + 27'd1;
    assign led_n    = ~{hb[26], sys_idle, run, calib};
    assign led_core = eth_locked;

endmodule
