// req_table.v — request table: 트랙마다 추론 요청 1개와 모델별 대기 목록 (03_ARCHITECTURE.md §2·§3)
//
// 트랙 칸: {RESET_STATE, x} 321 bit(연산 입력), {t_in, t_host, seq, model, RESET_STATE} 87 bit(결과용). BRAM, 읽기 지연 2.
// pend[트랙]: 추론 요청을 받았고 결과를 아직 보내지 않았다. ingest가 켜고 result가 끈다(drop 규칙, 06 §4.3).
// 모델별 대기 목록: 도착 순서의 linked list(next[트랙]). head·tail·수·head의 도착 순번을 모델마다 둔다.
//   추가(ingest)는 tail 뒤에 붙인다. 떼어 내기(track_scheduler)는 batch를 시작할 때 목록 전체를 가져가고 목록을 비운다.
//   같은 cycle에 같은 모델을 떼어 내고 추가하면 추가한 추론 요청은 새 목록의 첫 항목이 된다(이번 batch에 안 든다).
// 트랙마다 대기 추론 요청은 하나뿐이라(drop 규칙) next[트랙]은 그 추론 요청의 결과를 보낼 때까지 바뀌지 않는다.

module req_table #(
    parameter N_TRACKS = 1024,
    parameter N_MODELS = 40
)(
    input  wire                clk,
    input  wire                rst,
    // ingest: 확인과 추가
    input  wire [9:0]          chk_track,
    output wire                chk_pend,
    input  wire                ap_valid,
    input  wire [9:0]          ap_track,
    input  wire [5:0]          ap_model,
    input  wire [31:0]         ap_aseq,       // 도착 순번
    input  wire [320:0]        ap_xrs,        // {RESET_STATE, x}
    input  wire [86:0]         ap_meta,       // {t_in, t_host, seq, model, RESET_STATE}
    // 대기 목록
    output wire [N_MODELS-1:0] q_ne,          // 모델별 대기 추론 요청 있음
    output reg  [10:0]         q_total,       // 대기 추론 요청 수
    input  wire [5:0]          sc_model,      // 가장 오래된 추론 요청 찾기
    output wire                sc_ne,
    output wire [31:0]         sc_hseq,
    input  wire [5:0]          hd_model,      // 다음 batch 첫 추론 요청
    output wire [9:0]          hd_head,
    input  wire                dt_valid,      // Batch 시작: 목록 떼어 내기
    input  wire [5:0]          dt_model,
    output wire [10:0]         dt_cnt,
    input  wire [9:0]          nx_track,      // Batch 안 다음 추론 요청
    output wire [9:0]          nx_next,
    // 연산 입력 읽기
    input  wire                xr_en,
    input  wire [9:0]          xr_track,
    output reg  [320:0]        xr_data,
    // 결과용 읽기
    input  wire                mr_en,
    input  wire [9:0]          mr_track,
    output reg  [86:0]         mr_data,
    // 결과를 보낸 뒤 칸 비우기
    input  wire                free_valid,
    input  wire [9:0]          free_track,
    output reg  [10:0]         n_pend         // 결과 전인 추론 요청 수
);

    // ---------------- 트랙 칸 ----------------
    (* ram_style = "block" *) reg [320:0] xmem [0:N_TRACKS-1];
    (* ram_style = "block" *) reg [86:0]  meta [0:N_TRACKS-1];
    (* ram_style = "distributed" *) reg [9:0] nxt [0:N_TRACKS-1];
    reg [320:0] xq;
    reg [86:0]  mq;

    always @(posedge clk) begin
        if (ap_valid) begin
            xmem[ap_track] <= ap_xrs;
            meta[ap_track] <= ap_meta;
        end
        if (xr_en) xq <= xmem[xr_track];
        if (mr_en) mq <= meta[mr_track];
        xr_data <= xq;
        mr_data <= mq;
    end

    reg [N_TRACKS-1:0] pend;
    assign chk_pend = pend[chk_track];

    always @(posedge clk) begin
        if (rst) begin
            pend   <= {N_TRACKS{1'b0}};
            n_pend <= 11'd0;
        end else begin
            if (free_valid) pend[free_track] <= 1'b0;
            if (ap_valid)   pend[ap_track]   <= 1'b1;
            n_pend <= n_pend + {10'd0, ap_valid} - {10'd0, free_valid};
        end
    end

    // ---------------- 모델별 대기 목록 ----------------
    reg [9:0]  head [0:N_MODELS-1];
    reg [9:0]  tail [0:N_MODELS-1];
    reg [10:0] cnt  [0:N_MODELS-1];
    reg [31:0] hseq [0:N_MODELS-1];

    wire same = ap_valid && dt_valid && (ap_model == dt_model);
    wire link = ap_valid && (cnt[ap_model] != 11'd0) && !same;

    assign sc_ne   = (cnt[sc_model] != 11'd0);
    assign sc_hseq = hseq[sc_model];
    assign hd_head = head[hd_model];
    assign dt_cnt  = cnt[dt_model];
    assign nx_next = nxt[nx_track];

    genvar g;
    generate
        for (g = 0; g < N_MODELS; g = g + 1) begin : g_ne
            assign q_ne[g] = (cnt[g] != 11'd0);
        end
    endgenerate

    always @(posedge clk)
        if (link) nxt[tail[ap_model]] <= ap_track;

    integer i;
    always @(posedge clk) begin
        if (rst) begin
            for (i = 0; i < N_MODELS; i = i + 1) cnt[i] <= 11'd0;
            q_total <= 11'd0;
        end else begin
            if (dt_valid) cnt[dt_model] <= 11'd0;
            if (ap_valid) begin
                if (cnt[ap_model] == 11'd0 || same) begin
                    head[ap_model] <= ap_track;
                    hseq[ap_model] <= ap_aseq;
                    cnt[ap_model]  <= 11'd1;
                end else
                    cnt[ap_model]  <= cnt[ap_model] + 11'd1;
                tail[ap_model] <= ap_track;
            end
            q_total <= q_total + {10'd0, ap_valid} - (dt_valid ? dt_cnt : 11'd0);
        end
    end

endmodule
