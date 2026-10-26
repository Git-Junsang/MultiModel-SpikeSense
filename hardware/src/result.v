// result.v — 결과 packet 만들기와 request table 칸 비우기 (06_HOST_INTERFACE.md §4.2, 03_ARCHITECTURE.md §3)
//
// 완료 기록을 done 순서대로 FIFO에 쌓는다. On-chip 트랙은 바로, DDR3 트랙은 되쓰기 응답(wb_done) 뒤에 보낸다.
// membrane_buf는 되쓰기를 done 순서대로 하므로 wb_done 수만 세면 된다.
// Request table의 {t_in, t_host, seq, model, RESET_STATE}를 읽어 32 B 결과를 만들고, 보낸 뒤 그 트랙 칸을 비운다.
// LATE = t_done > t_host + DEADLINE_US − MARGIN_US(µs, 차이로 비교). res_ok = 0이면 scheduler가 새 추론을 시작하지 않는다.

module result #(
    parameter DEPTH = 4
)(
    input  wire          clk,
    input  wire          rst,
    input  wire [31:0]   deadline_us,
    input  wire [31:0]   margin_us,
    // 완료 기록 (track_scheduler)
    input  wire          cp_valid,
    input  wire [118:0]  cp_data,
    output wire          res_ok,
    // 되쓰기 응답 (membrane_storage)
    input  wire          wb_done,
    // req_table
    output wire          mr_en,
    output wire [9:0]    mr_track,
    input  wire [86:0]   mr_data,
    output reg           free_valid,
    output reg  [9:0]    free_track,
    // 결과
    output reg           rs_valid,
    input  wire          rs_ready,
    output reg  [255:0]  rs_data,
    // 사건·상태
    output reg           ev_res_out,
    output reg           ev_late,
    output reg           ev_sat,
    output wire          empty
);

    localparam AW = $clog2(DEPTH);

    reg  [118:0] f [0:DEPTH-1];
    reg  [AW-1:0] wp, rp;
    reg  [AW:0]   n;
    reg  [2:0]    wbn;                   // 아직 쓰지 않은 wb_done 수

    wire [118:0] h     = f[rp];
    wire         h_ddr = h[0];
    wire         h_sat = h[1];
    assign res_ok = (n <= DEPTH - 2);
    assign empty  = (n == 0);

    localparam [1:0] E_IDLE = 2'd0, E_RD = 2'd1, E_OUT = 2'd2;
    reg  [1:0] es;
    reg        rdc;
    wire       go_rd = (es == E_IDLE) && (n != 0) && (!h_ddr || wbn != 3'd0);
    assign mr_en    = go_rd;
    assign mr_track = h[118:109];

    wire        rs    = mr_data[0];
    wire [5:0]  model = mr_data[6:1];
    wire [15:0] seq   = mr_data[22:7];
    wire [31:0] t_host = mr_data[54:23];
    wire [31:0] t_in  = mr_data[86:55];
    wire [31:0] t_st  = h[108:77];
    wire [31:0] t_dn  = h[76:45];
    wire [10:0] bn    = h[44:34];
    wire [31:0] lim   = t_host + deadline_us - margin_us;
    wire        late  = $signed(t_dn - lim) > 0;
    wire        pop   = (es == E_OUT) && rs_valid && rs_ready;

    always @(posedge clk) begin
        free_valid <= 1'b0;
        ev_res_out <= 1'b0;
        ev_late    <= 1'b0;
        ev_sat     <= 1'b0;
        if (rst) begin
            wp <= {AW{1'b0}}; rp <= {AW{1'b0}}; n <= {(AW+1){1'b0}};
            wbn <= 3'd0;
            es <= E_IDLE;
            rs_valid <= 1'b0;
        end else begin
            if (cp_valid) begin
                f[wp] <= cp_data;
                wp    <= wp + 1'b1;
            end
            n   <= n + {{AW{1'b0}}, cp_valid} - {{AW{1'b0}}, pop};
            wbn <= wbn + {2'd0, wb_done} - {2'd0, pop && h_ddr};

            case (es)
            E_IDLE:
                if (go_rd) begin
                    rdc <= 1'b0;
                    es  <= E_RD;
                end
            E_RD: begin                                 // req_table 읽기 지연 2
                rdc <= 1'b1;
                if (rdc) begin
                    rs_valid <= 1'b1;
                    rs_data  <= {32'd0, h[17:2], h[33:18], t_dn, t_st, t_in, t_host,
                                 {5'd0, bn}, {5'd0, late, h_sat, rs}, {2'd0, model}, seq, {6'd0, h[118:109]}};
                    es       <= E_OUT;
                end
            end
            default:                                    // E_OUT
                if (pop) begin
                    rs_valid   <= 1'b0;
                    rp         <= rp + 1'b1;
                    free_valid <= 1'b1;
                    free_track <= h[118:109];
                    ev_res_out <= 1'b1;
                    ev_late    <= late;
                    ev_sat     <= h_sat;
                    es         <= E_IDLE;
                end
            endcase
        end
    end

endmodule
