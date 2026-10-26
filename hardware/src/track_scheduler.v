// track_scheduler.v — Grouping scheduler (05_SCHEDULING.md §3, simulation_engine.md §5)
//
// 계획: 계획된 batch가 없고 대기 추론 요청이 있으면 모델 목록의 head 도착 순번을 모델 0–39 차례로 비교해 가장 오래 기다린
//   추론 요청의 모델을 고르고 weight_cache에 알린다(pl). miss면 그동안 DMA가 적재한다(prefetch).
//   계획은 앞 batch의 첫 추론이 시작된 뒤에만 한다. Simulator가 batch 시작 시각 s에 다음 batch를 고르는 것과 같다.
// 시작: 다음에 시작할 추론 요청(지금 batch의 다음 구성원, 다 시작했으면 계획된 batch의 head)의 입력을 읽고 pf로 준비한 뒤 go를 낸다.
//   계획된 batch의 head가 시작되는 cycle에 그 모델 목록 전체를 떼어 낸다. 그때까지 도착한 같은 모델 추론 요청이 모두 batch에 든다.
//   Batch 안에서는 도착 순서대로 시작한다. 결과 FIFO에 자리가 없으면(res_ok = 0) go를 내지 않는다.
// 완료: done마다 그 추론의 {트랙, 시작·완료 시각, batch 크기, 출력, 16 bit 포화, DDR3 트랙}을 result로 넘긴다.

module track_scheduler #(
    parameter N_MODELS = 40,
    parameter N_ON_CHIP = 768,
    parameter EW       = 2
)(
    input  wire          clk,
    input  wire          rst,
    input  wire [31:0]   now_us,
    // req_table
    input  wire [10:0]   q_total,
    output wire [5:0]    sc_model,
    input  wire          sc_ne,
    input  wire [31:0]   sc_hseq,
    output wire [5:0]    hd_model,
    input  wire [9:0]    hd_head,
    output wire          dt_valid,
    output wire [5:0]    dt_model,
    input  wire [10:0]   dt_cnt,
    output wire [9:0]    nx_track,
    input  wire [9:0]    nx_next,
    output wire          xr_en,
    output wire [9:0]    xr_track,
    input  wire [320:0]  xr_data,
    // 교체 계획
    output reg           pl_valid,
    output reg  [5:0]    pl_model,
    input  wire          pl_ready,
    input  wire          pl_done,
    input  wire [EW-1:0] pl_entry,
    // Membrane potential 준비
    output reg           pf_valid,
    output reg  [9:0]    pf_track,
    output reg           pf_reset,
    input  wire          pf_ready,
    // 추론 시작
    output wire          go_valid,
    input  wire          go_ready,
    output reg  [EW-1:0] go_entry,
    output reg  [9:0]    go_track,
    output reg           go_reset,
    output reg  [319:0]  go_x,
    input  wire          res_ok,
    // 연산 완료
    input  wire          done,
    input  wire [15:0]   out_mem0,
    input  wire [15:0]   out_mem1,
    input  wire          sat16,
    output reg           cp_valid,
    output reg  [118:0]  cp_data,       // {트랙 10, t_start 32, t_done 32, batch 크기 11, out0 16, out1 16, 포화, DDR3 트랙}
    // 사건·상태
    output reg           ev_batch,
    output wire          idle
);

    // ---------------- 계획 ----------------
    localparam [1:0] Q_IDLE = 2'd0, Q_SCAN = 2'd1, Q_PLAN = 2'd2, Q_WAIT = 2'd3;
    reg  [1:0]    qs;
    reg  [5:0]    si;                    // 비교 중인 모델
    reg           bv;
    reg  [5:0]    bm;
    reg  [31:0]   bseq;
    reg           pv;                    // 계획됐고 아직 시작 안 한 batch
    reg  [5:0]    pm;
    reg  [EW-1:0] pe;

    assign sc_model = si;
    wire older = !bv || $signed(sc_hseq - bseq) < 0;    // 순번은 돌아도 차이로 비교한다

    // ---------------- 시작 ----------------
    localparam [1:0] M_IDLE = 2'd0, M_READ = 2'd1, M_PF = 2'd2, M_GO = 2'd3;
    reg  [1:0]    ms;
    reg           rdc;
    reg           nfirst;                // 준비 중인 추론 요청이 계획된 batch의 head
    reg  [10:0]   cleft;                 // 지금 batch에서 아직 시작 안 한 구성원 수
    reg  [9:0]    cnext;
    reg  [10:0]   cn;                    // 지금 batch 크기
    reg  [EW-1:0] ce;

    wire have_cur = (cleft != 11'd0);
    assign hd_model = pm;
    assign xr_en    = (ms == M_IDLE) && (have_cur || pv);
    assign xr_track = have_cur ? cnext : hd_head;

    assign go_valid = (ms == M_GO) && res_ok;
    wire   start    = go_valid && go_ready;
    assign dt_valid = start && nfirst;
    assign dt_model = pm;
    assign nx_track = go_track;

    // 지금 연산 중인 추론
    reg  [9:0]  r_track;
    reg  [31:0] r_t0;
    reg  [10:0] r_bn;

    always @(posedge clk) begin
        ev_batch <= 1'b0;
        cp_valid <= 1'b0;
        if (rst) begin
            qs       <= Q_IDLE;
            pv       <= 1'b0;
            pl_valid <= 1'b0;
            ms       <= M_IDLE;
            pf_valid <= 1'b0;
            cleft    <= 11'd0;
        end else begin
            // 계획
            case (qs)
            Q_IDLE:
                if (!pv && q_total != 11'd0) begin
                    si <= 6'd0;
                    bv <= 1'b0;
                    qs <= Q_SCAN;
                end
            Q_SCAN: begin
                if (sc_ne && older) begin
                    bv   <= 1'b1;
                    bm   <= si;
                    bseq <= sc_hseq;
                end
                if (si == N_MODELS - 1) qs <= Q_PLAN;
                else si <= si + 6'd1;
            end
            Q_PLAN:
                if (!bv) qs <= Q_IDLE;
                else begin
                    pl_valid <= 1'b1;
                    pl_model <= bm;
                    qs       <= Q_WAIT;
                end
            default: begin                                  // Q_WAIT
                if (pl_valid && pl_ready) pl_valid <= 1'b0;
                if (pl_done) begin
                    pv <= 1'b1;
                    pm <= bm;
                    pe <= pl_entry;
                    qs <= Q_IDLE;
                end
            end
            endcase

            // 다음 추론 준비와 시작
            case (ms)
            M_IDLE:
                if (have_cur || pv) begin
                    go_track <= xr_track;
                    go_entry <= have_cur ? ce : pe;
                    nfirst   <= !have_cur;
                    rdc      <= 1'b0;
                    ms       <= M_READ;
                end
            M_READ: begin                                   // req_table 읽기 지연 2
                rdc <= 1'b1;
                if (rdc) begin
                    go_x     <= xr_data[319:0];
                    go_reset <= xr_data[320];
                    pf_valid <= 1'b1;
                    pf_track <= go_track;
                    pf_reset <= xr_data[320];
                    ms       <= M_PF;
                end
            end
            M_PF:
                if (pf_ready) begin
                    pf_valid <= 1'b0;
                    ms       <= M_GO;
                end
            default:                                        // M_GO
                if (start) begin
                    ms      <= M_IDLE;
                    r_track <= go_track;
                    r_t0    <= now_us;
                    cnext   <= nx_next;
                    if (nfirst) begin
                        pv       <= 1'b0;
                        ce       <= go_entry;
                        cn       <= dt_cnt;
                        cleft    <= dt_cnt - 11'd1;
                        r_bn     <= dt_cnt;
                        ev_batch <= 1'b1;
                    end else begin
                        cleft <= cleft - 11'd1;
                        r_bn  <= cn;
                    end
                end
            endcase

            if (done) begin
                cp_valid <= 1'b1;
                cp_data  <= {r_track, r_t0, now_us, r_bn, out_mem0, out_mem1, sat16, r_track >= N_ON_CHIP};
            end
        end
    end

    assign idle = (qs == Q_IDLE) && !pv && (ms == M_IDLE) && !have_cur && (q_total == 11'd0);

endmodule
