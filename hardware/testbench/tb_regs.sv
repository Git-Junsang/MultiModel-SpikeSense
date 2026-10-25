// ============================================================
// tb_regs.sv — regs(register block, P4.6)를 06 §7 주소표와 대조
// ============================================================
// AXI4-Lite master 하나로 읽고 쓴다. 거래마다 AW·W 순서(같은 cycle, AW 먼저, W 먼저)와 bready·rready 지연을 돌려 쓴다.
// 확인 항목:
//   - 모든 register 기본값·읽기·쓰기, 없는 주소 읽기 0, 읽기 전용·없는 주소 쓰기 무시, wstrb != 4'hF 무시
//   - RUN = 1이면 설정·PNU 표 창 쓰기 무시(CTRL은 씀), 범위 밖 N_TRACKS·N_MODELS 무시
//   - PNU 표 창 → cfg_we 1 cycle, cfg_addr = (addr − 0x1000) >> 2, cfg_data = wdata[15:0] (OFFSET·N_REG·TAU·LUT_G·LUT_U 끝)
//   - 시각: 매 cycle testbench 모델과 비교. phase_us 31,999 → 0과 epoch +1을 실제 3,200,000 cycle을 돌려 확인
//     epoch 0xFFFF → 0(hierarchy로 당김) 뒤에도 first_epoch 0
//   - counter 사건마다 값, 모든 사건을 같은 cycle에, ev_state_xfer 1·2, MAX_PENDING, cnt_clear·SOFT_RESET으로 0
//   - 64 bit 값 5개: LO를 읽을 때 HI 고정, 값마다 따로. NOW_CYC·CMP_BUSY는 위쪽 bit를 hierarchy로 넣고,
//     WEIGHT_BYTES·STATE_BYTES는 사건을 실제로 2^32 B 넘게 넣는다
//   - 오류 우선순위 err0 > err1 > err2, 첫 오류만, ERR_CLEAR(같은 cycle 새 오류는 잡음), SOFT_RESET으로 지움
//   - core_rst는 SOFT_RESET 쓰기 다음 cycle부터 4 cycle, cnt_clear는 1 cycle, RUN 0
//   - AXI: valid·data 유지, 나가 있는 응답 하나, 응답 OKAY, 응답이 밀린 동안 다음 주소를 받지 않음
// 실행 (저장소 루트):
//   bash hardware/testbench/run_regs.sh
// ============================================================
`timescale 1ns / 1ps

module tb_regs;

    localparam [31:0] ID = 32'h534E_4E58, VERSION = 32'h0001_0000;
    localparam int N_ENTRY = 4, N_ONCHIP = 768;

    reg clk = 1'b0;
    always #5 clk = ~clk;
    reg rst = 1'b1;
    longint cyc = 0;
    always @(posedge clk) begin
        cyc <= cyc + 1;
        if (cyc > 8_000_000) begin            // 정상 실행은 약 340만 cycle
            $display("FAIL 시간 초과: cycle %0d", cyc);
            $finish;
        end
    end

    // ---------------- DUT ----------------
    reg  [31:0] awaddr = 0, wdata = 0, araddr = 0;
    reg  [3:0]  wstrb = 0;
    reg         awvalid = 0, wvalid = 0, bready = 0, arvalid = 0, rready = 0;
    wire        awready, wready, bvalid, arready, rvalid;
    wire [1:0]  bresp, rresp;
    wire [31:0] rdata;
    reg         mig_calib = 0, sys_idle = 0;
    wire        run, core_rst, cnt_clear, cfg_we, first_epoch;
    wire [10:0] n_tracks, cfg_addr;
    wire [5:0]  n_models;
    wire [31:0] model_base, state_base, deadline_us, margin_us, now_us, link_tune;
    wire [15:0] cfg_data, epoch;
    wire [63:0] now_cyc;
    wire [14:0] phase_us;
    reg         ev_req_in = 0, ev_req_drop = 0, ev_res_out = 0, ev_late = 0, ev_batch = 0, ev_load = 0, ev_sat = 0, cmp_busy = 0;
    reg  [1:0]  ev_state_xfer = 0;
    reg  [10:0] pending_n = 0;
    reg  [63:0] stall_cyc = 0;
    reg         err0_valid = 0, err1_valid = 0, err2_valid = 0;
    reg  [3:0]  err0_code = 0;
    reg  [31:0] err0_info = 0, err1_info = 0, err2_info = 0;

    regs #(.N_ENTRY(N_ENTRY), .N_ONCHIP(N_ONCHIP), .VERSION(VERSION)) dut (
        .clk(clk), .rst(rst),
        .s_axil_awaddr(awaddr), .s_axil_awvalid(awvalid), .s_axil_awready(awready),
        .s_axil_wdata(wdata), .s_axil_wstrb(wstrb), .s_axil_wvalid(wvalid), .s_axil_wready(wready),
        .s_axil_bresp(bresp), .s_axil_bvalid(bvalid), .s_axil_bready(bready),
        .s_axil_araddr(araddr), .s_axil_arvalid(arvalid), .s_axil_arready(arready),
        .s_axil_rdata(rdata), .s_axil_rresp(rresp), .s_axil_rvalid(rvalid), .s_axil_rready(rready),
        .mig_calib(mig_calib), .sys_idle(sys_idle),
        .run(run), .core_rst(core_rst), .cnt_clear(cnt_clear),
        .n_tracks(n_tracks), .n_models(n_models), .model_base(model_base), .state_base(state_base),
        .deadline_us(deadline_us), .margin_us(margin_us), .link_tune(link_tune),
        .cfg_we(cfg_we), .cfg_addr(cfg_addr), .cfg_data(cfg_data),
        .now_us(now_us), .now_cyc(now_cyc), .phase_us(phase_us), .epoch(epoch), .first_epoch(first_epoch),
        .ev_req_in(ev_req_in), .ev_req_drop(ev_req_drop), .ev_res_out(ev_res_out), .ev_late(ev_late),
        .ev_batch(ev_batch), .ev_load(ev_load), .ev_sat(ev_sat), .ev_state_xfer(ev_state_xfer),
        .pending_n(pending_n), .cmp_busy(cmp_busy), .stall_cyc(stall_cyc),
        .err0_valid(err0_valid), .err0_code(err0_code), .err0_info(err0_info),
        .err1_valid(err1_valid), .err1_info(err1_info), .err2_valid(err2_valid), .err2_info(err2_info)
    );

    // ---------------- 검사 도구 ----------------
    string grp = $sformatf("init");
    int fails[string];
    int n_chk = 0;

    task automatic chk(input string what, input longint got, input longint exp);
        n_chk++;
        if (got != exp) begin
            if (!fails.exists(grp)) fails[grp] = 0;
            fails[grp]++;
            if (fails[grp] <= 5) $display("FAIL [%s] %s: %0h (기대 %0h), cycle %0d", grp, what, got, exp, cyc);
        end
    endtask

    // ---------------- 시각 모델 (매 cycle 비교) ----------------
    longint m_cyc = 0;
    int m_div = 0, m_us = 0, m_ph = 0, m_ep = 0, t_bad = 0, n_wrap = 0;
    bit m_first = 1;
    always @(posedge clk) begin
        // cycle 0은 첫 rst edge 전이라 register 값이 아직 없다
        if (cyc != 0 && (now_cyc != m_cyc || now_us != m_us || phase_us != m_ph || epoch != m_ep || first_epoch != m_first)) begin
            t_bad++;
            if (t_bad <= 5) $display("FAIL 시각: cyc %0d/%0d us %0d/%0d phase %0d/%0d epoch %0d/%0d first %0b (cycle %0d)",
                                     now_cyc, m_cyc, now_us, m_us, phase_us, m_ph, epoch, m_ep, first_epoch, cyc);
        end
        if (core_rst) begin
            m_cyc = 0; m_div = 0; m_us = 0; m_ph = 0; m_ep = 0; m_first = 1;
        end else begin
            m_cyc = m_cyc + 1;
            if (m_div == 99) begin
                m_div = 0;
                m_us = m_us + 1;
                if (m_ph == 31999) begin m_ph = 0; m_ep = (m_ep + 1) & 16'hFFFF; m_first = 0; n_wrap++; end
                else m_ph = m_ph + 1;
            end else
                m_div = m_div + 1;
        end
    end

    // ---------------- 펄스·AXI 감시 ----------------
    longint sr_hs = -100, cc_hs = -100;
    bit cr_in = 0;
    int cr_len = 0, cr_runs = 0, cr_bad = 0, cc_len = 0, cc_runs = 0, cc_bad = 0;
    int axi_bad = 0, out_b = 0, out_r = 0, n_cfg = 0;
    int n_aw_first = 0, n_w_first = 0, n_same = 0, n_bwait = 0, n_rwait = 0, n_ar_block = 0, n_aw_block = 0;
    reg [10:0] q_addr[$];
    reg [15:0] q_data[$];
    reg [31:0] snap_us;
    longint snap_cyc;
    reg [63:0] snap_stall;
    reg prev_cr = 1'b1, prev_cc = 1'b0, prev_b = 1'b0, prev_r = 1'b0, prev_bready = 1'b0, prev_rready = 1'b0;
    reg [31:0] prev_rdata = 0;
    bit aw_seen = 0, w_seen = 0;

    always @(posedge clk) begin
        // core_rst: SOFT_RESET 쓰기 다음 cycle부터 4 cycle
        if (!rst) begin
            if (core_rst && !prev_cr) begin cr_in = 1; cr_len = 0; if (cyc != sr_hs + 1) cr_bad++; end
            if (core_rst) cr_len++;
            if (!core_rst && prev_cr && cr_in) begin cr_runs++; if (cr_len != 4) cr_bad++; end
            if (!core_rst) cr_in = 0;
            if (cnt_clear && !prev_cc) begin cc_len = 0; if (cyc != cc_hs + 1) cc_bad++; end
            if (cnt_clear) cc_len++;
            if (!cnt_clear && prev_cc) begin cc_runs++; if (cc_len != 1) cc_bad++; end
        end else
            cr_in = 0;
        prev_cr = core_rst; prev_cc = cnt_clear;
        if (cfg_we) begin q_addr.push_back(cfg_addr); q_data.push_back(cfg_data); n_cfg++; end
        // AXI 규칙: 응답 유지, OKAY, 나가 있는 거래 하나
        if (prev_b && !prev_bready && !bvalid) axi_bad++;
        if (prev_r && !prev_rready && (!rvalid || rdata != prev_rdata)) axi_bad++;
        if (bvalid && bresp != 2'b00) axi_bad++;
        if (rvalid && rresp != 2'b00) axi_bad++;
        if (awready != wready) axi_bad++;
        if (awvalid && awready && wvalid && wready) begin
            out_b++;
            if (awaddr == 32'h0104 && wstrb == 4'hF && wdata[1]) sr_hs = cyc;
            if (awaddr == 32'h0104 && wstrb == 4'hF && wdata[2]) cc_hs = cyc;
            if (aw_seen && !w_seen) n_aw_first++;
            else if (w_seen && !aw_seen) n_w_first++;
            else n_same++;
            aw_seen = 0; w_seen = 0;
        end else begin
            if (awvalid) aw_seen = 1;
            if (wvalid) w_seen = 1;
        end
        if ((awvalid && awready) != (wvalid && wready)) axi_bad++;
        if (bvalid && bready) out_b--;
        if (arvalid && arready) begin
            out_r++;
            snap_us = now_us; snap_cyc = now_cyc; snap_stall = stall_cyc;
        end
        if (rvalid && rready) out_r--;
        if (out_b > 1 || out_r > 1 || out_b < 0 || out_r < 0) axi_bad++;
        if (bvalid && !bready) n_bwait++;
        if (rvalid && !rready) n_rwait++;
        if (arvalid && !arready) n_ar_block++;
        if (awvalid && wvalid && !awready) n_aw_block++;
        prev_b = bvalid; prev_r = rvalid; prev_bready = bready; prev_rready = rready; prev_rdata = rdata;
    end

    // ---------------- AXI4-Lite master ----------------
    int n_wr = 0, n_rd = 0;

    task automatic wr(input [31:0] a, input [31:0] d, input [3:0] s = 4'hF);
        int ad, wd_, bd;
        case (n_wr % 5)
            0: begin ad = 0; wd_ = 0; end
            1: begin ad = 0; wd_ = 2; end   // AW 먼저
            2: begin ad = 3; wd_ = 0; end   // W 먼저
            3: begin ad = 1; wd_ = 0; end
            default: begin ad = 0; wd_ = 1; end
        endcase
        bd = (n_wr / 5) % 4;
        n_wr++;
        @(negedge clk);
        fork
            begin
                repeat (ad) @(negedge clk);
                awaddr = a; awvalid = 1'b1;
                #1;
                while (!awready) begin @(negedge clk); #1; end
                @(negedge clk);
                awvalid = 1'b0;
            end
            begin
                repeat (wd_) @(negedge clk);
                wdata = d; wstrb = s; wvalid = 1'b1;
                #1;
                while (!wready) begin @(negedge clk); #1; end
                @(negedge clk);
                wvalid = 1'b0;
            end
        join
        repeat (bd) @(negedge clk);
        bready = 1'b1;
        #1;
        while (!bvalid) begin @(negedge clk); #1; end
        @(negedge clk);
        bready = 1'b0;
    endtask

    task automatic rd(input [31:0] a, output [31:0] d);
        int dl;
        dl = n_rd % 4;
        n_rd++;
        @(negedge clk);
        araddr = a; arvalid = 1'b1;
        #1;
        while (!arready) begin @(negedge clk); #1; end
        @(negedge clk);
        arvalid = 1'b0;
        repeat (dl) @(negedge clk);
        rready = 1'b1;
        #1;
        while (!rvalid) begin @(negedge clk); #1; end
        d = rdata;
        @(negedge clk);
        rready = 1'b0;
    endtask

    task automatic rchk(input [31:0] a, input [31:0] exp);
        reg [31:0] d;
        rd(a, d);
        chk($sformatf("읽기 %08h", a), d, exp);
    endtask

    task automatic chk_set(input [10:0] t, input [5:0] m, input [31:0] mb, input [31:0] sb, input [31:0] dl, input [31:0] mg);
        chk($sformatf("port n_tracks"), n_tracks, t);
        chk($sformatf("port n_models"), n_models, m);
        chk($sformatf("port model_base"), model_base, mb);
        chk($sformatf("port state_base"), state_base, sb);
        chk($sformatf("port deadline_us"), deadline_us, dl);
        chk($sformatf("port margin_us"), margin_us, mg);
    endtask

    task automatic idle(input int n);
        repeat (n) @(negedge clk);
    endtask

    // 사건 n개를 매 cycle 하나씩
    task automatic ev(input int k, input int n);
        @(negedge clk);
        repeat (n) begin
            case (k)
                0: ev_req_in = 1; 1: ev_req_drop = 1; 2: ev_res_out = 1; 3: ev_late = 1;
                4: ev_batch = 1;  5: ev_load = 1;     6: ev_sat = 1;     7: cmp_busy = 1;
                8: ev_state_xfer = 2'd1; 9: ev_state_xfer = 2'd2;
                default: begin   // 모든 사건이 같은 cycle에
                    {ev_req_in, ev_req_drop, ev_res_out, ev_late, ev_batch, ev_load, ev_sat, cmp_busy} = 8'hFF;
                    ev_state_xfer = 2'd2;
                end
            endcase
            @(negedge clk);
        end
        {ev_req_in, ev_req_drop, ev_res_out, ev_late, ev_batch, ev_load, ev_sat, cmp_busy} = 0;
        ev_state_xfer = 0;
    endtask

    localparam [31:0] CNT_A[11] = '{32'h400, 32'h404, 32'h408, 32'h40C, 32'h414, 32'h418, 32'h41C,
                                    32'h420, 32'h428, 32'h430, 32'h410};

    task automatic cnt_all_zero();
        for (int i = 0; i < 11; i++) rchk(CNT_A[i], 0);
        for (int i = 7; i < 10; i++) rchk(CNT_A[i] + 4, 0);
    endtask

    // ---------------- 시험 ----------------
    reg [31:0] d, lo;
    int k0;

    initial begin
        // ===== 기본값 =====
        grp = $sformatf("기본값");
        idle(3);
        chk($sformatf("rst 중 core_rst"), core_rst, 1);
        rst = 1'b0;
        idle(2);
        chk($sformatf("core_rst"), core_rst, 0);
        rchk(32'h0000, ID);
        rchk(32'h0004, VERSION);
        rchk(32'h0008, N_ENTRY);
        rchk(32'h000C, N_ONCHIP);
        rchk(32'h0100, 0);
        rchk(32'h0104, 0);
        rchk(32'h0300, 1024);
        rchk(32'h0304, 40);
        rchk(32'h0308, 0);
        rchk(32'h030C, 32'h0200_0000);
        rchk(32'h0310, 32000);
        rchk(32'h0314, 0);
        rchk(32'h0318, 1);
        chk($sformatf("port link_tune"), link_tune, 1);
        chk_set(11'd1024, 6'd40, 32'd0, 32'h0200_0000, 32'd32000, 32'd0);
        chk($sformatf("run"), run, 0);
        cnt_all_zero();
        rchk(32'h0424, 0); rchk(32'h043C, 0); rchk(32'h020C, 0);
        rchk(32'h0500, 0);
        rchk(32'h0504, 0);

        // ===== STATUS =====
        grp = $sformatf("STATUS");
        mig_calib = 1; rchk(32'h0100, 4'b0100);
        sys_idle = 1;  rchk(32'h0100, 4'b0110);
        mig_calib = 0; rchk(32'h0100, 4'b0010);
        mig_calib = 1;

        // ===== 없는 주소 =====
        grp = $sformatf("없는 주소");
        begin
            reg [31:0] ua[22];
            ua = '{32'h0010, 32'h00FC, 32'h0108, 32'h01FC, 32'h0204, 32'h0210, 32'h031C, 32'h03FC, 32'h0440,
                   32'h04FC, 32'h0508, 32'h0FFC, 32'h1000, 32'h1100, 32'h2000, 32'h2FFC, 32'h3000,
                   32'h7FFF_FFFC, 32'h8000_0000, 32'h0001_0000, 32'h0001_0300, 32'hFFFF_FFFC};
            for (int i = 0; i < 22; i++) rchk(ua[i], 0);
        end

        // ===== 설정 쓰기·범위 =====
        grp = $sformatf("설정");
        wr(32'h0300, 5);           rchk(32'h0300, 5);
        wr(32'h0300, 0);           rchk(32'h0300, 5);
        wr(32'h0300, 1025);        rchk(32'h0300, 5);
        wr(32'h0300, 32'h1_0001);  rchk(32'h0300, 5);
        wr(32'h0300, 1024);        rchk(32'h0300, 1024);
        wr(32'h0300, 1);           rchk(32'h0300, 1);
        wr(32'h0304, 1);           rchk(32'h0304, 1);
        wr(32'h0304, 0);           rchk(32'h0304, 1);
        wr(32'h0304, 41);          rchk(32'h0304, 1);
        wr(32'h0304, 32'h100_0028); rchk(32'h0304, 1);
        wr(32'h0304, 40);          rchk(32'h0304, 40);
        wr(32'h0304, 17);          rchk(32'h0304, 17);
        wr(32'h0308, 32'h1234_5678); rchk(32'h0308, 32'h1234_5678);
        wr(32'h030C, 32'h0300_0000); rchk(32'h030C, 32'h0300_0000);
        wr(32'h0310, 32'd31000);   rchk(32'h0310, 31000);
        wr(32'h0314, 32'hDEAD_BEEF); rchk(32'h0314, 32'hDEAD_BEEF);
        wr(32'h0318, 32'hFFFF_FFFF); rchk(32'h0318, 32'hFFFF_001F);   // bit[15:5]는 0
        chk($sformatf("port link_tune"), link_tune, 32'hFFFF_001F);
        chk_set(11'd1, 6'd17, 32'h1234_5678, 32'h0300_0000, 32'd31000, 32'hDEAD_BEEF);

        // ===== wstrb != F =====
        grp = $sformatf("wstrb");
        begin
            reg [3:0] sb[5];
            sb = '{4'h0, 4'h7, 4'hE, 4'h1, 4'hB};
            for (int i = 0; i < 5; i++) begin
                wr(32'h0300, 33, sb[i]);
                wr(32'h0308, 32'hFFFF_FFFF, sb[i]);
                wr(32'h0104, 32'h1, sb[i]);
                wr(32'h1000, 32'h55, sb[i]);
            end
        end
        rchk(32'h0300, 1); rchk(32'h0308, 32'h1234_5678); rchk(32'h0104, 0);
        chk($sformatf("run"), run, 0);
        chk($sformatf("cfg_we 수"), n_cfg, 0);

        // ===== 읽기 전용·없는 주소 쓰기 =====
        grp = $sformatf("읽기 전용 쓰기");
        ev(0, 2);
        wr(32'h0000, 32'h0); wr(32'h0008, 9); wr(32'h0100, 32'hF); wr(32'h0200, 77); wr(32'h0400, 0);
        wr(32'h0500, 3); wr(32'h031C, 9); wr(32'h0001_0300, 9); wr(32'h0FFC, 1); wr(32'h3000, 1);
        wr(32'h0001_1000, 1); wr(32'h8000_0000, 1);
        rchk(32'h0000, ID); rchk(32'h0008, N_ENTRY); rchk(32'h0100, 4'b0110); rchk(32'h0400, 2); rchk(32'h0500, 0);
        rchk(32'h0300, 1);
        chk($sformatf("cfg_we 수"), n_cfg, 0);

        // ===== PNU 표 창 =====
        grp = $sformatf("PNU 표");
        begin
            reg [31:0] pa[10];
            reg [10:0] ea[10];
            pa = '{32'h1000, 32'h109C, 32'h1100, 32'h119C, 32'h1200, 32'h1208, 32'h1400, 32'h15FC, 32'h2000, 32'h2FFC};
            ea = '{11'h000, 11'h027, 11'h040, 11'h067, 11'h080, 11'h082, 11'h100, 11'h17F, 11'h400, 11'h7FF};
            q_addr.delete(); q_data.delete();
            for (int i = 0; i < 10; i++) wr(pa[i], {16'hA5A5 ^ i[15:0], 16'h1000 + 16'(i * 7)});
            wr(32'h2014, 32'hFFFF_0123);
            chk($sformatf("cfg_we 수"), q_addr.size(), 11);
            for (int i = 0; i < 10 && i < q_addr.size(); i++) begin
                chk($sformatf("cfg_addr %08h", pa[i]), q_addr[i], ea[i]);
                chk($sformatf("cfg_data %08h", pa[i]), q_data[i], 16'h1000 + 16'(i * 7));
            end
            if (q_addr.size() == 11) begin chk($sformatf("cfg_addr 2014"), q_addr[10], 11'h405); chk($sformatf("cfg_data 2014"), q_data[10], 16'h0123); end
            rchk(32'h1000, 0); rchk(32'h2014, 0);
        end

        // ===== RUN =====
        grp = $sformatf("RUN");
        wr(32'h0104, 32'h1);
        chk($sformatf("run"), run, 1);
        rchk(32'h0104, 1);
        rchk(32'h0100, 4'b0111);
        k0 = n_cfg;
        wr(32'h0300, 7); wr(32'h0304, 3); wr(32'h0308, 1); wr(32'h030C, 2); wr(32'h0310, 3); wr(32'h0314, 4);
        wr(32'h1000, 9); wr(32'h2FFC, 9);
        rchk(32'h0300, 1); rchk(32'h0304, 17); rchk(32'h0308, 32'h1234_5678); rchk(32'h030C, 32'h0300_0000);
        rchk(32'h0310, 31000); rchk(32'h0314, 32'hDEAD_BEEF);
        wr(32'h0318, 32'h5); rchk(32'h0318, 32'hFFFF_001F);
        chk($sformatf("cfg_we (RUN = 1)"), n_cfg - k0, 0);
        wr(32'h0104, 32'h1);
        chk($sformatf("run 유지"), run, 1);
        wr(32'h0104, 32'h0);                 // CTRL은 RUN = 1에도 쓸 수 있다
        chk($sformatf("run 끔"), run, 0);
        rchk(32'h0104, 0);
        wr(32'h0300, 7); rchk(32'h0300, 7);
        wr(32'h1004, 32'h0000_0021);
        chk($sformatf("cfg_we (RUN = 0)"), n_cfg - k0, 1);
        if (q_addr.size() > 0) begin chk($sformatf("cfg_addr"), q_addr[$], 11'h001); chk($sformatf("cfg_data"), q_data[$], 16'h0021); end
        // CTRL bit1~3은 읽으면 0, SOFT_RESET이 RUN을 끈다
        wr(32'h0104, 32'h1);
        wr(32'h0104, 32'hF);
        chk($sformatf("SOFT_RESET → run 0"), run, 0);
        rchk(32'h0104, 0);
        wr(32'h0104, 32'h1);
        wr(32'h0104, 32'h2);
        chk($sformatf("SOFT_RESET → run 0"), run, 0);
        rchk(32'h0300, 7);                   // SOFT_RESET은 설정을 지우지 않는다
        rchk(32'h0304, 17);

        // ===== counter =====
        grp = $sformatf("counter");
        wr(32'h0104, 32'h4);                 // CNT_CLEAR
        cnt_all_zero();
        ev(0, 3); ev(1, 5); ev(2, 7); ev(3, 2); ev(4, 4); ev(5, 6); ev(6, 9); ev(7, 11);
        ev(8, 3); ev(9, 5);                  // STATE_BYTES (3 + 10) × 1,088
        pending_n = 3; idle(1); pending_n = 1023; idle(1); pending_n = 7; idle(3);
        rchk(32'h0400, 3); rchk(32'h0404, 5); rchk(32'h0408, 7); rchk(32'h040C, 2); rchk(32'h0410, 1023);
        rchk(32'h0414, 4); rchk(32'h0418, 6); rchk(32'h041C, 9);
        rchk(32'h0420, 6 * 131648); rchk(32'h0424, 0);
        rchk(32'h0428, 13 * 1088);  rchk(32'h042C, 0);
        rchk(32'h0430, 11);         rchk(32'h0434, 0);
        stall_cyc = 64'd12345;
        rchk(32'h0438, 12345);      rchk(32'h043C, 0);
        pending_n = 0;
        wr(32'h0104, 32'h4);
        cnt_all_zero();
        pending_n = 5; idle(2); pending_n = 2; idle(2);
        rchk(32'h0410, 5);
        pending_n = 0;
        wr(32'h0104, 32'h4);
        // 모든 사건을 같은 cycle에 37번: counter끼리 서로 막지 않는다
        ev(10, 37);
        for (int i = 0; i < 7; i++) rchk(32'h0400 + 4 * (i < 4 ? i : i + 1), 37);
        rchk(32'h0420, 37 * 131648); rchk(32'h0428, 37 * 2176); rchk(32'h0430, 37);
        wr(32'h0104, 32'h4);
        // ERR_CLEAR·RUN 쓰기는 counter를 지우지 않는다
        ev(0, 4); wr(32'h0104, 32'h8); wr(32'h0104, 32'h0);
        rchk(32'h0400, 4);
        // SOFT_RESET(core_rst)으로 0
        ev(1, 2); ev(7, 3); ev(9, 1); ev(5, 1);
        wr(32'h0104, 32'h2);
        cnt_all_zero();

        // ===== 오류 =====
        grp = $sformatf("오류");
        rchk(32'h0500, 0); rchk(32'h0504, 0);
        @(negedge clk); err1_valid = 1; err1_info = 32'h1111_0001; err2_valid = 1; err2_info = 32'h2222_0002;
        @(negedge clk); err1_valid = 0; err2_valid = 0;
        rchk(32'h0500, 6); rchk(32'h0504, 32'h1111_0001); rchk(32'h0100, 4'b1110);
        @(negedge clk); err0_valid = 1; err0_code = 2; err0_info = 32'h0000_0AAA;
        @(negedge clk); err0_valid = 0;
        rchk(32'h0500, 6); rchk(32'h0504, 32'h1111_0001);    // 첫 오류만
        wr(32'h0104, 32'h8);
        rchk(32'h0500, 0); rchk(32'h0504, 0); rchk(32'h0100, 4'b0110);
        @(negedge clk);
        err0_valid = 1; err0_code = 3; err0_info = 32'h0000_0333;
        err1_valid = 1; err1_info = 32'h0000_0666; err2_valid = 1; err2_info = 32'h0000_0777;
        @(negedge clk); {err0_valid, err1_valid, err2_valid} = 0;
        rchk(32'h0500, 3); rchk(32'h0504, 32'h333);
        wr(32'h0104, 32'h8);
        @(negedge clk); err2_valid = 1; err2_info = 32'd1000;
        @(negedge clk); err2_valid = 0;
        rchk(32'h0500, 7); rchk(32'h0504, 1000);
        wr(32'h0104, 32'h8);
        @(negedge clk); err0_valid = 1; err0_code = 5; err0_info = 32'd513; err2_valid = 1;
        @(negedge clk); {err0_valid, err2_valid} = 0;
        rchk(32'h0500, 5); rchk(32'h0504, 513);
        // ERR_CLEAR와 같은 cycle의 새 오류는 남는다
        @(negedge clk);
        fork
            wr(32'h0104, 32'h8);
            begin
                #1; while (!(awready && wready)) begin @(negedge clk); #1; end
                err1_valid = 1; err1_info = 32'h0BAD_0BAD;
                @(negedge clk); err1_valid = 0;
            end
        join
        rchk(32'h0500, 6); rchk(32'h0504, 32'h0BAD_0BAD);
        // SOFT_RESET으로 지움
        wr(32'h0104, 32'h2);
        rchk(32'h0500, 0); rchk(32'h0504, 0); rchk(32'h0100, 4'b0110);
        @(negedge clk); err0_valid = 1; err0_code = 1; err0_info = 32'd42;
        @(negedge clk); err0_valid = 0;
        rchk(32'h0500, 1); rchk(32'h0504, 42);

        // ===== 64 bit HI =====
        grp = $sformatf("64 bit HI");
        // CMP_STALL: 입력을 그대로
        stall_cyc = 64'h0000_0001_FFFF_FFF0;
        rchk(32'h0438, 32'hFFFF_FFF0);
        stall_cyc = 64'h0000_0005_0000_0003;
        rchk(32'h043C, 1);                  // LO를 읽을 때 잡은 값
        rchk(32'h043C, 1);
        rchk(32'h0438, 3);
        rchk(32'h043C, 5);
        // NOW_CYC: 위쪽 bit를 hierarchy로 넣는다(모델도 같이)
        @(negedge clk);
        dut.now_cyc = 64'h0000_0002_FFFF_FF00; m_cyc = 64'h0000_0002_FFFF_FF00;
        rd(32'h0208, lo);
        chk($sformatf("NOW_CYC_LO"), lo, snap_cyc[31:0]);
        rchk(32'h020C, 2);
        idle(300);
        chk($sformatf("NOW_CYC 넘침"), now_cyc[63:32], 3);
        rchk(32'h020C, 2);                  // 아직 LO를 안 읽음
        rd(32'h0208, lo);
        chk($sformatf("NOW_CYC_LO"), lo, snap_cyc[31:0]);
        rchk(32'h020C, 3);
        rd(32'h0200, d);
        chk($sformatf("NOW_US"), d, snap_us);
        // CMP_BUSY
        @(negedge clk);
        dut.c_busy = 64'h0000_0004_FFFF_FFF0;
        ev(7, 32);
        rchk(32'h0430, 32'h10);
        rchk(32'h0434, 5);
        // WEIGHT_BYTES: 32,700 × 131,648 = 4,304,889,600 B
        ev(5, 32700);
        rchk(32'h0424, 0);                  // 아직 LO를 안 읽음
        rchk(32'h0420, 32'(64'd32700 * 131648));
        rchk(32'h0424, 1);
        rchk(32'h0434, 5);                  // 값마다 따로
        wr(32'h0104, 32'h4);                // CNT_CLEAR: 값은 0, 그림자는 남음
        rchk(32'h0424, 1);
        rchk(32'h0434, 5);
        rchk(32'h0420, 0);
        rchk(32'h0424, 0);
        rchk(32'h0434, 5);
        rchk(32'h0430, 0);
        rchk(32'h0434, 0);

        // ===== 시각: phase 넘침, STATE_BYTES 2^32 넘김 =====
        grp = $sformatf("시각");
        wr(32'h0104, 32'h2);                // core_rst → 시각 0
        rd(32'h0200, d);
        chk($sformatf("NOW_US"), d, snap_us);
        chk($sformatf("SOFT_RESET 뒤 NOW_US 작음"), d < 5, 1);
        ev(9, 1_974_000);                   // 1,974,000 × 2,176 = 4,295,424,000 B
        while (epoch == 0) @(negedge clk);
        chk($sformatf("phase 넘침 뒤 phase_us"), phase_us, 0);
        chk($sformatf("first_epoch"), first_epoch, 0);
        chk($sformatf("now_us"), now_us, 32000);
        idle(250);
        rd(32'h0200, d);
        chk($sformatf("NOW_US"), d, snap_us);
        chk($sformatf("NOW_US > 32,000"), d > 32000, 1);
        // epoch 16 bit가 한 바퀴 돌아 0이 되어도 first_epoch는 0 (35분 RUN을 hierarchy로 당김, 모델도 같이)
        @(negedge clk);
        dut.epoch = 16'hFFFF; m_ep = 16'hFFFF;
        dut.phase_us = 15'd31999; m_ph = 31999;
        dut.div = 7'd90; m_div = 90;
        idle(20);
        chk($sformatf("epoch 한 바퀴 뒤 epoch"), epoch, 0);
        chk($sformatf("epoch 한 바퀴 뒤 phase_us"), phase_us, 0);
        chk($sformatf("epoch 한 바퀴 뒤 first_epoch"), first_epoch, 0);
        grp = $sformatf("64 bit HI");
        rchk(32'h0428, 32'(64'd1_974_000 * 2176));
        rchk(32'h042C, 1);
        rchk(32'h0424, 0);
        // SOFT_RESET: 시각·counter 0, 시각은 다시 첫 epoch
        grp = $sformatf("시각");
        wr(32'h0104, 32'h2);
        chk($sformatf("first_epoch"), first_epoch, 1);
        chk($sformatf("epoch"), epoch, 0);
        rchk(32'h0428, 0);
        rchk(32'h042C, 0);

        // ===== AXI: 응답이 밀린 동안 =====
        grp = $sformatf("AXI");
        // 읽기 응답을 안 받으면 다음 AR을 받지 않는다
        @(negedge clk);
        araddr = 32'h0000; arvalid = 1;
        @(negedge clk);
        araddr = 32'h0004;
        #1;
        chk($sformatf("arready (rvalid 대기 중)"), arready, 0);
        repeat (5) begin @(negedge clk); #1; chk($sformatf("arready (rvalid 대기 중)"), arready, 0); end
        chk($sformatf("rdata 0"), rdata, ID);
        rready = 1;
        @(negedge clk); #1;
        rready = 0;
        while (!arready) begin @(negedge clk); #1; end
        @(negedge clk); arvalid = 0;
        #1; while (!rvalid) begin @(negedge clk); #1; end
        chk($sformatf("rdata 1"), rdata, VERSION);
        rready = 1; @(negedge clk); rready = 0;
        // 쓰기 응답을 안 받으면 다음 쓰기를 받지 않는다
        @(negedge clk);
        awaddr = 32'h0310; wdata = 111; wstrb = 4'hF; awvalid = 1; wvalid = 1;
        @(negedge clk);
        wdata = 222;
        #1;
        repeat (5) begin chk($sformatf("awready (bvalid 대기 중)"), awready, 0); @(negedge clk); #1; end
        chk($sformatf("DEADLINE_US 첫 쓰기"), deadline_us, 111);
        bready = 1;
        @(negedge clk); #1;
        bready = 0;
        while (!awready) begin @(negedge clk); #1; end
        @(negedge clk); awvalid = 0; wvalid = 0;
        #1; while (!bvalid) begin @(negedge clk); #1; end
        bready = 1; @(negedge clk); bready = 0;
        chk($sformatf("DEADLINE_US 둘째 쓰기"), deadline_us, 222);
        rchk(32'h0310, 222);
        chk($sformatf("bvalid 끝"), bvalid, 0);
        chk($sformatf("rvalid 끝"), rvalid, 0);

        // ===== rst: 설정 기본값 =====
        grp = $sformatf("rst");
        wr(32'h0104, 32'h1);
        @(negedge clk); rst = 1; idle(2); rst = 0; idle(2);
        chk($sformatf("run"), run, 0);
        chk_set(11'd1024, 6'd40, 32'd0, 32'h0200_0000, 32'd32000, 32'd0);
        rchk(32'h0300, 1024);
        rchk(32'h0500, 0);

        idle(5);
        grp = $sformatf("펄스");
        chk($sformatf("core_rst 4 cycle 위반"), cr_bad, 0);
        chk($sformatf("cnt_clear 1 cycle 위반"), cc_bad, 0);

        // ===== 요약 =====
        $display("run   cycle %0d, 쓰기 %0d, 읽기 %0d, 비교 %0d", cyc, n_wr, n_rd, n_chk);
        $display("run   쓰기 순서: 같은 cycle %0d, AW 먼저 %0d, W 먼저 %0d; bready 지연 cycle %0d, rready 지연 cycle %0d, AR 막힘 %0d, AW 막힘 %0d, AXI 규칙 위반 %0d",
                 n_same, n_aw_first, n_w_first, n_bwait, n_rwait, n_ar_block, n_aw_block, axi_bad);
        $display("run   SOFT_RESET %0d번(core_rst 4 cycle 위반 %0d), CNT_CLEAR %0d번(1 cycle 위반 %0d), cfg_we %0d",
                 cr_runs, cr_bad, cc_runs, cc_bad, n_cfg);
        $display("run   시각 불일치 cycle %0d, phase 넘침 %0d번", t_bad, n_wrap);
        foreach (fails[g]) $display("run   [%s] 불일치 %0d", g, fails[g]);
        if (fails.size() == 0 && t_bad == 0 && axi_bad == 0 && n_wrap == 2 && cr_runs >= 4 && cc_runs >= 4
            && n_same > 0 && n_aw_first > 0 && n_w_first > 0 && n_bwait > 0 && n_rwait > 0 && n_ar_block > 0 && n_aw_block > 0)
            $display("PASS");
        else
            $display("FAIL");
        $finish;
    end

endmodule
