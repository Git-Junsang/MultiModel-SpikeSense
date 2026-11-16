"""RTL 블록도 2: frontend.v — ingest, req_table, track_scheduler, result. 주요 port만, clock·reset은 뺀다.
track_scheduler의 now_us·ev_batch와 req_table의 pending_n(regs)은 선이 겹쳐 뺐다.

근거: hardware/src/frontend.v, ingest.v, req_table.v, track_scheduler.v, result.v (03_ARCHITECTURE.md §2·§3)
실행: python3 analysis/develop/rtl/fig2_x-frontend_y-rtl-block.py
출력: analysis/figure/rtl/fig2_x-frontend_y-rtl-block.{png,pdf}
"""
from blockdraw import FILL_MEM, MUTED, Sheet

S = Sheet(16.8, 8.9)

FB = (2.0, 0.6, 14.0, 8.3)
S.module(*FB, "frontend.v", "u_fe", at="br", size=14)
I = (2.5, 1.9, 4.5, 4.5)
T = (6.3, 1.9, 9.1, 5.95)
SC = (10.9, 1.9, 13.1, 5.95)
R = (6.3, 6.6, 9.9, 7.95)
S.module(*I, "ingest.v", "u_in", at="bc", size=10, lw=1.3)
S.module(*T, "req_table.v", "u_rt", at="bc", size=10, lw=1.3)
S.module(*SC, "track_scheduler.v", "u_sch", at="bc", size=10, lw=1.3)
S.module(*R, "result.v", "u_res", at="bc", size=10, lw=1.3)

# ---------- 내부 ----------
S.block(2.65, 2.15, 4.35, 3.6, "check\nmagic · track_id · model_id\nx ≤ 127 · pend (drop)", bold=True, size=8)
S.block(2.65, 3.7, 4.35, 4.1, "err_code[3:0], err_info", size=7.5)
for i, t in enumerate(["xmem[0:1023]\n321 bit {RESET_STATE, x}", "meta[0:1023]\n87 bit {t_in, t_host, seq, model}",
                       "nxt[0:1023] · pend[0:1023]\nper-track link, result pending",
                       "head · tail · cnt · hseq [0:39]\nper-model wait list"]):
    y = 2.05 + i * 0.86
    S.block(6.45, y, 8.95, y + 0.74, t, fill=FILL_MEM, bold=True, size=8)
S.block(11.05, 2.05, 12.95, 3.45, "plan FSM (Grouping)\nQ_SCAN → Q_PLAN → Q_WAIT\noldest head → pl_model", bold=True, size=8)
S.block(11.05, 3.6, 12.95, 5.0, "start FSM\nM_READ → M_PF → M_GO\nbatch members in arrival order", bold=True, size=8)
S.block(6.45, 6.75, 8.1, 7.55, "f[0:3] 119 bit\ncompletion FIFO", fill=FILL_MEM, bold=True, size=8)
S.block(8.25, 6.75, 9.75, 7.55, "LATE\nt_done > t_host\n+ deadline − margin", bold=True, size=7.5)

# ---------- 바깥 port: eth_link ----------
S.wire([(0.1, 2.4), (I[0], 2.4)], "rq_data[511:0], rq_valid", bus=True, dx=0.0)
S.wire([(R[0], 7.3), (0.1, 7.3)], "rs_data[255:0], rs_valid", bus=True, frac=1.0, dx=0.0)
S.text(0.1, 2.0, "from eth_link.v", size=8, color=MUTED, italic=True)
S.text(0.1, 6.9, "to eth_link.v", size=8, color=MUTED, italic=True)

# ---------- 바깥 port: regs ----------
S.wire([(2.9, 0.12), (2.9, I[1])], "run, n_tracks[10:0], n_models[5:0], now_us[31:0]", side="left", seg=0, frac=0.12,
       size=8)
S.wire([(3.7, I[1]), (3.7, 0.12)], "ev_req_in, ev_req_drop, err_code[3:0]", side="right", seg=0, frac=0.88, size=8)
S.wire([(6.75, 8.85), (6.75, R[3])], "deadline_us, margin_us", side="left", frac=0.3, size=8)
S.wire([(7.5, R[3]), (7.5, 8.85)], "ev_res_out, ev_late, ev_sat", side="right", frac=0.7, size=8)

# ---------- ingest ↔ req_table ----------
S.wire([(I[2], 2.4), (T[0], 2.4)], "chk_track[9:0]", bus=True)
S.wire([(T[0], 2.85), (I[2], 2.85)], "chk_pend", frac=1.0)
S.wire([(I[2], 3.55), (T[0], 3.55)], "ap_track[9:0], ap_model[5:0]\nap_xrs[320:0], ap_meta[86:0]", bus=True, size=8)

# ---------- ingest → predictor, req_table → weight_cache (S 위로) ----------
S.wire([(4.2, I[1]), (4.2, 1.1), (16.7, 1.1)], "arr_model[5:0], arr_t_host[31:0], arr_n_expect[10:0]  → next_use_predictor",
       bus=True, seg=1, frac=0.38, size=8)
S.wire([(8.8, T[1]), (8.8, 1.5), (16.7, 1.5)], "q_ne[39:0]  → weight_cache", bus=True, seg=1, frac=0.09, size=8)

# ---------- req_table ↔ track_scheduler ----------
ts = [
    (2.3, "sc_model, hd_model, dt_model", "<", False),
    (2.8, "sc_ne, sc_hseq, hd_head, dt_cnt", ">", True),
    (3.4, "nx_track[9:0], xr_track[9:0]", "<", True),
    (3.9, "nx_next[9:0]", ">", True),
    (4.45, "xr_data[320:0]", ">", True),
    (4.95, "q_total[10:0]", ">", True),
]
for y, lab, d, bus in ts:
    pts = [(T[2], y), (SC[0], y)] if d == ">" else [(SC[0], y), (T[2], y)]
    S.wire(pts, lab, bus=bus, size=7.8, frac=0.0 if d == ">" else 1.0)

# ---------- track_scheduler ↔ accel_core ----------
S.text(14.1, 1.85, "to / from accel_core.v", size=8, color=MUTED, italic=True)
sc = [
    (2.3, "pl_model[5:0]", ">", True),
    (2.75, "pl_entry, pl_hit, pl_done", "<", False),
    (3.25, "pf_track[9:0], pf_reset", ">", True),
    (3.7, "pf_ready", "<", False),
    (4.2, "go_x[319:0], go_track[9:0], go_entry", ">", True),
    (4.65, "go_ready", "<", False),
    (5.15, "done, out_mem0/1[15:0], sat16", "<", True),
]
for y, lab, d, bus in sc:
    pts = [(SC[2], y), (16.7, y)] if d == ">" else [(16.7, y), (SC[2], y)]
    S.wire(pts, lab, bus=bus, size=7.8, frac=0.0 if d == ">" else 1.0, dx=1.0)

# ---------- track_scheduler ↔ result ----------
S.wire([(11.5, SC[3]), (11.5, 7.0), (R[2], 7.0)], "cp_data[118:0]", bus=True, seg=1, frac=1.0, dx=0.05)
S.wire([(R[2], 7.45), (12.2, 7.45), (12.2, SC[3])], "res_ok", seg=1, frac=0.0, side="right", size=8)
S.wire([(16.7, 7.75), (R[2], 7.75)], "wb_done  (DDR3 track write-back)", frac=0.0, ha="right", dx=0.05, size=8)

# ---------- req_table ↔ result ----------
S.wire([(6.75, R[1]), (6.75, T[3])], "mr_track[9:0]", side="right", frac=0.5, size=7.5)
S.wire([(7.85, T[3]), (7.85, R[1])], "mr_data[86:0]", bus=True, side="right", frac=0.5, size=7.5)
S.wire([(8.95, R[1]), (8.95, T[3])], "free_track[9:0]", side="right", frac=0.5, size=7.5)

S.save(__file__)
