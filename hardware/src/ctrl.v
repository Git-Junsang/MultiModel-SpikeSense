// ctrl.v — 제어 packet 처리: 주소 공간 읽기·쓰기 (06_HOST_INTERFACE.md §7, §7.6)
//
// 요청 {magic 0x5C, op(1 읽기, 2 쓰기), tag, addr, count, status, 데이터}를 cq_*로 받아 다 모은 뒤 실행하고 응답
// {같은 머리, status, (읽기 성공이면) 데이터}를 cr_*로 낸다. 요청 하나에 응답은 늘 하나다(eth_link가 이를 믿고 기다린다).
// 데이터는 1 KiB 버퍼에 모은다. 쓰기는 길이까지 맞아야 시작하므로 반만 쓰는 일이 없다. 읽기도 다 읽은 뒤 status를 정한다.
// status (먼저 맞는 것):
//   3  머리 12 B 미만, magic ≠ 0x5C, op ∉ {1, 2}, count ∉ 1–256, 길이 ≠ 12 + 4 × count(쓰기) 또는 12(읽기)
//   1  addr 4 B 정렬 아님, 끝 주소가 다른 블록(regs ↔ DDR3, DDR3 창 0x8000_0000–0xBFFF_FFFF 밖)으로 넘어감
//   2  DDR3 창이고 run = 1
//   1  DDR3 창이고 addr 32 B 정렬 아님
//   3  DDR3 창이고 count % 8 ≠ 0
//   1  실행 중 AXI 오류 응답(SLVERR·DECERR)
// addr < 0x8000_0000: AXI4-Lite로 word 하나씩 addr + 4i. 나가 있는 거래는 하나. run 검사는 regs 몫이다.
// DDR3 창: MIG 주소 = addr − 0x8000_0000. AXI4 burst(32 B beat, 4 KiB 경계에서 나눔)를 하나씩 낸다.
//   쓰기 데이터는 주소 handshake 뒤에만 낸다. 데이터는 word 순서대로 little-endian(beat byte k = 데이터[8k+7:8k]).
// run 입력은 DDR3 창 거부(status 2) 조건이다. ctrl은 DDR3 응답을 시간 제한 없이 기다리므로 top은 MIG 보정 전에도
//   거부하도록 run || !mig_calib를 넣는다.
// rst는 idle일 때만 준다. 나가 있는 거래가 있으면 그 응답을 다음 거래의 것으로 잘못 센다.

module ctrl (
    input  wire         clk,
    input  wire         rst,
    input  wire         run,
    // 제어 요청·응답 (eth_link)
    input  wire [7:0]   cq_tdata,
    input  wire         cq_tvalid,
    output wire         cq_tready,
    input  wire         cq_tlast,
    output wire [7:0]   cr_tdata,
    output wire         cr_tvalid,
    input  wire         cr_tready,
    output wire         cr_tlast,
    output wire [10:0]  cr_len,                        // 응답 payload B(eth_link가 UDP 머리에 먼저 쓴다)
    // AXI4-Lite master (regs)
    output reg  [31:0]  m_axil_awaddr,
    output reg          m_axil_awvalid,
    input  wire         m_axil_awready,
    output wire [31:0]  m_axil_wdata,
    output wire [3:0]   m_axil_wstrb,
    output reg          m_axil_wvalid,
    input  wire         m_axil_wready,
    input  wire [1:0]   m_axil_bresp,
    input  wire         m_axil_bvalid,
    output wire         m_axil_bready,
    output reg  [31:0]  m_axil_araddr,
    output reg          m_axil_arvalid,
    input  wire         m_axil_arready,
    input  wire [31:0]  m_axil_rdata,
    input  wire [1:0]   m_axil_rresp,
    input  wire         m_axil_rvalid,
    output wire         m_axil_rready,
    // DDR3 AXI4 master. size 32 B, INCR, wstrb 모두 1, ID 0은 밖에서 묶는다
    output reg  [31:0]  m_araddr,
    output reg  [7:0]   m_arlen,
    output reg          m_arvalid,
    input  wire         m_arready,
    input  wire [255:0] m_rdata,
    input  wire         m_rlast,
    input  wire [1:0]   m_rresp,
    input  wire         m_rvalid,
    output wire         m_rready,
    output reg  [31:0]  m_awaddr,
    output reg  [7:0]   m_awlen,
    output reg          m_awvalid,
    input  wire         m_awready,
    output wire [255:0] m_wdata,
    output reg          m_wlast,
    output wire         m_wvalid,
    input  wire         m_wready,
    input  wire [1:0]   m_bresp,
    input  wire         m_bvalid,
    output wire         m_bready
);

    localparam [3:0] S_RX = 4'd0, S_CHK = 4'd1, S_WA = 4'd2, S_WL = 4'd3, S_WD = 4'd4, S_WB = 4'd5,
                     S_RA = 4'd6, S_RD = 4'd7, S_RS = 4'd8, S_TX = 4'd9;

    reg  [3:0]   st;
    reg  [15:0]  n;                          // 받은 요청 byte
    reg  [95:0]  hdr;                        // 요청 byte 0–11
    reg  [1:0]   stat;
    reg  [10:0]  p;                          // 버퍼 byte 위치, S_TX에서는 응답 byte 위치
    reg  [4:0]   k;                          // word·beat 안 byte
    reg  [31:0]  a;                          // 다음 bus 주소
    reg  [5:0]   bl;                         // burst에 남은 beat
    reg          lst;                        // 받은 beat가 burst 끝
    reg  [255:0] sh;
    reg          wv;

    wire [7:0]  magic = hdr[7:0];
    wire [7:0]  op    = hdr[15:8];
    wire [31:0] addr  = hdr[63:32];
    wire [15:0] cnt   = hdr[79:64];
    wire        ddr   = addr[31];
    wire [10:0] tb    = {cnt[8:0], 2'b00};   // 데이터 byte 수(count ≤ 256일 때)
    wire [31:0] aend  = addr + {21'd0, tb} - 32'd1;
    wire [4:0]  ulast = ddr ? 5'd31 : 5'd3;

    // ---------------- 버퍼 (1 KiB, 비동기 읽기) ----------------
    reg  [7:0]  mem [0:1023];
    wire        rx_hs  = cq_tvalid && cq_tready;
    wire [15:0] rx_off = n - 16'd12;
    wire        mem_we = (st == S_RX) ? (rx_hs && n >= 16'd12 && n < 16'd1036) : (st == S_RS);
    wire [9:0]  mem_wa = (st == S_RX) ? rx_off[9:0] : p[9:0];
    wire [7:0]  mem_wd = (st == S_RX) ? cq_tdata : sh[7:0];
    wire [10:0] tx_off = p - 11'd12;
    wire [7:0]  mem_q  = mem[(st == S_TX) ? tx_off[9:0] : p[9:0]];
    always @(posedge clk)
        if (mem_we) mem[mem_wa] <= mem_wd;

    // ---------------- 검사 ----------------
    reg [1:0] chk;
    always @(*) begin
        if (n < 16'd12 || magic != 8'h5C || (op != 8'd1 && op != 8'd2) || cnt == 16'd0 || cnt > 16'd256
            || n != ((op == 8'd2) ? {5'd0, tb} + 16'd12 : 16'd12))
            chk = 2'd3;
        else if (addr[1:0] != 2'd0 || (ddr ? (addr[30] || aend[31:30] != 2'b10) : aend[31]))
            chk = 2'd1;
        else if (ddr && run)
            chk = 2'd2;
        else if (ddr && addr[4:0] != 5'd0)
            chk = 2'd1;
        else if (ddr && cnt[2:0] != 3'd0)
            chk = 2'd3;
        else
            chk = 2'd0;
    end

    // DDR3 burst 길이: 남은 beat와 4 KiB 경계까지 beat 중 작은 것
    wire [10:0] left = tb - p;
    wire [7:0]  rem  = {2'd0, left[10:5]};
    wire [7:0]  bnd  = 8'd128 - {1'b0, a[11:5]};
    wire [7:0]  blen = (rem < bnd) ? rem : bnd;

    // ---------------- 응답 ----------------
    wire [95:0] rhdr  = {14'd0, stat, hdr[79:0]};
    wire [10:0] rlen  = (op == 8'd1 && stat == 2'd0) ? tb + 11'd12 : 11'd12;
    assign cq_tready = (st == S_RX);
    assign cr_tvalid = (st == S_TX);
    assign cr_tdata  = (p < 11'd12) ? rhdr[{p[3:0], 3'b000} +: 8] : mem_q;
    assign cr_tlast  = (p == rlen - 11'd1);
    assign cr_len    = rlen;

    // ---------------- bus ----------------
    assign m_axil_wdata  = sh[255:224];
    assign m_axil_wstrb  = 4'hF;
    assign m_axil_bready = (st == S_WB) && !ddr;
    assign m_axil_rready = (st == S_RD) && !ddr;
    assign m_wdata  = sh;
    assign m_wvalid = wv && !m_awvalid;
    assign m_bready = (st == S_WB) && ddr;
    assign m_rready = (st == S_RD) && ddr;

    wire b_hs = (m_axil_bvalid && m_axil_bready) || (m_bvalid && m_bready);
    wire b_err = ddr ? m_bresp[1] : m_axil_bresp[1];

    always @(posedge clk) begin
        if (rst) begin
            st             <= S_RX;
            n              <= 16'd0;
            hdr            <= 96'd0;
            m_axil_awvalid <= 1'b0;
            m_axil_wvalid  <= 1'b0;
            m_axil_arvalid <= 1'b0;
            m_arvalid      <= 1'b0;
            m_awvalid      <= 1'b0;
            wv             <= 1'b0;
        end else begin
            if (m_axil_awready) m_axil_awvalid <= 1'b0;
            if (m_axil_wready)  m_axil_wvalid  <= 1'b0;
            if (m_axil_arready) m_axil_arvalid <= 1'b0;
            if (m_arready)      m_arvalid      <= 1'b0;
            if (m_awready)      m_awvalid      <= 1'b0;
            case (st)
            S_RX:
                if (rx_hs) begin
                    if (n != 16'hFFFF) n <= n + 16'd1;
                    if (n < 16'd12) hdr[{n[3:0], 3'b000} +: 8] <= cq_tdata;
                    if (cq_tlast) st <= S_CHK;
                end
            S_CHK: begin
                stat <= chk;
                p    <= 11'd0;
                k    <= 5'd0;
                a    <= ddr ? {2'b00, addr[29:0]} : addr;
                st   <= (chk != 2'd0) ? S_TX : (op == 8'd2) ? (ddr ? S_WA : S_WL) : S_RA;
            end
            // 쓰기
            S_WA: begin
                m_awvalid <= 1'b1;
                m_awaddr  <= a;
                m_awlen   <= blen - 8'd1;
                bl        <= blen[5:0];
                a         <= a + {19'd0, blen, 5'd0};
                st        <= S_WL;
            end
            S_WL: begin
                sh <= {mem_q, sh[255:8]};
                p  <= p + 11'd1;
                k  <= k + 5'd1;
                if (k == ulast) begin
                    k  <= 5'd0;
                    st <= S_WD;
                    if (ddr) begin
                        wv      <= 1'b1;
                        m_wlast <= (bl == 6'd1);
                    end else begin
                        m_axil_awvalid <= 1'b1;
                        m_axil_awaddr  <= a;
                        m_axil_wvalid  <= 1'b1;
                        a              <= a + 32'd4;
                    end
                end
            end
            S_WD:
                if (ddr) begin
                    if (m_wvalid && m_wready) begin
                        wv <= 1'b0;
                        bl <= bl - 6'd1;
                        st <= m_wlast ? S_WB : S_WL;
                    end
                end else if ((!m_axil_awvalid || m_axil_awready) && (!m_axil_wvalid || m_axil_wready))
                    st <= S_WB;
            S_WB:
                if (b_hs) begin
                    if (b_err) stat <= 2'd1;
                    if (p == tb) begin
                        p  <= 11'd0;
                        st <= S_TX;
                    end else
                        st <= ddr ? S_WA : S_WL;
                end
            // 읽기
            S_RA: begin
                if (ddr) begin
                    m_arvalid <= 1'b1;
                    m_araddr  <= a;
                    m_arlen   <= blen - 8'd1;
                    a         <= a + {19'd0, blen, 5'd0};
                end else begin
                    m_axil_arvalid <= 1'b1;
                    m_axil_araddr  <= a;
                    a              <= a + 32'd4;
                end
                st <= S_RD;
            end
            S_RD:
                if (ddr ? m_rvalid : m_axil_rvalid) begin
                    sh  <= ddr ? m_rdata : {224'd0, m_axil_rdata};
                    lst <= !ddr || m_rlast;
                    if (ddr ? m_rresp[1] : m_axil_rresp[1]) stat <= 2'd1;
                    st  <= S_RS;
                end
            S_RS: begin
                sh <= {8'd0, sh[255:8]};
                p  <= p + 11'd1;
                k  <= k + 5'd1;
                if (k == ulast) begin
                    k <= 5'd0;
                    if (!lst)
                        st <= S_RD;
                    else if (p + 11'd1 == tb) begin
                        p  <= 11'd0;
                        st <= S_TX;
                    end else
                        st <= S_RA;
                end
            end
            default:   // S_TX
                if (cr_tready) begin
                    p <= p + 11'd1;
                    if (cr_tlast) begin
                        st  <= S_RX;
                        n   <= 16'd0;
                        hdr <= 96'd0;
                    end
                end
            endcase
        end
    end

endmodule
