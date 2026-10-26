// ============================================================
// tb_membrane_storage.sv — compute_array + weight_entry + membrane_storage를 golden_l64_m12와 대조 (P4.2)
// ============================================================
// vector 82개를 트랙 82개에 둔다(on-chip 60, DDR3 22. 경계 트랙 0·767·768·1023 포함).
// timestep마다 모델 순서로 batch를 만들고, 같은 모델의 트랙 두 개를 번갈아 추론한다.
// DDR3 트랙은 앞 구성원을 연산하는 동안 다음 구성원을 준비한다. Membrane potential은 RTL이 들고 있고
// DDR3는 TB 모델이다(명령 수락·response time과 beat 간격이 무작위, 처음 내용은 쓰레기 값).
// 확인 항목:
//   - row마다 전류, 포화 후 membrane potential, spike, 12 bit 저장값, 판정용 출력이 golden과 bit 일치
//   - 트랙 분리(같은 모델 두 트랙을 번갈아 처리), 첫 timestep RESET_STATE
//   - RESET_STATE면 DDR3를 읽지 않음: 읽은 beat = DDR3 트랙 × 30 × 34, 쓴 beat = DDR3 트랙 × 31 × 34
//   - 끝난 뒤 DDR3 내용 = 마지막 timestep의 12 bit 저장값 (뉴런 n = bit [12n+11:12n])
// 실행 (저장소 루트):
//   bash hardware/testbench/run_membrane_storage.sh
// ============================================================
`timescale 1ns / 1ps

module tb_membrane_storage;

    localparam N_VEC = 82, N_MOD = 42, T = 31, ROWS = 45, CUR_W = 17, N_ON_CHIP = 768;
    localparam string VEC = "hardware/sim/compute_array/vec_m12/";
    localparam [31:0] STATE_BASE = 32'h0200_0000;

    reg clk = 1'b0;
    always #5 clk = ~clk;
    reg rst = 1'b1;

    reg          start = 1'b0, reset_state = 1'b0;
    reg  [319:0] x_in = 320'd0;
    wire         busy, done;
    wire [15:0]  out_mem0, out_mem1;
    wire         w_en;
    wire [10:0]  w_a_addr, w_b_addr;
    wire [511:0] w_a_data, w_b_data;
    wire [5:0]   p_addr;
    wire [255:0] p_data;
    wire         m_rd_en, m_wr_en;
    wire [5:0]   m_rd_row, m_wr_row;
    wire [255:0] m_rd_data, m_wr_data, dbg_mem_sat;
    wire [16*CUR_W-1:0] dbg_cur;
    wire [15:0]  dbg_spk;

    reg          ld_we = 1'b0, ld_pwe = 1'b0;
    reg  [10:0]  ld_addr = 11'd0;
    reg  [5:0]   ld_paddr = 6'd0;
    reg  [511:0] ld_din = 512'd0;
    reg  [255:0] ld_pdin = 256'd0;

    reg  [9:0]   track = 10'd0;
    wire         can_start, wb_done, pf_ready;
    wire [9:0]   wb_track;
    reg          pf_valid = 1'b0, pf_reset = 1'b0;
    reg  [9:0]   pf_track = 10'd0;
    wire         dr_req_valid, dw_req_valid, dw_valid;
    wire [31:0]  dr_req_addr, dw_req_addr;
    wire [255:0] dw_data;
    reg          dr_req_ready = 1'b0, dr_valid = 1'b0, dw_req_ready = 1'b0, dw_ready = 1'b0, dw_resp = 1'b0;
    reg  [255:0] dr_data = 256'd0;

    compute_array #(.CUR_W(CUR_W)) dut (
        .clk(clk), .rst(rst),
        .start(start), .reset_state(reset_state), .x_in(x_in),
        .busy(busy), .done(done), .out_mem0(out_mem0), .out_mem1(out_mem1),
        .w_en(w_en), .w_a_addr(w_a_addr), .w_b_addr(w_b_addr),
        .w_a_data(w_a_data), .w_b_data(w_b_data), .p_addr(p_addr), .p_data(p_data),
        .m_rd_en(m_rd_en), .m_rd_row(m_rd_row), .m_rd_data(m_rd_data),
        .m_wr_en(m_wr_en), .m_wr_row(m_wr_row), .m_wr_data(m_wr_data),
        .dbg_cur(dbg_cur), .dbg_mem_sat(dbg_mem_sat), .dbg_spk(dbg_spk)
    );

    weight_entry u_entry (
        .clk(clk),
        .a_en(w_en), .a_addr(w_a_addr), .a_dout(w_a_data),
        .b_en(w_en | ld_we), .b_we(ld_we), .b_addr(ld_we ? ld_addr : w_b_addr),
        .b_din(ld_din), .b_dout(w_b_data),
        .p_we(ld_pwe), .p_waddr(ld_paddr), .p_din(ld_pdin),
        .p_raddr(p_addr), .p_dout(p_data)
    );

    membrane_storage #(.N_ON_CHIP(N_ON_CHIP)) u_ms (
        .clk(clk), .rst(rst), .state_base(STATE_BASE),
        .track(track), .can_start(can_start), .start(start), .done(done),
        .wb_done(wb_done), .wb_track(wb_track),
        .m_rd_en(m_rd_en), .m_rd_row(m_rd_row), .m_rd_data(m_rd_data),
        .m_wr_en(m_wr_en), .m_wr_row(m_wr_row), .m_wr_data(m_wr_data),
        .pf_valid(pf_valid), .pf_track(pf_track), .pf_reset(pf_reset), .pf_ready(pf_ready),
        .dr_req_valid(dr_req_valid), .dr_req_ready(dr_req_ready), .dr_req_addr(dr_req_addr),
        .dr_valid(dr_valid), .dr_data(dr_data),
        .dw_req_valid(dw_req_valid), .dw_req_ready(dw_req_ready), .dw_req_addr(dw_req_addr),
        .dw_valid(dw_valid), .dw_ready(dw_ready), .dw_data(dw_data), .dw_resp(dw_resp)
    );

    // ---------------- DDR3 + DMA 모델 (membrane potential 영역, beat = 32 B) ----------------
    reg  [255:0] ddr [0:65535];
    integer      rs = 0, rlat = 0, rcnt = 0, ws = 0, wlat = 0, wcnt = 0;
    reg  [15:0]  ridx = 16'd0, widx = 16'd0;
    longint      rd_beats = 0, wr_beats = 0;

    always @(posedge clk) begin
        dr_req_ready <= 1'b0;
        dr_valid     <= 1'b0;
        case (rs)
        0: if (dr_req_valid && !dr_req_ready && $urandom % 3 == 0) begin
               dr_req_ready <= 1'b1;
               ridx <= 16'((dr_req_addr - STATE_BASE) >> 5);
               rlat <= 8 + $urandom % 40;
               rcnt <= 0;
               rs   <= 1;
           end
        1: if (rlat == 0) rs <= 2; else rlat <= rlat - 1;
        default: if ($urandom % 4 != 0) begin
               dr_valid <= 1'b1;
               dr_data  <= ddr[ridx];
               ridx     <= ridx + 16'd1;
               rd_beats <= rd_beats + 1;
               if (rcnt == 33) rs <= 0; else rcnt <= rcnt + 1;
           end
        endcase
    end

    always @(posedge clk) begin
        dw_req_ready <= 1'b0;
        dw_resp      <= 1'b0;
        case (ws)
        0: if (dw_req_valid && !dw_req_ready && $urandom % 3 == 0) begin
               dw_req_ready <= 1'b1;
               widx <= 16'((dw_req_addr - STATE_BASE) >> 5);
               wcnt <= 0;
               ws   <= 1;
           end
        1: begin
               dw_ready <= ($urandom % 4 != 0);
               if (dw_valid && dw_ready) begin
                   ddr[widx] <= dw_data;
                   widx      <= widx + 16'd1;
                   wr_beats  <= wr_beats + 1;
                   if (wcnt == 33) begin
                       ws       <= 2;
                       wlat     <= 5 + $urandom % 30;
                       dw_ready <= 1'b0;
                   end else
                       wcnt <= wcnt + 1;
               end
           end
        default: if (wlat == 0) begin dw_resp <= 1'b1; ws <= 0; end else wlat <= wlat - 1;
        endcase
    end

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

    integer v_now = 0, t_now = 0, rows_seen = 0, n_inf = 0, err_rows = 0, err_out = 0, err_ddr = 0;

    function automatic integer trk(input integer v);
        case (v)
        0: trk = 0;
        1: trk = 768;
        2: trk = 767;
        3: trk = 1023;
        default: trk = (v * 37 + 11) % 1024;
        endcase
    endfunction

    function automatic [255:0] store12(input [255:0] m);
        integer i, x;
        for (i = 0; i < 16; i = i + 1) begin
            x = $signed(m[16*i +: 16]);
            x = (x > 2047) ? 2047 : (x < -2048) ? -2048 : x;
            store12[16*i +: 16] = x[15:0];
        end
    endfunction

    // row 쓰기 대조
    always @(negedge clk) begin
        if (!rst && m_wr_en) begin : chk
            reg [911:0] e;
            reg [255:0] st;
            integer k, lane_n, bad;
            e = eall[(v_now * T + t_now) * ROWS + m_wr_row];
            st = store12(m_wr_data);
            lane_n = (m_wr_row == 6'd44) ? 2 : 16;
            bad = 0;
            for (k = 0; k < lane_n; k = k + 1) begin
                if ($signed(dbg_cur[CUR_W*k +: CUR_W]) != $signed(e[24*k +: 24])) bad = bad + 1;
                if (dbg_mem_sat[16*k +: 16] != e[384 + 16*k +: 16]) bad = bad + 1;
                if (st[16*k +: 16] != e[640 + 16*k +: 16]) bad = bad + 1;
                if (dbg_spk[k] != e[896 + k]) bad = bad + 1;
            end
            if (bad != 0) begin
                if (err_rows < 5)
                    $display("FAIL v%0d(트랙 %0d) t%0d row %0d: 불일치 %0d", v_now, trk(v_now), t_now, m_wr_row, bad);
                err_rows = err_rows + 1;
            end
            rows_seen = rows_seen + 1;
        end
    end

    always @(negedge clk)
        if (wb_done) pend[wb_track] = 1'b0;

    task automatic load_model(input integer m);
        integer a;
        for (a = 0; a < 2034; a = a + 1) begin
            @(negedge clk);
            ld_we = 1'b1; ld_addr = a[10:0]; ld_din = wall[m * 2034 + a];
            ld_pwe = (a < 46); ld_paddr = a[5:0]; ld_pdin = pall[m * 46 + (a < 46 ? a : 0)];
        end
        @(negedge clk);
        ld_we = 1'b0; ld_pwe = 1'b0;
    endtask

    task automatic prefetch(input integer tk, input bit rs_);
        while (pend[tk]) @(negedge clk);
        pf_valid = 1'b1; pf_track = tk[9:0]; pf_reset = rs_;
        #1;
        while (!pf_ready) begin @(negedge clk); #1; end
        @(negedge clk);
        pf_valid = 1'b0;
    endtask

    task automatic start_inf(input integer v, input integer t);
        integer tk;
        tk = trk(v);
        @(negedge clk);
        track = tk[9:0];
        #1;
        while (!(can_start && !busy)) begin @(negedge clk); #1; end
        start = 1'b1; reset_state = (t == 0); x_in = xall[v * T + t];
        v_now = v; t_now = t; rows_seen = 0;
        if (tk >= N_ON_CHIP) pend[tk] = 1'b1;
        @(negedge clk);
        start = 1'b0;
    endtask

    task automatic wait_done(input integer v, input integer t);
        integer w;
        w = 0;
        while (!done) begin
            @(negedge clk);
            w = w + 1;
            if (w > 5000) begin
                $display("FAIL v%0d t%0d: done 없음", v, t);
                $finish;
            end
        end
        if (rows_seen != ROWS || {out_mem1, out_mem0} != oall[v * T + t]) begin
            if (err_out < 5) $display("FAIL v%0d t%0d: row %0d개, out_mem", v, t, rows_seen);
            err_out = err_out + 1;
        end
        n_inf = n_inf + 1;
    endtask

    initial begin : main
        integer v, t, m, i, r, k, n_ddr, w;
        reg [34*256-1:0] img;
        for (i = 0; i < 65536; i = i + 1) ddr[i] = {8{32'hA5A5_5A5A}};
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
        end
        n_ddr = 0;
        for (v = 0; v < N_VEC; v = v + 1) if (trk(v) >= N_ON_CHIP) n_ddr = n_ddr + 1;

        repeat (4) @(negedge clk);
        rst = 1'b0;

        for (t = 0; t < T; t = t + 1)
            for (m = 0; m < N_MOD; m = m + 1) begin
                load_model(m);
                prefetch(trk(mem_of[m][0]), t == 0);
                for (i = 0; i < n_of[m]; i = i + 1) begin
                    start_inf(mem_of[m][i], t);
                    if (i + 1 < n_of[m]) prefetch(trk(mem_of[m][i + 1]), t == 0);
                    wait_done(mem_of[m][i], t);
                end
            end

        // 마지막 되쓰기를 기다린 뒤 DDR3 내용 대조
        w = 0;
        for (i = 0; i < 1024; i = i + 1)
            while (pend[i]) begin @(negedge clk); w = w + 1; end
        for (v = 0; v < N_VEC; v = v + 1)
            if (trk(v) >= N_ON_CHIP) begin
                for (i = 0; i < 34; i = i + 1) img[256*i +: 256] = ddr[trk(v) * 64 + i];
                for (r = 0; r < ROWS; r = r + 1)
                    for (k = 0; k < ((r == 44) ? 2 : 16); k = k + 1)
                        if (img[12 * (16 * r + k) +: 12] != eall[(v * T + T - 1) * ROWS + r][640 + 16*k +: 12])
                            err_ddr = err_ddr + 1;
            end

        $display("run   추론 %0d (트랙 %0d, DDR3 트랙 %0d), row 불일치 %0d, 출력 불일치 %0d, DDR3 최종값 불일치 %0d",
                 n_inf, N_VEC, n_ddr, err_rows, err_out, err_ddr);
        $display("run   DDR3 읽은 beat %0d (기대 %0d), 쓴 beat %0d (기대 %0d)",
                 rd_beats, n_ddr * 30 * 34, wr_beats, n_ddr * 31 * 34);
        if (err_rows == 0 && err_out == 0 && err_ddr == 0 && n_inf == N_VEC * T
            && rd_beats == n_ddr * 30 * 34 && wr_beats == n_ddr * 31 * 34)
            $display("PASS");
        else
            $display("FAIL");
        $finish;
    end

endmodule
