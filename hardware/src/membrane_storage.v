// membrane_storage.v — membrane storage: compute_array의 membrane potential 읽기·쓰기를 트랙 자리로 보낸다
//
// track_id < N_ONCHIP이면 membrane_bank(on-chip), 아니면 membrane_buf를 거쳐 DDR3(04_MEMORY.md §5).
// compute_array는 16 bit로 읽고 쓰며, 여기서 12 bit로 포화해 저장하고 읽을 때 부호를 늘린다.
//
// 쓰는 쪽(scheduler) 규칙:
//   - track을 내놓고 can_start가 1일 때 compute_array와 같은 cycle에 start를 준다.
//   - DDR3 트랙은 먼저 pf_*로 준비한다(on-chip 트랙은 바로 받고 무시). 다음 구성원을 연산 중에 준비해 둔다.
//   - DDR3 트랙의 결과는 wb_done(wb_track) 뒤에 보낸다. 그 전에는 같은 트랙을 다시 준비하지 않는다.

module membrane_storage #(
    parameter N_ONCHIP = 768,
    parameter BANK_AW  = $clog2(N_ONCHIP * 45)
)(
    input  wire         clk,
    input  wire         rst,
    input  wire [31:0]  state_base,
    // 추론
    input  wire [9:0]   track,
    output wire         can_start,
    input  wire         start,
    input  wire         done,
    output wire         wb_done,
    output wire [9:0]   wb_track,
    // compute_array
    input  wire         m_rd_en,
    input  wire [5:0]   m_rd_row,
    output wire [255:0] m_rd_data,
    input  wire         m_wr_en,
    input  wire [5:0]   m_wr_row,
    input  wire [255:0] m_wr_data,
    // 준비
    input  wire         pf_valid,
    input  wire [9:0]   pf_track,
    input  wire         pf_reset,
    output wire         pf_ready,
    // dma
    output wire         dr_req_valid,
    input  wire         dr_req_ready,
    output wire [31:0]  dr_req_addr,
    input  wire         dr_valid,
    input  wire [255:0] dr_data,
    output wire         dw_req_valid,
    input  wire         dw_req_ready,
    output wire [31:0]  dw_req_addr,
    output wire         dw_valid,
    input  wire         dw_ready,
    output wire [255:0] dw_data,
    input  wire         dw_resp
);

    wire on_q  = (track < N_ONCHIP);
    wire on_pf = (pf_track < N_ONCHIP);

    reg cur_on;
    always @(posedge clk)
        if (start) cur_on <= on_q;
    wire [BANK_AW-1:0] base_in = track * 45;

    // 16 bit → 12 bit 포화, 12 bit → 16 bit
    reg [191:0] wr12;
    reg [255:0] rd16;
    wire [191:0] bank_q, buf_q;
    wire [191:0] rd12 = cur_on ? bank_q : buf_q;
    integer k;
    always @* begin
        for (k = 0; k < 16; k = k + 1) begin
            wr12[12*k +: 12] = ($signed(m_wr_data[16*k +: 16]) > 16'sd2047)  ? 12'h7FF :
                               ($signed(m_wr_data[16*k +: 16]) < -16'sd2048) ? 12'h800 : m_wr_data[16*k +: 12];
            rd16[16*k +: 16] = {{4{rd12[12*k+11]}}, rd12[12*k +: 12]};
        end
    end
    assign m_rd_data = rd16;

    membrane_bank #(.N_TRACKS(N_ONCHIP), .AW(BANK_AW)) u_bank (
        .clk(clk),
        .set_base(start), .base_in(base_in),
        .rd_en(m_rd_en && cur_on), .rd_row(m_rd_row), .rd_data(bank_q),
        .wr_en(m_wr_en && cur_on), .wr_row(m_wr_row), .wr_data(wr12)
    );

    wire buf_can, buf_pf_ready;
    membrane_buf u_buf (
        .clk(clk), .rst(rst), .state_base(state_base),
        .pf_valid(pf_valid && !on_pf), .pf_track(pf_track), .pf_reset(pf_reset), .pf_ready(buf_pf_ready),
        .q_track(track), .can_start(buf_can), .c_start(start && !on_q), .c_done(done && !cur_on),
        .c_rd_row(m_rd_row), .c_rd_data(buf_q),
        .c_wr_en(m_wr_en && !cur_on), .c_wr_row(m_wr_row), .c_wr_data(wr12),
        .dr_req_valid(dr_req_valid), .dr_req_ready(dr_req_ready), .dr_req_addr(dr_req_addr),
        .dr_valid(dr_valid), .dr_data(dr_data),
        .dw_req_valid(dw_req_valid), .dw_req_ready(dw_req_ready), .dw_req_addr(dw_req_addr),
        .dw_valid(dw_valid), .dw_ready(dw_ready), .dw_data(dw_data), .dw_resp(dw_resp),
        .wb_done(wb_done), .wb_track(wb_track)
    );

    assign can_start = on_q | buf_can;
    assign pf_ready  = on_pf | buf_pf_ready;

endmodule
