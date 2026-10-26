// ============================================================
// p42_timing_top.v — P4.2 timing 확인용 wrapper (out-of-context)
// ============================================================
// p41_timing_top에서 1트랙 RAM을 membrane_storage(on-chip 768트랙 + DDR3 buffer)로 바꿨다.
// bank 주소 계산, 12 bit 변환, bank/buffer 선택이 compute_array 경로에 더해진다.
// Cache 교체·DMA는 없다(P4.3, P4.4). 적재 port와 DMA port는 밖으로 낸다.
// ============================================================
`timescale 1ns / 1ps

module p42_timing_top (
    input  wire         clk,
    input  wire         rst,
    input  wire         start,
    input  wire         reset_state,
    input  wire [319:0] x_in,
    input  wire [1:0]   sel,           // 연산할 entry
    input  wire [1:0]   ld_sel,        // 적재할 entry
    input  wire         ld_we,
    input  wire [10:0]  ld_addr,
    input  wire [511:0] ld_din,
    input  wire         ld_pwe,
    input  wire [5:0]   ld_paddr,
    input  wire [255:0] ld_pdin,
    output wire         busy,
    output wire         done,
    output wire [15:0]  out_mem0,
    output wire [15:0]  out_mem1,
    // membrane_storage
    input  wire [31:0]  state_base,
    input  wire [9:0]   track,
    output wire         can_start,
    output wire         wb_done,
    output wire [9:0]   wb_track,
    input  wire         pf_valid,
    input  wire [9:0]   pf_track,
    input  wire         pf_reset,
    output wire         pf_ready,
    output wire         dr_req_valid,
    input  wire         dr_req_ready,
    output wire [31:0]  dr_req_addr,
    input  wire         dr_valid,
    input  wire [255:0] dr_data,
    output wire         dw_req_valid,
    input  wire         dw_req_ready,
    output wire [31:0]  dw_req_addr,
    output wire         dw_valid,
    input  wire         dw_ready,
    output wire [255:0] dw_data,
    input  wire         dw_resp
);

    reg  [1:0]   sel_q;
    wire         w_en, m_rd_en, m_wr_en;
    wire [10:0]  w_a_addr, w_b_addr;
    wire [5:0]   p_addr, m_rd_row, m_wr_row;
    wire [255:0] m_wr_data;
    wire [255:0] m_rd_data;

    wire [511:0] a_d [0:3];
    wire [511:0] b_d [0:3];
    wire [255:0] p_d [0:3];

    always @(posedge clk)
        if (!busy) sel_q <= sel;

    genvar e;
    generate
        for (e = 0; e < 4; e = e + 1) begin : g_entry
            wire mine = (ld_sel == e) && ld_we;
            weight_entry u_entry (
                .clk(clk),
                .a_en(w_en && sel_q == e), .a_addr(w_a_addr), .a_dout(a_d[e]),
                .b_en((w_en && sel_q == e) || mine), .b_we(mine), .b_addr(mine ? ld_addr : w_b_addr),
                .b_din(ld_din), .b_dout(b_d[e]),
                .p_we(ld_pwe && ld_sel == e), .p_waddr(ld_paddr), .p_din(ld_pdin),
                .p_raddr(p_addr), .p_dout(p_d[e])
            );
        end
    endgenerate

    compute_array u_ca (
        .clk(clk), .rst(rst),
        .start(start), .reset_state(reset_state), .x_in(x_in),
        .busy(busy), .done(done), .out_mem0(out_mem0), .out_mem1(out_mem1),
        .w_en(w_en), .w_a_addr(w_a_addr), .w_b_addr(w_b_addr),
        .w_a_data(a_d[sel_q]), .w_b_data(b_d[sel_q]), .p_addr(p_addr), .p_data(p_d[sel_q]),
        .m_rd_en(m_rd_en), .m_rd_row(m_rd_row), .m_rd_data(m_rd_data),
        .m_wr_en(m_wr_en), .m_wr_row(m_wr_row), .m_wr_data(m_wr_data),
        .dbg_cur(), .dbg_mem_sat(), .dbg_spk()
    );

    membrane_storage #(.N_ON_CHIP(768)) u_ms (
        .clk(clk), .rst(rst), .state_base(state_base),
        .track(track), .can_start(can_start), .start(start), .done(done),
        .wb_done(wb_done), .wb_track(wb_track),
        .m_rd_en(m_rd_en), .m_rd_row(m_rd_row), .m_rd_data(m_rd_data),
        .m_wr_en(m_wr_en), .m_wr_row(m_wr_row), .m_wr_data(m_wr_data),
        .pf_valid(pf_valid), .pf_track(pf_track), .pf_reset(pf_reset), .pf_ready(pf_ready),
        .dr_req_valid(dr_req_valid), .dr_req_ready(dr_req_ready), .dr_req_addr(dr_req_addr),
        .dr_valid(dr_valid), .dr_data(dr_data),
        .dw_req_valid(dw_req_valid), .dw_req_ready(dw_req_ready), .dw_req_addr(dw_req_addr),
        .dw_valid(dw_valid), .dw_ready(dw_ready), .dw_data(dw_data), .dw_resp(dw_resp)
    );

endmodule
