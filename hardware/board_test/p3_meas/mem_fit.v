// ============================================================
// mem_fit.v — P3.2·P3.4 BRAM 적합성(fit) 실험용 on-chip 메모리 골격
// ============================================================
// 기능 회로가 아니다. P3.4에서 정한 메모리 구성(포트·폭·깊이)을 실제 크기로
// 만들고, 두 포트를 모두 움직이게 해 합성·배치·배선 결과(BRAM 타일 수, 100 MHz
// 타이밍)를 보려는 것이다. 모든 메모리 출력은 XOR로 모아 sig로 내보내 최적화로
// 지워지지 않게 한다.
//
// 구성 (ui_clk 100 MHz, P3.4 문서의 구성안)
//   weight cache        N_ENT개 entry × 4,096 word × 256 bit (4,068 word 사용 = 130,176 B)
//                       쓰기 포트: DDR3 읽기 데이터(fill), 읽기 포트: 32레인 연산(1 word/cycle)
//   슬라이스 버퍼       SLICE_BUF=1이면 2 × 512 word × 256 bit (이중 버퍼, 16 KiB씩)
//   레인                32개, INT8 weight × 7 bit 입력 누산(layer 1 형태)
//   membrane potential  layer별 bank 16 bit: 512트랙 × 384 / 256 / 64 / 2 뉴런, 읽기-수정-쓰기
//   β·vth               BV_ALL40=1: 40모델 × 706뉴런 × 16 bit 상주, 0: entry별 1,024 × 16 bit
//   추론 요청 queue          512 × 512 bit (64 B/추론 요청). Q_BRAM=0이면 분산 RAM(LUTRAM)
//   트랙 메타           512 × 64 bit
// ============================================================
`timescale 1ns / 1ps

module mem_fit #(
    parameter integer N_ENT     = 4,
    parameter integer SLICE_BUF = 1,
    parameter integer BV_ALL40  = 1,
    parameter integer Q_BRAM    = 1
)(
    input  wire         clk,
    input  wire         rst,
    input  wire [255:0] fill_data,
    input  wire         fill_valid,
    output reg  [31:0]  sig
);
    localparam integer NB = N_ENT + SLICE_BUF;   // 쓰기 대상 수

    // ---------------- 쓰기(fill) 주소 ----------------
    reg [11:0] f_addr;
    reg [3:0]  f_tgt;
    always @(posedge clk) begin
        if (rst) begin
            f_addr <= 12'd0;
            f_tgt  <= 4'd0;
        end else if (fill_valid) begin
            f_addr <= f_addr + 12'd1;
            if (f_addr == 12'hFFF) f_tgt <= (f_tgt == NB - 1) ? 4'd0 : f_tgt + 4'd1;
        end
    end

    // ---------------- 읽기(연산) 주소 ----------------
    reg [11:0] c_addr;
    reg [3:0]  c_src;
    always @(posedge clk) begin
        if (rst) begin
            c_addr <= 12'd0;
            c_src  <= 4'd0;
        end else begin
            c_addr <= c_addr + 12'd1;
            if (c_addr == 12'hFFF) c_src <= (c_src == NB - 1) ? 4'd0 : c_src + 4'd1;
        end
    end

    // ---------------- weight cache entry ----------------
    wire [255:0] e_rd [0:NB-1];
    genvar e;
    generate
        for (e = 0; e < N_ENT; e = e + 1) begin : g_ent
            (* ram_style = "block" *) reg [255:0] wm [0:4095];
            reg [255:0] r0, r1;
            always @(posedge clk) begin
                if (fill_valid && f_tgt == e) wm[f_addr] <= fill_data;
                r0 <= wm[c_addr];
                r1 <= r0;
            end
            assign e_rd[e] = r1;
        end
        if (SLICE_BUF) begin : g_sb
            (* ram_style = "block" *) reg [255:0] sb [0:1023];
            reg [255:0] r0, r1;
            always @(posedge clk) begin
                if (fill_valid && f_tgt == N_ENT) sb[f_addr[9:0]] <= fill_data;
                r0 <= sb[c_addr[9:0]];
                r1 <= r0;
            end
            assign e_rd[N_ENT] = r1;
        end
    endgenerate

    reg [3:0]   c_src_d1, c_src_d2;
    reg [255:0] w_word;
    always @(posedge clk) begin
        c_src_d1 <= c_src;
        c_src_d2 <= c_src_d1;
        w_word   <= e_rd[c_src_d2];
    end

    // ---------------- 추론 요청 queue ----------------
    reg [255:0] fill_prev;
    reg [8:0]   q_wa, q_ra;
    reg [511:0] q_rd;
    always @(posedge clk) if (fill_valid) fill_prev <= fill_data;
    generate
        if (Q_BRAM) begin : g_qb
            (* ram_style = "block" *) reg [511:0] q [0:511];
            always @(posedge clk) begin
                if (fill_valid && f_addr[3:0] == 4'd0) q[q_wa] <= {fill_data, fill_prev};
                q_rd <= q[q_ra];
            end
        end else begin : g_qd
            (* ram_style = "distributed" *) reg [511:0] q [0:511];
            always @(posedge clk) begin
                if (fill_valid && f_addr[3:0] == 4'd0) q[q_wa] <= {fill_data, fill_prev};
                q_rd <= q[q_ra];
            end
        end
    endgenerate
    always @(posedge clk) begin
        if (rst) begin
            q_wa <= 9'd0;
            q_ra <= 9'd0;
        end else begin
            if (fill_valid && f_addr[3:0] == 4'd0) q_wa <= q_wa + 9'd1;
            if (c_addr[5:0] == 6'd0) q_ra <= q_ra + 9'd1;
        end
    end

    // ---------------- 32레인 ----------------
    reg  [5:0]  xi;
    reg  [6:0]  x;
    always @(posedge clk) begin
        xi <= (c_addr[5:0] >= 6'd40) ? c_addr[5:0] - 6'd40 : c_addr[5:0];
        x  <= q_rd[8*xi +: 7];
    end
    reg signed [23:0] acc [0:31];
    reg signed [23:0] shadow [0:31];
    wire grp_end = (c_addr[5:0] == 6'd39);
    integer k;
    always @(posedge clk) begin
        for (k = 0; k < 32; k = k + 1) begin
            if (grp_end) begin
                shadow[k] <= acc[k];
                acc[k]    <= 24'sd0;
            end else begin
                acc[k] <= acc[k] + $signed(w_word[8*k +: 8]) * $signed({1'b0, x});
            end
        end
    end

    // ---------------- β·vth ----------------
    localparam integer BV_D = BV_ALL40 ? 40 * 706 : 1024;
    localparam integer BV_N = BV_ALL40 ? 1 : NB;
    reg [14:0] bv_ra, bv_wa;
    reg [15:0] bv_rd;
    wire [15:0] bv_q [0:BV_N-1];
    genvar b;
    generate
        for (b = 0; b < BV_N; b = b + 1) begin : g_bv
            (* ram_style = "block" *) reg [15:0] bvm [0:BV_D-1];
            reg [15:0] r0;
            always @(posedge clk) begin
                if (fill_valid && f_addr[0] && (BV_ALL40 || f_tgt == b)) bvm[bv_wa] <= fill_data[15:0];
                r0 <= bvm[bv_ra];
            end
            assign bv_q[b] = r0;
        end
    endgenerate
    always @(posedge clk) begin
        if (rst) begin
            bv_ra <= 15'd0;
            bv_wa <= 15'd0;
        end else begin
            bv_ra <= (bv_ra == BV_D - 1) ? 15'd0 : bv_ra + 15'd1;
            if (fill_valid && f_addr[0]) bv_wa <= (bv_wa == BV_D - 1) ? 15'd0 : bv_wa + 15'd1;
        end
        bv_rd <= bv_q[c_src_d2 % BV_N];
    end

    // ---------------- membrane bank (읽기-수정-쓰기) ----------------
    // 1 뉴런/cycle. 읽기 주소 → 2 cycle 뒤 데이터 → 갱신 → 같은 주소에 쓰기.
    localparam integer D1 = 512 * 384, D2 = 512 * 256, D3 = 512 * 64, D4 = 512 * 2;
    wire [15:0] cur16 = shadow[c_addr[4:0]][15:0];
    wire [15:0] m_new [0:3];
    wire [15:0] m_old [0:3];
    mem_rmw #(.D(D1), .AW(18)) u_m1 (.clk(clk), .rst(rst), .cur(cur16), .bv(bv_rd), .old(m_old[0]), .nw(m_new[0]));
    mem_rmw #(.D(D2), .AW(17)) u_m2 (.clk(clk), .rst(rst), .cur(cur16), .bv(bv_rd), .old(m_old[1]), .nw(m_new[1]));
    mem_rmw #(.D(D3), .AW(15)) u_m3 (.clk(clk), .rst(rst), .cur(cur16), .bv(bv_rd), .old(m_old[2]), .nw(m_new[2]));
    mem_rmw #(.D(D4), .AW(10)) u_m4 (.clk(clk), .rst(rst), .cur(cur16), .bv(bv_rd), .old(m_old[3]), .nw(m_new[3]));

    // ---------------- 트랙 메타 ----------------
    (* ram_style = "block" *) reg [63:0] meta [0:511];
    reg [63:0] meta_rd;
    always @(posedge clk) begin
        if (grp_end) meta[q_ra] <= {shadow[0][23:0], shadow[1][23:0], m_new[0]};
        meta_rd <= meta[q_wa];
    end

    // ---------------- 관찰 출력 ----------------
    reg [31:0] x_acc, x_w, x_q;
    integer i;
    always @(posedge clk) begin
        x_acc = 32'd0;
        for (i = 0; i < 32; i = i + 1) x_acc = x_acc ^ {8'd0, shadow[i]};
        x_w = 32'd0;
        for (i = 0; i < 8; i = i + 1) x_w = x_w ^ w_word[32*i +: 32];
        x_q = 32'd0;
        for (i = 0; i < 16; i = i + 1) x_q = x_q ^ q_rd[32*i +: 32];
        sig <= x_acc ^ x_w ^ x_q ^ meta_rd[31:0] ^ meta_rd[63:32] ^ {bv_rd, m_old[0]} ^
               {m_old[1], m_old[2]} ^ {m_old[3], m_new[3]};
    end

endmodule

// ============================================================
// mem_rmw — membrane bank 하나: 깊이 D × 16 bit, 읽기-수정-쓰기 파이프라인
//   갱신식은 PLIF 형태(누설 β·mem>>8 + 전류, 16 bit 포화, threshold 이상이면 빼기)
// ============================================================
module mem_rmw #(
    parameter integer D  = 1024,
    parameter integer AW = 10
)(
    input  wire        clk,
    input  wire        rst,
    input  wire [15:0] cur,
    input  wire [15:0] bv,       // {β[7:0], vth[7:0]}
    output wire [15:0] old,
    output wire [15:0] nw
);
    (* ram_style = "block" *) reg [15:0] m [0:D-1];
    reg [AW-1:0] ra, a1, a2, a3;
    reg [15:0]   r0, r1;
    always @(posedge clk) begin
        if (rst) ra <= {AW{1'b0}};
        else     ra <= (ra == D - 1) ? {AW{1'b0}} : ra + 1'b1;
        a1 <= ra;
        a2 <= a1;
        a3 <= a2;
        r0 <= m[ra];
        r1 <= r0;
    end
    wire signed [24:0] leak = ($signed(r1) * $signed({1'b0, bv[15:8]})) >>> 8;
    wire signed [24:0] sum  = leak + $signed(cur);
    wire signed [15:0] sat  = (sum > 25'sd32767) ? 16'sh7FFF : (sum < -25'sd32768) ? 16'sh8000 : sum[15:0];
    wire        spk = (sat >= $signed({8'd0, bv[7:0]}));
    reg  [15:0] nreg;
    always @(posedge clk) begin
        nreg <= spk ? sat - {8'd0, bv[7:0]} : sat;
        m[a3] <= nreg;
    end
    assign old = r1;
    assign nw  = nreg;
endmodule
