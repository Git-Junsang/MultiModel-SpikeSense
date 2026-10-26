// next_use_predictor.v — PNU-Count: 모델마다 다음 사용까지 남은 시간 예측 (04_MEMORY.md §3.1)
//
// 모델 m의 nominal offset off = OFFSET_NUM[m] × 800 µs. 시각은 µs 정수.
//   kn, el = 지금 주기와 그 주기 nominal offset 뒤 경과 (el = phase − off, 음수면 + 32,000, kn = period − 1)
//   est    = 가장 최근 주기의 예상 추론 요청 수(packet n_expect). 아직 없으면 N_REG[m]
//   r      = est − (이번 주기 kn의 도착 수)
//   Δ_nxt  = (32,000 − el) + EG + LUT_U[0][rb(max(1, est))]
//   Δ      = 0                      queue에 추론 요청이 있음
//            ∞                      N_REG[m] = 0
//            Δ_nxt                  첫 주기 시작 전(kn < 0)
//            LUT_G[el / 256]        이번 주기 첫 추론 요청 전, r > 0, el < TAU_G
//            LUT_U[x / 256][rb(r)]  첫 추론 요청 뒤(x = 지금 − 첫 도착), r > 0, x < TAU_U
//            Δ_nxt                  그 밖
// rb: 남은 수 칸 1, 2, 3–4, 5–8, 9–16, 17 이상 → 0–5. 표 값은 칸 가운데의 기대값(engine.rtl_tables).
// 모델마다 가장 최근 주기 하나의 (주기 번호, 예상 수, 도착 수, 첫 도착 시각)만 둔다.
// 도착한 추론 요청의 주기: t_host − (지금 주기 nominal 시작)이 −16,000 µs보다 작으면 앞 주기.
// engine.PNURTL과 같은 식이다.
//
// 설정 주소(cfg_addr): 0x000+m OFFSET_NUM, 0x040+m N_REG, 0x080 TAU_G, 0x081 TAU_U, 0x082 EG,
//                      0x100+i LUT_G[i] (i < 128), 0x400 + {i, rb} LUT_U (i < 128, rb < 8)
// 질의: qy_valid(qy_model) 뒤 4 cycle에 qy_done, qy_delta(µs, 32'hFFFF_FFFF = 없음). 도착은 3 cycle 뒤에 기록된다.

module next_use_predictor #(
    parameter N_MODELS = 40
)(
    input  wire                clk,
    input  wire                rst,
    // 시각
    input  wire [31:0]         now_us,
    input  wire [14:0]         phase_us,      // 0 ~ 31,999
    input  wire [15:0]         period,
    input  wire                first_period,   // 시작 뒤 첫 주기(core_rst 뒤 첫 phase 넘김 전)
    // 설정
    input  wire                cfg_we,
    input  wire [10:0]         cfg_addr,
    input  wire [15:0]         cfg_data,
    // 도착
    input  wire                arr_valid,
    input  wire [5:0]          arr_model,
    input  wire [31:0]         arr_t_host,
    input  wire [10:0]         arr_n_expect,
    // Queue
    input  wire [N_MODELS-1:0] q_ne,
    // 질의
    input  wire                qy_valid,
    input  wire [5:0]          qy_model,
    output reg                 qy_done,
    output reg  [31:0]         qy_delta
);

    localparam [15:0] PER = 16'd32000;

    // ---------------- 설정 ----------------
    reg [14:0] off_us [0:63];
    reg [10:0] n_reg  [0:63];
    reg [15:0] tau_g, tau_u, eg;
    reg [15:0] lut_u0 [0:7];
    (* ram_style = "distributed" *) reg [15:0] lut_g [0:127];
    reg [15:0] lut_u [0:1023];

    always @(posedge clk) begin
        if (cfg_we) begin
            case (cfg_addr[10:6])
            5'h00: off_us[cfg_addr[5:0]] <= cfg_data[5:0] * 15'd800;
            5'h01: n_reg[cfg_addr[5:0]]  <= cfg_data[10:0];
            default: ;
            endcase
            if (cfg_addr == 11'h080) tau_g <= cfg_data;
            if (cfg_addr == 11'h081) tau_u <= cfg_data;
            if (cfg_addr == 11'h082) eg    <= cfg_data;
            if (cfg_addr[10:7] == 4'h2) lut_g[cfg_addr[6:0]] <= cfg_data;
            if (cfg_addr[10]) begin
                lut_u[cfg_addr[9:0]] <= cfg_data;
                if (cfg_addr[9:3] == 7'd0) lut_u0[cfg_addr[2:0]] <= cfg_data;
            end
        end
    end

    // ---------------- 모델별 상태 ----------------
    reg  [63:0] tv;                                       // 주기 기록이 있음
    reg  [15:0] tag  [0:63];
    reg  [10:0] n_e  [0:63];
    reg  [10:0] n_r  [0:63];
    reg  [31:0] a1   [0:63];

    // 주기 안 위치: {pl, el}. pl = phase < off(이번 주기 offset 전이라 kn = period − 1)
    function automatic [31:0] where(input [14:0] ph, input [14:0] off);
        reg pl;
        reg [15:0] el;
        begin
            pl = (ph < off);
            el = {1'b0, ph} - {1'b0, off} + (pl ? PER : 16'd0);
            where = {15'd0, pl, el};
        end
    endfunction

    // 도착: 3단. A 주기 위치, B 추론 요청 주기, C 모델 기록. 한 cycle에 두면 100 MHz에서 11.3 ns였다(P4.3 첫 배선)
    wire [31:0] wa    = where(phase_us, off_us[arr_model]);
    reg         a_v1, a_v2;
    reg  [5:0]  a_m1, a_m2;
    reg  [10:0] a_n1, a_n2;
    reg  [31:0] a_now1, a_now2, a_d1;
    reg  [15:0] a_el1, a_kn1, a_k2;
    wire signed [32:0] b_x = $signed({17'd0, a_el1}) - $signed({a_d1[31], a_d1});   // t_host − 이번 주기 nominal 시작
    wire [15:0] c_dk  = a_k2 - tag[a_m2];
    wire        c_new = !tv[a_m2] || (!c_dk[15] && c_dk != 16'd0);

    always @(posedge clk) begin
        a_v1   <= !rst && arr_valid;
        a_m1   <= arr_model;
        a_n1   <= arr_n_expect;
        a_now1 <= now_us;
        a_el1  <= wa[15:0];
        a_kn1  <= period - {15'd0, wa[16]};
        a_d1   <= now_us - arr_t_host;                    // 도착 − t_host (clock 차이로 음수일 수 있다)
        a_v2   <= !rst && a_v1;
        a_m2   <= a_m1;
        a_n2   <= a_n1;
        a_now2 <= a_now1;
        a_k2   <= (b_x >= -33'sd16000) ? a_kn1 : a_kn1 - 16'd1;
        if (rst)
            tv <= 64'd0;
        else if (a_v2) begin
            if (c_new) begin
                tv[a_m2]  <= 1'b1;
                tag[a_m2] <= a_k2;
                n_e[a_m2] <= a_n2;
                n_r[a_m2] <= 11'd1;
                a1[a_m2]  <= a_now2;
            end else if (a_k2 == tag[a_m2])
                n_r[a_m2] <= n_r[a_m2] + 11'd1;
        end
    end

    // ---------------- 질의 ----------------
    function automatic [2:0] rb(input [10:0] r);
        rb = (r >= 11'd17) ? 3'd5 : (r >= 11'd9) ? 3'd4 : (r >= 11'd5) ? 3'd3 :
             (r >= 11'd3)  ? 3'd2 : (r >= 11'd2) ? 3'd1 : 3'd0;
    endfunction

    // 0 대기, 1 상태 읽기, 2 판정·표 읽기, 3 결과
    reg  [1:0]  qs;
    reg  [5:0]  qm;
    wire [31:0] wq = where(phase_us, off_us[qm]);
    reg         r_zero, r_inf, r_pl, r_tv;
    reg  [15:0] r_el, r_kn, r_tag;
    reg  [10:0] r_ne, r_nr, r_reg;
    reg  [31:0] r_x;

    wire [10:0] q_est  = r_tv ? r_ne : r_reg;
    wire        q_seen = r_tv && r_tag == r_kn;
    wire signed [11:0] q_r = $signed({1'b0, q_est}) - $signed({1'b0, q_seen ? r_nr : 11'd0});
    wire [6:0]  q_xb   = (r_x[31:15] != 17'd0) ? 7'd127 : r_x[14:8];

    reg         s_zero, s_inf, s_before, s_g, s_u;
    reg  [16:0] s_nxt;
    reg  [15:0] s_lg, s_lu;

    always @(posedge clk) begin
        qy_done <= 1'b0;
        if (rst)
            qs <= 2'd0;
        else case (qs)
        2'd0: if (qy_valid) begin qm <= qy_model; qs <= 2'd1; end
        2'd1: begin
            r_zero <= q_ne[qm];
            r_inf  <= (n_reg[qm] == 11'd0);
            r_pl   <= wq[16];
            r_el   <= wq[15:0];
            r_kn   <= period - {15'd0, wq[16]};
            r_tv   <= tv[qm];
            r_tag  <= tag[qm];
            r_ne   <= n_e[qm];
            r_nr   <= n_r[qm];
            r_reg  <= n_reg[qm];
            r_x    <= now_us - a1[qm];
            qs     <= 2'd2;
        end
        2'd2: begin
            s_zero   <= r_zero;
            s_inf    <= r_inf;
            s_before <= first_period && r_pl;
            s_g      <= !q_seen && q_r > 0 && r_el < tau_g;
            s_u      <= q_seen && q_r > 0 && r_x < {16'd0, tau_u};
            s_nxt    <= {1'b0, PER - r_el} + {1'b0, eg} + {1'b0, lut_u0[rb((q_est == 11'd0) ? 11'd1 : q_est)]};
            s_lg     <= lut_g[r_el[14:8]];
            s_lu     <= lut_u[{q_xb, rb(q_r[10:0])}];
            qs       <= 2'd3;
        end
        default: begin
            qy_delta <= s_zero ? 32'd0 : s_inf ? 32'hFFFF_FFFF :
                        (s_before || !(s_g || s_u)) ? {15'd0, s_nxt} : {16'd0, s_g ? s_lg : s_lu};
            qy_done  <= 1'b1;
            qs       <= 2'd0;
        end
        endcase
    end

endmodule
