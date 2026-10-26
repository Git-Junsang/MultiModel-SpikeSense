// dma.v — DDR3 DMA: weight 적재(prefetch)와 DDR3 트랙 membrane potential 읽기·쓰기 (03_ARCHITECTURE.md §2, 04_MEMORY.md §3·§5)
//
// AXI4 master 256 bit 하나로 MIG에 붙는다. 우선순위는 membrane potential 읽기 > 쓰기 > weight 적재(04 §5).
//   - 읽기 주소 채널에는 membrane potential 읽기를 먼저 올린다.
//   - Membrane potential 쓰기가 기다리거나 진행 중이면 weight burst를 새로 내지 않는다.
//     MIG는 읽기 우선(RD_PRI_REG)이라 weight 읽기가 이어지면 쓰기가 밀린다.
// weight 적재: weight_cache가 ld_busy를 올리면 slot(model_base + ld_model × 256 KiB)의 앞 4,114 beat(131,648 B)를
//   WB beat burst로 읽는다. 동시에 W_OUT개까지 내보낸다(P3.1: 16 beat burst 4개면 순차 읽기 3.015 GB/s).
//   beat 0–45는 params row, 46부터는 beat 2개가 word 하나다(앞 beat = word bit [255:0], word 주소 = (beat − 46) / 2,
//   02_MODEL.md §6). 마지막 word를 쓰는 cycle에 ld_done을 준다.
// Membrane potential: membrane_buf의 전송 하나 = burst 하나(34 beat). 받는 쪽은 멈추지 않는다.
// 읽기 데이터는 ID로 나눈다(weight 0, membrane potential 1). ID가 다르면 slave가 순서를 바꾸거나 beat를 섞어도 된다.
// 쓰기 데이터는 주소 handshake 뒤에만 낸다. 오류 응답(SLVERR·DECERR)이면 err 1 cycle과 그 전송의 시작 주소
// (weight는 slot 주소)를 낸다. 같은 cycle에 두 오류가 나면 쓰기 쪽만 낸다.
// rst는 idle일 때만 준다. 나가 있는 burst가 있으면 그 응답을 다음 전송의 것으로 잘못 센다.

module dma #(
    parameter WB    = 16,       // weight burst beat 수. 2의 거듭제곱, 128 이하(4 KiB 경계를 넘지 않게)
    parameter W_OUT = 4,        // 동시에 나가 있는 weight burst 최대
    parameter OW    = $clog2(W_OUT + 1)
)(
    input  wire         clk,
    input  wire         rst,
    input  wire [31:0]  model_base,
    // weight 적재 (weight_cache)
    input  wire         ld_busy,
    input  wire [5:0]   ld_model,
    output reg          ld_done,
    output reg          wr_we,
    output reg  [10:0]  wr_addr,
    output reg  [511:0] wr_data,
    output reg          wr_pwe,
    output reg  [5:0]   wr_paddr,
    output reg  [255:0] wr_pdata,
    // Membrane potential (membrane_buf)
    input  wire         dr_req_valid,
    output wire         dr_req_ready,
    input  wire [31:0]  dr_req_addr,
    output wire         dr_valid,
    output wire [255:0] dr_data,
    input  wire         dw_req_valid,
    output wire         dw_req_ready,
    input  wire [31:0]  dw_req_addr,
    input  wire         dw_valid,
    output wire         dw_ready,
    input  wire [255:0] dw_data,
    output wire         dw_resp,
    // 상태
    output wire         idle,
    output reg          err,
    output reg  [31:0]  err_addr,
    // AXI4 master. size 32 B, INCR, wstrb 모두 1, awid 0은 밖에서 묶는다
    output reg  [31:0]  m_araddr,
    output reg  [7:0]   m_arlen,
    output reg          m_arid,
    output reg          m_arvalid,
    input  wire         m_arready,
    input  wire [255:0] m_rdata,
    input  wire         m_rid,
    input  wire [1:0]   m_rresp,
    input  wire         m_rlast,
    input  wire         m_rvalid,
    output wire         m_rready,
    output reg  [31:0]  m_awaddr,
    output wire [7:0]   m_awlen,
    output reg          m_awvalid,
    input  wire         m_awready,
    output wire [255:0] m_wdata,
    output wire         m_wlast,
    output wire         m_wvalid,
    input  wire         m_wready,
    input  wire [1:0]   m_bresp,
    input  wire         m_bvalid,
    output wire         m_bready
);

    localparam [12:0] LD_BEATS = 13'd4114;   // params 46 + weight 4,068 beat = 131,648 B
    localparam [12:0] P_BEATS  = 13'd46;
    localparam [7:0]  MS_LEN   = 8'd33;      // Membrane potential 34 beat

    // ---------------- 읽기 주소 ----------------
    reg           w_act;                     // 이번 적재를 맡음(ld_busy가 내려갈 때까지)
    reg  [12:0]   w_left;                    // 아직 내지 않은 beat
    reg  [31:0]   w_addr, w_base;
    reg  [OW-1:0] w_out;                     // 나가 있는 weight burst
    reg           mr_busy, mw_busy;          // membrane potential 읽기·쓰기가 나가 있음
    reg  [31:0]   mr_addr, mw_addr;

    wire       ar_free = !m_arvalid || m_arready;
    wire [7:0] w_len   = (w_left < WB) ? w_left[7:0] : WB[7:0];
    wire       mr_go   = dr_req_valid && ar_free;
    wire       w_go    = w_act && (w_left != 13'd0) && (w_out < W_OUT) && ar_free
                         && !dr_req_valid && !dw_req_valid && !mw_busy;
    assign dr_req_ready = mr_go;

    // ---------------- 읽기 데이터 (1단 register 뒤 나눔) ----------------
    reg         r_v, r_id, r_last;
    reg  [1:0]  r_resp;
    reg  [255:0] r_data;
    reg  [12:0] w_rcv;                       // 받은 weight beat
    reg  [255:0] lo;                         // word 앞 beat
    wire        w_beat = r_v && !r_id;
    wire [11:0] w_word = w_rcv[12:1] - 12'd23;   // (beat − 46) / 2

    assign m_rready = 1'b1;
    assign dr_valid = r_v && r_id;
    assign dr_data  = r_data;

    always @(posedge clk) begin
        r_v    <= !rst && m_rvalid;
        r_id   <= m_rid;
        r_last <= m_rlast;
        r_resp <= m_rresp;
        r_data <= m_rdata;
    end

    always @(posedge clk) begin
        wr_we   <= 1'b0;
        wr_pwe  <= 1'b0;
        ld_done <= 1'b0;
        if (rst) begin
            m_arvalid <= 1'b0;
            w_act     <= 1'b0;
            w_out     <= {OW{1'b0}};
            mr_busy   <= 1'b0;
        end else begin
            // 주소 register
            if (mr_go) begin
                m_arvalid <= 1'b1;
                m_araddr  <= dr_req_addr;
                m_arlen   <= MS_LEN;
                m_arid    <= 1'b1;
                mr_busy   <= 1'b1;
                mr_addr   <= dr_req_addr;
            end else if (w_go) begin
                m_arvalid <= 1'b1;
                m_araddr  <= w_addr;
                m_arlen   <= w_len - 8'd1;
                m_arid    <= 1'b0;
            end else if (m_arready)
                m_arvalid <= 1'b0;
            if (r_v && r_id && r_last)
                mr_busy <= 1'b0;

            // weight 적재
            if (!w_act && ld_busy) begin
                w_act  <= 1'b1;
                w_left <= LD_BEATS;
                w_rcv  <= 13'd0;
                w_addr <= model_base + {8'd0, ld_model, 18'd0};
                w_base <= model_base + {8'd0, ld_model, 18'd0};
            end else if (w_act && !ld_busy)
                w_act <= 1'b0;
            if (w_go) begin
                w_left <= w_left - {5'd0, w_len};
                w_addr <= w_addr + {19'd0, w_len, 5'd0};
            end
            w_out <= w_out + {{(OW-1){1'b0}}, w_go} - {{(OW-1){1'b0}}, w_beat && r_last};
            if (w_beat) begin
                w_rcv <= w_rcv + 13'd1;
                if (w_rcv < P_BEATS) begin
                    wr_pwe   <= 1'b1;
                    wr_paddr <= w_rcv[5:0];
                    wr_pdata <= r_data;
                end else if (!w_rcv[0])
                    lo <= r_data;
                else begin
                    wr_we   <= 1'b1;
                    wr_addr <= w_word[10:0];
                    wr_data <= {r_data, lo};
                end
                ld_done <= (w_rcv == LD_BEATS - 13'd1);
            end
        end
    end

    // ---------------- 쓰기 ----------------
    reg        w_open;                       // 주소 handshake 뒤 마지막 데이터 beat까지
    reg  [5:0] w_cnt;
    wire       mw_go = dw_req_valid && !mw_busy;

    assign dw_req_ready = mw_go;
    assign m_awlen  = MS_LEN;
    assign m_wvalid = dw_valid && w_open;
    assign dw_ready = m_wready && w_open;
    assign m_wdata  = dw_data;
    assign m_wlast  = (w_cnt == 6'd33);
    assign dw_resp  = m_bvalid;
    assign m_bready = 1'b1;

    always @(posedge clk) begin
        if (rst) begin
            m_awvalid <= 1'b0;
            mw_busy   <= 1'b0;
            w_open    <= 1'b0;
            w_cnt     <= 6'd0;
        end else begin
            if (mw_go) begin
                m_awvalid <= 1'b1;
                m_awaddr  <= dw_req_addr;
                mw_busy   <= 1'b1;
                mw_addr   <= dw_req_addr;
            end else if (m_awready)
                m_awvalid <= 1'b0;
            if (m_awvalid && m_awready)
                w_open <= 1'b1;
            if (m_wvalid && m_wready) begin
                w_cnt <= m_wlast ? 6'd0 : w_cnt + 6'd1;
                if (m_wlast) w_open <= 1'b0;
            end
            if (m_bvalid)
                mw_busy <= 1'b0;
        end
    end

    // ---------------- 오류·상태 ----------------
    always @(posedge clk) begin
        err <= !rst && ((m_bvalid && m_bresp[1]) || (r_v && r_resp[1]));
        if (m_bvalid && m_bresp[1])
            err_addr <= mw_addr;
        else if (r_v && r_resp[1])
            err_addr <= r_id ? mr_addr : w_base;
    end

    assign idle = !w_act && !mr_busy && !mw_busy && !dr_req_valid && !dw_req_valid;

endmodule
