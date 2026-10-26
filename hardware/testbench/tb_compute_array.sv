// ============================================================
// tb_compute_array.sv — compute_array + weight_entry를 golden 82개와 대조 (P4.1)
// ============================================================
// vector마다 31 timestep을 차례로 추론한다. 첫 timestep은 RESET_STATE.
// Membrane potential은 TB가 STORE_BITS로 포화해 들고 있다(RTL 저장은 P4.2 membrane_bank 몫).
//   STORE_BITS 16 → golden_l64, 12 → golden_l64_m12 (vector 폴더 vec/, vec_m12/)
// 확인 항목:
//   - row마다 전류, 포화 후 membrane potential, spike, soft reset 뒤 membrane potential이
//     golden과 bit 일치 (layer 4는 lane 0·1)
//   - 추론마다 row 45개를 한 번씩 쓴다, out_mem0·1이 판정용 출력(저장 전 값)과 같다
//   - 연산 cycle(busy 구간)과 control overhead = cycle − (240 + 4⌈n1/2⌉ + ⌈n2/2⌉ + 2)
// 실행 (저장소 루트):
//   bash hardware/testbench/run_compute_array.sh
// ============================================================
`timescale 1ns / 1ps

module tb_compute_array #(
    parameter int STORE_BITS = 16
);

    localparam N_VEC = 82, T = 31, ROWS = 45, CUR_W = 17;
    localparam string VEC = (STORE_BITS == 16) ? "hardware/sim/compute_array/vec/"
                                               : $sformatf("hardware/sim/compute_array/vec_m%0d/", STORE_BITS);
    localparam int S_MAX = (1 << (STORE_BITS - 1)) - 1, S_MIN = -(1 << (STORE_BITS - 1));

    // 다음 timestep으로 넘길 때만 STORE_BITS로 포화 (snn_int8.py store_bits)
    function automatic [255:0] store(input [255:0] m);
        integer i, x;
        for (i = 0; i < 16; i = i + 1) begin
            x = $signed(m[16*i +: 16]);
            x = (x > S_MAX) ? S_MAX : (x < S_MIN) ? S_MIN : x;
            store[16*i +: 16] = x[15:0];
        end
    endfunction

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
    reg  [255:0] m_rd_data;
    wire [255:0] m_wr_data, dbg_mem_sat;
    wire [16*CUR_W-1:0] dbg_cur;
    wire [15:0]  dbg_spk;

    // Entry 적재 (DMA 대신)
    reg          ld_we = 1'b0, ld_pwe = 1'b0;
    reg  [10:0]  ld_addr = 11'd0;
    reg  [5:0]   ld_paddr = 6'd0;
    reg  [511:0] ld_din = 512'd0;
    reg  [255:0] ld_pdin = 256'd0;

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

    // Membrane potential: STORE_BITS 포화 저장, 읽기 지연 2
    reg [255:0] mstate [0:ROWS-1];
    reg [255:0] m_q1;
    always @(posedge clk) begin
        if (m_rd_en)
            m_q1 <= mstate[m_rd_row];
        m_rd_data <= m_q1;
        if (m_wr_en)
            mstate[m_wr_row] <= store(m_wr_data);
    end

    // ---------------- data ----------------
    reg [7:0]   idx  [0:N_VEC-1];
    reg [511:0] wbuf [0:2033];
    reg [255:0] pbuf [0:45];
    reg [319:0] xbuf [0:T-1];
    reg [911:0] ebuf [0:T*ROWS-1];
    reg [31:0]  obuf [0:T-1];

    integer v, t, k, m_now;
    integer t_now;          // 대조 process가 읽는 timestep (Verilator는 for 초기값을 다른 process에 늦게 보였다)
    integer err [0:3];
    integer rows_seen, rows_checked, n_inf, fail_v;
    integer busy_cnt, cyc_min, cyc_max, ctl_min, ctl_max;
    longint cyc_sum, ctl_sum;

    function automatic integer layer_of(input integer row);
        layer_of = (row < 24) ? 0 : (row < 40) ? 1 : (row < 44) ? 2 : 3;
    endfunction

    // row 쓰기 대조
    always @(negedge clk) begin
        if (!rst && m_wr_en) begin : chk
            reg [911:0] e;
            reg [255:0] st;
            integer lane_n, bad;
            e = ebuf[t_now * ROWS + m_wr_row];
            st = store(m_wr_data);
            lane_n = (m_wr_row == 6'd44) ? 2 : 16;
            bad = 0;
            for (k = 0; k < lane_n; k = k + 1) begin
                if ($signed(dbg_cur[CUR_W*k +: CUR_W]) != $signed(e[24*k +: 24])) bad = bad + 1;
                if (dbg_mem_sat[16*k +: 16] != e[384 + 16*k +: 16]) bad = bad + 1;
                if (st[16*k +: 16] != e[640 + 16*k +: 16]) bad = bad + 1;
                if (dbg_spk[k] != e[896 + k]) bad = bad + 1;
            end
            if (bad != 0) begin
                if (err[layer_of(m_wr_row)] < 5)
                    $display("FAIL v%0d t%0d row %0d: 불일치 %0d", v, t_now, m_wr_row, bad);
                err[layer_of(m_wr_row)] = err[layer_of(m_wr_row)] + bad;
            end
            rows_seen = rows_seen + 1;
            rows_checked = rows_checked + 1;
        end
    end

    always @(posedge clk)
        if (busy) busy_cnt = busy_cnt + 1;

    task automatic load_model(input integer m);
        integer a;
        $readmemh($sformatf("%sm%02d_w.hex", VEC, m), wbuf);
        $readmemh($sformatf("%sm%02d_p.hex", VEC, m), pbuf);
        for (a = 0; a < 2034; a = a + 1) begin
            @(negedge clk);
            ld_we = 1'b1; ld_addr = a[10:0]; ld_din = wbuf[a];
            ld_pwe = (a < 46); ld_paddr = a[5:0]; ld_pdin = pbuf[a < 46 ? a : 0];
        end
        @(negedge clk);
        ld_we = 1'b0; ld_pwe = 1'b0;
    endtask

    function automatic integer spikes(input integer t0, input integer r0, input integer r1);
        integer r, c;
        c = 0;
        for (r = r0; r < r1; r = r + 1)
            c = c + $countones(ebuf[t0 * ROWS + r][911:896]);
        spikes = c;
    endfunction

    initial begin : main
        integer n1, n2, base, ctl, w;
        for (k = 0; k < 4; k = k + 1) err[k] = 0;
        rows_checked = 0; n_inf = 0; fail_v = 0;
        cyc_min = 1 << 30; cyc_max = 0; ctl_min = 1 << 30; ctl_max = 0; cyc_sum = 0; ctl_sum = 0;
        m_now = -1;
        for (k = 0; k < ROWS; k = k + 1) mstate[k] = 256'd0;
        $readmemh({VEC, "index.hex"}, idx);
        repeat (4) @(negedge clk);
        rst = 1'b0;

        for (v = 0; v < N_VEC; v = v + 1) begin
            integer e0;
            e0 = err[0] + err[1] + err[2] + err[3];
            if (idx[v] != m_now) begin
                m_now = idx[v];
                load_model(m_now);
            end
            $readmemh($sformatf("%sv%02d_x.hex", VEC, v), xbuf);
            $readmemh($sformatf("%sv%02d_e.hex", VEC, v), ebuf);
            $readmemh($sformatf("%sv%02d_o.hex", VEC, v), obuf);
            for (t = 0; t < T; t = t + 1) begin
                @(negedge clk);
                start = 1'b1; reset_state = (t == 0); x_in = xbuf[t];
                rows_seen = 0; busy_cnt = 0; t_now = t;
                @(negedge clk);
                start = 1'b0;
                w = 0;
                while (!done) begin
                    @(negedge clk);
                    w = w + 1;
                    if (w > 5000) begin
                        $display("FAIL v%0d t%0d: done 없음", v, t);
                        $finish;
                    end
                end
                if (rows_seen != ROWS)
                    begin $display("FAIL v%0d t%0d: row %0d개 씀", v, t, rows_seen); err[3] = err[3] + 1; end
                if ({out_mem1, out_mem0} != obuf[t])
                    begin $display("FAIL v%0d t%0d: out_mem", v, t); err[3] = err[3] + 1; end
                n1 = spikes(t, 0, 24);
                n2 = spikes(t, 24, 40);
                base = 240 + 4 * ((n1 + 1) / 2) + (n2 + 1) / 2 + 2;
                ctl = busy_cnt - base;
                n_inf = n_inf + 1;
                cyc_sum = cyc_sum + busy_cnt; ctl_sum = ctl_sum + ctl;
                if (busy_cnt < cyc_min) cyc_min = busy_cnt;
                if (busy_cnt > cyc_max) cyc_max = busy_cnt;
                if (ctl < ctl_min) ctl_min = ctl;
                if (ctl > ctl_max) ctl_max = ctl;
            end
            if (err[0] + err[1] + err[2] + err[3] != e0) fail_v = fail_v + 1;
        end

        $display("run   저장 %0d bit, vector %0d, 추론 %0d, row %0d개 대조", STORE_BITS, N_VEC, n_inf, rows_checked);
        $display("run   불일치 layer1 %0d, layer2 %0d, layer3 %0d, layer4 %0d, 틀린 vector %0d",
                 err[0], err[1], err[2], err[3], fail_v);
        $display("run   cycle 최소 %0d, 평균 %0.1f, 최대 %0d", cyc_min, real'(cyc_sum) / n_inf, cyc_max);
        $display("run   control overhead 최소 %0d, 평균 %0.1f, 최대 %0d (가정 203)", ctl_min, real'(ctl_sum) / n_inf, ctl_max);
        if (err[0] + err[1] + err[2] + err[3] == 0 && cyc_max <= 2237)
            $display("PASS");
        else
            $display("FAIL");
        $finish;
    end

endmodule
