// ============================================================
// tb_sys.sv — accel_sys 전체를 Ethernet 너머 Host와 DDR3 모델에 맞대어 golden_l64_m12와 대조 (P4.10)
// ============================================================
// Host 쪽은 tb_eth와 같은 verilog-ethernet stack(eth_mac_1g_rgmii_fifo + udp_complete, TARGET GENERIC, 125 MHz + 250 ppm)을
// RGMII 선으로 accel_sys에 잇는다. DDR3는 AXI4 256 bit slave 모델이다: 무작위 ready·지연·beat 간격(tb_dma MODE 1),
// ID가 다른 읽기 burst끼리 beat 섞기. 모델 slot m = 0x40000 × m(유효 4,114 beat), 트랙 k = 0x0200_0000 + 0x800 × k.
// 순서 (06_HOST_INTERFACE.md §6):
//   1) mig_calib = 0: DDR3 창 읽기·쓰기는 status 2, register 읽기(ID, VERSION, N_ENTRY, N_ONCHIP, STATUS.MIG_CALIB 0)
//   2) mig_calib = 1 뒤: 모델 0·1(+FULL=1이면 40개 모두)을 1 KiB 제어 쓰기로 DDR3 창에 적재하고 다시 읽어 비교.
//      나머지 slot은 DDR3 모델에 직접 넣는다(backdoor)
//   3) 설정 쓰기와 읽기(LINK_TUNE과 tx_ps 포함), PNU 표(주소마다 다른 값, 그다음 시나리오 값)를 쓰고 predictor 안 값을 계층 이름으로 확인, SOFT_RESET, STATUS.IDLE, RUN = 1, RUN = 1일 때 설정·DDR3 쓰기 무시
//   4) golden vector 80개(모델 0~39 × 2, 포화 시험용 모델 40·41 제외)를 트랙 80개(on-chip 60, DDR3 20)에.
//      t = 0~NT−1마다 NOW_US를 읽어 t_host로 쓰고 80개를 datagram(최대 23개)으로 보낸 뒤 결과 80개를 다 받는다.
//      결과마다 out0·out1이 golden과 bit 일치, track·seq·model·flags(RESET_STATE, 포화 0, LATE 식)·batch_n 1~2·시각 순서
//   5) IDLE 뒤 RUN = 0, counter 확인(REQ_IN, RES_OUT, REQ_DROP 0, WEIGHT_BYTES, STATE_BYTES, BATCHES, CMP_BUSY·CMP_STALL 등과
//      DDR3 모델이 센 beat), DDR3 트랙의 membrane potential을 DDR3 창으로 읽어 golden 마지막 12 bit 저장값과 비교
//   5b) cache에 있는 두 모델의 slot을 맞바꿔 쓰고 SOFT_RESET: entry·pending·counter·NOW_US 0, DEADLINE_US 1로
//      t = 0 한 번(model_id도 맞바꿈). 옛 entry가 남으면 out이 어긋난다. 결과마다 LATE, LATE counter 80, SAT_COUNT 0
//   6) 오류: model_id 45 → ERR_CODE 3·ERR_INFO 트랙, 100 B datagram은 첫 오류를 바꾸지 않음, ERR_CLEAR,
//      다시 100 B datagram → ERR_CODE 7·ERR_INFO 100
//   AXI 규칙(valid 유지, 4 KiB 경계, 주소 범위, 주소 전 W 없음, wlast, run 쪽마다 burst 꼴), RUN이 바뀔 때 DDR3 거래 없음,
//   DDR3 트랙 결과는 되쓰기 B 응답 뒤, 결과·DDR3 쓰기 data에 X 없음
// plusarg: +FULL=1 모델 40개를 모두 Ethernet으로 적재, +NT=n timestep 수(기본 31), +MAXERR=n 오류 n개면 멈춤
// 실행 (저장소 루트):
//   bash hardware/testbench/run_sys.sh
// ============================================================
`timescale 1ns / 1ps

module tb_sys;

    localparam [47:0] HOST_MAC = 48'h02_00_00_00_00_10;
    localparam [31:0] DUT_IP   = {8'd192, 8'd168, 8'd10, 8'd2};
    localparam [31:0] HOST_IP  = {8'd192, 8'd168, 8'd10, 8'd1};
    localparam [15:0] RPORT = 16'd6000, CPORT = 16'd6100;
    localparam int    PHY_RST = 50, E = 4, N_MOD = 40, N_VEC = 80, N_ONCHIP = 768, T = 31, ROWS = 45, LD = 4114;
    localparam string VEC = "hardware/sim/compute_array/vec_m12/";
    localparam [31:0] SB = 32'h0200_0000, DEADLINE = 32'd32000, MARGIN = 32'd0;

    int full = 0, nt = T, maxerr = 40;
    logic [31:0] dl = DEADLINE;              // 지금 DEADLINE_US(5b에서 1로 바꾼다)
    int          mmap [0:N_MOD-1];           // 요청에 싣는 model_id(5b에서 slot을 맞바꾼 두 모델만 다르다)
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
    reg rst = 1'b1, hrst = 1'b1, mig_calib = 1'b0;
    longint cyc = 0, wd_lim = 40_000_000;
    always @(posedge clk) begin
        cyc <= cyc + 1;
        if (cyc > wd_lim) begin
            $display("FAIL 시간 초과: cycle %0d", cyc);
            $finish;
        end
        if (errors >= maxerr) begin
            $display("FAIL 오류 %0d개에서 멈춤: cycle %0d", errors, cyc);
            $finish;
        end
    end

    // ---------------- DUT ----------------
    wire         d_txc, d_txctl, h_txc, h_txctl;
    wire [3:0]   d_txd, h_txd;
    wire         phy_reset_n, phy_mdc, phy_mdio, run, sys_idle;
    wire [15:0]  tx_ps;
    wire [31:0]  m_araddr, m_awaddr;
    wire [7:0]   m_arlen, m_awlen;
    wire         m_arid, m_arvalid, m_rready, m_awvalid, m_wlast, m_wvalid, m_bready;
    wire [255:0] m_wdata;
    reg          m_arready = 1'b0, m_rvalid = 1'b0, m_rid = 1'b0, m_rlast = 1'b0;
    reg          m_awready = 1'b0, m_wready = 1'b0, m_bvalid = 1'b0;
    reg  [255:0] m_rdata = '0;
    reg  [1:0]   m_rresp = 2'd0, m_bresp = 2'd0;

    accel_sys #(.TARGET("GENERIC"), .PHY_RST_CYC(PHY_RST), .E(E), .N_MODELS(N_MOD), .N_ONCHIP(N_ONCHIP)) dut (
        .clk(clk), .rst(rst), .mig_calib(mig_calib), .gtx_clk(gtx), .gtx_clk90(gtx90),
        .rgmii_rx_clk(h_txc), .rgmii_rxd(h_txd), .rgmii_rx_ctl(h_txctl),
        .rgmii_tx_clk(d_txc), .rgmii_txd(d_txd), .rgmii_tx_ctl(d_txctl),
        .phy_reset_n(phy_reset_n), .phy_mdc(phy_mdc), .phy_mdio(phy_mdio),
        .m_axi_araddr(m_araddr), .m_axi_arlen(m_arlen), .m_axi_arid(m_arid), .m_axi_arvalid(m_arvalid),
        .m_axi_arready(m_arready), .m_axi_rdata(m_rdata), .m_axi_rid(m_rid), .m_axi_rresp(m_rresp),
        .m_axi_rlast(m_rlast), .m_axi_rvalid(m_rvalid), .m_axi_rready(m_rready),
        .m_axi_awaddr(m_awaddr), .m_axi_awlen(m_awlen), .m_axi_awvalid(m_awvalid), .m_axi_awready(m_awready),
        .m_axi_wdata(m_wdata), .m_axi_wlast(m_wlast), .m_axi_wvalid(m_wvalid), .m_axi_wready(m_wready),
        .m_axi_bresp(m_bresp), .m_axi_bvalid(m_bvalid), .m_axi_bready(m_bready),
        .tx_ps(tx_ps), .run(run), .sys_idle(sys_idle)
    );

    // ---------------- Host network stack (tb_eth와 같다) ----------------
    wire [7:0]  hm_tx_tdata, hm_rx_tdata, he_rx_tdata, ht_tdata;
    wire        hm_tx_tvalid, hm_tx_tready, hm_tx_tlast, hm_tx_tuser;
    wire        hm_rx_tvalid, hm_rx_tlast, hm_rx_tuser, hm_rx_tready;
    wire        he_rx_tvalid, he_rx_tready, he_rx_tlast, he_rx_tuser;
    wire        heh_rx_valid, heh_rx_ready, heh_tx_valid, heh_tx_ready;
    wire [47:0] heh_rx_dmac, heh_rx_smac, heh_tx_dmac, heh_tx_smac;
    wire [15:0] heh_rx_type, heh_tx_type;
    reg         hs_hdr_valid = 1'b0, hs_tvalid = 1'b0, hs_tlast = 1'b0;
    reg  [15:0] hs_sport = 16'd0, hs_dport = 16'd0;
    reg  [7:0]  hs_tdata = 8'd0;
    wire        hs_hdr_ready, hs_tready;
    wire        hr_hdr_valid, hr_tvalid, hr_tlast, hr_tuser;
    wire [31:0] hr_sip, hr_dip;
    wire [15:0] hr_sport, hr_dport;
    wire [7:0]  hr_tdata;
    wire        ht_tvalid, ht_tready, ht_tlast, ht_tuser;

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
        .m_axis_tdata(hm_tx_tdata), .m_axis_tkeep(), .m_axis_tvalid(hm_tx_tvalid), .m_axis_tready(hm_tx_tready),
        .m_axis_tlast(hm_tx_tlast), .m_axis_tuser(hm_tx_tuser),
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
        .s_udp_ip_ttl(8'd64), .s_udp_ip_source_ip(HOST_IP), .s_udp_ip_dest_ip(DUT_IP),
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
        .local_mac(HOST_MAC), .local_ip(HOST_IP), .gateway_ip(HOST_IP), .subnet_mask({8'd255, 8'd255, 8'd255, 8'd0}),
        .clear_arp_cache(1'b0)
    );

    // ---------------- Host 받기: 결과(port 5000에서)와 제어 응답(5001에서) ----------------
    byte unsigned cur[$];
    logic [31:0]  hq_dip[$], hq_sip[$];
    logic [15:0]  hq_sport[$], hq_dport[$];
    logic [255:0] res_q[$];                  // 받은 결과
    byte unsigned rpb[$];                    // 받은 제어 응답 byte(이어 붙임)
    int           rpl[$];                    // 응답마다 길이
    always @(posedge hclk) begin
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
                if (sip != DUT_IP || dip != HOST_IP) err($sformatf("datagram IP %h -> %h", sip, dip));
                if (sp == 16'd5000) begin
                    logic [255:0] g;
                    for (int i = 0; i < 32; i++) g[8*i +: 8] = (i < cur.size()) ? cur[i] : 8'h00;
                    if (cur.size() != 32) err($sformatf("result length %0d", cur.size()));
                    if (dp != RPORT) err($sformatf("result sent to port %0d", dp));
                    res_q.push_back(g);
                end else if (sp == 16'd5001) begin
                    if (dp != CPORT) err($sformatf("reply sent to port %0d", dp));
                    foreach (cur[i]) rpb.push_back(cur[i]);
                    rpl.push_back(cur.size());
                end else
                    err($sformatf("src port %0d", sp));
                cur.delete();
            end
        end
    end

    // ---------------- data ----------------
    reg [7:0]   idx  [0:81];
    reg [511:0] wall [0:N_MOD*2034-1];
    reg [255:0] pall [0:N_MOD*46-1];
    reg [319:0] xall [0:N_VEC*T-1];
    reg [911:0] eall [0:N_VEC*T*ROWS-1];
    reg [31:0]  oall [0:N_VEC*T-1];
    int         vof  [0:1023];               // 트랙의 vector, 없으면 −1

    function automatic int trk(input int v);   // tb_dma와 같다
        case (v)
        0: trk = 0;
        1: trk = 768;
        2: trk = 767;
        3: trk = 1023;
        default: trk = (v * 37 + 11) % 1024;
        endcase
    endfunction

    // slot 이미지 beat b: params row 46개, 그다음 word마다 beat 2개(앞 beat = word bit [255:0])
    function automatic logic [255:0] img_beat(input int m, input int b);
        logic [511:0] w;
        if (b < 46) return pall[m * 46 + b];
        w = wall[m * 2034 + (b - 46) / 2];
        return ((b - 46) % 2 != 0) ? w[511:256] : w[255:0];
    endfunction

    // ---------------- DDR3: AXI4 slave 모델 ----------------
    reg [255:0] mslot  [0:N_MOD*LD-1];       // slot m의 beat b = mslot[m × 4,114 + b]
    reg [255:0] mstate [0:65535];            // 트랙 k의 beat i = mstate[k × 64 + i]

    function automatic bit in_slot(input [31:0] a);
        return a < SB && (a >> 18) < N_MOD && ((a >> 5) & 32'h1FFF) < LD;
    endfunction
    function automatic bit in_state(input [31:0] a);
        return a >= SB && a < SB + 32'h0020_0000;
    endfunction
    function automatic int slot_i(input [31:0] a);
        return (a >> 18) * LD + ((a >> 5) & 32'h1FFF);
    endfunction
    function automatic logic [255:0] ddr_rd(input [31:0] a);
        if (in_state(a)) return mstate[(a - SB) >> 5];
        if (in_slot(a))  return mslot[slot_i(a)];
        return {8{32'hBAD0_BAD0}};
    endfunction

    typedef struct packed {
        logic [31:0] addr;
        logic [7:0]  len;
        logic [63:0] t;
    } burst_t;

    burst_t rq0[$], rq1[$], awq[$], bq[$];
    int     rk0 = 0, rk1 = 0, wk = 0, n_prot = 0;
    longint rb0_run = 0, rb1_run = 0, wb_run = 0, rb_ctl = 0, wb_ctl = 0, n_ar_run = 0;

    function automatic void prot(input string s);
        n_prot++;
        err($sformatf("AXI: %s (cycle %0d)", s, cyc));
    endfunction

    // burst 꼴: 정렬, 4 KiB 경계, 주소 범위. run = 1이면 dma(weight ID 0 ≤ 16 beat, membrane potential 34 beat),
    // run = 0이면 ctrl(ID 0, ≤ 32 beat)
    function automatic void chk_burst(input string s, input bit wr, input [31:0] a, input [7:0] len, input bit id);
        logic [31:0] z;
        longint k;
        z = a + 32 * len;
        if (a[4:0] != 5'd0 || ({20'd0, a[11:0]} + (len + 1) * 32) > 4096) prot({s, " 정렬·4 KiB 경계"});
        if (!((in_slot(a) && in_slot(z)) || (in_state(a) && in_state(z)))) prot($sformatf("%s 주소 %h len %0d 범위 밖", s, a, len));
        k = (a - SB) >> 11;
        if (run) begin
            if (wr || id) begin
                if (len != 8'd33 || !in_state(a) || ((a - SB) & 32'h7FF) != 0 || k < N_ONCHIP)
                    prot($sformatf("%s membrane potential burst %h len %0d", s, a, len));
            end else if (len + 1 > 16 || !in_slot(a))
                prot($sformatf("%s weight burst %h len %0d", s, a, len));
        end else begin
            if (id) prot({s, " ctrl ID 1"});
            if (len + 1 > 32) prot($sformatf("%s ctrl burst len %0d", s, len));
        end
    endfunction

    // 읽기 채널: ID마다 순서대로, ID 0·1 사이는 beat를 섞는다
    always @(posedge clk) begin : rd_ch
        burst_t b;
        bit c0, c1, p1;
        if (m_arvalid && m_arready) begin
            chk_burst("read", 1'b0, m_araddr, m_arlen, m_arid);
            b.addr = m_araddr;
            b.len  = m_arlen;
            b.t    = cyc + 8 + $urandom % 50;
            if (m_arid) rq1.push_back(b); else rq0.push_back(b);
            if (rq0.size() > 4) prot("동시 ID 0 burst > 4");
            if (run) n_ar_run++;
        end
        m_arready <= ($urandom % 2 == 0);
        if (m_rvalid && m_rready) begin
            if (run) begin if (m_rid) rb1_run++; else rb0_run++; end
            else rb_ctl++;
        end
        if (m_rvalid && m_rready) m_rvalid <= 1'b0;
        if (!m_rvalid || m_rready) begin
            c0 = (rq0.size() > 0) && (rq0[0].t <= cyc);
            c1 = (rq1.size() > 0) && (rq1[0].t <= cyc);
            if ((c0 || c1) && $urandom % 4 != 0) begin
                if (c0 && c1) p1 = ($urandom % 2 == 0);
                else          p1 = c1;
                m_rvalid <= 1'b1;
                m_rid    <= p1;
                m_rresp  <= 2'd0;
                if (p1) begin
                    m_rdata <= ddr_rd(rq1[0].addr + rk1 * 32);
                    m_rlast <= (rk1 == rq1[0].len);
                    if (rk1 == rq1[0].len) begin void'(rq1.pop_front()); rk1 = 0; end else rk1++;
                end else begin
                    m_rdata <= ddr_rd(rq0[0].addr + rk0 * 32);
                    m_rlast <= (rk0 == rq0[0].len);
                    if (rk0 == rq0[0].len) begin void'(rq0.pop_front()); rk0 = 0; end else rk0++;
                end
            end
        end
    end

    // 쓰기 채널. wbk[k] = 트랙 k membrane potential 쓰기 burst의 B 응답 수(RUN 중)
    int          wbk [0:1023];
    logic [31:0] b_addr = '0;
    initial foreach (wbk[i]) wbk[i] = 0;
    always @(posedge clk) begin : wr_ch
        burst_t b;
        logic [31:0] a;
        logic [255:0] wd2;
        if (m_awvalid && m_awready) begin
            chk_burst("write", 1'b1, m_awaddr, m_awlen, 1'b0);
            b.addr = m_awaddr;
            b.len  = m_awlen;
            b.t    = 0;
            awq.push_back(b);
        end
        m_awready <= ($urandom % 2 == 0);
        if (m_wvalid && m_wready) begin
            if (awq.size() == 0)
                prot("주소 전 쓰기 data");
            else begin
                a = awq[0].addr + wk * 32;
                wd2 = m_wdata;
                // DRAM은 X를 담지 못한다(X가 제어 응답 frame에 들어가면 xsim에서 FCS가 깨져 Host가 버린다)
                if ($isunknown(m_wdata)) err($sformatf("X in DDR3 write data at %h", a));
                if (in_state(a))     mstate[(a - SB) >> 5] = wd2;
                else if (in_slot(a)) mslot[slot_i(a)] = wd2;
                if (run) wb_run++; else wb_ctl++;
                if (m_wlast != (wk == awq[0].len)) prot("wlast");
                if (wk == awq[0].len) begin
                    b = awq.pop_front();
                    b.t = cyc + 3 + $urandom % 40;
                    bq.push_back(b);
                    wk = 0;
                end else
                    wk++;
            end
        end
        m_wready <= ($urandom % 4 != 0);
        if (m_bvalid && m_bready) begin
            m_bvalid <= 1'b0;
            if (run && in_state(b_addr)) wbk[(b_addr - SB) >> 11]++;
        end
        if ((!m_bvalid || m_bready) && bq.size() > 0 && bq[0].t <= cyc) begin
            b = bq.pop_front();
            b_addr   <= b.addr;
            m_bvalid <= 1'b1;
            m_bresp  <= 2'd0;
        end
        if (dut.rs_valid && dut.rs_ready && $isunknown(dut.rs_data))
            err($sformatf("result with X bits: %h", dut.rs_data));
        // DDR3 트랙 결과는 그 timestep의 되쓰기 응답 뒤에 나간다(result.v, 03 §3). 같은 block이라 B를 먼저 센다
        if (dut.rs_valid && dut.rs_ready && dut.rs_data[15:0] >= N_ONCHIP && dut.rs_data[15:0] < 1024
            && wbk[dut.rs_data[9:0]] <= dut.rs_data[31:16])
            err($sformatf("track %0d seq %0d: result sent before membrane potential write-back (B %0d)",
                          dut.rs_data[15:0], dut.rs_data[31:16], wbk[dut.rs_data[9:0]]));
    end

    // valid 유지(negedge에 읽는다), RUN이 바뀔 때 DDR3 거래가 남아 있지 않음
    reg         h_ar = 1'b0, h_aw = 1'b0, h_w = 1'b0, run_q = 1'b0;
    reg [40:0]  h_arv, h_awv;
    reg [256:0] h_wv;
    always @(negedge clk) if (!rst) begin
        if (h_ar && !(m_arvalid && {m_arid, m_araddr, m_arlen} == h_arv)) prot("arvalid 유지");
        if (h_aw && !(m_awvalid && {1'b0, m_awaddr, m_awlen} == h_awv)) prot("awvalid 유지");
        if (h_w && !(m_wvalid && {m_wlast, m_wdata} == h_wv)) prot("wvalid 유지");
        h_ar = m_arvalid && !m_arready; h_arv = {m_arid, m_araddr, m_arlen};
        h_aw = m_awvalid && !m_awready; h_awv = {1'b0, m_awaddr, m_awlen};
        h_w  = m_wvalid && !m_wready;   h_wv  = {m_wlast, m_wdata};
        if (run !== run_q && (rq0.size() || rq1.size() || awq.size() || bq.size() || m_rvalid || m_bvalid
                              || m_arvalid || m_awvalid || m_wvalid))
            prot($sformatf("RUN %0b -> %0b with DDR3 transaction pending", run_q, run));
        run_q = run;
    end

    // 연산 cycle(CMP_BUSY 대조). core_rst로 0
    longint busy_cyc = 0, stall_cyc = 0;
    always @(posedge clk) begin
        if (dut.core_rst) busy_cyc <= 0;
        else if (dut.busy) busy_cyc <= busy_cyc + 1;
        // CMP_STALL 대조: accel_core.v의 stall 조건(정의는 06 §7.3 확인 대기). 여기서는 regs까지의 연결을 본다
        if (dut.core_rst || dut.cnt_clear) stall_cyc <= 0;
        else if (dut.go_valid && !dut.busy && !dut.go_ready) stall_cyc <= stall_cyc + 1;
    end

    // PHY reset
    longint phy_up = -1;
    always @(posedge clk)
        if (!rst && phy_reset_n === 1'b1 && phy_up < 0) phy_up <= cyc;

    // ---------------- Host 송신 ----------------
    task automatic hwait(input int n);
        repeat (n) @(posedge hclk);
    endtask

    byte unsigned txq[$];
    // 송신 handshake는 negedge에 내고 1 ns 뒤 ready를 본다(tb_eth와 같다)
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

    // ---------------- 제어 packet ----------------
    logic [31:0] wd[$], rd[$];
    int          n_ctl = 0;
    logic [15:0] ctag = 16'h1000;

    task automatic fatal(input string s);
        err(s);
        $display("FAIL %s: cycle %0d, 오류 %0d", s, cyc, errors);
        $finish;
    endtask

    // op 1 읽기 → rd, op 2 쓰기 ← wd. 응답 머리·길이·status를 확인한다
    task automatic ctl(input [7:0] op, input [31:0] addr, input int cnt, input int exp_st, input string name);
        int t, len, rlen;
        byte unsigned h[12], r[$];
        logic [15:0] c, st;
        c = cnt;
        r.delete();                          // task 안 queue를 호출마다 비우지 않는 simulator(Verilator 5.020)가 있다
        txq.delete();
        txq.push_back(8'h5C); txq.push_back(op); txq.push_back(ctag[7:0]); txq.push_back(ctag[15:8]);
        for (int i = 0; i < 4; i++) txq.push_back(addr[8*i +: 8]);
        txq.push_back(c[7:0]); txq.push_back(c[15:8]); txq.push_back(8'h00); txq.push_back(8'h00);
        if (op == 8'd2)
            for (int i = 0; i < cnt; i++)
                for (int b = 0; b < 4; b++) txq.push_back(wd[i][8*b +: 8]);
        for (int i = 0; i < 12; i++) h[i] = txq[i];
        ctag++;
        udp_send(CPORT, 16'd5001);
        t = 0;
        while (rpl.size() == 0 && t < 2_000_000) begin @(posedge hclk); t++; end
        if (rpl.size() == 0) fatal({name, ": 제어 응답 없음"});
        n_ctl++;
        rd.delete();
        len = rpl.pop_front();
        for (int i = 0; i < len; i++) r.push_back(rpb.pop_front());
        rlen = (op == 8'd1 && exp_st == 0) ? 12 + 4 * cnt : 12;
        for (int i = 0; i < 10; i++)
            if (i < len && r[i] != h[i]) begin err($sformatf("%s: reply header byte %0d = %h, sent %h", name, i, r[i], h[i])); break; end
        if (len != rlen) begin
            err($sformatf("%s: reply length %0d, expected %0d", name, len, rlen));
            return;
        end
        st = {r[11], r[10]};
        if (st != exp_st[15:0]) err($sformatf("%s: status %0d, expected %0d", name, st, exp_st));
        for (int i = 12; i < rlen; i += 4) rd.push_back({r[i+3], r[i+2], r[i+1], r[i]});
    endtask

    task automatic reg_rd(input [31:0] addr, input int cnt, input string name);
        ctl(8'd1, addr, cnt, 0, name);
        if (rd.size() != cnt) fatal({name, ": 읽은 word 수"});
    endtask

    task automatic reg_wr(input [31:0] addr, input [31:0] v, input string name);
        wd.delete();
        wd.push_back(v);
        ctl(8'd2, addr, 1, 0, name);
    endtask

    task automatic expect_word(input int i, input [31:0] e, input string name);
        logic [31:0] g;
        g = rd[i];
        if (g !== e) err($sformatf("%s: %h, expected %h", name, g, e));
    endtask

    task automatic wait_idle(input string name);
        int n;
        n = 0;
        do begin
            reg_rd(32'h0100, 1, "STATUS");
            n++;
        end while (rd[0][1] !== 1'b1 && n < 200);
        if (rd[0][1] !== 1'b1) err({name, ": STATUS.IDLE 0"});
    endtask

    // ---------------- 모델 적재 (DDR3 창, 1 KiB 쓰기) ----------------
    function automatic logic [31:0] img_word(input int m, input int w);  // slot 안 word w
        logic [255:0] b;
        b = img_beat(m, w / 8);
        return b[32 * (w % 8) +: 32];
    endfunction

    int n_ld_eth = 0;
    // slot m에 모델 src의 이미지를 1 KiB 제어 쓰기로 넣는다
    task automatic wr_slot(input int m, input int src);
        int nb;
        for (int i = 0; 32 * i < LD; i++) begin
            nb = (LD - 32 * i < 32) ? LD - 32 * i : 32;
            wd.delete();
            for (int w = 0; w < 8 * nb; w++) wd.push_back(img_word(src, 256 * i + w));
            ctl(8'd2, 32'h8000_0000 + 32'h40000 * m + 1024 * i, 8 * nb, 0, $sformatf("slot %0d write %0d", m, i));
        end
    endtask

    task automatic load_model(input int m);
        int nb, mis;
        wr_slot(m, m);
        mis = 0;
        for (int i = 0; 32 * i < LD; i++) begin
            nb = (LD - 32 * i < 32) ? LD - 32 * i : 32;
            ctl(8'd1, 32'h8000_0000 + 32'h40000 * m + 1024 * i, 8 * nb, 0, $sformatf("model %0d read %0d", m, i));
            for (int w = 0; w < rd.size(); w++) begin
                logic [31:0] g, e;
                g = rd[w];
                e = img_word(m, 256 * i + w);
                if (g !== e) mis++;
            end
        end
        for (int b = 0; b < LD; b++) begin
            logic [255:0] g, e;
            g = mslot[m * LD + b];
            e = img_beat(m, b);
            if (g !== e) mis++;
        end
        if (mis != 0) err($sformatf("model %0d: read back / DDR3 mismatch %0d", m, mis));
        n_ld_eth++;
    endtask

    // ---------------- 추론 요청·결과 ----------------
    task automatic push_req(input int tk, input int t, input int model, input [31:0] th, input [319:0] x);
        logic [511:0] w;
        logic [15:0]  tk16, t16;
        tk16 = tk;
        t16  = t;
        w = '0;
        w[7:0]     = 8'hA5;
        w[8]       = (t == 0);
        w[31:16]   = tk16;
        w[47:32]   = t16;
        w[55:48]   = model;
        w[95:64]   = th;
        w[127:96]  = 32'd2;
        w[447:128] = x;
        for (int k = 0; k < 64; k++) txq.push_back(w[8*k +: 8]);
    endtask

    bit     got [0:1023];
    int     n_res = 0, n_late = 0, n_bn [0:2], err_out = 0, err_fld = 0;

    task automatic chk_res(input logic [255:0] g, input int t, input [31:0] th);
        logic [15:0] tk, seq, bn, o0, o1;
        logic [7:0]  model, fl;
        logic [31:0] t_host, t_in, t_st, t_dn, o_exp, rsv, lim;
        bit          late;
        int          v;
        tk = g[15:0]; seq = g[31:16]; model = g[39:32]; fl = g[47:40]; bn = g[63:48];
        t_host = g[95:64]; t_in = g[127:96]; t_st = g[159:128]; t_dn = g[191:160];
        o0 = g[207:192]; o1 = g[223:208]; rsv = g[255:224];
        n_res++;
        v = (tk < 1024) ? vof[tk] : -1;
        if (v < 0) begin err($sformatf("result for unknown track %0d", tk)); return; end
        if (got[tk]) begin err($sformatf("t%0d: second result for track %0d", t, tk)); return; end
        got[tk] = 1'b1;
        o_exp = oall[v * T + t];
        if ({o1, o0} !== o_exp) begin
            err_out++;
            err($sformatf("t%0d track %0d (v%0d): out %h, golden %h", t, tk, v, {o1, o0}, o_exp));
        end
        lim  = t_host + dl - MARGIN;
        late = $signed(t_dn - lim) > 0;
        if (late) n_late++;
        if (bn >= 1 && bn <= 2) n_bn[bn]++;
        if (seq != t[15:0] || model != mmap[idx[v]] || fl != {5'd0, late, 1'b0, t == 0} || bn < 1 || bn > 2
            || t_host != th || $signed(t_in - t_host) < 0 || $signed(t_st - t_in) < 0 || $signed(t_dn - t_st) < 0
            || rsv != 32'd0) begin
            err_fld++;
            err($sformatf("t%0d track %0d: seq %0d model %0d flags %b batch_n %0d t_host %0d/%0d t_in %0d t_start %0d t_done %0d rsv %h",
                          t, tk, seq, model, fl, bn, t_host, th, t_in, t_st, t_dn, rsv));
        end
    endtask

    task automatic wait_res(input int n, input int t, input [31:0] th, input string name);
        int k, w;
        logic [255:0] g;
        k = 0; w = 0;
        while (k < n) begin
            if (res_q.size() != 0) begin
                g = res_q.pop_front();
                chk_res(g, t, th);
                k++;
                w = 0;
            end else begin
                @(posedge hclk);
                w++;
                if (w > 3_000_000) fatal($sformatf("%s: 결과 %0d/%0d개만 옴", name, k, n));
            end
        end
    endtask

    // timestep 하나: NOW_US를 t_host로, 80개를 섞어 datagram(최대 23개)으로 보내고 결과 80개를 받아 확인
    int nreq = 0;
    task automatic do_t(input int t);
        logic [31:0] th;
        int order[$];
        reg_rd(32'h0200, 1, "NOW_US");
        th = rd[0];
        for (int i = 0; i < 1024; i++) got[i] = 1'b0;
        order.delete();                      // task 안 queue를 호출마다 비우지 않는 simulator가 있다(ctl과 같다)
        for (int v = 0; v < N_VEC; v++) order.push_back(v);
        order.shuffle();
        for (int i = 0; i < N_VEC; i += 23) begin
            txq.delete();
            for (int j = i; j < i + 23 && j < N_VEC; j++) begin
                push_req(trk(order[j]), t, mmap[idx[order[j]]], th, xall[order[j] * T + t]);
                nreq++;
            end
            udp_send(RPORT, 16'd5000);
        end
        wait_res(N_VEC, t, th, $sformatf("t%0d", t));
    endtask

    // ---------------- PNU 표 ----------------
    // pat = 1: 주소마다 다른 값(위 16 bit는 버려져야 한다), 0: 시나리오 값(OFFSET m, N_REG 2, 나머지 0)
    function automatic logic [15:0] pnu_v(input bit pat, input int tbl, input int i);
        case (tbl)
        0: return pat ? 16'(39 - i) : 16'(i);                 // OFFSET_TABLE
        1: return pat ? 16'(12'h400 + 13 * i) : 16'd2;        // N_REG
        2: return pat ? 16'(16'h1234 + 16'h4444 * i) : 16'd0; // TAU_G, TAU_U, EG
        3: return pat ? 16'(i * 515 + 7) : 16'd0;              // LUT_G
        default: return pat ? 16'(i * 40503 + 1) : 16'd0;    // LUT_U
        endcase
    endfunction

    task automatic pnu_write(input bit pat);
        wd.delete();
        for (int m = 0; m < N_MOD; m++) wd.push_back({16'hA5A5, pnu_v(pat, 0, m)});
        ctl(8'd2, 32'h1000, N_MOD, 0, "OFFSET_TABLE");
        wd.delete();
        for (int m = 0; m < N_MOD; m++) wd.push_back({16'h5A5A, pnu_v(pat, 1, m)});
        ctl(8'd2, 32'h1100, N_MOD, 0, "N_REG");
        wd.delete();
        for (int i = 0; i < 3; i++) wd.push_back({16'hFFFF, pnu_v(pat, 2, i)});
        ctl(8'd2, 32'h1200, 3, 0, "TAU_G, TAU_U, EG");
        wd.delete();
        for (int i = 0; i < 128; i++) wd.push_back({16'h0F0F, pnu_v(pat, 3, i)});
        ctl(8'd2, 32'h1400, 128, 0, "LUT_G");
        for (int k = 0; k < 4; k++) begin
            wd.delete();
            for (int i = 0; i < 256; i++) wd.push_back({16'hF0F0, pnu_v(pat, 4, 256 * k + i)});
            ctl(8'd2, 32'h2000 + 1024 * k, 256, 0, "LUT_U");
        end
    endtask

    // 표는 쓰기 전용(읽으면 0)이라 next_use_predictor 안의 값을 계층 이름으로 본다
    task automatic pnu_check(input bit pat, input string name);
        int mis;
        mis = 0;
        for (int m = 0; m < N_MOD; m++) begin
            if (dut.u_core.u_wc.u_pred.off_us[m] !== 15'(pnu_v(pat, 0, m) * 800)) mis++;
            if (dut.u_core.u_wc.u_pred.n_reg[m]  !== pnu_v(pat, 1, m)) mis++;
        end
        if (dut.u_core.u_wc.u_pred.tau_g !== pnu_v(pat, 2, 0)) mis++;
        if (dut.u_core.u_wc.u_pred.tau_u !== pnu_v(pat, 2, 1)) mis++;
        if (dut.u_core.u_wc.u_pred.eg    !== pnu_v(pat, 2, 2)) mis++;
        for (int i = 0; i < 128; i++)  if (dut.u_core.u_wc.u_pred.lut_g[i] !== pnu_v(pat, 3, i)) mis++;
        for (int i = 0; i < 1024; i++) if (dut.u_core.u_wc.u_pred.lut_u[i] !== pnu_v(pat, 4, i)) mis++;
        for (int i = 0; i < 8; i++)    if (dut.u_core.u_wc.u_pred.lut_u0[i] !== pnu_v(pat, 4, i)) mis++;
        if (mis != 0) err($sformatf("%s: predictor table mismatch %0d", name, mis));
    endtask

    // ---------------- 순서 ----------------
    longint c0, c1, c_inf, c_ld;
    int     n_ddr, e0, mis;
    real    tw0;

    initial begin : main
        if ($value$plusargs("FULL=%d", full)) ;
        if ($value$plusargs("NT=%d", nt)) ;
        if ($value$plusargs("MAXERR=%d", maxerr)) ;
        if (nt < 1 || nt > T) nt = T;
        foreach (mmap[m]) mmap[m] = m;
        if (full) wd_lim = 80_000_000;

        // golden
        for (int i = 0; i < 65536; i++) mstate[i] = {8{32'hA5A5_5A5A}};
        for (int i = 0; i < 1024; i++) vof[i] = -1;
        $readmemh({VEC, "index.hex"}, idx);
        for (int v = 0; v < N_VEC; v++) begin
            $readmemh($sformatf("%sv%02d_x.hex", VEC, v), xall, v * T, v * T + T - 1);
            $readmemh($sformatf("%sv%02d_e.hex", VEC, v), eall, v * T * ROWS, (v + 1) * T * ROWS - 1);
            $readmemh($sformatf("%sv%02d_o.hex", VEC, v), oall, v * T, v * T + T - 1);
            vof[trk(v)] = v;
            if (idx[v] != v / 2) err($sformatf("index.hex v%0d model %0d", v, idx[v]));
        end
        n_ddr = 0;
        for (int v = 0; v < N_VEC; v++) if (trk(v) >= N_ONCHIP) n_ddr++;
        for (int m = 0; m < N_MOD; m++) begin
            $readmemh($sformatf("%sm%02d_w.hex", VEC, m), wall, m * 2034, m * 2034 + 2033);
            $readmemh($sformatf("%sm%02d_p.hex", VEC, m), pall, m * 46, m * 46 + 45);
        end
        // slot 0·1(FULL이면 모두)은 Ethernet으로 적재하므로 쓰레기로 둔다. 나머지는 backdoor로 넣는다
        for (int m = 0; m < N_MOD; m++)
            for (int b = 0; b < LD; b++)
                mslot[m * LD + b] = (full || m < 2) ? {8{32'hDEAD_BEEF ^ b}} : img_beat(m, b);

        repeat (20) @(negedge clk);
        rst  = 1'b0;
        hrst = 1'b0;
        hwait(300);

        // 1. MIG 보정 전
        e0 = errors;
        reg_rd(32'h0000, 4, "info");
        expect_word(0, 32'h534E_4E58, "ID");
        expect_word(1, 32'h0001_0000, "VERSION");
        expect_word(2, E, "N_ENTRY");
        expect_word(3, N_ONCHIP, "N_ONCHIP");
        reg_rd(32'h0100, 1, "STATUS before calib");
        expect_word(0, 32'h2, "STATUS before calib");        // IDLE만
        ctl(8'd1, 32'h8000_0000, 8, 2, "DDR3 read before calib");
        wd.delete();
        for (int i = 0; i < 8; i++) wd.push_back(32'h1234_0000 + i);
        ctl(8'd2, 32'h8000_0000, 8, 2, "DDR3 write before calib");
        if (rb_ctl != 0 || wb_ctl != 0 || n_ar_run != 0) err("DDR3 accessed before calib");
        hwait(500);
        mig_calib = 1'b1;
        reg_rd(32'h0100, 1, "STATUS after calib");
        expect_word(0, 32'h6, "STATUS after calib");
        $display("run   1) MIG 보정 전: 정보·STATUS 읽기, DDR3 창 status 2, 오류 %0d, cycle %0d", errors - e0, cyc);

        // 2. 모델 적재
        e0 = errors;
        c0 = cyc;
        for (int m = 0; m < (full ? N_MOD : 2); m++) load_model(m);
        c_ld = cyc - c0;
        $display("run   2) 모델 %0d개 Ethernet 적재·확인(나머지 %0d개 backdoor), 제어 packet %0d, DDR3 beat 쓰기 %0d·읽기 %0d, 오류 %0d, %0d cycle",
                 n_ld_eth, N_MOD - n_ld_eth, n_ctl, wb_ctl, rb_ctl, errors - e0, c_ld);

        // 3. 설정, PNU 표, SOFT_RESET, RUN
        e0 = errors;
        wd = '{32'd1000, 32'd39, 32'h0000_0100, 32'h0300_0000, 32'd12345, 32'd7};
        ctl(8'd2, 32'h0300, 6, 0, "settings test write");
        reg_rd(32'h0300, 6, "settings test read");
        for (int i = 0; i < 6; i++) expect_word(i, wd[i], $sformatf("setting %0d test value", i));
        wd = '{32'd1024, N_MOD, 32'h0000_0000, SB, DEADLINE, MARGIN};
        ctl(8'd2, 32'h0300, 6, 0, "settings write");
        reg_rd(32'h0300, 6, "settings read");
        for (int i = 0; i < 6; i++) expect_word(i, wd[i], $sformatf("setting %0d", i));
        reg_rd(32'h0318, 1, "LINK_TUNE");
        expect_word(0, 32'h0, "LINK_TUNE default");         // GENERIC, RX_IDELAY 0, TX_PS 0
        reg_wr(32'h0318, 32'hFFF0_0003, "LINK_TUNE write");
        reg_rd(32'h0318, 1, "LINK_TUNE read");
        expect_word(0, 32'hFFF0_0003, "LINK_TUNE");
        if (tx_ps !== 16'hFFF0) err($sformatf("tx_ps %h", tx_ps));
        reg_wr(32'h0318, 32'h0, "LINK_TUNE restore");
        pnu_write(1'b1);
        pnu_check(1'b1, "PNU table pattern");
        pnu_write(1'b0);
        pnu_check(1'b0, "PNU table");
        reg_rd(32'h1000, 2, "PNU table read");
        expect_word(0, 0, "PNU table read 0");
        expect_word(1, 0, "PNU table read 1");
        reg_wr(32'h0104, 32'h2, "SOFT_RESET");
        reg_rd(32'h0100, 1, "STATUS after SOFT_RESET");
        expect_word(0, 32'h6, "STATUS after SOFT_RESET");    // IDLE, MIG_CALIB
        reg_wr(32'h0104, 32'h1, "RUN");
        reg_rd(32'h0100, 1, "STATUS RUN");
        expect_word(0, 32'h7, "STATUS RUN");
        reg_wr(32'h0300, 32'd512, "N_TRACKS write while RUN");
        reg_wr(32'h0310, 32'd1, "DEADLINE_US write while RUN");
        reg_rd(32'h0300, 6, "settings read while RUN");
        expect_word(0, 32'd1024, "N_TRACKS after write while RUN");
        expect_word(4, DEADLINE, "DEADLINE_US after write while RUN");
        wd.delete();
        for (int i = 0; i < 8; i++) wd.push_back(32'h5555_0000 + i);
        ctl(8'd2, 32'h8000_0000, 8, 2, "DDR3 write while RUN");
        ctl(8'd1, 32'h8000_0000, 8, 2, "DDR3 read while RUN");
        reg_wr(32'h1000, 32'd7, "OFFSET_TABLE write while RUN");
        pnu_check(1'b0, "PNU table after write while RUN");
        reg_rd(32'h0400, 3, "counters after SOFT_RESET");
        for (int i = 0; i < 3; i++) expect_word(i, 0, "counter after SOFT_RESET");
        $display("run   3) 설정·PNU 표 쓰기와 읽기, SOFT_RESET, RUN = 1, RUN 중 설정·DDR3 쓰기 무시, 오류 %0d", errors - e0);

        // 4. 추론
        e0 = errors;
        c0 = cyc;
        nreq = 0;
        n_bn[0] = 0; n_bn[1] = 0; n_bn[2] = 0;
        for (int t = 0; t < nt; t++) begin
            do_t(t);
            if (t == 0 || t == nt - 1)
                $display("run      t%0d: 결과 %0d, 누적 오류 %0d, cycle %0d", t, n_res, errors - e0, cyc);
        end
        c_inf = cyc - c0;
        $display("run   4) 추론 요청 %0d, 결과 %0d (DDR3 트랙 %0d), out 불일치 %0d, 필드 불일치 %0d, batch_n 1: %0d·2: %0d, LATE %0d, 오류 %0d, %0d cycle",
                 nreq, n_res, n_ddr, err_out, err_fld, n_bn[1], n_bn[2], n_late, errors - e0, c_inf);

        // 5. 끝: IDLE, RUN = 0, counter, DDR3 membrane potential
        e0 = errors;
        wait_idle("after last result");
        reg_wr(32'h0104, 32'h0, "RUN = 0");
        reg_rd(32'h0100, 1, "STATUS stop");
        expect_word(0, 32'h6, "STATUS stop");
        reg_rd(32'h0400, 16, "counters");
        begin
            logic [31:0] c[16];
            longint wb, sb, bz, stl;
            for (int i = 0; i < 16; i++) c[i] = rd[i];
            wb = {c[9], c[8]}; sb = {c[11], c[10]}; bz = {c[13], c[12]}; stl = {c[15], c[14]};
            if (c[0] != nreq) err($sformatf("REQ_IN %0d, expected %0d", c[0], nreq));
            if (c[1] != 0) err($sformatf("REQ_DROP %0d", c[1]));
            if (c[2] != nreq) err($sformatf("RES_OUT %0d, expected %0d", c[2], nreq));
            if (c[3] != n_late) err($sformatf("LATE %0d, expected %0d", c[3], n_late));
            if (c[4] < 1 || c[4] > N_VEC) err($sformatf("MAX_PENDING %0d", c[4]));
            if (c[5] < N_MOD * nt || c[5] > N_VEC * nt) err($sformatf("BATCHES %0d", c[5]));
            if (c[5] != n_bn[2] / 2 + n_bn[1]) err($sformatf("BATCHES %0d, results say %0d", c[5], n_bn[2] / 2 + n_bn[1]));
            if (wb != longint'(c[6]) * 131648) err($sformatf("WEIGHT_BYTES %0d, MODEL_LOADS %0d", wb, c[6]));
            if (rb0_run != longint'(c[6]) * LD) err($sformatf("weight beats %0d, MODEL_LOADS %0d × %0d", rb0_run, c[6], LD));
            if (c[7] != 0) err($sformatf("SAT_COUNT %0d", c[7]));
            if (sb != longint'(n_ddr * (nt - 1) + n_ddr * nt) * 1088) err($sformatf("STATE_BYTES %0d", sb));
            if (rb1_run != n_ddr * (nt - 1) * 34 || wb_run != n_ddr * nt * 34)
                err($sformatf("membrane potential beats read %0d write %0d", rb1_run, wb_run));
            begin
                int s;
                s = 0;
                foreach (wbk[i]) s += wbk[i];
                if (s != n_ddr * nt) err($sformatf("membrane potential write B responses %0d, expected %0d", s, n_ddr * nt));
            end
            if (bz == 0 || bz != busy_cyc) err($sformatf("CMP_BUSY %0d, testbench %0d", bz, busy_cyc));
            if (stl == 0 || stl != stall_cyc) err($sformatf("CMP_STALL %0d, testbench %0d", stl, stall_cyc));
            $display("run   counter: REQ_IN %0d, REQ_DROP %0d, RES_OUT %0d, LATE %0d, MAX_PENDING %0d, BATCHES %0d, MODEL_LOADS %0d, SAT_COUNT %0d",
                     c[0], c[1], c[2], c[3], c[4], c[5], c[6], c[7]);
            $display("run   counter: WEIGHT_BYTES %0d, STATE_BYTES %0d, CMP_BUSY %0d, CMP_STALL %0d; DDR3 beat weight %0d, membrane potential 읽기 %0d·쓰기 %0d",
                     wb, sb, bz, stl, rb0_run, rb1_run, wb_run);
        end
        reg_rd(32'h0500, 2, "ERR after run");
        expect_word(0, 0, "ERR_CODE after run");
        mis = 0;
        for (int v = 0; v < N_VEC; v++)
            if (trk(v) >= N_ONCHIP) begin
                logic [34*256-1:0] img;
                logic [31:0] a;
                a = 32'h8000_0000 + SB + 32'h800 * trk(v);
                ctl(8'd1, a, 256, 0, "state read 0");
                for (int i = 0; i < 256; i++) img[32*i +: 32] = rd[i];
                ctl(8'd1, a + 1024, 16, 0, "state read 1");
                for (int i = 0; i < 16; i++) img[32*(256 + i) +: 32] = rd[i];
                for (int r = 0; r < ROWS; r++)
                    for (int j = 0; j < ((r == 44) ? 2 : 16); j++) begin
                        logic [911:0] e;
                        logic [11:0] gv, ev;
                        e  = eall[(v * T + nt - 1) * ROWS + r];
                        gv = img[12 * (16 * r + j) +: 12];
                        ev = e[640 + 16*j +: 12];
                        if (gv !== ev) mis++;
                    end
            end
        if (mis != 0) err($sformatf("DDR3 membrane potential mismatch %0d", mis));
        $display("run   5) IDLE 뒤 RUN = 0, counter, DDR3 트랙 %0d개 membrane potential DDR3 창 읽기 불일치 %0d, 오류 %0d",
                 n_ddr, mis, errors - e0);

        // 5b. 활동 뒤 SOFT_RESET (06 §6 5: entry 무효화, request table·counter·시각 초기화).
        //     cache에 있는 두 모델 A·B의 slot을 Ethernet으로 맞바꿔 쓰고(A ← B 이미지, B ← A 이미지) SOFT_RESET한다.
        //     A의 vector는 model_id B로, B의 vector는 A로 보낸다. entry가 남아 있으면 옛 weight로 계산해 golden과 어긋난다.
        //     DEADLINE_US = 1로 두어 모든 결과가 LATE여야 한다(LATE counter·flag, SAT_COUNT 0)
        e0 = errors;
        begin
            int ma, mb, ne;
            logic [31:0] c[16];
            longint wb, sb, bz, stl;
            ma = -1; mb = -1; ne = 0;
            for (int i = 0; i < E; i++)
                if (dut.u_core.u_wc.occ[i]) begin
                    ne++;
                    if (ma < 0) ma = dut.u_core.u_wc.tag[i];
                    else if (mb < 0) mb = dut.u_core.u_wc.tag[i];
                end
            if (ma < 0 || mb < 0) fatal($sformatf("5b: cache holds %0d entries, need 2", ne));
            wr_slot(ma, mb);
            wr_slot(mb, ma);
            mis = 0;
            for (int b = 0; b < LD; b++) begin
                if (mslot[ma * LD + b] !== img_beat(mb, b)) mis++;
                if (mslot[mb * LD + b] !== img_beat(ma, b)) mis++;
            end
            if (mis != 0) err($sformatf("5b: slot swap DDR3 mismatch %0d", mis));
            if (dut.u_core.u_wc.occ == '0) err("5b: cache empty before SOFT_RESET");
            reg_wr(32'h0104, 32'h2, "SOFT_RESET after run");
            if (dut.u_core.u_wc.occ !== '0) err($sformatf("5b: cache entries %b valid after SOFT_RESET", dut.u_core.u_wc.occ));
            if (dut.pending_n !== '0) err($sformatf("5b: pending %0d after SOFT_RESET", dut.pending_n));
            reg_rd(32'h0200, 1, "NOW_US after SOFT_RESET");
            if (rd[0] > 1000) err($sformatf("5b: NOW_US %0d after SOFT_RESET", rd[0]));
            reg_rd(32'h0400, 16, "counters after SOFT_RESET 2");
            for (int i = 0; i < 16; i++) expect_word(i, 0, $sformatf("counter %0d after SOFT_RESET 2", i));
            reg_wr(32'h0310, 32'd1, "DEADLINE_US 1");
            dl = 32'd1;
            mmap[ma] = mb;
            mmap[mb] = ma;
            n_late = 0; n_bn[1] = 0; n_bn[2] = 0; err_out = 0; err_fld = 0;
            nreq = 0;
            reg_wr(32'h0104, 32'h1, "RUN 5b");
            do_t(0);
            wait_idle("5b");
            reg_wr(32'h0104, 32'h0, "RUN = 0 5b");
            reg_rd(32'h0400, 16, "counters 5b");
            for (int i = 0; i < 16; i++) c[i] = rd[i];
            wb = {c[9], c[8]}; sb = {c[11], c[10]}; bz = {c[13], c[12]}; stl = {c[15], c[14]};
            if (c[0] != N_VEC || c[1] != 0 || c[2] != N_VEC) err($sformatf("5b: REQ_IN %0d REQ_DROP %0d RES_OUT %0d", c[0], c[1], c[2]));
            if (n_late != N_VEC || c[3] != N_VEC) err($sformatf("5b: LATE flags %0d, counter %0d, expected %0d", n_late, c[3], N_VEC));
            if (c[5] < N_MOD || c[5] != n_bn[2] / 2 + n_bn[1]) err($sformatf("5b: BATCHES %0d", c[5]));
            if (c[6] < N_MOD || wb != longint'(c[6]) * 131648) err($sformatf("5b: MODEL_LOADS %0d WEIGHT_BYTES %0d", c[6], wb));
            if (c[7] != 0) err($sformatf("5b: SAT_COUNT %0d", c[7]));
            if (sb != longint'(n_ddr) * 1088) err($sformatf("5b: STATE_BYTES %0d", sb));
            if (bz == 0 || bz != busy_cyc) err($sformatf("5b: CMP_BUSY %0d, testbench %0d", bz, busy_cyc));
            if (stl == 0 || stl != stall_cyc) err($sformatf("5b: CMP_STALL %0d, testbench %0d", stl, stall_cyc));
            reg_wr(32'h0310, DEADLINE, "DEADLINE_US restore");
            dl = DEADLINE;
            $display("run   5b) SOFT_RESET 뒤(모델 %0d·%0d slot 맞바꿈, DEADLINE 1 µs): 결과 %0d, out 불일치 %0d, LATE %0d, MODEL_LOADS %0d, BATCHES %0d, CMP_STALL %0d, 오류 %0d",
                     ma, mb, n_bn[1] + n_bn[2], err_out, n_late, c[6], c[5], stl, errors - e0);
        end

        // 6. 오류
        e0 = errors;
        reg_wr(32'h0104, 32'h1, "RUN again");
        txq.delete();
        push_req(5, 1, 45, 32'd0, '0);
        udp_send(RPORT, 16'd5000);
        hwait(2000);
        reg_rd(32'h0500, 2, "ERR model 45");
        expect_word(0, 3, "ERR_CODE model 45");
        expect_word(1, 5, "ERR_INFO model 45");
        reg_rd(32'h0100, 1, "STATUS ERR");
        expect_word(0, 32'hF, "STATUS ERR");
        txq.delete();
        for (int i = 0; i < 100; i++) txq.push_back(i);
        udp_send(RPORT, 16'd5000);
        hwait(2000);
        reg_rd(32'h0500, 2, "ERR after 100 B");
        expect_word(0, 3, "ERR_CODE kept");
        expect_word(1, 5, "ERR_INFO kept");
        reg_wr(32'h0104, 32'h9, "ERR_CLEAR");
        reg_rd(32'h0500, 2, "ERR cleared");
        expect_word(0, 0, "ERR_CODE cleared");
        expect_word(1, 0, "ERR_INFO cleared");
        reg_rd(32'h0100, 1, "STATUS cleared");
        expect_word(0, 32'h7, "STATUS cleared");
        txq.delete();
        for (int i = 0; i < 100; i++) txq.push_back(i);
        udp_send(RPORT, 16'd5000);
        hwait(2000);
        reg_rd(32'h0500, 2, "ERR 100 B");
        expect_word(0, 7, "ERR_CODE 100 B");
        expect_word(1, 100, "ERR_INFO 100 B");
        reg_rd(32'h0404, 1, "REQ_DROP");
        expect_word(0, 1, "REQ_DROP after model 45");
        reg_wr(32'h0104, 32'h0, "RUN = 0 end");
        if (res_q.size() != 0) err($sformatf("%0d unexpected results", res_q.size()));
        $display("run   6) 오류: model 45 → 3·트랙 5, 100 B datagram은 첫 오류 유지, ERR_CLEAR, 100 B → 7·100, 오류 %0d", errors - e0);

        if (phy_up < 0 || phy_up > PHY_RST + 30) err($sformatf("phy_reset_n rose at cycle %0d", phy_up));
        if (hq_sip.size() != 0 || cur.size() != 0 || rpl.size() != 0) err("datagram left in host");
        $display("run   끝: cycle %0d (적재 %0d, 추론 %0d), 제어 packet %0d, AXI 위반 %0d, 오류 %0d, FULL %0d, NT %0d",
                 cyc, c_ld, c_inf, n_ctl, n_prot, errors, full, nt);
        if (errors == 0) $display("PASS");
        else $display("FAIL 오류 %0d개", errors);
        $finish;
    end

endmodule
