"""RTL 블록도 4: compute_array.v — spike_list ×2, 64 × mac_unit, layer-4 adder tree, shadow, plif_array(16 × plift_core).
주요 port만, clock·reset은 뺀다. FSM의 제어선(단계 register c_*, row 순서 bu_*)은 그리지 않았다.

근거: hardware/src/compute_array.v, spike_list.v, mac_unit.v, plif_array.v, plift_core.v (03_ARCHITECTURE.md §4)
실행: python3 analysis/develop/rtl/fig4_x-compute-array_y-rtl-block.py
출력: analysis/figure/rtl/fig4_x-compute-array_y-rtl-block.{png,pdf}
"""
from blockdraw import FILL_MEM, MUTED, Sheet

S = Sheet(15.4, 9.7)

CB = (2.4, 1.0, 13.9, 8.7)
S.module(*CB, "compute_array.v", "u_ca", at="bl", size=14)

# ---------- 내부 ----------
FSM = (2.8, 1.4, 4.8, 2.45)
INB = (2.8, 2.9, 4.8, 3.5)
OUT = (2.8, 7.3, 4.8, 7.95)
ADR = (5.5, 1.4, 7.5, 2.4)
SPK = (5.5, 3.5, 7.5, 4.6)
S3 = (5.5, 4.85, 7.5, 5.4)
MAC = (8.6, 1.4, 11.4, 3.0)
SH = (8.3, 3.6, 9.7, 4.3)
TR = (9.9, 3.6, 11.4, 4.3)
PL = (5.5, 6.0, 11.4, 6.9)
CNT = (11.8, 7.4, 13.4, 8.1)

S.block(*FSM, "FSM\nS_IDLE → S_L1 … S_L4 → S_WAIT\nlayer · group · op_pos", bold=True, size=7.8)
S.block(*INB, "in_buf[319:0]\nmel 40 × 8 bit", fill=FILL_MEM, bold=True, size=7.8)
S.block(*OUT, "out_mem0/1[15:0]\nlayer-4 outputs", fill=FILL_MEM, bold=True, size=7.8)
S.block(*ADR, "word address (stage 1)\nw_*_addr = base + idx", bold=True, size=7.8)
S.block(*SPK, "u_list1, u_list2: spike_list\nindex of spikes = 1\nlayer 1: 384 · layer 2: 256", fill=FILL_MEM, bold=True,
        size=7.8)
S.block(*S3, "s3[63:0]\nlayer-3 spikes", fill=FILL_MEM, bold=True, size=7.8)
S.block(*MAC, "g_lane[0:63]: 64 × mac_unit\nDSP48E1\np = (a + d) × b + p", bold=True, size=8)
S.block(*SH, "shadow\n64 × cur", fill=FILL_MEM, bold=True, size=7.8)
S.block(*TR, "layer-4 adder tree\n64 → 16 → 4 → 1", bold=True, size=7.8)
S.block(*PL, "plif_array (u_plif): 16 × plift_core\nleak · integrate · fire · soft reset, 16 neurons / cycle", bold=True,
        size=8)
S.block(*CNT, "row counter bu_row\nP0 read → P4 write", bold=True, size=7.5)
S.mux(7.95, 1.55, 8.25, 2.85)

# ---------- 바깥: accel_core (왼쪽) ----------
S.text(0.1, 1.25, "from / to accel_core.v", size=8, color=MUTED, italic=True)
S.wire([(0.1, 1.7), (FSM[0], 1.7)], "start, reset_state", size=8, dx=0.0)
S.wire([(FSM[0], 2.15), (0.1, 2.15)], "busy, done", size=8, frac=1.0, dx=0.0)
S.wire([(0.1, 3.2), (INB[0], 3.2)], "x_in[319:0]", bus=True, size=8, dx=0.0)
S.wire([(OUT[0], 7.6), (0.1, 7.6)], "out_mem0/1[15:0], sat16", bus=True, size=8, frac=1.0, dx=0.0)

# ---------- 바깥: weight_cache (위) ----------
S.wire([(6.5, ADR[1]), (6.5, 0.12)], "w_a_addr, w_b_addr[10:0]", bus=True, side="right", frac=0.75, size=8)
S.wire([(9.3, 0.12), (9.3, MAC[1])], "w_a_data[511:0] → a", bus=True, side="right", frac=0.2, size=8)
S.wire([(10.7, 0.12), (10.7, MAC[1])], "w_b_data[511:0] → d", bus=True, side="right", frac=0.2, size=8)
S.wire([(12.2, 0.12), (12.2, 6.45), (PL[2], 6.45)], "p_data[255:0]\n{vth, beta}", bus=True, side="right", frac=0.2,
       size=8)
S.wire([(13.1, CNT[1]), (13.1, 0.12)], "p_addr[5:0]", side="right", frac=0.86, size=8)
S.text(13.95, 0.25, "weight_cache.v", size=8, color=MUTED, italic=True)

# ---------- 바깥: membrane_storage (아래) ----------
S.wire([(8.6, PL[3]), (8.6, 9.6)], "m_wr_data[255:0]", bus=True, side="right", frac=0.75, size=8)
S.wire([(10.4, 9.6), (10.4, PL[3])], "m_rd_data[255:0]", bus=True, side="right", frac=0.25, size=8)
S.wire([(12.6, CNT[3]), (12.6, 9.6)], "m_rd_row, m_wr_row[5:0]", side="right", frac=0.6, size=8)
S.text(13.95, 9.45, "membrane_storage.v", size=8, color=MUTED, italic=True, va="center")

# ---------- 내부 선 ----------
S.wire([(6.5, SPK[1]), (6.5, ADR[3])], "rd_idx0, rd_idx1", side="right", frac=0.5, size=7.5)
S.wire([(INB[2], 3.2), (7.75, 3.2), (7.75, 1.8), (7.95, 1.8)], "x_q bit (layer 1)", seg=0, frac=0.0, size=7.5)
S.wire([(S3[2], 5.1), (7.85, 5.1), (7.85, 2.6), (7.95, 2.6)], "s3[j] (layer 4)", seg=0, frac=0.0, size=7.5, dx=0.04)
S.text(7.9, 2.2, "1", ha="right", size=7.5)
S.wire([(8.25, 2.2), (MAC[0], 2.2)], "b", size=7.5, dx=0.02)
S.wire([(9.0, MAC[3]), (9.0, SH[1])], "p", bus=True, side="right", frac=0.5, size=7.5)
S.wire([(10.7, MAC[3]), (10.7, TR[1])], "p_low", bus=True, side="right", frac=0.5, size=7.5)
S.wire([(TR[0], 3.95), (SH[2], 3.95)])
S.text(9.8, 3.55, "t3", ha="center", size=7.5, va="bottom")
S.wire([(9.0, SH[3]), (9.0, PL[1])], "cur (4 rows × 16)", bus=True, side="right", frac=0.5, size=7.5)
S.wire([(PL[0], 6.3), (5.2, 6.3), (5.2, 3.9), (SPK[0], 3.9)], "spk[15:0]", seg=1, side="left", frac=0.15, size=7.5,
       dot=[(5.2, 5.1)])
S.wire([(5.2, 5.1), (S3[0], 5.1)])
S.wire([(PL[0], 6.7), (3.8, 6.7), (3.8, OUT[1])], "mem_out (layer 4)", seg=1, side="left", frac=0.5, size=7.5)

S.save(__file__)
