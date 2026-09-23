// ============================================================
// blink_top.v — P0.5 보드 동작 확인용 LED 점멸
// ============================================================
// 대상 : ALINX AX7A200B (XC7A200T-2FBG484I)
// 제약 : hardware/constraints/ax7a200b_base.xdc, ax7a200b_io.xdc
//
// 동작 (200 MHz 시스템 클럭 기준):
//   led_core  (코어보드, Active-High) : 1 Hz 점멸 → 클럭·비트스트림 확인
//   led_n[3:0](캐리어, Active-Low)    : 약 3 Hz로 LED1→LED4 순환
//   KEY1~4를 누르고 있으면 해당 LED가 순환과 관계없이 계속 켜진다 → 버튼 핀 확인
//   RESET을 누르고 있으면 카운터가 멈추고 캐리어 LED가 모두 꺼진다 → RESET 핀 확인
//
// 원격 확인 (LED를 볼 수 없을 때, VIO로 JTAG 읽기):
//   probe_in0 [31:0] 사이클 카운터 — 두 번 읽은 차이 / Host 시각 차이 = 클럭 주파수
//   probe_in1 [31:0] 1^2 + 2^2 + ... + 1000^2 계산 결과 (기대값 333,833,500 = 0x13E5_E51C)
//   probe_in2 [0]    계산 완료
//   probe_in3 [4:0]  {led_core, led_n[3:0]} 구동값
//   probe_in4 [4:0]  {rst_n, key_n[3:0]} 동기화된 버튼 입력
//   시뮬레이션(SIM 정의)에서는 VIO를 넣지 않는다.
//
// 빌드 (저장소 루트에서):
//   vivado -mode batch -source hardware/board_test/p05_blink/build_p05.tcl
// ============================================================
`timescale 1ns / 1ps

module blink_top #(
    parameter integer CLK_HZ = 200_000_000
) (
    input  wire       sys_clk_p,
    input  wire       sys_clk_n,
    input  wire       rst_n,      // RESET 버튼, Active-Low
    input  wire [3:0] key_n,      // KEY1~4, Active-Low
    output wire       led_core,   // Active-High
    output wire [3:0] led_n       // LED1~4, Active-Low
);

    // ---- 클럭 ----
    wire clk;
    IBUFDS u_ibufds (.I(sys_clk_p), .IB(sys_clk_n), .O(clk));

    // ---- 비동기 입력 2단 동기화 ----
    reg [1:0] rst_sync;
    reg [3:0] key_s0, key_s1;
    always @(posedge clk) begin
        rst_sync <= {rst_sync[0], rst_n};
        key_s0   <= key_n;
        key_s1   <= key_s0;
    end
    wire rst = ~rst_sync[1];

    // ---- 1 Hz 코어 LED ----
    localparam integer HALF_SEC = CLK_HZ / 2;
    reg [27:0] cnt_core;
    reg        core_on;
    always @(posedge clk) begin
        if (rst) begin
            cnt_core <= 28'd0;
            core_on  <= 1'b0;
        end else if (cnt_core == HALF_SEC[27:0] - 28'd1) begin
            cnt_core <= 28'd0;
            core_on  <= ~core_on;
        end else begin
            cnt_core <= cnt_core + 28'd1;
        end
    end

    // ---- 캐리어 LED 순환 (약 1/3 s마다 한 칸) ----
    localparam integer STEP = CLK_HZ / 3;
    reg [27:0] cnt_step;
    reg [3:0]  ring;
    always @(posedge clk) begin
        if (rst) begin
            cnt_step <= 28'd0;
            ring     <= 4'b0001;
        end else if (cnt_step == STEP[27:0] - 28'd1) begin
            cnt_step <= 28'd0;
            ring     <= {ring[2:0], ring[3]};
        end else begin
            cnt_step <= cnt_step + 28'd1;
        end
    end

    wire [3:0] led_on = rst ? 4'b0000 : (ring | ~key_s1);

    assign led_core = core_on;
    assign led_n    = ~led_on;

    // ---- 원격 확인용 연산: sum_{i=1}^{1000} i^2 ----
    reg [31:0] cyc;
    reg [9:0]  idx;
    reg [31:0] acc;
    reg        calc_done;
    always @(posedge clk) begin
        cyc <= cyc + 32'd1;
        if (rst) begin
            idx       <= 10'd1;
            acc       <= 32'd0;
            calc_done <= 1'b0;
        end else if (!calc_done) begin
            acc <= acc + {22'd0, idx} * {22'd0, idx};
            if (idx == 10'd1000) calc_done <= 1'b1;
            else                 idx <= idx + 10'd1;
        end
    end

`ifndef SIM
    vio_p05 u_vio (
        .clk       (clk),
        .probe_in0 (cyc),
        .probe_in1 (acc),
        .probe_in2 (calc_done),
        .probe_in3 ({led_core, led_n}),
        .probe_in4 ({rst_sync[1], key_s1})
    );
`endif

endmodule
