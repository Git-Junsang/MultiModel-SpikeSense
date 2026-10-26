// weight_entry.v — weight cache entry 1개 (모델 1벌)
//
// word RAM: 64 B word 2,034개(04_MEMORY.md §3). true dual port BRAM.
//   port A  compute 읽기
//   port B  compute 읽기(spike 2개/cycle의 두 번째 word) 또는 DMA 쓰기
//   DMA는 연산 중이 아닌 entry에만 쓰므로 port B를 compute와 동시에 쓰지 않는다.
//   읽기 지연 2(BRAM 출력 register 포함).
// params RAM: row 46개 × 256 bit. row r = 뉴런 16r~16r+15의 {vth, beta}.
//   slot params section의 32 B beat 하나가 row 하나다(02_MODEL.md §6). 읽기 지연 1.
//
// word 주소: layer 1 0–239, layer 2 240–1,775, layer 3 1,776–2,031, layer 4 2,032–2,033.
// lane j = word bit [8j+7:8j].

module weight_entry (
    input  wire         clk,
    // port A
    input  wire         a_en,
    input  wire [10:0]  a_addr,
    output reg  [511:0] a_dout,
    // port B
    input  wire         b_en,
    input  wire         b_we,
    input  wire [10:0]  b_addr,
    input  wire [511:0] b_din,
    output reg  [511:0] b_dout,
    // params
    input  wire         p_we,
    input  wire [5:0]   p_waddr,
    input  wire [255:0] p_din,
    input  wire [5:0]   p_raddr,
    output reg  [255:0] p_dout
);

    (* ram_style = "block" *) reg [511:0] wmem [0:2047];
    reg [511:0] a_q, b_q;

    always @(posedge clk) begin
        if (a_en)
            a_q <= wmem[a_addr];
        a_dout <= a_q;
    end

    always @(posedge clk) begin
        if (b_en) begin
            if (b_we)
                wmem[b_addr] <= b_din;
            b_q <= wmem[b_addr];
        end
        b_dout <= b_q;
    end

    (* ram_style = "distributed" *) reg [255:0] pmem [0:63];
    always @(posedge clk) begin
        if (p_we)
            pmem[p_waddr] <= p_din;
        p_dout <= pmem[p_raddr];
    end

endmodule
