// membrane_bank.v — on-chip 트랙의 membrane potential (12 bit)
//
// 트랙마다 row 45개, row 하나 = 뉴런 16개 × 12 bit = 192 bit. 주소 = track × 45 + row.
// simple dual port BRAM. 읽기 지연 2, 쓰기 1 cycle.
// compute_array는 한 추론에서 row마다 한 번 읽고(P0) 나중에 쓴다(P4). 같은 row를 동시에 읽고 쓰지 않는다.
//
// 깊이 2,048짜리 sub 메모리로 나눈다. 한 덩어리(768트랙 = 34,560 × 192)로 두면 Vivado가 32K × 1
// BRAM을 두 단 이어 RAMB36 384개를 썼다(P4.2 첫 합성). sub 하나는 2K × 18 BRAM 11개(198 bit)다.
// 트랙 기준 주소(track × 45)는 start 때 sub마다 따로 잡고 주소 덧셈도 sub마다 한다. 주소 하나를 BRAM 187개로
// 퍼뜨리면 배선만 8.4 ns가 걸렸다(P4.3 첫 배선).

module membrane_bank #(
    parameter N_TRACKS = 768,
    parameter AW = $clog2(N_TRACKS * 45)
)(
    input  wire          clk,
    input  wire          set_base,
    input  wire [AW-1:0] base_in,      // track × 45
    input  wire          rd_en,
    input  wire [5:0]    rd_row,
    output reg  [191:0]  rd_data,
    input  wire          wr_en,
    input  wire [5:0]    wr_row,
    input  wire [191:0]  wr_data
);

    localparam NSUB = (N_TRACKS * 45 + 2047) / 2048;

    wire [192*NSUB-1:0] q_all;
    reg  [AW-1:0]       base_s;     // 출력 선택용
    reg  [AW-1:0]       sel;
    wire [AW-1:0]       rd_addr = base_s + {{(AW-6){1'b0}}, rd_row};

    always @(posedge clk)
        if (set_base) base_s <= base_in;

    genvar s;
    generate
        for (s = 0; s < NSUB; s = s + 1) begin : g_sub
            (* ram_style = "block" *) reg [191:0] mem [0:2047];
            (* keep = "true" *) reg [AW-1:0] base;
            reg  [191:0]  q;
            (* use_dsp = "no" *) wire [AW-1:0] ra = base + {{(AW-6){1'b0}}, rd_row};
            (* use_dsp = "no" *) wire [AW-1:0] wa = base + {{(AW-6){1'b0}}, wr_row};
            always @(posedge clk) begin
                if (set_base)
                    base <= base_in;
                if (rd_en)
                    q <= mem[ra[10:0]];
                if (wr_en && (wa >> 11) == s)
                    mem[wa[10:0]] <= wr_data;
            end
            assign q_all[192*s +: 192] = q;
        end
    endgenerate

    always @(posedge clk) begin
        if (rd_en)
            sel <= rd_addr >> 11;
        rd_data <= q_all[192*sel +: 192];
    end

endmodule
