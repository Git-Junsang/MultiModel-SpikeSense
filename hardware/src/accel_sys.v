// accel_sys.v — 100 MHz 쪽 전체: eth_link, ctrl, regs, frontend, accel_core와 MIG 입구 선택 (03_ARCHITECTURE.md §2)
//
// 추론 요청: Ethernet → eth_link → frontend → accel_core → frontend(result) → eth_link → Ethernet.
// 제어: Ethernet → eth_link → ctrl → regs(AXI4-Lite) 또는 DDR3 창(AXI4). 응답은 같은 길로 되돌아간다.
// reset: rst는 전원·MIG reset이고 제어 경로(eth_link, ctrl, regs의 설정)만 받는다. SOFT_RESET이 제어 packet으로 오므로
//        frontend·accel_core·시각·counter는 regs가 내는 core_rst를 받는다.
// MIG 입구: run = 1이면 dma, 0이면 ctrl의 DDR3 master. run은 IDLE에서만 바꾼다(06 §6). size 32 B, INCR, wstrb 전부 1,
//           ID 위 bit 0은 top이 묶는다. dma는 읽기 data를 ID bit 0으로 나누므로 m_axi_rid를 꼭 연결한다.

module accel_sys #(
    parameter        TARGET      = "GENERIC",
    parameter        RX_IDELAY   = 0,
    parameter [15:0] TX_PS       = 16'd0,               // 송신 clock 위상 기본값(LINK_TUNE bit[31:16])
    parameter        PHY_RST_CYC = 1_100_000,
    parameter        E           = 4,
    parameter        N_TRACKS    = 1024,
    parameter        N_MODELS    = 40,
    parameter        N_ONCHIP    = 768,
    parameter [31:0] VERSION     = 32'h0001_0000,
    parameter        EW          = (E > 1) ? $clog2(E) : 1
)(
    input  wire         clk,
    input  wire         rst,
    input  wire         mig_calib,
    input  wire         gtx_clk,
    input  wire         gtx_clk90,
    // RGMII PHY
    input  wire         rgmii_rx_clk,
    input  wire [3:0]   rgmii_rxd,
    input  wire         rgmii_rx_ctl,
    output wire         rgmii_tx_clk,
    output wire [3:0]   rgmii_txd,
    output wire         rgmii_tx_ctl,
    output wire         phy_reset_n,
    output wire         phy_mdc,
    inout  wire         phy_mdio,
    // MIG AXI4 master
    output wire [31:0]  m_axi_araddr,
    output wire [7:0]   m_axi_arlen,
    output wire         m_axi_arid,
    output wire         m_axi_arvalid,
    input  wire         m_axi_arready,
    input  wire [255:0] m_axi_rdata,
    input  wire         m_axi_rid,
    input  wire [1:0]   m_axi_rresp,
    input  wire         m_axi_rlast,
    input  wire         m_axi_rvalid,
    output wire         m_axi_rready,
    output wire [31:0]  m_axi_awaddr,
    output wire [7:0]   m_axi_awlen,
    output wire         m_axi_awvalid,
    input  wire         m_axi_awready,
    output wire [255:0] m_axi_wdata,
    output wire         m_axi_wlast,
    output wire         m_axi_wvalid,
    input  wire         m_axi_wready,
    input  wire [1:0]   m_axi_bresp,
    input  wire         m_axi_bvalid,
    output wire         m_axi_bready,
    // 송신 clock 위상(LINK_TUNE bit[31:16]) → top의 MMCM 미세 위상 이동
    output wire [15:0]  tx_ps,
    // 상태(LED)
    output wire         run,
    output wire         sys_idle
);

    // ---------------- 신호 ----------------
    wire         core_rst, cnt_clear, cfg_we, first_epoch;
    wire [10:0]  n_tracks, cfg_addr, pending_n;
    wire [5:0]   n_models;
    wire [31:0]  model_base, state_base, deadline_us, margin_us, now_us, link_tune;
    wire [63:0]  now_cyc, stall_cyc;
    wire [14:0]  phase_us;
    wire [15:0]  epoch, cfg_data;

    wire         rq_valid, rq_ready, rs_valid, rs_ready, len_err_valid;
    wire [511:0] rq_data;
    wire [255:0] rs_data;
    wire [31:0]  len_err_info;
    wire [7:0]   cq_tdata, cr_tdata;
    wire         cq_tvalid, cq_tready, cq_tlast, cr_tvalid, cr_tready, cr_tlast;
    wire [10:0]  cr_len;

    wire [31:0]  l_awaddr, l_wdata, l_araddr, l_rdata;
    wire [3:0]   l_wstrb;
    wire [1:0]   l_bresp, l_rresp;
    wire         l_awvalid, l_awready, l_wvalid, l_wready, l_bvalid, l_bready, l_arvalid, l_arready, l_rvalid, l_rready;

    wire [N_MODELS-1:0] q_ne;
    wire         arr_valid, pl_valid, pl_ready, pl_done, pl_hit, pl_evict, pf_valid, pf_reset, pf_ready;
    wire         go_valid, go_ready, go_reset, busy, done, wb_done, sat16, dma_idle, dma_err, fe_idle;
    wire [5:0]   arr_model, pl_model, pl_victim;
    wire [31:0]  arr_t_host, dma_err_addr;
    wire [10:0]  arr_n_expect;
    wire [EW-1:0] pl_entry, go_entry;
    wire [9:0]   pf_track, go_track, wb_track;
    wire [319:0] go_x;
    wire [15:0]  out_mem0, out_mem1;
    wire [1:0]   ev_state_xfer;
    wire         ev_req_in, ev_req_drop, ev_res_out, ev_late, ev_batch, ev_load, ev_sat, fe_err_valid;
    wire [3:0]   fe_err_code;
    wire [31:0]  fe_err_info;

    // dma(d_*)와 ctrl(c_*) DDR3 master
    wire [31:0]  d_araddr, d_awaddr, c_araddr, c_awaddr;
    wire [7:0]   d_arlen, d_awlen, c_arlen, c_awlen;
    wire [255:0] d_wdata, c_wdata;
    wire         d_arid, d_arvalid, d_rready, d_awvalid, d_wlast, d_wvalid, d_bready;
    wire         c_arvalid, c_rready, c_awvalid, c_wlast, c_wvalid, c_bready;

    assign sys_idle = fe_idle && dma_idle && !busy;
    assign tx_ps    = link_tune[31:16];

    // ---------------- 제어 경로 ----------------
    eth_link #(.TARGET(TARGET), .RX_IDELAY(RX_IDELAY), .PHY_RST_CYC(PHY_RST_CYC)) u_eth (
        .clk(clk), .rst(rst), .gtx_clk(gtx_clk), .gtx_clk90(gtx_clk90), .rx_tap(link_tune[4:0]),
        .rgmii_rx_clk(rgmii_rx_clk), .rgmii_rxd(rgmii_rxd), .rgmii_rx_ctl(rgmii_rx_ctl),
        .rgmii_tx_clk(rgmii_tx_clk), .rgmii_txd(rgmii_txd), .rgmii_tx_ctl(rgmii_tx_ctl),
        .phy_reset_n(phy_reset_n), .phy_mdc(phy_mdc), .phy_mdio(phy_mdio),
        .rq_valid(rq_valid), .rq_ready(rq_ready), .rq_data(rq_data),
        .len_err_valid(len_err_valid), .len_err_info(len_err_info),
        .rs_valid(rs_valid), .rs_ready(rs_ready), .rs_data(rs_data),
        .cq_tdata(cq_tdata), .cq_tvalid(cq_tvalid), .cq_tready(cq_tready), .cq_tlast(cq_tlast),
        .cr_tdata(cr_tdata), .cr_tvalid(cr_tvalid), .cr_tready(cr_tready), .cr_tlast(cr_tlast), .cr_len(cr_len)
    );

    ctrl u_ctrl (
        .clk(clk), .rst(rst), .run(run || !mig_calib),          // MIG 보정 전 DDR3 창 접근은 status 2로 거부
        .cq_tdata(cq_tdata), .cq_tvalid(cq_tvalid), .cq_tready(cq_tready), .cq_tlast(cq_tlast),
        .cr_tdata(cr_tdata), .cr_tvalid(cr_tvalid), .cr_tready(cr_tready), .cr_tlast(cr_tlast), .cr_len(cr_len),
        .m_axil_awaddr(l_awaddr), .m_axil_awvalid(l_awvalid), .m_axil_awready(l_awready),
        .m_axil_wdata(l_wdata), .m_axil_wstrb(l_wstrb), .m_axil_wvalid(l_wvalid), .m_axil_wready(l_wready),
        .m_axil_bresp(l_bresp), .m_axil_bvalid(l_bvalid), .m_axil_bready(l_bready),
        .m_axil_araddr(l_araddr), .m_axil_arvalid(l_arvalid), .m_axil_arready(l_arready),
        .m_axil_rdata(l_rdata), .m_axil_rresp(l_rresp), .m_axil_rvalid(l_rvalid), .m_axil_rready(l_rready),
        .m_araddr(c_araddr), .m_arlen(c_arlen), .m_arvalid(c_arvalid), .m_arready(m_axi_arready && !run),
        .m_rdata(m_axi_rdata), .m_rlast(m_axi_rlast), .m_rresp(m_axi_rresp), .m_rvalid(m_axi_rvalid && !run), .m_rready(c_rready),
        .m_awaddr(c_awaddr), .m_awlen(c_awlen), .m_awvalid(c_awvalid), .m_awready(m_axi_awready && !run),
        .m_wdata(c_wdata), .m_wlast(c_wlast), .m_wvalid(c_wvalid), .m_wready(m_axi_wready && !run),
        .m_bresp(m_axi_bresp), .m_bvalid(m_axi_bvalid && !run), .m_bready(c_bready)
    );

    regs #(.N_ENTRY(E), .N_ONCHIP(N_ONCHIP), .VERSION(VERSION), .LINK_TUNE0({TX_PS, 11'd0, RX_IDELAY[4:0]})) u_regs (
        .clk(clk), .rst(rst),
        .s_axil_awaddr(l_awaddr), .s_axil_awvalid(l_awvalid), .s_axil_awready(l_awready),
        .s_axil_wdata(l_wdata), .s_axil_wstrb(l_wstrb), .s_axil_wvalid(l_wvalid), .s_axil_wready(l_wready),
        .s_axil_bresp(l_bresp), .s_axil_bvalid(l_bvalid), .s_axil_bready(l_bready),
        .s_axil_araddr(l_araddr), .s_axil_arvalid(l_arvalid), .s_axil_arready(l_arready),
        .s_axil_rdata(l_rdata), .s_axil_rresp(l_rresp), .s_axil_rvalid(l_rvalid), .s_axil_rready(l_rready),
        .mig_calib(mig_calib), .sys_idle(sys_idle),
        .run(run), .core_rst(core_rst), .cnt_clear(cnt_clear),
        .n_tracks(n_tracks), .n_models(n_models), .model_base(model_base), .state_base(state_base),
        .deadline_us(deadline_us), .margin_us(margin_us), .link_tune(link_tune),
        .cfg_we(cfg_we), .cfg_addr(cfg_addr), .cfg_data(cfg_data),
        .now_us(now_us), .now_cyc(now_cyc), .phase_us(phase_us), .epoch(epoch), .first_epoch(first_epoch),
        .ev_req_in(ev_req_in), .ev_req_drop(ev_req_drop), .ev_res_out(ev_res_out), .ev_late(ev_late),
        .ev_batch(ev_batch), .ev_load(ev_load), .ev_sat(ev_sat), .ev_state_xfer(ev_state_xfer),
        .pending_n(pending_n), .cmp_busy(busy), .stall_cyc(stall_cyc),
        .err0_valid(fe_err_valid), .err0_code(fe_err_code), .err0_info(fe_err_info),
        .err1_valid(dma_err), .err1_info(dma_err_addr),
        .err2_valid(len_err_valid), .err2_info(len_err_info)
    );

    // ---------------- 연산 경로 ----------------
    frontend #(.N_TRACKS(N_TRACKS), .N_MODELS(N_MODELS), .N_ONCHIP(N_ONCHIP), .EW(EW)) u_fe (
        .clk(clk), .rst(core_rst), .run(run), .n_tracks(n_tracks), .n_models(n_models),
        .deadline_us(deadline_us), .margin_us(margin_us), .now_us(now_us),
        .rq_valid(rq_valid), .rq_ready(rq_ready), .rq_data(rq_data),
        .rs_valid(rs_valid), .rs_ready(rs_ready), .rs_data(rs_data),
        .q_ne(q_ne), .arr_valid(arr_valid), .arr_model(arr_model), .arr_t_host(arr_t_host), .arr_n_expect(arr_n_expect),
        .pl_valid(pl_valid), .pl_model(pl_model), .pl_ready(pl_ready), .pl_done(pl_done), .pl_entry(pl_entry), .pl_hit(pl_hit),
        .pf_valid(pf_valid), .pf_track(pf_track), .pf_reset(pf_reset), .pf_ready(pf_ready),
        .go_valid(go_valid), .go_ready(go_ready), .go_entry(go_entry), .go_track(go_track), .go_reset(go_reset), .go_x(go_x),
        .done(done), .out_mem0(out_mem0), .out_mem1(out_mem1), .sat16(sat16), .wb_done(wb_done),
        .ev_req_in(ev_req_in), .ev_req_drop(ev_req_drop), .ev_res_out(ev_res_out), .ev_late(ev_late),
        .ev_batch(ev_batch), .ev_load(ev_load), .ev_sat(ev_sat), .pending_n(pending_n),
        .err_valid(fe_err_valid), .err_code(fe_err_code), .err_info(fe_err_info), .idle(fe_idle)
    );

    accel_core #(.E(E), .N_MODELS(N_MODELS), .N_ONCHIP(N_ONCHIP)) u_core (
        .clk(clk), .rst(core_rst), .model_base(model_base), .state_base(state_base),
        .now_us(now_us), .phase_us(phase_us), .epoch(epoch), .first_epoch(first_epoch),
        .cfg_we(cfg_we), .cfg_addr(cfg_addr), .cfg_data(cfg_data),
        .arr_valid(arr_valid), .arr_model(arr_model), .arr_t_host(arr_t_host), .arr_n_expect(arr_n_expect), .q_ne(q_ne),
        .pl_valid(pl_valid), .pl_model(pl_model), .pl_ready(pl_ready), .pl_done(pl_done),
        .pl_entry(pl_entry), .pl_hit(pl_hit), .pl_evict(pl_evict), .pl_victim(pl_victim),
        .pf_valid(pf_valid), .pf_track(pf_track), .pf_reset(pf_reset), .pf_ready(pf_ready),
        .go_valid(go_valid), .go_ready(go_ready), .go_entry(go_entry), .go_track(go_track), .go_reset(go_reset), .go_x(go_x),
        .busy(busy), .done(done), .out_mem0(out_mem0), .out_mem1(out_mem1), .wb_done(wb_done), .wb_track(wb_track),
        .sat16(sat16), .cnt_clear(cnt_clear), .stall_cyc(stall_cyc), .dma_idle(dma_idle), .ev_state_xfer(ev_state_xfer),
        .err(dma_err), .err_addr(dma_err_addr),
        .m_araddr(d_araddr), .m_arlen(d_arlen), .m_arid(d_arid), .m_arvalid(d_arvalid), .m_arready(m_axi_arready && run),
        .m_rdata(m_axi_rdata), .m_rid(m_axi_rid), .m_rresp(m_axi_rresp), .m_rlast(m_axi_rlast), .m_rvalid(m_axi_rvalid && run),
        .m_rready(d_rready),
        .m_awaddr(d_awaddr), .m_awlen(d_awlen), .m_awvalid(d_awvalid), .m_awready(m_axi_awready && run),
        .m_wdata(d_wdata), .m_wlast(d_wlast), .m_wvalid(d_wvalid), .m_wready(m_axi_wready && run),
        .m_bresp(m_axi_bresp), .m_bvalid(m_axi_bvalid && run), .m_bready(d_bready)
    );

    // ---------------- MIG 입구 선택 ----------------
    assign m_axi_araddr  = run ? d_araddr  : c_araddr;
    assign m_axi_arlen   = run ? d_arlen   : c_arlen;
    assign m_axi_arid    = run ? d_arid    : 1'b0;
    assign m_axi_arvalid = run ? d_arvalid : c_arvalid;
    assign m_axi_rready  = run ? d_rready  : c_rready;
    assign m_axi_awaddr  = run ? d_awaddr  : c_awaddr;
    assign m_axi_awlen   = run ? d_awlen   : c_awlen;
    assign m_axi_awvalid = run ? d_awvalid : c_awvalid;
    assign m_axi_wdata   = run ? d_wdata   : c_wdata;
    assign m_axi_wlast   = run ? d_wlast   : c_wlast;
    assign m_axi_wvalid  = run ? d_wvalid  : c_wvalid;
    assign m_axi_bready  = run ? d_bready  : c_bready;

endmodule
