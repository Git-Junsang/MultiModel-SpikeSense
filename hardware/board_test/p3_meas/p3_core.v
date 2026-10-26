// ============================================================
// p3_core.v — P3 측정 설계의 register 블록 + DDR3 traffic 생성기
// ============================================================
// ui_clk(100 MHz) 도메인. AXI4-Lite 슬레이브(32 bit, 64 KiB)는 XDMA BAR0와
// JTAG-AXI가 SmartConnect를 거쳐 접근한다. 쓰기는 32 bit 전체만 지원한다.
//
// register 지도 (바이트 offset)
//   0x0000 R   ID = 0x4D4D5033 ("MMP3")
//   0x0004 R   VERSION
//   0x0008 R   STATUS  [0] init_calib_complete [1] user_lnk_up [2] tgen busy
//                      [3] tgen done [4] ddr_sel [5] narrow burst 감지(Host 경로)
//   0x000C RW  SCRATCH
//   0x0010 R   TS_LO   64 bit 자유 계수기(ui_clk, 10 ns) 하위. 읽을 때 상위를 TS_HI에 보관
//   0x0014 R   TS_HI   직전 TS_LO 읽기 시점의 상위
//   0x0018 W   MARK    쓰면 도착 시각을 MARK_TS에, 값을 MARK_VAL에 남긴다
//   0x001C R   MARK_TS_LO   0x0020 R MARK_TS_HI   0x0024 R MARK_VAL
//   0x0040 W   CTRL    [0] start  [1] abort  [2] narrow 플래그 지우기 (쓰기 펄스)
//   0x0044 RW  DDR_SEL 0 = traffic 생성기, 1 = Host(XDMA) — 둘 다 쉬고 있을 때만 바꾼다
//   0x0048 RW  OPMODE  [0] write [1] verify [3:2] addr_mode [4] pipelined
//   0x004C RW  BASE        0x0050 RW XFER_BEATS   0x0054 RW BURST_MAX
//   0x0058 RW  N_XFERS     0x005C RW MAX_OUTST    0x0060 RW STRIDE
//   0x0064 RW  SLOT_CNT    0x0068 RW SLOT_MASK    0x006C RW ADDR_MASK
//   0x0070 RW  WRAP        0x0074 RW seed         0x0078 RW GAP
//   0x007C RW  LOG_MASK
//   0x0100 R   CYCLES_LO/HI(0x0104)   0x0108 R BEATS_LO/HI(0x010C)
//   0x0110 R   XFERS
//   0x0114 R   LAT_MIN  0x0118 LAT_MAX  0x011C LAT_SUM_LO  0x0120 LAT_SUM_HI
//   0x0124 R   FST_MIN  0x0128 FST_MAX  0x012C FST_SUM_LO  0x0130 FST_SUM_HI
//   0x0134 R   ERR_CNT  0x0138 ERR_ADDR 0x013C PROTO_ERR
//   0x0140 R   AX_STALL 0x0144 W_STALL  0x0148 LOG_N
//   0x8000~    R   지연 기록: 항목 i = 0x8000 + 8i → [fst, lat] (각 32 bit)
// ============================================================
`timescale 1ns / 1ps

module p3_core #(
    parameter [31:0] VERSION = 32'h0001_0000,
    parameter integer LOG_AW = 11
)(
    input  wire         clk,
    input  wire         rst,
    // 상태 입력
    input  wire         calib_done,
    input  wire         lnk_up,         // 비동기 (내부에서 동기화)
    input  wire         narrow_seen,
    output reg          narrow_clr,
    output reg          ddr_sel,
    output wire         tg_busy,
    // AXI4-Lite 슬레이브
    input  wire [15:0]  s_awaddr,
    input  wire         s_awvalid,
    output reg          s_awready,
    input  wire [31:0]  s_wdata,
    input  wire         s_wvalid,
    output reg          s_wready,
    output wire [1:0]   s_bresp,
    output reg          s_bvalid,
    input  wire         s_bready,
    input  wire [15:0]  s_araddr,
    input  wire         s_arvalid,
    output reg          s_arready,
    output reg  [31:0]  s_rdata,
    output wire [1:0]   s_rresp,
    output reg          s_rvalid,
    input  wire         s_rready,
    // AXI4 마스터 → MIG (MUX 경유)
    output wire [29:0]  m_awaddr,
    output wire [7:0]   m_awlen,
    output wire         m_awvalid,
    input  wire         m_awready,
    output wire [255:0] m_wdata,
    output wire         m_wlast,
    output wire         m_wvalid,
    input  wire         m_wready,
    input  wire         m_bvalid,
    output wire         m_bready,
    input  wire [1:0]   m_bresp,
    output wire [29:0]  m_araddr,
    output wire [7:0]   m_arlen,
    output wire         m_arvalid,
    input  wire         m_arready,
    input  wire [255:0] m_rdata,
    input  wire         m_rlast,
    input  wire         m_rvalid,
    output wire         m_rready,
    input  wire [1:0]   m_rresp
);

    assign s_bresp = 2'b00;
    assign s_rresp = 2'b00;

    // ---------------- 시각 ----------------
    reg [63:0] ts;
    always @(posedge clk) begin
        if (rst) ts <= 64'd0;
        else     ts <= ts + 64'd1;
    end

    reg [1:0] lnk_s;
    always @(posedge clk) lnk_s <= {lnk_s[0], lnk_up};

    // ---------------- 설정 register ----------------
    reg [31:0] scratch;
    reg [63:0] mark_ts;
    reg [31:0] mark_val;
    reg [31:0] opmode, base, xfer_beats, burst_max, n_xfers, max_outst, stride;
    reg [31:0] slot_cnt, slot_mask, addr_mask, wrap, seed, gap, log_mask;
    reg        tg_start, tg_abort;

    // ---------------- Traffic 생성기 ----------------
    wire          tg_done;
    wire [63:0]   r_cycles, r_beats, r_delay_sum, r_fst_sum;
    wire [31:0]   r_xfers, r_delay_min, r_delay_max, r_fst_min, r_fst_max;
    wire [31:0]   r_err_cnt, r_proto_err, r_ax_stall, r_w_stall;
    wire [29:0]   r_err_addr;
    wire [LOG_AW:0] r_log_n;
    wire [63:0]   log_rdata;
    reg  [15:0]   rd_a;

    ddr_tgen #(.AW(30), .LOG_AW(LOG_AW)) u_tgen (
        .clk(clk), .rst(rst),
        .start(tg_start), .abort(tg_abort), .busy(tg_busy), .done(tg_done),
        .cfg_write(opmode[0]), .cfg_verify(opmode[1]), .cfg_amode(opmode[3:2]),
        .cfg_pipe(opmode[4]), .cfg_base(base[29:0]), .cfg_xfer_beats(xfer_beats[23:0]),
        .cfg_burst_max(burst_max[7:0]), .cfg_n_xfers(n_xfers), .cfg_max_outst(max_outst[4:0]),
        .cfg_stride(stride[29:0]), .cfg_slot_cnt(slot_cnt[7:0]), .cfg_slot_mask(slot_mask[7:0]),
        .cfg_addr_mask(addr_mask[24:0]), .cfg_wrap(wrap[29:0]), .cfg_seed(seed),
        .cfg_gap(gap[15:0]), .cfg_log_mask(log_mask),
        .r_cycles(r_cycles), .r_beats(r_beats), .r_xfers(r_xfers),
        .r_delay_min(r_delay_min), .r_delay_max(r_delay_max), .r_delay_sum(r_delay_sum),
        .r_fst_min(r_fst_min), .r_fst_max(r_fst_max), .r_fst_sum(r_fst_sum),
        .r_err_cnt(r_err_cnt), .r_err_addr(r_err_addr), .r_proto_err(r_proto_err),
        .r_ax_stall(r_ax_stall), .r_w_stall(r_w_stall), .r_log_n(r_log_n),
        .log_raddr(rd_a[LOG_AW+2:3]), .log_rdata(log_rdata),
        .m_awaddr(m_awaddr), .m_awlen(m_awlen), .m_awvalid(m_awvalid), .m_awready(m_awready),
        .m_wdata(m_wdata), .m_wlast(m_wlast), .m_wvalid(m_wvalid), .m_wready(m_wready),
        .m_bvalid(m_bvalid), .m_bready(m_bready), .m_bresp(m_bresp),
        .m_araddr(m_araddr), .m_arlen(m_arlen), .m_arvalid(m_arvalid), .m_arready(m_arready),
        .m_rdata(m_rdata), .m_rlast(m_rlast), .m_rvalid(m_rvalid), .m_rready(m_rready),
        .m_rresp(m_rresp)
    );

    // ---------------- AXI-Lite 쓰기 ----------------
    reg [1:0]  wph;
    reg [15:0] wr_a;
    reg [31:0] wr_d;
    always @(posedge clk) begin
        if (rst) begin
            wph        <= 2'd0;
            s_awready  <= 1'b0;
            s_wready   <= 1'b0;
            s_bvalid   <= 1'b0;
            tg_start   <= 1'b0;
            tg_abort   <= 1'b0;
            narrow_clr <= 1'b0;
            ddr_sel    <= 1'b0;
            scratch    <= 32'd0;
            opmode     <= 32'd0;
            base       <= 32'd0;
            xfer_beats <= 32'd128;
            burst_max  <= 32'd16;
            n_xfers    <= 32'd0;
            max_outst  <= 32'd4;
            stride     <= 32'h21000;
            slot_cnt   <= 32'd40;
            slot_mask  <= 32'd63;
            addr_mask  <= 32'h01FF_FFFF;
            wrap       <= 32'd0;
            seed       <= 32'h1234_5678;
            gap        <= 32'd0;
            log_mask   <= 32'd0;
        end else begin
            s_awready  <= 1'b0;
            s_wready   <= 1'b0;
            tg_start   <= 1'b0;
            tg_abort   <= 1'b0;
            narrow_clr <= 1'b0;
            case (wph)
            2'd0: if (s_awvalid && s_wvalid) begin
                      s_awready <= 1'b1;
                      s_wready  <= 1'b1;
                      wr_a      <= s_awaddr;
                      wr_d      <= s_wdata;
                      wph       <= 2'd1;
                  end
            2'd1: begin   // 핸드셰이크가 끝난 cycle 다음: 쓰기 수행
                      wph      <= 2'd2;
                      s_bvalid <= 1'b1;
                      case (wr_a[15:2])
                      14'h0003: scratch <= wr_d;
                      14'h0006: begin mark_ts <= ts; mark_val <= wr_d; end
                      14'h0010: begin tg_start <= wr_d[0]; tg_abort <= wr_d[1]; narrow_clr <= wr_d[2]; end
                      14'h0011: ddr_sel    <= wr_d[0];
                      14'h0012: opmode     <= wr_d;
                      14'h0013: base       <= wr_d;
                      14'h0014: xfer_beats <= wr_d;
                      14'h0015: burst_max  <= wr_d;
                      14'h0016: n_xfers    <= wr_d;
                      14'h0017: max_outst  <= wr_d;
                      14'h0018: stride     <= wr_d;
                      14'h0019: slot_cnt   <= wr_d;
                      14'h001A: slot_mask  <= wr_d;
                      14'h001B: addr_mask  <= wr_d;
                      14'h001C: wrap       <= wr_d;
                      14'h001D: seed       <= wr_d;
                      14'h001E: gap        <= wr_d;
                      14'h001F: log_mask   <= wr_d;
                      default: ;
                      endcase
                  end
            2'd2: if (s_bready) begin
                      s_bvalid <= 1'b0;
                      wph      <= 2'd0;
                  end
            default: wph <= 2'd0;
            endcase
        end
    end

    // ---------------- AXI-Lite 읽기 ----------------
    // 0: 대기 → arready 1 cycle → 1: 주소 보관 → 2: 기록 메모리 읽기 대기 → 3: 데이터 → 4: rvalid
    reg [2:0]  rph;
    reg [63:0] ts_cap;
    reg [31:0] ts_hi_sh;
    always @(posedge clk) begin
        if (rst) begin
            rph       <= 3'd0;
            s_arready <= 1'b0;
            s_rvalid  <= 1'b0;
        end else begin
            s_arready <= 1'b0;
            case (rph)
            3'd0: if (s_arvalid) begin
                      s_arready <= 1'b1;
                      rd_a      <= s_araddr;
                      ts_cap    <= ts;
                      rph       <= 3'd1;
                  end
            3'd1: rph <= 3'd2;
            3'd2: rph <= 3'd3;
            3'd3: begin
                      s_rvalid <= 1'b1;
                      rph      <= 3'd4;
                      if (rd_a[15]) begin
                          s_rdata <= rd_a[2] ? log_rdata[31:0] : log_rdata[63:32];
                      end else begin
                          case (rd_a[14:2])
                          13'h0000: s_rdata <= 32'h4D4D5033;
                          13'h0001: s_rdata <= VERSION;
                          13'h0002: s_rdata <= {26'd0, narrow_seen, ddr_sel, tg_done, tg_busy, lnk_s[1], calib_done};
                          13'h0003: s_rdata <= scratch;
                          13'h0004: begin s_rdata <= ts_cap[31:0]; ts_hi_sh <= ts_cap[63:32]; end
                          13'h0005: s_rdata <= ts_hi_sh;
                          13'h0007: s_rdata <= mark_ts[31:0];
                          13'h0008: s_rdata <= mark_ts[63:32];
                          13'h0009: s_rdata <= mark_val;
                          13'h0011: s_rdata <= {31'd0, ddr_sel};
                          13'h0012: s_rdata <= opmode;
                          13'h0013: s_rdata <= base;
                          13'h0014: s_rdata <= xfer_beats;
                          13'h0015: s_rdata <= burst_max;
                          13'h0016: s_rdata <= n_xfers;
                          13'h0017: s_rdata <= max_outst;
                          13'h0018: s_rdata <= stride;
                          13'h0019: s_rdata <= slot_cnt;
                          13'h001A: s_rdata <= slot_mask;
                          13'h001B: s_rdata <= addr_mask;
                          13'h001C: s_rdata <= wrap;
                          13'h001D: s_rdata <= seed;
                          13'h001E: s_rdata <= gap;
                          13'h001F: s_rdata <= log_mask;
                          13'h0040: s_rdata <= r_cycles[31:0];
                          13'h0041: s_rdata <= r_cycles[63:32];
                          13'h0042: s_rdata <= r_beats[31:0];
                          13'h0043: s_rdata <= r_beats[63:32];
                          13'h0044: s_rdata <= r_xfers;
                          13'h0045: s_rdata <= r_delay_min;
                          13'h0046: s_rdata <= r_delay_max;
                          13'h0047: s_rdata <= r_delay_sum[31:0];
                          13'h0048: s_rdata <= r_delay_sum[63:32];
                          13'h0049: s_rdata <= r_fst_min;
                          13'h004A: s_rdata <= r_fst_max;
                          13'h004B: s_rdata <= r_fst_sum[31:0];
                          13'h004C: s_rdata <= r_fst_sum[63:32];
                          13'h004D: s_rdata <= r_err_cnt;
                          13'h004E: s_rdata <= {2'd0, r_err_addr};
                          13'h004F: s_rdata <= r_proto_err;
                          13'h0050: s_rdata <= r_ax_stall;
                          13'h0051: s_rdata <= r_w_stall;
                          13'h0052: s_rdata <= {{(31-LOG_AW){1'b0}}, r_log_n};
                          default:  s_rdata <= 32'hDEADBEEF;
                          endcase
                      end
                  end
            3'd4: if (s_rready) begin
                      s_rvalid <= 1'b0;
                      rph      <= 3'd0;
                  end
            default: rph <= 3'd0;
            endcase
        end
    end

endmodule
