// ============================================================
// p06_top.v — P0.6 MIG DDR3 예제 설계 보드 시험용 탑
// ============================================================
// MIG 예제 설계(example_top: MIG + AXI4 트래픽 생성기)를 감싸고 결과를
// LED와 VIO(JTAG)로 내보낸다. example_top은 build_p06.tcl이 MIG에서
// 생성한 뒤 ui_clk 출력 포트만 덧붙인 사본을 쓴다.
//
// LED (캐리어 LED는 Active-Low):
//   LED1 (led_n[0]) : init_calib_complete — 캘리브레이션 완료 시 켜짐
//   LED2 (led_n[1]) : 오류 래치 — tg_compare_error가 한 번이라도 1이면 켜짐
//   LED3 (led_n[2]) : ui_clk 1 Hz 점멸 — MIG 클럭 동작
//   LED4 (led_n[3]) : 꺼짐
//   코어 LED         : 캘리브레이션 완료 후 오류가 없으면 켜짐
// 버튼:
//   RESET  : MIG sys_rst (Active-Low)
//   KEY1   : 오류 래치·시간 카운터 초기화
//
// VIO 입력 probe (ui_clk 도메인):
//   probe_in0 [0] init_calib_complete
//   probe_in1 [0] tg_compare_error (현재값)
//   probe_in2 [0] 오류 래치
//   probe_in3 [31:0] 캘리브레이션 완료 후 경과 초(오류와 무관하게 증가)
//   probe_in4 [31:0] 오류 래치가 처음 켜진 시점의 경과 초
// ============================================================
`timescale 1ns / 1ps

module p06_top (
    input  wire        sys_clk_p,
    input  wire        sys_clk_n,
    input  wire        rst_n,
    input  wire [3:0]  key_n,

    inout  wire [31:0] ddr3_dq,
    inout  wire [3:0]  ddr3_dqs_n,
    inout  wire [3:0]  ddr3_dqs_p,
    output wire [14:0] ddr3_addr,
    output wire [2:0]  ddr3_ba,
    output wire        ddr3_ras_n,
    output wire        ddr3_cas_n,
    output wire        ddr3_we_n,
    output wire        ddr3_reset_n,
    output wire [0:0]  ddr3_ck_p,
    output wire [0:0]  ddr3_ck_n,
    output wire [0:0]  ddr3_cke,
    output wire [0:0]  ddr3_cs_n,
    output wire [3:0]  ddr3_dm,
    output wire [0:0]  ddr3_odt,

    output wire        led_core,
    output wire [3:0]  led_n
);

    localparam integer UI_HZ = 100_000_000;   // 400 MHz 메모리 클럭, 4:1

    wire ui_clk;
    wire init_calib_complete;
    wire tg_compare_error;

    example_top u_ex (
        .ddr3_dq            (ddr3_dq),
        .ddr3_dqs_n         (ddr3_dqs_n),
        .ddr3_dqs_p         (ddr3_dqs_p),
        .ddr3_addr          (ddr3_addr),
        .ddr3_ba            (ddr3_ba),
        .ddr3_ras_n         (ddr3_ras_n),
        .ddr3_cas_n         (ddr3_cas_n),
        .ddr3_we_n          (ddr3_we_n),
        .ddr3_reset_n       (ddr3_reset_n),
        .ddr3_ck_p          (ddr3_ck_p),
        .ddr3_ck_n          (ddr3_ck_n),
        .ddr3_cke           (ddr3_cke),
        .ddr3_cs_n          (ddr3_cs_n),
        .ddr3_dm            (ddr3_dm),
        .ddr3_odt           (ddr3_odt),
        .sys_clk_p          (sys_clk_p),
        .sys_clk_n          (sys_clk_n),
        .tg_compare_error   (tg_compare_error),
        .init_calib_complete(init_calib_complete),
        .sys_rst            (rst_n),
        .ui_clk_o           (ui_clk)
    );

    // ---- 비동기 입력 동기화 (ui_clk) ----
    reg [1:0] calib_s, key1_s;
    always @(posedge ui_clk) begin
        calib_s <= {calib_s[0], init_calib_complete};
        key1_s  <= {key1_s[0], ~key_n[0]};
    end
    wire calib = calib_s[1];
    wire clear = key1_s[1];

    // ---- 1초 틱 ----
    reg [26:0] tick_cnt;
    reg        tick;
    always @(posedge ui_clk) begin
        tick <= 1'b0;
        if (tick_cnt == UI_HZ - 1) begin
            tick_cnt <= 27'd0;
            tick     <= 1'b1;
        end else begin
            tick_cnt <= tick_cnt + 27'd1;
        end
    end

    reg blink;
    always @(posedge ui_clk) if (tick) blink <= ~blink;

    // ---- 경과 시간·오류 래치 ----
    reg [31:0] run_sec, err_sec;
    reg        err_latch;
    always @(posedge ui_clk) begin
        if (clear || !calib) begin
            run_sec   <= 32'd0;
            err_sec   <= 32'd0;
            err_latch <= 1'b0;
        end else begin
            if (tick) run_sec <= run_sec + 32'd1;
            if (tg_compare_error && !err_latch) begin
                err_latch <= 1'b1;
                err_sec   <= run_sec;
            end
        end
    end

    vio_p06 u_vio (
        .clk       (ui_clk),
        .probe_in0 (init_calib_complete),
        .probe_in1 (tg_compare_error),
        .probe_in2 (err_latch),
        .probe_in3 (run_sec),
        .probe_in4 (err_sec)
    );

    assign led_n    = ~{1'b0, blink, err_latch, calib};
    assign led_core = calib & ~err_latch;

endmodule
