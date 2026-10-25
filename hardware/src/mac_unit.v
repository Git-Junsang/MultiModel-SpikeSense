// mac_unit.v — compute_array lane 1개, DSP48E1 하나 (pre-adder + 곱 + 누산)
//
// 선행 mac_unit.v(INT8×INT8 직렬 누산)를 pre-adder 형태로 바꿨다.
//   p = acc_clr ? m : p + m,   m = (a + d) × b
//
// layer별 사용 (03_ARCHITECTURE.md §4):
//   layer 1     a = W1, d = 0,          b = mel 입력 x_q (0~127)
//   layer 2·3   a = W(spike 1), d = W(spike 2) 또는 0, b = 1 (빈 cycle은 b = 0)
//   layer 4     a = W4[k][j], d = 0,    b = s3[j]
//
// 단계: 입력 register(A·D·B) → AD → M → P. acc_en·acc_clr은 M 단계와 같은 cycle에 준다
// (입력보다 3 cycle 늦게). 누산 폭: layer 1 |Σ| ≤ 40 × 127 × 128 = 650,240 → 21 bit.

module mac_unit #(
    parameter ACC_W = 21
)(
    input  wire                    clk,
    input  wire signed [7:0]       a,
    input  wire signed [7:0]       d,
    input  wire                    d_en,
    input  wire        [7:0]       b,
    input  wire                    acc_en,
    input  wire                    acc_clr,
    output reg  signed [ACC_W-1:0] p
);

    reg signed [7:0]  a_r, d_r;
    reg signed [8:0]  b_r, b_r2;
    reg signed [8:0]  ad_r;
    reg signed [17:0] m_r;
    wire signed [ACC_W-1:0] m_x = {{(ACC_W-18){m_r[17]}}, m_r};

    always @(posedge clk) begin
        a_r  <= a;
        d_r  <= d_en ? d : 8'sd0;      // DSP RSTD
        b_r  <= $signed({1'b0, b});
        ad_r <= a_r + d_r;
        b_r2 <= b_r;
        m_r  <= ad_r * b_r2;
        if (acc_en)
            p <= acc_clr ? m_x : p + m_x;
    end

endmodule
