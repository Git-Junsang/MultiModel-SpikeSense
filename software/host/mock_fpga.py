#!/usr/bin/env python3
"""mock_fpga.py — FPGA mock. software/host의 mmss_host를 장치 없이 시험한다 (06 §4·§7)

UDP <ip>:5000(추론 요청)과 5001(제어 packet)을 받는다. 주소 공간은 정보·상태·제어·시각·설정·counter·오류·PNU 표·DDR3 창만 흉내 낸다.
결과는 snn_int8과 같은 정수 연산으로 바로 계산한다(membrane potential 12 bit 저장, RESET_STATE면 0부터).
weight는 Host가 DDR3 창에 적재한 slot을 02 §6 배치로 읽는다. 그래서 모델 image 적재가 틀리면 결과도 틀린다.
시각은 실제 FPGA가 아니다. NOW_US는 시작 5초 뒤 2^32에서 되감기게 둔다(Host의 32 bit 시각 처리 확인).
  --drop TRACK:SEQ        그 추론 요청을 결과 없이 버린다(state도 바꾸지 않는다)
  --delay TRACK:SEQ:MS    그 결과를 MS ms 늦게 보낸다
RUN이 1 → 0이 되면 받은 추론 요청·결과(requests.npz), 설정·PNU 표·counter(regs.json), DDR3 내용(ddr3.bin)을 --out에 쓴다.

    python3 software/host/mock_fpga.py --out <폴더> [--ip 127.0.0.1] [--drop 31:40] [--delay 7:70:45]
"""
import argparse
import json
import os
import select
import socket
import struct
import threading
import time

import numpy as np

SLOT, USED = 0x40000, 131648
LAYERS = [(0x5C0, 384, 40, 6), (0x41C0, 256, 384, 4), (0x1C1C0, 64, 256, 1), (0x201C0, 2, 64, 1)]   # 시작, 출력, 입력, 64-lane 묶음
PSTART = (0, 768, 1280, 1408)                                                                          # params 안 layer 시작 B
DDR3_BASE, DDR3_SIZE = 0x8000_0000, 40 * SLOT


def decode_slot(b):
    """slot 앞 131,648 B → snn_int8.quantize와 같은 꼴의 layer 목록(W [출력, 입력] int8, beta, vth)"""
    q = []
    for (st, n_out, n_in, g), ps in zip(LAYERS, PSTART):
        w = np.frombuffer(b, np.int8, n_out * n_in, st)
        if g > 1:              # (g × n_in + i) × 64 + j = W[64g + j][i]
            W = w.reshape(g, n_in, 64).transpose(0, 2, 1).reshape(n_out, n_in)
        elif n_out == 64:      # i × 64 + j = W3[j][i]
            W = w.reshape(n_in, 64).T
        else:                  # k × 64 + j = W4[k][j]
            W = w.reshape(n_out, n_in)
        p = np.frombuffer(b, np.uint8, 2 * n_out, ps).reshape(n_out, 2).astype(np.int64)
        q.append(dict(Wt=W.astype(np.float64).T, beta=p[:, 0], vth=p[:, 1]))
    return q


def step(q, mem, x):
    """추론 하나씩(행마다 트랙). snn_int8.forward의 한 timestep, 저장 12 bit. 반환 layer 4 reset 뒤 membrane potential"""
    h = x.astype(np.float64)
    for i, l in enumerate(q):
        acc = np.rint(h @ l['Wt']).astype(np.int64)
        v = np.clip(((l['beta'] * mem[i]) >> 8) + (acc >> 7 if i == 0 else acc), -32768, 32767)
        spk = v >= l['vth']
        post = v - spk * l['vth']
        mem[i] = np.clip(post, -2048, 2047)
        h = spk.astype(np.float64)
    return post


class Mock:
    def __init__(self, a):
        self.a, self.out = a, a.out
        self.drop = {tuple(map(int, s.split(':'))) for s in a.drop}
        self.delay = {tuple(map(int, s.split(':')[:2])): int(s.split(':')[2]) for s in a.delay}
        self.base = (1 << 32) - self.raw_us() - 5_000_000
        self.ddr3, self.ddr3_hi = bytearray(DDR3_SIZE), 0
        self.cfg = {0x300 + 4 * i: 0 for i in range(7)}
        self.pnu, self.run, self.err = {}, 0, (0, 0)
        self.reset()
        self.rs = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.rs.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 << 20)
        self.rs.bind((a.ip, 5000))
        self.cs = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.cs.bind((a.ip, 5001))

    def raw_us(self):
        return time.monotonic_ns() // 1000

    def now(self):
        return (self.raw_us() + self.base) & 0xFFFF_FFFF

    def reset(self):                                    # SOFT_RESET: counter, state, 읽은 모델
        self.cnt = dict(REQ_IN=0, REQ_DROP=0, RES_OUT=0, BATCHES=0)
        self.state, self.models, self.log, self.res, self.dg = {}, {}, [], [], 0

    # ---------------- 제어 packet (06 §7.6) ----------------
    def rd(self, addr):
        regs = {0x0: 0x534E_4E58, 0x4: 0x0001_0000, 0x8: 4, 0xC: 768, 0x104: self.run, 0x200: self.now(),
                0x100: self.run | 2 | 4 | (8 if self.err[0] else 0), 0x500: self.err[0], 0x504: self.err[1]}
        regs.update(self.cfg)
        regs.update({0x400: self.cnt['REQ_IN'], 0x404: self.cnt['REQ_DROP'], 0x408: self.cnt['RES_OUT'], 0x414: self.cnt['BATCHES']})
        return regs.get(addr, 0)

    def wr(self, addr, v):
        if addr == 0x104:
            if v & 2:
                self.reset()
            if v & 8:
                self.err = (0, 0)
            if self.run and not v & 1:
                self.dump()
            self.run = v & 1
        elif self.run:
            return                                      # RUN = 1이면 설정·PNU 표 쓰기는 무시
        elif addr in self.cfg:
            self.cfg[addr] = v
        elif 0x1000 <= addr < 0x3000:
            self.pnu[addr] = v

    def control(self, p, src):
        if len(p) < 12 or p[0] != 0x5C:
            return
        op, tag, addr, cnt = p[1], *struct.unpack_from('<HIH', p, 2)
        st, data = 0, b''
        if not 1 <= cnt <= 256 or (op == 2 and len(p) != 12 + 4 * cnt) or op not in (1, 2):
            st = 3
        elif addr % 4:
            st = 1
        elif addr >= DDR3_BASE:
            a = addr - DDR3_BASE
            if addr % 32 or a + 4 * cnt > DDR3_SIZE:
                st = 1
            elif cnt % 8:
                st = 3
            elif self.run:
                st = 2
            elif op == 2:
                self.ddr3[a:a + 4 * cnt] = p[12:12 + 4 * cnt]
                self.ddr3_hi = max(self.ddr3_hi, a + 4 * cnt)
            else:
                data = bytes(self.ddr3[a:a + 4 * cnt])
        elif op == 2:
            for i, v in enumerate(struct.unpack_from(f'<{cnt}I', p, 12)):
                self.wr(addr + 4 * i, v)
        else:
            data = struct.pack(f'<{cnt}I', *(self.rd(addr + 4 * i) for i in range(cnt)))
        self.cs.sendto(p[:10] + struct.pack('<H', st) + data, src)

    # ---------------- 추론 요청 (06 §4) ----------------
    def error(self, code, info):
        self.cnt['REQ_DROP'] += 1
        if not self.err[0]:
            self.err = (code, info)

    def requests(self, p, src):
        t_rx = self.now()
        n = len(p) // 64
        if not self.run:
            return
        if len(p) % 64 or not 1 <= n <= 23:
            return self.error(7, len(p))
        self.dg += 1
        ok = []
        for i in range(n):
            r = p[64 * i:64 * i + 64]
            tr, seq, m, th, ne = struct.unpack_from('<HHB', r, 2) + struct.unpack_from('<II', r, 8)
            x = np.frombuffer(r, np.uint8, 40, 16)
            self.log.append((tr, seq, m, r[1], th, ne, self.dg, n, t_rx, r[7] == 0 and r[56:64] == bytes(8), *x))
            if r[0] != 0xA5:
                self.error(1, self.cnt['REQ_IN'] + self.cnt['REQ_DROP'])
            elif tr >= self.cfg[0x300]:
                self.error(2, tr)
            elif m >= self.cfg[0x304]:
                self.error(3, tr)
            elif x.max() > 127:
                self.error(4, tr)
            elif (tr, seq) in self.drop:
                self.cnt['REQ_DROP'] += 1
                self.res.append((tr, seq, 0, 0, 1))
            else:
                self.cnt['REQ_IN'] += 1
                ok.append((tr, seq, m, r[1] & 1, th, x))
        for m in sorted({o[2] for o in ok}):
            grp = [o for o in ok if o[2] == m]
            if m not in self.models:
                self.models[m] = decode_slot(bytes(self.ddr3[m * SLOT:m * SLOT + USED]))
            q = self.models[m]
            for o in grp:
                if o[3] or o[0] not in self.state:
                    self.state[o[0]] = [np.zeros(l['vth'].size, np.int64) for l in q]
            mem = [np.stack([self.state[o[0]][i] for o in grp]) for i in range(4)]
            t0 = self.now()
            out = step(q, mem, np.stack([o[5] for o in grp]))
            self.cnt['BATCHES'] += 1
            for j, o in enumerate(grp):
                self.state[o[0]] = [mem[i][j] for i in range(4)]
                pkt = struct.pack('<HHBBHIIIIhhI', o[0], o[1], m, o[3], len(grp), o[4], t_rx, t0, self.now(), *out[j], 0)
                d = self.delay.get((o[0], o[1]))
                self.res.append((o[0], o[1], int(out[j][0]), int(out[j][1]), 0))
                self.cnt['RES_OUT'] += 1
                if d:
                    threading.Timer(d / 1000, self.rs.sendto, (pkt, src)).start()
                else:
                    self.rs.sendto(pkt, src)

    def dump(self):
        os.makedirs(self.out, exist_ok=True)
        L = np.array(self.log, np.int64).reshape(-1, 50)
        R = np.array(self.res, np.int64).reshape(-1, 5)
        names = 'track seq model flags t_host_us n_expect dgram dgram_n t_rx_us pad_ok'.split()
        np.savez(os.path.join(self.out, 'requests.npz'), x=L[:, 10:].astype(np.uint8),
                 res=R, **{k: L[:, i] for i, k in enumerate(names)})
        with open(os.path.join(self.out, 'regs.json'), 'w') as f:
            json.dump(dict(cfg=self.cfg, pnu=self.pnu, cnt=self.cnt, err=self.err), f)
        with open(os.path.join(self.out, 'ddr3.bin'), 'wb') as f:
            f.write(self.ddr3[:self.ddr3_hi])

    def serve(self):
        print('ready', flush=True)
        while True:
            for s in select.select([self.rs, self.cs], [], [])[0]:
                p, src = s.recvfrom(2048)
                (self.requests if s is self.rs else self.control)(p, src)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--out', required=True)
    ap.add_argument('--ip', default='127.0.0.1')
    ap.add_argument('--drop', action='append', default=[])
    ap.add_argument('--delay', action='append', default=[])
    Mock(ap.parse_args()).serve()
