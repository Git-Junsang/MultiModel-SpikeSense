// ============================================================
// tb_dma.sv — accel_core(compute_array + weight_cache + membrane_storage + DMA)를 golden_l64_m12와 대조 (P4.4)
// ============================================================
// weight와 DDR3 트랙의 membrane potential을 모두 DMA가 AXI slave 모델(DDR3)에서 읽고 쓴다. testbench는 scheduler 대신
// batch를 정해 교체 계획(pl), membrane potential 준비(pf), 추론 시작(go)을 낸다. 다음 batch의 계획은 지금 batch의
// 첫 추론이 시작될 때 낸다(prefetch). 다음 추론의 pf와 go는 앞 추론이 연산하는 동안 미리 낸다.
//   앞 timestep 0–15   모델마다 batch 하나에 그 모델 트랙의 timestep을 모두 넣는다. Batch가 적재(4,114 beat)보다
//                      길어 다음 모델 적재가 연산 중에 끝나야 한다(첫 batch 뒤 weight 대기 0).
//   뒤 timestep 16–30  batch 하나 = 추론 하나. 같은 모델의 두 번째 트랙은 hit, 다음 모델은 miss라 적재가 늦어
//                      연산이 멈춘다.
// slave 모델 MODE: 0 멈춤 없음(첫 beat까지 26 cycle, ID 순서대로), 1 무작위 ready·지연·beat 간격, ID가 다른 burst끼리
//                  순서 바꾸기와 beat 섞기, 2 = 1 + 오류 응답(SLVERR) 주입.
// 확인 항목:
//   - row마다 전류·membrane potential·spike·12 bit 저장값, 판정용 출력이 golden과 bit 일치, 끝난 뒤 DDR3 트랙 내용
//   - 적재마다 entry의 word 2,034개·params row 46개가 slot과 같음(spike 0 건너뛰기로 안 읽는 word 포함)
//   - 적재 수 = miss 수, weight beat = 적재 × 4,114, membrane potential beat = 읽기 22 × 30 × 34, 쓰기 22 × 31 × 34
//   - AXI 규칙(valid 유지, 4 KiB 경계, burst 길이·주소 범위, 주소 전 쓰기 데이터 없음, wlast, 동시 weight burst ≤ 4)
//   - 우선순위: membrane potential 읽기·쓰기가 기다리거나 진행 중일 때 새 weight burst를 내지 않음
//   - 적재 중인 entry로 시작하지 않음, stall_cyc = testbench가 센 정지 cycle, 오류 응답의 주소
// 실행 (저장소 루트):
//   bash hardware/testbench/run_dma.sh
// ============================================================
`timescale 1ns / 1ps

module tb_dma #(
    parameter int MODE = 1
);

    localparam int N_VEC = 82, N_MOD = 42, T = 31, TA = 16, ROWS = 45, CUR_W = 17, N_ON_CHIP = 768, E = 4, EW = 2;
    localparam int LD = 4114, WB = 16, W_OUT = 4, LAT0 = 26;
    localparam string VEC = "hardware/sim/compute_array/vec_m12/";
    localparam [31:0] MODEL_BASE = 32'h0000_0000, STATE_BASE = 32'h0200_0000;

    reg clk = 1'b0;
    always #5 clk = ~clk;
    reg rst = 1'b1;
    longint cyc = 0;
    always @(posedge clk) begin
        cyc <= cyc + 1;
        if (cyc > 20_000_000) begin           // 정상 실행은 370만~460만 cycle. 적재가 끝나지 않으면 여기서 멈춘다
            $display("FAIL 시간 초과: cycle %0d", cyc);
            $finish;
        end
    end

    // ---------------- DUT ----------------
    reg           cfg_we = 1'b0;
    reg  [10:0]   cfg_addr = 11'd0;
    reg  [15:0]   cfg_data = 16'd0;
    reg           pl_valid = 1'b0;
    reg  [5:0]    pl_model = 6'd0;
    wire          pl_ready, pl_done, pl_hit, pl_evict;
    wire [EW-1:0] pl_entry;
    wire [5:0]    pl_victim;
    reg           pf_valid = 1'b0, pf_reset = 1'b0;
    reg  [9:0]    pf_track = 10'd0;
    wire          pf_ready;
    reg           go_valid = 1'b0, go_reset = 1'b0;
    reg  [EW-1:0] go_entry = '0;
    reg  [9:0]    go_track = 10'd0;
    reg  [319:0]  go_x = '0;
    wire          go_ready, busy, done, wb_done;
    wire [15:0]   out_mem0, out_mem1;
    wire [9:0]    wb_track;
    wire [63:0]   stall_cyc;
    wire          dma_idle, err;
    wire [31:0]   err_addr;

    wire [31:0]   m_araddr, m_awaddr;
    wire [7:0]    m_arlen, m_awlen;
    wire          m_arid, m_arvalid, m_rready, m_awvalid, m_wlast, m_wvalid, m_bready;
    wire [255:0]  m_wdata;
    reg           m_arready = 1'b0, m_rvalid = 1'b0, m_rid = 1'b0, m_rlast = 1'b0;
    reg           m_awready = 1'b0, m_wready = 1'b0, m_bvalid = 1'b0;
    reg  [255:0]  m_rdata = '0;
    reg  [1:0]    m_rresp = 2'd0, m_bresp = 2'd0;

    accel_core #(.E(E), .N_MODELS(N_MOD), .N_ON_CHIP(N_ON_CHIP)) dut (
        .clk(clk), .rst(rst), .model_base(MODEL_BASE), .state_base(STATE_BASE),
        .now_us(32'd0), .phase_us(15'd0), .period(16'd0), .first_period(1'b1),
        .cfg_we(cfg_we), .cfg_addr(cfg_addr), .cfg_data(cfg_data),
        .arr_valid(1'b0), .arr_model(6'd0), .arr_t_host(32'd0), .arr_n_expect(11'd0), .q_ne({N_MOD{1'b0}}),
        .pl_valid(pl_valid), .pl_model(pl_model), .pl_ready(pl_ready), .pl_done(pl_done),
        .pl_entry(pl_entry), .pl_hit(pl_hit), .pl_evict(pl_evict), .pl_victim(pl_victim),
        .pf_valid(pf_valid), .pf_track(pf_track), .pf_reset(pf_reset), .pf_ready(pf_ready),
        .go_valid(go_valid), .go_ready(go_ready), .go_entry(go_entry), .go_track(go_track),
        .go_reset(go_reset), .go_x(go_x),
        .busy(busy), .done(done), .out_mem0(out_mem0), .out_mem1(out_mem1), .wb_done(wb_done), .wb_track(wb_track),
        .cnt_clear(1'b0), .stall_cyc(stall_cyc), .dma_idle(dma_idle), .err(err), .err_addr(err_addr),
        .m_araddr(m_araddr), .m_arlen(m_arlen), .m_arid(m_arid), .m_arvalid(m_arvalid), .m_arready(m_arready),
        .m_rdata(m_rdata), .m_rid(m_rid), .m_rresp(m_rresp), .m_rlast(m_rlast), .m_rvalid(m_rvalid), .m_rready(m_rready),
        .m_awaddr(m_awaddr), .m_awlen(m_awlen), .m_awvalid(m_awvalid), .m_awready(m_awready),
        .m_wdata(m_wdata), .m_wlast(m_wlast), .m_wvalid(m_wvalid), .m_wready(m_wready),
        .m_bresp(m_bresp), .m_bvalid(m_bvalid), .m_bready(m_bready)
    );

    // ---------------- data ----------------
    reg [7:0]   idx  [0:N_VEC-1];
    reg [511:0] wall [0:N_MOD*2034-1];
    reg [255:0] pall [0:N_MOD*46-1];
    reg [319:0] xall [0:N_VEC*T-1];
    reg [911:0] eall [0:N_VEC*T*ROWS-1];
    reg [31:0]  oall [0:N_VEC*T-1];
    integer     mem_of [0:N_MOD-1][0:1];
    integer     n_of   [0:N_MOD-1];
    bit         pend   [0:1023];          // 되쓰기 응답 전인 DDR3 트랙

    function automatic integer trk(input integer v);
        case (v)
        0: trk = 0;
        1: trk = 768;
        2: trk = 767;
        3: trk = 1023;
        default: trk = (v * 37 + 11) % 1024;
        endcase
    endfunction

    // ---------------- DDR3: AXI slave 모델 ----------------
    // 모델 slot m의 beat b = mslot[m × 4,114 + b](slot 앞 131,648 B), 트랙 k의 beat i = mstate[k × 64 + i]
    reg [255:0] mslot  [0:N_MOD*LD-1];
    reg [255:0] mstate [0:65535];

    function automatic [255:0] ddr_rd(input [31:0] a);
        if (a >= STATE_BASE) ddr_rd = mstate[(a - STATE_BASE) >> 5];
        else                 ddr_rd = mslot[(a >> 18) * LD + ((a >> 5) & 32'h1FFF)];
    endfunction

    typedef struct packed {
        logic [31:0] addr;
        logic [7:0]  len;
        logic [63:0] t;          // 첫 beat를 낼 수 있는 cycle(읽기), 응답 cycle(쓰기)
        logic        err;        // 오류 응답 후보
    } burst_t;

    burst_t rq0[$], rq1[$], awq[$], bq[$];
    int     rk0 = 0, rk1 = 0, wk = 0;
    longint rbeat0 = 0, rbeat1 = 0, wbeat = 0, last_inj = -100;
    int     prot_err = 0, prio_err = 0, n_inj = 0, n_err_seen = 0, err_mis = 0;
    reg [31:0] exp_err [$];

    task automatic prot(input string s);
        if (prot_err < 5) $display("FAIL AXI: %s (cycle %0d)", s, cyc);
        prot_err = prot_err + 1;
    endtask

    task automatic check_ar(input [31:0] a, input [7:0] len, input id);
        longint k;
        if (a[4:0] != 5'd0 || ({20'd0, a[11:0]} + (len + 1) * 32) > 4096) prot("주소 정렬, 4 KiB 경계");
        if (id) begin
            k = (a - STATE_BASE) >> 11;
            if (len != 8'd33 || a < STATE_BASE || ((a - STATE_BASE) & 32'h7FF) != 0 || k >= 1024 || k < N_ON_CHIP)
                prot("membrane potential 읽기 주소·길이");
        end else if (len + 1 > WB || a >= STATE_BASE || (a >> 18) >= N_MOD || ((a >> 5) & 32'h1FFF) + len + 1 > LD)
            prot("weight burst 주소·길이");
    endtask

    // 오류 응답은 앞 주입과 8 cycle 넘게 떨어질 때만 낸다(DMA는 같은 cycle에 하나만 보고한다)
    function automatic bit inject(input bit cand, input [31:0] a);
        inject = 1'b0;
        if (cand && cyc - last_inj > 8) begin
            inject = 1'b1;
            last_inj = cyc;
            exp_err.push_back(a);
            n_inj = n_inj + 1;
        end
    endfunction

    // 읽기 채널
    always @(posedge clk) begin : rd_ch
        burst_t b;
        bit c0, c1, p1;
        if (m_arvalid && m_arready) begin
            check_ar(m_araddr, m_arlen, m_arid);
            b.addr = m_araddr;
            b.len  = m_arlen;
            b.t    = cyc + ((MODE == 0) ? LAT0 : 8 + $urandom % 50);
            b.err  = (MODE == 2) && ($urandom % 30 == 0);
            if (m_arid) rq1.push_back(b); else rq0.push_back(b);
            if (rq0.size() > W_OUT) prot("동시 weight burst 수");
        end
        m_arready <= (MODE == 0) || ($urandom % 2 == 0);
        m_rvalid  <= 1'b0;
        c0 = (rq0.size() > 0) && (rq0[0].t <= cyc);
        c1 = (rq1.size() > 0) && (rq1[0].t <= cyc);
        if ((c0 || c1) && (MODE == 0 || $urandom % 4 != 0)) begin
            if (c0 && c1) p1 = (MODE == 0) ? (rq1[0].t < rq0[0].t) : ($urandom % 2 == 0);
            else          p1 = c1;
            m_rvalid <= 1'b1;
            m_rid    <= p1;
            if (p1) begin
                m_rdata <= ddr_rd(rq1[0].addr + rk1 * 32);
                m_rlast <= (rk1 == rq1[0].len);
                m_rresp <= (rk1 == 0 && inject(rq1[0].err, rq1[0].addr)) ? 2'd2 : 2'd0;
                rbeat1 = rbeat1 + 1;
                if (rk1 == rq1[0].len) begin void'(rq1.pop_front()); rk1 = 0; end else rk1 = rk1 + 1;
            end else begin
                m_rdata <= ddr_rd(rq0[0].addr + rk0 * 32);
                m_rlast <= (rk0 == rq0[0].len);
                m_rresp <= (rk0 == 0 && inject(rq0[0].err, rq0[0].addr & ~32'h3FFFF)) ? 2'd2 : 2'd0;
                rbeat0 = rbeat0 + 1;
                if (rk0 == rq0[0].len) begin void'(rq0.pop_front()); rk0 = 0; end else rk0 = rk0 + 1;
            end
        end
    end

    // 쓰기 채널
    always @(posedge clk) begin : wr_ch
        burst_t b;
        longint k;
        if (m_awvalid && m_awready) begin
            k = (m_awaddr - STATE_BASE) >> 11;
            if (m_awlen != 8'd33 || m_awaddr < STATE_BASE || ((m_awaddr - STATE_BASE) & 32'h7FF) != 0
                || k >= 1024 || k < N_ON_CHIP)
                prot("membrane potential 쓰기 주소·길이");
            b.addr = m_awaddr;
            b.len  = m_awlen;
            b.t    = 0;
            b.err  = (MODE == 2) && ($urandom % 30 == 0);
            awq.push_back(b);
        end
        m_awready <= (MODE == 0) || ($urandom % 2 == 0);
        if (m_wvalid && m_wready) begin
            if (awq.size() == 0)
                prot("주소 전 쓰기 data");
            else begin
                mstate[((awq[0].addr - STATE_BASE) >> 5) + wk] = m_wdata;
                wbeat = wbeat + 1;
                if (m_wlast != (wk == 33)) prot("wlast");
                if (wk == 33) begin
                    b = awq.pop_front();
                    b.t = cyc + ((MODE == 0) ? 5 : 3 + $urandom % 40);
                    bq.push_back(b);
                    wk = 0;
                end else
                    wk = wk + 1;
            end
        end
        m_wready <= (MODE == 0) || ($urandom % 4 != 0);
        m_bvalid <= 1'b0;
        if (bq.size() > 0 && bq[0].t <= cyc) begin
            b = bq.pop_front();
            m_bvalid <= 1'b1;
            m_bresp  <= inject(b.err, b.addr) ? 2'd2 : 2'd0;
        end
    end

    // valid 유지와 우선순위. 값은 negedge에 읽는다(cycle 안에서 안정)
    reg        h_ar = 1'b0, h_aw = 1'b0, h_w = 1'b0, p_arv = 1'b0, p_arhs = 1'b0, p_wrb = 1'b0, p_drq = 1'b0;
    reg [31:0] h_araddr, h_awaddr;
    reg [7:0]  h_arlen;
    reg        h_arid, h_wlast;
    reg [255:0] h_wdata;
    always @(negedge clk) if (!rst) begin
        if (h_ar && !(m_arvalid && m_araddr == h_araddr && m_arlen == h_arlen && m_arid == h_arid)) prot("arvalid 유지");
        if (h_aw && !(m_awvalid && m_awaddr == h_awaddr)) prot("awvalid 유지");
        if (h_w && !(m_wvalid && m_wdata == h_wdata && m_wlast == h_wlast)) prot("wvalid 유지");
        if (!m_rready || !m_bready) prot("rready·bready");
        // 앞 cycle에 쓰기나 membrane potential 읽기가 있었으면 이번 cycle의 새 주소는 weight burst가 아니다
        if (m_arvalid && (!p_arv || p_arhs) && !m_arid && (p_wrb || p_drq)) begin
            if (prio_err < 5) $display("FAIL 우선순위: cycle %0d 새 weight burst (쓰기 %0b, 읽기 %0b)", cyc, p_wrb, p_drq);
            prio_err = prio_err + 1;
        end
        h_ar = m_arvalid && !m_arready; h_araddr = m_araddr; h_arlen = m_arlen; h_arid = m_arid;
        h_aw = m_awvalid && !m_awready; h_awaddr = m_awaddr;
        h_w  = m_wvalid && !m_wready;   h_wdata = m_wdata;   h_wlast = m_wlast;
        p_arv  = m_arvalid;
        p_arhs = m_arvalid && m_arready;
        p_wrb  = m_awvalid || awq.size() > 0 || bq.size() > 0 || m_bvalid || dut.dw_req_valid;
        p_drq  = dut.dr_req_valid;
    end

    // ---------------- 대조 ----------------
    integer v_now = 0, t_now = 0, rows_seen = 0, n_inf = 0, err_rows = 0, err_out = 0, err_ddr = 0, n_sat = 0, err_sat = 0;
    bit     sat_exp = 1'b0;                // 이번 추론에서 golden의 포화 후 값이 16 bit 끝값인 lane이 있음

    function automatic [255:0] store12(input [255:0] m);
        integer i, x;
        for (i = 0; i < 16; i = i + 1) begin
            x = $signed(m[16*i +: 16]);
            x = (x > 2047) ? 2047 : (x < -2048) ? -2048 : x;
            store12[16*i +: 16] = x[15:0];
        end
    endfunction

    always @(negedge clk) begin
        if (!rst && dut.u_ca.m_wr_en) begin : chk
            reg [911:0] e;
            reg [255:0] st;
            integer k, lane_n, bad;
            e = eall[(v_now * T + t_now) * ROWS + dut.u_ca.m_wr_row];
            st = store12(dut.u_ca.m_wr_data);
            lane_n = (dut.u_ca.m_wr_row == 6'd44) ? 2 : 16;
            bad = 0;
            for (k = 0; k < lane_n; k = k + 1) begin
                if (e[384 + 16*k +: 16] == 16'h7FFF || e[384 + 16*k +: 16] == 16'h8000) sat_exp = 1'b1;
                if ($signed(dut.u_ca.dbg_cur[CUR_W*k +: CUR_W]) != $signed(e[24*k +: 24])) bad = bad + 1;
                if (dut.u_ca.dbg_mem_sat[16*k +: 16] != e[384 + 16*k +: 16]) bad = bad + 1;
                if (st[16*k +: 16] != e[640 + 16*k +: 16]) bad = bad + 1;
                if (dut.u_ca.dbg_spk[k] != e[896 + k]) bad = bad + 1;
            end
            if (bad != 0) begin
                if (err_rows < 5)
                    $display("FAIL v%0d(트랙 %0d) t%0d row %0d: 불일치 %0d", v_now, trk(v_now), t_now, dut.u_ca.m_wr_row, bad);
                err_rows = err_rows + 1;
            end
            rows_seen = rows_seen + 1;
        end
    end

    bit        done_seen = 1'b0;
    reg [31:0] out_q;
    integer    rows_q;
    always @(negedge clk) begin
        if (done) begin
            if (dut.sat16 !== sat_exp) err_sat = err_sat + 1;
            if (sat_exp) n_sat = n_sat + 1;
            done_seen = 1'b1;
            out_q     = {out_mem1, out_mem0};
            rows_q    = rows_seen;
        end
        if (wb_done) pend[wb_track] = 1'b0;
        if (err) begin
            n_err_seen = n_err_seen + 1;
            if (exp_err.size() == 0 || exp_err[0] != err_addr) begin
                if (err_mis < 5) $display("FAIL 오류 응답: 주소 %08h", err_addr);
                err_mis = err_mis + 1;
            end
            if (exp_err.size() > 0) void'(exp_err.pop_front());
        end
    end

    // 적재가 끝나면(ld_done 다음 cycle) entry 내용을 slot과 맞춘다
    reg           chk_now = 1'b0;
    reg [EW-1:0]  chk_e;
    reg [5:0]     chk_m;
    integer       n_load = 0, ent_bad = 0;
    longint       ld_t0 = 0, ld_sum = 0, ld_min = 64'h7FFF_FFFF, ld_max = 0;
    reg           ldb_q = 1'b0;
    always @(posedge clk) begin
        chk_now <= dut.ld_done;
        chk_e   <= dut.ld_entry;
        chk_m   <= dut.ld_model;
        if (dut.ld_busy && !ldb_q) ld_t0 = cyc;
        ldb_q <= dut.ld_busy;
        if (dut.ld_done) begin
            n_load = n_load + 1;
            ld_sum = ld_sum + (cyc - ld_t0 + 1);
            if (cyc - ld_t0 + 1 < ld_min) ld_min = cyc - ld_t0 + 1;
            if (cyc - ld_t0 + 1 > ld_max) ld_max = cyc - ld_t0 + 1;
        end
    end
    genvar g;
    generate
        for (g = 0; g < E; g = g + 1) begin : g_chk
            always @(negedge clk)
                if (chk_now && chk_e == g) begin : cmp
                    integer a, bad;
                    bad = 0;
                    for (a = 0; a < 2034; a = a + 1)
                        if (dut.u_wc.g_entry[g].u_entry.wmem[a] !== wall[chk_m * 2034 + a]) bad = bad + 1;
                    for (a = 0; a < 46; a = a + 1)
                        if (dut.u_wc.g_entry[g].u_entry.pmem[a] !== pall[chk_m * 46 + a]) bad = bad + 1;
                    if (bad != 0 && ent_bad < 5) $display("FAIL 적재: entry %0d 모델 %0d 불일치 %0d", g, chk_m, bad);
                    if (bad != 0) ent_bad = ent_bad + 1;
                end
        end
    endgenerate

    // 정지 cycle(weight 적재 대기 / membrane potential 대기), membrane potential 전송 시간
    longint w_stall = 0, m_stall = 0, mr_t0 = 0, mw_t0 = 0, mr_sum = 0, mr_max = 0, mw_sum = 0, mw_max = 0;
    integer mr_n = 0, mw_n = 0, mr_beats = 0;
    always @(posedge clk) if (!rst) begin
        if (go_valid && !busy && !go_ready) begin
            if (dut.ld_busy && dut.ld_entry == go_entry) w_stall = w_stall + 1;
            else m_stall = m_stall + 1;
        end
        if (dut.dr_req_valid && dut.dr_req_ready) begin mr_t0 = cyc; mr_beats = 0; end
        if (dut.dr_valid) begin
            mr_beats = mr_beats + 1;
            if (mr_beats == 34) begin
                mr_n = mr_n + 1;
                mr_sum = mr_sum + (cyc - mr_t0);
                if (cyc - mr_t0 > mr_max) mr_max = cyc - mr_t0;
            end
        end
        if (dut.dw_req_valid && dut.dw_req_ready) mw_t0 = cyc;
        if (dut.dw_resp) begin
            mw_n = mw_n + 1;
            mw_sum = mw_sum + (cyc - mw_t0);
            if (cyc - mw_t0 > mw_max) mw_max = cyc - mw_t0;
        end
    end

    // ---------------- Scheduler 대신 ----------------
    integer n_plan = 0, n_miss = 0, gate_err = 0;
    longint ref_stall = 0;

    task automatic plan(input integer m, output integer ent);
        @(negedge clk);
        pl_model = m[5:0];
        #1;
        while (!pl_ready) begin @(negedge clk); #1; end
        pl_valid = 1'b1;
        @(negedge clk);
        pl_valid = 1'b0;
        while (!pl_done) @(negedge clk);
        ent = pl_entry;
        n_plan = n_plan + 1;
        if (!pl_hit) n_miss = n_miss + 1;
    endtask

    task automatic prefetch(input integer tk, input bit rs_);
        while (pend[tk]) @(negedge clk);
        pf_valid = 1'b1; pf_track = tk[9:0]; pf_reset = rs_;
        #1;
        while (!pf_ready) begin @(negedge clk); #1; end
        @(negedge clk);
        pf_valid = 1'b0;
    endtask

    task automatic go(input integer v, input integer t, input integer ent);
        integer tk;
        tk = trk(v);
        @(negedge clk);
        go_valid = 1'b1; go_track = tk[9:0]; go_reset = (t == 0); go_x = xall[v * T + t]; go_entry = ent[EW-1:0];
        #1;
        while (!go_ready) begin
            if (!busy) ref_stall = ref_stall + 1;
            @(negedge clk); #1;
        end
        if (dut.ld_busy && dut.ld_entry == go_entry) gate_err = gate_err + 1;
        v_now = v; t_now = t; rows_seen = 0; sat_exp = 1'b0;
        if (tk >= N_ON_CHIP) pend[tk] = 1'b1;
        @(negedge clk);
        go_valid = 1'b0;
    endtask

    task automatic wait_done(input integer v, input integer t);
        integer w;
        w = 0;
        while (!done_seen) begin
            @(negedge clk);
            w = w + 1;
            if (w > 100000) begin
                $display("FAIL v%0d t%0d: done 없음", v, t);
                $finish;
            end
        end
        done_seen = 1'b0;
        if (rows_q != ROWS || out_q != oall[v * T + t]) begin
            if (err_out < 5) $display("FAIL v%0d t%0d: row %0d개, out_mem", v, t, rows_q);
            err_out = err_out + 1;
        end
        n_inf = n_inf + 1;
    endtask

    initial begin : main
        integer v, t, m, i, r, j, n, b, n_ddr, e;
        longint w_first, w_a, m_a;
        reg [34*256-1:0] img;
        integer bm[$], bs[$], mv[$], mt[$], mb[$], eb[$];   // Batch: 모델, 첫 추론 / 추론: vector, timestep, batch / batch의 entry

        for (i = 0; i < 65536; i = i + 1) mstate[i] = {8{32'hA5A5_5A5A}};
        for (i = 0; i < 1024; i = i + 1) pend[i] = 1'b0;
        for (m = 0; m < N_MOD; m = m + 1) n_of[m] = 0;
        $readmemh({VEC, "index.hex"}, idx);
        for (v = 0; v < N_VEC; v = v + 1) begin
            mem_of[idx[v]][n_of[idx[v]]] = v;
            n_of[idx[v]] = n_of[idx[v]] + 1;
            $readmemh($sformatf("%sv%02d_x.hex", VEC, v), xall, v * T, v * T + T - 1);
            $readmemh($sformatf("%sv%02d_e.hex", VEC, v), eall, v * T * ROWS, (v + 1) * T * ROWS - 1);
            $readmemh($sformatf("%sv%02d_o.hex", VEC, v), oall, v * T, v * T + T - 1);
        end
        for (m = 0; m < N_MOD; m = m + 1) begin
            $readmemh($sformatf("%sm%02d_w.hex", VEC, m), wall, m * 2034, m * 2034 + 2033);
            $readmemh($sformatf("%sm%02d_p.hex", VEC, m), pall, m * 46, m * 46 + 45);
            // slot = params row 46개, 그다음 word마다 beat 2개(앞 beat = word bit [255:0])
            for (b = 0; b < LD; b = b + 1)
                mslot[m * LD + b] = (b < 46) ? pall[m * 46 + b]
                                  : wall[m * 2034 + (b - 46) / 2][256 * ((b - 46) % 2) +: 256];
        end
        n_ddr = 0;
        for (v = 0; v < N_VEC; v = v + 1) if (trk(v) >= N_ON_CHIP) n_ddr = n_ddr + 1;

        // Batch 목록: 앞 timestep은 모델마다 하나, 뒤 timestep은 추론마다 하나
        for (m = 0; m < N_MOD; m = m + 1) begin
            bm.push_back(m);
            bs.push_back(mv.size());
            for (t = 0; t < TA; t = t + 1)
                for (i = 0; i < n_of[m]; i = i + 1) begin
                    mv.push_back(mem_of[m][i]); mt.push_back(t); mb.push_back(bm.size() - 1);
                end
        end
        for (t = TA; t < T; t = t + 1)
            for (m = 0; m < N_MOD; m = m + 1)
                for (i = 0; i < n_of[m]; i = i + 1) begin
                    bm.push_back(m); bs.push_back(mv.size());
                    mv.push_back(mem_of[m][i]); mt.push_back(t); mb.push_back(bm.size() - 1);
                end

        repeat (4) @(negedge clk);
        rst = 1'b0;
        // predictor: 모든 모델 N_REG = 0(다음 사용 없음) → victim은 가장 오래된 entry
        for (i = 0; i < 64; i = i + 1) begin
            cfg_we = 1'b1; cfg_addr = 11'h040 + i[10:0]; cfg_data = 16'd0;
            @(negedge clk);
        end
        cfg_we = 1'b0;

        w_first = 0; w_a = 0; m_a = 0;
        plan(bm[0], e);
        eb.push_back(e);
        prefetch(trk(mv[0]), mt[0] == 0);
        go(mv[0], mt[0], eb[0]);
        w_first = w_stall;
        for (n = 0; n < mv.size(); n = n + 1) begin
            // 추론 n이 시작됐다. Batch의 첫 추론이면 다음 batch를 계획한다(prefetch)
            if (n == bs[mb[n]] && mb[n] + 1 < bm.size()) begin
                plan(bm[mb[n] + 1], e);
                eb.push_back(e);
            end
            // 다음 추론을 준비하고, 추론 n이 연산하는 동안 go를 미리 올린다
            if (n + 1 < mv.size()) begin
                prefetch(trk(mv[n + 1]), mt[n + 1] == 0);
                if (n + 1 == bs[N_MOD]) begin w_a = w_stall - w_first; m_a = m_stall; end
                go(mv[n + 1], mt[n + 1], eb[mb[n + 1]]);
            end
            wait_done(mv[n], mt[n]);
        end

        // 마지막 되쓰기를 기다린 뒤 DDR3 내용 대조
        for (i = 0; i < 1024; i = i + 1)
            while (pend[i]) @(negedge clk);
        repeat (20) @(negedge clk);
        for (v = 0; v < N_VEC; v = v + 1)
            if (trk(v) >= N_ON_CHIP) begin
                for (i = 0; i < 34; i = i + 1) img[256*i +: 256] = mstate[trk(v) * 64 + i];
                for (r = 0; r < ROWS; r = r + 1)
                    for (j = 0; j < ((r == 44) ? 2 : 16); j = j + 1)
                        if (img[12 * (16 * r + j) +: 12] != eall[(v * T + T - 1) * ROWS + r][640 + 16*j +: 12])
                            err_ddr = err_ddr + 1;
            end

        $display("run   MODE %0d: cycle %0d, 추론 %0d (batch %0d, DDR3 트랙 %0d), row 불일치 %0d, 출력 불일치 %0d, DDR3 최종값 불일치 %0d",
                 MODE, cyc, n_inf, bm.size(), n_ddr, err_rows, err_out, err_ddr);
        $display("run   적재 %0d (miss %0d / 계획 %0d), entry 내용 불일치 %0d, weight beat %0d (기대 %0d)",
                 n_load, n_miss, n_plan, ent_bad, rbeat0, n_load * LD);
        $display("run   membrane potential beat 읽기 %0d (기대 %0d), 쓰기 %0d (기대 %0d)",
                 rbeat1, n_ddr * 30 * 34, wbeat, n_ddr * 31 * 34);
        $display("run   적재 cycle 평균 %0.1f, 최소 %0d, 최대 %0d; membrane potential 읽기 평균 %0.1f·최대 %0d, 쓰기 평균 %0.1f·최대 %0d",
                 real'(ld_sum) / n_load, ld_min, ld_max, real'(mr_sum) / mr_n, mr_max, real'(mw_sum) / mw_n, mw_max);
        $display("run   정지 cycle: stall_cyc %0d, testbench %0d; weight 대기 첫 적재 %0d, 앞 timestep(그 뒤) %0d, 뒤 timestep %0d; membrane potential 대기 앞 %0d, 뒤 %0d",
                 stall_cyc, ref_stall, w_first, w_a, w_stall - w_first - w_a, m_a, m_stall - m_a);
        $display("run   AXI 규칙 위반 %0d, 우선순위 위반 %0d, 적재 중 entry로 시작 %0d, 오류 응답 주입 %0d·보고 %0d·불일치 %0d, dma_idle %0b",
                 prot_err, prio_err, gate_err, n_inj, n_err_seen, err_mis, dma_idle);
        $display("run   16 bit 포화가 난 추론 %0d, sat16 불일치 %0d", n_sat, err_sat);
        if (err_rows == 0 && err_out == 0 && err_ddr == 0 && n_inf == N_VEC * T && ent_bad == 0
            && n_load == n_miss && rbeat0 == n_load * LD && rbeat1 == n_ddr * 30 * 34 && wbeat == n_ddr * 31 * 34
            && stall_cyc == ref_stall && w_a == 0 && prot_err == 0 && prio_err == 0 && gate_err == 0
            && err_mis == 0 && n_err_seen == n_inj && (MODE != 2 || n_inj > 0) && dma_idle && err_sat == 0)
            $display("PASS");
        else
            $display("FAIL");
        $finish;
    end

endmodule
