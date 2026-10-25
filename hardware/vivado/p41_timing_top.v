// ============================================================
// p41_timing_top.v — P4.1 timing 확인용 wrapper (out-of-context)
// ============================================================
// compute_array + weight_entry 4개 + entry 출력 4:1 mux + membrane potential RAM(1트랙).
// 03_ARCHITECTURE.md §6의 위험(entry 출력 mux, adder tree)을 첫 합성에서 본다.
// cache 교체·dma는 없다(P4.3, P4.4). 적재 port는 밖에서 바로 쓴다.
// ============================================================
`timescale 1ns / 1ps

module p41_timing_top (
    input  wire         clk,
    input  wire         rst,
    input  wire         start,
    input  wire         reset_state,
    input  wire [319:0] x_in,
    input  wire [1:0]   sel,           // 연산할 entry
    input  wire [1:0]   ld_sel,        // 적재할 entry
    input  wire         ld_we,
    input  wire [10:0]  ld_addr,
    input  wire [511:0] ld_din,
    input  wire         ld_pwe,
    input  wire [5:0]   ld_paddr,
    input  wire [255:0] ld_pdin,
    output wire         busy,
    output wire         done,
    output wire [15:0]  out_mem0,
    output wire [15:0]  out_mem1
);

    reg  [1:0]   sel_q;
    wire         w_en, m_rd_en, m_wr_en;
    wire [10:0]  w_a_addr, w_b_addr;
    wire [5:0]   p_addr, m_rd_row, m_wr_row;
    wire [255:0] m_wr_data;
    reg  [255:0] m_q1, m_rd_data;

    wire [511:0] a_d [0:3];
    wire [511:0] b_d [0:3];
    wire [255:0] p_d [0:3];

    always @(posedge clk)
        if (!busy) sel_q <= sel;

    genvar e;
    generate
        for (e = 0; e < 4; e = e + 1) begin : g_entry
            wire mine = (ld_sel == e) && ld_we;
            weight_entry u_entry (
                .clk(clk),
                .a_en(w_en && sel_q == e), .a_addr(w_a_addr), .a_dout(a_d[e]),
                .b_en((w_en && sel_q == e) || mine), .b_we(mine), .b_addr(mine ? ld_addr : w_b_addr),
                .b_din(ld_din), .b_dout(b_d[e]),
                .p_we(ld_pwe && ld_sel == e), .p_waddr(ld_paddr), .p_din(ld_pdin),
                .p_raddr(p_addr), .p_dout(p_d[e])
            );
        end
    endgenerate

    compute_array u_ca (
        .clk(clk), .rst(rst),
        .start(start), .reset_state(reset_state), .x_in(x_in),
        .busy(busy), .done(done), .out_mem0(out_mem0), .out_mem1(out_mem1),
        .w_en(w_en), .w_a_addr(w_a_addr), .w_b_addr(w_b_addr),
        .w_a_data(a_d[sel_q]), .w_b_data(b_d[sel_q]), .p_addr(p_addr), .p_data(p_d[sel_q]),
        .m_rd_en(m_rd_en), .m_rd_row(m_rd_row), .m_rd_data(m_rd_data),
        .m_wr_en(m_wr_en), .m_wr_row(m_wr_row), .m_wr_data(m_wr_data),
        .dbg_cur(), .dbg_mem_sat(), .dbg_spk()
    );

    (* ram_style = "block" *) reg [255:0] mem [0:63];
    always @(posedge clk) begin
        if (m_rd_en)
            m_q1 <= mem[m_rd_row];
        m_rd_data <= m_q1;
        if (m_wr_en)
            mem[m_wr_row] <= m_wr_data;
    end

endmodule
