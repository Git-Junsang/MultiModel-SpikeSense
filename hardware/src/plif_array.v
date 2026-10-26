// plif_array.v — PLIF 16뉴런/cycle, 지연 2 (plift_core 안 1단 + 출력 register)
//
// cycle마다 row 하나(뉴런 16개)를 받는다. lane k = 뉴런 16 × row + k.
// 묶음 bus는 lane k가 [W×k +: W]다. params는 {vth, beta} 16 bit (params.hex 순서).

module plif_array #(
    parameter CUR_W = 17
)(
    input  wire                  clk,
    input  wire [16*CUR_W-1:0]   cur,
    input  wire [255:0]          mem_in,
    input  wire [255:0]          params,

    output reg  [15:0]           spk,
    output reg  [255:0]          mem_sat,
    output reg  [255:0]          mem_out,
    output reg  [15:0]           sat        // lane마다 16 bit 포화
);

    genvar k;
    generate
        for (k = 0; k < 16; k = k + 1) begin : g_lane
            wire        s, st;
            wire [15:0] ms, mo;
            plift_core #(.MEM_W(16), .CUR_W(CUR_W)) u_core (
                .clk     (clk),
                .current (cur[CUR_W*k +: CUR_W]),
                .mem_in  (mem_in[16*k +: 16]),
                .beta    (params[16*k +: 8]),
                .vth     (params[16*k+8 +: 8]),
                .spike   (s),
                .mem_sat (ms),
                .mem_out (mo),
                .sat     (st)
            );
            always @(posedge clk) begin
                spk[k]              <= s;
                sat[k]              <= st;
                mem_sat[16*k +: 16] <= ms;
                mem_out[16*k +: 16] <= mo;
            end
        end
    endgenerate

endmodule
