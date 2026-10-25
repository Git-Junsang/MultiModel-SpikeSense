// ============================================================
// tb_frontend.sv — frontend(ingest, req_table, track_scheduler, result)를 simulator 결정과 대조 (P4.5·P4.6)
// ============================================================
// 1) 기록 재생: export_sched_trace.py가 낸 simulator(Grouping + PNU-count) 사건을 시각 순서로 넣는다.
//    도착은 64 B 추론 요청으로 넣고, accel_core 자리의 stub이 사건 시각에 연산 시작(go_ready)과 완료(done)를 준다.
//    사건 사이에는 RTL이 결정할 시간(GAP cycle)을 둔다. 같은 시각 사건은 이어서 넣는다. now_us는 사건 시각이다.
//    확인: 교체 계획 순서·모델·그때의 모델별 queue 있음(q_ne), batch 첫 추론과 구성원·순서, go의 entry·입력·RESET_STATE,
//          go 전에 pf, predictor 도착 알림, 결과 32 B 모든 필드(batch 크기, 시각, 출력, 포화·LATE flag), drop 수,
//          DDR3 트랙 결과가 wb_done 뒤에 나옴(wb_done을 0~400 cycle 늦게 준다), ev_*·pending_n 출력.
// 2) 지정 시험: 검사 오류 1~5와 정보(범위 밖 위 bit, 받은 순번, x의 여러 byte), n_expect 포화, run = 0,
//    결과 전 같은 트랙 drop, 결과 backpressure(res_ok), 같은 cycle의 목록 추가·떼어 내기, DDR3 결과가 wb_done을 기다리는 순서.
// 실행 (저장소 루트):
//   bash hardware/testbench/run_frontend.sh
// ============================================================
`timescale 1ns / 1ps

module tb_frontend #(
    parameter int GAP = 96
);

    localparam int N_MODELS = 40, N_ONCHIP = 768, MAXE = 400000, MAXB = 200000;
    int    TID = 0;                       // 기록 번호(+TID=n)
    string DIR;
    localparam [31:0] DEADLINE = 32000, MARGIN = 31000;    // 응답이 1 ms를 넘으면 LATE

    reg clk = 1'b0;
    always #5 clk = ~clk;
    reg rst = 1'b1;
    longint cyc = 0;
    always @(posedge clk) begin
        cyc <= cyc + 1;
        if (cyc > 80_000_000) begin $display("FAIL 시간 초과"); $finish; end
    end

    // ---------------- DUT ----------------
    reg          run = 1'b1;
    reg  [10:0]  n_tracks = 11'd1024;
    reg  [5:0]   n_models = 6'd40;
    reg  [31:0]  now_us = 32'd0;
    reg          rq_valid = 1'b0;
    reg  [511:0] rq_data = '0;
    wire         rq_ready, rs_valid;
    reg          rs_ready = 1'b0;
    wire [255:0] rs_data;
    wire [N_MODELS-1:0] q_ne;
    wire         arr_valid, pl_valid, pf_valid, pf_reset, go_valid, go_reset;
    wire [5:0]   arr_model, pl_model;
    wire [31:0]  arr_t_host;
    wire [10:0]  arr_n_expect, pending_n;
    reg          pl_ready = 1'b1, pl_done = 1'b0, pl_hit = 1'b0, pf_ready = 1'b0, go_ready = 1'b0;
    reg  [1:0]   pl_entry = 2'd0;
    wire [9:0]   pf_track, go_track;
    wire [1:0]   go_entry;
    wire [319:0] go_x;
    reg          done = 1'b0, sat16 = 1'b0, wb_done = 1'b0, wb_rep = 1'b0;
    reg  [15:0]  out_mem0 = 16'd0, out_mem1 = 16'd0;
    wire         ev_req_in, ev_req_drop, ev_res_out, ev_late, ev_batch, ev_load, ev_sat, err_valid, fe_idle;
    wire [3:0]   err_code;
    wire [31:0]  err_info;

    frontend #(.N_TRACKS(1024), .N_MODELS(N_MODELS), .N_ONCHIP(N_ONCHIP), .EW(2)) dut (
        .clk(clk), .rst(rst), .run(run), .n_tracks(n_tracks), .n_models(n_models),
        .deadline_us(DEADLINE), .margin_us(MARGIN), .now_us(now_us),
        .rq_valid(rq_valid), .rq_ready(rq_ready), .rq_data(rq_data),
        .rs_valid(rs_valid), .rs_ready(rs_ready), .rs_data(rs_data),
        .q_ne(q_ne), .arr_valid(arr_valid), .arr_model(arr_model), .arr_t_host(arr_t_host), .arr_n_expect(arr_n_expect),
        .pl_valid(pl_valid), .pl_model(pl_model), .pl_ready(pl_ready), .pl_done(pl_done), .pl_entry(pl_entry), .pl_hit(pl_hit),
        .pf_valid(pf_valid), .pf_track(pf_track), .pf_reset(pf_reset), .pf_ready(pf_ready),
        .go_valid(go_valid), .go_ready(go_ready), .go_entry(go_entry), .go_track(go_track), .go_reset(go_reset), .go_x(go_x),
        .done(done), .out_mem0(out_mem0), .out_mem1(out_mem1), .sat16(sat16), .wb_done(wb_done || wb_rep),
        .ev_req_in(ev_req_in), .ev_req_drop(ev_req_drop), .ev_res_out(ev_res_out), .ev_late(ev_late), .ev_batch(ev_batch),
        .ev_load(ev_load), .ev_sat(ev_sat), .pending_n(pending_n),
        .err_valid(err_valid), .err_code(err_code), .err_info(err_info), .idle(fe_idle)
    );

    // ---------------- 기록 ----------------
    reg [31:0]  nn [0:1];
    reg [255:0] ev [0:MAXE-1];
    reg [127:0] bt [0:MAXB-1];

    // 추론 요청 i의 x: byte b = (7i + 13b + 5) & 0x7F
    function automatic [319:0] xval(input longint i);
        for (int b = 0; b < 40; b++) xval[8*b +: 8] = 8'((i * 7 + b * 13 + 5) & 64'h7F);
    endfunction

    function automatic [511:0] mkreq(input [7:0] magic, input rs, input [15:0] trk, input [15:0] seq, input [7:0] mdl,
                                     input [31:0] th, input [31:0] nexp, input [319:0] x);
        mkreq = '0;
        mkreq[7:0] = magic; mkreq[8] = rs; mkreq[31:16] = trk; mkreq[47:32] = seq; mkreq[55:48] = mdl;
        mkreq[95:64] = th; mkreq[127:96] = nexp; mkreq[447:128] = x;
    endfunction

    // ---------------- 검사 계수 ----------------
    int err_plan = 0, err_qne = 0, err_go = 0, err_pf = 0, err_arr = 0, err_res = 0, err_misc = 0;
    int n_plan = 0, n_start = 0, n_res = 0, n_arr = 0, n_drop = 0, n_late = 0, n_sat = 0, n_batch_ev = 0, n_load_ev = 0;
    int exp_drop = 0;
    bit replaying = 1'b1;

    task automatic fail(input string s, ref int cnt);
        if (cnt < 5) $display("FAIL %s (cycle %0d)", s, cyc);
        cnt++;
    endtask

    // 교체 계획 stub: 계획 k는 batch k. 1~20 cycle 뒤 pl_done
    int pend_done = -1;
    always @(posedge clk) begin
        pl_done <= 1'b0;
        if (rst) begin pl_ready <= 1'b1; pend_done = -1; end
        else begin
            if (pl_valid && pl_ready) begin
                pl_hit <= 1'b1;
                if (replaying && n_plan < nn[1]) begin
                    if (pl_model != bt[n_plan][127:120]) fail($sformatf("계획 %0d 모델 %0d, 기대 %0d", n_plan, pl_model, bt[n_plan][127:120]), err_plan);
                    if (q_ne != bt[n_plan][102:63]) fail($sformatf("계획 %0d q_ne %010h, 기대 %010h", n_plan, q_ne, bt[n_plan][102:63]), err_qne);
                    pl_hit   <= bt[n_plan][119];
                end
                pl_entry <= 2'(n_plan % 4);
                n_plan++;
                pl_ready <= 1'b0;
                pend_done = 1 + $urandom % 20;
            end else if (pend_done > 0)
                pend_done--;
            else if (pend_done == 0) begin
                pl_done  <= 1'b1;
                pl_ready <= 1'b1;
                pend_done = -1;
            end
        end
    end

    // pf stub: 무작위로 받고 트랙마다 기록
    bit pf_ok [0:1023];
    bit pf_rs [0:1023];
    always @(posedge clk) begin
        if (pf_valid && pf_ready) begin pf_ok[pf_track] = 1'b1; pf_rs[pf_track] = pf_reset; end
        pf_ready <= ($urandom % 2 == 0);
    end

    int n_in_ev = 0, n_out_ev = 0, n_late_ev = 0, n_sat_ev = 0, last_ne = 0;
    always @(posedge clk) if (!rst) begin
        if (arr_valid) begin n_arr++; last_ne = arr_n_expect; end
        if (ev_req_drop) n_drop++;
        if (ev_batch) n_batch_ev++;
        if (ev_load) n_load_ev++;
        if (ev_req_in) n_in_ev++;
        if (ev_res_out) n_out_ev++;
        if (ev_late) n_late_ev++;
        if (ev_sat) n_sat_ev++;
    end

    // 재생의 되쓰기 응답: DDR3 트랙 완료마다 0~400 cycle 늦게, 완료 순서대로
    longint wb_due [$];
    int     wb_trk [$];
    bit     wb_seen [0:1023];
    longint wb_last = 0;
    always @(posedge clk) begin
        wb_rep <= 1'b0;
        if (wb_due.size() > 0 && cyc >= wb_due[0]) begin
            wb_rep <= 1'b1;
            wb_seen[wb_trk[0]] = 1'b1;
            void'(wb_due.pop_front());
            void'(wb_trk.pop_front());
        end
    end

    // ---------------- 결과 대조 ----------------
    typedef struct packed {
        logic [15:0] trk, seq; logic [7:0] mdl, flags; logic [15:0] bn;
        logic [31:0] th, tin, tst, tdn; logic [15:0] o0, o1;
    } res_t;
    res_t   rq_exp [$];
    int     res_pend [0:1023];               // 트랙마다 아직 안 나간 결과 수(되쓰기 응답 대기 포함)
    reg [255:0] got [$];
    bit     rs_rand = 1'b1;
    always @(posedge clk) begin
        if (rs_valid && rs_ready && !replaying) got.push_back(rs_data);
        if (rs_valid && rs_ready && replaying) begin
            res_t e;
            n_res++;
            if (rq_exp.size() == 0) fail("기대하지 않은 결과", err_res);
            else begin
                e = rq_exp.pop_front();
                res_pend[e.trk]--;
                if (e.trk >= N_ONCHIP) begin
                    if (!wb_seen[e.trk]) fail($sformatf("트랙 %0d: wb_done 전에 결과", e.trk), err_res);
                    wb_seen[e.trk] = 1'b0;
                end
                if (rs_data != {32'd0, e.o1, e.o0, e.tdn, e.tst, e.tin, e.th, e.bn, e.flags, e.mdl, e.seq, e.trk})
                    fail($sformatf("결과 트랙 %0d: %064h, 기대 trk %0d seq %0d bn %0d flags %0h tst %0d tdn %0d",
                                   e.trk, rs_data, e.trk, e.seq, e.bn, e.flags, e.tst, e.tdn), err_res);
                if (e.flags[2]) n_late++;
                if (e.flags[1]) n_sat++;
            end
        end
        rs_ready <= rs_rand ? ($urandom % 4 != 0) : 1'b0;
    end

    // ---------------- 재생 ----------------
    longint t_in_of [0:1023];          // 트랙의 대기 추론 요청 정보
    longint idx_of  [0:1023];
    bit     rs_of   [0:1023];
    longint th_of   [0:1023];
    int     seq_of  [0:1023];
    int     mdl_of  [0:1023];
    longint tst_of  [0:1023];
    int     bn_of   [0:1023];
    int     cur_b = -1, cur_size = 0;
    int     run_trk = -1;
    int     q_model = 0, err_pend = 0, n_miss_bt = 0;

    task automatic step(input int n);
        repeat (n) @(negedge clk);
    endtask

    int n_sent = 0;                          // rst 뒤 보낸 추론 요청 수 = ingest의 받은 순번
    task automatic send_req(input [511:0] d);
        n_sent++;
        @(negedge clk);
        rq_valid = 1'b1; rq_data = d;
        #1;
        while (!rq_ready) begin @(negedge clk); #1; end
        @(negedge clk);
        rq_valid = 1'b0;
    endtask

    task automatic do_arr(input [255:0] e);
        longint i = e[221:190];
        int tr = e[189:180];
        int arr0, drop0, w = 0;
        // simulator는 연산 완료로 drop을 판정하고 RTL은 결과를 보낸 뒤 칸을 비운다. 재생은 사건 순서만 지키므로 그 사이 cycle을 준다
        while (!e[50] && res_pend[tr] != 0) begin step(1); if (++w > 5000) begin fail($sformatf("트랙 %0d 결과가 안 나감", tr), err_misc); break; end end
        arr0 = n_arr; drop0 = n_drop;
        send_req(mkreq(8'hA5, e[125], 16'(tr), e[141:126], 8'(e[179:174]), e[173:142], {16'd0, e[124:109]}, xval(i)));
        step(4);
        if (e[50]) begin
            exp_drop++;
            if (n_drop != drop0 + 1) fail($sformatf("추론 요청 %0d: drop 기대", i), err_arr);
        end else begin
            if (n_arr != arr0 + 1 || arr_model != e[179:174] || arr_t_host != e[173:142]
                || arr_n_expect != ((e[124:109] > 2047) ? 11'd2047 : 11'(e[124:109])))
                fail($sformatf("추론 요청 %0d: predictor 도착 알림", i), err_arr);
            q_model++;
            t_in_of[tr] = now_us; idx_of[tr] = i; rs_of[tr] = e[125]; th_of[tr] = e[173:142];
            seq_of[tr] = e[141:126]; mdl_of[tr] = e[179:174];
        end
    endtask

    task automatic do_start(input [255:0] e);
        longint i = e[221:190];
        int tr = e[189:180], b = e[108:93], w;
        if (e[92]) begin cur_b = b; cur_size = bt[b][118:103]; q_model -= cur_size; end
        w = 0;
        @(negedge clk); #1;
        while (!(go_valid && go_track == tr)) begin
            if (go_valid && go_track != tr && w == 300) fail($sformatf("batch %0d 시작: go 트랙 %0d, 기대 %0d", b, go_track, tr), err_go);
            @(negedge clk); #1;
            if (++w > 2000) begin fail($sformatf("batch %0d 트랙 %0d: go 없음", b, tr), err_go); $finish; end
        end
        if (go_entry != 2'(b % 4) || go_reset != rs_of[tr] || go_x != xval(i))
            fail($sformatf("batch %0d 트랙 %0d: go entry·입력·RESET_STATE", b, tr), err_go);
        if (!pf_ok[tr] || pf_rs[tr] != rs_of[tr]) fail($sformatf("트랙 %0d: go 전에 pf 없음", tr), err_pf);
        pf_ok[tr] = 1'b0;
        go_ready = 1'b1;
        @(negedge clk);
        go_ready = 1'b0;
        n_start++;
        run_trk = tr; tst_of[tr] = now_us; bn_of[tr] = cur_size;
    endtask

    task automatic do_done(input [255:0] e);
        longint i = e[221:190];
        int tr = e[189:180];
        res_t r;
        logic [31:0] lim;
        logic sat;
        if (tr != run_trk) fail($sformatf("완료 트랙 %0d, 연산 중 %0d", tr, run_trk), err_misc);
        sat = (i % 7 == 0);
        @(negedge clk);
        done = 1'b1; out_mem0 = 16'(i); out_mem1 = ~16'(i); sat16 = sat;
        @(negedge clk);
        done = 1'b0;
        lim = th_of[tr] + DEADLINE - MARGIN;
        r.trk = 16'(tr); r.seq = 16'(seq_of[tr]); r.mdl = 8'(mdl_of[tr]); r.bn = 16'(bn_of[tr]);
        r.th = th_of[tr]; r.tin = t_in_of[tr]; r.tst = tst_of[tr]; r.tdn = now_us; r.o0 = 16'(i); r.o1 = ~16'(i);
        r.flags = {5'd0, ($signed(now_us - lim) > 0), sat, rs_of[tr]};
        rq_exp.push_back(r);
        res_pend[tr]++;
        if (tr >= N_ONCHIP) begin
            wb_last = (cyc + 2 + $urandom % 400 > wb_last + 1) ? cyc + 2 + $urandom % 400 : wb_last + 1;
            wb_due.push_back(wb_last);
            wb_trk.push_back(tr);
        end
    endtask

    task automatic replay();
        int k;
        reg [255:0] e;
        $readmemh({DIR, "n.hex"}, nn);
        $readmemh({DIR, "ev.hex"}, ev, 0, nn[0] - 1);
        $readmemh({DIR, "batch.hex"}, bt, 0, nn[1] - 1);
        for (k = 0; k < nn[0]; k++) begin
            e = ev[k];
            now_us = e[253:222];
            case (e[255:254])
            2'd1: do_arr(e);
            2'd2: do_start(e);
            default: do_done(e);
            endcase
            if (e[49] && e[255:254] == 2'd1 && ev[k + 1][255:254] == 2'd1)
                ;                                            // 시각이 정확히 같은 도착은 이어서 넣는다
            else begin
                step(GAP);
                if (pending_n != 11'(q_model)) fail($sformatf("사건 %0d: pending_n %0d, 기대 %0d", k, pending_n, q_model), err_pend);
            end
        end
        for (k = 0; k < nn[1]; k++) if (!bt[k][119]) n_miss_bt++;
        step(200);
        while (rq_exp.size() != 0 || wb_due.size() != 0) step(10);
        step(20);
        $display("run   재생 t%0d: 사건 %0d, batch %0d(시작 이벤트 %0d), 추론 시작 %0d, 결과 %0d, 계획 %0d(miss %0d), drop %0d(기대 %0d)",
                 TID, nn[0], nn[1], n_batch_ev, n_start, n_res, n_plan, n_load_ev, n_drop, exp_drop);
        $display("run   불일치: 계획 모델 %0d, q_ne %0d, go %0d, pf %0d, 도착 알림 %0d, 결과 %0d, pending_n %0d, 기타 %0d; LATE %0d, 포화 %0d, idle %0b",
                 err_plan, err_qne, err_go, err_pf, err_arr, err_res, err_pend, err_misc, n_late, n_sat, fe_idle);
        $display("run   사건 출력: req_in %0d(기대 %0d), res_out %0d(%0d), late %0d(%0d), sat %0d(%0d), load %0d(%0d)",
                 n_in_ev, n_arr, n_out_ev, n_res, n_late_ev, n_late, n_sat_ev, n_sat, n_load_ev, n_miss_bt);
        if (n_plan != nn[1] || n_batch_ev != nn[1] || n_drop != exp_drop || !fe_idle || n_in_ev != n_arr || n_out_ev != n_res
            || n_late_ev != n_late || n_sat_ev != n_sat || n_load_ev != n_miss_bt) err_misc++;
    endtask

    // ---------------- 지정 시험 ----------------
    // auto_go = 1이면 stub이 go를 본 2 cycle 뒤 go_ready를 주고, 실제 handshake 뒤 LAT cycle에 done(DDR3 트랙은 2 cycle 뒤 wb_done)을 낸다
    int  d_err = 0, LAT = 40, n_go = 0;
    bit  auto_go = 1'b0;
    int  st = 0, cnt = 0, trk = 0;
    always @(posedge clk) if (auto_go && !rst) begin : auto_stub
        go_ready <= 1'b0; done <= 1'b0; wb_done <= 1'b0;
        case (st)
        0: if (go_valid) begin cnt = 2; st = 1; end
        1: if (cnt != 0) cnt--;
           else if (go_valid) begin go_ready <= 1'b1; st = 4; end
           else st = 0;
        4: if (go_valid) begin trk = go_track; n_go++; cnt = LAT; st = 2; end     // go_ready가 1인 cycle의 handshake
           else st = 0;
        2: if (cnt == 0) begin done <= 1'b1; out_mem0 <= 16'(trk); out_mem1 <= 16'(trk + 1); sat16 <= 1'b0;
                               cnt = 2; st = (trk >= N_ONCHIP) ? 3 : 0; end else cnt--;
        default: if (cnt == 0) begin wb_done <= 1'b1; st = 0; end else cnt--;
        endcase
    end

    task automatic dfail(input string s);
        $display("FAIL 지정 시험: %s", s);
        d_err++;
    endtask

    // 오류 하나를 기대하고 추론 요청을 보낸다(code 0 = 오류 없이 drop)
    task automatic send_expect(input [511:0] d, input [3:0] code, input [31:0] info, input string what);
        int seen = 0, drop0 = n_drop, arr0 = n_arr;
        logic [3:0] c = 0; logic [31:0] inf = 0;
        fork
            begin send_req(d); step(4); end
            begin repeat (8) begin @(posedge clk); if (err_valid) begin seen++; c = err_code; inf = err_info; end end end
        join
        if (seen != (code != 0) || (code != 0 && (c != code || inf != info)) || n_drop != drop0 + 1 || n_arr != arr0)
            dfail($sformatf("%s: 오류 %0d번 code %0d info %0d, drop %0d, 도착 알림 %0d", what, seen, c, inf, n_drop - drop0, n_arr - arr0));
    endtask

    task automatic wait_idle(input string what);
        int w = 0;
        while (!fe_idle) begin step(1); if (++w > 20000) begin dfail({what, ": idle 안 됨"}); return; end end
    endtask

    task automatic directed();
        int s0, k;
        reg [255:0] r;
        replaying = 1'b0;
        rst = 1'b1; step(4); rst = 1'b0; step(4);
        now_us = 32'd100;
        got.delete();
        n_sent = 0;

        // 1) 검사 오류. 받은 순번은 rst 뒤 0부터
        n_tracks = 11'd1000;
        send_expect(mkreq(8'hA4, 0, 16'd5, 0, 8'd1, 0, 0, xval(1)), 4'd1, 32'd0, "magic");
        send_expect(mkreq(8'hA5, 0, 16'd1000, 0, 8'd1, 0, 0, xval(1)), 4'd2, 32'd1000, "track_id");
        send_expect(mkreq(8'hA5, 0, 16'd7, 0, 8'd40, 0, 0, xval(1)), 4'd3, 32'd7, "model_id");
        send_expect(mkreq(8'hA5, 0, 16'd8, 0, 8'd2, 0, 0, xval(1) | (320'h80 << 64)), 4'd4, 32'd8, "x > 127");
        send_expect(mkreq(8'hA5, 0, 16'h8005, 0, 8'd1, 0, 0, xval(1)), 4'd2, 32'h8005, "track_id 위 bit");
        send_expect(mkreq(8'hA5, 0, 16'd7, 0, 8'h45, 0, 0, xval(1)), 4'd3, 32'd7, "model_id 위 bit");
        send_expect(mkreq(8'hA5, 0, 16'd8, 0, 8'd2, 0, 0, xval(1) | 320'h80), 4'd4, 32'd8, "x byte 0 > 127");
        send_expect(mkreq(8'hA5, 0, 16'd8, 0, 8'd2, 0, 0, xval(1) | (320'hFF << 312)), 4'd4, 32'd8, "x byte 39 > 127");
        s0 = n_sent;
        send_expect(mkreq(8'h00, 0, 16'd5, 0, 8'd1, 0, 0, xval(1)), 4'd1, 32'(s0), "magic 받은 순번");
        n_tracks = 11'd1024;
        run = 1'b0;
        send_expect(mkreq(8'hA5, 0, 16'd11, 0, 8'd4, 0, 0, xval(11)), 4'd0, 32'd0, "run 0");
        run = 1'b1;
        // 같은 트랙이 결과 전이면 drop(5). 결과를 보낸 뒤에는 받는다
        auto_go = 1'b1;
        send_req(mkreq(8'hA5, 1, 16'd9, 16'd1, 8'd3, 32'd50, 32'd1, xval(9)));
        step(4);
        send_expect(mkreq(8'hA5, 0, 16'd9, 16'd2, 8'd3, 32'd60, 32'd1, xval(10)), 4'd5, 32'd9, "같은 트랙");
        wait_idle("drop 뒤");
        s0 = n_arr;
        send_req(mkreq(8'hA5, 0, 16'd9, 16'd3, 8'd3, 32'd70, 32'd1, xval(12)));
        step(4);
        if (n_arr != s0 + 1) dfail("결과를 보낸 트랙의 다음 추론 요청을 받지 않음");
        wait_idle("drop 다음");
        // n_expect는 11 bit로 포화
        for (k = 0; k < 4; k++) begin
            s0 = (k == 0) ? 5000 : (k == 1) ? 2048 : (k == 2) ? 2047 : 100;
            send_req(mkreq(8'hA5, 0, 16'(40 + k), 0, 8'(10 + k), 32'd80, 32'(s0), xval(40 + k)));
            step(4);
            if (last_ne != ((s0 > 2047) ? 2047 : s0)) dfail($sformatf("n_expect %0d → %0d", s0, last_ne));
        end
        wait_idle("n_expect");
        $display("run   지정 시험 1: 검사 오류 1~5, run 0, 결과 뒤 다시 받기. 불일치 %0d", d_err);

        // 2) 결과 backpressure: rs_ready = 0이면 완료 3개까지만 연산하고 멈춘다. 풀면 6개 모두 순서대로
        got.delete();
        rs_rand = 1'b0;
        s0 = n_go;
        for (k = 0; k < 6; k++) send_req(mkreq(8'hA5, 0, 16'(100 + k), 16'(k), 8'd5, 32'd200, 32'd6, xval(100 + k)));
        step(2000);
        if (n_go - s0 != 3) dfail($sformatf("결과를 못 보낼 때 시작한 추론 %0d개(기대 3)", n_go - s0));
        rs_rand = 1'b1;
        wait_idle("backpressure");
        if (got.size() != 6) dfail($sformatf("결과 %0d개", got.size()));
        else for (k = 0; k < 6; k++) begin
            r = got[k];
            if (r[15:0] != 16'(100 + k) || r[63:48] != 16'd6 || r[207:192] != 16'(100 + k)) dfail($sformatf("backpressure 결과 %0d", k));
        end
        $display("run   지정 시험 2: 결과 backpressure. 불일치 %0d", d_err);

        // 3) batch 시작 cycle에 같은 모델 추론 요청이 들어오면 다음 batch로 간다
        auto_go = 1'b0;
        got.delete();
        send_req(mkreq(8'hA5, 0, 16'd800, 16'd0, 8'd7, 32'd300, 32'd2, xval(800)));   // DDR3 트랙
        k = 0;
        while (!go_valid) begin step(1); if (++k > 1000) break; end
        @(negedge clk); rq_valid = 1'b1; rq_data = mkreq(8'hA5, 0, 16'd801, 16'd0, 8'd7, 32'd300, 32'd2, xval(801));
        @(negedge clk); rq_valid = 1'b0;
        @(negedge clk); go_ready = 1'b1;
        #1;
        if (!(dut.dt_valid && dut.ap_valid && dut.ap_model == dut.dt_model)) dfail("같은 cycle 추가·떼어 내기를 만들지 못함");
        @(negedge clk); go_ready = 1'b0;
        step(20);
        @(negedge clk); done = 1'b1; out_mem0 = 16'd800; @(negedge clk); done = 1'b0;
        step(3); @(negedge clk); wb_done = 1'b1; @(negedge clk); wb_done = 1'b0;
        auto_go = 1'b1;
        wait_idle("같은 cycle");
        if (got.size() != 2 || got[0][15:0] != 16'd800 || got[0][63:48] != 16'd1 || got[1][15:0] != 16'd801 || got[1][63:48] != 16'd1)
            dfail("같은 cycle에 들어온 추론 요청이 다음 batch로 가지 않음");
        $display("run   지정 시험 3: batch 시작 cycle의 같은 모델 도착. 불일치 %0d", d_err);

        // 4) 연산은 끝났지만 결과를 아직 못 보낸 트랙의 다음 추론 요청은 drop(5). 결과를 보낸 뒤에는 받는다
        rs_rand = 1'b0;
        for (k = 0; k < 2; k++) begin : drop_after_done
            int tk;
            tk = (k == 0) ? 20 : 850;                           // on-chip, DDR3
            s0 = n_go;
            send_req(mkreq(8'hA5, 0, 16'(tk), 16'd0, 8'd6, 32'd400, 32'd1, xval(tk)));
            while (n_go == s0) step(1);
            step(LAT + 10);
            send_expect(mkreq(8'hA5, 0, 16'(tk), 16'd1, 8'd6, 32'd410, 32'd1, xval(tk + 1)), 4'd5, 32'(tk), "연산 뒤 결과 전");
            rs_rand = 1'b1;
            wait_idle("연산 뒤 결과 전");
            s0 = n_arr;
            send_req(mkreq(8'hA5, 0, 16'(tk), 16'd2, 8'd6, 32'd420, 32'd1, xval(tk + 2)));
            step(4);
            if (n_arr != s0 + 1) dfail("결과를 보낸 뒤 같은 트랙을 받지 않음");
            wait_idle("결과 뒤");
            rs_rand = 1'b0;
        end
        rs_rand = 1'b1;
        $display("run   지정 시험 4: 연산 뒤 결과 전 같은 트랙 drop. 불일치 %0d", d_err);

        // 5) DDR3 트랙 결과는 wb_done까지 기다리고, 뒤의 on-chip 결과도 그 뒤에 순서대로 나온다
        auto_go = 1'b0;
        got.delete();
        send_req(mkreq(8'hA5, 0, 16'd860, 16'd0, 8'd9, 32'd500, 32'd2, xval(860)));
        send_req(mkreq(8'hA5, 0, 16'd31, 16'd0, 8'd9, 32'd500, 32'd2, xval(31)));
        for (k = 0; k < 2; k++) begin
            s0 = 0;
            while (!go_valid) begin step(1); if (++s0 > 2000) break; end
            @(negedge clk); go_ready = 1'b1; @(negedge clk); go_ready = 1'b0;
            step(LAT);
            @(negedge clk); done = 1'b1; out_mem0 = (k == 0) ? 16'd860 : 16'd31; @(negedge clk); done = 1'b0;
        end
        step(60);
        if (got.size() != 0) dfail("wb_done 전에 결과가 나옴");
        @(negedge clk); wb_done = 1'b1; @(negedge clk); wb_done = 1'b0;
        wait_idle("DDR3 결과 순서");
        if (got.size() != 2 || got[0][15:0] != 16'd860 || got[1][15:0] != 16'd31 || got[0][63:48] != 16'd2 || got[0][207:192] != 16'd860)
            dfail("wb_done 뒤 결과 순서");
        $display("run   지정 시험 5: DDR3 결과가 wb_done을 기다림. 불일치 %0d", d_err);
        auto_go = 1'b0;
    endtask

    initial begin : main
        rs_rand = 1'b1;
        void'($value$plusargs("TID=%d", TID));
        DIR = $sformatf("hardware/sim/frontend/t%0d/", TID);
        repeat (4) @(negedge clk);
        rst = 1'b0;
        step(4);
        replay();
        directed();
        if (err_plan || err_qne || err_go || err_pf || err_arr || err_res || err_pend || err_misc || n_res != n_start || d_err)
            $display("FAIL");
        else
            $display("PASS");
        $finish;
    end

endmodule
