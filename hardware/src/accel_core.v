// accel_core.v — compute_array, weight_cache, membrane_storage, dma를 묶은 연산 경로 (03_ARCHITECTURE.md §2·§3)
//
// scheduler(track_scheduler, P4.5)가 쓰는 port:
//   교체 계획 pl_*   weight_cache 그대로. batch i를 연산하는 동안 batch i+1의 모델을 알리면 miss일 때 dma가
//                   그 entry에 적재한다(prefetch). batch i+1이 시작된 뒤에 batch i+2를 알린다(연산 중 entry 보호).
//   준비 pf_*        membrane_storage 그대로. DDR3 트랙은 연산 전에 준비한다.
//   추론 go_*        go_valid를 올리고 그 batch의 entry(pl_entry), 트랙, 입력을 둔다. compute array가 비고,
//                   그 entry의 적재가 끝났고, membrane potential이 준비되면 받는다(go_ready, 그 cycle에 시작).
//   결과            done·out_mem은 compute_array, wb_done은 DDR3 트랙의 되쓰기 응답(결과는 그 뒤에 보낸다).
// compute array가 비었는데 적재나 membrane potential 준비 때문에 go를 받지 못한 cycle을 stall_cyc로 센다
// (CMP_STALL, 06_HOST_INTERFACE.md §7). DDR3는 dma의 AXI4 master 하나로 MIG에 붙는다.

module accel_core #(
    parameter E        = 4,
    parameter N_MODELS = 40,
    parameter N_ONCHIP = 768,
    parameter EW       = (E > 1) ? $clog2(E) : 1
)(
    input  wire                clk,
    input  wire                rst,
    input  wire [31:0]         model_base,
    input  wire [31:0]         state_base,
    // predictor 시각·설정·도착·queue
    input  wire [31:0]         now_us,
    input  wire [14:0]         phase_us,
    input  wire [15:0]         epoch,
    input  wire                first_epoch,
    input  wire                cfg_we,
    input  wire [10:0]         cfg_addr,
    input  wire [15:0]         cfg_data,
    input  wire                arr_valid,
    input  wire [5:0]          arr_model,
    input  wire [31:0]         arr_t_host,
    input  wire [10:0]         arr_n_expect,
    input  wire [N_MODELS-1:0] q_ne,
    // 교체 계획
    input  wire                pl_valid,
    input  wire [5:0]          pl_model,
    output wire                pl_ready,
    output wire                pl_done,
    output wire [EW-1:0]       pl_entry,
    output wire                pl_hit,
    output wire                pl_evict,
    output wire [5:0]          pl_victim,
    // membrane potential 준비
    input  wire                pf_valid,
    input  wire [9:0]          pf_track,
    input  wire                pf_reset,
    output wire                pf_ready,
    // 추론
    input  wire                go_valid,
    output wire                go_ready,
    input  wire [EW-1:0]       go_entry,
    input  wire [9:0]          go_track,
    input  wire                go_reset,
    input  wire [319:0]        go_x,
    output wire                busy,
    output wire                done,
    output wire [15:0]         out_mem0,
    output wire [15:0]         out_mem1,
    output wire                wb_done,
    output wire [9:0]          wb_track,
    output wire                sat16,         // 이번 추론에서 16 bit 연산 포화(done 때 유효)
    // 계측·상태
    input  wire                cnt_clear,
    output reg  [63:0]         stall_cyc,
    output wire                dma_idle,
    output wire [1:0]          ev_state_xfer, // 이번 cycle에 받은 membrane potential 전송 수(읽기·쓰기, 하나 = 1,088 B)
    output wire                err,
    output wire [31:0]         err_addr,
    // AXI4 master (dma.v)
    output wire [31:0]         m_araddr,
    output wire [7:0]          m_arlen,
    output wire                m_arid,
    output wire                m_arvalid,
    input  wire                m_arready,
    input  wire [255:0]        m_rdata,
    input  wire                m_rid,
    input  wire [1:0]          m_rresp,
    input  wire                m_rlast,
    input  wire                m_rvalid,
    output wire                m_rready,
    output wire [31:0]         m_awaddr,
    output wire [7:0]          m_awlen,
    output wire                m_awvalid,
    input  wire                m_awready,
    output wire [255:0]        m_wdata,
    output wire                m_wlast,
    output wire                m_wvalid,
    input  wire                m_wready,
    input  wire [1:0]          m_bresp,
    input  wire                m_bvalid,
    output wire                m_bready
);

    wire         ld_busy, ld_done;
    wire [EW-1:0] ld_entry;
    wire [5:0]   ld_model;
    wire         wr_we, wr_pwe;
    wire [10:0]  wr_addr;
    wire [511:0] wr_data;
    wire [5:0]   wr_paddr;
    wire [255:0] wr_pdata;

    wire         w_en, m_rd_en, m_wr_en, can_start;
    wire [10:0]  w_a_addr, w_b_addr;
    wire [511:0] w_a_data, w_b_data;
    wire [5:0]   p_addr, m_rd_row, m_wr_row;
    wire [255:0] p_data, m_rd_data, m_wr_data;

    wire         dr_req_valid, dr_req_ready, dr_valid, dw_req_valid, dw_req_ready, dw_valid, dw_ready, dw_resp;
    wire [31:0]  dr_req_addr, dw_req_addr;
    wire [255:0] dr_data, dw_data;

    assign ev_state_xfer = {1'b0, dr_req_valid && dr_req_ready} + {1'b0, dw_req_valid && dw_req_ready};

    // ---------------- 추론 시작 ----------------
    reg  [EW-1:0] cmp_entry;
    wire          w_ready = !(ld_busy && ld_entry == go_entry);
    wire          start   = go_valid && go_ready;
    assign go_ready = !busy && w_ready && can_start;

    always @(posedge clk) begin
        if (start) cmp_entry <= go_entry;
        if (rst || cnt_clear)
            stall_cyc <= 64'd0;
        else if (go_valid && !busy && !go_ready)
            stall_cyc <= stall_cyc + 64'd1;
    end

    weight_cache #(.E(E), .N_MODELS(N_MODELS)) u_wc (
        .clk(clk), .rst(rst),
        .now_us(now_us), .phase_us(phase_us), .epoch(epoch), .first_epoch(first_epoch),
        .cfg_we(cfg_we), .cfg_addr(cfg_addr), .cfg_data(cfg_data),
        .arr_valid(arr_valid), .arr_model(arr_model), .arr_t_host(arr_t_host), .arr_n_expect(arr_n_expect),
        .q_ne(q_ne),
        .pl_valid(pl_valid), .pl_model(pl_model), .pl_ready(pl_ready), .pl_done(pl_done),
        .pl_entry(pl_entry), .pl_hit(pl_hit), .pl_evict(pl_evict), .pl_victim(pl_victim),
        .ld_busy(ld_busy), .ld_entry(ld_entry), .ld_model(ld_model), .ld_done(ld_done),
        .wr_we(wr_we), .wr_addr(wr_addr), .wr_data(wr_data), .wr_pwe(wr_pwe), .wr_paddr(wr_paddr), .wr_pdata(wr_pdata),
        .cmp_entry(cmp_entry), .w_en(w_en), .w_a_addr(w_a_addr), .w_b_addr(w_b_addr),
        .w_a_data(w_a_data), .w_b_data(w_b_data), .p_addr(p_addr), .p_data(p_data)
    );

    compute_array u_ca (
        .clk(clk), .rst(rst),
        .start(start), .reset_state(go_reset), .x_in(go_x),
        .busy(busy), .done(done), .out_mem0(out_mem0), .out_mem1(out_mem1),
        .w_en(w_en), .w_a_addr(w_a_addr), .w_b_addr(w_b_addr),
        .w_a_data(w_a_data), .w_b_data(w_b_data), .p_addr(p_addr), .p_data(p_data),
        .m_rd_en(m_rd_en), .m_rd_row(m_rd_row), .m_rd_data(m_rd_data),
        .m_wr_en(m_wr_en), .m_wr_row(m_wr_row), .m_wr_data(m_wr_data),
        .sat16(sat16), .dbg_cur(), .dbg_mem_sat(), .dbg_spk()
    );

    membrane_storage #(.N_ONCHIP(N_ONCHIP)) u_ms (
        .clk(clk), .rst(rst), .state_base(state_base),
        .track(go_track), .can_start(can_start), .start(start), .done(done),
        .wb_done(wb_done), .wb_track(wb_track),
        .m_rd_en(m_rd_en), .m_rd_row(m_rd_row), .m_rd_data(m_rd_data),
        .m_wr_en(m_wr_en), .m_wr_row(m_wr_row), .m_wr_data(m_wr_data),
        .pf_valid(pf_valid), .pf_track(pf_track), .pf_reset(pf_reset), .pf_ready(pf_ready),
        .dr_req_valid(dr_req_valid), .dr_req_ready(dr_req_ready), .dr_req_addr(dr_req_addr),
        .dr_valid(dr_valid), .dr_data(dr_data),
        .dw_req_valid(dw_req_valid), .dw_req_ready(dw_req_ready), .dw_req_addr(dw_req_addr),
        .dw_valid(dw_valid), .dw_ready(dw_ready), .dw_data(dw_data), .dw_resp(dw_resp)
    );

    dma u_dma (
        .clk(clk), .rst(rst), .model_base(model_base),
        .ld_busy(ld_busy), .ld_model(ld_model), .ld_done(ld_done),
        .wr_we(wr_we), .wr_addr(wr_addr), .wr_data(wr_data), .wr_pwe(wr_pwe), .wr_paddr(wr_paddr), .wr_pdata(wr_pdata),
        .dr_req_valid(dr_req_valid), .dr_req_ready(dr_req_ready), .dr_req_addr(dr_req_addr),
        .dr_valid(dr_valid), .dr_data(dr_data),
        .dw_req_valid(dw_req_valid), .dw_req_ready(dw_req_ready), .dw_req_addr(dw_req_addr),
        .dw_valid(dw_valid), .dw_ready(dw_ready), .dw_data(dw_data), .dw_resp(dw_resp),
        .idle(dma_idle), .err(err), .err_addr(err_addr),
        .m_araddr(m_araddr), .m_arlen(m_arlen), .m_arid(m_arid), .m_arvalid(m_arvalid), .m_arready(m_arready),
        .m_rdata(m_rdata), .m_rid(m_rid), .m_rresp(m_rresp), .m_rlast(m_rlast), .m_rvalid(m_rvalid), .m_rready(m_rready),
        .m_awaddr(m_awaddr), .m_awlen(m_awlen), .m_awvalid(m_awvalid), .m_awready(m_awready),
        .m_wdata(m_wdata), .m_wlast(m_wlast), .m_wvalid(m_wvalid), .m_wready(m_wready),
        .m_bresp(m_bresp), .m_bvalid(m_bvalid), .m_bready(m_bready)
    );

endmodule
