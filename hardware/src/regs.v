// regs.v — register block: AXI4-Lite slave, 주소표·시각·counter·첫 오류 (06_HOST_INTERFACE.md §5·§7, P4.6)
//
// 주소는 06 §7 표 그대로다. 주소 bit [1:0]은 보지 않는다. 없는 주소를 읽으면 0, 쓰면 무시한다.
// wstrb == 4'hF인 쓰기만 반영한다. 응답은 늘 OKAY. 쓰기는 AW와 W가 둘 다 valid일 때 함께 받는다.
// RUN = 1이면 설정(0x0300~)과 PNU 표 창(0x1000–0x2FFF) 쓰기를 무시한다. CTRL은 언제나 쓸 수 있다.
//   범위 밖 N_TRACKS(0, > 1,024)·N_MODELS(0, > 40)도 무시한다.
// PNU 표 창 쓰기는 cfg_we 1 cycle, cfg_addr = (addr − 0x1000) >> 2, cfg_data = wdata[15:0]으로 넘긴다. 읽으면 0.
// CTRL: bit0 RUN, bit1 SOFT_RESET, bit2 CNT_CLEAR, bit3 ERR_CLEAR. 1–3은 쓰면 한 번, 읽으면 0.
//   SOFT_RESET은 RUN을 0으로 하고 core_rst를 다음 cycle부터 4 cycle 낸다. 설정 값은 rst로만 초기화한다.
//   cnt_clear는 쓰기 다음 cycle에 1 cycle 낸다.
// 0x0440–0x046C: eth_link 진단 counter(결과 받음, UDP 머리, MAC FIFO good·bad·overflow, 송신 underflow, IP·UDP payload 조기 종료,
//   ARP 실패, 링크 속도 바뀜, 수신 FCS 오류, 수신 FIFO overflow). eth_link 안에서 세고 CNT_CLEAR·core_rst로 0.
// LINK_TUNE(0x0318): bit[4:0] RGMII 수신 IDELAY tap, bit[31:16] 송신 clock 위상(90°에서 옮길 MMCM 미세 단계, 부호 있음).
//   나머지 bit는 0으로 읽힌다. 보드에서 frame 오류를 보며 맞추는 보정값이다(P4.10).
// 시각(100 MHz): now_cyc 매 cycle +1, now_us 100 cycle마다 +1, phase_us 0–31,999, 넘칠 때 period +1. core_rst로 0.
//   first_period는 core_rst 뒤 첫 phase 넘침까지 1이다. period(16 bit)가 한 바퀴 돌아 0이 되어도 다시 1이 되지 않는다.
// counter는 cnt_clear·core_rst로 0. 같은 cycle의 사건은 버린다. 32 bit counter는 넘치면 0부터 다시 센다.
// 64 bit 값은 값마다 HI 그림자를 두고 LO를 읽을 때 HI를 잡는다. HI 주소는 그림자를 읽는다.
// 오류: 오류가 없을 때 들어온 첫 오류만 잡는다. 같은 cycle이면 err0 > err1 > err2. ERR_CLEAR와 같은 cycle의
//   새 오류는 잡는다. core_rst로 지운다.

module regs #(
    parameter        N_ENTRY  = 4,
    parameter        N_ON_CHIP = 768,
    parameter [31:0] VERSION  = 32'h0001_0000,
    parameter [31:0] LINK_TUNE0 = 32'h0000_0001
)(
    input  wire        clk,
    input  wire        rst,
    // AXI4-Lite slave
    input  wire [31:0] s_axil_awaddr,
    input  wire        s_axil_awvalid,
    output wire        s_axil_awready,
    input  wire [31:0] s_axil_wdata,
    input  wire [3:0]  s_axil_wstrb,
    input  wire        s_axil_wvalid,
    output wire        s_axil_wready,
    output wire [1:0]  s_axil_bresp,
    output reg         s_axil_bvalid,
    input  wire        s_axil_bready,
    input  wire [31:0] s_axil_araddr,
    input  wire        s_axil_arvalid,
    output wire        s_axil_arready,
    output reg  [31:0] s_axil_rdata,
    output wire [1:0]  s_axil_rresp,
    output reg         s_axil_rvalid,
    input  wire        s_axil_rready,
    // 상태
    input  wire        mig_calib,
    input  wire        sys_idle,
    // 제어
    output reg         run,
    output wire        core_rst,
    output reg         cnt_clear,
    // MDIO(0x0108): 쓰기 = {op[31:30], 0, phy[25:21], reg[20:16], 데이터[15:0]} 명령, 읽기 = {busy, 0, 데이터[15:0]}
    output reg         md_valid,
    output reg  [31:0] md_cmd,
    input  wire        md_busy,
    input  wire [15:0] md_rdata,
    // 설정
    output reg  [10:0] n_tracks,
    output reg  [5:0]  n_models,
    output reg  [31:0] model_base,
    output reg  [31:0] state_base,
    output reg  [31:0] deadline_us,
    output reg  [31:0] margin_us,
    output reg  [31:0] link_tune,
    // PNU 표 → accel_core
    output reg         cfg_we,
    output reg  [10:0] cfg_addr,
    output reg  [15:0] cfg_data,
    // 시각
    output reg  [31:0] now_us,
    output reg  [63:0] now_cyc,
    output reg  [14:0] phase_us,
    output reg  [15:0] period,
    output reg         first_period,
    // counter 사건
    input  wire        ev_req_in,
    input  wire        ev_req_drop,
    input  wire        ev_res_out,
    input  wire        ev_late,
    input  wire        ev_batch,
    input  wire        ev_load,
    input  wire        ev_sat,
    input  wire [1:0]  ev_state_xfer,
    input  wire [10:0] pending_n,
    input  wire        cmp_busy,
    input  wire [63:0] stall_cyc,
    input  wire [383:0] link_dbg,            // eth_link 진단 counter 12개(읽기 전용, 0x0440–0x046C)
    // 오류
    input  wire        err0_valid,
    input  wire [3:0]  err0_code,
    input  wire [31:0] err0_info,
    input  wire        err1_valid,
    input  wire [31:0] err1_info,
    input  wire        err2_valid,
    input  wire [31:0] err2_info
);

    // ---------------- AXI4-Lite ----------------
    wire wr = s_axil_awvalid && s_axil_wvalid && !s_axil_bvalid;
    wire rd = s_axil_arvalid && !s_axil_rvalid;
    assign s_axil_awready = wr;
    assign s_axil_wready  = wr;
    assign s_axil_arready = !s_axil_rvalid;
    assign s_axil_bresp   = 2'b00;
    assign s_axil_rresp   = 2'b00;

    wire [31:0] wa  = {s_axil_awaddr[31:2], 2'b00};
    wire [31:0] ra  = {s_axil_araddr[31:2], 2'b00};
    wire        we  = wr && s_axil_wstrb == 4'hF;
    wire [31:0] wd  = s_axil_wdata;
    wire        wcf = we && !run;                       // 설정·PNU 표 쓰기 허용
    wire        wctl = we && wa == 32'h0104;
    wire [11:0] pnu_off = s_axil_awaddr[13:2] - 12'h400;

    // ---------------- 제어·설정 ----------------
    reg [2:0] sr_cnt;
    assign core_rst = rst || sr_cnt != 3'd0;

    always @(posedge clk) begin
        if (rst) begin
            run <= 1'b0; sr_cnt <= 3'd0; cnt_clear <= 1'b0; md_valid <= 1'b0; md_cmd <= 32'd0;
            n_tracks <= 11'd1024; n_models <= 6'd40;
            model_base <= 32'h0000_0000; state_base <= 32'h0200_0000;
            deadline_us <= 32'd32000; margin_us <= 32'd0; link_tune <= LINK_TUNE0;
            cfg_we <= 1'b0; cfg_addr <= 11'd0; cfg_data <= 16'd0;
        end else begin
            cnt_clear <= wctl && wd[2];
            md_valid  <= we && wa == 32'h0108;     // CTRL block처럼 RUN과 상관없이 쓴다
            if (we && wa == 32'h0108) md_cmd <= wd;
            if (wctl) run <= wd[0] && !wd[1];
            if (wctl && wd[1]) sr_cnt <= 3'd4;
            else if (sr_cnt != 3'd0) sr_cnt <= sr_cnt - 3'd1;
            if (wcf) begin
                case (wa)
                32'h0300: if (wd != 32'd0 && wd <= 32'd1024) n_tracks <= wd[10:0];
                32'h0304: if (wd != 32'd0 && wd <= 32'd40)   n_models <= wd[5:0];
                32'h0308: model_base  <= wd;
                32'h030C: state_base  <= wd;
                32'h0310: deadline_us <= wd;
                32'h0314: margin_us   <= wd;
                32'h0318: link_tune   <= {wd[31:16], 11'd0, wd[4:0]};
                default: ;
                endcase
            end
            cfg_we <= wcf && wa >= 32'h1000 && wa < 32'h3000;
            if (wcf) begin cfg_addr <= pnu_off[10:0]; cfg_data <= wd[15:0]; end
        end
    end

    // ---------------- 시각 ----------------
    reg [6:0] div;

    always @(posedge clk) begin
        if (core_rst) begin
            now_cyc <= 64'd0; div <= 7'd0; now_us <= 32'd0; phase_us <= 15'd0; period <= 16'd0;
            first_period <= 1'b1;
        end else begin
            now_cyc <= now_cyc + 64'd1;
            if (div == 7'd99) begin
                div <= 7'd0;
                now_us <= now_us + 32'd1;
                if (phase_us == 15'd31999) begin phase_us <= 15'd0; period <= period + 16'd1; first_period <= 1'b0; end
                else phase_us <= phase_us + 15'd1;
            end else
                div <= div + 7'd1;
        end
    end

    // ---------------- counter ----------------
    reg [31:0] c_req_in, c_req_drop, c_res_out, c_late, c_batch, c_load, c_sat;
    reg [10:0] c_max_pend;
    reg [63:0] c_wbytes, c_sbytes, c_busy;
    wire       cclr = cnt_clear || core_rst;

    always @(posedge clk) begin
        if (cclr) begin
            c_req_in <= 32'd0; c_req_drop <= 32'd0; c_res_out <= 32'd0; c_late <= 32'd0;
            c_batch <= 32'd0; c_load <= 32'd0; c_sat <= 32'd0; c_max_pend <= 11'd0;
            c_wbytes <= 64'd0; c_sbytes <= 64'd0; c_busy <= 64'd0;
        end else begin
            c_req_in   <= c_req_in   + {31'd0, ev_req_in};
            c_req_drop <= c_req_drop + {31'd0, ev_req_drop};
            c_res_out  <= c_res_out  + {31'd0, ev_res_out};
            c_late     <= c_late     + {31'd0, ev_late};
            c_batch    <= c_batch    + {31'd0, ev_batch};
            c_load     <= c_load     + {31'd0, ev_load};
            c_sat      <= c_sat      + {31'd0, ev_sat};
            if (pending_n > c_max_pend) c_max_pend <= pending_n;
            if (ev_load) c_wbytes <= c_wbytes + 64'd131648;
            c_sbytes <= c_sbytes + {62'd0, ev_state_xfer} * 64'd1088;
            c_busy   <= c_busy + {63'd0, cmp_busy};
        end
    end

    // ---------------- 오류 ----------------
    reg        err;
    reg [3:0]  err_code;
    reg [31:0] err_info;
    wire       err_clr = wctl && wd[3];

    always @(posedge clk) begin
        if (core_rst) begin
            err <= 1'b0; err_code <= 4'd0; err_info <= 32'd0;
        end else if ((err0_valid || err1_valid || err2_valid) && (!err || err_clr)) begin
            err <= 1'b1;
            if (err0_valid)      begin err_code <= err0_code; err_info <= err0_info; end
            else if (err1_valid) begin err_code <= 4'd6;      err_info <= err1_info; end
            else                 begin err_code <= 4'd7;      err_info <= err2_info; end
        end else if (err_clr) begin
            err <= 1'b0; err_code <= 4'd0; err_info <= 32'd0;
        end
    end

    // ---------------- 읽기 ----------------
    reg [31:0] hi_cyc, hi_wb, hi_sb, hi_busy, hi_stall;

    always @(posedge clk) begin
        if (rst) begin
            s_axil_bvalid <= 1'b0; s_axil_rvalid <= 1'b0; s_axil_rdata <= 32'd0;
            hi_cyc <= 32'd0; hi_wb <= 32'd0; hi_sb <= 32'd0; hi_busy <= 32'd0; hi_stall <= 32'd0;
        end else begin
            if (wr) s_axil_bvalid <= 1'b1;
            else if (s_axil_bready) s_axil_bvalid <= 1'b0;
            if (rd) s_axil_rvalid <= 1'b1;
            else if (s_axil_rready) s_axil_rvalid <= 1'b0;
            if (rd) begin
                case (ra)
                32'h0000: s_axil_rdata <= 32'h534E_4E58;
                32'h0004: s_axil_rdata <= VERSION;
                32'h0008: s_axil_rdata <= N_ENTRY;
                32'h000C: s_axil_rdata <= N_ON_CHIP;
                32'h0100: s_axil_rdata <= {28'd0, err, mig_calib, sys_idle, run};
                32'h0104: s_axil_rdata <= {31'd0, run};
                32'h0108: s_axil_rdata <= {md_busy, 15'd0, md_rdata};
                32'h0200: s_axil_rdata <= now_us;
                32'h0208: begin s_axil_rdata <= now_cyc[31:0]; hi_cyc <= now_cyc[63:32]; end
                32'h020C: s_axil_rdata <= hi_cyc;
                32'h0300: s_axil_rdata <= {21'd0, n_tracks};
                32'h0304: s_axil_rdata <= {26'd0, n_models};
                32'h0308: s_axil_rdata <= model_base;
                32'h030C: s_axil_rdata <= state_base;
                32'h0310: s_axil_rdata <= deadline_us;
                32'h0314: s_axil_rdata <= margin_us;
                32'h0318: s_axil_rdata <= link_tune;
                32'h0400: s_axil_rdata <= c_req_in;
                32'h0404: s_axil_rdata <= c_req_drop;
                32'h0408: s_axil_rdata <= c_res_out;
                32'h040C: s_axil_rdata <= c_late;
                32'h0410: s_axil_rdata <= {21'd0, c_max_pend};
                32'h0414: s_axil_rdata <= c_batch;
                32'h0418: s_axil_rdata <= c_load;
                32'h041C: s_axil_rdata <= c_sat;
                32'h0420: begin s_axil_rdata <= c_wbytes[31:0];  hi_wb    <= c_wbytes[63:32]; end
                32'h0424: s_axil_rdata <= hi_wb;
                32'h0428: begin s_axil_rdata <= c_sbytes[31:0];  hi_sb    <= c_sbytes[63:32]; end
                32'h042C: s_axil_rdata <= hi_sb;
                32'h0430: begin s_axil_rdata <= c_busy[31:0];    hi_busy  <= c_busy[63:32]; end
                32'h0434: s_axil_rdata <= hi_busy;
                32'h0438: begin s_axil_rdata <= stall_cyc[31:0]; hi_stall <= stall_cyc[63:32]; end
                32'h043C: s_axil_rdata <= hi_stall;
                32'h0500: s_axil_rdata <= {28'd0, err_code};
                32'h0504: s_axil_rdata <= err_info;
                32'h0440, 32'h0444, 32'h0448, 32'h044C, 32'h0450, 32'h0454,
                32'h0458, 32'h045C, 32'h0460, 32'h0464, 32'h0468, 32'h046C:
                          s_axil_rdata <= link_dbg[32 * ra[5:2] +: 32];
                default:  s_axil_rdata <= 32'd0;
                endcase
            end
        end
    end

endmodule
