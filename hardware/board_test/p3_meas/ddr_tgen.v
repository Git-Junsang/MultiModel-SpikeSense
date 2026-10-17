// ============================================================
// ddr_tgen.v — P3.1 DDR3 실효 대역폭·지연 측정용 AXI4 트래픽 생성기
// ============================================================
// MIG AXI 슬레이브(256 bit, ui_clk 100 MHz)에 직접 붙는 마스터다.
// 한 번의 실행(start)은 "전송(transfer)" n개로 이루어진다. 전송 하나는
// 연속 주소 xfer_beats × 32 B이며, 4 KiB 경계와 burst_max에서 AXI 버스트로
// 잘라 보낸다. 전송은 weight 슬라이스 하나를 가져오는 DMA 요청에 해당한다.
//
// 주소 모드 (cfg_amode):
//   0 SEQ       전송 i의 시작 = base + (i × 전송 크기) mod wrap  (wrap=0이면 감지 안 함)
//   1 SLOT_RAND 시작 = base + slot × stride, slot은 [0, slot_cnt) 균등 난수
//               (LFSR & slot_mask가 slot_cnt 이상이면 다시 뽑는다) — 모델 전환
//   2 RAND_BEAT 시작 = base + (LFSR & addr_mask) × 32 B — 임의 주소 단일 지연
//   3 SLOT_RR   시작 = base + (i mod slot_cnt) × stride — 결정적 모델 순환
// 발행 방식 (cfg_pipe):
//   0 blocking  전송 하나가 끝나고 gap cycle이 지나야 다음 전송을 시작한다
//               (슬라이스를 하나씩 요청하는 단순 DMA). 전송 안의 버스트는
//               max_outst개까지 겹쳐 보낸다.
//   1 pipelined 전송 경계와 무관하게 max_outst개까지 버스트를 계속 보낸다.
//
// 지연 정의 (ui_clk cycle):
//   lat  = 전송의 첫 버스트를 AR/AW에 올린 cycle → 마지막 R beat(읽기) 또는
//          마지막 B 응답(쓰기)을 받은 cycle
//   fst  = 첫 버스트 → 첫 R beat (읽기만, 쓰기는 lat와 같게 기록)
// 결과: cycle 수, beat 수, 전송 수, lat·fst의 min/max/합, 검증 오류,
//       주소·W 채널 정체 cycle, 앞쪽 전송의 (fst, lat) 기록 2^LOG_AW개
//       (log_mask로 i & log_mask == 0인 전송만 기록해 표본 간격을 둘 수 있다)
//
// 데이터 패턴: 32 bit 워드 k(0..7)의 값 = {beat 주소[24:0], k, 4'b0101} ^ rotl(seed, 4k)
//   주소마다 달라 주소 별칭(aliasing)과 이전 실행의 잔존 데이터를 잡는다.
//   cfg_verify=1인 읽기는 매 beat를 이 패턴과 비교한다.
//
// abort: 새 버스트 발행을 멈추고 나가 있는 버스트가 모두 끝나면 done.
// AXI ID는 쓰지 않는다(모두 0, 응답 순서 = 발행 순서).
// ============================================================
`timescale 1ns / 1ps

module ddr_tgen #(
    parameter integer AW     = 30,
    parameter integer LOG_AW = 11
)(
    input  wire              clk,
    input  wire              rst,
    // 제어
    input  wire              start,
    input  wire              abort,
    output reg               busy,
    output reg               done,
    // 설정 (start 시점에 래치)
    input  wire              cfg_write,
    input  wire              cfg_verify,
    input  wire [1:0]        cfg_amode,
    input  wire              cfg_pipe,
    input  wire [AW-1:0]     cfg_base,
    input  wire [23:0]       cfg_xfer_beats,
    input  wire [7:0]        cfg_burst_max,
    input  wire [31:0]       cfg_n_xfers,
    input  wire [4:0]        cfg_max_outst,
    input  wire [AW-1:0]     cfg_stride,
    input  wire [7:0]        cfg_slot_cnt,
    input  wire [7:0]        cfg_slot_mask,
    input  wire [24:0]       cfg_addr_mask,
    input  wire [AW-1:0]     cfg_wrap,
    input  wire [31:0]       cfg_seed,
    input  wire [15:0]       cfg_gap,
    input  wire [31:0]       cfg_log_mask,
    // 결과
    output reg  [63:0]       r_cycles,
    output reg  [63:0]       r_beats,
    output reg  [31:0]       r_xfers,
    output reg  [31:0]       r_lat_min,
    output reg  [31:0]       r_lat_max,
    output reg  [63:0]       r_lat_sum,
    output reg  [31:0]       r_fst_min,
    output reg  [31:0]       r_fst_max,
    output reg  [63:0]       r_fst_sum,
    output reg  [31:0]       r_err_cnt,
    output reg  [AW-1:0]     r_err_addr,
    output reg  [31:0]       r_proto_err,
    output reg  [31:0]       r_ax_stall,
    output reg  [31:0]       r_w_stall,
    output reg  [LOG_AW:0]   r_log_n,
    // 기록 읽기 (1 cycle 지연)
    input  wire [LOG_AW-1:0] log_raddr,
    output reg  [63:0]       log_rdata,
    // AXI4 마스터 (256 bit)
    output wire [AW-1:0]     m_awaddr,
    output wire [7:0]        m_awlen,
    output wire              m_awvalid,
    input  wire              m_awready,
    output wire [255:0]      m_wdata,
    output wire              m_wlast,
    output wire              m_wvalid,
    input  wire              m_wready,
    input  wire              m_bvalid,
    output wire              m_bready,
    input  wire [1:0]        m_bresp,
    output wire [AW-1:0]     m_araddr,
    output wire [7:0]        m_arlen,
    output wire              m_arvalid,
    input  wire              m_arready,
    input  wire [255:0]      m_rdata,
    input  wire              m_rlast,
    input  wire              m_rvalid,
    output wire              m_rready,
    input  wire [1:0]        m_rresp
);

    localparam integer BA = AW - 5;     // beat 주소 폭 (32 B 단위)

    // ---------------- 패턴 ----------------
    function [255:0] pat;
        input [BA-1:0] ba;
        input [31:0]   seed;
        integer k;
        begin
            for (k = 0; k < 8; k = k + 1)
                pat[32*k +: 32] = {ba, k[2:0], 4'b0101} ^
                                  ((k == 0) ? seed : ((seed << (4*k)) | (seed >> (32 - 4*k))));
        end
    endfunction

    // ---------------- 설정 래치 ----------------
    reg          c_write, c_verify, c_pipe;
    reg [1:0]    c_amode;
    reg [AW-1:0] c_base, c_stride, c_wrap;
    reg [23:0]   c_xfer_beats;
    reg [7:0]    c_burst_max, c_slot_cnt, c_slot_mask;
    reg [31:0]   c_n_xfers, c_seed, c_log_mask;
    reg [4:0]    c_max_outst;
    reg [24:0]   c_addr_mask;
    reg [15:0]   c_gap;

    wire go = start && !busy;
    always @(posedge clk) begin
        if (go) begin
            c_write      <= cfg_write;
            c_verify     <= cfg_verify;
            c_pipe       <= cfg_pipe;
            c_amode      <= cfg_amode;
            c_base       <= {cfg_base[AW-1:5], 5'd0};
            c_stride     <= {cfg_stride[AW-1:5], 5'd0};
            c_wrap       <= {cfg_wrap[AW-1:5], 5'd0};
            c_xfer_beats <= (cfg_xfer_beats == 24'd0) ? 24'd1 : cfg_xfer_beats;
            c_burst_max  <= (cfg_burst_max == 8'd0) ? 8'd1 :
                            (cfg_burst_max > 8'd128) ? 8'd128 : cfg_burst_max;
            c_slot_cnt   <= (cfg_slot_cnt == 8'd0) ? 8'd1 : cfg_slot_cnt;
            c_slot_mask  <= cfg_slot_mask;
            c_n_xfers    <= cfg_n_xfers;
            c_seed       <= cfg_seed;
            c_log_mask   <= cfg_log_mask;
            c_max_outst  <= (cfg_max_outst == 5'd0) ? 5'd1 :
                            (cfg_max_outst > 5'd16) ? 5'd16 : cfg_max_outst;
            c_addr_mask  <= cfg_addr_mask;
            c_gap        <= cfg_gap;
        end
    end

    // ---------------- 실행 상태 ----------------
    reg         run;          // 발행 단계 (abort 시 0)
    reg [63:0]  cyc;          // 실행 시작 후 cycle
    wire [31:0] now = cyc[31:0];
    reg [31:0]  xf_issued;    // 시작한 전송 수
    reg [31:0]  xf_done;      // 끝난 전송 수
    reg [5:0]   outst;        // 나가 있는 버스트 수
    reg [5:0]   outst_x;      // 나가 있는 전송 수
    reg [15:0]  gap_cnt;

    // ---------------- 주소 생성기 ----------------
    reg [31:0]   lfsr;
    wire [31:0]  lfsr_nx = {1'b0, lfsr[31:1]} ^ (lfsr[0] ? 32'h80200003 : 32'h0);
    reg [31:0]   ag_cnt;      // 생성한 시작 주소 수
    reg          xa_vld;
    reg [AW-1:0] xa_addr;
    reg [AW-1:0] seq_off;     // SEQ: base로부터의 offset
    reg [7:0]    rr_slot;     // SLOT_RR
    reg [AW-1:0] rr_base;
    reg          sp_vld;      // SLOT_RAND: 뽑은 slot, 곱셈 대기
    reg [7:0]    sp_slot;
    wire         xa_take;     // 발행부가 이번 cycle에 가져감
    wire         ag_room = !xa_vld || xa_take;
    wire         ag_more = (ag_cnt != c_n_xfers);
    wire [AW-1:0] xfer_bytes = {1'b0, c_xfer_beats, 5'd0};
    wire [7:0]   lf_slot = lfsr[7:0] & c_slot_mask;
    wire [AW-1:0] seq_nx = seq_off + xfer_bytes;

    always @(posedge clk) begin
        if (go) begin
            lfsr    <= (cfg_seed == 32'd0) ? 32'h1 : cfg_seed;
            ag_cnt  <= 32'd0;
            xa_vld  <= 1'b0;
            seq_off <= {AW{1'b0}};
            rr_slot <= 8'd0;
            rr_base <= {AW{1'b0}};
            sp_vld  <= 1'b0;
        end else if (busy && run) begin
            if (xa_take) xa_vld <= 1'b0;
            case (c_amode)
            2'd0: if (ag_room && ag_more) begin
                      xa_addr <= c_base + seq_off;
                      xa_vld  <= 1'b1;
                      ag_cnt  <= ag_cnt + 32'd1;
                      if (c_wrap != {AW{1'b0}} && (seq_nx + xfer_bytes) > c_wrap)
                          seq_off <= {AW{1'b0}};
                      else
                          seq_off <= seq_nx;
                  end
            2'd1: begin
                      // 단계 1: slot 뽑기 (거부 표본추출)
                      if (!sp_vld && ag_more) begin
                          lfsr <= lfsr_nx;
                          if (lf_slot < c_slot_cnt) begin
                              sp_vld  <= 1'b1;
                              sp_slot <= lf_slot;
                          end
                      end
                      // 단계 2: 주소 = base + slot × stride
                      if (sp_vld && ag_room) begin
                          xa_addr <= c_base + sp_slot * c_stride;
                          xa_vld  <= 1'b1;
                          sp_vld  <= 1'b0;
                          ag_cnt  <= ag_cnt + 32'd1;
                      end
                  end
            2'd2: if (ag_room && ag_more) begin
                      xa_addr <= c_base + {lfsr[24:0] & c_addr_mask, 5'd0};
                      lfsr    <= lfsr_nx;
                      xa_vld  <= 1'b1;
                      ag_cnt  <= ag_cnt + 32'd1;
                  end
            2'd3: if (ag_room && ag_more) begin
                      xa_addr <= c_base + rr_base;
                      xa_vld  <= 1'b1;
                      ag_cnt  <= ag_cnt + 32'd1;
                      if (rr_slot + 8'd1 >= c_slot_cnt) begin
                          rr_slot <= 8'd0;
                          rr_base <= {AW{1'b0}};
                      end else begin
                          rr_slot <= rr_slot + 8'd1;
                          rr_base <= rr_base + c_stride;
                      end
                  end
            endcase
        end
    end

    // ---------------- FIFO ----------------
    // rf: 응답 추적 (발행 순서), {첫 버스트, 마지막 버스트, len, beat 주소}
    // wf: W 데이터 (AW 핸드셰이크 순서), {len, beat 주소}
    // xf: 전송 시작 시각
    localparam integer RFW = 2 + 8 + BA;
    localparam integer WFW = 8 + BA;

    wire           rf_push, rf_pop, rf_full, rf_empty;
    wire [RFW-1:0] rf_din, rf_dout;
    wire           wf_push, wf_pop, wf_full, wf_empty;
    wire [WFW-1:0] wf_din, wf_dout;
    wire           xf_push, xf_pop, xf_full, xf_empty;
    wire [31:0]    xf_dout;
    wire           fifo_clr = go;

    tgen_fifo #(.W(RFW)) u_rf (.clk(clk), .clr(rst | fifo_clr), .push(rf_push), .din(rf_din),
        .pop(rf_pop), .dout(rf_dout), .full(rf_full), .empty(rf_empty));
    tgen_fifo #(.W(WFW)) u_wf (.clk(clk), .clr(rst | fifo_clr), .push(wf_push), .din(wf_din),
        .pop(wf_pop), .dout(wf_dout), .full(wf_full), .empty(wf_empty));
    tgen_fifo #(.W(32))  u_xf (.clk(clk), .clr(rst | fifo_clr), .push(xf_push), .din(now),
        .pop(xf_pop), .dout(xf_dout), .full(xf_full), .empty(xf_empty));

    // ---------------- 발행부 ----------------
    reg          in_xfer;
    reg [AW-1:0] cur_addr;
    reg [23:0]   cur_rem;
    reg          ax_valid;
    reg [AW-1:0] ax_addr;
    reg [7:0]    ax_len;
    wire         ax_ready = c_write ? m_awready : m_arready;
    wire         ax_hs    = ax_valid && ax_ready;
    wire         ax_free  = !ax_valid || ax_hs;

    wire          blk_ok  = c_pipe || (outst_x == 6'd0 && gap_cnt == 16'd0);
    wire          nx_new  = !in_xfer;
    wire [AW-1:0] nx_addr = in_xfer ? cur_addr : xa_addr;
    wire [23:0]   nx_rem  = in_xfer ? cur_rem  : c_xfer_beats;
    wire          nx_ok   = in_xfer || (xa_vld && blk_ok);
    wire [7:0]    to4k    = 8'd128 - {1'b0, nx_addr[11:5]};
    wire [7:0]    m1      = (nx_rem < {16'd0, c_burst_max}) ? nx_rem[7:0] : c_burst_max;
    wire [7:0]    blen    = (m1 < to4k) ? m1 : to4k;
    wire          nx_last = (nx_rem == {16'd0, blen});
    wire          issue   = busy && run && nx_ok && ax_free &&
                            (outst < {1'b0, c_max_outst}) && !rf_full && !xf_full;

    assign xa_take = issue && nx_new;
    assign rf_push = issue;
    assign rf_din  = {nx_new, nx_last, blen - 8'd1, nx_addr[AW-1:5]};
    assign xf_push = issue && nx_new;

    // AW 핸드셰이크 때 W 정보를 넣는다 (W가 AW보다 앞서지 않게)
    reg [BA-1:0] ax_ba;
    assign wf_push = ax_hs && c_write;
    assign wf_din  = {ax_len, ax_ba};

    always @(posedge clk) begin
        if (rst || go) begin
            in_xfer  <= 1'b0;
            ax_valid <= 1'b0;
        end else begin
            if (ax_hs) ax_valid <= 1'b0;
            if (issue) begin
                ax_valid <= 1'b1;
                ax_addr  <= nx_addr;
                ax_ba    <= nx_addr[AW-1:5];
                ax_len   <= blen - 8'd1;
                in_xfer  <= !nx_last;
                cur_addr <= nx_addr + {{(AW-13){1'b0}}, blen, 5'd0};
                cur_rem  <= nx_rem - {16'd0, blen};
            end
        end
    end

    assign m_awaddr  = ax_addr;
    assign m_awlen   = ax_len;
    assign m_awvalid = ax_valid && c_write;
    assign m_araddr  = ax_addr;
    assign m_arlen   = ax_len;
    assign m_arvalid = ax_valid && !c_write;

    // ---------------- W 데이터 ----------------
    reg [7:0]    wcnt;
    wire [7:0]   wf_len = wf_dout[WFW-1:BA];
    wire [BA-1:0] wf_ba = wf_dout[BA-1:0];
    assign m_wvalid = !wf_empty;
    assign m_wlast  = (wcnt == wf_len);
    assign m_wdata  = pat(wf_ba + {{(BA-8){1'b0}}, wcnt}, c_seed);
    wire   w_hs     = m_wvalid && m_wready;
    assign wf_pop   = w_hs && m_wlast;
    always @(posedge clk) begin
        if (rst || go) wcnt <= 8'd0;
        else if (w_hs) wcnt <= m_wlast ? 8'd0 : wcnt + 8'd1;
    end

    // ---------------- 응답 처리 ----------------
    assign m_rready = 1'b1;
    assign m_bready = 1'b1;

    wire          rf_first = rf_dout[RFW-1];
    wire          rf_last  = rf_dout[RFW-2];
    wire [7:0]    rf_len   = rf_dout[RFW-3 -: 8];
    wire [BA-1:0] rf_ba    = rf_dout[BA-1:0];

    reg [7:0]  rcnt;
    reg [31:0] t_first;
    wire r_beat = m_rvalid && !rf_empty && !c_write;
    wire b_resp = m_bvalid && !rf_empty && c_write;
    wire burst_end = (r_beat && m_rlast) || b_resp;
    assign rf_pop  = burst_end;
    wire xfer_end  = burst_end && rf_last;
    assign xf_pop  = xfer_end;

    wire [31:0] fst_now = (r_beat && rcnt == 8'd0 && rf_first) ? now : t_first;

    // 통계 단계 (1 cycle 뒤)
    reg        s_vld;
    reg [31:0] s_lat, s_fst;
    // 검증 단계
    reg          v_vld;
    reg [255:0]  v_data;
    reg [BA-1:0] v_ba;

    always @(posedge clk) begin
        if (rst || go) begin
            rcnt  <= 8'd0;
            s_vld <= 1'b0;
            v_vld <= 1'b0;
        end else begin
            s_vld <= 1'b0;
            v_vld <= 1'b0;
            if (r_beat) begin
                if (rcnt == 8'd0 && rf_first) t_first <= now;
                rcnt   <= m_rlast ? 8'd0 : rcnt + 8'd1;
                v_vld  <= c_verify;
                v_data <= m_rdata;
                v_ba   <= rf_ba + {{(BA-8){1'b0}}, rcnt};
            end
            if (xfer_end) begin
                s_vld <= 1'b1;
                s_lat <= now - xf_dout;
                s_fst <= c_write ? (now - xf_dout) : (fst_now - xf_dout);
            end
        end
    end

    // ---------------- 카운터·통계 ----------------
    reg [63:0] log_mem [0:(1<<LOG_AW)-1];
    wire log_sel = ((xf_done & c_log_mask) == 32'd0) && !r_log_n[LOG_AW];

    always @(posedge clk) begin
        log_rdata <= log_mem[log_raddr];
        if (s_vld && log_sel) log_mem[r_log_n[LOG_AW-1:0]] <= {s_fst, s_lat};
    end

    wire inc_b = issue;
    wire dec_b = burst_end;
    wire inc_x = issue && nx_new;
    wire dec_x = xfer_end;

    always @(posedge clk) begin
        if (rst) begin
            busy <= 1'b0;
            done <= 1'b0;
            run  <= 1'b0;
        end else if (go) begin
            busy        <= 1'b1;
            done        <= 1'b0;
            run         <= 1'b1;
            cyc         <= 64'd0;
            xf_issued   <= 32'd0;
            xf_done     <= 32'd0;
            outst       <= 6'd0;
            outst_x     <= 6'd0;
            gap_cnt     <= 16'd0;
            r_cycles    <= 64'd0;
            r_beats     <= 64'd0;
            r_xfers     <= 32'd0;
            r_lat_min   <= 32'hFFFFFFFF;
            r_lat_max   <= 32'd0;
            r_lat_sum   <= 64'd0;
            r_fst_min   <= 32'hFFFFFFFF;
            r_fst_max   <= 32'd0;
            r_fst_sum   <= 64'd0;
            r_err_cnt   <= 32'd0;
            r_err_addr  <= {AW{1'b0}};
            r_proto_err <= 32'd0;
            r_ax_stall  <= 32'd0;
            r_w_stall   <= 32'd0;
            r_log_n     <= {(LOG_AW+1){1'b0}};
        end else if (busy) begin
            cyc     <= cyc + 64'd1;
            outst   <= outst + {5'd0, inc_b} - {5'd0, dec_b};
            outst_x <= outst_x + {5'd0, inc_x} - {5'd0, dec_x};
            if (inc_x) xf_issued <= xf_issued + 32'd1;
            if (abort) run <= 1'b0;

            if (dec_x)               gap_cnt <= c_gap;
            else if (gap_cnt != 0)   gap_cnt <= gap_cnt - 16'd1;

            if (ax_valid && !ax_ready)  r_ax_stall <= r_ax_stall + 32'd1;
            if (m_wvalid && !m_wready)  r_w_stall  <= r_w_stall + 32'd1;
            if (r_beat || w_hs)         r_beats    <= r_beats + 64'd1;
            if (r_beat && (m_rlast != (rcnt == rf_len)))
                r_proto_err <= r_proto_err + 32'd1;
            if ((r_beat && m_rresp != 2'b00) || (b_resp && m_bresp != 2'b00))
                r_proto_err <= r_proto_err + 32'd1;

            if (v_vld && v_data != pat(v_ba, c_seed)) begin
                if (r_err_cnt == 32'd0) r_err_addr <= {v_ba, 5'd0};
                r_err_cnt <= r_err_cnt + 32'd1;
            end

            if (s_vld) begin
                xf_done   <= xf_done + 32'd1;
                r_xfers   <= r_xfers + 32'd1;
                r_lat_sum <= r_lat_sum + {32'd0, s_lat};
                r_fst_sum <= r_fst_sum + {32'd0, s_fst};
                if (s_lat < r_lat_min) r_lat_min <= s_lat;
                if (s_lat > r_lat_max) r_lat_max <= s_lat;
                if (s_fst < r_fst_min) r_fst_min <= s_fst;
                if (s_fst > r_fst_max) r_fst_max <= s_fst;
                if (log_sel) r_log_n <= r_log_n + 1'b1;
            end

            // 종료: 모든 전송 완료, 또는 abort 후 나가 있는 것이 모두 끝남
            // (검증·통계 단계가 비도록 s_vld·v_vld가 0일 때)
            if (!s_vld && !v_vld && !ax_valid && outst == 6'd0 && wf_empty &&
                ((xf_done == c_n_xfers) || !run)) begin
                busy     <= 1'b0;
                done     <= 1'b1;
                run      <= 1'b0;
                r_cycles <= cyc;
            end
        end
    end

endmodule

// ============================================================
// tgen_fifo — 깊이 32, 앞 데이터가 바로 보이는(FWFT) 동기 FIFO (분산 RAM)
// ============================================================
module tgen_fifo #(
    parameter integer W = 32
)(
    input  wire         clk,
    input  wire         clr,
    input  wire         push,
    input  wire [W-1:0] din,
    input  wire         pop,
    output wire [W-1:0] dout,
    output wire         full,
    output wire         empty
);
    reg [W-1:0] mem [0:31];
    reg [5:0]   wp, rp;
    assign dout  = mem[rp[4:0]];
    assign empty = (wp == rp);
    assign full  = (wp[4:0] == rp[4:0]) && (wp[5] != rp[5]);
    always @(posedge clk) begin
        if (clr) begin
            wp <= 6'd0;
            rp <= 6'd0;
        end else begin
            if (push && !full) begin
                mem[wp[4:0]] <= din;
                wp <= wp + 6'd1;
            end
            if (pop && !empty) rp <= rp + 6'd1;
        end
    end
endmodule
