"""RTL 블록도 1: accel_top.v 전체(accel_sys 아래 모듈까지). 주요 port만, clock·reset은 뺀다.

근거: hardware/src/accel_top.v, accel_sys.v (03_ARCHITECTURE.md §2)
실행: python3 analysis/develop/rtl/fig1_x-accel-top_y-rtl-block.py
출력: analysis/figure/rtl/fig1_x-accel-top_y-rtl-block.{png,pdf}
"""
from blockdraw import FILL_IP, Sheet

S = Sheet(16.4, 8.4)

# ---------- 모듈 ----------
S.module(2.1, 0.3, 14.2, 8.1, "accel_top.v", at="tr", size=14)
S.module(2.5, 0.8, 11.75, 7.8, "accel_sys.v", "u_sys", at="br", size=13)

E = (2.95, 1.5, 4.45, 7.3)
CT = (5.9, 1.5, 7.4, 2.9)
RG = (9.1, 1.5, 10.6, 3.05)
FE = (5.9, 4.05, 7.4, 7.3)
CO = (9.1, 4.05, 10.6, 7.3)
for box, name in [(E, "eth_link.v"), (CT, "ctrl.v"), (RG, "regs.v"), (FE, "frontend.v"), (CO, "accel_core.v")]:
    S.module(*box, name, at="bc", size=10.5, lw=1.3)

# 아래 모듈(자세한 그림은 2–5)
for y, t in [(2.0, "eth_mac_1g_rgmii_fifo\n(verilog-ethernet)"), (3.0, "udp_complete\n(verilog-ethernet)"),
             (6.0, "mdio_master")]:
    S.block(3.1, y, 4.3, y + 0.55, t, size=8)
S.block(6.05, 1.62, 7.25, 2.32, "parser · FSM\nmem[1 KiB]", size=8)
S.block(9.25, 1.62, 10.45, 2.6, "CTRL · config\nnow_us · period\ncounters · ERR", size=8)
for i, t in enumerate(["ingest", "req_table", "track_scheduler", "result"]):
    S.block(6.05, 4.4 + i * 0.62, 7.25, 4.85 + i * 0.62, t, size=8.5)
for i, t in enumerate(["weight_cache", "compute_array", "membrane_storage", "dma"]):
    S.block(9.25, 4.4 + i * 0.62, 10.45, 4.85 + i * 0.62, t, size=8.5)

S.mux(11.2, 4.4, 11.5, 5.7, sel="run")
S.module(12.55, 4.15, 13.85, 5.95, "mig_ddr3", at="bc", size=10, lw=1.3, fill=FILL_IP)
S.text(13.2, 4.8, "MIG IP\nDDR3 controller", ha="center", size=8.5)
S.module(12.55, 6.5, 13.85, 7.7, "clock · reset", at="bc", size=9.5, lw=1.0, fill=FILL_IP)
S.text(13.2, 6.9, "MMCME2_ADV · BUFG\nIDELAYCTRL · sync_reset", ha="center", size=7.5)

# ---------- 보드 port ----------
S.wire([(0.1, 2.3), (E[0], 2.3)], "rgmii_rxd[3:0], rgmii_rx_ctl", bus=True, dx=0.0)
S.wire([(E[0], 2.9), (0.1, 2.9)], "rgmii_txd[3:0], rgmii_tx_ctl", bus=True, frac=1.0, dx=0.0)
S.wire([(E[0], 6.35), (0.1, 6.35)], "phy_mdc, phy_mdio", end="<>", frac=1.0, dx=0.0)
S.wire([(E[0], 6.95), (0.1, 6.95)], "phy_reset_n", frac=1.0, dx=0.0)
S.wire([(13.85, 5.05), (16.3, 5.05)], "ddr3_dq[31:0], ddr3_dqs[3:0]\nddr3_addr[14:0], ddr3_ba[2:0] …", bus=True,
       end="<>", dx=0.12)

# ---------- eth_link ↔ frontend, ctrl ----------
S.wire([(E[2], 4.6), (FE[0], 4.6)], "rq_data[511:0]", bus=True)
S.wire([(FE[0], 5.25), (E[2], 5.25)], "rs_data[255:0]", bus=True, frac=1.0)
S.wire([(E[2], 1.95), (CT[0], 1.95)], "cq_tdata[7:0]", bus=True)
S.wire([(CT[0], 2.55), (E[2], 2.55)], "cr_tdata[7:0]", bus=True, frac=1.0)

# ---------- ctrl → regs, DDR3 창 ----------
S.wire([(CT[2], 2.0), (RG[0], 2.0)], "AXI4-Lite [31:0]", bus=True)
S.wire([(7.1, CT[1]), (7.1, 1.2), (11.05, 1.2), (11.05, 4.75), (11.2, 4.75)],
       "c_* : AXI4 [255:0], DDR3 window (model image, run = 0)", bus=True, seg=1, dx=0.08, size=8)

# ---------- regs ↔ eth_link, frontend, accel_core ----------
S.wire([(9.3, RG[3]), (9.3, 3.45), (E[2], 3.45)], "rx_tap[4:0], md_cmd[31:0]  /  link_dbg[383:0]", end="<>",
       seg=1, frac=1.0)
S.wire([(9.6, RG[3]), (9.6, 3.8), (7.1, 3.8), (7.1, FE[1])], "run, n_tracks, now_us  /  ev_*, err_*", end="<>",
       seg=1, frac=1.0, size=7.5, dx=0.08)
S.wire([(9.95, RG[3]), (9.95, CO[1])], end="<>")
S.text(10.02, 3.55, "model_base,\nstate_base,\nnow_us, cfg_*\n/ stall_cyc, err", size=7.2)

# ---------- frontend ↔ accel_core ----------
fe_co = [
    (4.5, "arr_model[5:0], arr_t_host[31:0]", ">", True),
    (4.9, "q_ne[39:0]", ">", True),
    (5.3, "pl_model[5:0]", ">", True),
    (5.7, "pl_entry, pl_hit, pl_done", "<", False),
    (6.1, "pf_track[9:0], pf_reset", ">", True),
    (6.5, "go_x[319:0], go_track[9:0]", ">", True),
    (6.9, "done, out_mem0/1[15:0], wb_done", "<", True),
]
for y, lab, d, bus in fe_co:
    pts = [(FE[2], y), (CO[0], y)] if d == ">" else [(CO[0], y), (FE[2], y)]
    S.wire(pts, lab, bus=bus, size=7.5, frac=0.0 if d == ">" else 1.0)

# ---------- accel_core → mux → MIG ----------
S.wire([(CO[2], 5.35), (11.2, 5.35)], "d_*", bus=True, size=7.5)
S.wire([(11.5, 5.05), (12.55, 5.05)], "m_axi_*\n[255:0]", bus=True, size=8)

S.save(__file__)
