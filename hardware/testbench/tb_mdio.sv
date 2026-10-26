// ============================================================
// tb_mdio.sv — mdio_master.v(Clause 22 MDIO master)를 PHY register 모델에 맞대어 확인 (P5.3)
// ============================================================
// PHY 모델: 주소 3, register 32개. MDC 상승 edge에서 bit를 받고, 읽기면 TA 둘째 bit부터 상승 edge 뒤 40 ns에 낸다.
// MDIO는 pull-up(tri1). 확인: 쓰기 뒤 읽기, ID register, 다른 PHY 주소 읽기 = 0xFFFF, 바쁠 때 온 명령은 버림,
//   쉬는 동안 MDC 0·MDIO Z, frame마다 MDC 상승 edge 64개.
// 실행 (저장소 루트): bash hardware/testbench/run_mdio.sh
// ============================================================
`timescale 1ns / 1ps

module tb_mdio;
    reg clk = 1'b0, rst = 1'b1;
    always #5 clk = ~clk;

    reg         cmd_valid = 1'b0;
    reg  [1:0]  cmd_op = 2'd0;
    reg  [4:0]  cmd_phy = 5'd0, cmd_reg = 5'd0;
    reg  [15:0] cmd_data = 16'd0;
    wire        busy, mdc;
    wire [15:0] rdata;
    tri1        mdio;

    mdio_master #(.DIV(4)) dut (.clk(clk), .rst(rst), .cmd_valid(cmd_valid), .cmd_op(cmd_op), .cmd_phy(cmd_phy),
        .cmd_reg(cmd_reg), .cmd_data(cmd_data), .busy(busy), .rdata(rdata), .mdc(mdc), .mdio(mdio));

    int errors = 0;
    function automatic void err(input string s);
        errors++;
        $display("ERROR t=%0t %s", $time, s);
    endfunction

    // ---------------- PHY 모델 ----------------
    reg  [15:0] pr [0:31];
    reg         p_oe = 1'b0, p_o = 1'b1;
    assign mdio = p_oe ? p_o : 1'bz;
    int         n_rise = 0;
    initial begin
        for (int i = 0; i < 32; i++) pr[i] = 16'h1000 + i;
        pr[2] = 16'h0022; pr[3] = 16'h1622;
    end
    initial begin : phy
        logic [13:0] hd;
        int ones;
        forever begin
            ones = 0;
            while (ones < 32) begin @(posedge mdc); n_rise++; ones = (mdio === 1'b1) ? ones + 1 : 0; end
            do begin @(posedge mdc); n_rise++; end while (mdio === 1'b1);           // ST의 0
            for (int i = 0; i < 13; i++) begin @(posedge mdc); n_rise++; hd[12 - i] = mdio; end  // ST의 1, OP, PHYAD, REGAD
            if (hd[12] !== 1'b1) begin err("ST"); continue; end
            if (hd[11:10] == 2'b01) begin                                          // 쓰기
                logic [15:0] d;
                repeat (2) begin @(posedge mdc); n_rise++; end
                for (int i = 15; i >= 0; i--) begin @(posedge mdc); n_rise++; d[i] = mdio; end
                if (hd[9:5] == 5'd3) pr[hd[4:0]] = d;
            end else if (hd[11:10] == 2'b10) begin                                 // 읽기
                @(posedge mdc); n_rise++;                                         // TA 첫 bit: Z
                if (hd[9:5] == 5'd3) begin
                    #40 p_oe = 1'b1; p_o = 1'b0;                                  // TA 둘째 bit
                    for (int i = 15; i >= 0; i--) begin @(posedge mdc); n_rise++; #40 p_o = pr[hd[4:0]][i]; end
                    @(posedge mdc); n_rise++; #40 p_oe = 1'b0;
                end else
                    repeat (17) begin @(posedge mdc); n_rise++; end
            end else
                err("OP");
        end
    end

    // 쉬는 동안 MDC 0, MDIO Z(pull-up 1)
    always @(posedge clk) if (!rst && !busy && !cmd_valid && (mdc !== 1'b0 || dut.oe !== 1'b0)) err("idle MDC·MDIO");

    task automatic cmd(input [1:0] op, input [4:0] phy, input [4:0] rg, input [15:0] d);
        @(negedge clk);
        cmd_valid = 1'b1; cmd_op = op; cmd_phy = phy; cmd_reg = rg; cmd_data = d;
        @(negedge clk);
        cmd_valid = 1'b0;
        while (busy) @(negedge clk);
        repeat (3) @(negedge clk);
    endtask

    task automatic rd_chk(input [4:0] phy, input [4:0] rg, input [15:0] e, input string name);
        int r0;
        r0 = n_rise;
        cmd(2'b10, phy, rg, 16'd0);
        if (rdata !== e) err($sformatf("%s: read %h, expected %h", name, rdata, e));
        if (n_rise - r0 != 64) err($sformatf("%s: MDC rising edges %0d", name, n_rise - r0));
    endtask

    initial begin
        repeat (5) @(negedge clk);
        rst = 1'b0;
        rd_chk(5'd3, 5'd2, 16'h0022, "PHY ID 1");
        rd_chk(5'd3, 5'd3, 16'h1622, "PHY ID 2");
        cmd(2'b01, 5'd3, 5'd9, 16'h1A00);
        if (pr[9] !== 16'h1A00) err($sformatf("write reg 9: %h", pr[9]));
        rd_chk(5'd3, 5'd9, 16'h1A00, "reg 9 after write");
        cmd(2'b01, 5'd3, 5'd31, 16'hA5C3);
        rd_chk(5'd3, 5'd31, 16'hA5C3, "reg 31 after write");
        rd_chk(5'd4, 5'd2, 16'hFFFF, "other PHY address");
        cmd(2'b01, 5'd4, 5'd9, 16'h0000);
        if (pr[9] !== 16'h1A00) err("write to other PHY address changed reg 9");
        // 바쁠 때 온 명령은 버린다
        @(negedge clk); cmd_valid = 1'b1; cmd_op = 2'b01; cmd_phy = 5'd3; cmd_reg = 5'd5; cmd_data = 16'h1111;
        @(negedge clk); cmd_reg = 5'd6; cmd_data = 16'h2222;
        @(negedge clk); cmd_valid = 1'b0;
        while (busy) @(negedge clk);
        repeat (300) @(negedge clk);
        if (pr[5] !== 16'h1111 || pr[6] !== 16'h1006) err($sformatf("busy command: reg5 %h reg6 %h", pr[5], pr[6]));
        cmd(2'b00, 5'd3, 5'd7, 16'h7777);                                         // 없는 op는 무시
        if (busy || pr[7] !== 16'h1007) err("invalid op");
        $display("run   MDIO 쓰기 4·읽기 5, MDC 상승 edge %0d, 오류 %0d", n_rise, errors);
        if (errors == 0) $display("PASS");
        else $display("FAIL 오류 %0d개", errors);
        $finish;
    end
endmodule
