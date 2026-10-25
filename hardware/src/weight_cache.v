// weight_cache.v — weight cache: entry E개, PNU-count 교체 (04_MEMORY.md §3)
//
// scheduler가 다음 batch의 모델을 pl_model로 알리면(지금 batch를 연산하는 동안):
//   hit   그 모델이 entry에 있다(적재 중 포함). 그 entry를 가장 최근으로 올린다
//   fill  빈 entry가 있으면 거기에 적재한다
//   evict 가장 최근 entry(지금 연산 중인 batch의 모델)를 뺀 entry를 오래된 순서로 predictor에 묻고,
//         {다음 사용까지 남은 시간, queue가 빔}이 가장 큰 entry를 내보낸다. 같으면 오래된 entry
// miss면 그 entry를 적재 중으로 두고 ld_entry·ld_model을 dma에 낸다. dma는 wr_*로 그 entry에 쓰고 ld_done을 준다.
// 적재가 끝날 때까지 다음 계획을 받지 않는다(pl_ready = 0). 그래서 적재 대상과 연산 중 entry는 victim 후보에 들지 않는다.
// compute_array는 cmp_entry의 entry를 읽는다(port 2개). engine.PNURTL·NextUse.plan과 같은 결정을 낸다.

module weight_cache #(
    parameter E        = 4,
    parameter N_MODELS = 40,
    parameter EW       = (E > 1) ? $clog2(E) : 1
)(
    input  wire                clk,
    input  wire                rst,
    // 시각, predictor 설정·도착·queue
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
    output reg                 pl_done,
    output reg  [EW-1:0]       pl_entry,
    output reg                 pl_hit,
    output reg                 pl_evict,
    output reg  [5:0]          pl_victim,
    // 적재
    output reg                 ld_busy,
    output reg  [EW-1:0]       ld_entry,
    output reg  [5:0]          ld_model,
    input  wire                ld_done,
    input  wire                wr_we,
    input  wire [10:0]         wr_addr,
    input  wire [511:0]        wr_data,
    input  wire                wr_pwe,
    input  wire [5:0]          wr_paddr,
    input  wire [255:0]        wr_pdata,
    // compute_array
    input  wire [EW-1:0]       cmp_entry,
    input  wire                w_en,
    input  wire [10:0]         w_a_addr,
    input  wire [10:0]         w_b_addr,
    output wire [511:0]        w_a_data,
    output wire [511:0]        w_b_data,
    input  wire [5:0]          p_addr,
    output wire [255:0]        p_data
);

    // ---------------- entry ----------------
    wire [511:0] a_d [0:E-1];
    wire [511:0] b_d [0:E-1];
    wire [255:0] p_d [0:E-1];

    genvar e;
    generate
        for (e = 0; e < E; e = e + 1) begin : g_entry
            wire mine = ld_busy && (ld_entry == e);
            wire rd   = w_en && (cmp_entry == e);
            weight_entry u_entry (
                .clk(clk),
                .a_en(rd), .a_addr(w_a_addr), .a_dout(a_d[e]),
                .b_en(rd || (mine && wr_we)), .b_we(mine && wr_we), .b_addr((mine && wr_we) ? wr_addr : w_b_addr),
                .b_din(wr_data), .b_dout(b_d[e]),
                .p_we(mine && wr_pwe), .p_waddr(wr_paddr), .p_din(wr_pdata),
                .p_raddr(p_addr), .p_dout(p_d[e])
            );
        end
    endgenerate

    assign w_a_data = a_d[cmp_entry];
    assign w_b_data = b_d[cmp_entry];
    assign p_data   = p_d[cmp_entry];

    // ---------------- 교체 ----------------
    reg  [E-1:0]  occ;                     // 모델이 있음(적재 중 포함)
    reg  [5:0]    tag  [0:E-1];
    reg  [EW-1:0] rank [0:E-1];           // 0 = 가장 최근, E−1 = 가장 오래됨

    reg           qy_valid;
    reg  [5:0]    qy_model;
    wire          qy_done;
    wire [31:0]   qy_delta;

    next_use_predictor #(.N_MODELS(N_MODELS)) u_pred (
        .clk(clk), .rst(rst),
        .now_us(now_us), .phase_us(phase_us), .epoch(epoch), .first_epoch(first_epoch),
        .cfg_we(cfg_we), .cfg_addr(cfg_addr), .cfg_data(cfg_data),
        .arr_valid(arr_valid), .arr_model(arr_model), .arr_t_host(arr_t_host), .arr_n_expect(arr_n_expect),
        .q_ne(q_ne), .qy_valid(qy_valid), .qy_model(qy_model), .qy_done(qy_done), .qy_delta(qy_delta)
    );

    localparam [1:0] S_IDLE = 2'd0, S_ASK = 2'd1, S_WAIT = 2'd2;
    reg  [1:0]    st;
    reg  [5:0]    m;
    reg  [EW-1:0] r;                      // 묻는 순위
    reg  [EW-1:0] cand, best;
    reg           best_v;
    reg  [32:0]   best_key;

    assign pl_ready = (st == S_IDLE) && !ld_busy;

    // 모델 x가 든 entry, 빈 entry, 순위 r인 entry
    reg           hit_v, emp_v;
    reg  [EW-1:0] hit_e, emp_e, at_r;
    integer i;
    always @* begin
        hit_v = 1'b0; hit_e = {EW{1'b0}};
        emp_v = 1'b0; emp_e = {EW{1'b0}};
        at_r  = {EW{1'b0}};
        for (i = E - 1; i >= 0; i = i - 1) begin
            if (occ[i] && tag[i] == pl_model) begin hit_v = 1'b1; hit_e = i[EW-1:0]; end
            if (!occ[i])                      begin emp_v = 1'b1; emp_e = i[EW-1:0]; end
            if (rank[i] == r)                 at_r = i[EW-1:0];
        end
    end

    // 가장 최근으로 올리기
    task automatic touch(input [EW-1:0] t);
        integer j;
        begin
            for (j = 0; j < E; j = j + 1)
                if (rank[j] < rank[t]) rank[j] <= rank[j] + 1'b1;
            rank[t] <= {EW{1'b0}};
        end
    endtask

    // 모델 mm을 entry t에 적재한다(ev = 내보냄)
    task automatic take(input [EW-1:0] t, input ev, input [5:0] mm);
        begin
            occ[t]    <= 1'b1;
            tag[t]    <= mm;
            ld_busy   <= 1'b1;
            ld_entry  <= t;
            ld_model  <= mm;
            pl_done   <= 1'b1;
            pl_entry  <= t;
            pl_hit    <= 1'b0;
            pl_evict  <= ev;
            pl_victim <= tag[t];
            touch(t);
        end
    endtask

    wire [32:0] key = {qy_delta, !q_ne[qy_model]};

    always @(posedge clk) begin
        pl_done  <= 1'b0;
        qy_valid <= 1'b0;
        if (rst) begin
            st      <= S_IDLE;
            occ     <= {E{1'b0}};
            ld_busy <= 1'b0;
            for (i = 0; i < E; i = i + 1) rank[i] <= i[EW-1:0];
        end else begin
            if (ld_done) ld_busy <= 1'b0;
            case (st)
            S_IDLE:
                if (pl_valid && pl_ready) begin
                    m <= pl_model;
                    if (hit_v) begin
                        pl_done  <= 1'b1;
                        pl_entry <= hit_e;
                        pl_hit   <= 1'b1;
                        pl_evict <= 1'b0;
                        touch(hit_e);
                    end else if (emp_v)
                        take(emp_e, 1'b0, pl_model);
                    else begin
                        r      <= E[EW-1:0] - 1'b1;
                        best_v <= 1'b0;
                        st     <= S_ASK;
                    end
                end
            S_ASK: begin                              // 순위 r(> 0)인 entry를 묻는다
                cand     <= at_r;
                qy_model <= tag[at_r];
                qy_valid <= 1'b1;
                st       <= S_WAIT;
            end
            default:                                  // S_WAIT
                if (qy_done) begin
                    if (!best_v || key > best_key) begin
                        best_v   <= 1'b1;
                        best     <= cand;
                        best_key <= key;
                    end
                    if (r == 1) begin
                        take((!best_v || key > best_key) ? cand : best, 1'b1, m);
                        st <= S_IDLE;
                    end else begin
                        r  <= r - 1'b1;
                        st <= S_ASK;
                    end
                end
            endcase
        end
    end

endmodule
