"""RTL 블록도 5: accel_sys.v의 링크·제어 경로 — eth_link.v(IDELAYE2, verilog-ethernet MAC·UDP, 받기·보내기 FSM,
mdio_master), ctrl.v, regs.v. 주요 port만, clock·reset은 뺀다. len_err와 진단 counter 입력선은 상자 글로 적었다.

근거: hardware/src/eth_link.v, mdio_master.v, ctrl.v, regs.v, accel_sys.v (06_HOST_INTERFACE.md §3·§4·§7)
실행: python3 analysis/develop/rtl/fig5_x-eth-ctrl-regs_y-rtl-block.py
출력: analysis/figure/rtl/fig5_x-eth-ctrl-regs_y-rtl-block.{png,pdf}
"""
from blockdraw import FILL_IP, FILL_MEM, MUTED, Sheet

S = Sheet(19.6, 9.7)

EB = (2.3, 0.9, 11.7, 9.1)
CT = (12.95, 2.7, 15.25, 5.3)
RG = (12.95, 6.9, 15.95, 9.1)
S.module(*EB, "eth_link.v", "u_eth", at="tl", size=13)
S.module(*CT, "ctrl.v", "u_ctrl", at="bc", size=10.5, lw=1.3)
S.module(*RG, "regs.v", "u_regs", at="bc", size=10.5, lw=1.3)

# ---------- eth_link 안 ----------
DLY = (2.7, 1.75, 3.9, 2.7)
MAC = (4.3, 1.6, 6.05, 6.6)
ERX = (6.6, 1.75, 7.7, 3.0)
ETX = (6.6, 5.2, 7.7, 6.45)
UDP = (8.3, 1.6, 9.4, 6.6)
RXF = (10.0, 1.6, 11.3, 3.6)
TXF = (10.0, 4.6, 11.3, 6.6)
MDIO = (2.7, 7.3, 4.1, 7.95)
PRST = (2.7, 8.15, 4.1, 8.75)
DIAG = (8.2, 8.15, 11.3, 8.75)
S.block(*DLY, "IDELAYE2 ×5\n(u_dly)\ntap = rx_tap", bold=True, size=7.2)
S.block(*MAC, "eth_mac_1g_rgmii_fifo\n(u_mac)\nRGMII ↔ MAC\nFCS check\nRX FIFO 8 KiB\nTX FIFO 4 KiB",
        fill=FILL_IP, bold=True, size=7.8)
S.block(*ERX, "eth_axis_rx\n(u_erx)", fill=FILL_IP, bold=True, size=7.8)
S.block(*ETX, "eth_axis_tx\n(u_etx)", fill=FILL_IP, bold=True, size=7.8)
S.block(*UDP, "udp_complete\n(u_udp)\nARP · IPv4\nUDP\nchecksum 0", fill=FILL_IP, bold=True, size=7.8)
S.block(*RXF, "RX FSM\nR_HDR · R_REQ\nR_CTRL · R_DROP\nport 5000 → rq\nport 5001 → cq\nlength check", bold=True,
        size=7.5)
S.block(*TXF, "TX FSM\nT_HDR · T_PAY\nresult first,\nthen ctrl reply", bold=True, size=7.5)
S.block(*MDIO, "mdio_master\n(u_mdio)", bold=True, size=7.5)
S.block(*PRST, "PHY reset counter", size=7.5)
S.block(*DIAG, "dc[0:11] diagnostic counters (FIFO, FCS, ARP …)", size=7.5)
S.text(6.85, 6.85, "gray blocks: verilog-ethernet (MIT)", size=7.5, color=MUTED, italic=True, ha="center")

# ---------- 보드 PHY (왼쪽) ----------
S.text(0.1, 1.45, "RGMII PHY", size=8, color=MUTED, italic=True)
S.wire([(0.1, 2.2), (DLY[0], 2.2)], "rgmii_rxd[3:0], rgmii_rx_ctl", bus=True, size=8, dx=0.0)
S.wire([(MAC[0], 5.9), (0.1, 5.9)], "rgmii_txd[3:0], rgmii_tx_ctl", bus=True, size=8, frac=1.0, dx=0.0)
S.wire([(MDIO[0], 7.62), (0.1, 7.62)], "phy_mdc, phy_mdio", end="<>", size=8, frac=1.0, dx=0.0)
S.wire([(PRST[0], 8.45), (0.1, 8.45)], "phy_reset_n", size=8, frac=1.0, dx=0.0)

# ---------- 받기 ----------
S.wire([(DLY[2], 2.2), (MAC[0], 2.2)], bus=True)
S.wire([(MAC[2], 2.2), (ERX[0], 2.2)], bus=True)
S.wire([(ERX[2], 2.4), (UDP[0], 2.4)], bus=True)
S.wire([(UDP[2], 2.4), (RXF[0], 2.4)], bus=True)

# ---------- 보내기 ----------
S.wire([(TXF[0], 5.6), (UDP[2], 5.6)], bus=True)
S.wire([(UDP[0], 5.8), (ETX[2], 5.8)], bus=True)
S.wire([(ETX[0], 5.8), (MAC[2], 5.8)], bus=True)

# ---------- frontend ----------
S.wire([(RXF[2], 1.9), (19.5, 1.9)], "rq_data[511:0]  → frontend.v (64 B request)", bus=True, frac=0.0, size=8,
       dx=1.75)
S.wire([(19.5, 6.3), (TXF[2], 6.3)], "rs_data[255:0]  ← frontend.v (32 B result)", bus=True, frac=0.0, ha="right",
       size=8, dx=0.1)

# ---------- ctrl ----------
S.block(13.1, 3.0, 15.1, 3.7, "mem[0:1023]\nrequest / reply buffer", fill=FILL_MEM, bold=True, size=7.5)
S.block(13.1, 3.85, 15.1, 4.85, "FSM\nS_RX → S_CHK → AXI → reply\nstatus 1–3", bold=True, size=7.5)
S.wire([(RXF[2], 3.2), (CT[0], 3.2)], "cq_tdata[7:0]", bus=True, size=7.8, dx=0.5)
S.wire([(CT[0], 4.95), (TXF[2], 4.95)], "cr_tdata[7:0]\ncr_len[10:0]", bus=True, size=7.8, frac=1.0, dx=0.5)
S.wire([(CT[2], 3.4), (19.5, 3.4)], "c_* : AXI4 [255:0]  → MIG (DDR3 window, run = 0)", bus=True, size=8, dx=0.1)

# ---------- regs ----------
S.wire([(14.05, CT[3]), (14.05, RG[1])], "AXI4-Lite [31:0]", bus=True, side="right", frac=0.75, size=7.8)
S.block(13.1, 7.15, 14.4, 7.95, "CTRL\nRUN · SOFT_RESET\nCNT/ERR_CLEAR", bold=True, size=7)
S.block(14.5, 7.15, 15.8, 7.95, "config\nN_TRACKS · bases\nDEADLINE · LINK_TUNE", bold=True, size=7)
S.block(13.1, 8.05, 14.4, 8.7, "time\nnow_us · period", fill=FILL_MEM, bold=True, size=7)
S.block(14.5, 8.05, 15.8, 8.7, "counters · first ERR\nPNU window → cfg_*", fill=FILL_MEM, bold=True, size=7)
S.wire([(RG[0], 7.55), (MDIO[2], 7.55)], "md_cmd[31:0]  /  md_rdata[15:0]", end="<>", size=7.8, frac=1.0, dx=0.1)
S.wire([(DIAG[2], 8.45), (RG[0], 8.45)], "link_dbg[383:0], len_err", bus=True, size=7.8, dx=0.45)
S.text(4.25, 7.12, "rx_tap[4:0] (LINK_TUNE) → IDELAYE2", size=7.5, color=MUTED, italic=True)
S.wire([(RG[2], 7.35), (19.5, 7.35)], "run, n_tracks, n_models, model_base, state_base,\ndeadline_us, margin_us, now_us, "
       "phase_us, period, cfg_*", size=7.8, dx=0.1)
S.text(16.05, 6.75, "→ frontend.v, accel_core.v", size=8, color=MUTED, italic=True)
S.wire([(19.5, 8.15), (RG[2], 8.15)], "ev_*, pending_n, stall_cyc, err_*  ← frontend.v, accel_core.v", size=7.8,
       ha="right", frac=0.0, dx=0.05)
S.wire([(RG[2], 8.8), (19.5, 8.8)], "tx_ps[15:0] (LINK_TUNE) → MMCM fine phase", size=7.8, dx=0.1)

S.save(__file__)
