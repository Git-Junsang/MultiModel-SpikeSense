// ============================================================
// tb_weight_cache.sv — weight_cache + next_use_predictor를 engine.PNURTL 기록과 대조 (P4.3)
// ============================================================
// 1) entry 경로: 빈 entry E개에 모델을 적재하며 entry마다 다른 값을 쓰고, cmp_entry로 port A·B·params를 읽어 확인한다.
// 2) 재생: export_pnu_trace.py가 낸 simulator 실행(도착, 교체 계획, 그때의 queue)을 시각 순서로 넣는다.
//    사건 한 줄 = {kind[143:140], now[139:108], model[107:100], t_host[99:68], n_expect[67:52], exp[51:48], victim[47:40], q_ne[39:0]}
//    교체 계획마다 RTL의 결정(hit / 빈 entry / 내보냄, victim 모델)이 simulator와 같은지 본다.
//    내보낸 entry가 직전 계획의 entry(연산 중)가 아닌지도 본다. 적재는 바로 끝난 것으로 둔다.
// 실행 (저장소 루트):
//   bash hardware/testbench/run_weight_cache.sh
// ============================================================
`timescale 1ns / 1ps

module tb_weight_cache #(
    parameter int E   = 4,
    parameter int TID = 0
);

    localparam int N_MODELS = 40, EW = $clog2(E), MAXC = 4096, MAXE = 262144;
    localparam string DIR = $sformatf("hardware/sim/weight_cache/t%0d/", TID);

    reg clk = 1'b0;
    always #5 clk = ~clk;
    reg rst = 1'b1;

    reg  [31:0]  now_us = 32'd0;
    wire [14:0]  phase_us = now_us % 32000;
    wire [15:0]  period = 16'(now_us / 32000);
    wire         first_period = (now_us < 32000);
    reg          cfg_we = 1'b0;
    reg  [10:0]  cfg_addr = 11'd0;
    reg  [15:0]  cfg_data = 16'd0;
    reg          arr_valid = 1'b0;
    reg  [5:0]   arr_model = 6'd0;
    reg  [31:0]  arr_t_host = 32'd0;
    reg  [10:0]  arr_n_expect = 11'd0;
    reg  [N_MODELS-1:0] q_ne = '0;
    reg          pl_valid = 1'b0;
    reg  [5:0]   pl_model = 6'd0;
    wire         pl_ready, pl_done, pl_hit, pl_evict, ld_busy;
    wire [EW-1:0] pl_entry, ld_entry;
    wire [5:0]   pl_victim, ld_model;
    reg          ld_done = 1'b0;
    reg          wr_we = 1'b0, wr_pwe = 1'b0;
    reg  [10:0]  wr_addr = 11'd0;
    reg  [511:0] wr_data = '0;
    reg  [5:0]   wr_paddr = 6'd0;
    reg  [255:0] wr_pdata = '0;
    reg  [EW-1:0] cmp_entry = '0;
    reg          w_en = 1'b0;
    reg  [10:0]  w_a_addr = 11'd0, w_b_addr = 11'd0;
    wire [511:0] w_a_data, w_b_data;
    reg  [5:0]   p_addr = 6'd0;
    wire [255:0] p_data;

    weight_cache #(.E(E), .N_MODELS(N_MODELS)) dut (
        .clk(clk), .rst(rst),
        .now_us(now_us), .phase_us(phase_us), .period(period), .first_period(first_period),
        .cfg_we(cfg_we), .cfg_addr(cfg_addr), .cfg_data(cfg_data),
        .arr_valid(arr_valid), .arr_model(arr_model), .arr_t_host(arr_t_host), .arr_n_expect(arr_n_expect),
        .q_ne(q_ne),
        .pl_valid(pl_valid), .pl_model(pl_model), .pl_ready(pl_ready), .pl_done(pl_done),
        .pl_entry(pl_entry), .pl_hit(pl_hit), .pl_evict(pl_evict), .pl_victim(pl_victim),
        .ld_busy(ld_busy), .ld_entry(ld_entry), .ld_model(ld_model), .ld_done(ld_done),
        .wr_we(wr_we), .wr_addr(wr_addr), .wr_data(wr_data), .wr_pwe(wr_pwe), .wr_paddr(wr_paddr), .wr_pdata(wr_pdata),
        .cmp_entry(cmp_entry), .w_en(w_en), .w_a_addr(w_a_addr), .w_b_addr(w_b_addr),
        .w_a_data(w_a_data), .w_b_data(w_b_data), .p_addr(p_addr), .p_data(p_data)
    );

    reg [31:0]  nn  [0:1];
    reg [31:0]  cfg [0:MAXC-1];
    reg [143:0] ev  [0:MAXE-1];
    integer err_path = 0, err_dec = 0, err_prot = 0, n_plan = 0, n_hit = 0, n_fill = 0, n_ev = 0, n_arr = 0;

    // 계획 하나: 받을 때까지 기다리고 결과를 돌려준다
    task automatic plan(input [5:0] m, output bit hit, output bit evict, output [5:0] vic, output [EW-1:0] ent);
        @(negedge clk);
        pl_model = m;
        #1;
        while (!pl_ready) begin @(negedge clk); #1; end
        pl_valid = 1'b1;
        @(negedge clk);
        pl_valid = 1'b0;
        while (!pl_done) @(negedge clk);
        hit = pl_hit; evict = pl_evict; vic = pl_victim; ent = pl_entry;
        if (!hit) begin
            ld_done = 1'b1;
            @(negedge clk);
            ld_done = 1'b0;
        end
    endtask

    initial begin : main
        integer i, k;
        bit hit, evict;
        reg [5:0] vic;
        reg [EW-1:0] ent, ents [0:E-1], prev;
        reg [143:0] x;
        bit have_prev;

        // ---------------- 1) Entry 경로 ----------------
        repeat (4) @(negedge clk);
        rst = 1'b0;
        for (i = 0; i < E; i = i + 1) begin
            pl_model = i[5:0];
            @(negedge clk);
            pl_valid = 1'b1;
            @(negedge clk);
            pl_valid = 1'b0;
            while (!pl_done) @(negedge clk);
            ents[i] = pl_entry;
            if (pl_hit || pl_evict || !ld_busy || ld_entry != pl_entry) err_path = err_path + 1;
            wr_we = 1'b1; wr_addr = 11'd7; wr_data = {64{8'(i + 1)}};
            wr_pwe = 1'b1; wr_paddr = 6'd3; wr_pdata = {32{8'(i + 9)}};
            @(negedge clk);
            wr_we = 1'b0; wr_pwe = 1'b0;
            ld_done = 1'b1;
            @(negedge clk);
            ld_done = 1'b0;
        end
        for (i = 0; i < E; i = i + 1) begin
            cmp_entry = ents[i]; w_en = 1'b1; w_a_addr = 11'd7; w_b_addr = 11'd7; p_addr = 6'd3;
            repeat (3) @(negedge clk);
            if (w_a_data != {64{8'(i + 1)}} || w_b_data != {64{8'(i + 1)}} || p_data != {32{8'(i + 9)}})
                err_path = err_path + 1;
        end
        w_en = 1'b0;
        $display("run   entry 경로: entry %0d개, 불일치 %0d", E, err_path);

        // ---------------- 2) 재생 ----------------
        rst = 1'b1;
        $readmemh({DIR, "n.hex"}, nn);
        $readmemh({DIR, "cfg.hex"}, cfg, 0, nn[0] - 1);
        $readmemh({DIR, "ev.hex"}, ev, 0, nn[1] - 1);
        repeat (2) @(negedge clk);
        rst = 1'b0;
        for (i = 0; i < nn[0]; i = i + 1) begin
            cfg_we = 1'b1; cfg_addr = cfg[i][26:16]; cfg_data = cfg[i][15:0];
            @(negedge clk);
        end
        cfg_we = 1'b0;
        have_prev = 1'b0;
        for (k = 0; k < nn[1]; k = k + 1) begin
            x = ev[k];
            now_us = x[139:108];
            if (x[143:140] == 4'd1) begin
                arr_valid = 1'b1; arr_model = x[105:100]; arr_t_host = x[99:68]; arr_n_expect = x[62:52];
                @(negedge clk);
                arr_valid = 1'b0;
                n_arr = n_arr + 1;
            end else begin
                q_ne = x[39:0];
                plan(x[105:100], hit, evict, vic, ent);
                n_plan = n_plan + 1;
                case (x[51:48])
                4'd0: begin n_hit = n_hit + 1; if (!hit) err_dec = err_dec + 1; end
                4'd1: begin n_fill = n_fill + 1; if (hit || evict) err_dec = err_dec + 1; end
                default: begin
                    n_ev = n_ev + 1;
                    if (hit || !evict || vic != x[45:40]) begin
                        if (err_dec < 5)
                            $display("FAIL 사건 %0d (%0d µs): 모델 %0d, RTL hit %0b evict %0b victim %0d, 기대 victim %0d",
                                     k, now_us, x[105:100], hit, evict, vic, x[45:40]);
                        err_dec = err_dec + 1;
                    end
                    if (have_prev && ent == prev) err_prot = err_prot + 1;
                end
                endcase
                prev = ent;
                have_prev = 1'b1;
            end
        end
        $display("run   재생 t%0d: 도착 %0d, 계획 %0d (hit %0d, 빈 entry %0d, 내보냄 %0d)", TID, n_arr, n_plan, n_hit, n_fill, n_ev);
        $display("run   결정 불일치 %0d, 연산 중 entry를 내보냄 %0d", err_dec, err_prot);
        if (err_path == 0 && err_dec == 0 && err_prot == 0 && n_plan > 0) $display("PASS"); else $display("FAIL");
        $finish;
    end

endmodule
