// ============================================================
// tb_eth.sv — eth_link + ctrl를 RGMII 선 너머 Host network stack과 맞대어 확인 (P4.7)
// ============================================================
// Host 쪽은 같은 verilog-ethernet(eth_mac_1g_rgmii_fifo + udp_complete, TARGET GENERIC)으로 만든다. 두 MAC은 RGMII 선으로
// 바로 잇는다. Host clock은 125 MHz에서 250 ppm 어긋나게 둔다. eth_link 뒤에는 ctrl, AXI4-Lite register 모델(regs 대신),
// 무작위 ready·지연의 DDR3 AXI4 slave 모델, frontend 대신 64 B 추론 요청을 무작위 지연 뒤 32 B 결과로 바꾸는 loopback을 둔다.
// 확인 항목:
//   - 추론 요청 word가 보낸 순서대로 bit 일치. 1개·23개 datagram, 23개짜리 11개를 선로 속도로 이어 보내도 빠짐 없음
//   - 길이 0·1·63·100·1,480 B, 24개(1,536 B) datagram은 전체를 버리고 len_err_info = 길이. 다른 port는 조용히 버림
//     (길이 0도 port 5001·6000이면 len_err 없음). MF가 선 첫 IP 조각은 len_err, 뒤 조각은 조용히 버림
//   - 결과가 가장 최근 정상 추론 요청의 src IP·port로 감(길이 오류 datagram은 받는 곳을 바꾸지 않음, Host IP 바꿈 포함)
//   - FCS가 틀린 frame(RGMII 선 bit 뒤집기)은 버림. ARP: Host → FPGA, FPGA → Host(바뀐 IP) 양쪽
//   - 제어: register·DDR3 창 읽기·쓰기, tag·머리 되돌림, 응답 받는 곳(결과 받는 곳과 다른 IP, FPGA ARP cache에 없는 IP),
//     응답 전에 이어 보낸 요청은 버리고 다시 보내면 처리, status 1·2·3, 4 KiB 경계 burst 나눔,
//     쓰기 길이 오류면 아무것도 쓰지 않음, AXI4·AXI4-Lite 오류 응답이면 status 1
//   - 송신 순서: 결과와 제어 응답이 함께 기다리면 결과가 먼저
//   - AXI 규칙: valid 유지, 4 KiB 경계, 주소 전 W 없음, wlast, run = 1일 때 DDR3 접근 없음. phy_reset_n 시간, MDC·MDIO
// 실행 (저장소 루트):
//   bash hardware/testbench/run_eth.sh
// ============================================================
`timescale 1ns / 1ps

module tb_eth;

    localparam [47:0] DUT_MAC  = 48'h02_00_00_00_00_01, HOST_MAC = 48'h02_00_00_00_00_10;
    localparam [31:0] DUT_IP   = {8'd192, 8'd168, 8'd10, 8'd2};
    localparam [31:0] IP1      = {8'd192, 8'd168, 8'd10, 8'd1}, IP7 = {8'd192, 8'd168, 8'd10, 8'd7};
    localparam [31:0] IP9      = {8'd192, 8'd168, 8'd10, 8'd9};
    localparam int    PHY_RST  = 50;

    int errors = 0;
    function automatic void err(input string s);
        errors++;
        if (errors <= 30) $display("ERROR t=%0t %s", $time, s);
    endfunction

    // ---------------- clock, reset ----------------
    reg clk = 1'b0, gtx = 1'b0, gtx90 = 1'b0, hclk = 1'b0, hclk90 = 1'b0;
    always #5 clk = ~clk;
    always #4 gtx = ~gtx;
    initial begin #2; forever #4 gtx90 = ~gtx90; end
    always #4.001 hclk = ~hclk;
    initial begin #2.001; forever #4.001 hclk90 = ~hclk90; end
    reg rst = 1'b1, hrst = 1'b1;
    longint cyc = 0;
    always @(posedge clk) begin
        cyc <= cyc + 1;
        if (cyc > 3_000_000) begin           // 정상 실행은 약 40만 cycle
            $display("FAIL 시간 초과: cycle %0d", cyc);
            $finish;
        end
    end

    // ---------------- DUT ----------------
    wire         d_txc, d_txctl, h_txc, h_txctl;
    wire [3:0]   d_txd, h_txd;
    reg          flip = 1'b0;                // Host → FPGA 선 rxd[0] 뒤집기
    wire         phy_reset_n, phy_mdc, phy_mdio;
    wire         rq_valid, len_err_valid;
    reg          rq_ready = 1'b0;
    wire [511:0] rq_data;
    wire [31:0]  len_err_info;
    reg          rs_valid = 1'b0;
    wire         rs_ready;
    reg  [255:0] rs_data = '0;
    wire [7:0]   cq_tdata, cr_tdata;
    wire         cq_tvalid, cq_tready, cq_tlast, cr_tvalid, cr_tready, cr_tlast;
    wire [10:0]  cr_len;
    reg          run = 1'b0;

    eth_link #(.TARGET("GENERIC"), .PHY_RST_CYC(PHY_RST)) dut (
        .clk(clk), .rst(rst), .gtx_clk(gtx), .gtx_clk90(gtx90), .rx_tap(5'd0), .dbg_clr(1'b0), .dbg_cnt(),
        .md_valid(1'b0), .md_op(2'd0), .md_phy(5'd0), .md_reg(5'd0), .md_wdata(16'd0), .md_busy(), .md_rdata(),
        .rgmii_rx_clk(h_txc), .rgmii_rxd(h_txd ^ {3'b000, flip}), .rgmii_rx_ctl(h_txctl),
        .rgmii_tx_clk(d_txc), .rgmii_txd(d_txd), .rgmii_tx_ctl(d_txctl),
        .phy_reset_n(phy_reset_n), .phy_mdc(phy_mdc), .phy_mdio(phy_mdio),
        .rq_valid(rq_valid), .rq_ready(rq_ready), .rq_data(rq_data),
        .len_err_valid(len_err_valid), .len_err_info(len_err_info),
        .rs_valid(rs_valid), .rs_ready(rs_ready), .rs_data(rs_data),
        .cq_tdata(cq_tdata), .cq_tvalid(cq_tvalid), .cq_tready(cq_tready), .cq_tlast(cq_tlast),
        .cr_tdata(cr_tdata), .cr_tvalid(cr_tvalid), .cr_tready(cr_tready), .cr_tlast(cr_tlast), .cr_len(cr_len)
    );

    wire [31:0]  l_awaddr, l_wdata, l_araddr;
    wire [3:0]   l_wstrb;
    wire         l_awvalid, l_wvalid, l_bready, l_arvalid, l_rready;
    reg          l_awready = 1'b0, l_wready = 1'b0, l_bvalid = 1'b0, l_arready = 1'b0, l_rvalid = 1'b0;
    reg  [31:0]  l_rdata = '0;
    reg  [1:0]   l_bresp = 2'd0, l_rresp = 2'd0;
    wire [31:0]  m_araddr, m_awaddr;
    wire [7:0]   m_arlen, m_awlen;
    wire         m_arvalid, m_rready, m_awvalid, m_wlast, m_wvalid, m_bready;
    wire [255:0] m_wdata;
    reg          m_arready = 1'b0, m_rvalid = 1'b0, m_rlast = 1'b0, m_awready = 1'b0, m_wready = 1'b0, m_bvalid = 1'b0;
    reg  [255:0] m_rdata = '0;
    reg  [1:0]   m_rresp = 2'd0, m_bresp = 2'd0;

    ctrl uc (
        .clk(clk), .rst(rst), .run(run),
        .cq_tdata(cq_tdata), .cq_tvalid(cq_tvalid), .cq_tready(cq_tready), .cq_tlast(cq_tlast),
        .cr_tdata(cr_tdata), .cr_tvalid(cr_tvalid), .cr_tready(cr_tready), .cr_tlast(cr_tlast), .cr_len(cr_len),
        .m_axil_awaddr(l_awaddr), .m_axil_awvalid(l_awvalid), .m_axil_awready(l_awready),
        .m_axil_wdata(l_wdata), .m_axil_wstrb(l_wstrb), .m_axil_wvalid(l_wvalid), .m_axil_wready(l_wready),
        .m_axil_bresp(l_bresp), .m_axil_bvalid(l_bvalid), .m_axil_bready(l_bready),
        .m_axil_araddr(l_araddr), .m_axil_arvalid(l_arvalid), .m_axil_arready(l_arready),
        .m_axil_rdata(l_rdata), .m_axil_rresp(l_rresp), .m_axil_rvalid(l_rvalid), .m_axil_rready(l_rready),
        .m_araddr(m_araddr), .m_arlen(m_arlen), .m_arvalid(m_arvalid), .m_arready(m_arready),
        .m_rdata(m_rdata), .m_rlast(m_rlast), .m_rresp(m_rresp), .m_rvalid(m_rvalid), .m_rready(m_rready),
        .m_awaddr(m_awaddr), .m_awlen(m_awlen), .m_awvalid(m_awvalid), .m_awready(m_awready),
        .m_wdata(m_wdata), .m_wlast(m_wlast), .m_wvalid(m_wvalid), .m_wready(m_wready),
        .m_bresp(m_bresp), .m_bvalid(m_bvalid), .m_bready(m_bready)
    );

    // ---------------- Host network stack ----------------
    reg  [31:0] host_ip = IP1;
    wire [7:0]  hm_tx_tdata, he_tx_tdata, hm_rx_tdata, he_rx_tdata, ht_tdata;
    wire        hm_tx_tvalid, hm_tx_tready, hm_tx_tlast, hm_tx_tuser;
    wire        he_tx_tvalid, he_tx_tready, he_tx_tlast, he_tx_tuser;
    wire        hm_rx_tvalid, hm_rx_tlast, hm_rx_tuser;
    wire        he_rx_tvalid, he_rx_tready, he_rx_tlast, he_rx_tuser;
    wire        heh_rx_valid, heh_rx_ready, heh_tx_valid, heh_tx_ready;
    wire [47:0] heh_rx_dmac, heh_rx_smac, heh_tx_dmac, heh_tx_smac;
    wire [15:0] heh_rx_type, heh_tx_type;
    reg         inj = 1'b0, inj_tvalid = 1'b0, inj_tlast = 1'b0;   // 날 frame 넣기(길이 0 datagram)
    reg  [7:0]  inj_tdata = 8'd0;
    reg         hs_hdr_valid = 1'b0, hs_tvalid = 1'b0, hs_tlast = 1'b0;
    reg  [15:0] hs_sport = 16'd0, hs_dport = 16'd0;
    reg  [7:0]  hs_tdata = 8'd0;
    wire        hs_hdr_ready, hs_tready;
    wire        hr_hdr_valid, hr_tvalid, hr_tlast, hr_tuser;
    wire [31:0] hr_sip, hr_dip;
    wire [15:0] hr_sport, hr_dport;
    wire [7:0]  hr_tdata;
    wire        ht_tvalid, ht_tready, ht_tlast, ht_tuser, hm_rx_tready;

    assign hm_tx_tdata  = inj ? inj_tdata  : he_tx_tdata;
    assign hm_tx_tvalid = inj ? inj_tvalid : he_tx_tvalid;
    assign hm_tx_tlast  = inj ? inj_tlast  : he_tx_tlast;
    assign hm_tx_tuser  = inj ? 1'b0       : he_tx_tuser;
    assign he_tx_tready = !inj && hm_tx_tready;

    eth_mac_1g_rgmii_fifo #(
        .TARGET("GENERIC"), .IODDR_STYLE("IODDR"), .CLOCK_INPUT_STYLE("BUFR"), .USE_CLK90("TRUE"),
        .TX_FIFO_DEPTH(4096), .RX_FIFO_DEPTH(8192)
    ) h_mac (
        .gtx_clk(hclk), .gtx_clk90(hclk90), .gtx_rst(hrst), .logic_clk(hclk), .logic_rst(hrst),
        .tx_axis_tdata(hm_tx_tdata), .tx_axis_tkeep(1'b1), .tx_axis_tvalid(hm_tx_tvalid), .tx_axis_tready(hm_tx_tready),
        .tx_axis_tlast(hm_tx_tlast), .tx_axis_tuser(hm_tx_tuser),
        .rx_axis_tdata(hm_rx_tdata), .rx_axis_tkeep(), .rx_axis_tvalid(hm_rx_tvalid), .rx_axis_tready(hm_rx_tready),
        .rx_axis_tlast(hm_rx_tlast), .rx_axis_tuser(hm_rx_tuser),
        .rgmii_rx_clk(d_txc), .rgmii_rxd(d_txd), .rgmii_rx_ctl(d_txctl),
        .rgmii_tx_clk(h_txc), .rgmii_txd(h_txd), .rgmii_tx_ctl(h_txctl),
        .tx_error_underflow(), .tx_fifo_overflow(), .tx_fifo_bad_frame(), .tx_fifo_good_frame(),
        .rx_error_bad_frame(), .rx_error_bad_fcs(), .rx_fifo_overflow(), .rx_fifo_bad_frame(), .rx_fifo_good_frame(),
        .speed(), .cfg_ifg(8'd12), .cfg_tx_enable(1'b1), .cfg_rx_enable(1'b1)
    );

    eth_axis_rx h_erx (
        .clk(hclk), .rst(hrst),
        .s_axis_tdata(hm_rx_tdata), .s_axis_tkeep(1'b1), .s_axis_tvalid(hm_rx_tvalid), .s_axis_tready(hm_rx_tready),
        .s_axis_tlast(hm_rx_tlast), .s_axis_tuser(hm_rx_tuser),
        .m_eth_hdr_valid(heh_rx_valid), .m_eth_hdr_ready(heh_rx_ready),
        .m_eth_dest_mac(heh_rx_dmac), .m_eth_src_mac(heh_rx_smac), .m_eth_type(heh_rx_type),
        .m_eth_payload_axis_tdata(he_rx_tdata), .m_eth_payload_axis_tkeep(), .m_eth_payload_axis_tvalid(he_rx_tvalid),
        .m_eth_payload_axis_tready(he_rx_tready), .m_eth_payload_axis_tlast(he_rx_tlast), .m_eth_payload_axis_tuser(he_rx_tuser),
        .busy(), .error_header_early_termination()
    );

    eth_axis_tx h_etx (
        .clk(hclk), .rst(hrst),
        .s_eth_hdr_valid(heh_tx_valid), .s_eth_hdr_ready(heh_tx_ready),
        .s_eth_dest_mac(heh_tx_dmac), .s_eth_src_mac(heh_tx_smac), .s_eth_type(heh_tx_type),
        .s_eth_payload_axis_tdata(ht_tdata), .s_eth_payload_axis_tkeep(1'b1), .s_eth_payload_axis_tvalid(ht_tvalid),
        .s_eth_payload_axis_tready(ht_tready), .s_eth_payload_axis_tlast(ht_tlast), .s_eth_payload_axis_tuser(ht_tuser),
        .m_axis_tdata(he_tx_tdata), .m_axis_tkeep(), .m_axis_tvalid(he_tx_tvalid), .m_axis_tready(he_tx_tready),
        .m_axis_tlast(he_tx_tlast), .m_axis_tuser(he_tx_tuser),
        .busy()
    );

    udp_complete #(
        .ARP_REQUEST_RETRY_INTERVAL(125_000), .ARP_REQUEST_TIMEOUT(1_250_000)
    ) h_udp (
        .clk(hclk), .rst(hrst),
        .s_eth_hdr_valid(heh_rx_valid), .s_eth_hdr_ready(heh_rx_ready),
        .s_eth_dest_mac(heh_rx_dmac), .s_eth_src_mac(heh_rx_smac), .s_eth_type(heh_rx_type),
        .s_eth_payload_axis_tdata(he_rx_tdata), .s_eth_payload_axis_tvalid(he_rx_tvalid), .s_eth_payload_axis_tready(he_rx_tready),
        .s_eth_payload_axis_tlast(he_rx_tlast), .s_eth_payload_axis_tuser(he_rx_tuser),
        .m_eth_hdr_valid(heh_tx_valid), .m_eth_hdr_ready(heh_tx_ready),
        .m_eth_dest_mac(heh_tx_dmac), .m_eth_src_mac(heh_tx_smac), .m_eth_type(heh_tx_type),
        .m_eth_payload_axis_tdata(ht_tdata), .m_eth_payload_axis_tvalid(ht_tvalid), .m_eth_payload_axis_tready(ht_tready),
        .m_eth_payload_axis_tlast(ht_tlast), .m_eth_payload_axis_tuser(ht_tuser),
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
        .s_udp_hdr_valid(hs_hdr_valid), .s_udp_hdr_ready(hs_hdr_ready), .s_udp_ip_dscp(6'd0), .s_udp_ip_ecn(2'd0),
        .s_udp_ip_ttl(8'd64), .s_udp_ip_source_ip(host_ip), .s_udp_ip_dest_ip(DUT_IP),
        .s_udp_source_port(hs_sport), .s_udp_dest_port(hs_dport), .s_udp_length(16'd0), .s_udp_checksum(16'd0),
        .s_udp_payload_axis_tdata(hs_tdata), .s_udp_payload_axis_tvalid(hs_tvalid), .s_udp_payload_axis_tready(hs_tready),
        .s_udp_payload_axis_tlast(hs_tlast), .s_udp_payload_axis_tuser(1'b0),
        .m_udp_hdr_valid(hr_hdr_valid), .m_udp_hdr_ready(1'b1),
        .m_udp_eth_dest_mac(), .m_udp_eth_src_mac(), .m_udp_eth_type(), .m_udp_ip_version(), .m_udp_ip_ihl(),
        .m_udp_ip_dscp(), .m_udp_ip_ecn(), .m_udp_ip_length(), .m_udp_ip_identification(), .m_udp_ip_flags(),
        .m_udp_ip_fragment_offset(), .m_udp_ip_ttl(), .m_udp_ip_protocol(), .m_udp_ip_header_checksum(),
        .m_udp_ip_source_ip(hr_sip), .m_udp_ip_dest_ip(hr_dip),
        .m_udp_source_port(hr_sport), .m_udp_dest_port(hr_dport), .m_udp_length(), .m_udp_checksum(),
        .m_udp_payload_axis_tdata(hr_tdata), .m_udp_payload_axis_tvalid(hr_tvalid), .m_udp_payload_axis_tready(1'b1),
        .m_udp_payload_axis_tlast(hr_tlast), .m_udp_payload_axis_tuser(hr_tuser),
        .ip_rx_busy(), .ip_tx_busy(), .udp_rx_busy(), .udp_tx_busy(),
        .ip_rx_error_header_early_termination(), .ip_rx_error_payload_early_termination(),
        .ip_rx_error_invalid_header(), .ip_rx_error_invalid_checksum(), .ip_tx_error_payload_early_termination(),
        .ip_tx_error_arp_failed(), .udp_rx_error_header_early_termination(),
        .udp_rx_error_payload_early_termination(), .udp_tx_error_payload_early_termination(),
        .local_mac(HOST_MAC), .local_ip(host_ip), .gateway_ip(IP1), .subnet_mask({8'd255, 8'd255, 8'd255, 8'd0}),
        .clear_arp_cache(1'b0)
    );

    // ---------------- 기대값 ----------------
    logic [511:0] exp_req[$];                // eth_link가 낼 추론 요청 word
    logic [255:0] exp_res[$];                // Host가 받을 결과
    logic [47:0]  exp_dst[$];                // 그 결과의 받는 곳 {IP, port}
    int unsigned  exp_len[$];                // len_err_info
    byte unsigned txq[$];                    // 다음에 보낼 payload
    int           n_req = 0, n_res = 0, n_lenerr = 0, n_fcs = 0, n_arp_rx = 0, n_arp_tx = 0, n_ctl = 0;

    function automatic logic [255:0] f_res(input logic [511:0] w);
        return w[255:0] ^ ~w[511:256];
    endfunction

    // ---------------- frontend loopback ----------------
    logic [255:0] fq_d[$];
    longint       fq_t[$];
    logic [511:0] x;
    logic [255:0] y;
    int unsigned  z;
    bit           hold_rs = 0;               // 1이면 ctrl이 요청을 실행하기 시작할 때까지 결과를 쌓아 둔다
    always @(posedge clk) begin
        rq_ready <= ($urandom_range(0, 15) != 0);
        // Queue pop은 조건식 밖에서 한다. Verilator 5.020은 else-if 조건의 pop을 앞 조건과 상관없이 실행한다
        if (rq_valid && rq_ready) begin
            if (exp_req.size() == 0)
                err("unexpected request");
            else begin
                x = exp_req.pop_front();
                if (x !== rq_data) err($sformatf("request %0d mismatch", n_req));
            end
            n_req++;
            fq_d.push_back(f_res(rq_data));
            fq_t.push_back(cyc + $urandom_range(0, 400));
        end
        if (rs_valid && rs_ready)
            rs_valid <= 1'b0;
        if ((!rs_valid || rs_ready) && fq_d.size() != 0 && cyc >= fq_t[0] && $urandom_range(0, 3) != 0
            && !(hold_rs && uc.st == 4'd0)) begin
            rs_valid <= 1'b1;
            y = fq_d.pop_front();
            rs_data  <= y;
            void'(fq_t.pop_front());
        end
        if (len_err_valid) begin
            n_lenerr++;
            if (exp_len.size() == 0)
                err($sformatf("unexpected len_err %0d", len_err_info));
            else begin
                z = exp_len.pop_front();
                if (z != len_err_info) err($sformatf("len_err_info %0d, expected %0d", len_err_info, z));
            end
        end
        if (dut.u_mac.rx_error_bad_fcs)
            n_fcs++;
    end

    // ---------------- 송신 순서: 결과와 응답이 함께 기다리면 결과 ----------------
    bit prio_chk = 0;
    int n_prio = 0;
    always @(posedge clk) begin
        if (prio_chk && dut.sel !== 1'b0) err("control reply sent before a waiting result");
        prio_chk <= !rst && dut.ts == 2'd0 && rs_valid && cr_tvalid;
        if (!rst && dut.ts == 2'd0 && rs_valid && cr_tvalid) n_prio++;
    end

    // ---------------- Host 받기 ----------------
    byte unsigned cur[$];
    logic [31:0]  hq_sip[$], hq_dip[$];
    logic [15:0]  hq_sport[$], hq_dport[$];
    byte unsigned rpb[$];                    // 받은 제어 응답 byte(이어 붙임)
    int           rpl[$];                    // 응답마다 길이
    logic [47:0]  rpd[$];                    // 응답마다 받는 곳
    always @(posedge hclk) begin
        if (heh_rx_valid && heh_rx_ready && heh_rx_type == 16'h0806) n_arp_rx++;
        if (heh_tx_valid && heh_tx_ready && heh_tx_type == 16'h0806) n_arp_tx++;
        if (hr_hdr_valid) begin
            hq_sip.push_back(hr_sip);
            hq_dip.push_back(hr_dip);
            hq_sport.push_back(hr_sport);
            hq_dport.push_back(hr_dport);
        end
        if (hr_tvalid) begin
            cur.push_back(hr_tdata);
            if (hr_tlast) begin
                logic [31:0] sip, dip;
                logic [15:0] sp, dp;
                sip = hq_sip.pop_front(); dip = hq_dip.pop_front(); sp = hq_sport.pop_front(); dp = hq_dport.pop_front();
                if (hr_tuser) err("host rx datagram tuser");
                if (sip != DUT_IP) err("src IP of result/reply");
                if (sp == 16'd5000) begin
                    logic [255:0] g, e;
                    logic [47:0]  ed;
                    for (int i = 0; i < 32; i++) g[8*i +: 8] = cur[i];
                    if (cur.size() != 32) err($sformatf("result length %0d", cur.size()));
                    else if (exp_res.size() == 0) err("unexpected result");
                    else begin
                        e = exp_res.pop_front();
                        ed = exp_dst.pop_front();
                        if (g !== e) err($sformatf("result %0d mismatch", n_res));
                        if ({dip, dp} != ed)
                            err($sformatf("result %0d sent to %h:%0d", n_res, dip, dp));
                    end
                    n_res++;
                end else if (sp == 16'd5001) begin
                    foreach (cur[i]) rpb.push_back(cur[i]);
                    rpl.push_back(cur.size());
                    rpd.push_back({dip, dp});
                end else
                    err($sformatf("src port %0d", sp));
                cur.delete();
            end
        end
    end

    // ---------------- AXI4-Lite register 모델 ----------------
    logic [31:0] rmem [0:4095];
    bit          aw_got = 0, w_got = 0, ar_got = 0, err_lb = 0, err_lr = 0;
    logic [31:0] aw_a, w_d, ar_a;
    int          r_wait = 0;
    always @(posedge clk) begin
        if (rst) begin
            l_bvalid <= 1'b0;
            l_rvalid <= 1'b0;
        end else begin
            if (l_awvalid && l_awready) begin aw_got = 1; aw_a = l_awaddr; end
            if (l_wvalid && l_wready) begin
                w_got = 1; w_d = l_wdata;
                if (l_wstrb != 4'hF) err("wstrb");
            end
            if (l_bvalid && l_bready) l_bvalid <= 1'b0;
            if (aw_got && w_got && !l_bvalid) begin
                if (aw_a >= 32'h4000) err($sformatf("register write addr %h", aw_a));
                rmem[aw_a[13:2]] = w_d;
                aw_got = 0; w_got = 0;
                l_bvalid <= 1'b1;
                l_bresp  <= err_lb ? 2'd2 : 2'd0;
                err_lb = 0;
            end
            l_awready <= !aw_got && $urandom_range(0, 2) != 0;
            l_wready  <= !w_got && $urandom_range(0, 2) != 0;
            if (l_arvalid && l_arready) begin
                ar_got = 1; ar_a = l_araddr; r_wait = $urandom_range(0, 4);
                if (ar_a >= 32'h4000) err($sformatf("register read addr %h", ar_a));
            end
            if (l_rvalid && l_rready) l_rvalid <= 1'b0;
            if (ar_got && !l_rvalid) begin
                if (r_wait > 0) r_wait--;
                else begin
                    l_rvalid <= 1'b1;
                    l_rdata  <= rmem[ar_a[13:2]];
                    l_rresp  <= err_lr ? 2'd2 : 2'd0;
                    ar_got = 0; err_lr = 0;
                end
            end
            l_arready <= !ar_got && $urandom_range(0, 2) != 0;
        end
    end

    // ---------------- DDR3 AXI4 slave 모델 ----------------
    logic [255:0] dmem [int unsigned];       // 32 B beat 번호
    logic [40:0]  blog[$];                   // {쓰기, 주소, len}
    bit           aw_act = 0, b_pend = 0, ar_act = 0, err_b = 0, err_r = 0;
    int unsigned  w_ptr, r_ptr;
    int           w_left = 0, r_left = 0, b_wait = 0, rd_wait = 0;
    int           n_ddr_w = 0, n_ddr_r = 0;

    function automatic logic [255:0] dread(input int unsigned i);
        return dmem.exists(i) ? dmem[i] : {8{i}};
    endfunction

    function automatic void burst_chk(input string s, input logic [31:0] a, input logic [7:0] len);
        if (run) err($sformatf("DDR3 %s while run = 1", s));
        if (a[4:0] != 0) err($sformatf("DDR3 %s addr %h not aligned", s, a));
        if (a[11:0] + (len + 1) * 32 > 4096) err($sformatf("DDR3 %s burst %h len %0d crosses 4 KiB", s, a, len));
    endfunction

    always @(posedge clk) begin
        if (rst) begin
            m_bvalid <= 1'b0;
            m_rvalid <= 1'b0;
        end else begin
            if (m_awvalid && m_awready) begin
                burst_chk("write", m_awaddr, m_awlen);
                blog.push_back({1'b1, m_awaddr, m_awlen});
                aw_act = 1; w_ptr = m_awaddr >> 5; w_left = m_awlen + 1;
            end
            if (m_wvalid && m_wready) begin
                if (!aw_act) err("W before AW");
                else begin
                    dmem[w_ptr] = m_wdata;
                    w_ptr++; w_left--; n_ddr_w++;
                    if (m_wlast != (w_left == 0)) err("wlast");
                    if (w_left == 0) begin aw_act = 0; b_pend = 1; b_wait = $urandom_range(0, 10); end
                end
            end
            if (m_bvalid && m_bready) m_bvalid <= 1'b0;
            if (b_pend && !m_bvalid) begin
                if (b_wait > 0) b_wait--;
                else begin
                    m_bvalid <= 1'b1;
                    m_bresp  <= err_b ? 2'd2 : 2'd0;
                    err_b = 0; b_pend = 0;
                end
            end
            m_awready <= !aw_act && !b_pend && $urandom_range(0, 2) != 0;
            m_wready  <= aw_act && $urandom_range(0, 3) != 0;

            if (m_arvalid && m_arready) begin
                burst_chk("read", m_araddr, m_arlen);
                blog.push_back({1'b0, m_araddr, m_arlen});
                ar_act = 1; r_ptr = m_araddr >> 5; r_left = m_arlen + 1; rd_wait = $urandom_range(5, 30);
            end
            if (m_rvalid && m_rready) m_rvalid <= 1'b0;
            if (ar_act && (!m_rvalid || m_rready)) begin
                if (rd_wait > 0) rd_wait--;
                else if ($urandom_range(0, 3) != 0) begin
                    m_rvalid <= 1'b1;
                    m_rdata  <= dread(r_ptr);
                    m_rlast  <= (r_left == 1);
                    m_rresp  <= err_r ? 2'd2 : 2'd0;
                    r_ptr++; r_left--; n_ddr_r++;
                    if (r_left == 0) begin ar_act = 0; err_r = 0; end
                end
            end
            m_arready <= !ar_act && !m_rvalid && $urandom_range(0, 2) != 0;
        end
    end

    // ---------------- AXI valid 유지 ----------------
    logic [39:0]  p_ar, p_aw, p_lar, p_law;
    logic [256:0] p_w;
    logic [31:0]  p_lw;
    bit           p_arv = 0, p_awv = 0, p_wv = 0, p_larv = 0, p_lawv = 0, p_lwv = 0;
    always @(posedge clk) begin
        if (!rst) begin
            if (p_arv && !(m_arvalid && {m_araddr, m_arlen} == p_ar)) err("AR valid dropped");
            if (p_awv && !(m_awvalid && {m_awaddr, m_awlen} == p_aw)) err("AW valid dropped");
            if (p_wv && !(m_wvalid && {m_wlast, m_wdata} == p_w)) err("W valid dropped");
            if (p_larv && !(l_arvalid && l_araddr == p_lar[31:0])) err("AXI4-Lite AR valid dropped");
            if (p_lawv && !(l_awvalid && l_awaddr == p_law[31:0])) err("AXI4-Lite AW valid dropped");
            if (p_lwv && !(l_wvalid && l_wdata == p_lw)) err("AXI4-Lite W valid dropped");
        end
        p_arv  <= m_arvalid && !m_arready;  p_ar  <= {m_araddr, m_arlen};
        p_awv  <= m_awvalid && !m_awready;  p_aw  <= {m_awaddr, m_awlen};
        p_wv   <= m_wvalid && !m_wready;    p_w   <= {m_wlast, m_wdata};
        p_larv <= l_arvalid && !l_arready;  p_lar <= {8'd0, l_araddr};
        p_lawv <= l_awvalid && !l_awready;  p_law <= {8'd0, l_awaddr};
        p_lwv  <= l_wvalid && !l_wready;    p_lw  <= l_wdata;
    end

    // ---------------- PHY reset, FCS 뒤집기 ----------------
    longint rst_end = 0, phy_up = -1;
    always @(posedge clk) begin
        if (rst) begin
            rst_end <= cyc + 1;
            if (phy_reset_n !== 1'b0 && cyc > 2) err("phy_reset_n != 0 during rst");
        end else if (phy_reset_n === 1'b1 && phy_up < 0)
            phy_up <= cyc - rst_end;
        if (phy_mdc !== 1'b0) err("MDC");
`ifndef VERILATOR
        if (phy_mdio !== 1'bz) err("MDIO");
`endif
    end

    bit fcs_arm = 0;
    always @(posedge h_txctl)
        if (fcs_arm) begin
            fcs_arm = 0;
            #400;
            flip = 1'b1;
            #8;
            flip = 1'b0;
        end

    // ---------------- Host 송신 task ----------------
    task automatic hwait(input int n);
        repeat (n) @(posedge hclk);
    endtask

    // 송신 handshake는 negedge에 내고 1 ns 뒤 ready를 본다. initial 안의 @(posedge) 뒤 읽기는 simulator마다
    // NBA 앞뒤가 달라(Verilator) handshake를 놓친다
    task automatic udp_send(input [15:0] sport, input [15:0] dport);
        @(negedge hclk);
        hs_hdr_valid = 1'b1;
        hs_sport     = sport;
        hs_dport     = dport;
        forever begin #1; if (hs_hdr_ready) break; @(negedge hclk); end
        @(negedge hclk);
        hs_hdr_valid = 1'b0;
        for (int i = 0; i < txq.size(); i++) begin
            hs_tvalid = 1'b1;
            hs_tdata  = txq[i];
            hs_tlast  = (i == txq.size() - 1);
            forever begin #1; if (hs_tready) break; @(negedge hclk); end
            @(negedge hclk);
        end
        hs_tvalid = 1'b0;
        hs_tlast  = 1'b0;
    endtask

    // 추론 요청 n개 datagram. good이면 기대값에 넣는다
    task automatic send_reqs(input int n, input [15:0] sport, input bit good);
        txq.delete();
        for (int r = 0; r < n; r++) begin
            logic [511:0] w;
            for (int k = 0; k < 64; k++) begin
                w[8*k +: 8] = $urandom;
                txq.push_back(w[8*k +: 8]);
            end
            if (good) begin
                exp_req.push_back(w);
                exp_res.push_back(f_res(w));
                exp_dst.push_back({host_ip, sport});
            end
        end
        udp_send(sport, 16'd5000);
    endtask

    // 길이 오류 datagram
    task automatic send_bad(input int len, input [15:0] sport);
        txq.delete();
        for (int i = 0; i < len; i++) txq.push_back($urandom);
        exp_len.push_back(len);
        udp_send(sport, 16'd5000);
    endtask

    // 날 IPv4 frame: payload ipq(UDP 머리 포함), ff = {flags, fragment offset}. udp_complete는 길이 0 datagram이나
    // IP 조각을 만들지 못하므로 Ethernet frame을 직접 MAC에 넣는다
    byte unsigned ipq[$];
    task automatic inject_ip(input [15:0] ff);
        byte unsigned fr[$];
        logic [31:0] cs;
        logic [15:0] tl;
        logic [7:0] ip [0:19];
        tl = 20 + ipq.size();
        ip = '{8'h45, 8'h00, tl[15:8], tl[7:0], 8'h00, 8'h00, ff[15:8], ff[7:0], 8'd64, 8'h11, 8'h00, 8'h00,
               host_ip[31:24], host_ip[23:16], host_ip[15:8], host_ip[7:0],
               DUT_IP[31:24], DUT_IP[23:16], DUT_IP[15:8], DUT_IP[7:0]};
        cs = 0;
        for (int i = 0; i < 20; i += 2) cs += {ip[i], ip[i+1]};
        cs = (cs & 32'hFFFF) + (cs >> 16);
        cs = (cs & 32'hFFFF) + (cs >> 16);
        ip[10] = ~cs[15:8];
        ip[11] = ~cs[7:0];
        for (int i = 5; i >= 0; i--) fr.push_back(DUT_MAC[8*i +: 8]);
        for (int i = 5; i >= 0; i--) fr.push_back(HOST_MAC[8*i +: 8]);
        fr.push_back(8'h08); fr.push_back(8'h00);
        for (int i = 0; i < 20; i++) fr.push_back(ip[i]);
        foreach (ipq[i]) fr.push_back(ipq[i]);
        hwait(3000);                         // Host 송신이 비었을 때 넣는다
        @(negedge hclk);
        inj = 1'b1;
        for (int i = 0; i < fr.size(); i++) begin
            inj_tvalid = 1'b1;
            inj_tdata  = fr[i];
            inj_tlast  = (i == fr.size() - 1);
            forever begin #1; if (hm_tx_tready) break; @(negedge hclk); end
            @(negedge hclk);
        end
        inj_tvalid = 1'b0;
        inj        = 1'b0;
    endtask

    // UDP 머리 + n B. ulen = UDP 머리의 길이
    task automatic udp_hdr(input [15:0] sport, input [15:0] dport, input [15:0] ulen, input int n);
        ipq.delete();
        ipq.push_back(sport[15:8]); ipq.push_back(sport[7:0]); ipq.push_back(dport[15:8]); ipq.push_back(dport[7:0]);
        ipq.push_back(ulen[15:8]); ipq.push_back(ulen[7:0]); ipq.push_back(8'h00); ipq.push_back(8'h00);
        for (int i = 0; i < n; i++) ipq.push_back($urandom);
    endtask

    // 길이 0 UDP datagram. port 5000이면 len_err 0
    task automatic inject_zero(input [15:0] sport, input [15:0] dport);
        udp_hdr(sport, dport, 16'd8, 0);
        if (dport == 16'd5000) exp_len.push_back(0);
        inject_ip(16'h0000);
    endtask

    // 모든 추론 요청이 결과로 돌아올 때까지
    task automatic barrier(input string s);
        int t = 0;
        while ((exp_req.size() || exp_res.size() || fq_d.size() || rs_valid || exp_len.size()) && t < 400_000) begin
            @(posedge hclk);
            t++;
        end
        if (t >= 400_000)
            err($sformatf("%s: left requests %0d, results %0d, len_err %0d", s, exp_req.size(), exp_res.size(), exp_len.size()));
    endtask

    // ---------------- 제어 packet ----------------
    logic [31:0] wd[$], rd[$];
    // 보낸 제어 요청: 머리 앞 10 B(못 보낸 byte는 0), 응답 port, 기대 응답 길이, 기대 status
    byte unsigned pq[$];
    logic [15:0]  p_sport[$];
    int           p_rlen[$], p_st[$];

    task automatic ctl_send(input [15:0] sport, input [7:0] magic, input [7:0] op, input [31:0] addr, input [15:0] cnt,
                            input int nw, input int extra, input int trunc, input int exp_st);
        logic [15:0] tag;
        tag = $urandom;
        txq.delete();
        txq.push_back(magic); txq.push_back(op); txq.push_back(tag[7:0]); txq.push_back(tag[15:8]);
        for (int i = 0; i < 4; i++) txq.push_back(addr[8*i +: 8]);
        txq.push_back(cnt[7:0]); txq.push_back(cnt[15:8]); txq.push_back(8'h00); txq.push_back(8'h00);
        for (int i = 0; i < nw; i++)
            for (int b = 0; b < 4; b++) txq.push_back(wd[i][8*b +: 8]);
        for (int i = 0; i < extra; i++) txq.push_back(8'h00);
        if (trunc > 0) while (txq.size() > trunc) void'(txq.pop_back());
        for (int i = 0; i < 10; i++) pq.push_back((i < txq.size()) ? txq[i] : 8'h00);
        p_sport.push_back(sport);
        p_rlen.push_back((op == 8'd1 && exp_st == 0) ? 12 + 4 * cnt : 12);
        p_st.push_back(exp_st);
        udp_send(sport, 16'd5001);
    endtask

    // 가장 앞 제어 요청의 응답을 기다려 확인하고 읽은 데이터를 rd에 둔다
    task automatic ctl_wait(input string name);
        int t, len, rlen, st;
        logic [47:0] dst;
        logic [15:0] sport;
        byte unsigned r[$];
        t = 0;
        while (rpl.size() == 0 && t < 200_000) begin @(posedge hclk); t++; end
        n_ctl++;
        rd.delete();
        sport = p_sport.pop_front();
        rlen  = p_rlen.pop_front();
        st    = p_st.pop_front();
        if (rpl.size() == 0) begin
            err($sformatf("%s: no reply", name));
            repeat (10) void'(pq.pop_front());
            return;
        end
        len = rpl.pop_front();
        dst = rpd.pop_front();
        for (int i = 0; i < len; i++) r.push_back(rpb.pop_front());
        if (dst != {host_ip, sport}) err($sformatf("%s: reply sent to %h", name, dst));
        for (int i = 0; i < 10; i++) begin
            byte unsigned h;
            h = pq.pop_front();
            if (i < len && r[i] != h) err($sformatf("%s: reply header byte %0d", name, i));
        end
        if (len != rlen) begin
            err($sformatf("%s: reply length %0d, expected %0d", name, len, rlen));
            return;
        end
        if ({r[11], r[10]} != st[15:0])
            err($sformatf("%s: status %0d, expected %0d", name, {r[11], r[10]}, st));
        for (int i = 12; i < rlen; i += 4) rd.push_back({r[i+3], r[i+2], r[i+1], r[i]});
    endtask

    // 마지막으로 보낸 제어 요청은 버려질 것이므로 기대값에서 뺀다
    task automatic ctl_forget();
        repeat (10) void'(pq.pop_back());
        void'(p_sport.pop_back()); void'(p_rlen.pop_back()); void'(p_st.pop_back());
    endtask

    task automatic ctl(input [15:0] sport, input [7:0] magic, input [7:0] op, input [31:0] addr, input [15:0] cnt,
                       input int nw, input int extra, input int trunc, input int exp_st, input string name);
        ctl_send(sport, magic, op, addr, cnt, nw, extra, trunc, exp_st);
        ctl_wait(name);
    endtask

    task automatic fill_wd(input int n);
        wd.delete();
        for (int i = 0; i < n; i++) wd.push_back($urandom);
    endtask

    // DDR3 창 내용과 wd 비교(MIG 주소 a부터 n word)
    task automatic chk_dmem(input logic [31:0] a, input int n, input string name);
        for (int i = 0; i < n; i++) begin
            logic [255:0] b;
            logic [31:0]  v;
            b = dread((a >> 5) + i / 8);
            v = b[32*(i%8) +: 32];           // xsim 2026.1은 넓은 vector의 part-select와 queue 원소를 바로 비교하면 같아도 다르다고 낸다
            if (v !== wd[i]) begin err($sformatf("%s: DDR3 word %0d", name, i)); break; end
        end
    endtask

    task automatic chk_rd(input int n, input string name);
        if (rd.size() != n) err($sformatf("%s: read %0d words", name, rd.size()));
        else for (int i = 0; i < n; i++)
            if (rd[i] !== wd[i]) begin err($sformatf("%s: read word %0d mismatch", name, i)); break; end
    endtask

    logic [40:0] e[$];                       // 기대 burst
    function automatic logic [40:0] bu(input bit w, input logic [31:0] a, input logic [7:0] len);
        return {w, a, len};
    endfunction
    task automatic chk_log(input string name);
        if (blog.size() != e.size()) err($sformatf("%s: %0d bursts, expected %0d", name, blog.size(), e.size()));
        else foreach (e[i])
            if (blog[i] != e[i]) err($sformatf("%s: burst %0d = %h, expected %h", name, i, blog[i], e[i]));
        blog.delete();
        e.delete();
    endtask

    // ---------------- 순서 ----------------
    int e0;
    initial begin
        for (int i = 0; i < 4096; i++) rmem[i] = 32'hDEAD_0000 + i;
        rmem[0] = 32'h534E_4E58;
        repeat (20) @(negedge clk);
        rst  = 1'b0;
        hrst = 1'b0;
        hwait(300);

        // 1. 추론 요청: Host IP .1, port 6000. 사이사이 길이 오류(port 7777)·다른 port·제어 읽기
        e0 = errors;
        send_reqs(1, 16'd6000, 1'b1);
        send_reqs(23, 16'd6000, 1'b1);
        for (int i = 0; i < 24; i++) begin
            send_reqs($urandom_range(1, 23), 16'd6000, 1'b1);
            case (i)
            3:  send_bad(1536, 16'd7777);    // 24개
            6:  begin send_bad(100, 16'd7777); send_bad(1, 16'd7777); end
            9:  begin send_bad(63, 16'd7777); send_bad(1480, 16'd7777); end
            12: begin txq.delete(); repeat (128) txq.push_back(8'hEE); udp_send(16'd6000, 16'd6000); end
            15: begin wd.delete(); ctl(16'd6100, 8'h5C, 8'd1, 32'h0000_0000, 16'd1, 0, 0, 0, 0, "ID read during results");
                      if (rd.size() != 1 || rd[0] != 32'h534E_4E58) err("ID value"); end
            18: begin inject_zero(16'd7777, 16'd5000); inject_zero(16'd7777, 16'd5001); inject_zero(16'd7777, 16'd6000); end
            21: begin
                    // MF가 선 첫 조각(UDP 머리 길이 200 B, 실제 128 B): 전체를 버리고 len_err 192
                    udp_hdr(16'd7777, 16'd5000, 16'd200, 128);
                    exp_len.push_back(192);
                    inject_ip(16'h2000);
                    // 뒤 조각(offset 1,480 B): 앞 8 B가 정상 추론 요청 머리처럼 보여도 버린다
                    udp_hdr(16'd7777, 16'd5000, 16'd72, 64);
                    inject_ip(16'd185);
                end
            default: ;
            endcase
            if (i % 6 == 5) barrier("request group");
        end
        barrier("phase 1");
        // 모델 그룹: 23개 datagram 11개를 선로 속도로
        for (int i = 0; i < 11; i++) send_reqs(23, 16'd6000, 1'b1);
        barrier("model group burst");
        $display("run   요청·결과: 요청 %0d, 결과 %0d, len_err %0d, 오류 %0d", n_req, n_res, n_lenerr, errors - e0);

        // 2. FCS: 선의 bit를 뒤집은 frame은 버리고 다음 것은 받는다
        e0 = errors;
        begin
            int f0;
            f0 = n_fcs;
            hwait(2000);
            fcs_arm = 1;
            send_reqs(5, 16'd6000, 1'b0);
            hwait(3000);
            send_reqs(3, 16'd6000, 1'b1);
            barrier("FCS");
            if (n_fcs != f0 + 1) err($sformatf("%0d bad FCS frames", n_fcs - f0));
        end
        $display("run   FCS: 틀린 frame %0d개 버림, 오류 %0d", n_fcs, errors - e0);

        // 3. 받는 곳 바꾸기: port 6001, 그다음 Host IP .7 port 6002(FPGA가 .7을 ARP로 찾음)
        e0 = errors;
        for (int i = 0; i < 8; i++) send_reqs($urandom_range(1, 23), 16'd6001, 1'b1);
        send_bad(128 + 1, 16'd6009);
        barrier("port 6001");
        host_ip = IP7;
        for (int i = 0; i < 8; i++) send_reqs($urandom_range(1, 23), 16'd6002, 1'b1);
        barrier("IP .7");
        if (n_arp_rx < 2 || n_arp_tx < 2) err($sformatf("ARP frames rx %0d, tx %0d", n_arp_rx, n_arp_tx));
        $display("run   받는 곳: 요청 %0d, 결과 %0d, ARP 받음 %0d·보냄 %0d, 오류 %0d", n_req, n_res, n_arp_rx, n_arp_tx, errors - e0);

        // 4. 제어 packet
        e0 = errors;
        blog.delete();
        fill_wd(3);
        ctl(16'd6100, 8'h5C, 8'd2, 32'h0000_0300, 16'd3, 3, 0, 0, 0, "config write");
        for (int i = 0; i < 3; i++) if (rmem[12'h0C0 + i] !== wd[i]) err("config write value");
        ctl(16'd6101, 8'h5C, 8'd1, 32'h0000_0300, 16'd3, 0, 0, 0, 0, "config read");
        chk_rd(3, "config read");
        fill_wd(256);
        ctl(16'd6100, 8'h5C, 8'd2, 32'h0000_1000, 16'd256, 256, 0, 0, 0, "register 1 KiB write");
        ctl(16'd6100, 8'h5C, 8'd1, 32'h0000_1000, 16'd256, 0, 0, 0, 0, "register 1 KiB read");
        chk_rd(256, "register 1 KiB read");
        for (int i = 0; i < 256; i++) if (rmem[12'h400 + i] !== wd[i]) begin err("register 1 KiB value"); break; end
        chk_log("register");

        // DDR3: 4 KiB 경계를 넘는 1 KiB
        ctl(16'd6100, 8'h5C, 8'd2, 32'h8000_0F00, 16'd256, 256, 0, 0, 0, "DDR3 1 KiB write across 4 KiB");
        chk_dmem(32'h0F00, 256, "DDR3 1 KiB write across 4 KiB");
        e = '{bu(1'b1, 32'h0F00, 8'd7), bu(1'b1, 32'h1000, 8'd23)};
        chk_log("DDR3 write split");
        ctl(16'd6100, 8'h5C, 8'd1, 32'h8000_0F00, 16'd256, 0, 0, 0, 0, "DDR3 1 KiB read across 4 KiB");
        chk_rd(256, "DDR3 1 KiB read across 4 KiB");
        e = '{bu(1'b0, 32'h0F00, 8'd7), bu(1'b0, 32'h1000, 8'd23)};
        chk_log("DDR3 read split");
        fill_wd(256);
        ctl(16'd6100, 8'h5C, 8'd2, 32'h8000_2000, 16'd256, 256, 0, 0, 0, "DDR3 1 KiB write");
        chk_dmem(32'h2000, 256, "DDR3 1 KiB write");
        ctl(16'd6100, 8'h5C, 8'd1, 32'h8000_2000, 16'd256, 0, 0, 0, 0, "DDR3 1 KiB read");
        chk_rd(256, "DDR3 1 KiB read");
        e = '{bu(1'b1, 32'h2000, 8'd31), bu(1'b0, 32'h2000, 8'd31)};
        chk_log("DDR3 single burst");
        // 결과가 .7로 가는 중에 FPGA ARP cache에 없는 .9에서 제어 요청 A(오래 걸림)와 B를 이어 보낸다.
        // A의 응답은 .9로, 결과보다 늦게 가야 한다. B는 A의 응답 전에 왔으므로 버려지고, 다시 보내면 처리된다.
        // 받기를 멈춰 B를 붙잡으면 .9의 ARP reply가 B 뒤에 막혀 A의 응답이 나가지 못한다
        begin
            int p0;
            p0 = n_prio;
            hold_rs = 1;
            send_reqs(23, 16'd6002, 1'b1);
            hwait(3000);
            host_ip = IP9;
            ctl_send(16'd6102, 8'h5C, 8'd1, 32'h8000_2000, 16'd256, 0, 0, 0, 0);
            ctl_send(16'd6103, 8'h5C, 8'd2, 32'h0000_0320, 16'd2, 2, 0, 0, 0);
            ctl_forget();
            ctl_wait("DDR3 read from new IP during results");
            hold_rs = 0;
            chk_rd(256, "DDR3 read from new IP during results");
            hwait(5000);
            if (rpl.size() != 0) err("control request sent before the reply was answered");
            if (rmem[12'h0C8] === wd[0]) err("control request sent before the reply was executed");
            ctl(16'd6103, 8'h5C, 8'd2, 32'h0000_0320, 16'd2, 2, 0, 0, 0, "retried register write");
            if (rmem[12'h0C8] !== wd[0] || rmem[12'h0C9] !== wd[1]) err("retried register value");
            host_ip = IP7;
            barrier("results during reply");
            if (n_prio == p0) err("no result and reply waited together");
            e = '{bu(1'b0, 32'h2000, 8'd31)};
            chk_log("reply source");
        end
        fill_wd(16);
        ctl(16'd6100, 8'h5C, 8'd2, 32'hBFFF_EFE0, 16'd16, 16, 0, 0, 0, "DDR3 64 B write across 4 KiB");
        chk_dmem(32'h3FFF_EFE0, 16, "DDR3 64 B write across 4 KiB");
        ctl(16'd6100, 8'h5C, 8'd1, 32'hBFFF_EFE0, 16'd16, 0, 0, 0, 0, "DDR3 64 B read across 4 KiB");
        chk_rd(16, "DDR3 64 B read across 4 KiB");
        e = '{bu(1'b1, 32'h3FFF_EFE0, 8'd0), bu(1'b1, 32'h3FFF_F000, 8'd0),
                  bu(1'b0, 32'h3FFF_EFE0, 8'd0), bu(1'b0, 32'h3FFF_F000, 8'd0)};
        chk_log("DDR3 64 B split");

        // run = 1: DDR3는 status 2, register는 그대로 한다
        run = 1'b1;
        fill_wd(8);
        ctl(16'd6100, 8'h5C, 8'd2, 32'h8000_3000, 16'd8, 8, 0, 0, 2, "DDR3 write while run");
        ctl(16'd6100, 8'h5C, 8'd1, 32'h8000_2000, 16'd8, 0, 0, 0, 2, "DDR3 read while run");
        if (dmem.exists(32'h3000 >> 5)) err("DDR3 written while run");
        ctl(16'd6100, 8'h5C, 8'd2, 32'h0000_0104, 16'd1, 1, 0, 0, 0, "CTRL write while run");
        if (rmem[12'h041] !== wd[0]) err("CTRL value while run");
        run = 1'b0;
        chk_log("while run");

        // status 1·3
        fill_wd(8);
        ctl(16'd6100, 8'h5C, 8'd2, 32'h8000_0010, 16'd8, 8, 0, 0, 1, "DDR3 not 32 B aligned");
        ctl(16'd6100, 8'h5C, 8'd1, 32'h0000_0302, 16'd1, 0, 0, 0, 1, "register not 4 B aligned");
        ctl(16'd6100, 8'h5C, 8'd1, 32'h8000_0000, 16'd4, 0, 0, 0, 3, "DDR3 count 4");
        ctl(16'd6100, 8'h5C, 8'd1, 32'h0000_0000, 16'd0, 0, 0, 0, 3, "count 0");
        ctl(16'd6100, 8'h5C, 8'd1, 32'h0000_0000, 16'd257, 0, 0, 0, 3, "count 257");
        ctl(16'd6100, 8'h5C, 8'd1, 32'hC000_0000, 16'd8, 0, 0, 0, 1, "outside DDR3 window");
        ctl(16'd6100, 8'h5C, 8'd1, 32'hBFFF_FFE0, 16'd16, 0, 0, 0, 1, "past DDR3 window end");
        ctl(16'd6100, 8'h5C, 8'd1, 32'h7FFF_FFFC, 16'd2, 0, 0, 0, 1, "register into DDR3");
        ctl(16'd6100, 8'h5C, 8'd2, 32'h0000_0310, 16'd4, 3, 0, 0, 3, "write data short");
        if (rmem[12'h0C4] !== 32'hDEAD_00C4) err("short write request was written");
        ctl(16'd6100, 8'h5C, 8'd2, 32'h0000_0310, 16'd2, 3, 0, 0, 3, "write data long");
        ctl(16'd6100, 8'h5C, 8'd1, 32'h0000_0310, 16'd1, 0, 4, 0, 3, "read with data");
        ctl(16'd6100, 8'hA5, 8'd1, 32'h0000_0000, 16'd1, 0, 0, 0, 3, "bad magic");
        ctl(16'd6100, 8'h5C, 8'd3, 32'h0000_0000, 16'd1, 0, 0, 0, 3, "op 3");
        ctl(16'd6100, 8'h5C, 8'd1, 32'h0000_0000, 16'd1, 0, 0, 5, 3, "5 B header");
        chk_log("bad requests");
        // AXI 오류 응답
        fill_wd(8);
        err_b = 1;
        ctl(16'd6100, 8'h5C, 8'd2, 32'h8000_4000, 16'd8, 8, 0, 0, 1, "DDR3 write SLVERR");
        err_r = 1;
        ctl(16'd6100, 8'h5C, 8'd1, 32'h8000_4000, 16'd8, 0, 0, 0, 1, "DDR3 read SLVERR");
        blog.delete();
        err_lb = 1;
        ctl(16'd6100, 8'h5C, 8'd2, 32'h0000_0330, 16'd1, 1, 0, 0, 1, "register write SLVERR");
        err_lr = 1;
        ctl(16'd6100, 8'h5C, 8'd1, 32'h0000_0330, 16'd1, 0, 0, 0, 1, "register read SLVERR");
        // 다시 정상
        ctl(16'd6100, 8'h5C, 8'd1, 32'h8000_4000, 16'd8, 0, 0, 0, 0, "DDR3 read after error");
        chk_rd(8, "DDR3 read after error");
        $display("run   제어: 요청 %0d개, DDR3 beat 쓰기 %0d·읽기 %0d, 결과·응답 동시 대기 %0d, ARP 받음 %0d·보냄 %0d, 오류 %0d",
                 n_ctl, n_ddr_w, n_ddr_r, n_prio, n_arp_rx, n_arp_tx, errors - e0);

        // 5. 끝
        e0 = errors;
        send_reqs(23, 16'd6002, 1'b1);
        barrier("end");
        if (phy_up < PHY_RST || phy_up > PHY_RST + 1) err($sformatf("phy_reset_n rose %0d cycles after rst", phy_up));
        if (hq_sip.size() != 0 || cur.size() != 0 || rpl.size() != 0) err("datagram left in host");
        $display("run   끝: 요청 %0d, 결과 %0d, phy_reset_n %0d cycle, 오류 %0d, %0d cycle", n_req, n_res, phy_up, errors - e0, cyc);
        if (errors == 0) $display("PASS");
        else $display("FAIL 오류 %0d개", errors);
        $finish;
    end

endmodule
