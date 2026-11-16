"""RTL 블록도 3: accel_core.v — weight_cache(weight_entry ×4, next_use_predictor), compute_array, membrane_storage
(membrane_bank, membrane_buf), dma와 추론 시작 조건. 주요 port만, clock·reset은 뺀다.
stall_cyc·ev_state_xfer·dma_idle(regs)와 시작 조건의 입력(ld_busy·ld_entry, can_start, busy)은 선이 겹쳐 상자 글로 적었다.

근거: hardware/src/accel_core.v, weight_cache.v, weight_entry.v, next_use_predictor.v, compute_array.v,
      membrane_storage.v, membrane_bank.v, membrane_buf.v, dma.v (03_ARCHITECTURE.md §2, 04_MEMORY.md §3·§5)
실행: python3 analysis/develop/rtl/fig3_x-accel-core_y-rtl-block.py
출력: analysis/figure/rtl/fig3_x-accel-core_y-rtl-block.{png,pdf}
"""
from blockdraw import FILL_MEM, MUTED, Sheet

S = Sheet(15.4, 10.4)

S.module(2.5, 0.75, 14.9, 9.4, "accel_core.v", "u_core", at="tr", size=14)
CA = (5.0, 2.7, 8.2, 5.0)
WC = (9.8, 1.35, 14.4, 5.0)
MS = (5.0, 6.2, 8.6, 8.95)
DM = (10.2, 6.2, 14.4, 8.95)
S.module(*CA, "compute_array.v", "u_ca", at="bc", size=10, lw=1.3)
S.module(*WC, "weight_cache.v", "u_wc", at="bc", size=10, lw=1.3)
S.module(*MS, "membrane_storage.v", "u_ms", at="bc", size=10, lw=1.3)
S.module(*DM, "dma.v", "u_dma", at="bc", size=10, lw=1.3)

# ---------- 내부 ----------
S.block(5.15, 2.85, 8.05, 3.3, "spike_list ×2  (u_list1, u_list2)", size=8)
S.block(5.15, 3.4, 8.05, 3.85, "64 × mac_unit  (g_lane, DSP48E1)", size=8)
S.block(5.15, 3.95, 8.05, 4.4, "plif_array → 16 × plift_core", size=8)
for e in range(4):
    y = 1.6 + e * 0.53
    S.block(9.95, y, 12.1, y + 0.45, f"weight_entry  g_entry[{e}]", fill=FILL_MEM, size=8)
S.text(11.03, 3.97, "word 2,034 × 512 bit\nparams 46 × 256 bit (each)", ha="center", size=7.5, color=MUTED)
S.block(12.3, 1.6, 14.25, 3.2, "next_use_predictor (u_pred)\nPNU-Count\nOFFSET_NUM · N_REG\nLUT_G · LUT_U", bold=True, size=8)
S.block(12.3, 3.35, 14.25, 4.1, "tag[0:3] · rank[0:3]\nvictim FSM", bold=True, size=8)
S.block(5.15, 6.45, 6.75, 7.9, "membrane_bank (u_bank)\non-chip tracks 0–767\n45 rows × 192 bit / track\n187 tile",
        fill=FILL_MEM, bold=True, size=7.5)
S.block(6.9, 6.45, 8.45, 7.9, "membrane_buf (u_buf)\nDDR3 tracks 768–1023\n2 buffers\nFILL→READY→BUSY→DRAIN",
        fill=FILL_MEM, bold=True, size=7.5)
S.block(5.15, 8.0, 8.45, 8.4, "16-bit compute ↔ 12-bit store (saturate · sign-extend)", size=7.5)
S.block(10.35, 6.45, 12.25, 7.6, "weight load\nslot = model_base + ld_model × 256 KiB\n4,114 beat (131,648 B)", bold=True,
        size=7.5)
S.block(12.4, 6.45, 14.25, 7.6, "state read / write\n34 beat (1,088 B) per track", bold=True, size=7.5)
S.block(10.35, 7.75, 14.25, 8.45, "AXI4 master 256 bit · ID 0 weight, ID 1 state\npriority: state read > state write > weight",
        size=7.5)
S.block(2.65, 5.15, 4.75, 6.05, "start = go_valid · go_ready\ngo_ready = !busy · w_ready · can_start\ncmp_entry, stall_cyc[63:0]",
        size=7)

# ---------- frontend (왼쪽) ----------
S.text(0.1, 1.25, "to / from frontend.v", size=8, color=MUTED, italic=True)
left = [
    (1.65, "pl_model[5:0]", ">", True, WC[0]),
    (2.0, "pl_entry, pl_hit, pl_done", "<", False, WC[0]),
    (2.4, "arr_*, q_ne[39:0]", ">", True, WC[0]),
    (3.1, "go_x[319:0], go_reset", ">", True, CA[0]),
    (4.1, "done, out_mem0/1[15:0], sat16", "<", True, CA[0]),
    (5.45, "go_valid, go_entry", ">", False, 2.65),
    (5.8, "go_ready", "<", False, 2.65),
    (6.6, "go_track[9:0]", ">", True, MS[0]),
    (7.05, "pf_track[9:0], pf_reset", ">", True, MS[0]),
    (7.5, "pf_ready", "<", False, MS[0]),
    (7.95, "wb_done", "<", False, MS[0]),
]
for y, lab, d, bus, x in left:
    pts = [(0.1, y), (x, y)] if d == ">" else [(x, y), (0.1, y)]
    S.wire(pts, lab, bus=bus, size=8, frac=0.0 if d == ">" else 1.0, dx=0.0)

# ---------- regs (위·아래) ----------
S.wire([(13.3, 0.1), (13.3, WC[1])], "from regs.v: now_us, phase_us, period, first_period, cfg_we, cfg_addr[10:0], cfg_data[15:0]",
       side="left", frac=0.22, size=8)
S.wire([(7.8, 10.3), (7.8, MS[3])], "state_base[31:0] (regs)", bus=True, side="left", frac=0.3, size=8)
S.wire([(10.7, 10.3), (10.7, DM[3])], "model_base[31:0] (regs)", bus=True, side="left", frac=0.3, size=8)
S.wire([(11.6, DM[3]), (11.6, 10.3)], "err, err_addr[31:0] (regs)", side="right", frac=0.7, size=8)
S.wire([(13.4, DM[3]), (13.4, 10.3)], "m_axi_*[255:0] (AXI4)\n→ MIG (run mux)", bus=True, end="<>", side="right",
       frac=0.72, size=8)

# ---------- 시작 신호 ----------
S.wire([(4.75, 5.6), (5.25, 5.6), (5.25, CA[3])], dot=[(5.25, 5.6)])
S.wire([(5.25, 5.6), (5.25, MS[1])])
S.text(4.8, 5.53, "start", size=7.5, va="bottom")

# ---------- compute_array ↔ weight_cache ----------
S.wire([(WC[0], 3.0), (CA[2], 3.0)], "w_a_data, w_b_data[511:0]", bus=True, frac=1.0, size=7.8)
S.wire([(WC[0], 3.5), (CA[2], 3.5)], "p_data[255:0]", bus=True, frac=1.0, size=7.8)
S.wire([(CA[2], 4.05), (WC[0], 4.05)], "w_a_addr, w_b_addr[10:0]\np_addr[5:0]", bus=True, size=7.8)

# ---------- weight_cache ↔ dma ----------
S.wire([(10.5, WC[3]), (10.5, DM[1])], "ld_model[5:0]\nld_busy", side="right", frac=0.5, size=7.8)
S.wire([(11.9, DM[1]), (11.9, WC[3])], "ld_done", side="right", frac=0.5, size=7.8)
S.wire([(12.9, DM[1]), (12.9, WC[3])], "wr_addr[10:0], wr_data[511:0]\nwr_paddr[5:0], wr_pdata[255:0]", bus=True,
       side="right", frac=0.5, size=7.8)

# ---------- compute_array ↔ membrane_storage ----------
S.wire([(5.75, CA[3]), (5.75, MS[1])], "m_rd_row[5:0]\nm_wr_row[5:0]", side="right", frac=0.5, size=7.5)
S.wire([(7.0, CA[3]), (7.0, MS[1])], "m_wr_data\n[255:0]", bus=True, side="right", frac=0.5, size=7.5)
S.wire([(8.05, MS[1]), (8.05, CA[3])], "m_rd_data\n[255:0]", bus=True, side="right", frac=0.5, size=7.5)

# ---------- membrane_buf ↔ dma ----------
S.wire([(MS[2], 6.7), (DM[0], 6.7)], "dr_req_addr[31:0]", size=7.8)
S.wire([(DM[0], 7.15), (MS[2], 7.15)], "dr_data[255:0]", bus=True, frac=1.0, size=7.8)
S.wire([(MS[2], 7.65), (DM[0], 7.65)], "dw_req_addr, dw_data[255:0]", bus=True, size=7.8)
S.wire([(DM[0], 8.15), (MS[2], 8.15)], "dw_resp", frac=1.0, size=7.8)

S.save(__file__)
