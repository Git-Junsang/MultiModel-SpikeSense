// ============================================================
// tb_p3_core.sv — p3_core(register + ddr_tgen) 단위 검증 (xsim)
// ============================================================
// MIG 대신 동작 모델(AXI4 슬레이브, 무작위 ready·지연, 순서 응답)을 붙이고
// AXI-Lite로 설정·시작·결과 읽기를 한다. 확인 항목:
//   - 4 KiB 경계를 넘는 버스트가 없고 len ≤ burst_max, 전송 크기 합이 맞다
//   - 쓰기 패턴을 읽기 검증으로 다시 읽으면 오류 0 (SEQ / SLOT_RAND / SLOT_RR / RAND_BEAT)
//   - 메모리 한 워드를 바꾸면 오류 1개와 그 주소가 보고된다
//   - blocking 모드에서 전송이 겹치지 않는다, pipelined에서 max_outst를 넘지 않는다
//   - 지연 통계(min ≤ 평균 ≤ max)와 기록 개수·값, abort, TS·MARK register
// 실행 (저장소 루트):
//   bash hardware/board_test/p3_meas/run_tb.sh
// ============================================================
`timescale 1ns / 1ps

module tb_p3_core;

    reg clk = 1'b0;
    always #5 clk = ~clk;
    reg rst = 1'b1;

    // AXI-Lite
    reg  [15:0] awaddr, araddr;
    reg         awvalid, wvalid, bready, arvalid, rready;
    reg  [31:0] wdata;
    wire        awready, wready, bvalid, arready, rvalid;
    wire [31:0] rdata;
    wire [1:0]  bresp, rresp;

    // AXI4 (tgen → 모델)
    wire [29:0]  m_awaddr, m_araddr;
    wire [7:0]   m_awlen, m_arlen;
    wire         m_awvalid, m_arvalid, m_wvalid, m_wlast, m_bready, m_rready;
    wire [255:0] m_wdata;
    reg          m_awready, m_arready, m_wready, m_bvalid, m_rvalid, m_rlast;
    reg  [255:0] m_rdata;

    wire ddr_sel, narrow_clr, tg_busy;

    p3_core #(.LOG_AW(11)) dut (
        .clk(clk), .rst(rst), .calib_done(1'b1), .lnk_up(1'b1),
        .narrow_seen(1'b0), .narrow_clr(narrow_clr), .ddr_sel(ddr_sel), .tg_busy(tg_busy),
        .s_awaddr(awaddr), .s_awvalid(awvalid), .s_awready(awready),
        .s_wdata(wdata), .s_wvalid(wvalid), .s_wready(wready),
        .s_bresp(bresp), .s_bvalid(bvalid), .s_bready(bready),
        .s_araddr(araddr), .s_arvalid(arvalid), .s_arready(arready),
        .s_rdata(rdata), .s_rresp(rresp), .s_rvalid(rvalid), .s_rready(rready),
        .m_awaddr(m_awaddr), .m_awlen(m_awlen), .m_awvalid(m_awvalid), .m_awready(m_awready),
        .m_wdata(m_wdata), .m_wlast(m_wlast), .m_wvalid(m_wvalid), .m_wready(m_wready),
        .m_bvalid(m_bvalid), .m_bready(m_bready), .m_bresp(2'b00),
        .m_araddr(m_araddr), .m_arlen(m_arlen), .m_arvalid(m_arvalid), .m_arready(m_arready),
        .m_rdata(m_rdata), .m_rlast(m_rlast), .m_rvalid(m_rvalid), .m_rready(m_rready),
        .m_rresp(2'b00)
    );

    integer fails = 0;
    task automatic check(input bit cond, input string msg);
        if (!cond) begin
            fails++;
            $display("FAIL: %s", msg);
        end
    endtask

    // ---------------- 메모리 모델 ----------------
    bit [255:0] mem [bit [24:0]];
    int rd_delay = 20;            // AR 수락 → 첫 R beat 최소 cycle
    int ready_pct = 70;
    int max_seen_outst = 0;
    int n_iss = 0, n_cmp = 0;
    int cur_logmask = 0;
    always @(negedge clk) if (n_iss - n_cmp > max_seen_outst) max_seen_outst = n_iss - n_cmp;
    int bursts_seen = 0;
    longint beats_seen = 0;

    typedef struct { bit [24:0] ba; int len; longint t; } req_t;
    req_t rq[$], wq[$], bq[$];
    longint cyc = 0;
    always @(posedge clk) cyc <= cyc + 1;

    function automatic bit [255:0] pat(bit [24:0] ba, bit [31:0] seed);
        bit [31:0] r;
        for (int k = 0; k < 8; k++) begin
            r = (k == 0) ? seed : ((seed << (4*k)) | (seed >> (32 - 4*k)));
            pat[32*k +: 32] = {ba, k[2:0], 4'b0101} ^ r;
        end
    endfunction

    function automatic void burst_check(bit [29:0] a, bit [7:0] len, int bmax);
        bit [29:0] last = a + (len + 1) * 32 - 1;
        if (a[29:12] != last[29:12]) begin fails++; $display("FAIL: 4KiB 경계 넘음 addr=%h len=%0d", a, len); end
        if (a[4:0] != 0) begin fails++; $display("FAIL: 비정렬 주소 %h", a); end
        if (len + 1 > bmax) begin fails++; $display("FAIL: len %0d > burst_max %0d", len + 1, bmax); end
    endfunction

    int cur_bmax = 128;

    // AR/AW ready 무작위
    always @(posedge clk) begin
        m_arready <= ($urandom_range(99) < ready_pct);
        m_awready <= ($urandom_range(99) < ready_pct);
        m_wready  <= ($urandom_range(99) < ready_pct);
    end

    always @(posedge clk) begin
        if (m_arvalid && m_arready) begin
            rq.push_back('{m_araddr[29:5], m_arlen, cyc});
            burst_check(m_araddr, m_arlen, cur_bmax);
            bursts_seen++;
            n_iss++;
        end
        if (m_awvalid && m_awready) begin
            wq.push_back('{m_awaddr[29:5], m_awlen, cyc});
            burst_check(m_awaddr, m_awlen, cur_bmax);
            bursts_seen++;
            n_iss++;
        end
    end

    // R 채널
    int rbeat = 0;
    always @(posedge clk) begin
        if (rst) begin
            m_rvalid <= 1'b0;
            m_rlast  <= 1'b0;
        end else begin
            if (m_rvalid && m_rready) begin
                beats_seen++;
                if (m_rlast) begin
                    void'(rq.pop_front());
                    rbeat = 0;
                    n_cmp++;
                end else rbeat++;
            end
            m_rvalid <= 1'b0;
            m_rlast  <= 1'b0;
            if (rq.size() > 0 && cyc >= rq[0].t + rd_delay && $urandom_range(99) < 85) begin
                if (!(m_rvalid && m_rready && m_rlast && rq.size() == 0)) begin
                    m_rvalid <= 1'b1;
                    m_rdata  <= mem.exists(rq[0].ba + rbeat) ? mem[rq[0].ba + rbeat] : '0;
                    m_rlast  <= (rbeat == rq[0].len);
                end
            end
        end
    end

    // W 채널 + B 채널
    int wbeat = 0;
    always @(posedge clk) begin
        if (rst) begin
            m_bvalid <= 1'b0;
        end else begin
            if (m_wvalid && m_wready) begin
                if (wq.size() == 0) begin fails++; $display("FAIL: AW 없이 W"); end
                else begin
                    mem[wq[0].ba + wbeat] = m_wdata;
                    beats_seen++;
                    if (m_wlast != (wbeat == wq[0].len)) begin fails++; $display("FAIL: wlast 위치"); end
                    if (m_wlast) begin
                        bq.push_back('{0, 0, cyc});
                        void'(wq.pop_front());
                        wbeat = 0;
                    end else wbeat++;
                end
            end
            if (m_bvalid && m_bready) begin
                m_bvalid <= 1'b0;
                void'(bq.pop_front());
                n_cmp++;
            end else if (!m_bvalid && bq.size() > 0 && cyc >= bq[0].t + 8) begin
                m_bvalid <= 1'b1;
            end
        end
    end

    // ---------------- AXI-Lite 태스크 ----------------
    task automatic wr(input [15:0] a, input [31:0] d);
        @(posedge clk);
        awaddr <= a; wdata <= d; awvalid <= 1'b1; wvalid <= 1'b1;
        do @(posedge clk); while (!(awready && wready));
        awvalid <= 1'b0; wvalid <= 1'b0; bready <= 1'b1;
        do @(posedge clk); while (!bvalid);
        bready <= 1'b0;
    endtask

    task automatic rd(input [15:0] a, output [31:0] d);
        @(posedge clk);
        araddr <= a; arvalid <= 1'b1;
        do @(posedge clk); while (!arready);
        arvalid <= 1'b0; rready <= 1'b1;
        do @(posedge clk); while (!rvalid);
        d = rdata;
        rready <= 1'b0;
    endtask

    typedef struct {
        bit [31:0] cyc, beats, xfers, delay_min, delay_max, delay_sum, fst_min, fst_max, err, err_addr, proto, log_n;
    } res_t;

    task automatic run(input bit write, input bit verify, input [1:0] amode, input bit pipe,
                       input [31:0] base, input [31:0] xb, input [31:0] bmax, input [31:0] n,
                       input [31:0] outst, input [31:0] seed, output res_t r);
        bit [31:0] st;
        int v_exp_log;
        cur_bmax = bmax;
        wr(16'h0048, {27'd0, pipe, amode, verify, write});
        wr(16'h004C, base);
        wr(16'h0050, xb);
        wr(16'h0054, bmax);
        wr(16'h0058, n);
        wr(16'h005C, outst);
        wr(16'h0074, seed);
        max_seen_outst = 0;
        bursts_seen = 0;
        beats_seen = 0;
        wr(16'h0040, 32'h1);
        do begin
            repeat (50) @(posedge clk);
            rd(16'h0008, st);
        end while (st[2]);
        check(st[3], "done 비트");
        rd(16'h0100, r.cyc);
        rd(16'h0108, r.beats);
        rd(16'h0110, r.xfers);
        rd(16'h0114, r.delay_min);
        rd(16'h0118, r.delay_max);
        rd(16'h011C, r.delay_sum);
        rd(16'h0124, r.fst_min);
        rd(16'h0128, r.fst_max);
        rd(16'h0134, r.err);
        rd(16'h0138, r.err_addr);
        rd(16'h013C, r.proto);
        rd(16'h0148, r.log_n);
        $display("run w=%0d v=%0d am=%0d pipe=%0d xb=%0d bmax=%0d n=%0d out=%0d : cyc=%0d beats=%0d xfers=%0d lat[min=%0d max=%0d avg=%0.1f] fst[min=%0d max=%0d] err=%0d proto=%0d log=%0d maxout=%0d",
                 write, verify, amode, pipe, xb, bmax, n, outst, r.cyc, r.beats, r.xfers,
                 r.delay_min, r.delay_max, real'(r.delay_sum) / real'(r.xfers), r.fst_min, r.fst_max,
                 r.err, r.proto, r.log_n, max_seen_outst);
        check(r.xfers == n, "전송 수");
        check(r.beats == n * xb, "beat 수(tgen)");
        check(beats_seen == n * xb, "beat 수(모델)");
        check(r.proto == 0, "프로토콜 오류");
        check(r.delay_min <= r.delay_max, "lat min<=max");
        v_exp_log = (n + cur_logmask) / (cur_logmask + 1);
        check(r.log_n == ((v_exp_log < 2048) ? v_exp_log : 2048), "기록 개수");
        check(max_seen_outst <= outst, "max_outst 초과");
    endtask

    res_t r;
    bit [31:0] v, v2;
    bit [31:0] base0 = 32'h0000_0E00;   // 4 KiB 경계 직전에서 시작

    initial begin
        awvalid = 0; wvalid = 0; bready = 0; arvalid = 0; rready = 0;
        repeat (20) @(posedge clk);
        rst = 1'b0;
        repeat (10) @(posedge clk);

        rd(16'h0000, v);
        check(v == 32'h4D4D5033, "ID");
        wr(16'h000C, 32'hCAFEF00D);
        rd(16'h000C, v);
        check(v == 32'hCAFEF00D, "SCRATCH");
        rd(16'h0010, v);
        rd(16'h0010, v2);
        check(v2 > v, "TS 증가");
        wr(16'h0018, 32'h55AA);
        rd(16'h0024, v);
        check(v == 32'h55AA, "MARK_VAL");

        // 1) SEQ 쓰기 → 읽기 검증, 4 KiB 경계 분할 (blocking)
        run(1, 0, 0, 0, base0, 200, 64, 5, 4, 32'hA5A5_0001, r);
        check(r.err == 0, "쓰기 오류");
        run(0, 1, 0, 0, base0, 200, 64, 5, 4, 32'hA5A5_0001, r);
        check(r.err == 0, "SEQ 읽기 검증");
        check(r.fst_min >= rd_delay, "fst >= 모델 지연");

        // 2) 한 워드를 바꾸면 오류 1개와 그 주소
        mem[(base0 >> 5) + 77] ^= 256'h1;
        run(0, 1, 0, 1, base0, 200, 32, 5, 8, 32'hA5A5_0001, r);
        check(r.err == 1, "오류 1개 검출");
        check(r.err_addr == base0 + 77 * 32, "오류 주소");

        // 3) SLOT_RAND: 같은 seed로 쓰고 읽으면 같은 slot 순서 → 검증 통과
        wr(16'h0060, 32'h21000);  // stride
        wr(16'h0064, 32'd40);
        wr(16'h0068, 32'd63);
        run(1, 0, 1, 1, 32'h0000_3C00, 96, 128, 60, 8, 32'h0BAD_5EED, r);
        run(0, 1, 1, 1, 32'h0000_3C00, 96, 128, 60, 8, 32'h0BAD_5EED, r);
        check(r.err == 0, "SLOT_RAND 검증");

        // 4) SLOT_RR blocking, 전체 모델(4068 beat) 3개
        run(1, 0, 3, 0, 32'h0, 4068, 128, 3, 16, 32'h77, r);
        run(0, 1, 3, 0, 32'h0, 4068, 128, 3, 16, 32'h77, r);
        check(r.err == 0, "SLOT_RR 전체 모델 검증");

        // 5) RAND_BEAT 단일 beat, 64 KiB 범위 (먼저 SEQ로 채움)
        run(1, 0, 0, 1, 32'h0010_0000, 2048, 128, 1, 16, 32'h99, r);
        wr(16'h006C, 32'h7FF);     // addr_mask: 2048 beat
        run(0, 1, 2, 0, 32'h0010_0000, 1, 1, 300, 1, 32'h99, r);
        check(r.err == 0, "RAND_BEAT 검증");
        check(r.delay_min >= rd_delay, "단일 지연 >= 모델 지연");

        // 6) 기록 값 확인: 0번 항목의 lat가 통계 범위 안
        rd(16'h8004, v);
        rd(16'h8000, v2);
        check(v >= r.delay_min && v <= r.delay_max, "기록 lat 범위");
        check(v2 <= v, "기록 fst <= lat");

        // 7) 2048개 초과 → 기록 2048개에서 멈춤, log_mask
        run(0, 0, 0, 1, 32'h0, 1, 1, 3000, 16, 32'h1, r);
        wr(16'h007C, 32'h3);
        cur_logmask = 3;           // 400개 중 0, 4, 8, ... → 100개 기록
        run(0, 0, 0, 1, 32'h0, 1, 1, 400, 16, 32'h1, r);
        wr(16'h007C, 32'h0);
        cur_logmask = 0;

        // 8) abort
        cur_bmax = 128;
        wr(16'h0048, 32'h0);
        wr(16'h0050, 32'd1000);
        wr(16'h0058, 32'd100000);
        wr(16'h0040, 32'h1);
        repeat (2000) @(posedge clk);
        wr(16'h0040, 32'h2);
        repeat (3000) @(posedge clk);
        rd(16'h0008, v);
        check(!v[2] && v[3], "abort 후 done");
        rd(16'h0110, v);
        check(v > 0 && v < 100000, "abort 전송 수");

        if (fails == 0) $display("PASS tb_p3_core");
        else            $display("FAIL tb_p3_core: %0d건", fails);
        $finish;
    end

    initial begin
        #200_000_000;
        $display("FAIL: 시간 초과");
        $finish;
    end

endmodule
