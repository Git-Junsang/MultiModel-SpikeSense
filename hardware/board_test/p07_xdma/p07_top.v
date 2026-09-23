// ============================================================
// p07_top.v — P0.7 PCIe Gen2 ×2 XDMA 보드 시험용 탑
// ============================================================
// 구성: XDMA(AXI-MM 64 bit, H2C 1 + C2H 1) → AXI BRAM 64 KiB (블록 디자인 p07_bd)
// Host는 H2C로 BRAM에 쓰고 C2H로 읽어 데이터 왕복을 확인한다.
//
// 리셋: PCIe PERST# 핀이 매뉴얼에 없어(ENVIRONMENT.md §5) 연결하지 않는다.
//   대신 구성(configuration) 직후 200 MHz 시스템 클럭으로 약 20 ms 동안
//   sys_rst_n을 Low로 유지하는 내부 파워온 리셋을 쓴다. KEY1을 누르면 다시
//   리셋한다(RESET 버튼도 같다). Host 재부팅 중 PERST#에 따른 재초기화는 되지 않는다.
//
// PERST# 후보 확인: 매뉴얼 보드 간 커넥터 표에서 캐리어 주변장치에 배정되지
//   않은 3.3 V 핀 14개를 풀다운 입력으로 받아 VIO로 읽는다. Host가 켜져 있으면
//   PERST#는 High이므로, High로 읽히는 핀이 후보다.
//
// LED (캐리어 LED Active-Low):
//   LED1: user_lnk_up   LED2: 내부 리셋 해제   LED3: axi_aclk 약 1 Hz 점멸
//   LED4: KEY1/RESET 리셋 중   코어 LED: 200 MHz 시스템 클럭 약 0.75 Hz 점멸
//
// VIO (200 MHz 시스템 클럭 도메인, 동기화 후 샘플):
//   probe_in0 [0]   user_lnk_up
//   probe_in1 [0]   sys_rst_n (내부 리셋 해제)
//   probe_in2 [13:0] PERST# 후보 핀 (perst_cand[13:0])
//   probe_in3 [31:0] axi_aclk 카운터 상위 비트 (클럭 동작 확인)
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
    input  wire [13:0] perst_cand,
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
    reg [1:0]  key1_s;
    reg [21:0] por_cnt = 22'd0;
    reg        sys_rst_n = 1'b0;
    always @(posedge clk200) begin
        key1_s <= {key1_s[0], ~key_n[0] | ~rst_n};
        if (key1_s[1]) begin
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
        cand_s0    <= perst_cand;
        cand_s1    <= cand_s0;
        aclk_cnt_s <= {6'd0, aclk_cnt[31:6]};
    end

    vio_p07 u_vio (
        .clk       (clk200),
        .probe_in0 (lnk_s[1]),
        .probe_in1 (sys_rst_n),
        .probe_in2 (cand_s1),
        .probe_in3 (aclk_cnt_s)
    );

    // ---- LED ----
    reg [27:0] c200;
    always @(posedge clk200) c200 <= c200 + 28'd1;

    assign led_core = c200[27];                 // 200e6 / 2^28 ≈ 0.75 Hz
    assign led_n    = ~{key1_s[1], aclk_cnt[26], sys_rst_n, lnk_s[1]};

endmodule
