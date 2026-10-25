// eth_link.v — Gigabit Ethernet(RGMII) UDP 링크: 추론 요청 받기, 결과·제어 응답 보내기 (06_HOST_INTERFACE.md §3·§4·§7.6)
//
// verilog-ethernet(hardware/ip/verilog-ethernet)의 eth_mac_1g_rgmii_fifo + udp_complete를 쓴다. RGMII 쪽만 gtx_clk
// 125 MHz이고 나머지는 clk(100 MHz) 하나다. MAC RX frame FIFO가 FCS가 틀린 frame을 버린다.
// 받기: 이 FPGA IP로 온 datagram만 본다. 그 밖의 port·IP는 버린다. IP 조각은 첫 조각만 머리를 보고 나머지는 버린다
//   (udp_complete가 조각을 걸러 내지 않아 뒤 조각의 data를 UDP 머리로 읽는다).
//   REQ_PORT: 조각나지 않았고 payload 길이가 64 B의 배수이고 64~1,472 B면 64 B마다 rq word 하나(byte k = rq_data[8k+7:8k])를 낸다.
//     아니면(MF가 선 첫 조각 포함) datagram 전체를 버리고 len_err_valid 1 cycle, len_err_info = UDP 머리의 payload 길이 B.
//     길이 0 datagram은 udp_complete가 머리 없이 버리므로 그 오류 신호와 남은 port·길이 값으로 알아챈다.
//     정상 datagram이면 그 src IP·port를 결과 받는 곳으로 바꾼다.
//   CTRL_PORT: payload를 cq_*로 넘긴다. ctrl은 요청 하나에 응답 하나를 낸다. 응답을 다 보내기 전에 온 제어
//     datagram은 버린다(Host가 같은 tag로 다시 보낸다, 06 §7.6). 머리를 붙잡아 받기를 멈추면 그 응답을 보내는 데
//     필요한 ARP reply도 뒤에 막혀 ARP timeout(약 36 s)까지 link 전체가 선다.
// MAC RX FIFO는 8 KiB다. clk 쪽은 1 B/cycle(100 MB/s)이라 1,472 B datagram이 선로 속도로 이어 오면 frame마다
//   약 300 B씩 밀린다. 4 KiB면 23개짜리 datagram 11개(모델 묶음 약 240트랙, 06 §3)를 이어 받을 때 tb_eth에서 frame을 잃었다.
// 보내기: 결과(rs 32 B)와 제어 응답(cr, 길이 cr_len)을 udp_complete 송신 하나로 보낸다. frame 사이마다 결과가 먼저다.
//   UDP checksum은 0(IPv4에서 '계산 안 함')으로 보낸다. udp_complete의 checksum 생성기는 header FIFO(8개)가 찬 때
//   들어온 header를 버리고 뒤 payload와 짝이 어긋나므로 끈다(결과가 밀리면 simulation에서 실제로 생겼다).
//   frame은 MAC TX frame FIFO가 다 모은 뒤 내보내므로 응답이 중간에 멈춰도 선로로 끊겨 나가지 않는다.
// phy_reset_n: rst 뒤 PHY_RST_CYC cycle 동안 0. MDIO는 쓰지 않는다(MDC 0, MDIO Z).
// RX_IDELAY != 0이고 TARGET = "XILINX"면 rxd·rx_ctl에 IDELAYE2(VAR_LOAD, 처음 tap = RX_IDELAY)를 둔다. IDELAYCTRL은 top 몫.
//   rx_tap(LINK_TUNE)이 바뀌면 그 값을 다시 싣는다. 보드에서 frame 오류를 보며 tap을 맞춘다(P4.10).

`timescale 1ns / 1ps

module eth_link #(
    parameter        TARGET      = "GENERIC",          // board "XILINX", simulation "GENERIC"
    parameter        RX_IDELAY   = 0,                  // IDELAYE2 tap 0~31, 0 = 두지 않음
    parameter [47:0] LOCAL_MAC   = 48'h02_00_00_00_00_01,
    parameter [31:0] LOCAL_IP    = {8'd192, 8'd168, 8'd10, 8'd2},
    parameter [31:0] GATEWAY_IP  = {8'd192, 8'd168, 8'd10, 8'd1},
    parameter [31:0] SUBNET_MASK = {8'd255, 8'd255, 8'd255, 8'd0},
    parameter [15:0] REQ_PORT    = 16'd5000,
    parameter [15:0] CTRL_PORT   = 16'd5001,
    parameter        PHY_RST_CYC = 1_100_000           // 11 ms at 100 MHz. simulation은 짧게
)(
    input  wire         clk,
    input  wire         rst,
    input  wire         gtx_clk,                       // 125 MHz
    input  wire         gtx_clk90,                     // 125 MHz, 90°
    input  wire [4:0]   rx_tap,                        // 수신 IDELAY tap(RX_IDELAY != 0일 때)
    // RGMII PHY
    input  wire         rgmii_rx_clk,
    input  wire [3:0]   rgmii_rxd,
    input  wire         rgmii_rx_ctl,
    output wire         rgmii_tx_clk,
    output wire [3:0]   rgmii_txd,
    output wire         rgmii_tx_ctl,
    output reg          phy_reset_n,
    output wire         phy_mdc,
    inout  wire         phy_mdio,
    // 추론 요청 (frontend)
    output reg          rq_valid,
    input  wire         rq_ready,
    output reg  [511:0] rq_data,
    output reg          len_err_valid,
    output reg  [31:0]  len_err_info,
    // 결과 (frontend)
    input  wire         rs_valid,
    output wire         rs_ready,
    input  wire [255:0] rs_data,
    // 제어 packet (ctrl)
    output wire [7:0]   cq_tdata,
    output wire         cq_tvalid,
    input  wire         cq_tready,
    output wire         cq_tlast,
    input  wire [7:0]   cr_tdata,
    input  wire         cr_tvalid,
    output wire         cr_tready,
    input  wire         cr_tlast,
    input  wire [10:0]  cr_len                         // 응답 payload B, cr_tvalid 동안 유지
);

    assign phy_mdc  = 1'b0;
    assign phy_mdio = 1'bz;

    // ---------------- PHY reset ----------------
    localparam PW = $clog2(PHY_RST_CYC + 1);
    reg [PW-1:0] prc;
    always @(posedge clk) begin
        if (rst) begin
            prc         <= {PW{1'b0}};
            phy_reset_n <= 1'b0;
        end else if (!phy_reset_n) begin
            prc         <= prc + 1'b1;
            phy_reset_n <= (prc == PHY_RST_CYC[PW-1:0] - 1'b1);
        end
    end

    // ---------------- RGMII 수신 지연 ----------------
    wire [4:0] rx_pin = {rgmii_rx_ctl, rgmii_rxd};
    wire [4:0] rx_dly;
    generate
        if (TARGET == "XILINX" && RX_IDELAY != 0) begin : g_idelay
            reg [4:0] tap_q  = RX_IDELAY;
            reg       tap_ld = 1'b0;
            always @(posedge clk) begin
                tap_ld <= rx_tap != tap_q;
                tap_q  <= rx_tap;
            end
            genvar i;
            for (i = 0; i < 5; i = i + 1) begin : g_bit
                IDELAYE2 #(
                    .IDELAY_TYPE("VAR_LOAD"), .IDELAY_VALUE(RX_IDELAY), .DELAY_SRC("IDATAIN"),
                    .REFCLK_FREQUENCY(200.0), .HIGH_PERFORMANCE_MODE("TRUE"), .SIGNAL_PATTERN("DATA")
                ) u_dly (
                    .IDATAIN(rx_pin[i]), .DATAOUT(rx_dly[i]), .DATAIN(1'b0), .C(clk), .CE(1'b0), .INC(1'b0),
                    .CINVCTRL(1'b0), .CNTVALUEIN(tap_q), .CNTVALUEOUT(), .LD(tap_ld), .LDPIPEEN(1'b0), .REGRST(1'b0)
                );
            end
        end else begin : g_nodly
            assign rx_dly = rx_pin;
        end
    endgenerate

    // ---------------- MAC ----------------
    wire gtx_rst;
    sync_reset #(.N(4)) u_gtx_rst (.clk(gtx_clk), .rst(rst), .out(gtx_rst));

    wire [7:0] mrx_tdata, mtx_tdata;
    wire       mrx_tvalid, mrx_tready, mrx_tlast, mrx_tuser;
    wire       mtx_tvalid, mtx_tready, mtx_tlast, mtx_tuser;

    eth_mac_1g_rgmii_fifo #(
        .TARGET(TARGET), .IODDR_STYLE("IODDR"), .CLOCK_INPUT_STYLE("BUFR"), .USE_CLK90("TRUE"),
        .ENABLE_PADDING(1), .MIN_FRAME_LENGTH(64),
        .TX_FIFO_DEPTH(4096), .TX_FRAME_FIFO(1), .RX_FIFO_DEPTH(8192), .RX_FRAME_FIFO(1)
    ) u_mac (
        .gtx_clk(gtx_clk), .gtx_clk90(gtx_clk90), .gtx_rst(gtx_rst), .logic_clk(clk), .logic_rst(rst),
        .tx_axis_tdata(mtx_tdata), .tx_axis_tkeep(1'b1), .tx_axis_tvalid(mtx_tvalid), .tx_axis_tready(mtx_tready),
        .tx_axis_tlast(mtx_tlast), .tx_axis_tuser(mtx_tuser),
        .rx_axis_tdata(mrx_tdata), .rx_axis_tkeep(), .rx_axis_tvalid(mrx_tvalid), .rx_axis_tready(mrx_tready),
        .rx_axis_tlast(mrx_tlast), .rx_axis_tuser(mrx_tuser),
        .rgmii_rx_clk(rgmii_rx_clk), .rgmii_rxd(rx_dly[3:0]), .rgmii_rx_ctl(rx_dly[4]),
        .rgmii_tx_clk(rgmii_tx_clk), .rgmii_txd(rgmii_txd), .rgmii_tx_ctl(rgmii_tx_ctl),
        .tx_error_underflow(), .tx_fifo_overflow(), .tx_fifo_bad_frame(), .tx_fifo_good_frame(),
        .rx_error_bad_frame(), .rx_error_bad_fcs(), .rx_fifo_overflow(), .rx_fifo_bad_frame(), .rx_fifo_good_frame(),
        .speed(), .cfg_ifg(8'd12), .cfg_tx_enable(1'b1), .cfg_rx_enable(1'b1)
    );

    // ---------------- Ethernet frame ↔ UDP ----------------
    wire        erx_hdr_valid, erx_hdr_ready, etx_hdr_valid, etx_hdr_ready;
    wire [47:0] erx_dmac, erx_smac, etx_dmac, etx_smac;
    wire [15:0] erx_type, etx_type;
    wire [7:0]  erx_tdata, etx_tdata;
    wire        erx_tvalid, erx_tready, erx_tlast, erx_tuser;
    wire        etx_tvalid, etx_tready, etx_tlast, etx_tuser;

    eth_axis_rx u_erx (
        .clk(clk), .rst(rst),
        .s_axis_tdata(mrx_tdata), .s_axis_tkeep(1'b1), .s_axis_tvalid(mrx_tvalid), .s_axis_tready(mrx_tready),
        .s_axis_tlast(mrx_tlast), .s_axis_tuser(mrx_tuser),
        .m_eth_hdr_valid(erx_hdr_valid), .m_eth_hdr_ready(erx_hdr_ready),
        .m_eth_dest_mac(erx_dmac), .m_eth_src_mac(erx_smac), .m_eth_type(erx_type),
        .m_eth_payload_axis_tdata(erx_tdata), .m_eth_payload_axis_tkeep(), .m_eth_payload_axis_tvalid(erx_tvalid),
        .m_eth_payload_axis_tready(erx_tready), .m_eth_payload_axis_tlast(erx_tlast), .m_eth_payload_axis_tuser(erx_tuser),
        .busy(), .error_header_early_termination()
    );

    eth_axis_tx u_etx (
        .clk(clk), .rst(rst),
        .s_eth_hdr_valid(etx_hdr_valid), .s_eth_hdr_ready(etx_hdr_ready),
        .s_eth_dest_mac(etx_dmac), .s_eth_src_mac(etx_smac), .s_eth_type(etx_type),
        .s_eth_payload_axis_tdata(etx_tdata), .s_eth_payload_axis_tkeep(1'b1), .s_eth_payload_axis_tvalid(etx_tvalid),
        .s_eth_payload_axis_tready(etx_tready), .s_eth_payload_axis_tlast(etx_tlast), .s_eth_payload_axis_tuser(etx_tuser),
        .m_axis_tdata(mtx_tdata), .m_axis_tkeep(), .m_axis_tvalid(mtx_tvalid), .m_axis_tready(mtx_tready),
        .m_axis_tlast(mtx_tlast), .m_axis_tuser(mtx_tuser),
        .busy()
    );

    wire        urx_hdr_valid, utx_hdr_ready;
    reg         urx_hdr_ready, utx_hdr_valid;
    wire [31:0] urx_sip, urx_dip;
    wire [15:0] urx_sport, urx_dport, urx_len;
    wire [7:0]  urx_tdata;
    wire        urx_tvalid, urx_tlast;
    reg         urx_tready;
    reg  [31:0] utx_dip;
    reg  [15:0] utx_sport, utx_dport, utx_len;
    reg  [7:0]  utx_tdata;
    reg         utx_tvalid, utx_tlast;
    wire        utx_tready;
    wire        urx_hdr_err;
    wire [2:0]  urx_flags;                   // {0, DF, MF}
    wire [12:0] urx_foff;

    udp_complete #(
        .ARP_CACHE_ADDR_WIDTH(4),
        .ARP_REQUEST_RETRY_COUNT(4),
        .ARP_REQUEST_RETRY_INTERVAL(36'd200_000_000),   // 2 s at 100 MHz
        .ARP_REQUEST_TIMEOUT(36'd3_000_000_000),        // 30 s
        .UDP_CHECKSUM_GEN_ENABLE(0)
    ) u_udp (
        .clk(clk), .rst(rst),
        .s_eth_hdr_valid(erx_hdr_valid), .s_eth_hdr_ready(erx_hdr_ready),
        .s_eth_dest_mac(erx_dmac), .s_eth_src_mac(erx_smac), .s_eth_type(erx_type),
        .s_eth_payload_axis_tdata(erx_tdata), .s_eth_payload_axis_tvalid(erx_tvalid), .s_eth_payload_axis_tready(erx_tready),
        .s_eth_payload_axis_tlast(erx_tlast), .s_eth_payload_axis_tuser(erx_tuser),
        .m_eth_hdr_valid(etx_hdr_valid), .m_eth_hdr_ready(etx_hdr_ready),
        .m_eth_dest_mac(etx_dmac), .m_eth_src_mac(etx_smac), .m_eth_type(etx_type),
        .m_eth_payload_axis_tdata(etx_tdata), .m_eth_payload_axis_tvalid(etx_tvalid), .m_eth_payload_axis_tready(etx_tready),
        .m_eth_payload_axis_tlast(etx_tlast), .m_eth_payload_axis_tuser(etx_tuser),
        // IP 송수신은 쓰지 않는다
        .s_ip_hdr_valid(1'b0), .s_ip_hdr_ready(), .s_ip_dscp(6'd0), .s_ip_ecn(2'd0), .s_ip_length(16'd0),
        .s_ip_ttl(8'd0), .s_ip_protocol(8'd0), .s_ip_source_ip(32'd0), .s_ip_dest_ip(32'd0),
        .s_ip_payload_axis_tdata(8'd0), .s_ip_payload_axis_tvalid(1'b0), .s_ip_payload_axis_tready(),
        .s_ip_payload_axis_tlast(1'b0), .s_ip_payload_axis_tuser(1'b0),
        .m_ip_hdr_valid(), .m_ip_hdr_ready(1'b1), .m_ip_eth_dest_mac(), .m_ip_eth_src_mac(), .m_ip_eth_type(),
        .m_ip_version(), .m_ip_ihl(), .m_ip_dscp(), .m_ip_ecn(), .m_ip_length(), .m_ip_identification(),
        .m_ip_flags(), .m_ip_fragment_offset(), .m_ip_ttl(), .m_ip_protocol(), .m_ip_header_checksum(),
        .m_ip_source_ip(), .m_ip_dest_ip(),
        .m_ip_payload_axis_tdata(), .m_ip_payload_axis_tvalid(), .m_ip_payload_axis_tready(1'b1),
        .m_ip_payload_axis_tlast(), .m_ip_payload_axis_tuser(),
        // UDP 송신
        .s_udp_hdr_valid(utx_hdr_valid), .s_udp_hdr_ready(utx_hdr_ready), .s_udp_ip_dscp(6'd0), .s_udp_ip_ecn(2'd0),
        .s_udp_ip_ttl(8'd64), .s_udp_ip_source_ip(LOCAL_IP), .s_udp_ip_dest_ip(utx_dip),
        .s_udp_source_port(utx_sport), .s_udp_dest_port(utx_dport), .s_udp_length(utx_len), .s_udp_checksum(16'd0),
        .s_udp_payload_axis_tdata(utx_tdata), .s_udp_payload_axis_tvalid(utx_tvalid), .s_udp_payload_axis_tready(utx_tready),
        .s_udp_payload_axis_tlast(utx_tlast), .s_udp_payload_axis_tuser(1'b0),
        // UDP 수신
        .m_udp_hdr_valid(urx_hdr_valid), .m_udp_hdr_ready(urx_hdr_ready),
        .m_udp_eth_dest_mac(), .m_udp_eth_src_mac(), .m_udp_eth_type(), .m_udp_ip_version(), .m_udp_ip_ihl(),
        .m_udp_ip_dscp(), .m_udp_ip_ecn(), .m_udp_ip_length(), .m_udp_ip_identification(), .m_udp_ip_flags(urx_flags),
        .m_udp_ip_fragment_offset(urx_foff), .m_udp_ip_ttl(), .m_udp_ip_protocol(), .m_udp_ip_header_checksum(),
        .m_udp_ip_source_ip(urx_sip), .m_udp_ip_dest_ip(urx_dip),
        .m_udp_source_port(urx_sport), .m_udp_dest_port(urx_dport), .m_udp_length(urx_len), .m_udp_checksum(),
        .m_udp_payload_axis_tdata(urx_tdata), .m_udp_payload_axis_tvalid(urx_tvalid), .m_udp_payload_axis_tready(urx_tready),
        .m_udp_payload_axis_tlast(urx_tlast), .m_udp_payload_axis_tuser(),
        .ip_rx_busy(), .ip_tx_busy(), .udp_rx_busy(), .udp_tx_busy(),
        .ip_rx_error_header_early_termination(), .ip_rx_error_payload_early_termination(),
        .ip_rx_error_invalid_header(), .ip_rx_error_invalid_checksum(), .ip_tx_error_payload_early_termination(),
        .ip_tx_error_arp_failed(), .udp_rx_error_header_early_termination(urx_hdr_err),
        .udp_rx_error_payload_early_termination(), .udp_tx_error_payload_early_termination(),
        .local_mac(LOCAL_MAC), .local_ip(LOCAL_IP), .gateway_ip(GATEWAY_IP), .subnet_mask(SUBNET_MASK),
        .clear_arp_cache(1'b0)
    );

    // ---------------- 받기 ----------------
    localparam [1:0] R_HDR = 2'd0, R_REQ = 2'd1, R_CTRL = 2'd2, R_DROP = 2'd3;
    reg  [1:0]  rt;
    reg  [5:0]  bc;                          // rq word 안 byte 수
    reg         cbusy;                       // 제어 요청을 넘겼고 응답을 다 보내지 않음
    reg  [31:0] res_ip, cr_ip;
    reg  [15:0] res_port, cr_port;

    wire [15:0] plen    = urx_len - 16'd8;
    wire        to_me   = (urx_dip == LOCAL_IP) && (urx_foff == 13'd0);
    wire        is_req  = to_me && (urx_dport == REQ_PORT);
    wire        is_ctrl = to_me && (urx_dport == CTRL_PORT);
    wire        len_ok  = (plen != 16'd0) && (plen[5:0] == 6'd0) && (plen <= 16'd1472) && !urx_flags[0];
    wire        urx_hs  = urx_tvalid && urx_tready;

    assign cq_tdata  = urx_tdata;
    assign cq_tvalid = urx_tvalid && (rt == R_CTRL);
    assign cq_tlast  = urx_tlast;

    always @(*) begin
        urx_hdr_ready = (rt == R_HDR);
        case (rt)
        R_REQ:   urx_tready = !rq_valid || rq_ready;
        R_CTRL:  urx_tready = cq_tready;
        R_DROP:  urx_tready = 1'b1;
        default: urx_tready = 1'b0;
        endcase
    end

    // shortcut: 머리 길이만 검사한다. 조각나지 않았는데 payload가 UDP 머리 길이보다 짧은(udp_complete tuser) datagram은
    // 이미 낸 word를 되돌리지 못한다. 깨진 Host만 만드는 경우라 두었고, 막으려면 datagram 하나를 FIFO에 다 받은 뒤 낸다.
    always @(posedge clk) begin
        len_err_valid <= 1'b0;
        if (rst) begin
            rt       <= R_HDR;
            bc       <= 6'd0;
            rq_valid <= 1'b0;
            cbusy    <= 1'b0;
            res_ip   <= 32'd0;
            res_port <= 16'd0;
        end else begin
            if (urx_hdr_valid && urx_hdr_ready) begin
                if (is_req && len_ok) begin
                    rt       <= R_REQ;
                    res_ip   <= urx_sip;
                    res_port <= urx_sport;
                end else if (is_ctrl && !cbusy) begin
                    rt      <= R_CTRL;
                    cbusy   <= 1'b1;
                    cr_ip   <= urx_sip;
                    cr_port <= urx_sport;
                end else
                    rt <= R_DROP;
                if (is_req && !len_ok) begin
                    len_err_valid <= 1'b1;
                    len_err_info  <= {16'd0, plen};
                end
            end else if (urx_hdr_err && is_req && urx_len == 16'd8) begin
                len_err_valid <= 1'b1;
                len_err_info  <= 32'd0;
            end
            if (rq_valid && rq_ready)
                rq_valid <= 1'b0;
            if (urx_hs) begin
                if (rt == R_REQ) begin
                    rq_data <= {urx_tdata, rq_data[511:8]};
                    bc      <= bc + 6'd1;
                    if (bc == 6'd63) rq_valid <= 1'b1;
                end
                if (urx_tlast) begin
                    rt <= R_HDR;
                    bc <= 6'd0;
                end
            end
            if (cr_tvalid && cr_tready && cr_tlast)
                cbusy <= 1'b0;
        end
    end

    // ---------------- 보내기 ----------------
    localparam [1:0] T_IDLE = 2'd0, T_HDR = 2'd1, T_PAY = 2'd2;
    reg  [1:0]   ts;
    reg          sel;                        // 0 결과, 1 제어 응답
    reg  [255:0] rsr;
    reg  [4:0]   tc;

    assign rs_ready  = (ts == T_IDLE);
    assign cr_tready = (ts == T_PAY) && sel && utx_tready;

    always @(*) begin
        utx_hdr_valid = (ts == T_HDR);
        utx_dip       = sel ? cr_ip : res_ip;
        utx_dport     = sel ? cr_port : res_port;
        utx_sport     = sel ? CTRL_PORT : REQ_PORT;
        utx_len       = sel ? {5'd0, cr_len} + 16'd8 : 16'd40;
        utx_tvalid    = (ts == T_PAY) && (!sel || cr_tvalid);
        utx_tdata     = sel ? cr_tdata : rsr[7:0];
        utx_tlast     = sel ? cr_tlast : (tc == 5'd31);
    end

    always @(posedge clk) begin
        if (rst) begin
            ts  <= T_IDLE;
            sel <= 1'b0;
        end else case (ts)
            T_IDLE: begin
                tc <= 5'd0;
                if (rs_valid) begin
                    sel <= 1'b0;
                    rsr <= rs_data;
                    ts  <= T_HDR;
                end else if (cr_tvalid) begin
                    sel <= 1'b1;
                    ts  <= T_HDR;
                end
            end
            T_HDR:
                if (utx_hdr_ready) ts <= T_PAY;
            default:
                if (utx_tvalid && utx_tready) begin
                    rsr <= {8'd0, rsr[255:8]};
                    tc  <= tc + 5'd1;
                    if (utx_tlast) ts <= T_IDLE;
                end
        endcase
    end

endmodule
