// ingest.v — 추론 요청 검사와 request table 등록 (03_ARCHITECTURE.md §3, 06_HOST_INTERFACE.md §4.1·§4.3)
//
// 64 B 추론 요청 하나 = rq_data 하나(byte k = bit [8k+7:8k]). 2 cycle에 하나씩 받는다.
// 검사 순서(첫 오류 하나만 err로 낸다): magic ≠ 0xA5(1, 정보 = 받은 순번), track_id ≥ N_TRACKS(2), model_id ≥ N_MODELS(3),
// x 중 하나 > 127(4), 같은 트랙의 이전 추론 요청이 아직 결과 전(5, drop). 정보는 2~5에서 track_id.
// 통과하면 req_table에 넣고 모델 목록 끝에 붙이며 predictor에 도착을 알린다. run = 0이면 오류 없이 버린다.
// n_expect(4 B)는 predictor 폭 11 bit로 포화한다.

module ingest (
    input  wire         clk,
    input  wire         rst,
    input  wire         run,
    input  wire [10:0]  n_tracks,
    input  wire [5:0]   n_models,
    input  wire [31:0]  now_us,
    // 추론 요청
    input  wire         rq_valid,
    output wire         rq_ready,
    input  wire [511:0] rq_data,
    // req_table
    output wire [9:0]   chk_track,
    input  wire         chk_pend,
    output reg          ap_valid,
    output reg  [9:0]   ap_track,
    output reg  [5:0]   ap_model,
    output reg  [31:0]  ap_aseq,
    output reg  [320:0] ap_xrs,
    output reg  [86:0]  ap_meta,
    // predictor
    output reg          arr_valid,
    output reg  [5:0]   arr_model,
    output reg  [31:0]  arr_t_host,
    output reg  [10:0]  arr_n_expect,
    // 사건
    output reg          ev_req_in,
    output reg          ev_req_drop,
    output reg          err_valid,
    output reg  [3:0]   err_code,
    output reg  [31:0]  err_info
);

    reg         s1;                      // 검사 단계에 추론 요청이 있음
    reg [511:0] q;
    reg [31:0]  rx_n;                    // 받은 추론 요청 순번
    reg [31:0]  aseq;                    // 등록한 추론 요청 순번

    assign rq_ready  = !s1;
    assign chk_track = q[25:16];

    wire [7:0]  magic  = q[7:0];
    wire        rs     = q[8];
    wire [15:0] track  = q[31:16];
    wire [15:0] seq    = q[47:32];
    wire [7:0]  model  = q[55:48];
    wire [31:0] t_host = q[95:64];
    wire [31:0] n_exp  = q[127:96];
    wire [319:0] x     = q[447:128];

    reg x_bad;
    integer b;
    always @* begin
        x_bad = 1'b0;
        for (b = 0; b < 40; b = b + 1)
            x_bad = x_bad | x[8*b + 7];
    end

    wire [3:0] code = (magic != 8'hA5)              ? 4'd1 :
                      (track >= {5'd0, n_tracks})   ? 4'd2 :
                      (model >= {2'd0, n_models})   ? 4'd3 :
                      x_bad                         ? 4'd4 :
                      chk_pend                      ? 4'd5 : 4'd0;

    always @(posedge clk) begin
        ap_valid    <= 1'b0;
        arr_valid   <= 1'b0;
        ev_req_in   <= 1'b0;
        ev_req_drop <= 1'b0;
        err_valid   <= 1'b0;
        if (rst) begin
            s1   <= 1'b0;
            rx_n <= 32'd0;
            aseq <= 32'd0;
        end else begin
            if (rq_valid && rq_ready) begin
                s1 <= 1'b1;
                q  <= rq_data;
            end
            if (s1) begin
                s1   <= 1'b0;
                rx_n <= rx_n + 32'd1;
                if (!run)
                    ev_req_drop <= 1'b1;
                else if (code != 4'd0) begin
                    ev_req_drop <= 1'b1;
                    err_valid   <= 1'b1;
                    err_code    <= code;
                    err_info    <= (code == 4'd1) ? rx_n : {16'd0, track};
                end else begin
                    ap_valid     <= 1'b1;
                    ap_track     <= track[9:0];
                    ap_model     <= model[5:0];
                    ap_aseq      <= aseq;
                    ap_xrs       <= {rs, x};
                    ap_meta      <= {now_us, t_host, seq, model[5:0], rs};
                    aseq         <= aseq + 32'd1;
                    arr_valid    <= 1'b1;
                    arr_model    <= model[5:0];
                    arr_t_host   <= t_host;
                    arr_n_expect <= (n_exp > 32'd2047) ? 11'd2047 : n_exp[10:0];
                    ev_req_in    <= 1'b1;
                end
            end
        end
    end

endmodule
