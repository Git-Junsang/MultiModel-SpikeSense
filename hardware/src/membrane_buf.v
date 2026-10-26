// membrane_buf.v — DDR3 트랙 membrane potential의 준비·연산·되쓰기 buffer (2개)
//
// 한 buffer = 트랙 하나의 row 45개(12 bit). 상태: FREE → FILL(DDR3 읽기) → READY → BUSY(연산) → DRAIN(되쓰기) → FREE.
// 한 buffer로 연산하는 동안 다른 buffer에 다음 트랙을 읽거나 앞 트랙을 되쓴다. RESET_STATE면 읽지 않고 바로 READY.
//
// DDR3 배치: 뉴런 n의 12 bit가 bit [12n+11:12n] (little-endian 이어 붙임). 트랙 주소 = state_base + track × 0x800.
// row 4개(그룹 g) = 768 bit = 32 B beat 3개. 트랙 하나 = beat 34개(1,088 B, 앞 1,059 B가 유효).
// buffer는 그룹 12개 × 64 bit chunk 12개로 둔다. row slot s = chunk 3s~3s+2, beat k = chunk 4k~4k+3.
//
// 같은 트랙의 다음 추론 요청은 되쓰기 응답 뒤에만 오므로(req_table, 03_ARCHITECTURE.md §3) DDR3 읽기가 앞 쓰기를 앞지르지 않는다.
// compute 읽기 지연 2. DMA 쪽은 valid/ready handshake 뒤 beat 34개를 순서대로 주고받는다.

module membrane_buf (
    input  wire         clk,
    input  wire         rst,
    input  wire [31:0]  state_base,
    // 준비
    input  wire         pf_valid,
    input  wire [9:0]   pf_track,
    input  wire         pf_reset,
    output wire         pf_ready,
    // 연산
    input  wire [9:0]   q_track,
    output wire         can_start,      // q_track이 READY
    input  wire         c_start,        // q_track 연산 시작
    input  wire         c_done,         // 연산 끝 → 되쓰기
    input  wire [5:0]   c_rd_row,
    output reg  [191:0] c_rd_data,
    input  wire         c_wr_en,
    input  wire [5:0]   c_wr_row,
    input  wire [191:0] c_wr_data,
    // DMA 읽기
    output reg          dr_req_valid,
    input  wire         dr_req_ready,
    output reg  [31:0]  dr_req_addr,
    input  wire         dr_valid,
    input  wire [255:0] dr_data,
    // DMA 쓰기
    output reg          dw_req_valid,
    input  wire         dw_req_ready,
    output reg  [31:0]  dw_req_addr,
    output wire         dw_valid,
    input  wire         dw_ready,
    output wire [255:0] dw_data,
    input  wire         dw_resp,
    // 되쓰기 완료
    output reg          wb_done,
    output reg  [9:0]   wb_track
);

    localparam [2:0] FREE = 3'd0, FILL = 3'd1, READY = 3'd2, BUSY = 3'd3, DRAIN = 3'd4;

    reg  [2:0] st  [0:1];
    reg  [9:0] trk [0:1];

    // ---------------- 준비 (DDR3 → buffer) ----------------
    reg        f_act;                    // beat를 받는 중
    reg        f_idx;
    reg  [3:0] f_g;
    reg  [1:0] f_k;
    wire       f_busy = dr_req_valid | f_act;
    wire       free0 = (st[0] == FREE), free1 = (st[1] == FREE);
    assign pf_ready = (free0 | free1) & !f_busy;
    wire       pf_idx = !free0;
    wire       f_last = (f_g == 4'd11);  // 그룹 11은 row 44 하나, beat 1개

    // ---------------- 연산 ----------------
    wire       rdy0 = (st[0] == READY) && (trk[0] == q_track);
    wire       rdy1 = (st[1] == READY) && (trk[1] == q_track);
    assign can_start = rdy0 | rdy1;
    reg        c_idx;

    // ---------------- 되쓰기 (buffer → DDR3) ----------------
    reg        d_act, d_sent;
    reg        d_idx;
    reg  [3:0] d_g;
    reg  [1:0] d_k;
    wire       d_idle = !dw_req_valid & !d_act;
    wire       d_last = (d_g == 4'd11);
    assign dw_valid = d_act & !d_sent;

    always @(posedge clk) begin
        wb_done <= 1'b0;
        if (rst) begin
            st[0] <= FREE; st[1] <= FREE;
            dr_req_valid <= 1'b0; f_act <= 1'b0;
            dw_req_valid <= 1'b0; d_act <= 1'b0; d_sent <= 1'b0;
        end else begin
            // 준비 명령
            if (pf_valid && pf_ready) begin
                trk[pf_idx] <= pf_track;
                if (pf_reset)
                    st[pf_idx] <= READY;
                else begin
                    st[pf_idx]   <= FILL;
                    f_idx        <= pf_idx;
                    f_g          <= 4'd0;
                    f_k          <= 2'd0;
                    dr_req_valid <= 1'b1;
                    dr_req_addr  <= state_base + {11'd0, pf_track, 11'd0};
                end
            end
            if (dr_req_valid && dr_req_ready) begin
                dr_req_valid <= 1'b0;
                f_act        <= 1'b1;
            end
            if (f_act && dr_valid) begin
                if (f_last) begin
                    f_act      <= 1'b0;
                    st[f_idx]  <= READY;
                end else if (f_k == 2'd2) begin
                    f_k <= 2'd0;
                    f_g <= f_g + 4'd1;
                end else
                    f_k <= f_k + 2'd1;
            end

            // 연산 시작·끝
            if (c_start) begin
                c_idx      <= rdy1;
                st[rdy1]   <= BUSY;
            end
            if (c_done)
                st[c_idx] <= DRAIN;

            // 되쓰기: DRAIN인 buffer를 하나씩
            if (d_idle && (st[0] == DRAIN || st[1] == DRAIN)) begin
                d_idx        <= (st[0] != DRAIN);
                d_g          <= 4'd0;
                d_k          <= 2'd0;
                dw_req_valid <= 1'b1;
                dw_req_addr  <= state_base + {11'd0, trk[st[0] != DRAIN], 11'd0};
            end
            if (dw_req_valid && dw_req_ready) begin
                dw_req_valid <= 1'b0;
                d_act        <= 1'b1;
                d_sent       <= 1'b0;
            end
            if (dw_valid && dw_ready) begin
                if (d_last)
                    d_sent <= 1'b1;
                else if (d_k == 2'd2) begin
                    d_k <= 2'd0;
                    d_g <= d_g + 4'd1;
                end else
                    d_k <= d_k + 2'd1;
            end
            if (d_act && d_sent && dw_resp) begin
                d_act     <= 1'b0;
                st[d_idx] <= FREE;
                wb_done   <= 1'b1;
                wb_track  <= trk[d_idx];
            end
        end
    end

    // ---------------- buffer 기억 ----------------
    // buffer b, chunk c: 64 bit × 그룹 16칸(12칸 사용). 쓰기는 준비(beat) 또는 연산(row), 읽기는 연산 또는 되쓰기.
    wire [767:0] rd_grp [0:1];

    genvar b, c;
    generate
        for (b = 0; b < 2; b = b + 1) begin : g_buf
            wire       filling  = (st[b] == FILL) && f_act;
            wire       f_we     = filling && dr_valid;
            wire       c_we     = (st[b] == BUSY) && c_wr_en;
            wire [3:0] wa       = filling ? f_g : c_wr_row[5:2];
            wire [3:0] ra       = (st[b] == DRAIN) ? d_g : c_rd_row[5:2];
            for (c = 0; c < 12; c = c + 1) begin : g_chunk
                localparam integer BEAT = c / 4, SLOT = c / 3;   // 이 chunk가 속한 beat k, row slot s
                (* ram_style = "distributed" *) reg [63:0] m [0:15];
                wire we = (f_we && f_k == BEAT[1:0]) || (c_we && c_wr_row[1:0] == SLOT[1:0]);
                always @(posedge clk)
                    if (we)
                        m[wa] <= filling ? dr_data[64*(c%4) +: 64] : c_wr_data[64*(c%3) +: 64];
                assign rd_grp[b][64*c +: 64] = m[ra];
            end
        end
    endgenerate

    wire [767:0] c_grp = rd_grp[c_idx];
    wire [767:0] d_grp = rd_grp[d_idx];
    // 마지막 beat(row 44)의 위 64 bit는 쓰지 않는 chunk라 0으로 낸다
    assign dw_data = d_last ? {64'd0, d_grp[191:0]} : d_grp[256*d_k +: 256];

    reg [191:0] c_q;
    always @(posedge clk) begin
        c_q       <= c_grp[192*c_rd_row[1:0] +: 192];
        c_rd_data <= c_q;
    end

endmodule
