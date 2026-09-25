// ============================================================
// p07_top.v — P0.7 PCIe Gen2 ×2 XDMA 보드 시험용 탑
// ============================================================
// 구성: XDMA(AXI-MM 64 bit, H2C 1 + C2H 1) → AXI BRAM 64 KiB (블록 디자인 p07_bd)
// Host는 H2C로 BRAM에 쓰고 C2H로 읽어 데이터 왕복을 확인한다.
//
// 리셋: PCIe PERST#(L16, 2026-09-23 보드 시험으로 확정 → ax7a200b_pcie.xdc)를
//   XDMA sys_rst_n에 연결한다. Host가 리셋하면 코어도 함께 초기화된다.
//   구성 직후 약 21 ms 내부 파워온 리셋을 함께 걸고, KEY1·RESET 버튼과
//   VIO probe_out0으로도 리셋할 수 있다.
//
// LED (캐리어 LED Active-Low):
//   LED1: user_lnk_up   LED2: 내부 리셋 해제   LED3: axi_aclk 약 1 Hz 점멸
//   LED4: KEY1/RESET 리셋 중   코어 LED: 200 MHz 시스템 클럭 약 0.75 Hz 점멸
//
// VIO (200 MHz 시스템 클럭 도메인, 동기화 후 샘플):
//   probe_in0 [0]   user_lnk_up
//   probe_in1 [0]   sys_rst_n (내부 리셋 해제)
//   probe_in2 [13:0] 미배정 3.3 V 핀 관찰용 (perst_cand[13:0], bit5 = L16 = PERST#)
//   probe_in3 [31:0] axi_aclk 카운터 상위 비트 (클럭 동작 확인)
//   probe_in4 [13:0] 후보 핀이 한 번이라도 High였는지 (래치)
//   probe_in5 [13:0] 후보 핀이 한 번이라도 Low였는지 (래치)
//   probe_out0 [0]  1로 두는 동안 PCIe 코어 리셋, 0으로 되돌리면 약 21 ms 뒤 해제
//   probe_out1 [0]  1로 두는 동안 래치 초기화
//
//   PERST# 찾기: 래치를 초기화하고 Host를 재부팅한 뒤 읽는다. 부팅 과정에서
//   PERST#는 반드시 Low로 떨어졌다 High로 돌아오므로, ever_high와 ever_low가
//   모두 1인 핀이 PERST#다. 200 MHz 클럭은 보드 발진기라 Host 상태와 무관하게 돈다.
// ============================================================
`timescale 1ns / 1ps

module p07_top (
    input  wire        sys_clk_p,       // 200 MHz (R4/T4)
    input  wire        sys_clk_n,
    input  wire        pcie_refclk_p,   // 100 MHz (F10/E10)
    input  wire        pcie_refclk_n,
    input  wire [1:0]  pci_exp_rxp,
    input  wire [1:0]  pci_exp_rxn,
    output wire [1:0]  pci_exp_txp,
    output wire [1:0]  pci_exp_txn,
    input  wire        rst_n,           // RESET 버튼
    input  wire [3:0]  key_n,
    input  wire        pcie_perst_n,    // L16, Host 슬롯 리셋
    input  wire [12:0] perst_cand,     // L16(PERST#)을 뺀 나머지 후보
    output wire        led_core,
    output wire [3:0]  led_n
);

    // ---- 클럭 ----
    wire clk200;
    IBUFDS u_ibufds_sys (.I(sys_clk_p), .IB(sys_clk_n), .O(clk200));

    wire refclk;
    IBUFDS_GTE2 u_ibufds_ref (
        .I(pcie_refclk_p), .IB(pcie_refclk_n), .CEB(1'b0),
        .O(refclk), .ODIV2()
    );

    // ---- 내부 파워온 리셋 (약 20 ms) ----
    wire       perst_n_i;
    IBUF u_ibuf_perst (.I(pcie_perst_n), .O(perst_n_i));
    reg [1:0]  perst_s;
    wire       vio_rst;
    reg [1:0]  vio_rst_s;
    reg [1:0]  key1_s;
    reg [21:0] por_cnt = 22'd0;
    reg        sys_rst_n = 1'b0;
    always @(posedge clk200) begin
        key1_s    <= {key1_s[0], ~key_n[0] | ~rst_n};
        perst_s   <= {perst_s[0], ~perst_n_i};
        vio_rst_s <= {vio_rst_s[0], vio_rst};
        if (key1_s[1] || vio_rst_s[1] || perst_s[1]) begin
            por_cnt   <= 22'd0;
            sys_rst_n <= 1'b0;
        end else if (por_cnt != 22'h3FFFFF) begin
            por_cnt   <= por_cnt + 22'd1;
            sys_rst_n <= 1'b0;
        end else begin
            sys_rst_n <= 1'b1;
        end
    end

    // ---- XDMA + BRAM ----
    wire axi_aclk;
    wire user_lnk_up;

    p07_bd_wrapper u_bd (
        .pcie_mgt_rxn (pci_exp_rxn),
        .pcie_mgt_rxp (pci_exp_rxp),
        .pcie_mgt_txn (pci_exp_txn),
        .pcie_mgt_txp (pci_exp_txp),
        .sys_clk      (refclk),
        .sys_rst_n    (sys_rst_n),
        .axi_aclk     (axi_aclk),
        .user_lnk_up  (user_lnk_up)
    );

    // ---- axi_aclk 동작 확인 ----
    reg [31:0] aclk_cnt;
    always @(posedge axi_aclk) aclk_cnt <= aclk_cnt + 32'd1;

    // 클럭 도메인 교차: 상태 비트만 2단 동기화, 카운터 값은 VIO 관찰용(비정밀)
    reg [1:0]  lnk_s;
    reg [13:0] cand_s0, cand_s1;
    reg [31:0] aclk_cnt_s;
    always @(posedge clk200) begin
        lnk_s      <= {lnk_s[0], user_lnk_up};
        cand_s0    <= {perst_cand[12:5], ~perst_n_i, perst_cand[4:0]};
        cand_s1    <= cand_s0;
        aclk_cnt_s <= {6'd0, aclk_cnt[31:6]};
    end

    // ---- 후보 핀 래치 (글리치 방지: 64 클럭(0.32 us) 연속 같은 값일 때만 반영) ----
    wire       lat_clr;
    reg [1:0]  lat_clr_s;
    reg [13:0] cand_prev;
    reg [5:0]  stable_cnt;
    reg [13:0] ever_high, ever_low;
    always @(posedge clk200) begin
        lat_clr_s <= {lat_clr_s[0], lat_clr};
        cand_prev <= cand_s1;
        if (cand_s1 != cand_prev) stable_cnt <= 6'd0;
        else if (stable_cnt != 6'h3F) stable_cnt <= stable_cnt + 6'd1;

        if (lat_clr_s[1]) begin
            ever_high <= 14'd0;
            ever_low  <= 14'd0;
        end else if (stable_cnt == 6'h3F) begin
            ever_high <= ever_high |  cand_s1;
            ever_low  <= ever_low  | ~cand_s1;
        end
    end

    vio_p07 u_vio (
        .clk       (clk200),
        .probe_in0 (lnk_s[1]),
        .probe_in1 (sys_rst_n),
        .probe_in2 (cand_s1),
        .probe_in3 (aclk_cnt_s),
        .probe_in4 (ever_high),
        .probe_in5 (ever_low),
        .probe_out0(vio_rst),
        .probe_out1(lat_clr)
    );

    // ---- LED ----
    reg [27:0] c200;
    always @(posedge clk200) c200 <= c200 + 28'd1;

    assign led_core = c200[27];                 // 200e6 / 2^28 ≈ 0.75 Hz
    assign led_n    = ~{key1_s[1] | vio_rst_s[1] | perst_s[1], aclk_cnt[26], sys_rst_n, lnk_s[1]};

endmodule
