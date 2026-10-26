// spike_list.v — spike가 1인 input 번호 목록 (spike 0 건너뛰기)
//
// plif_array가 row마다 spike 16개를 주면 1인 뉴런 번호를 목록 끝에 붙인다.
// 다음 layer는 위치 p, p+1의 번호 2개를 cycle마다 읽는다(spike 2개/cycle).
// 목록은 16 bank에 돌아가며 둔다(위치 q → bank q mod 16, 칸 q / 16).
// 한 row의 spike는 이어진 위치에 들어가므로 bank마다 cycle당 쓰기가 1개 이하다.
// 이웃한 두 위치도 bank가 달라 읽기가 겹치지 않는다. 누산 순서는 결과에 영향이 없다.
//
// 읽기 지연 1. 쓰지 않은 위치를 읽으면 값은 정해지지 않는다(호출 쪽이 버린다).

module spike_list #(
    parameter DEPTH = 24,          // bank당 칸 = layer 뉴런 수 / 16
    parameter IW    = 9            // 뉴런 번호 폭
)(
    input  wire          clk,
    input  wire          clr,      // 추론 시작: 목록 비움
    input  wire          wr_en,
    input  wire [IW-5:0] wr_row,   // layer 안 row 번호
    input  wire [15:0]   wr_spk,
    input  wire [IW:0]   rd_pos,
    output reg  [IW-1:0] rd_idx0,  // 위치 rd_pos
    output reg  [IW-1:0] rd_idx1,  // 위치 rd_pos + 1
    output reg  [IW:0]   count
);

    localparam AW = $clog2(DEPTH);

    // pre[k] = wr_spk[k-1:0]의 1 개수 = 이번 row에서 lane k가 받을 순번
    reg [4:0] pre [0:16];
    integer k;
    always @* begin
        pre[0] = 5'd0;
        for (k = 0; k < 16; k = k + 1)
            pre[k+1] = pre[k] + {4'd0, wr_spk[k]};
    end

    wire [IW*16-1:0] rd_all;

    genvar b;
    generate
        for (b = 0; b < 16; b = b + 1) begin : g_bank
            localparam [3:0] BI = b;
            (* ram_style = "distributed" *) reg [IW-1:0] mem [0:DEPTH-1];

            // 쓰기: 이 bank는 이번 row의 o번째 spike를 받는다
            wire [3:0] o = BI - count[3:0];
            reg        hit;
            reg [3:0]  sel;
            integer    j;
            always @* begin
                hit = 1'b0;
                sel = 4'd0;
                for (j = 0; j < 16; j = j + 1)
                    if (wr_spk[j] && pre[j][3:0] == o) begin
                        hit = 1'b1;
                        sel = j[3:0];
                    end
            end
            wire [IW:0] wpos = count + {{(IW-3){1'b0}}, o};
            always @(posedge clk)
                if (wr_en && hit)
                    mem[wpos[AW+3:4]] <= {wr_row, sel};

            // 읽기: rd_pos 이상인 위치 가운데 이 bank의 첫 칸
            /* verilator lint_off CMPCONST */
            wire [AW-1:0] ra = rd_pos[AW+3:4] + {{(AW-1){1'b0}}, (BI < rd_pos[3:0])};
            /* verilator lint_on CMPCONST */
            assign rd_all[IW*b +: IW] = mem[ra];
        end
    endgenerate

    wire [3:0] p1 = rd_pos[3:0] + 4'd1;
    always @(posedge clk) begin
        rd_idx0 <= rd_all[IW*rd_pos[3:0] +: IW];
        rd_idx1 <= rd_all[IW*p1 +: IW];
        if (clr)
            count <= {(IW+1){1'b0}};
        else if (wr_en)
            count <= count + {{(IW-4){1'b0}}, pre[16]};
    end

endmodule
