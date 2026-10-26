// ============================================================
// p43_timing_top.v — P4.3 timing 확인용 wrapper (out-of-context)
// ============================================================
// compute_array + weight_cache(entry 4개, next_use_predictor) + membrane_storage(on-chip 768트랙).
// p42_timing_top의 entry 4개·출력 mux를 weight_cache로 바꿨다. predictor 설정·도착·queue·교체 계획과
// DMA port(weight 쓰기, membrane potential)는 밖으로 낸다. Scheduler·DMA·ingest는 없다(P4.4~P4.6).
// ============================================================
`timescale 1ns / 1ps

module p43_timing_top (
    input  wire         clk,
    input  wire         rst,
    input  wire         start,
    input  wire         reset_state,
    input  wire [319:0] x_in,
    output wire         busy,
    output wire         done,
    output wire [15:0]  out_mem0,
    output wire [15:0]  out_mem1,
    // weight_cache
    input  wire [31:0]  now_us,
    input  wire [14:0]  phase_us,
    input  wire [15:0]  period,
    input  wire         first_period,
    input  wire         cfg_we,
    input  wire [10:0]  cfg_addr,
    input  wire [15:0]  cfg_data,
    input  wire         arr_valid,
    input  wire [5:0]   arr_model,
    input  wire [31:0]  arr_t_host,
    input  wire [10:0]  arr_n_expect,
    input  wire [39:0]  q_ne,
    input  wire         pl_valid,
    input  wire [5:0]   pl_model,
    output wire         pl_ready,
    output wire         pl_done,
    output wire [1:0]   pl_entry,
    output wire         pl_hit,
    output wire         pl_evict,
    output wire [5:0]   pl_victim,
    output wire         ld_busy,
    output wire [1:0]   ld_entry,
    output wire [5:0]   ld_model,
    input  wire         ld_done,
    input  wire         wr_we,
    input  wire [10:0]  wr_addr,
    input  wire [511:0] wr_data,
    input  wire         wr_pwe,
    input  wire [5:0]   wr_paddr,
    input  wire [255:0] wr_pdata,
    input  wire [1:0]   sel,           // 연산할 entry (pl_entry)
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
    wire [511:0] w_a_data, w_b_data;
    wire [5:0]   p_addr, m_rd_row, m_wr_row;
    wire [255:0] p_data, m_rd_data, m_wr_data;

    always @(posedge clk)
        if (!busy) sel_q <= sel;

    weight_cache #(.E(4)) u_wc (
        .clk(clk), .rst(rst),
        .now_us(now_us), .phase_us(phase_us), .period(period), .first_period(first_period),
        .cfg_we(cfg_we), .cfg_addr(cfg_addr), .cfg_data(cfg_data),
        .arr_valid(arr_valid), .arr_model(arr_model), .arr_t_host(arr_t_host), .arr_n_expect(arr_n_expect),
        .q_ne(q_ne),
        .pl_valid(pl_valid), .pl_model(pl_model), .pl_ready(pl_ready), .pl_done(pl_done),
        .pl_entry(pl_entry), .pl_hit(pl_hit), .pl_evict(pl_evict), .pl_victim(pl_victim),
        .ld_busy(ld_busy), .ld_entry(ld_entry), .ld_model(ld_model), .ld_done(ld_done),
        .wr_we(wr_we), .wr_addr(wr_addr), .wr_data(wr_data), .wr_pwe(wr_pwe), .wr_paddr(wr_paddr), .wr_pdata(wr_pdata),
        .cmp_entry(sel_q), .w_en(w_en), .w_a_addr(w_a_addr), .w_b_addr(w_b_addr),
        .w_a_data(w_a_data), .w_b_data(w_b_data), .p_addr(p_addr), .p_data(p_data)
    );

    compute_array u_ca (
        .clk(clk), .rst(rst),
        .start(start), .reset_state(reset_state), .x_in(x_in),
        .busy(busy), .done(done), .out_mem0(out_mem0), .out_mem1(out_mem1),
        .w_en(w_en), .w_a_addr(w_a_addr), .w_b_addr(w_b_addr),
        .w_a_data(w_a_data), .w_b_data(w_b_data), .p_addr(p_addr), .p_data(p_data),
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
