// compute_array.v — 추론 1개(40→384→256→64→2)를 처리하는 64 lane 연산부
//
// 03_ARCHITECTURE.md §4. 64 lane output-stationary, lane j = 출력 그룹의 뉴런 64g + j.
//   layer 1  그룹 6개 × input 40개, cycle마다 word 1개
//   layer 2  그룹 4개, spike가 1인 layer 1 뉴런만 cycle마다 2개(port A·B + pre-adder)
//   layer 3  그룹 1개, spike가 1인 layer 2 뉴런만 cycle마다 2개
//   layer 4  word 2개, lane j가 W4[k][j]·s3[j]를 만들고 adder tree로 더한다
// 그룹 누산이 끝나면 shadow register에 잡고 plif_array가 4 cycle(row 4개)에 갱신한다.
// 그동안 다음 그룹을 누산한다. layer 경계에서는 앞 layer의 PLIF가 끝날 때까지 기다린다.
// spike 0 건너뛰기 그룹은 최소 4 cycle로 채운다(shadow를 비우기 전에 덮지 않도록). 빈 cycle은 b = 0.
//
// 단계 (cycle 번호 = 명령이 그 단계 register에 있는 cycle)
//   0      명령 register (FSM)
//   1      목록 읽기 결과, word 주소 → entry
//   3      entry 출력(latency 2) → mac_unit 입력
//   6      누산 enable·clear (mac_unit M 단계)
//   7      누산 결과 → shadow 또는 layer 4 adder tree
//   P0~P4  row마다 membrane potential·params 읽기(P0) → plif_array(P2, latency 2) → 쓰기(P4)
//
// membrane potential row r = 뉴런 16r~16r+15. layer 1 row 0~23, layer 2 24~39, layer 3 40~43,
// layer 4 44(lane 0·1만 유효). 읽기 latency 2. 저장 bit 줄이기는 membrane_bank 몫이다.

module compute_array #(
    parameter CUR_W = 17,          // 전류 |최대| 49,152 (layer 2)
    parameter ACC_W = 21
)(
    input  wire                 clk,
    input  wire                 rst,
    // 추론
    input  wire                 start,          // busy가 0일 때만 받는다
    input  wire                 reset_state,    // RESET_STATE
    input  wire [319:0]         x_in,           // mel 40개, byte i = input i
    output wire                 busy,
    output reg                  done,           // 1 cycle, out_mem 유효
    output reg                  sat16,          // 이번 추론에서 16 bit 포화가 났다(done 때 유효, row 44는 lane 0·1만)
    output reg  [15:0]          out_mem0,
    output reg  [15:0]          out_mem1,
    // weight entry
    output wire                 w_en,
    output wire [10:0]          w_a_addr,
    output wire [10:0]          w_b_addr,
    input  wire [511:0]         w_a_data,
    input  wire [511:0]         w_b_data,
    output wire [5:0]           p_addr,
    input  wire [255:0]         p_data,
    // membrane potential
    output wire                 m_rd_en,
    output wire [5:0]           m_rd_row,
    input  wire [255:0]         m_rd_data,
    output wire                 m_wr_en,
    output wire [5:0]           m_wr_row,
    output wire [255:0]         m_wr_data,
    // golden 대조용 (m_wr_en과 같은 cycle)
    output reg  [16*CUR_W-1:0]  dbg_cur,
    output wire [255:0]         dbg_mem_sat,
    output wire [15:0]          dbg_spk
);

    localparam [1:0] L1 = 2'd0, L2 = 2'd1, L3 = 2'd2, L4 = 2'd3;
    localparam W_LAT = 2;
    localparam K_MAC = 1 + W_LAT;   // mac_unit 입력 단계
    localparam K_ACC = K_MAC + 3;   // 누산 단계
    localparam K_CAP = K_MAC + 4;   // 누산 결과 단계

    localparam [2:0] S_IDLE = 3'd0, S_L1 = 3'd1, S_L2 = 3'd2, S_L3 = 3'd3, S_L4 = 3'd4, S_WAIT = 3'd5;

    // ---------------- 명령 생성 (단계 0) ----------------
    reg  [2:0]   state;
    reg  [1:0]   layer;              // 지금 내거나 기다리는 layer
    reg  [2:0]   grp;
    reg  [8:0]   cnt;
    reg  [8:0]   len;
    reg  [319:0] in_buf;
    reg          rst_q;

    reg          op_v, op_first, op_last, op_bv, op_pad;
    reg  [1:0]   op_layer;
    reg  [2:0]   op_grp;
    reg  [9:0]   op_pos;
    reg  [10:0]  op_base;

    wire [9:0]   n1, n2;             // layer 1·2 spike 수
    wire         empty;

    wire [9:0]   pos2 = {cnt, 1'b0};
    wire [9:0]   n_now = (state == S_L2) ? n1 : n2;
    wire         g_last = (cnt == len - 9'd1);
    wire [9:0]   len1 = (n1 + 10'd1) >> 1;   // ⌈n/2⌉ ≤ 192
    wire [9:0]   len2 = (n2 + 10'd1) >> 1;

    assign busy = (state != S_IDLE);

    always @(posedge clk) begin
        if (rst) begin
            state <= S_IDLE;
            op_v  <= 1'b0;
        end else begin
            op_v <= 1'b0;
            case (state)
            S_IDLE:
                if (start) begin
                    in_buf <= x_in;
                    rst_q  <= reset_state;
                    grp    <= 3'd0;
                    cnt    <= 9'd0;
                    state  <= S_L1;
                end
            S_L1: begin
                op_v     <= 1'b1;
                op_layer <= L1;
                op_grp   <= grp;
                op_pos   <= {1'b0, cnt};
                op_first <= (cnt == 9'd0);
                op_last  <= (cnt == 9'd39);
                op_bv    <= 1'b0;
                op_pad   <= 1'b0;
                op_base  <= 11'd40 * grp;
                if (cnt == 9'd39) begin
                    cnt <= 9'd0;
                    grp <= grp + 3'd1;
                    if (grp == 3'd5) begin
                        layer <= L1;
                        state <= S_WAIT;
                    end
                end else
                    cnt <= cnt + 9'd1;
            end
            S_L2, S_L3: begin
                op_v     <= 1'b1;
                op_layer <= (state == S_L2) ? L2 : L3;
                op_grp   <= grp;
                op_pos   <= pos2;
                op_first <= (cnt == 9'd0);
                op_last  <= g_last;
                op_bv    <= (pos2 + 10'd1 < n_now);
                op_pad   <= (pos2 >= n_now);
                op_base  <= (state == S_L2) ? 11'd240 + 11'd384 * grp : 11'd1776;
                if (g_last) begin
                    cnt <= 9'd0;
                    grp <= grp + 3'd1;
                    if (state == S_L3 || grp == 3'd3) begin
                        layer <= (state == S_L2) ? L2 : L3;
                        state <= S_WAIT;
                    end
                end else
                    cnt <= cnt + 9'd1;
            end
            S_L4: begin
                op_v     <= 1'b1;
                op_layer <= L4;
                op_grp   <= cnt[2:0];
                op_pos   <= 10'd0;
                op_first <= 1'b1;
                op_last  <= 1'b1;
                op_bv    <= 1'b0;
                op_pad   <= 1'b0;
                op_base  <= 11'd2032 + {10'd0, cnt[0]};
                if (cnt[0]) begin
                    layer <= L4;
                    state <= S_WAIT;
                end
                cnt <= cnt + 9'd1;
            end
            S_WAIT:
                if (empty) begin
                    grp <= 3'd0;
                    cnt <= 9'd0;
                    case (layer)
                    L1: begin len <= (len1 < 10'd4) ? 9'd4 : len1[8:0]; state <= S_L2; end
                    L2: begin len <= (len2 < 10'd4) ? 9'd4 : len2[8:0]; state <= S_L3; end
                    L3: state <= S_L4;
                    default: state <= S_IDLE;
                    endcase
                end
            default: state <= S_IDLE;
            endcase
        end
    end

    // ---------------- spike 목록 ----------------
    wire        list_clr = (state == S_IDLE) && start;
    wire [8:0]  l1_idx0, l1_idx1;
    wire [7:0]  l2_idx0, l2_idx1;

    reg         pl_v;
    reg  [1:0]  pl_layer;
    reg  [5:0]  pl_row;
    wire [15:0] pl_spk;

    spike_list #(.DEPTH(24), .IW(9)) u_list1 (
        .clk(clk), .clr(list_clr),
        .wr_en(pl_v && pl_layer == L1), .wr_row(pl_row[4:0]), .wr_spk(pl_spk),
        .rd_pos(op_pos), .rd_idx0(l1_idx0), .rd_idx1(l1_idx1), .count(n1)
    );
    wire [5:0] l2_row = pl_row - 6'd24;
    spike_list #(.DEPTH(16), .IW(8)) u_list2 (
        .clk(clk), .clr(list_clr),
        .wr_en(pl_v && pl_layer == L2), .wr_row(l2_row[3:0]), .wr_spk(pl_spk),
        .rd_pos(op_pos[8:0]), .rd_idx0(l2_idx0), .rd_idx1(l2_idx1), .count(n2[8:0])
    );
    assign n2[9] = 1'b0;

    // ---------------- 단계 1~K_CAP 제어 ----------------
    reg         c_v     [1:K_CAP];
    reg         c_first [1:K_CAP];
    reg         c_last  [1:K_CAP];
    reg         c_bv    [1:K_CAP];
    reg         c_pad   [1:K_CAP];
    reg  [1:0]  c_layer [1:K_CAP];
    reg  [2:0]  c_grp   [1:K_CAP];
    reg  [7:0]  c_x     [1:K_CAP];
    reg  [9:0]  s1_pos;
    reg  [10:0] s1_base;

    integer i;
    always @(posedge clk) begin
        c_v[1]     <= rst ? 1'b0 : op_v;
        c_first[1] <= op_first;
        c_last[1]  <= op_last;
        c_bv[1]    <= op_bv;
        c_pad[1]   <= op_pad;
        c_layer[1] <= op_layer;
        c_grp[1]   <= op_grp;
        c_x[1]     <= in_buf[8*op_pos[5:0] +: 8];
        s1_pos     <= op_pos;
        s1_base    <= op_base;
        for (i = 2; i <= K_CAP; i = i + 1) begin
            c_v[i]     <= rst ? 1'b0 : c_v[i-1];
            c_first[i] <= c_first[i-1];
            c_last[i]  <= c_last[i-1];
            c_bv[i]    <= c_bv[i-1];
            c_pad[i]   <= c_pad[i-1];
            c_layer[i] <= c_layer[i-1];
            c_grp[i]   <= c_grp[i-1];
            c_x[i]     <= c_x[i-1];
        end
    end

    // 단계 1: word 주소. 빈 cycle은 그룹 첫 word를 읽는다(b = 0이라 값은 버려진다).
    reg [8:0] idx_a, idx_b;
    always @* begin
        case (c_layer[1])
        L1:      begin idx_a = s1_pos[8:0]; idx_b = 9'd0; end
        L2:      begin idx_a = l1_idx0;     idx_b = l1_idx1; end
        L3:      begin idx_a = {1'b0, l2_idx0}; idx_b = {1'b0, l2_idx1}; end
        default: begin idx_a = 9'd0;        idx_b = 9'd0; end
        endcase
        if (c_pad[1]) idx_a = 9'd0;
        if (!c_bv[1]) idx_b = 9'd0;
    end
    assign w_en     = c_v[1];
    assign w_a_addr = s1_base + {2'd0, idx_a};
    assign w_b_addr = s1_base + {2'd0, idx_b};

    // ---------------- 64 lane ----------------
    reg  [63:0]          s3;                     // layer 3 spike
    wire                 cap = c_v[K_CAP] && c_last[K_CAP] && c_layer[K_CAP] != L4;
    wire                 l1_cap = (c_layer[K_CAP] == L1);
    wire [6:0]           b_hi = (c_layer[K_MAC] == L1) ? c_x[K_MAC][7:1] : 7'd0;
    wire [64*10-1:0]     p_low;
    wire [64*CUR_W-1:0]  shadow;

    reg                  t3_v;
    reg                  t3_k;
    reg  signed [14:0]   t3;

    genvar j;
    generate
        for (j = 0; j < 64; j = j + 1) begin : g_lane
            reg b0;
            always @* begin
                case (c_layer[K_MAC])
                L1:      b0 = c_x[K_MAC][0];
                L4:      b0 = s3[j];
                default: b0 = !c_pad[K_MAC];
                endcase
            end

            wire signed [ACC_W-1:0] p;
            mac_unit #(.ACC_W(ACC_W)) u_mac (
                .clk(clk),
                .a(w_a_data[8*j +: 8]), .d(w_b_data[8*j +: 8]), .d_en(c_bv[K_MAC]),
                .b({b_hi, b0}),
                .acc_en(c_v[K_ACC]), .acc_clr(c_first[K_ACC]),
                .p(p)
            );
            assign p_low[10*j +: 10] = {{2{p[7]}}, p[7:0]};   // layer 4: W4·s3 ∈ [−128, 127]

            wire signed [ACC_W-1:0] p_sh = p >>> 7;   // layer 1 전류
            reg  [CUR_W-1:0] sh;
            always @(posedge clk) begin
                if (cap)
                    sh <= l1_cap ? p_sh[CUR_W-1:0] : p[CUR_W-1:0];
                else if (j < 2 && t3_v && t3_k == (j == 1))
                    sh <= {{(CUR_W-15){t3[14]}}, t3};
            end
            assign shadow[CUR_W*j +: CUR_W] = sh;
        end
    endgenerate

    // layer 4 adder tree: 64 → 16 → 4 → 1, 단계마다 register
    reg                t1_v, t2_v, t1_k, t2_k;
    reg signed [9:0]   t1 [0:15];
    reg signed [11:0]  t2 [0:3];
    always @(posedge clk) begin
        t1_v <= rst ? 1'b0 : (c_v[K_CAP] && c_layer[K_CAP] == L4);
        t2_v <= rst ? 1'b0 : t1_v;
        t3_v <= rst ? 1'b0 : t2_v;
        t1_k <= c_grp[K_CAP][0];
        t2_k <= t1_k;
        t3_k <= t2_k;
        for (i = 0; i < 16; i = i + 1)
            t1[i] <= $signed(p_low[40*i +: 10]) + $signed(p_low[40*i+10 +: 10])
                   + $signed(p_low[40*i+20 +: 10]) + $signed(p_low[40*i+30 +: 10]);
        for (i = 0; i < 4; i = i + 1)
            t2[i] <= {{2{t1[4*i][9]}}, t1[4*i]} + {{2{t1[4*i+1][9]}}, t1[4*i+1]}
                   + {{2{t1[4*i+2][9]}}, t1[4*i+2]} + {{2{t1[4*i+3][9]}}, t1[4*i+3]};
        // 부호 확장을 함수로 하면 xsim 2026.1이 accel_sys 안에서 X를 낸다(P4.10)
        t3 <= {{3{t2[0][11]}}, t2[0]} + {{3{t2[1][11]}}, t2[1]} + {{3{t2[2][11]}}, t2[2]} + {{3{t2[3][11]}}, t2[3]};
    end

    // ---------------- PLIF: row 묶음 ----------------
    reg  [2:0]  bu_left;
    reg  [5:0]  bu_row;
    reg  [1:0]  bu_r;
    reg  [1:0]  bu_layer;
    wire [5:0]  cap_row = (c_layer[K_CAP] == L1) ? {1'b0, c_grp[K_CAP], 2'b00} :
                          (c_layer[K_CAP] == L2) ? 6'd24 + {1'b0, c_grp[K_CAP], 2'b00} : 6'd40;
    always @(posedge clk) begin
        if (rst)
            bu_left <= 3'd0;
        else if (cap) begin
            bu_left  <= 3'd4;
            bu_row   <= cap_row;
            bu_r     <= 2'd0;
            bu_layer <= c_layer[K_CAP];
        end else if (t3_v && t3_k) begin
            bu_left  <= 3'd1;
            bu_row   <= 6'd44;
            bu_r     <= 2'd0;
            bu_layer <= L4;
        end else if (bu_left != 3'd0) begin
            bu_left <= bu_left - 3'd1;
            bu_row  <= bu_row + 6'd1;
            bu_r    <= bu_r + 2'd1;
        end
    end

    // P0: 읽기 주소
    assign m_rd_en  = (bu_left != 3'd0);
    assign m_rd_row = bu_row;
    assign p_addr   = bu_row;

    reg                 q1_v, q2_v;
    reg  [1:0]          q1_layer, q2_layer;
    reg  [5:0]          q1_row, q2_row;
    reg  [16*CUR_W-1:0] q1_cur, q2_cur;
    reg  [255:0]        q2_par;
    reg                 q3_v;
    reg  [1:0]          q3_layer;
    reg  [5:0]          q3_row;
    reg  [16*CUR_W-1:0] q3_cur;
    always @(posedge clk) begin
        q1_v     <= rst ? 1'b0 : m_rd_en;
        q1_layer <= bu_layer;
        q1_row   <= bu_row;
        q1_cur   <= shadow[16*CUR_W*bu_r +: 16*CUR_W];
        q2_v     <= rst ? 1'b0 : q1_v;
        q2_layer <= q1_layer;
        q2_row   <= q1_row;
        q2_cur   <= q1_cur;
        q2_par   <= p_data;           // P1
        q3_v     <= rst ? 1'b0 : q2_v;
        q3_layer <= q2_layer;
        q3_row   <= q2_row;
        q3_cur   <= q2_cur;
        pl_v     <= rst ? 1'b0 : q3_v;
        pl_layer <= q3_layer;
        pl_row   <= q3_row;
        dbg_cur  <= q3_cur;
    end

    // P2: plif_array 입력, P4: 결과
    wire [255:0] pl_mem_out;
    wire [15:0]  pl_sat;
    plif_array #(.CUR_W(CUR_W)) u_plif (
        .clk(clk), .cur(q2_cur), .mem_in(rst_q ? 256'd0 : m_rd_data), .params(q2_par),
        .spk(pl_spk), .mem_sat(dbg_mem_sat), .mem_out(pl_mem_out), .sat(pl_sat)
    );
    assign dbg_spk   = pl_spk;
    assign m_wr_en   = pl_v;
    assign m_wr_row  = pl_row;
    assign m_wr_data = pl_mem_out;

    always @(posedge clk) begin
        if (pl_v && pl_layer == L3)
            s3[16*(pl_row - 6'd40) +: 16] <= pl_spk;
        if (pl_v && pl_layer == L4) begin
            out_mem0 <= pl_mem_out[15:0];
            out_mem1 <= pl_mem_out[31:16];
        end
        done <= rst ? 1'b0 : (pl_v && pl_layer == L4);
        if (list_clr)
            sat16 <= 1'b0;
        else if (pl_v && |(pl_sat & ((pl_row == 6'd44) ? 16'h0003 : 16'hFFFF)))
            sat16 <= 1'b1;
    end

    // ---------------- 비었는지 ----------------
    reg pipe_v;
    always @* begin
        pipe_v = op_v | t1_v | t2_v | t3_v | (bu_left != 3'd0) | q1_v | q2_v | q3_v | pl_v;
        for (i = 1; i <= K_CAP; i = i + 1)
            pipe_v = pipe_v | c_v[i];
    end
    assign empty = !pipe_v;

endmodule
