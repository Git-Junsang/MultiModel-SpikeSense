// mdio_master.v — MDIO master(IEEE 802.3 Clause 22). 한 번에 읽기 또는 쓰기 하나 (P5.3 결과 손실 조사)
//
// Frame 64 bit = preamble 1 × 32, ST 01, OP(01 쓰기, 10 읽기), PHYAD 5, REGAD 5, TA(쓰기 10, 읽기 Z0), DATA 16.
// MDC = clk / (2·DIV). bit b는 MDC가 0인 동안 내고 PHY는 상승 edge b에서 잡는다.
// 읽기 데이터는 PHY가 상승 edge b−1 뒤(≤ 300 ns) 내므로 상승 edge b에서 잡는다(bit 48–63 = D15~D0).
// 쉬는 동안 MDC 0, MDIO Z. 바쁠 때 온 명령은 버린다.

`timescale 1ns / 1ps

module mdio_master #(
    parameter DIV = 32                       // 100 MHz면 MDC 1.56 MHz
)(
    input  wire        clk,
    input  wire        rst,
    input  wire        cmd_valid,
    input  wire [1:0]  cmd_op,               // 2'b01 쓰기, 2'b10 읽기
    input  wire [4:0]  cmd_phy,
    input  wire [4:0]  cmd_reg,
    input  wire [15:0] cmd_data,
    output reg         busy = 1'b0,
    output reg  [15:0] rdata,
    output reg         mdc = 1'b0,
    inout  wire        mdio
);

    reg  [63:0] sh;
    reg  [6:0]  b;                           // 지금 bit
    localparam DW = $clog2(DIV);
    localparam integer DV_LAST = DIV - 1;
    reg  [DW-1:0] dv;
    reg         rd, oe = 1'b0, mo = 1'b1;
    reg  [1:0]  mi;                          // MDIO 입력 동기화
    assign mdio = oe ? mo : 1'bz;

    always @(posedge clk) begin
        mi <= {mi[0], mdio};
        if (rst) begin
            busy <= 1'b0; mdc <= 1'b0; oe <= 1'b0; mo <= 1'b1; dv <= {DW{1'b0}};
        end else if (!busy) begin
            mdc <= 1'b0;
            oe  <= 1'b0;
            if (cmd_valid && (cmd_op == 2'b01 || cmd_op == 2'b10)) begin
                busy <= 1'b1;
                rd   <= cmd_op == 2'b10;
                sh   <= {32'hFFFF_FFFF, 2'b01, cmd_op, cmd_phy, cmd_reg, cmd_op == 2'b01 ? 2'b10 : 2'b11,
                         cmd_op == 2'b01 ? cmd_data : 16'hFFFF};
                b    <= 7'd0;
                dv   <= {DW{1'b0}};
            end
        end else begin
            dv <= dv + 1'b1;
            if (dv == {DW{1'b0}}) begin
                if (!mdc) begin                  // MDC 0 반주기 시작: bit b를 낸다
                    if (b == 7'd64) begin
                        busy <= 1'b0;
                        oe   <= 1'b0;
                    end else begin
                        oe <= !rd || b < 7'd46;      // 읽기는 TA부터 PHY가 낸다
                        mo <= sh[63];
                        sh <= {sh[62:0], 1'b1};
                    end
                end
            end
            if (dv == DV_LAST[DW-1:0]) begin
                dv  <= {DW{1'b0}};
                mdc <= !mdc;
                if (!mdc) begin                  // 상승 edge b
                    if (rd && b >= 7'd48) rdata <= {rdata[14:0], mi[1]};
                    b <= b + 7'd1;
                end
            end
        end
    end

endmodule
