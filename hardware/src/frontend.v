// frontend.v — 추론 요청을 받아 batch로 묶고 결과를 내는 쪽: ingest, req_table, track_scheduler, result (03_ARCHITECTURE.md §2·§3)
//
// 추론 요청 rq(64 B) → ingest가 검사해 req_table과 모델 목록에 넣는다 → track_scheduler가 Grouping으로 batch를 정해
// accel_core에 교체 계획(pl), membrane potential 준비(pf), 추론 시작(go)을 낸다 → done·wb_done 뒤 result가 결과 rs(32 B)를 낸다.
// 사건(ev_*)과 오류(err_*)는 regs의 counter·ERR_CODE로 간다. ev_load = miss로 정한 교체 계획(적재 한 번).

module frontend #(
    parameter N_TRACKS = 1024,
    parameter N_MODELS = 40,
    parameter N_ONCHIP = 768,
    parameter EW       = 2
)(
    input  wire                clk,
    input  wire                rst,
    // 설정·시각 (regs)
    input  wire                run,
    input  wire [10:0]         n_tracks,
    input  wire [5:0]          n_models,
    input  wire [31:0]         deadline_us,
    input  wire [31:0]         margin_us,
    input  wire [31:0]         now_us,
    // 추론 요청·결과
    input  wire                rq_valid,
    output wire                rq_ready,
    input  wire [511:0]        rq_data,
    output wire                rs_valid,
    input  wire                rs_ready,
    output wire [255:0]        rs_data,
    // accel_core
    output wire [N_MODELS-1:0] q_ne,
    output wire                arr_valid,
    output wire [5:0]          arr_model,
    output wire [31:0]         arr_t_host,
    output wire [10:0]         arr_n_expect,
    output wire                pl_valid,
    output wire [5:0]          pl_model,
    input  wire                pl_ready,
    input  wire                pl_done,
    input  wire [EW-1:0]       pl_entry,
    input  wire                pl_hit,
    output wire                pf_valid,
    output wire [9:0]          pf_track,
    output wire                pf_reset,
    input  wire                pf_ready,
    output wire                go_valid,
    input  wire                go_ready,
    output wire [EW-1:0]       go_entry,
    output wire [9:0]          go_track,
    output wire                go_reset,
    output wire [319:0]        go_x,
    input  wire                done,
    input  wire [15:0]         out_mem0,
    input  wire [15:0]         out_mem1,
    input  wire                sat16,
    input  wire                wb_done,
    // 사건·상태 (regs)
    output wire                ev_req_in,
    output wire                ev_req_drop,
    output wire                ev_res_out,
    output wire                ev_late,
    output wire                ev_batch,
    output wire                ev_load,
    output wire                ev_sat,
    output wire [10:0]         pending_n,
    output wire                err_valid,
    output wire [3:0]          err_code,
    output wire [31:0]         err_info,
    output wire                idle            // 받은 추론 요청을 모두 처리하고 결과를 보냈다
);

    wire [9:0]   chk_track, ap_track, hd_head, nx_track, nx_next, xr_track, mr_track, free_track;
    wire         chk_pend, ap_valid, sc_ne, dt_valid, xr_en, mr_en, free_valid, cp_valid, res_ok, s_idle, r_empty;
    wire [5:0]   ap_model, sc_model, hd_model, dt_model;
    wire [31:0]  ap_aseq, sc_hseq;
    wire [320:0] ap_xrs, xr_data;
    wire [86:0]  ap_meta, mr_data;
    wire [10:0]  q_total, dt_cnt, n_pend;
    wire [118:0] cp_data;

    assign pending_n = q_total;
    assign ev_load   = pl_done && !pl_hit;
    assign idle      = (n_pend == 11'd0) && s_idle && r_empty;

    ingest u_in (
        .clk(clk), .rst(rst), .run(run), .n_tracks(n_tracks), .n_models(n_models), .now_us(now_us),
        .rq_valid(rq_valid), .rq_ready(rq_ready), .rq_data(rq_data),
        .chk_track(chk_track), .chk_pend(chk_pend),
        .ap_valid(ap_valid), .ap_track(ap_track), .ap_model(ap_model), .ap_aseq(ap_aseq), .ap_xrs(ap_xrs), .ap_meta(ap_meta),
        .arr_valid(arr_valid), .arr_model(arr_model), .arr_t_host(arr_t_host), .arr_n_expect(arr_n_expect),
        .ev_req_in(ev_req_in), .ev_req_drop(ev_req_drop),
        .err_valid(err_valid), .err_code(err_code), .err_info(err_info)
    );

    req_table #(.N_TRACKS(N_TRACKS), .N_MODELS(N_MODELS)) u_rt (
        .clk(clk), .rst(rst),
        .chk_track(chk_track), .chk_pend(chk_pend),
        .ap_valid(ap_valid), .ap_track(ap_track), .ap_model(ap_model), .ap_aseq(ap_aseq), .ap_xrs(ap_xrs), .ap_meta(ap_meta),
        .q_ne(q_ne), .q_total(q_total),
        .sc_model(sc_model), .sc_ne(sc_ne), .sc_hseq(sc_hseq),
        .hd_model(hd_model), .hd_head(hd_head),
        .dt_valid(dt_valid), .dt_model(dt_model), .dt_cnt(dt_cnt),
        .nx_track(nx_track), .nx_next(nx_next),
        .xr_en(xr_en), .xr_track(xr_track), .xr_data(xr_data),
        .mr_en(mr_en), .mr_track(mr_track), .mr_data(mr_data),
        .free_valid(free_valid), .free_track(free_track), .n_pend(n_pend)
    );

    track_scheduler #(.N_MODELS(N_MODELS), .N_ONCHIP(N_ONCHIP), .EW(EW)) u_sch (
        .clk(clk), .rst(rst), .now_us(now_us),
        .q_total(q_total), .sc_model(sc_model), .sc_ne(sc_ne), .sc_hseq(sc_hseq),
        .hd_model(hd_model), .hd_head(hd_head), .dt_valid(dt_valid), .dt_model(dt_model), .dt_cnt(dt_cnt),
        .nx_track(nx_track), .nx_next(nx_next), .xr_en(xr_en), .xr_track(xr_track), .xr_data(xr_data),
        .pl_valid(pl_valid), .pl_model(pl_model), .pl_ready(pl_ready), .pl_done(pl_done), .pl_entry(pl_entry),
        .pf_valid(pf_valid), .pf_track(pf_track), .pf_reset(pf_reset), .pf_ready(pf_ready),
        .go_valid(go_valid), .go_ready(go_ready), .go_entry(go_entry), .go_track(go_track), .go_reset(go_reset), .go_x(go_x),
        .res_ok(res_ok),
        .done(done), .out_mem0(out_mem0), .out_mem1(out_mem1), .sat16(sat16),
        .cp_valid(cp_valid), .cp_data(cp_data),
        .ev_batch(ev_batch), .idle(s_idle)
    );

    result u_res (
        .clk(clk), .rst(rst), .deadline_us(deadline_us), .margin_us(margin_us),
        .cp_valid(cp_valid), .cp_data(cp_data), .res_ok(res_ok), .wb_done(wb_done),
        .mr_en(mr_en), .mr_track(mr_track), .mr_data(mr_data),
        .free_valid(free_valid), .free_track(free_track),
        .rs_valid(rs_valid), .rs_ready(rs_ready), .rs_data(rs_data),
        .ev_res_out(ev_res_out), .ev_late(ev_late), .ev_sat(ev_sat), .empty(r_empty)
    );

endmodule
