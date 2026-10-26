#!/usr/bin/env python3
"""p52_sys.py — accel_top 보드 시험(P5.2): tb_sys.sv와 같은 순서를 Ethernet 너머 실제 FPGA에 돌린다 (FPGA Host)

Host NIC는 FPGA와 직결하고 192.168.10.1/24를 준다(FPGA 192.168.10.2, 06 §4). 표준 라이브러리만 쓴다.
golden은 tb_sys와 같은 vec_m12(hardware/testbench/export_compute_vectors.py가 만든 hex)다.

    python3 p52_sys.py --vec <vec_m12 폴더> [--nt 31] [--out result.json]

순서 (06_HOST_INTERFACE.md §6, tb_sys와 같다. testbench만 볼 수 있는 계층 확인은 뺀다):
  1) 정보 register, STATUS.MIG_CALIB
  2) 모델 40개를 1 KiB 제어 쓰기로 DDR3 창에 적재하고 다시 읽어 비교
  3) 설정 쓰기·읽기, PNU 표(시나리오 값), SOFT_RESET, RUN = 1, RUN 중 설정·DDR3 쓰기 무시
  4) timestep마다 NOW_US를 t_host로 추론 요청 80개(트랙 80, DDR3 20)를 datagram(최대 23개)으로 보내고 결과 80개를 받아
     out0·out1을 golden과 비교, track·seq·model·flags·batch_n·시각 순서 확인
  5) IDLE 뒤 RUN = 0, counter, DDR3 트랙 membrane potential을 DDR3 창으로 읽어 golden 마지막 12 bit 저장값과 비교
  5b) 모델 slot을 둘씩(2k ↔ 2k+1) 맞바꿔 쓰고 SOFT_RESET, DEADLINE_US 1로 timestep 한 번. Cache entry가 남으면 out이 어긋난다
  6) 오류: model_id 45 → ERR_CODE 3·ERR_INFO 트랙, 100 B datagram은 첫 오류 유지, ERR_CLEAR, 100 B → ERR_CODE 7·100
"""
import argparse
import json
import os
import random
import socket
import struct
import sys
import time

FPGA_IP, HOST_IP = '192.168.10.2', '192.168.10.1'
RPORT, CPORT = 6000, 6100                    # Host 쪽 port(FPGA는 받은 port로 되돌려 보낸다)
N_MOD, N_VEC, N_ON_CHIP, E, T, ROWS, LD = 40, 80, 768, 4, 31, 45, 4114
SB, DEADLINE, MARGIN = 0x0200_0000, 32000, 0
DDR = 0x8000_0000
CMP_BUSY_SIM = 1_331_594                     # tb_sys(nt 31)의 CMP_BUSY. 연산 cycle은 데이터로 정해져 batch 구성과 상관없다

errors = []


def err(s):
    errors.append(s)
    if len(errors) <= 30:
        print('ERROR', s, flush=True)


def trk(v):                                  # tb_dma·tb_sys와 같다
    return {0: 0, 1: 768, 2: 767, 3: 1023}.get(v, (v * 37 + 11) % 1024)


def readhex(path):
    with open(path) as f:
        return [int(s, 16) for s in (l.split('//')[0].strip() for l in f) if s and not s.startswith('@')]


# ---------------- 제어 packet (06 §7.6) ----------------
class Ctl:
    def __init__(self, timeout):
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.s.bind((HOST_IP, CPORT))
        self.s.settimeout(timeout)
        self.tag = 0x1000
        self.n = 0

    def __call__(self, op, addr, cnt, data=(), exp_st=0, name=''):
        h = struct.pack('<BBHIHH', 0x5C, op, self.tag & 0xFFFF, addr, cnt, 0)
        self.tag += 1
        self.s.sendto(h + b''.join(struct.pack('<I', w) for w in data), (FPGA_IP, 5001))
        try:
            r, src = self.s.recvfrom(2048)
        except socket.timeout:
            raise SystemExit(f'FAIL {name}: 제어 응답 없음')
        self.n += 1
        rlen = 12 + 4 * cnt if op == 1 and exp_st == 0 else 12
        if r[:10] != h[:10]:
            err(f'{name}: reply header {r[:10].hex()}, sent {h[:10].hex()}')
        if len(r) != rlen:
            err(f'{name}: reply length {len(r)}, expected {rlen}')
            return []
        st = struct.unpack_from('<H', r, 10)[0]
        if st != exp_st:
            err(f'{name}: status {st}, expected {exp_st}')
        return list(struct.unpack_from(f'<{(rlen - 12) // 4}I', r, 12))

    def rd(self, addr, cnt, name):
        w = self(1, addr, cnt, name=name)
        if len(w) != cnt:
            raise SystemExit(f'FAIL {name}: 읽은 word 수 {len(w)}')
        return w

    def wr(self, addr, v, name):
        self(2, addr, 1, [v], name=name)


def expect(got, exp, name):
    if got != exp:
        err(f'{name}: {got:#x}, expected {exp:#x}')


# ---------------- golden ----------------
class Golden:
    def __init__(self, vec, nt):
        self.idx = readhex(f'{vec}/index.hex')
        self.x = [readhex(f'{vec}/v{v:02d}_x.hex') for v in range(N_VEC)]
        self.o = [readhex(f'{vec}/v{v:02d}_o.hex') for v in range(N_VEC)]
        self.e = {}                          # DDR3 트랙의 마지막 timestep row만
        for v in range(N_VEC):
            if self.idx[v] != v // 2:
                err(f'index.hex v{v} model {self.idx[v]}')
            if trk(v) >= N_ON_CHIP:
                e = readhex(f'{vec}/v{v:02d}_e.hex')
                self.e[v] = e[(nt - 1) * ROWS:nt * ROWS]
        self.img = []                        # slot 이미지 word: params row 46개, 그다음 512 bit word마다 beat 2개(앞 = 아래 256 bit)
        for m in range(N_MOD):
            p, w = readhex(f'{vec}/m{m:02d}_p.hex'), readhex(f'{vec}/m{m:02d}_w.hex')
            beats = p + [b for x in w for b in (x & (1 << 256) - 1, x >> 256)]
            assert len(beats) == LD
            self.img.append([(b >> 32 * j) & 0xFFFF_FFFF for b in beats for j in range(8)])


# ---------------- 단계 ----------------
def slot_chunks():
    for i in range((LD + 31) // 32):
        yield i, min(32, LD - 32 * i)


def wr_slot(ctl, g, m, src):
    for i, nb in slot_chunks():
        ctl(2, DDR + 0x40000 * m + 1024 * i, 8 * nb, g.img[src][256 * i:256 * i + 8 * nb], name=f'slot {m} write {i}')


def load_model(ctl, g, m):
    wr_slot(ctl, g, m, m)
    mis = 0
    for i, nb in slot_chunks():
        r = ctl(1, DDR + 0x40000 * m + 1024 * i, 8 * nb, name=f'model {m} read {i}')
        mis += sum(a != b for a, b in zip(r, g.img[m][256 * i:256 * i + 8 * nb])) + abs(len(r) - 8 * nb)
    if mis:
        err(f'model {m}: read back mismatch {mis}')


def req_bytes(tk, t, model, th, x):
    w = 0xA5 | (int(t == 0) << 8) | (tk << 16) | (t << 32) | (model << 48) | (th << 64) | (2 << 96) | (x << 128)
    return w.to_bytes(64, 'little')


class Infer:
    def __init__(self, ctl, g, timeout):
        self.ctl, self.g = ctl, g
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.s.bind((HOST_IP, RPORT))
        self.s.settimeout(timeout)
        self.vof = {trk(v): v for v in range(N_VEC)}
        self.mmap = list(range(N_MOD))
        self.dl = DEADLINE
        self.reset_stats()

    def reset_stats(self):
        self.nreq = self.n_res = self.n_late = self.err_out = self.err_fld = 0
        self.n_bn = [0, 0, 0]
        self.fpga_delay = []                        # t_done − t_in (µs)

    def check(self, r, t, th, got):
        g = int.from_bytes(r, 'little')
        f = lambda lo, n: (g >> lo) & ((1 << n) - 1)
        tk, seq, model, fl, bn = f(0, 16), f(16, 16), f(32, 8), f(40, 8), f(48, 16)
        t_host, t_in, t_st, t_dn, o, rsv = f(64, 32), f(96, 32), f(128, 32), f(160, 32), f(192, 32), f(224, 32)
        s32 = lambda a: a - (1 << 32) if a & (1 << 31) else a
        self.n_res += 1
        v = self.vof.get(tk)
        if v is None or len(r) != 32:
            err(f't{t}: result for unknown track {tk} (length {len(r)})')
            return
        if tk in got:
            err(f't{t}: second result for track {tk}')
            return
        got.add(tk)
        if o != self.g.o[v][t]:
            self.err_out += 1
            err(f't{t} track {tk} (v{v}): out {o:08x}, golden {self.g.o[v][t]:08x}')
        late = s32((t_dn - (t_host + self.dl - MARGIN)) & 0xFFFF_FFFF) > 0
        self.n_late += late
        if 1 <= bn <= 2:
            self.n_bn[bn] += 1
        self.fpga_delay.append(s32((t_dn - t_in) & 0xFFFF_FFFF))
        if (seq != t or model != self.mmap[self.g.idx[v]] or fl != (late << 2 | int(t == 0)) or not 1 <= bn <= 2
                or t_host != th or s32((t_in - t_host) & 0xFFFF_FFFF) < 0 or s32((t_st - t_in) & 0xFFFF_FFFF) < 0
                or s32((t_dn - t_st) & 0xFFFF_FFFF) < 0 or rsv != 0):
            self.err_fld += 1
            err(f't{t} track {tk}: seq {seq} model {model} flags {fl:03b} batch_n {bn} t_host {t_host}/{th} '
                f't_in {t_in} t_start {t_st} t_done {t_dn} rsv {rsv:x}')

    def do_t(self, t, rng):
        th = self.ctl.rd(0x0200, 1, 'NOW_US')[0]
        order = list(range(N_VEC))
        rng.shuffle(order)
        for i in range(0, N_VEC, 23):
            d = b''.join(req_bytes(trk(v), t, self.mmap[self.g.idx[v]], th, self.g.x[v][t]) for v in order[i:i + 23])
            self.s.sendto(d, (FPGA_IP, 5000))
            self.nreq += len(order[i:i + 23])
        got = set()
        while len(got) < N_VEC:
            try:
                r = self.s.recv(2048)
            except socket.timeout:
                raise SystemExit(f'FAIL t{t}: 결과 {len(got)}/{N_VEC}개만 옴')
            self.check(r, t, th, got)


def wait_idle(ctl, name):
    for _ in range(200):
        if ctl.rd(0x0100, 1, 'STATUS')[0] & 2:
            return
        time.sleep(0.001)
    err(f'{name}: STATUS.IDLE 0')


def counters(ctl, name):
    c = ctl.rd(0x0400, 16, name)
    q = lambda i: c[i] | c[i + 1] << 32
    return c, q(8), q(10), q(12), q(14)       # c, WEIGHT_BYTES, STATE_BYTES, CMP_BUSY, CMP_STALL


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--vec', required=True)
    ap.add_argument('--nt', type=int, default=T)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--timeout', type=float, default=1.0)
    ap.add_argument('--out', default='')
    ap.add_argument('--link', default='', help='시작 전에 쓸 LINK_TUNE "수신 tap,송신 위상 단계"(p52_link.py로 찾은 값)')
    a = ap.parse_args()
    nt = max(1, min(a.nt, T))
    rng = random.Random(a.seed)
    t0 = time.time()
    g = Golden(a.vec, nt)
    ctl = Ctl(a.timeout)
    inf = Infer(ctl, g, a.timeout)
    n_ddr3 = sum(trk(v) >= N_ON_CHIP for v in range(N_VEC))
    summary = {'nt': nt, 'seed': a.seed, 'link': a.link}
    if a.link:                               # 손실이 있는 기본값에서 쓰므로 다시 읽어 맞을 때까지 되풀이한다
        rx, tx = (int(x) for x in a.link.split(','))
        v = ((tx & 0xFFFF) << 16) | rx
        for _ in range(60):
            try:
                ctl(2, 0x0318, 1, [v], name='LINK_TUNE')
                if ctl(1, 0x0318, 1, name='LINK_TUNE read') == [v]:
                    break
            except SystemExit:
                pass
        else:
            raise SystemExit('FAIL LINK_TUNE을 쓰지 못함')
        del errors[:]                         # 맞추는 동안 생긴 응답 오류는 시험 결과가 아니다

    # 1. 정보, MIG 보정
    e0 = len(errors)
    ctl.wr(0x0104, 8, 'RUN = 0, ERR_CLEAR')  # 앞 실행이 RUN = 1이나 오류 7로 끝났을 수 있다
    info = ctl.rd(0x0000, 4, 'info')
    for i, (e, n) in enumerate([(0x534E_4E58, 'ID'), (0x0001_0000, 'VERSION'), (E, 'N_ENTRY'), (N_ON_CHIP, 'N_ON_CHIP')]):
        expect(info[i], e, n)
    expect(ctl.rd(0x0100, 1, 'STATUS')[0] & 0xD, 0x4, 'STATUS (RUN 0, MIG_CALIB 1, ERR 0)')
    print(f'run   1) 정보·STATUS(MIG 보정 1), 오류 {len(errors) - e0}', flush=True)

    # 2. 모델 적재
    e0, c0 = len(errors), time.time()
    for m in range(N_MOD):
        load_model(ctl, g, m)
    summary['load_s'] = round(time.time() - c0, 2)
    print(f'run   2) 모델 {N_MOD}개 Ethernet 적재·확인, 제어 packet {ctl.n}, {summary["load_s"]} s, 오류 {len(errors) - e0}', flush=True)

    # 3. 설정, PNU 표(시나리오 값: offset m, N_REG 2, 나머지 0), SOFT_RESET, RUN
    e0 = len(errors)
    st = [1024, N_MOD, 0, SB, DEADLINE, MARGIN]
    ctl(2, 0x0300, 6, st, name='settings write')
    for i, w in enumerate(ctl.rd(0x0300, 6, 'settings read')):
        expect(w, st[i], f'setting {i}')
    ctl(2, 0x1000, N_MOD, list(range(N_MOD)), name='OFFSET_TABLE')
    ctl(2, 0x1100, N_MOD, [2] * N_MOD, name='N_REG')
    ctl(2, 0x1200, 3, [0] * 3, name='TAU_G, TAU_U, EG')
    ctl(2, 0x1400, 128, [0] * 128, name='LUT_G')
    for k in range(4):
        ctl(2, 0x2000 + 1024 * k, 256, [0] * 256, name='LUT_U')
    expect(ctl.rd(0x1000, 2, 'PNU table read') == [0, 0], True, 'PNU table reads 0 (write only)')
    ctl.wr(0x0104, 2, 'SOFT_RESET')
    expect(ctl.rd(0x0100, 1, 'STATUS after SOFT_RESET')[0], 0x6, 'STATUS after SOFT_RESET')
    ctl.wr(0x0104, 1, 'RUN')
    expect(ctl.rd(0x0100, 1, 'STATUS RUN')[0], 0x7, 'STATUS RUN')
    ctl.wr(0x0300, 512, 'N_TRACKS write while RUN')
    ctl.wr(0x0310, 1, 'DEADLINE_US write while RUN')
    s = ctl.rd(0x0300, 6, 'settings read while RUN')
    expect(s[0], 1024, 'N_TRACKS after write while RUN')
    expect(s[4], DEADLINE, 'DEADLINE_US after write while RUN')
    ctl(2, DDR, 8, [0x5555_0000 + i for i in range(8)], exp_st=2, name='DDR3 write while RUN')
    ctl(1, DDR, 8, exp_st=2, name='DDR3 read while RUN')
    for i, w in enumerate(ctl.rd(0x0400, 3, 'counters after SOFT_RESET')):
        expect(w, 0, f'counter {i} after SOFT_RESET')
    print(f'run   3) 설정·PNU 표 쓰기, SOFT_RESET, RUN = 1, RUN 중 설정·DDR3 쓰기 무시, 오류 {len(errors) - e0}', flush=True)

    # 4. 추론
    e0, c0 = len(errors), time.time()
    for t in range(nt):
        inf.do_t(t, rng)
        if t == 0 or t == nt - 1:
            print(f'run      t{t}: 결과 {inf.n_res}, 누적 오류 {len(errors) - e0}', flush=True)
    fpga_delay = sorted(inf.fpga_delay)
    summary.update(infer_s=round(time.time() - c0, 2), nreq=inf.nreq, n_res=inf.n_res, err_out=inf.err_out,
                   err_fld=inf.err_fld, batch_n=inf.n_bn[1:], late=inf.n_late,
                   t_done_minus_t_in_us={'min': fpga_delay[0], 'p50': fpga_delay[len(fpga_delay) // 2], 'max': fpga_delay[-1]})
    print(f'run   4) 추론 요청 {inf.nreq}, 결과 {inf.n_res} (DDR3 트랙 {n_ddr3}), out 불일치 {inf.err_out}, 필드 불일치 {inf.err_fld}, '
          f'batch_n 1: {inf.n_bn[1]}·2: {inf.n_bn[2]}, LATE {inf.n_late}, t_done − t_in {fpga_delay[0]}~{fpga_delay[-1]} µs, 오류 {len(errors) - e0}',
          flush=True)

    # 5. 끝: IDLE, RUN = 0, counter, DDR3 membrane potential
    e0 = len(errors)
    wait_idle(ctl, 'after last result')
    ctl.wr(0x0104, 0, 'RUN = 0')
    expect(ctl.rd(0x0100, 1, 'STATUS stop')[0], 0x6, 'STATUS stop')
    c, wb, sb, bz, stl = counters(ctl, 'counters')
    for got, exp, n in [(c[0], inf.nreq, 'REQ_IN'), (c[1], 0, 'REQ_DROP'), (c[2], inf.nreq, 'RES_OUT'), (c[3], inf.n_late, 'LATE'),
                        (c[5], inf.n_bn[2] // 2 + inf.n_bn[1], 'BATCHES (results)'), (wb, c[6] * 131648, 'WEIGHT_BYTES'),
                        (c[7], 0, 'SAT_COUNT'), (sb, n_ddr3 * (2 * nt - 1) * 1088, 'STATE_BYTES')]:
        expect(got, exp, n)
    if not 1 <= c[4] <= N_VEC:
        err(f'MAX_PENDING {c[4]}')
    if not N_MOD * nt <= c[5] <= N_VEC * nt:
        err(f'BATCHES {c[5]}')
    if nt == T:
        expect(bz, CMP_BUSY_SIM, 'CMP_BUSY (tb_sys)')
    if stl == 0:
        err('CMP_STALL 0')
    summary['counters'] = dict(REQ_IN=c[0], REQ_DROP=c[1], RES_OUT=c[2], LATE=c[3], MAX_PENDING=c[4], BATCHES=c[5],
                               MODEL_LOADS=c[6], SAT_COUNT=c[7], WEIGHT_BYTES=wb, STATE_BYTES=sb, CMP_BUSY=bz, CMP_STALL=stl)
    print('run   counter: ' + ', '.join(f'{k} {v}' for k, v in summary['counters'].items()), flush=True)
    expect(ctl.rd(0x0500, 2, 'ERR after run')[0], 0, 'ERR_CODE after run')
    mis = 0
    for v, e in g.e.items():
        a0 = DDR + SB + 0x800 * trk(v)
        w = ctl.rd(a0, 256, 'state read 0') + ctl.rd(a0 + 1024, 16, 'state read 1')
        img = sum(x << 32 * i for i, x in enumerate(w))
        for r in range(ROWS):
            for j in range(2 if r == 44 else 16):
                mis += ((img >> 12 * (16 * r + j)) & 0xFFF) != ((e[r] >> (640 + 16 * j)) & 0xFFF)
    if mis:
        err(f'DDR3 membrane potential mismatch {mis}')
    summary['state_mismatch'] = mis
    print(f'run   5) IDLE 뒤 RUN = 0, counter, DDR3 트랙 {len(g.e)}개 membrane potential DDR3 창 읽기 불일치 {mis}, 오류 {len(errors) - e0}',
          flush=True)

    # 5b. slot을 둘씩 맞바꿔 쓰고 SOFT_RESET. 어느 entry가 cache에 있든 무효화되지 않으면 옛 weight로 계산해 어긋난다
    e0 = len(errors)
    for m in range(0, N_MOD, 2):
        wr_slot(ctl, g, m, m + 1)
        wr_slot(ctl, g, m + 1, m)
        inf.mmap[m], inf.mmap[m + 1] = m + 1, m
    ctl.wr(0x0104, 2, 'SOFT_RESET after run')
    now = ctl.rd(0x0200, 1, 'NOW_US after SOFT_RESET')[0]
    if now > 100_000:
        err(f'5b: NOW_US {now} after SOFT_RESET')
    for i, w in enumerate(ctl.rd(0x0400, 16, 'counters after SOFT_RESET 2')):
        expect(w, 0, f'counter {i} after SOFT_RESET 2')
    ctl.wr(0x0310, 1, 'DEADLINE_US 1')
    inf.dl = 1
    inf.reset_stats()
    ctl.wr(0x0104, 1, 'RUN 5b')
    inf.do_t(0, rng)
    wait_idle(ctl, '5b')
    ctl.wr(0x0104, 0, 'RUN = 0 5b')
    c, wb, sb, bz, stl = counters(ctl, 'counters 5b')
    if c[0] != N_VEC or c[1] != 0 or c[2] != N_VEC:
        err(f'5b: REQ_IN {c[0]} REQ_DROP {c[1]} RES_OUT {c[2]}')
    if inf.n_late != N_VEC or c[3] != N_VEC:
        err(f'5b: LATE flags {inf.n_late}, counter {c[3]}, expected {N_VEC}')
    if c[5] < N_MOD or c[5] != inf.n_bn[2] // 2 + inf.n_bn[1]:
        err(f'5b: BATCHES {c[5]}')
    if c[6] < N_MOD or wb != c[6] * 131648:
        err(f'5b: MODEL_LOADS {c[6]} WEIGHT_BYTES {wb}')
    if c[7] != 0 or sb != n_ddr3 * 1088:
        err(f'5b: SAT_COUNT {c[7]} STATE_BYTES {sb}')
    ctl.wr(0x0310, DEADLINE, 'DEADLINE_US restore')
    inf.dl = DEADLINE
    print(f'run   5b) slot 둘씩 맞바꿈 + SOFT_RESET(NOW_US {now} µs), DEADLINE 1 µs: 결과 {inf.n_res}, out 불일치 {inf.err_out}, '
          f'LATE {inf.n_late}, MODEL_LOADS {c[6]}, BATCHES {c[5]}, 오류 {len(errors) - e0}', flush=True)

    # 6. 오류
    e0 = len(errors)
    ctl.wr(0x0104, 1, 'RUN again')
    inf.s.sendto(req_bytes(5, 1, 45, 0, 0), (FPGA_IP, 5000))
    time.sleep(0.05)
    e = ctl.rd(0x0500, 2, 'ERR model 45')
    expect(e[0], 3, 'ERR_CODE model 45')
    expect(e[1], 5, 'ERR_INFO model 45')
    expect(ctl.rd(0x0100, 1, 'STATUS ERR')[0], 0xF, 'STATUS ERR')
    inf.s.sendto(bytes(range(100)), (FPGA_IP, 5000))
    time.sleep(0.05)
    e = ctl.rd(0x0500, 2, 'ERR after 100 B')
    expect(e[0], 3, 'ERR_CODE kept')
    expect(e[1], 5, 'ERR_INFO kept')
    ctl.wr(0x0104, 9, 'ERR_CLEAR')
    expect(ctl.rd(0x0500, 2, 'ERR cleared') == [0, 0], True, 'ERR cleared')
    expect(ctl.rd(0x0100, 1, 'STATUS cleared')[0], 0x7, 'STATUS cleared')
    inf.s.sendto(bytes(range(100)), (FPGA_IP, 5000))
    time.sleep(0.05)
    e = ctl.rd(0x0500, 2, 'ERR 100 B')
    expect(e[0], 7, 'ERR_CODE 100 B')
    expect(e[1], 100, 'ERR_INFO 100 B')
    expect(ctl.rd(0x0404, 1, 'REQ_DROP')[0], 1, 'REQ_DROP after model 45')
    ctl.wr(0x0104, 0, 'RUN = 0 end')
    inf.s.settimeout(0.2)
    try:
        r = inf.s.recv(2048)
        err(f'unexpected result {r.hex()}')
    except socket.timeout:
        pass
    print(f'run   6) 오류: model 45 → 3·트랙 5, 100 B datagram은 첫 오류 유지, ERR_CLEAR, 100 B → 7·100, 오류 {len(errors) - e0}', flush=True)

    summary.update(ctl_packets=ctl.n, errors=len(errors), first_errors=errors[:30], total_s=round(time.time() - t0, 1),
                   result='PASS' if not errors else 'FAIL')
    print(f'run   끝: 제어 packet {ctl.n}, {summary["total_s"]} s, 오류 {len(errors)}, NT {nt}')
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, 'w') as f:
            json.dump(summary, f, indent=1, ensure_ascii=False)
    print('PASS' if not errors else f'FAIL 오류 {len(errors)}개')
    return 0 if not errors else 1


if __name__ == '__main__':
    sys.exit(main())
