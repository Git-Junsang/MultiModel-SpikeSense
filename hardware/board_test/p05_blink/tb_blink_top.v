// tb_blink_top.v — blink_top 동작 확인 (CLK_HZ를 줄여 빠르게 실행)
// 실행 (저장소 루트에서):
//   xvlog -d SIM hardware/board_test/p05_blink/*.v /tools/Xilinx/2026.1/Vivado/data/verilog/src/glbl.v
//   xelab -L unisims_ver tb_blink_top glbl -s tb_blink && xsim tb_blink -R
`timescale 1ns / 1ps
module tb_blink_top;
    reg clk = 0, rst_n = 0;
    reg [3:0] key_n = 4'hF;
    wire led_core;
    wire [3:0] led_n;
    always #2.5 clk = ~clk;

    blink_top #(.CLK_HZ(60)) dut (
        .sys_clk_p(clk), .sys_clk_n(~clk), .rst_n(rst_n), .key_n(key_n),
        .led_core(led_core), .led_n(led_n));

    integer errors = 0;
    integer core_toggles = 0;
    reg core_prev = 0;
    always @(posedge clk) begin
        if (led_core !== core_prev) core_toggles = core_toggles + 1;
        core_prev <= led_core;
    end

    initial begin
        repeat (10) @(posedge clk);
        if (led_n !== 4'b1111) begin errors = errors + 1; $display("FAIL reset: led_n=%b", led_n); end
        rst_n = 1;
        repeat (5) @(posedge clk);
        if (led_n !== 4'b1110) begin errors = errors + 1; $display("FAIL ring0: led_n=%b", led_n); end
        repeat (20) @(posedge clk);            // STEP = 20 클럭
        if (led_n !== 4'b1101) begin errors = errors + 1; $display("FAIL ring1: led_n=%b", led_n); end
        key_n = 4'b0111;                        // KEY4 누름
        repeat (4) @(posedge clk);
        if (led_n[3] !== 1'b0) begin errors = errors + 1; $display("FAIL key4: led_n=%b", led_n); end
        key_n = 4'hF;
        repeat (1100) @(posedge clk);
        if (core_toggles < 8) begin errors = errors + 1; $display("FAIL core toggles=%0d", core_toggles); end
        if (dut.acc !== 32'd333833500 || !dut.calc_done) begin errors = errors + 1; $display("FAIL calc acc=%0d", dut.acc); end
        if (errors == 0) $display("PASS core_toggles=%0d acc=%0d", core_toggles, dut.acc);
        $finish;
    end
endmodule
