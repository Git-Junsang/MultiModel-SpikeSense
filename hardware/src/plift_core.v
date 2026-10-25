// plift_core.v — PLIF 뉴런 1개, 누설 곱 뒤 register 1단
//
// 선행 SpikeSense-Edge plift_core.v를 기준으로 세 곳을 바꿨다.
//   - current 폭을 CUR_W로 넓혔다. layer 2 전류는 최대 384 × 128 = 49,152라 16 bit를 넘는다.
//   - 적분 결과를 16 bit로 되감지 않고 포화한다(snn_int8.py의 sat16).
//   - 누설 곱(DSP) 뒤에 register를 넣었다. 한 cycle로는 100 MHz에서 10.8 ns였다(P4.1 첫 배선).
//     입력은 cycle t, 출력(spike, mem_sat, mem_out)은 cycle t+1의 조합 출력이다.
//
// 연산 순서 (02_MODEL.md §4):
//   1) 누설      decayed = (beta × mem_in) >>> 8        Q0.8, 산술 shift(내림)
//   2) 적분      mem_sat = sat16(decayed + current)
//   3) 발화      spike   = (mem_sat >= vth)
//   4) soft reset mem_out = spike ? mem_sat − vth : mem_sat
//
// beta: Q0.8 uint8, vth: uint8(1~255), membrane potential: 16 bit signed

module plift_core #(
    parameter MEM_W = 16,
    parameter CUR_W = 17
)(
    input  wire                    clk,
    input  wire signed [CUR_W-1:0] current,
    input  wire signed [MEM_W-1:0] mem_in,
    input  wire        [7:0]       beta,
    input  wire        [7:0]       vth,

    output wire                    spike,
    output wire signed [MEM_W-1:0] mem_sat,   // 포화 후·발화 전 (golden mem_pre)
    output wire signed [MEM_W-1:0] mem_out,   // soft reset 뒤 (golden mem)
    output wire                    sat        // 적분 결과가 MEM_W bit를 넘어 포화했다
);

    localparam signed [CUR_W:0] MAX = (1 <<< (MEM_W - 1)) - 1;
    localparam signed [CUR_W:0] MIN = -(1 <<< (MEM_W - 1));

    // 9 bit 양수 × 16 bit → 25 bit. |decayed| < 2^15라 >>> 8 뒤 MEM_W bit에 들어간다.
    wire signed [MEM_W+8:0] product = $signed({1'b0, beta}) * mem_in;
    reg  signed [MEM_W-1:0] decayed;
    reg  signed [CUR_W-1:0] cur_r;
    reg         [7:0]       vth_r;
    always @(posedge clk) begin
        decayed <= product[MEM_W+7:8];
        cur_r   <= current;
        vth_r   <= vth;
    end

    wire signed [CUR_W:0] sum = {{(CUR_W+1-MEM_W){decayed[MEM_W-1]}}, decayed} + {cur_r[CUR_W-1], cur_r};
    assign sat     = (sum > MAX) || (sum < MIN);
    assign mem_sat = (sum > MAX) ? MAX[MEM_W-1:0] :
                     (sum < MIN) ? MIN[MEM_W-1:0] : sum[MEM_W-1:0];

    wire signed [MEM_W-1:0] vth_ext = {{(MEM_W-8){1'b0}}, vth_r};
    assign spike   = (mem_sat >= vth_ext);
    assign mem_out = spike ? mem_sat - vth_ext : mem_sat;

endmodule
